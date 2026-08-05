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
const failed = new Set();  // строки, вернувшие identity/таймаут: не спамим
let waitingWindows = new Set();
let _autoStateTimer = null;

// ── ускорение игры: множитель updateMain (MV и MZ) ──
window.__octopus_gameSpeed = 1;
window.__octopus_setGameSpeed = function (n) {
  n = Math.max(1, Math.min(20, Math.floor(n || 1)));
  window.__octopus_gameSpeed = n;
  if (!window.__octopus_speedHooked &&
      typeof SceneManager !== "undefined" && SceneManager.updateMain) {
    try {
      const _obUpdateMain = SceneManager.updateMain;
      SceneManager.updateMain = function () {
        const k = window.__octopus_gameSpeed || 1;
        if (k > 1) {
          for (let i = 0; i < k; i++) {
            _obUpdateMain.call(this);
            // MV: Input.update вызывается один раз за кадр вне updateMain —
            // без синхронизации каждое нажатие срабатывает k раз (меню,
            // диалоги листаются кратно скорости). MZ: вызов идемпотентен.
            if (i < k - 1 &&
                typeof SceneManager.updateInputData === "function") {
              try { SceneManager.updateInputData(); } catch (e) {}
            }
          }
        } else {
          _obUpdateMain.call(this);
        }
      };
      window.__octopus_speedHooked = true;
    } catch (e) {}
  }
};

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
// Не отправляем: строки без единой буквы (символы, цифры, пустые) и
// одиночные кана-символы (кнопки кана-клавиатуры: ホ, ァ, ヴ) — это
// буквы, а не слова, перевода у них нет. «あらあら……」 — это уже слово,
// переводим.
const HAS_LETTER_RE = /[A-Za-z\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF\u3040-\u30FF\u31F0-\u31FF\u3400-\u9FFF\uAC00-\uD7A3\uFF66-\uFF9F]/;
const SINGLE_KANA_RE = /^[\u3040-\u30FF\u31F0-\u31FF\uFF65-\uFF9F]$/;

function translatable(text) {
  if (typeof text !== "string") return false;
  text = text.trim();
  if (text.length < 1) return false;
  if (SINGLE_KANA_RE.test(text)) return false;
  if (!HAS_LETTER_RE.test(text)) return false;
  return true;
}

// ── распознавание перемотки текста (скип) ──
// Пока игрок держит OK/листает диалоги мгновенно, переводить нечего:
// запросы лишь копятся в очереди и вешают приложение. Скипнутый текст
// пропускаем и при следующем обычном показе переведём заново.
function isFastForwarding(win) {
  try {
    if (win && win._showFast) return true;
    const scene = SceneManager._scene;
    if (!scene) return false;
    const mw = scene._messageWindow;
    if (mw && mw._showFast) return true;
    if (scene._scrollTextWindow && scene._scrollTextWindow.isFastForward &&
        scene._scrollTextWindow.isFastForward()) return true;
    if (scene._logWindow && scene._logWindow.isFastForward &&
        scene._logWindow.isFastForward()) return true;
    if (scene.isFastForward && scene.isFastForward()) return true;
  } catch (e) {}
  return false;
}

// Игрок хочет пролистать диалог: удержание OK или Ctrl — гейт «…» не
// должен его блокировать. _showFast не выставляется, пока страница
// заморожена — смотрим сырое состояние ввода.
function skipRequested(win) {
  if (isFastForwarding(win)) return true;
  try {
    if (typeof Input !== "undefined") {
      if (Input.isPressed("ok")) return true;
      if (Input.isPressed("control")) return true;
    }
  } catch (e) {}
  return false;
}

