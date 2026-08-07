# -*- coding: utf-8 -*-
"""Щупальце TyranoScript: CDP-внедрение в NW.js-процесс игры.

Запуск: Game.exe (NW.js-обёртка) с --remote-debugging-port — файлы игры
не трогаем. Перевод: JS-пейлоад наблюдает за DOM-текстом движка
(#tyrano_base) и заменяет его переводами через CDP-канал. Переменные
Tyrano (kag.variables / kag.tmp) доступны для чит-вкладок.

Для браузерной игры без exe живого подключения нет: пользователю
предлагается запустить через Launch (см. error в launch).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time

from app.core import process as proc
from app.transport.cdp import browser
from app.transport.cdp.client import CDPClient, CDPError
from app.core.tentacles.cdp_base import CDPTentacle

# Кандидаты портов для сканирования (как у RPG Maker)
SCAN_PORTS = [9222, 9229, 9333] + list(range(9000, 9101)) + \
    list(range(26000, 26051))

# признак страницы Tyrano
_TYRANO_PROBE = ("!!(window.kag && window.kag.variables) || "
                 "!!(document.querySelector('#tyrano_base'))")

# ── JS-пейлоад: перевод DOM-текста + переменные ──
PAYLOAD = r"""
if (!window.__octopus.tyrano) {
window.__octopus.tyrano = true;

const cache = new Map();
const inflight = new Set();
const done = new Set();          // уже переведённые строки (значения)
const settle = new Map();        // стабилизация текста перед запросом
let enabled = true;              // перевод вкл/выкл (мост шлёт статус)
const SETTLE_MS = 300;
const HAS_LETTER_RE = /[A-Za-z\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF\u3040-\u30FF\u31F0-\u31FF\u3400-\u9FFF\uAC00-\uD7A3\uFF66-\uFF9F]/;
const CYR_RE = /[А-яЁё]/;

window.__octopus_addToCache = function (pairs) {
  for (const k of Object.keys(pairs)) {
    cache.set(k, pairs[k]);
    inflight.delete(k);
    done.add(pairs[k]);
  }
  prune();
  window.translateDOM();
};

// минимум 2 символа: одиночные каны в процессе набора текста
// (печатная машинка) не переводим — honyaku галлюцинирует на них
function tr(text) {
  if (typeof text !== "string") return false;
  const t = text.trim();
  if (t.length < 2 || CYR_RE.test(t)) return false;
  return HAS_LETTER_RE.test(t);
}

// Скип (перемотка): во время скипа строки мелькают мгновенно — не
// сканируем DOM и не ставим таймеры стабилизации впустую. Строки,
// пропущенные при перемотке, не теряются: при следующем обычном
// показе они пройдут через translateDOM заново.
function isSkip() {
  try {
    if (typeof kag !== "undefined" && kag.config && kag.config.skip) {
      return true;
    }
  } catch (e) {}
  try {
    return !!document.body.classList.contains("tyrano_skip");
  } catch (e) {
    return false;
  }
}

function prune() {
  while (cache.size > 30000) cache.delete(cache.keys().next().value);
  while (done.size > 60000) done.delete(done.values().next().value);
}

// ── единицы перевода ──
// Строки диалогов: p внутри .message_inner (движок печатает текст
// посимвольно в span.current_span — переводим ЦЕЛУЮ строку, а не узлы).
// Прочий текст (меню, UI): отдельные текстовые узлы вне .message_inner.
function walkText(root) {
  const nodes = [];
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      const pe = n.parentElement;
      if (!pe) return NodeFilter.FILTER_REJECT;
      const tag = pe.tagName;
      if (tag === "SCRIPT" || tag === "STYLE" || tag === "TEXTAREA" ||
          tag === "IFRAME") return NodeFilter.FILTER_REJECT;
      if (pe.closest(".message_inner")) return NodeFilter.FILTER_REJECT;
      if (n.textContent.trim() && tr(n.textContent)) {
        return NodeFilter.FILTER_ACCEPT;
      }
      return NodeFilter.FILTER_REJECT;
    }
  }, false);
  while (w.nextNode()) { nodes.push(w.currentNode); }
  return nodes;
}

function messageUnits(root) {
  const units = [];
  const blocks = root.querySelectorAll(".message_inner");
  blocks.forEach(function (inner) {
    const ps = inner.querySelectorAll("p");
    if (ps.length) {
      ps.forEach(function (p) { units.push(p); });
    } else {
      units.push(inner);
    }
  });
  return units;
}

