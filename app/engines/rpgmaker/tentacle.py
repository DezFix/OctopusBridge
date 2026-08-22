# -*- coding: utf-8 -*-
"""Щупальце RPG Maker MV/MZ — два профиля.

MZ (и Electron/asar-сборки MV): CDP-внедрение в NW.js-процесс игры,
запуск с --remote-debugging-port, Runtime.evaluate + JS-пейлоад.

MV (официальный десктопный рантайм): non-SDK NW.js без remote
debugging — канал через мост octopus_ob.js (HTTP-сервер внутри игры,
см. app.core.rpgmaker.mv_bridge). Весь API (evaluate/request_state/
apply_translation) прозрачно роутится через мост.
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
from app.core.rpgmaker import mv_bridge
from app.core.rpgmaker import variant as rpgm_variant

# Кандидаты портов для сканирования
SCAN_PORTS = [9222, 9229, 9333] + list(range(9000, 9101)) + \
    list(range(26000, 26051))

# признак страницы RPG Maker / NW.js
_RPGM_PROBE = ("!!(window.$gameMessage || window.$dataSystem || "
               "(window.nw && window.nw.Window))")

# ── JS-пейлоад: читы + автосинхронизация состояния ──
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

// ── ускорение игры: MV 1.6+/MZ — аккумулятор фиксированных шагов ──
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
        if (k <= 1) {
          _obUpdateMain.call(this);
          return;
        }
        if (typeof this._deltaTime === "number") {
          // MV 1.6+/MZ: движок сам догоняет время фиксированными шагами
          // (while по _accumulator). Уменьшаем шаг в k раз — за кадр
          // накрутится k тиков, а renderScene/requestUpdate отработают
          // один раз (в оригинале они вне цикла). НЕЛЬЗЯ звать
          // updateMain k раз: requestUpdate = requestAnimationFrame —
          // каждый вызов расписывает ещё кадр, рост экспоненциальный,
          // игра зависает и вылетает.
          const orig = this._deltaTime;
          this._deltaTime = orig / k;
          try {
            _obUpdateMain.call(this);
          } finally {
            this._deltaTime = orig;
          }
        } else {
          // древний MV без аккумулятора: k кадров, но requestUpdate
          // глушим (считаем), чтобы не расплодить rAF-кадры
          const obReq = SceneManager.requestUpdate;
          let reqs = 0;
          if (typeof obReq === "function") {
            SceneManager.requestUpdate = function () { reqs++; };
          }
          try {
            for (let i = 0; i < k; i++) _obUpdateMain.call(this);
          } finally {
            SceneManager.requestUpdate = obReq;
          }
          if (typeof obReq === "function" && reqs) obReq.call(this);
        }
      };
      window.__octopus_speedHooked = true;
    } catch (e) {}
  }
};

let _autoStateTimer = null;

function autoSendState() {
  if (_autoStateTimer) return;
  _autoStateTimer = setTimeout(() => { _autoStateTimer = null; sendState(); }, 500);
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
    playerX: _has("$gamePlayer") ? $gamePlayer.x : 0,
    playerY: _has("$gamePlayer") ? $gamePlayer.y : 0,
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
  if (typeof Scene_Map === "undefined" ||
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
"""