function requestBackground(text, win) {
  if (!translatable(text) || requested.has(text)) {
    if (win) waitingWindows.add(win);
    return;
  }
  if (isFastForwarding(win)) return;  // скип: перематываемый текст не переводим
  requested.add(text);
  if (win) waitingWindows.add(win);
  window.__octopus_translate(text).then((tr) => {
    if (tr !== text) {
      cache.set(text, tr);
    } else {
      // перевод приостановлен пользователем или не успел за таймаут
      // канала: identity не запоминаем (после включения переведём
      // заново), но помечаем «не удалось» — полл не будет долбить
      // повторными запросами каждые 150мс
      requested.delete(text);
      failed.add(text);
      setTimeout(() => { failed.delete(text); }, 30000);
    }
    refreshMessageIfShowing(text);
    const wins = waitingWindows;
    waitingWindows = new Set();
    wins.forEach((w) => {
      try { if (w.refresh && !w._octWaiting) w.refresh(); } catch (e) {}
    });
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

function rewrapMessage(win, hideMissing) {
  const original = $gameMessage._texts.map(
    (t) => (cache.has(t) ? cache.get(t)
            : (hideMissing ? "\u2026" : t)));
  const full = original.join("\n");
  // MV: innerWidth — метод, MZ: getter
  const maxWidth = typeof win.innerWidth === "function"
    ? win.innerWidth()
    : (win.innerWidth || (win.contents ? win.contents.width : 800));
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
    if (w && w.isOpen() && $gameMessage._texts.includes(original) &&
        !w._showFast && !w._octWaiting) {
      w.startMessage();
    }
  } catch (e) {}
  _refreshing = false;
}

// Окна, где оригинал показывать нельзя (перевод готовится за кадром):
// текстовые окна (ScrollText, BattleLog) — вместо оригинала «…»,
// которое заменяется переводом по мере готовности.
const HIDDEN_WINDOWS = ["Window_ScrollText", "Window_BattleLog"];

function isHiddenWindow(win) {
  if (!win) return false;
  if (win.__octHide) return true;
  return HIDDEN_WINDOWS.some((n) => typeof window[n] !== "undefined" &&
                                    win instanceof window[n]);
}

function wrapText(text, win) {
  if (!translatable(text)) return text;
  const t = cache.get(text);
  if (t !== undefined) return t;
  if (isHiddenWindow(win)) {
    requestBackground(text, win);
    return "\u2026";  // «…» вместо оригинала, потом подставится перевод
  }
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
function safePatch(target, patchFn) {
  // MV-совместимость: отсутствующая функция не ломает остальные хуки
  if (typeof target === "function") {
    try { patchFn(); } catch (e) {
      console.warn("[octopus] hook skip: " + e);
    }
  }
}

function installHooks() {
  safePatch(Game_Message.prototype.add, () => {
    const _gameMessageAdd = Game_Message.prototype.add;
    Game_Message.prototype.add = function (text) {
      if (translatable(text) && !cache.has(text)) requestBackground(text, null);
      _gameMessageAdd.call(this, text);
    };
  });

  // диалог «за кадром»: строки без перевода показываются как «…»,
  // продвижение по тексту (ввод/скип) блокируется, пока перевод не готов,
  // затем страница перезапускается с реальным переводом — оригинал никто
  // не увидит, лишний клик не нужен (игрок не успел уйти дальше).
  safePatch(Window_Message.prototype.startMessage, () => {
    const _startMessage = Window_Message.prototype.startMessage;
    const PENDING_TIMEOUT = 6000;
    const PENDING_POLL_MS = 150;
    Window_Message.prototype.startMessage = function () {
      const texts = ($gameMessage && $gameMessage._texts) || [];
      const missing = texts.filter(
        (t) => translatable(t) && !cache.has(t) && !failed.has(t));
      if (missing.length === 0) {
        this._octWaiting = false;
        this._octWaitToken = (this._octWaitToken || 0) + 1;
        rewrapMessage(this);
        return _startMessage.call(this);
      }
      // скип (удержание OK/Ctrl): гейт не держит — показываем что есть:
      // переводы для готового, оригиналы для остального
      if (skipRequested(this)) {
        this._octWaiting = false;
        this._octWaitToken = (this._octWaitToken || 0) + 1;
        rewrapMessage(this);
        return _startMessage.call(this);
      }
      // перевод ещё идёт: держим окно на первой странице с «…»
      if (this._octWaiting && this._octWaitToken) {
        return;  // полл уже активен, не дублируем
      }
      const win = this;
      win._octWaiting = true;
      win._octWaitToken = (win._octWaitToken || 0) + 1;
      win._octOriginals = texts.slice();  // оригиналы: _texts займут «…»
      const token = win._octWaitToken;
      const deadline = Date.now() + PENDING_TIMEOUT;
      try {
        missing.forEach((t) => requestBackground(t, win));
        rewrapMessage(win, true);
        _startMessage.call(win);
      } catch (e) {}
      if (typeof win.startWait === "function") win.startWait(PENDING_POLL_MS);
      // замораживаем перерисовку: пока перевод идёт, страница не должна
      // прокручиваться (скип/пауза в конце страницы не сработают)
      if (typeof win.updateMessage === "function") {
        win._octFrozenUpdate = win.updateMessage;
        win.updateMessage = function () {};
      }
      (function poll() {
        if (win._octWaitToken !== token || !win._octWaiting) return;
        // готовность проверяем по сохранённым оригиналам: текущие
        // $gameMessage._texts — уже плейсхолдеры «…», их в кэше нет
        const originals = win._octOriginals || [];
        const left = originals.filter(
          (t) => translatable(t) && !cache.has(t) && !failed.has(t));
        if (left.length === 0 || Date.now() > deadline || skipRequested(win)) {
          win._octWaiting = false;
          win._octWaitToken = (win._octWaitToken || 0) + 1;
          win._octOriginals = null;
          if (win._octFrozenUpdate) {
            win.updateMessage = win._octFrozenUpdate;
            win._octFrozenUpdate = null;
          }
          win._waitCount = 0;  // снимаем блокировку страницы
          try {
            // таймаут: непереведённое показываем оригиналом, а не «…»
            $gameMessage._texts = originals.slice();
            rewrapMessage(win, false);
            _startMessage.call(win);
          } catch (e) {}
          return;
        }
        if (typeof win.startWait === "function") win.startWait(PENDING_POLL_MS);
        try { left.forEach((t) => requestBackground(t, win)); } catch (e) {}
        setTimeout(poll, PENDING_POLL_MS);
      })();
    };
  });

  safePatch(Window_Message.prototype.terminateMessage, () => {
    const _terminateMessage = Window_Message.prototype.terminateMessage;
    Window_Message.prototype.terminateMessage = function () {
      this._octWaiting = false;
      this._octWaitToken = (this._octWaitToken || 0) + 1;
      this._octOriginals = null;
      if (this._octFrozenUpdate) {
        this.updateMessage = this._octFrozenUpdate;
        this._octFrozenUpdate = null;
      }
      if (this.contents) this.contents.fontSize = BASE_FONT_SIZE;
      _terminateMessage.call(this);
    };
  });

  safePatch(Window_Base.prototype.drawTextEx, () => {
    const _drawTextEx = Window_Base.prototype.drawTextEx;
    Window_Base.prototype.drawTextEx = function (text, x, y, width, maxLines) {
      return _drawTextEx.call(this, wrapText(text, this), x, y, width, maxLines);
    };
  });

  safePatch(Window_Base.prototype.drawText, () => {
    const _drawText = Window_Base.prototype.drawText;
    Window_Base.prototype.drawText = function (text, x, y, width, align) {
      return _drawText.call(this, wrapText(text, this), x, y, width, align);
    };
  });

  // телепорт по Ctrl+клику
  safePatch(Scene_Map.prototype.update, () => {
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
  });

  // автосинхронизация состояния
  safePatch(Game_Variables.prototype.setValue, () => {
    const _origGameVarsSetValue = Game_Variables.prototype.setValue;
    Game_Variables.prototype.setValue = function(id, value) {
      _origGameVarsSetValue.call(this, id, value);
      autoSendState();
    };
  });

  safePatch(Game_Switches.prototype.setValue, () => {
    const _origGameSwitchesSetValue = Game_Switches.prototype.setValue;
    Game_Switches.prototype.setValue = function(id, value) {
      _origGameSwitchesSetValue.call(this, id, value);
      autoSendState();
    };
  });

  safePatch(Game_Party.prototype.gainGold, () => {
    const _origGainGold = Game_Party.prototype.gainGold;
    Game_Party.prototype.gainGold = function(amount) {
      _origGainGold.call(this, amount);
      autoSendState();
    };
  });

  safePatch(Game_Party.prototype.loseGold, () => {
    const _origLoseGold = Game_Party.prototype.loseGold;
    Game_Party.prototype.loseGold = function(amount) {
      _origLoseGold.call(this, amount);
      autoSendState();
    };
  });

  safePatch(Game_Player.prototype.reserveTransfer, () => {
    const _origReserveTransfer = Game_Player.prototype.reserveTransfer;
    Game_Player.prototype.reserveTransfer = function(mapId, x, y, d, fadeType) {
      _origReserveTransfer.call(this, mapId, x, y, d, fadeType);
      autoSendState();
    };
  });

  safePatch(Game_BattlerBase.prototype.setHp, () => {
    const _origSetHp = Game_BattlerBase.prototype.setHp;
    Game_BattlerBase.prototype.setHp = function(hp) {
      _origSetHp.call(this, hp);
      autoSendState();
    };
  });

  safePatch(Game_BattlerBase.prototype.setMp, () => {
    const _origSetMp = Game_BattlerBase.prototype.setMp;
    Game_BattlerBase.prototype.setMp = function(mp) {
      _origSetMp.call(this, mp);
      autoSendState();
    };
  });

  safePatch(Game_Actor.prototype.changeLevel, () => {
    const _origChangeLevel = Game_Actor.prototype.changeLevel;
    Game_Actor.prototype.changeLevel = function(level, showEffect) {
      _origChangeLevel.call(this, level, showEffect);
      autoSendState();
    };
  });

  safePatch(Game_Actor.prototype.changeExp, () => {
    const _origChangeExp = Game_Actor.prototype.changeExp;
    Game_Actor.prototype.changeExp = function(exp, showEffect) {
      _origChangeExp.call(this, exp, showEffect);
      autoSendState();
    };
  });

  safePatch(Game_Party.prototype.gainItem, () => {
    const _origGainItem = Game_Party.prototype.gainItem;
    Game_Party.prototype.gainItem = function(item, amount, includeEquip) {
      _origGainItem.call(this, item, amount, includeEquip);
      autoSendState();
    };
  });

  window.__octopus_hooksReady = true;
  window.__octopus_setGameSpeed(window.__octopus_gameSpeed || 1);
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
    # Одноразовая миграция: старый кэш (Argos, ранние версии Honyaku)
    # содержит галлюцинации («Домой» вместо каны). Honyaku переводит эти
    # строки нормально, но пока запись в кэше — перевод не обновится.
    # Чистим артефакты.
    _LEGACY_ARTIFACTS = frozenset({"домой", "дома", "дом", "главная",
                                   "внутренний"})

    def _load_cache(self, game_dir: str):
        from app.core.translate.game_cache import CACHE_FILENAME, \
            load_game_cache
        self._cache_path = os.path.join(game_dir, CACHE_FILENAME)
        self._cache = load_game_cache(game_dir, "rpgmaker")
        bad = [k for k, v in self._cache.items()
               if isinstance(v, str) and
               v.strip().lower() in self._LEGACY_ARTIFACTS]
        for k in bad:
            del self._cache[k]
        if bad:
            self._cache_dirty = True
            self.log.emit(
                f"Кэш перевода: удалено {len(bad)} артефактов.")
        self.log.emit(f"Кэш перевода: {len(self._cache)} строк.")
        self._save_timer.start()

    def _save_cache(self):
        self._cache_dirty = True

    def _flush_cache(self):
        if not self._cache_dirty or not self._cache_path:
            return
        self._cache_dirty = False
        from app.core.translate.game_cache import save_game_cache
        save_game_cache(os.path.dirname(self._cache_path), "rpgmaker",
                        self._cache)

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
        if not self._translation_enabled or not text \
                or not self._translate_fn:
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
        if cmd == "game_speed":
            return f"window.__octopus_setGameSpeed({int(kwargs['value'])})"
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
            return ("(() => { if (typeof $gameParty === 'undefined' || "
                    "!$gameParty.inBattle()) "
                    "throw new Error('сейчас нет боя'); "
                    "const troop = $gameTroop; "
                    "troop.members().forEach("
                    "e => { if (e.isAlive()) e.die(); }); "
                    "if (troop.isAllDead()) BattleManager.processVictory(); "
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