// применяем перевод, только если текст не изменился (перематывание,
// набор текста) — иначе устаревший ответ не вносим
function applyToUnit(unit, s, trText) {
  if (trText === undefined || trText === s || !unit.isConnected) return;
  if (unit.textContent.trim() !== s) return;
  if (unit.nodeType === 3) {            // текстовый узел (UI)
    unit.textContent = trText;
    return;
  }
  // строку сообщения заменяем внутри span движка (каркас не трогаем),
  // иначе следующий символ движка сломает вёрстку
  const sp = unit.querySelector(".current_span") || unit.querySelector("span");
  if (sp && sp.textContent.trim() === s) {
    sp.textContent = trText;
  } else {
    unit.textContent = trText;
  }
}

function requestUnit(unit, s) {
  if (!enabled || isSkip() || inflight.has(s) || settle.has(s)) return;
  // ждём, пока текст не перестанет меняться: при перематывании и наборе
  // посимвольно не дёргаем переводчик. Таймер НЕ перезапускаем — в живой
  // сцене мутации идут постоянно; если проверка не прошла, следующий
  // проход поставит таймер заново
  settle.set(s, setTimeout(function () {
    settle.delete(s);
    if (inflight.has(s) || !unit.isConnected ||
        unit.textContent.trim() !== s) return;
    inflight.add(s);
    window.__octopus_translate(s).then(function (r) {
      inflight.delete(s);
      if (r !== s) {
        cache.set(s, r);
        done.add(r);
        prune();
      }
      applyToUnit(unit, s, r);
    });
  }, SETTLE_MS));
}

window.translateDOM = function () {
  if (!enabled || isSkip()) return;
  const root = document.querySelector("#tyrano_base") || document.body;
  if (!root) return;
  messageUnits(root).forEach(function (unit) {
    const s = unit.textContent.trim();
    if (!tr(s) || done.has(s)) return;
    if (cache.has(s)) {
      const v = cache.get(s);
      applyToUnit(unit, s, v);
      done.add(v);
      return;
    }
    requestUnit(unit, s);
  });
  walkText(root).forEach(function (n) {
    const s = n.textContent.trim();
    if (!tr(s) || done.has(s)) return;
    if (cache.has(s)) {
      const v = cache.get(s);
      applyToUnit(n, s, v);
      done.add(v);
      return;
    }
    requestUnit(n, s);
  });
};

let obsTimer = null;
function startObs() {
  const t = document.querySelector("#tyrano_base") || document.body;
  if (!t) return;
  new MutationObserver(function () {
    clearTimeout(obsTimer);
    obsTimer = setTimeout(window.translateDOM, 120);
  }).observe(t, { childList: true, subtree: true, characterData: true });
}

// статус перевода от моста: при выключенном переводе не сканируем DOM
// и не шлём запросы (выключенный перевод раньше гонял setInterval +
// MutationObserver и CDP-канал впустую)
window.__octopus_setEnabled = function (v) {
  enabled = !!v;
  if (enabled) window.translateDOM();
};

// подстраховка: если мутации прекратились, а строка не переведена —
// периодический проход это починит (запросы повторно не идут)
setInterval(function () { window.translateDOM(); }, 2500);

// ── переменные Tyrano ──
// %user и &system лежат в kag.variables, временные tf. — в kag.tmp.
window.__octopus_collectState = function () {
  const s = { type: "state", engine: "tyrano", variables: {}, variablesFlat: {} };
  try {
    if (typeof kag !== "undefined") {
      const kv = kag.variables || {};
      const tmp = kag.tmp || {};
      const src = {};
      for (const k of Object.keys(kv)) src[k] = kv[k];
      for (const k of Object.keys(tmp)) src["tf." + k] = tmp[k];
      s.variables = JSON.parse(JSON.stringify(src));
    }
    const flat = {};
    (function fl(o, p) {
      for (const k in o) {
        const n = p ? p + "." + k : k;
        const v = o[k];
        if (v && typeof v === "object" && !Array.isArray(v)) fl(v, n);
        else flat[n] = v;
      }
    })(s.variables, "");
    s.variablesFlat = flat;
  } catch (e) {}
  return s;
};

function sendState() {
  try { window.__octopus.send(window.__octopus_collectState()); } catch (e) {}
}