# ── JS-пейлоад: гибридный live-перевод (MV и MZ) ──
# Подменяет текст в рантайме через словарь original->translation,
# не трогая файлы игры. Работает и для зашифрованных/asar-сборок.
_TRANSLATION_PAYLOAD = r"""
if (!window.__octopus_trInit) {
  window.__octopus_trInit = true;
  window.__octopus_tr = {};

  window.__octopus_trApply = function (text) {
    if (typeof text !== "string" || text.length === 0) return text;
    var t = window.__octopus_tr[text];
    return (t === undefined || t === null) ? text : t;
  };

  window.__octopus_trInstall = function (obj) {
    if (obj) {
      for (var k in obj) {
        if (Object.prototype.hasOwnProperty.call(obj, k)) {
          window.__octopus_tr[k] = obj[k];
        }
      }
    }
    return Object.keys(window.__octopus_tr).length;
  };

  function trSafePatch(method, patchFn) {
    if (typeof method === "function") {
      try { patchFn(); } catch (e) {
        console.warn("[octopus] tr hook skip: " + e);
      }
    }
  }

  var _trPoll = setInterval(function () {
    if (typeof Window_Base === "undefined") return;
    clearInterval(_trPoll);
    // диалоги/сообщения: подменяем строку ДО раскрытия escape-кодов,
    // чтобы перевод сохранил \N[..] / \C[..] как есть
    trSafePatch(Window_Base.prototype.convertEscapeCharacters, function () {
      var obCvt = Window_Base.prototype.convertEscapeCharacters;
      Window_Base.prototype.convertEscapeCharacters = function (text) {
        return obCvt.call(this, window.__octopus_trApply(text));
      };
    });
    // имена акторов (меню, статусы, сообщения \N[x])
    trSafePatch(Game_Actor.prototype.name, function () {
      var obName = Game_Actor.prototype.name;
      Game_Actor.prototype.name = function () {
        return window.__octopus_trApply(obName.call(this));
      };
    });
    // имя текущей карты
    trSafePatch(Game_Map.prototype.displayName, function () {
      var obDName = Game_Map.prototype.displayName;
      Game_Map.prototype.displayName = function () {
        return window.__octopus_trApply(obDName.call(this));
      };
    });

    // ── перевод на уровне данных ──
    // Меню/предметы/скиллы/термины рисуются напрямую из таблиц $data*
    // мимо convertEscapeCharacters, поэтому проходим сами таблицы
    // в ПАМЯТИ и подменяем точные совпадения. Файлы игры не трогаем.
    // Команды событий ({code, parameters}) обходим по белому списку
    // ТОЛЬКО отображаемых позиций: комментарии 108/408 и скрипты
    // 355/655 плагины часто читают как теги — их не трогаем.
    var obDict = window.__octopus_tr;

    function obHas(s) {
      return Object.prototype.hasOwnProperty.call(obDict, s)
        && typeof obDict[s] === "string";
    }
    function obSubst(node, key) {
      var v = node[key];
      if (typeof v === "string" && obHas(v)) node[key] = obDict[v];
    }
    window.__octopus_trWalk = function (node, depth) {
      if (!node || typeof node !== "object" || depth > 12) return;
      if (Array.isArray(node)) {
        for (var ai = 0; ai < node.length; ai++) {
          var av = node[ai];
          if (av && typeof av === "object") {
            window.__octopus_trWalk(av, depth + 1);
          } else if (typeof av === "string") {
            if (obHas(av)) node[ai] = obDict[av];
          }
        }
        return;
      }
      // команда события? ({code:Number, parameters:Array})
      if (typeof node.code === "number"
          && Object.prototype.hasOwnProperty.call(node, "parameters")) {
        obWalkCmd(node);
        return;
      }
      for (var k in node) {
        if (!Object.prototype.hasOwnProperty.call(node, k)) continue;
        if (k === "note" || k === "meta") continue; // теги плагинов
        var v2 = node[k];
        if (v2 && typeof v2 === "object") {
          window.__octopus_trWalk(v2, depth + 1);
        } else {
          obSubst(node, k);
        }
      }
    };
    // белые списки: код команды -> индексы параметров с текстом
    var obTextCodes = {
      101: [4],   // заголовок диалога (имя говорящего)
      102: [0],   // выбор вариантов (массив строк)
      320: [1],   // сменить имя актора
      324: [1],   // сменить прозвище
      356: [0],   // MV-команда плагина (строка целиком)
      357: [3],   // MZ-команда плагина (аргументы)
      401: [0],   // строки диалога
      402: [1],   // ветка выбора (When)
      405: [0]    // прокручиваемый текст
    };
    function obWalkCmd(cmd) {
      var idxs = obTextCodes[cmd.code];
      if (!idxs) return;
      var ps = cmd.parameters || [];
      for (var q = 0; q < idxs.length; q++) {
        var i = idxs[q];
        if (i >= ps.length) continue;
        var v = ps[i];
        if (typeof v === "string") {
          if (obHas(v)) ps[i] = obDict[v];
        } else if (v && typeof v === "object") {
          // выбор 102[0]: массив строк; аргументы 357: вложенные структуры
          window.__octopus_trWalk(v, 0);
        }
      }
    }

    var obDbTables = ["$dataActors", "$dataClasses", "$dataSkills",
      "$dataItems", "$dataWeapons", "$dataArmors", "$dataEnemies",
      "$dataTroops", "$dataStates", "$dataSystem", "$dataMapInfos",
      "$dataCommonEvents"];
    function obRefreshData() {
      for (var i = 0; i < obDbTables.length; i++) {
        try { window.__octopus_trWalk(window[obDbTables[i]], 0); }
        catch (e) {}
      }
      try { window.__octopus_trWalk(window["$dataMap"], 0); }
      catch (e) {}
    }
    // база грузится асинхронно — ждём все основные таблицы
    var _dbPoll = setInterval(function () {
      for (var j = 0; j < obDbTables.length; j++) {
        if (!window[obDbTables[j]]) return;
      }
      clearInterval(_dbPoll);
      obRefreshData();
    }, 400);
    // карты подгружаются по ходу игры — переобход после каждой загрузки
    trSafePatch(Game_Map.prototype.setup, function () {
      var obSetup = Game_Map.prototype.setup;
      Game_Map.prototype.setup = function (mapId) {
        var r = obSetup.call(this, mapId);
        try { obRefreshData(); } catch (e) {}
        return r;
      };
    });
    // словарь могли залить позже (live-режим через мост) — если база
    // уже загружена, обходим её сразу
    var obInstallBase = window.__octopus_trInstall;
    window.__octopus_trInstall = function (obj) {
      var n = obInstallBase(obj);
      try {
        if (typeof $dataSystem !== "undefined" && $dataSystem
            && window.__octopus_trWalk) {
          obRefreshData();
        }
      } catch (e) {}
      return n;
    };
  }, 400);
}

window.__octopus_trInstall(__TR_DICT__);
"""


