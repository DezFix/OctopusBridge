# -*- coding: utf-8 -*-
"""Щупальце RPG Maker MV/MZ: CDP-внедрение в NW.js-процесс игры.

Запуск: Game.exe с --remote-debugging-port (файлы игры не трогаем).
Перевод: JS-пейлоад перехватывает вывод текста движка и просит перевод
через CDP-канал. Читы/состояние: прямой Runtime.evaluate.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time

from app.core import process as proc
from app.transport.cdp import browser
from app.transport.cdp.client import CDPClient, CDPError
from app.core.tentacles.cdp_base import CDPTentacle
from app.engines.rpgmaker.textwrap import (DEFAULT_WINDOW_WIDTH,
                                            DEFAULT_VISIBLE_ROWS,
                                            BASE_FONT_SIZE, MIN_FONT_SIZE,
                                            MAX_WRAP_RETRIES)

# Кандидаты портов для сканирования
SCAN_PORTS = [9222, 9229, 9333] + list(range(9000, 9101)) + \
    list(range(26000, 26051))

# признак страницы RPG Maker / NW.js
_RPGM_PROBE = ("!!(window.$gameMessage || window.$dataSystem || "
               "(window.nw && window.nw.Window))")

# ── JS-пейлоад: перехват текста + автосинхронизация состояния ──
PAYLOAD = r"""
if (!window.__octopus.rpgm) {
window.__octopus.rpgm = true;
window.__octopus.clickTp = false;
window.__octopus_hooksReady = false;

// ── кириллица: @font-face с unicode-range ──
try {
  const s = document.createElement("style");
  s.textContent =
    '@font-face{font-family:"rmmz-mainfont";src:local("Arial");' +
    'unicode-range:U+0400-04FF,U+0500-052F,U+2DE0-2DFF,U+A640-A69F}' +
    '@font-face{font-family:"mplus-1m-regular";src:local("Arial");' +
    'unicode-range:U+0400-04FF,U+0500-052F}' +
    '@font-face{font-family:"GameFont";src:local("Arial");' +
    'unicode-range:U+0400-04FF,U+0500-052F}';
  document.head.appendChild(s);
} catch (e) {}

const cache = new Map();
const requested = new Set();
let waitingWindows = new Set();
let _autoStateTimer = null;

window.__octopus_addToCache = function (pairs) {
  for (const k of Object.keys(pairs)) {
    cache.set(k, pairs[k]);
    requested.add(k);
  }
};

function autoSendState() {
  if (_autoStateTimer) return;
  _autoStateTimer = setTimeout(() => { _autoStateTimer = null; sendState(); }, 500);
}

// ---------- перевод ----------
function translatable(text) {
  if (typeof text !== "string") return false;
  if (text.trim().length < 1) return false;
  if (!/[^\s\\{}\[\]0-9]/.test(text)) return false;
  return true;
}

function requestBackground(text, win) {
  if (!translatable(text) || requested.has(text)) {
    if (win) waitingWindows.add(win);
    return;
  }
  requested.add(text);
  if (win) waitingWindows.add(win);
  window.__octopus_translate(text).then((tr) => {
    cache.set(text, tr);
    refreshMessageIfShowing(text);
    const wins = waitingWindows;
    waitingWindows = new Set();
    wins.forEach((w) => { try { if (w.refresh) w.refresh(); } catch (e) {} });
  });
}

// --- перенос строк переведённого текста под реальную ширину окна ---
const BASE_FONT_SIZE = %d;
const MIN_FONT_SIZE = %d;
const MAX_WRAP_RETRIES = %d;

function stripCodesForWidth(s) {
  return s
    .replace(/\\[Vv]\[\d+\]/g, "9999")
    .replace(/\\[Nn]\[\d+\]/g, "ИмяИмя")
    .replace(/\\[Pp]\[\d+\]/g, "ИмяИмя")
    .replace(/\\[Cc]\[\d+\]/g, "")
    .replace(/\\[Ii]\[\d+\]/g, "  ")
    .replace(/\\[G$.|!<>^]/g, "");
}

function wrapLine(win, text, maxWidth) {
  const tokens = text.split(/(\s+)/);
  const lines = [];
  let line = "";
  for (const tok of tokens) {
    const candidate = line + tok;
    if (win.textWidth(stripCodesForWidth(candidate)) > maxWidth && line.trim()) {
      lines.push(line.replace(/\s+$/, ""));
      line = tok.replace(/^\s+/, "");
    } else {
      line = candidate;
    }
  }
  if (line) lines.push(line.replace(/\s+$/, ""));
  return lines;
}

function rewrapMessage(win) {
  const original = $gameMessage._texts.map((t) => cache.get(t) || t);
  const full = original.join("\n");
  const maxWidth = win.innerWidth || (win.contents ? win.contents.width : 800);
  const visibleRows = $gameMessage._numVisibleRows || 4;

  let fontSize = BASE_FONT_SIZE;
  let wrapped = [];
  let retries = 0;
  if (win.contents) win.contents.fontSize = fontSize;
  for (;;) {
    wrapped = [];
    full.split("\n").forEach((line) => wrapped.push(...wrapLine(win, line, maxWidth)));
    if (wrapped.length <= visibleRows || fontSize <= MIN_FONT_SIZE) break;
    if (++retries >= MAX_WRAP_RETRIES) break;
    fontSize -= 2;
    if (win.contents) win.contents.fontSize = fontSize;
  }
  $gameMessage._texts = wrapped;
}

let _refreshing = false;
function refreshMessageIfShowing(original) {
  if (_refreshing) return;
  _refreshing = true;
  try {
    const scene = SceneManager._scene;
    const w = scene && scene._messageWindow;
    if (w && w.isOpen() && $gameMessage._texts.includes(original)) {
      w.startMessage();
    }
  } catch (e) {}
  _refreshing = false;
}

function wrapText(text, win) {
  if (!translatable(text)) return text;
  const t = cache.get(text);
  if (t !== undefined) return t;
  requestBackground(text, win);
  return text;
}

// ---------- полный снимок состояния ----------
function collectItems(kind, db) {
  const out = [];
  if (!db) return out;
  for (let i = 1; i < db.length; i++) {
    const it = db[i];
    if (it && it.name) {
      out.push({ kind: kind, id: it.id, name: it.name,
                 count: $gameParty.numItems(it) });
    }
  }
  return out;
}

function _has(name) {
  return typeof window[name] !== "undefined" && !!window[name];
}

window.__octopus_collectState = function () {
  const state = {
    type: "state",
    gold: _has("$gameParty") ? $gameParty.gold() : 0,
    mapId: _has("$gameMap") ? $gameMap.mapId() : 0,
    inBattle: _has("$gameParty") ? $gameParty.inBattle() : false,
    party: [],
    items: [],
    variables: _has("$gameVariables") ? $gameVariables._data.slice(1) : [],
    switches: _has("$gameSwitches") ? $gameSwitches._data.slice(1) : []
  };
  if (_has("$gameActors") && _has("$gameParty")) {
    $gameActors._data.forEach((a) => {
      if (!a) return;
      state.party.push({
        id: a.actorId(), name: a.name(), level: a.level,
        hp: a.hp, mp: a.mp, mhp: a.mhp, mmp: a.mmp, exp: a.currentExp(),
        className: a.currentClass() ? a.currentClass().name : "",
        inParty: $gameParty.members().includes(a),
        params: [0, 1, 2, 3, 4, 5, 6, 7].map((i) => a.param(i))
      });
    });
    state.items = collectItems("item", window.$dataItems)
      .concat(collectItems("weapon", window.$dataWeapons))
      .concat(collectItems("armor", window.$dataArmors));
  }
  return state;
};

function sendState() {
  try { window.__octopus.send(window.__octopus_collectState()); } catch (e) {}
}

// ---------- установка хуков ----------
function installHooks() {
  const _gameMessageAdd = Game_Message.prototype.add;
  Game_Message.prototype.add = function (text) {
    if (translatable(text) && !cache.has(text)) requestBackground(text, null);
    _gameMessageAdd.call(this, text);
  };

  const _startMessage = Window_Message.prototype.startMessage;
  Window_Message.prototype.startMessage = function () {
    rewrapMessage(this);
    _startMessage.call(this);
  };

  const _terminateMessage = Window_Message.prototype.terminateMessage;
  Window_Message.prototype.terminateMessage = function () {
    if (this.contents) this.contents.fontSize = BASE_FONT_SIZE;
    _terminateMessage.call(this);
  };

  const _drawTextEx = Window_Base.prototype.drawTextEx;
  Window_Base.prototype.drawTextEx = function (text, x, y, width, maxLines) {
    return _drawTextEx.call(this, wrapText(text, this), x, y, width, maxLines);
  };

  const _drawText = Window_Base.prototype.drawText;
  Window_Base.prototype.drawText = function (text, x, y, width, align) {
    return _drawText.call(this, wrapText(text, this), x, y, width, align);
  };

  // телепорт по Ctrl+клику
  const _sceneMapUpdate = Scene_Map.prototype.update;
  Scene_Map.prototype.update = function () {
    _sceneMapUpdate.call(this);
    if (window.__octopus.clickTp && TouchInput.isTriggered() &&
        Input.isPressed("control")) {
      const x = $gameMap.canvasToMapX(TouchInput.x);
      const y = $gameMap.canvasToMapY(TouchInput.y);
      if ($gameMap.isValid(x, y)) $gamePlayer.locate(x, y);
    }
  };

  // автосинхронизация состояния
  const _origGameVarsSetValue = Game_Variables.prototype.setValue;
  Game_Variables.prototype.setValue = function(id, value) {
    _origGameVarsSetValue.call(this, id, value);
    autoSendState();
  };

  const _origGameSwitchesSetValue = Game_Switches.prototype.setValue;
  Game_Switches.prototype.setValue = function(id, value) {
    _origGameSwitchesSetValue.call(this, id, value);
    autoSendState();
  };

  const _origGainGold = Game_Party.prototype.gainGold;
  Game_Party.prototype.gainGold = function(amount) {
    _origGainGold.call(this, amount);
    autoSendState();
  };

  const _origLoseGold = Game_Party.prototype.loseGold;
  Game_Party.prototype.loseGold = function(amount) {
    _origLoseGold.call(this, amount);
    autoSendState();
  };

  const _origReserveTransfer = Game_Player.prototype.reserveTransfer;
  Game_Player.prototype.reserveTransfer = function(mapId, x, y, d, fadeType) {
    _origReserveTransfer.call(this, mapId, x, y, d, fadeType);
    autoSendState();
  };

  const _origSetHp = Game_BattlerBase.prototype.setHp;
  Game_BattlerBase.prototype.setHp = function(hp) {
    _origSetHp.call(this, hp);
    autoSendState();
  };

  const _origSetMp = Game_BattlerBase.prototype.setMp;
  Game_BattlerBase.prototype.setMp = function(mp) {
    _origSetMp.call(this, mp);
    autoSendState();
  };

  const _origChangeLevel = Game_Actor.prototype.changeLevel;
  Game_Actor.prototype.changeLevel = function(level, showEffect) {
    _origChangeLevel.call(this, level, showEffect);
    autoSendState();
  };

  const _origChangeExp = Game_Actor.prototype.changeExp;
  Game_Actor.prototype.changeExp = function(exp, showEffect) {
    _origChangeExp.call(this, exp, showEffect);
    autoSendState();
  };

  const _origGainItem = Game_Party.prototype.gainItem;
  Game_Party.prototype.gainItem = function(item, amount, includeEquip) {
    _origGainItem.call(this, item, amount, includeEquip);
    autoSendState();
  };

  window.__octopus_hooksReady = true;
  sendState();
}

const _enginePoll = setInterval(function () {
  if (typeof Game_Message === "undefined" ||
      typeof Window_Base === "undefined" ||
      typeof Window_Message === "undefined" ||
      typeof Scene_Map === "undefined" ||
      typeof Game_Variables === "undefined" ||
      typeof Game_Switches === "undefined" ||
      typeof Game_Party === "undefined" ||
      typeof Game_Player === "undefined" ||
      typeof Game_BattlerBase === "undefined" ||
      typeof Game_Actor === "undefined") return;
  clearInterval(_enginePoll);
  try {
    installHooks();
    console.log("[octopus] RPGM hooks installed");
  } catch (e) {
    console.warn("[octopus] hook install failed: " + e);
  }
}, 400);
}
""" % (BASE_FONT_SIZE, MIN_FONT_SIZE, MAX_WRAP_RETRIES)


# ── Bulk-перевод $data ──

PRETRANSLATE_FIELDS = {
    "Actors": ["name", "nickname", "profile"],
    "Items": ["name", "description"],
    "Weapons": ["name", "description"],
    "Armors": ["name", "description"],
    "Skills": ["name", "description", "message1", "message2"],
    "Enemies": ["name"],
    "Classes": ["name"],
    "States": ["name", "message1", "message2", "message3", "message4"],
    "System": ["gameTitle", "currencyUnit"],
    "Troops": ["name"],
}

_EXTRACT_DATA_JS = """(function(){
var names = %s;
var result = {};
for (var i = 0; i < names.length; i++) {
  var key = '$data' + names[i];
  if (typeof window[key] !== 'undefined') result[names[i]] = window[key];
}
return JSON.stringify(result);
})()""" % json.dumps(list(PRETRANSLATE_FIELDS))

_CYR_RE = None


def _worth_translating(text: str) -> bool:
    global _CYR_RE
    if _CYR_RE is None:
        _CYR_RE = re.compile("[А-яЁё]")
    if len(text.strip()) <= 2 or _CYR_RE.search(text):
        return False
    return any(ch.isalpha() for ch in text)


class RpgMakerTentacle(CDPTentacle):
    key = "rpgmaker"
    title = "RPG Maker (CDP)"
    PAYLOAD = PAYLOAD

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._cache: dict[str, str] = {}
        self._cache_path: str | None = None
        self._cache_dirty = False
        from PySide6.QtCore import QTimer
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(3000)
        self._save_timer.timeout.connect(self._flush_cache)

    # ── запуск ──
    def launch(self, target: str) -> bool:
        exe = target
        if os.path.isdir(target):
            exe = os.path.join(target, "Game.exe")
        if not os.path.isfile(exe):
            self.error.emit(f"Не найден исполняемый файл игры: {exe}")
            return False
        port = browser.free_port()
        game_dir = os.path.dirname(exe)
        try:
            self._proc = subprocess.Popen(
                [exe, f"--remote-debugging-port={port}"],
                cwd=game_dir)
        except OSError as e:
            self.error.emit(f"Не удалось запустить игру: {e}")
            return False
        self._pid = self._proc.pid
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
        ok = self._connect_page(port, url_hint=".html", wait=5.0)
        if ok:
            exe = proc.exe_of(pid)
            if exe:
                self._load_cache(os.path.dirname(exe))
        return ok

    def set_port_hint(self, port: int):
        self._port_hint = port

    # ── кэш перевода ──
    def _load_cache(self, game_dir: str):
        self._cache_path = os.path.join(game_dir, ".translation_cache.json")
        try:
            with open(self._cache_path, encoding="utf-8") as f:
                self._cache = json.load(f)
            self.log.emit(f"Кэш перевода: {len(self._cache)} строк.")
        except (OSError, json.JSONDecodeError):
            self._cache = {}
        self._save_timer.start()

    def _save_cache(self):
        self._cache_dirty = True

    def _flush_cache(self):
        if not self._cache_dirty or not self._cache_path:
            return
        self._cache_dirty = False
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def detach(self):
        self._flush_cache()
        self._save_timer.stop()
        self._proc = None
        super().detach()

    def _on_translate_request(self, msg: dict):
        original = msg.get("text", "")
        translation = self.translate(original)
        if original and translation and translation != original:
            self._cache[original] = translation
        self._save_cache()
        mid = msg.get("id")
        expr = ("window.__octopus_onTranslation(" +
                json.dumps(mid) + ", " + json.dumps(translation,
                                                    ensure_ascii=False) + ")")
        try:
            self._client.evaluate(expr)
        except Exception:
            pass
        self.text_seen.emit(original, translation)

    def translate(self, text: str) -> str:
        if not text:
            return text
        if not self._translate_fn:
            return text
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        return super().translate(text)

    # ── bulk-перевод $data ──
    def _after_attach(self):
        import threading
        threading.Thread(target=self._pretranslate_worker,
                         daemon=True, name="RpgmPretranslate").start()

    def _pretranslate_worker(self):
        try:
            self._pretranslate()
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"Bulk-перевод $data: {e}")

    def _pretranslate(self):
        ok, raw = self.evaluate(_EXTRACT_DATA_JS, timeout=30)
        if not ok or not raw:
            return
        try:
            data = json.loads(raw)
        except ValueError:
            return
        locations: list[tuple[str, int, str, str]] = []
        seen: set[str] = set()
        for type_name, fields in PRETRANSLATE_FIELDS.items():
            entries = data.get(type_name)
            if not isinstance(entries, list):
                continue
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                for field in fields:
                    text = entry.get(field)
                    if isinstance(text, str) and text and \
                            _worth_translating(text) and text not in seen:
                        seen.add(text)
                        locations.append((type_name, idx, field, text))
        if not locations:
            return
        pairs: dict[str, str] = {}
        for _obj, _idx, _field, text in locations:
            if not self.is_attached():
                return
            tr = self.translate(text)
            if tr and tr != text:
                pairs[text] = tr
        if not pairs:
            return
        lines = []
        for type_name, idx, field, text in locations:
            tr = pairs.get(text)
            if not tr:
                continue
            obj = f"$data{type_name}"
            lines.append(f"{obj}[{idx}] && ({obj}[{idx}][{json.dumps(field)}]"
                         f" = {json.dumps(tr)});")
        for i in range(0, len(lines), 100):
            if not self.is_attached():
                return
            self.evaluate("\n".join(lines[i:i + 100]), timeout=30)
        self.evaluate(f"window.__octopus_addToCache({json.dumps(pairs)})",
                      timeout=30)
        self.log.emit(
            f"Bulk-перевод: {len(lines)} полей $data, {len(pairs)} строк.")

    # ── состояние ──
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
        return self.request_state()

    def set_variable(self, name: str, value) -> bool:
        if name.startswith("var:"):
            return self.send_cheat("var_set", index=int(name[4:]),
                                   value=value)
        if name.startswith("switch:"):
            return self.send_cheat("switch_set", index=int(name[7:]),
                                   value=bool(value))
        return False

    def send_cheat(self, cmd: str, **kwargs) -> bool:
        expr = self._cheat_expr(cmd, **kwargs)
        if expr is None:
            self.cheat_ack.emit(cmd, False, "unknown cmd", "")
            return False
        ok, val = self.evaluate(expr)
        if not ok:
            time.sleep(0.5)
            ok, val = self.evaluate(expr)
        self.cheat_ack.emit(cmd, ok, "" if ok else str(val),
                            json.dumps(val) if ok else "")
        return ok

    @staticmethod
    def _cheat_expr(cmd: str, **kwargs) -> str | None:
        js = json.dumps
        if cmd == "gold_set":
            return f"$gameParty._gold = {int(kwargs['value'])}"
        if cmd == "gold_add":
            return f"$gameParty.gainGold({int(kwargs['value'])})"
        if cmd == "var_set":
            return ("$gameVariables.setValue("
                    f"{int(kwargs['index'])}, {js(kwargs['value'])})")
        if cmd == "switch_set":
            v = "true" if kwargs["value"] else "false"
            return f"$gameSwitches.setValue({int(kwargs['index'])}, {v})"
        if cmd == "heal":
            return ("$gameParty.members().forEach("
                    "a => { a.setHp(a.mhp); a.setMp(a.mmp); }), 'healed'")
        if cmd == "speed":
            return f"$gamePlayer.setMoveSpeed({int(kwargs['value'])})"
        if cmd == "through":
            v = "true" if kwargs["value"] else "false"
            return f"$gamePlayer.setThrough({v})"
        if cmd == "click_tp":
            v = "true" if kwargs["value"] else "false"
            return f"window.__octopus.clickTp = {v}"
        if cmd == "teleport":
            return ("$gamePlayer.reserveTransfer("
                    f"{int(kwargs['mapId'])}, {int(kwargs['x'])}, "
                    f"{int(kwargs['y'])}, 0, 0), 'teleported'")
        if cmd == "win_battle":
            return ("(() => { if (!$gameParty.inBattle()) "
                    "throw new Error('сейчас нет боя'); "
                    "$gameTroop.members().forEach("
                    "e => { if (e.isAlive()) e.die(); }); "
                    "return 'won'; })()")
        if cmd == "give_item":
            kind = str(kwargs.get("kind", ""))
            db = {"weapon": "$dataWeapons", "armor": "$dataArmors"}.get(
                kind, "$dataItems")
            return ("(() => { const it = " + db + f"[{int(kwargs['id'])}]; "
                    "if (!it) throw new Error('нет такого предмета'); "
                    f"$gameParty.gainItem(it, {int(kwargs.get('count', 1))}, "
                    "true); return it.name; })()")
        if cmd == "open_menu":
            return ("SceneManager.push(Scene_Menu), 'menu_opened'")
        if cmd == "open_items":
            return ("SceneManager.push(Scene_Item), 'items_opened'")
        if cmd == "open_skills":
            return ("SceneManager.push(Scene_Skill), 'skills_opened'")
        if cmd == "open_equip":
            return ("SceneManager.push(Scene_Equip), 'equip_opened'")
        if cmd == "open_status":
            return ("SceneManager.push(Scene_Status), 'status_opened'")
        if cmd == "open_save":
            return ("SceneManager.push(Scene_Save), 'save_opened'")
        if cmd == "open_load":
            return ("SceneManager.push(Scene_Load), 'load_opened'")
        if cmd == "open_options":
            return ("SceneManager.push(Scene_Options), 'options_opened'")
        if cmd == "open_gameend":
            return ("SceneManager.push(Scene_GameEnd), 'gameend_opened'")
        if cmd == "actor_set":
            field = str(kwargs["field"])
            fid = int(kwargs["actorId"])
            val = kwargs["value"]
            ops = {
                "level": f"a.changeLevel({int(val)}, false)",
                "hp": f"a.setHp({int(val)})",
                "mp": f"a.setMp({int(val)})",
                "exp": f"a.changeExp({js(val)}, false)",
            }
            op = ops.get(field)
            if not op:
                return None
            return ("(() => { const a = $gameActors.actor(" + str(fid) +
                    "); if (!a) throw new Error('нет такого героя'); "
                    + op + "; return a.name(); })()")
        return None

    def game_pid(self) -> int | None:
        if self._proc and self._proc.poll() is None:
            return self._proc.pid
        return self._pid if (self._pid and proc.pid_exists(self._pid)) \
            else self._pid


# ── Поиск порта ──

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
        if _port_is_rpgm_game(port, pid):
            return port
    return 0


def _port_is_rpgm_game(port: int, pid: int) -> bool:
    target = browser.pick_page_target(port, ".html")
    if not target:
        return False
    client = CDPClient()
    if not client.connect(target["webSocketDebuggerUrl"]):
        return False
    try:
        client.call("Runtime.enable")
        ok, val = client.evaluate(_RPGM_PROBE)
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
        return len(proc.find_game_processes("rpgmaker")) <= 1
    except CDPError:
        return False
    finally:
        client.close()