// ── установка хуков после готовности движка ──
(function init() {
  const poll = setInterval(function () {
    if (typeof kag === "undefined" && !document.querySelector("#tyrano_base")) {
      return;
    }
    clearInterval(poll);
    try {
      startObs();
      setTimeout(window.translateDOM, 300);
      sendState();
      console.log("[octopus] Tyrano hooks installed");
    } catch (e) {
      console.warn("[octopus] Tyrano hook install failed: " + e);
    }
  }, 400);
})();
}
"""

_CYR_RE = re.compile("[А-яЁё]")


def _worth_translating(text: str) -> bool:
    if len(text.strip()) <= 2 or _CYR_RE.search(text):
        return False
    return any(ch.isalpha() for ch in text)


class TyranoTentacle(CDPTentacle):
    key = "tyrano"
    title = "TyranoScript (CDP)"
    PAYLOAD = PAYLOAD

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._game_dir: str = ""
        self._cache: dict[str, str] = {}
        self._cache_path: str | None = None
        self._cache_dirty = False
        self._bulk_active = False
        from PySide6.QtCore import QTimer
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(3000)
        self._save_timer.timeout.connect(self._flush_cache)

    # ── запуск ──
    def launch(self, target: str) -> bool:
        exe = target
        game_dir = target
        if os.path.isdir(target):
            game_dir = target
            exe = os.path.join(target, "Game.exe")
            if not os.path.isfile(exe):
                # некоторые сборки TyranoBuilder: index.html в корне без exe
                for cand in ("TyranoPlayer.exe", "nw.exe", "nwjs.exe"):
                    p = os.path.join(target, cand)
                    if os.path.isfile(p):
                        exe = p
                        break
        if not os.path.isfile(exe):
            self.error.emit(
                f"Не найден исполняемый файл игры: {exe}\n"
                "Tyrano-игра без exe (браузерная) поддерживается только "
                "в файловом режиме перевода.")
            return False
        port = browser.free_port()
        try:
            self._proc = subprocess.Popen(
                [exe, f"--remote-debugging-port={port}"],
                cwd=game_dir)
        except OSError as e:
            self.error.emit(f"Не удалось запустить игру: {e}")
            return False
        self._pid = self._proc.pid
        self._game_dir = game_dir
        self.log.emit(f"Игра запущена (pid {self._pid}), отладка :{port}.")
        if not self._connect_page(port, url_hint=".html", wait=30.0):
            self.detach()
            return False
        self._load_cache(game_dir)
        return True

    def attach(self, pid: int) -> bool:
        port = getattr(self, "_port_hint", 0) or probe_game_port(pid)
        if not port:
            self.error.emit(
                "Отладочный порт не найден: игра запущена без "
                "--remote-debugging-port. Запустите её через OctopusBridge.")
            return False
        self._pid = pid
        exe = proc.exe_of(pid)
        self._game_dir = os.path.dirname(exe) if exe else ""
        ok = self._connect_page(port, url_hint=".html", wait=5.0)
        if ok and exe:
            self._load_cache(os.path.dirname(exe))
        return ok

    def set_port_hint(self, port: int):
        self._port_hint = port

    # ── кэш перевода ──
    def _load_cache(self, game_dir: str):
        from app.core.translate.game_cache import CACHE_FILENAME, \
            load_game_cache
        self._cache_path = os.path.join(game_dir, CACHE_FILENAME)
        loaded = load_game_cache(game_dir, "tyrano")
        # выкидываем мусор из старых сессий (одиночные каны и т.п. —
        # до введения _worth_translating они попадали в кэш)
        self._cache = {k: v for k, v in loaded.items()
                       if _worth_translating(k)}
        if len(self._cache) != len(loaded):
            self.log.emit(
                f"Кэш перевода: {len(self._cache)} строк "
                f"(очищено мусора: {len(loaded) - len(self._cache)}).")
        else:
            self.log.emit(f"Кэш перевода: {len(self._cache)} строк.")
        self._save_timer.start()

    def _flush_cache(self):
        if not self._cache_dirty or not self._cache_path:
            return
        self._cache_dirty = False
        from app.core.translate.game_cache import save_game_cache
        save_game_cache(os.path.dirname(self._cache_path), "tyrano",
                        self._cache)

    def detach(self):
        self._bulk_active = False
        self._flush_cache()
        self._save_timer.stop()
        self._proc = None
        super().detach()

    # ── перезагрузка страницы: JS-кэш пейлоада пустеет ──
    def _on_event(self, method: str, params: dict):
        # Tyrano перезагружает страницу часто (титул, загрузка сейва) —
        # в новом документе кэш Map пейлоада пуст, и одни и те же строки
        # запрашиваются заново. Заливаем наш кэш в новую страницу.
        if method == "Page.frameNavigated":
            threading.Thread(target=self._repush_worker, daemon=True,
                             name="TyranoCacheRepush").start()
            return
        super()._on_event(method, params)

    def _repush_worker(self):
        try:
            for _attempt in range(15):
                if not self.is_attached():
                    return
                ok, ready = self.evaluate(
                    "typeof window.__octopus_addToCache === 'function'")
                if ok and ready is True:
                    break
                time.sleep(1.0)
            if not self.is_attached():
                return
            if self._push_cache():
                self.log.emit(
                    f"Кэш перевода передан в игру "
                    f"({len(self._cache)} строк).")
        except Exception:  # noqa: BLE001
            pass

    def _push_cache(self) -> bool:
        """Заливает Python-кэш в JS-пейлоад (идемпотентно), по 400 пар."""
        if not self.is_attached() or not self._cache:
            return False
        items = list(self._cache.items())
        for i in range(0, len(items), 400):
            if not self.is_attached():
                return False
            chunk = dict(items[i:i + 400])
            ok, _val = self.evaluate(
                "window.__octopus_addToCache("
                f"{json.dumps(chunk, ensure_ascii=False)})",
                timeout=30)
            if not ok:
                return False
        return True

    def _on_translate_request(self, msg: dict):
        original = msg.get("text", "")
        # одиночные каны/мусор с типаю посимвольно не переводим:
        # honyaku на них галлюцинирует, и мусор оседает в кэше/TM
        if _worth_translating(original):
            translation = self.translate(original)
            if original and translation and translation != original:
                self._cache[original] = translation
                self._cache_dirty = True
        else:
            translation = original
        mid = msg.get("id")
        expr = ("window.__octopus_onTranslation(" +
                json.dumps(mid) + ", " + json.dumps(translation,
                                                    ensure_ascii=False) + ")")
        try:
            self._client.evaluate(expr)
        except Exception:  # noqa: BLE001
            pass
        self.text_seen.emit(original, translation)

    def translate(self, text: str) -> str:
        if not self._translation_enabled or not text \
                or not self._translate_fn:
            return text
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        return super().translate(text)

    def set_translation_enabled(self, enabled: bool):
        super().set_translation_enabled(enabled)
        # JS-пейлоад: при выключенном переводе не сканировать DOM и
        # не слать запросы впустую
        if self.is_attached():
            self.evaluate(
                "window.__octopus_setEnabled && "
                f"window.__octopus_setEnabled({json.dumps(bool(enabled))})")

    # ── bulk-перевод файлов при подключении ──
    def _after_attach(self):
        self._bulk_active = True
        threading.Thread(target=self._pretranslate_worker,
                         daemon=True, name="TyranoPretranslate").start()

    def _pretranslate_worker(self):
        try:
            self._pretranslate()
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"Bulk-перевод .ks: {e}")

    def _pretranslate(self):
        from app.core.tyrano import parser
        if not self._game_dir:
            return
        # сразу заливаем уже переведённое: пока bulk-перевод идёт,
        # живые строки будут отвечаться из кэша без запросов к движку
        try:
            self._push_cache()
        except Exception:  # noqa: BLE001
            pass
        try:
            entries = parser.extract(self._game_dir)
        except Exception:  # noqa: BLE001
            return
        # honyaku грузит CPU — если игру закрыли, останавливаемся сразу,
        # а не после перевода всех строк
        def alive() -> bool:
            return self._bulk_active and self.is_attached()

        pairs: dict[str, str] = {}
        for e in entries:
            if not alive():
                return
            text = e.original
            if not _worth_translating(text):
                continue
            cached = self._cache.get(text)
            if cached is not None:
                tr = cached
            elif self._translation_enabled and self._translate_fn:
                # прямой вызов мимо _LIVE_EXECUTOR: bulk-перевод тысяч
                # строк не должен забивать общий пул воркеров, из-за
                # которого живой перевод ждёт до 12с (игра виснет)
                try:
                    tr = self._translate_fn(text)
                except Exception:  # noqa: BLE001
                    tr = text
            else:
                tr = text
            if tr and tr != text:
                pairs[text] = tr
        if not pairs:
            return
        # переведённое в bulk тоже сохраняем в кэш-файл — иначе после
        # перезапуска игры он не отражает работу, а push повторяет запросы
        self._cache.update(pairs)
        self._cache_dirty = True
        if not alive():
            return
        # большие порции могут не пролезть в один evaluate — шлём по 400
        items = list(pairs.items())
        for i in range(0, len(items), 400):
            if not alive():
                return
            chunk = dict(items[i:i + 400])
            self.evaluate(
                f"window.__octopus_addToCache("
                f"{json.dumps(chunk, ensure_ascii=False)})",
                timeout=30)
        self.log.emit(f"Bulk-перевод: {len(pairs)} строк из .ks в кэше.")

    # ── состояние/переменные ──
    def request_state(self) -> bool:
        ok, val = self.evaluate(
            "JSON.stringify(window.__octopus_collectState "
            "? window.__octopus_collectState() : null)")
        if ok and isinstance(val, str) and val:
            try:
                self.state_received.emit(json.loads(val))
                return True
            except ValueError:
                pass
        return False

    def request_vars(self) -> bool:
        return self.send_cheat("get_vars")

    def set_variable(self, name: str, value) -> bool:
        return self.send_cheat("var_set", name=name, value=value)

    def send_cheat(self, cmd: str, **kwargs) -> bool:
        expr = self._cheat_expr(cmd, **kwargs)
        if expr is None:
            self.cheat_ack.emit(cmd, False, "unknown cmd", "")
            return False
        ok, val = self.evaluate(expr)
        if not ok:
            time.sleep(0.5)
            ok, val = self.evaluate(expr)
        if cmd == "get_vars" and ok:
            try:
                raw = json.loads(val) if isinstance(val, str) else val
                items = raw.get("variablesFlat") or {}
                self.vars_received.emit(
                    [{"name": k, "value": v} for k, v in items.items()])
            except (ValueError, AttributeError):
                pass
        self.cheat_ack.emit(cmd, ok, "" if ok else str(val),
                            json.dumps(val, ensure_ascii=False) if ok else "")
        return ok

    @staticmethod
    def _cheat_expr(cmd: str, **kwargs) -> str | None:
        js = json.dumps
        if cmd == "get_vars":
            return ("JSON.stringify(window.__octopus_collectState "
                    "? window.__octopus_collectState() : null)")
        if cmd == "var_set":
            name = str(kwargs["name"])
            value = kwargs["value"]
            # tf.x живёт в kag.tmp, остальное — в kag.variables
            target = "kag.tmp" if name.startswith("tf.") else "kag.variables"
            key = name[3:] if name.startswith("tf.") else name
            return ("(() => { if (typeof kag === 'undefined') "
                    f"throw new Error('kag not ready'); "
                    f"{target}[{js(key)}] = {js(value)}; "
                    "return JSON.stringify({ok:true}); })()")
        if cmd == "exec":
            return ("(() => { try { return JSON.stringify({ok:true, "
                    "value:(function(){" + kwargs["code"] + "})()}); } "
                    "catch(e) { return JSON.stringify({ok:false, "
                    "error:String(e)}); } })()")
        return None

    def game_pid(self) -> int | None:
        if self._proc and self._proc.poll() is None:
            return self._proc.pid
        return self._pid if self._pid else None


# ── Поиск порта для attach ──

def probe_game_port(pid: int) -> int:
    exe = proc.exe_of(pid)
    game_dir = os.path.dirname(exe) if exe else ""
    port = proc.debug_port_from_cmdline(proc.cmdline_of(pid))
    if port:
        return port
    port = browser.port_from_devtools_file(exe, game_dir)
    if port:
        return port
    return _bruteforce_port(pid)


def _bruteforce_port(pid: int) -> int:
    candidates = browser.scan_ports(SCAN_PORTS)
    if not candidates:
        time.sleep(2.0)
        candidates = browser.scan_ports(SCAN_PORTS)
    for port in candidates:
        if _port_is_tyrano(port, pid):
            return port
    return 0


def _port_is_tyrano(port: int, pid: int) -> bool:
    target = browser.pick_page_target(port, ".html")
    if not target:
        return False
    client = CDPClient()
    if not client.connect(target["webSocketDebuggerUrl"]):
        return False
    try:
        client.call("Runtime.enable")
        ok, val = client.evaluate(_TYRANO_PROBE)
        if not (ok and val is True):
            return False
        try:
            info = client.call("SystemInfo.getProcessInfo", timeout=3)
            procs = info.get("processInfo") or []
            browser_pid = next((p.get("id") for p in procs
                                if p.get("type") == "browser"), None)
            if browser_pid is not None:
                return int(browser_pid) == int(pid)
        except CDPError:
            pass
        return True
    except CDPError:
        return False
    finally:
        client.close()