def build_tr_dict(entries) -> dict:
    """Словарь original->translation для live-перевода (пустые пропущены)."""
    tr: dict = {}
    for e in entries:
        if isinstance(e, dict):
            orig = e.get("original", "")
            text = e.get("translation", "") or ""
            status = e.get("status", "")
        else:
            orig = getattr(e, "original", "")
            text = getattr(e, "translation", "") or ""
            status = getattr(e, "status", "")
        if orig and text.strip() and status != "skip":
            tr[orig] = text
    return tr


def _nwjs_profile_dirs(game_dir: str) -> list[str]:
    """Возможные каталоги профиля NW.js (user-data-dir).

    По умолчанию NW.js держит профиль в папке приложения, но многие
    игры задают --user-data-dir в chromium-args, а часть движков
    (например, runtime RPG Maker MV) кладёт профиль в
    %LOCALAPPDATA%\\<name>\\User Data по имени из package.json.
    """
    dirs = [game_dir]
    local = os.environ.get("LOCALAPPDATA")
    try:
        with open(os.path.join(game_dir, "package.json"),
                  encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = None
    args = (manifest or {}).get("chromium-args")
    if isinstance(args, str):
        for m in re.finditer(r"--user-data-dir=(?:\"([^\"]+)\"|(\S+))", args):
            path = m.group(1) or m.group(2)
            if path:
                resolved = path if os.path.isabs(path) else os.path.join(
                    game_dir, path)
                if resolved not in dirs:
                    dirs.append(os.path.abspath(resolved))
    if not local:
        return dirs
    name = (manifest or {}).get("name")
    if isinstance(name, str) and name.strip():
        base = local
        for part in re.split(r"[\\/]+", name.strip()):
            if part:
                base = os.path.join(base, part)
    else:
        base = os.path.join(local, "nwjs")
    for d in (base, os.path.join(base, "User Data"),
              os.path.join(local, "User Data"),  # MV runtime (пустой name)
              os.path.join(local, "KADOKAWA", "RPGMV"),
              os.path.join(local, "KADOKAWA", "RPGMV", "User Data"),
              os.path.join(local, "KADOKAWA", "RPGMZ"),
              os.path.join(local, "KADOKAWA", "RPGMZ", "User Data")):
        if d not in dirs:
            dirs.append(d)
    return dirs


def _is_stale_version(value) -> bool:
    """user_data_version из Local State: число или числовая строка.

    Chromium пишет ключ то числом, то строкой — принимаем оба варианта,
    иначе «протухший» профиль остаётся незамеченным и ошибка вернётся.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str) and value.strip().isdigit():
        return True
    return False


def _has_stale_profile(profile_dir: str) -> bool:
    """True, если в профиле есть Local State от более новой версии NW.js."""
    ls = os.path.join(profile_dir, "Local State")
    if not os.path.isfile(ls):
        return False
    try:
        with open(ls, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    return _is_stale_version(data.get("user_data_version"))


def _rename_if_exists(path: str) -> bool:
    """Переименовывает файл в path.bak с ретраями.

    Запущенный NW.js-процесс держит файлы профиля залоченными — при
    первом OSError пробуем ещё пару раз с паузой.
    """
    if not os.path.isfile(path):
        return False
    bak = path + ".bak"
    for _ in range(3):
        try:
            if os.path.exists(bak):
                os.remove(bak)
            os.rename(path, bak)
            return True
        except OSError:
            time.sleep(0.4)
    return False


def clean_nwjs_profile(game_dir: str) -> list[str]:
    """Чинит «Ваш профиль не может использоваться, поскольку он от более
    новой версии NW.js».

    Причина: Chromium мигрирует профиль только «вперёд» — если игру
    раньше запускали более новой сборкой NW.js (или профиль общий:
    у MV-игр с пустым name в package.json это %LOCALAPPDATA%\\nwjs),
    старая NW.js не может прочитать базы нового формата и показывает
    эту ошибку. Официальная рекомендация nwjs и сообщества RPG Maker —
    очистить каталог профиля.

    Файлы, где «зашита» версия: Local State (механизм Chromium) и
    Default/Web Data*, Default/Preferences. Их не удаляем, а
    переименовываем в *.bak — NW.js создаст свежий профиль. Каталог
    Default/Local Storage не трогаем (localStorage плагинов), а сейвы
    RPG Maker лежат в www/save — профиль их не содержит.

    Возвращает список каталогов профилей, где что-то переименовано.
    """
    renamed = []
    for d in _nwjs_profile_dirs(game_dir):
        ls = os.path.join(d, "Local State")
        default_dir = os.path.join(d, "Default")
        # «протухший» профиль: маркер версии в Local State ИЛИ реально
        # использованный профиль (Web Data/Preferences) — именно там, по
        # опыту сообщества RPG Maker, зашита версия, из-за которой
        # старая NW.js показывает «профиль от более новой версии»
        dirty = (_has_stale_profile(d)
                 or os.path.isfile(os.path.join(default_dir, "Web Data"))
                 or os.path.isfile(
                     os.path.join(default_dir, "Web Data-journal"))
                 or os.path.isfile(
                     os.path.join(default_dir, "Preferences"))
                 or os.path.isfile(
                     os.path.join(default_dir, "Secure Preferences")))
        if not dirty:
            continue
        if _rename_if_exists(ls):
            renamed.append(d)
        if os.path.isdir(default_dir):
            for name in ("Web Data", "Web Data-journal",
                         "Preferences", "Secure Preferences"):
                _rename_if_exists(os.path.join(default_dir, name))
        if not renamed or renamed[-1] != d:
            renamed.append(d)
    return renamed


class RpgMakerTentacle(CDPTentacle):
    key = "rpgmaker"
    title = "RPG Maker (CDP)"
    PAYLOAD = PAYLOAD

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._bridge_port = 0
        self._variant = ""

    # ── запуск ──
    def launch(self, target: str) -> bool:
        exe = target
        if os.path.isdir(target):
            exe = os.path.join(target, "Game.exe")
        if not os.path.isfile(exe):
            self.error.emit(f"Не найден исполняемый файл игры: {exe}")
            return False
        game_dir = os.path.dirname(exe)
        self._game_dir = game_dir
        self._variant = rpgm_variant.detect_variant(game_dir)
        is_mv = self._variant == "mv"

        # Игра уже запущена? NW.js (single-instance) не даёт второму
        # экземпляру поднять отладочный порт — поэтому подключаемся
        # к уже запущенному процессу, а без порта перезапускаем его
        # с --remote-debugging-port (иначе читы молча не работают).
        norm_dir = os.path.normpath(game_dir).lower()
        for r in proc.find_game_processes("rpgmaker", game_dir):
            if not os.path.normpath(r["exe"]).lower().startswith(norm_dir):
                continue  # чужая игра — не трогаем
            pid = r["pid"]
            if r["port"]:
                self.log.emit(
                    f"Игра уже запущена (pid {pid}, отладка "
                    f":{r['port']}) — подключаюсь к ней.")
                self._pid = pid
                if self._connect_page(r["port"], url_hint=".html",
                                      wait=10.0):
                    return True
                self._pid = None
                self.log.emit(
                    "Не удалось подключиться к запущенной игре — "
                    "перезапускаю её с отладкой.")
            else:
                if is_mv:
                    # MV: CDP недоступен, но мост мог подняться (плагин
                    # уже в игре) — подключаемся, ничего не закрывая
                    bport = mv_bridge.find_bridge_port(wait=5.0)
                    if bport:
                        self.log.emit(
                            f"Игра уже запущена с мостом (pid {pid}) — "
                            f"подключаюсь к :{bport}.")
                        self._pid = pid
                        self._bridge_port = bport
                        self.attached.emit()
                        return True
                self.log.emit(
                    f"Игра запущена без отладки (pid {pid}) — закрываю "
                    "и запускаю заново с отладочным портом.")
            if not proc.terminate(pid, timeout=5.0):
                self.error.emit(
                    "Не удалось закрыть уже запущенную игру. "
                    "Закройте её вручную и нажмите «Запустить» снова.")
                return False
            time.sleep(1.5)  # освободить порт и профиль NW.js
            break

        port = browser.free_port()
        if clean_nwjs_profile(game_dir):
            self.log.emit(
                "Профиль NW.js от другой версии: Local State переименован "
                "в Local State.bak (сейвы не тронуты).")
        if is_mv:
            # плагин-мост должен лежать в игре ДО старта: иначе игра
            # прочитает plugins.js без него и мост не поднимется
            if mv_bridge.ensure_bridge_registered(
                    game_dir, self.PAYLOAD, _TRANSLATION_PAYLOAD):
                self.log.emit(
                    "Мост MV внедрён: js/plugins/octopus_ob.js.")
        try:
            self._proc = subprocess.Popen(
                [exe, f"--remote-debugging-port={port}"],
                cwd=game_dir)
        except OSError as e:
            self.error.emit(f"Не удалось запустить игру: {e}")
            return False
        self._pid = self._proc.pid
        self.log.emit(f"Игра запущена (pid {self._pid}).")
        if is_mv:
            return self._launch_mv(port)
        self.log.emit(f"Отладка :{port}.")
        if not self._connect_page(port, url_hint=".html", wait=30.0):
            # NW.js мог поднять отладчик на другом порту (занятый
            # порт/инкремент) — ищем фактический до того, как закрывать
            actual = probe_game_port(self._pid) if self._pid else 0
            if actual and actual != port:
                self.log.emit(
                    f"Отладка поднялась на :{actual} — подключаюсь туда.")
                if self._connect_page(actual, url_hint=".html", wait=10.0):
                    return True
            if self._proc is not None:
                self._proc.terminate()
            self.detach()
            return False
        return True

    def _launch_mv(self, port: int) -> bool:
        """MV-профиль: мост вместо CDP (non-SDK NW.js, отладка вырезана).

        Перед стартом гарантируем наличие плагина-моста в игре (если его
        ещё нет — например, игру ещё не переводили). Затем ждём HTTP-мост;
        на расширенной (SDK) сборке запасной путь — CDP. Если не вышло
        ни то, ни другое, игру НЕ закрываем: перевод работает через файлы.
        """
        self.log.emit("Жду мост MV (официальный рантайм без CDP)…")
        bport = mv_bridge.find_bridge_port(wait=35.0)
        if bport:
            self._bridge_port = bport
            self.log.emit(
                f"Мост подключён: http://127.0.0.1:{bport}")
            self._log_game_errors(bport)
            self.attached.emit()
            return True
        if self._connect_page(port, url_hint=".html", wait=10.0):
            self.log.emit("Подключено через CDP (расширенная сборка).")
            return True
        self.log.emit(
            "Игра запущена без отладки: официальный рантайм MV "
            "не поддерживает remote debugging. Читы заработают после "
            "перезапуска через OctopusBridge; перевод применяется "
            "напрямую к файлам игры.")
        return True

    def attach(self, pid: int) -> bool:
        # MV: мост может быть уже поднят (игра запущена с нашим плагином)
        bport = mv_bridge.find_bridge_port(wait=3.0)
        if bport:
            self._pid = pid
            self._bridge_port = bport
            self.log.emit(
                f"Мост подключён: http://127.0.0.1:{bport}")
            self._log_game_errors(bport)
            self.attached.emit()
            return True
        port = getattr(self, "_port_hint", 0) or probe_game_port(pid)
        if not port:
            self.error.emit(
                "Отладочный порт не найден: игра запущена без "
                "--remote-debugging-port. Запустите её через OctopusBridge.")
            return False
        self._pid = pid
        # Профиль NW.js чистим и при attach (best-effort): файлы может
        # держать запущенная игра — переименования с ретраями упадут
        # молча, зато следующий запуск будет без «профиль от более
        # новой версии».
        try:
            exe_path = proc.exe_of(pid)
            if exe_path:
                clean_nwjs_profile(os.path.dirname(exe_path))
        except Exception:  # noqa: BLE001
            pass
        return self._connect_page(port, url_hint=".html", wait=5.0)

    def set_port_hint(self, port: int):
        self._port_hint = port

    def detach(self):
        self._proc = None
        self._bridge_port = 0
        super().detach()

    # ── мост MV: прозрачный роутинг поверх CDP-API ──
    def _log_game_errors(self, bport: int):
        """Ошибки страницы игры из предыдущих сессий (пережили краш в
        localStorage) — молчаливые вылеты MV становятся видимыми."""
        try:
            err = mv_bridge.bridge_errlog(bport)
        except Exception:  # noqa: BLE001
            return
        if not isinstance(err, dict):
            return
        for kind in ("catch", "error", "rejection"):
            e = err.get(kind)
            if isinstance(e, dict) and e.get("msg"):
                self.log.emit(
                    f"[игра] {kind}: {e['msg']} "
                    f"({e.get('extra', '')})")

    def evaluate(self, expression: str, await_promise: bool = False,
                 timeout: float = 15.0):
        if self._bridge_port:
            return mv_bridge.bridge_eval(
                self._bridge_port, expression, timeout)
        return super().evaluate(expression, await_promise, timeout)

    def is_attached(self) -> bool:
        if self._bridge_port:
            return True
        return super().is_attached()

    def send_key(self, key: str, code: str = "", keyCode: int = 0,
                 windowsKeyCode: int = 0) -> bool:
        if self._bridge_port:
            return False  # Input.dispatchKeyEvent недоступен без CDP
        return super().send_key(key, code, keyCode, windowsKeyCode)

    def screenshot(self) -> bytes | None:
        if self._bridge_port:
            return None  # Page.captureScreenshot недоступен без CDP
        return super().screenshot()

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

    def apply_translation(self, entries) -> bool:
        """Гибридный live-перевод: внедряет словарь в игру (MV и MZ).

        Работает поверх файлового патча и покрывает зашифрованные/asar
        сборки, где данные не меняются напрямую.
        """
        tr = build_tr_dict(entries)
        if not tr:
            return False
        code = _TRANSLATION_PAYLOAD.replace(
            "__TR_DICT__", mv_bridge.js_json(tr))
        ok, _val = self.evaluate(code)
        return bool(ok)

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
        if cmd == "heal_all":
            # MV: removeAllStates() отсутствует (MZ-only) — снимаем через
            # states().forEach(removeState), это же лечит смерть (revive)
            return ("$gameParty.members().forEach("
                    "a => { a.states().forEach("
                    "s => a.removeState(s.id)); a.setHp(a.mhp); "
                    "a.setMp(a.mmp); }), 'healed_all'")
        if cmd == "clear_states":
            return ("$gameParty.members().forEach("
                    "a => a.states().forEach("
                    "s => a.removeState(s.id))), 'states_cleared'")
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
        if cmd == "reload_map":
            return (
                "(() => {"
                " const mapId = $gameMap.mapId();"
                " const fn = 'data/Map' + ('00' + mapId).slice(-3)"
                " + '.json';"
                " const xhr = new XMLHttpRequest();"
                " xhr.open('GET', fn);"
                " xhr.overrideMimeType('application/octet-stream');"
                " xhr.onload = () => {"
                "   if (xhr.status > 0) {"
                "     let text = xhr.responseText;"
                "     if (typeof Decrypter !== 'undefined'"
                "         && Decrypter.hasEncryptedImages) {"
                "       try { text = Decrypter.decrypt(text); }"
                "       catch (e) {}"
                "     }"
                "     try { $dataMap = JSON.parse(text); }"
                "     catch (e) { return; }"
                "     $gameMap.setup(mapId);"
                "     $gamePlayer.reserveTransfer(mapId,"
                "       $gamePlayer.x, $gamePlayer.y,"
                "       $gamePlayer.direction(), 0);"
                "   }"
                " };"
                " xhr.send();"
                " return 'map_reloaded';"
                "})()")
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
        if self._pid and proc.pid_exists(self._pid):
            return self._pid
        return None


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
