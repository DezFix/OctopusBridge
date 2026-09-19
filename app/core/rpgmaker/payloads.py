# -*- coding: utf-8 -*-
"""JS-пейлоады RPG Maker (ES5): читы и live-перевод.

Вынесены из engines/rpgmaker/tentacle.py в ядро, чтобы runtime-overlay
(install_runtime) не тянул Qt-зависимости (PySide6) через tentacle.
Источники правды — здесь; tentacle.py реэкспортирует их для совместимости.
"""
from __future__ import annotations


PAYLOAD = r"""
if (!window.__octopus.rpgm) {
window.__octopus.rpgm = true;
window.__octopus.clickTp = false;
window.__octopus_hooksReady = false;

// ── кириллица: @font-face с unicode-range ──
try {
  var obStyle = document.createElement("style");
  obStyle.textContent =
    '@font-face{font-family:"rmmz-mainfont";src:local("Arial");' +
    'unicode-range:U+0400-04FF,U+0500-052F,U+2DE0-2DFF,U+A640-A69F}' +
    '@font-face{font-family:"mplus-1m-regular";src:local("Arial");' +
    'unicode-range:U+0400-04FF,U+0500-052F}' +
    '@font-face{font-family:"GameFont";src:local("Arial");' +
    'unicode-range:U+0400-04FF,U+0500-052F}';
  document.head.appendChild(obStyle);
} catch (e) {}

// ── ускорение игры: MV 1.6+/MZ — аккумулятор фиксированных шагов ──
window.__octopus_gameSpeed = 1;
window.__octopus_setGameSpeed = function (n) {
  n = Math.max(1, Math.min(20, Math.floor(n || 1)));
  window.__octopus_gameSpeed = n;
  if (!window.__octopus_speedHooked &&
      typeof SceneManager !== "undefined" && SceneManager.updateMain) {
    try {
      var _obUpdateMain = SceneManager.updateMain;
      SceneManager.updateMain = function () {
        var k = window.__octopus_gameSpeed || 1;
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
          var orig = this._deltaTime;
          this._deltaTime = orig / k;
          try {
            _obUpdateMain.call(this);
          } finally {
            this._deltaTime = orig;
          }
        } else {
          // древний MV без аккумулятора: k кадров, но requestUpdate
          // глушим (считаем), чтобы не расплодить rAF-кадры
          var obReq = SceneManager.requestUpdate;
          var reqs = 0;
          if (typeof obReq === "function") {
            SceneManager.requestUpdate = function () { reqs++; };
          }
          try {
            for (var i = 0; i < k; i++) { _obUpdateMain.call(this); }
          } finally {
            SceneManager.requestUpdate = obReq;
          }
          if (typeof obReq === "function" && reqs) { obReq.call(this); }
        }
      };
      window.__octopus_speedHooked = true;
    } catch (e) {}
  }
};

var _autoStateTimer = null;

function autoSendState() {
  if (_autoStateTimer) { return; }
  _autoStateTimer = setTimeout(function () { _autoStateTimer = null; sendState(); }, 500);
}

// ---------- полный снимок состояния ----------
function collectItems(kind, db) {
  var out = [];
  if (!db) { return out; }
  for (var i = 1; i < db.length; i++) {
    var it = db[i];
    if (it && it.name) {
      var cnt = 0;
      try { cnt = $gameParty.numItems(it); } catch (e2) { cnt = 0; }
      out.push({ kind: kind, id: it.id, name: it.name, count: cnt });
    }
  }
  return out;
}

function _has(name) {
  return typeof window[name] !== "undefined" && !!window[name];
}

window.__octopus_collectState = function () {
  var state = {
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
    try {
      $gameActors._data.forEach(function (a) {
        if (!a) { return; }
        var cls = null;
        try { cls = a.currentClass(); } catch (e) { cls = null; }
        var inP = false;
        try { inP = $gameParty.members().indexOf(a) !== -1; } catch (e2) { inP = false; }
        var pars = [];
        try {
          for (var pi = 0; pi < 8; pi++) { pars.push(a.param(pi)); }
        } catch (e3) { pars = []; }
        var nm = "";
        var lv = 0;
        var ex = 0;
        try { nm = a.name(); } catch (e4) {}
        try { lv = a.level; } catch (e5) {}
        try { ex = a.currentExp(); } catch (e6) {}
        state.party.push({
          id: a.actorId(), name: nm, level: lv,
          hp: a.hp, mp: a.mp, mhp: a.mhp, mmp: a.mmp, exp: ex,
          className: cls ? cls.name : "",
          inParty: inP,
          params: pars
        });
      });
    } catch (e) {}
    try {
      state.items = collectItems("item", window.$dataItems)
        .concat(collectItems("weapon", window.$dataWeapons))
        .concat(collectItems("armor", window.$dataArmors));
    } catch (e7) {}
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
      try { console.warn("[octopus] hook skip: " + e); } catch (e2) {}
    }
  }
}

function installHooks() {
  // телепорт по Ctrl+клику
  safePatch(Scene_Map.prototype.update, function () {
    var _sceneMapUpdate = Scene_Map.prototype.update;
    Scene_Map.prototype.update = function () {
      _sceneMapUpdate.call(this);
      try {
        if (window.__octopus.clickTp && TouchInput.isTriggered() &&
            Input.isPressed("control")) {
          var x = $gameMap.canvasToMapX(TouchInput.x);
          var y = $gameMap.canvasToMapY(TouchInput.y);
          if ($gameMap.isValid(x, y)) { $gamePlayer.locate(x, y); }
        }
      } catch (e) {}
    };
  });

  // автосинхронизация состояния
  safePatch(Game_Variables.prototype.setValue, function () {
    var _origGameVarsSetValue = Game_Variables.prototype.setValue;
    Game_Variables.prototype.setValue = function (id, value) {
      _origGameVarsSetValue.call(this, id, value);
      autoSendState();
    };
  });

  safePatch(Game_Switches.prototype.setValue, function () {
    var _origGameSwitchesSetValue = Game_Switches.prototype.setValue;
    Game_Switches.prototype.setValue = function (id, value) {
      _origGameSwitchesSetValue.call(this, id, value);
      autoSendState();
    };
  });

  safePatch(Game_Party.prototype.gainGold, function () {
    var _origGainGold = Game_Party.prototype.gainGold;
    Game_Party.prototype.gainGold = function (amount) {
      _origGainGold.call(this, amount);
      autoSendState();
    };
  });

  safePatch(Game_Party.prototype.loseGold, function () {
    var _origLoseGold = Game_Party.prototype.loseGold;
    Game_Party.prototype.loseGold = function (amount) {
      _origLoseGold.call(this, amount);
      autoSendState();
    };
  });

  safePatch(Game_Player.prototype.reserveTransfer, function () {
    var _origReserveTransfer = Game_Player.prototype.reserveTransfer;
    Game_Player.prototype.reserveTransfer = function (mapId, x, y, d, fadeType) {
      _origReserveTransfer.call(this, mapId, x, y, d, fadeType);
      autoSendState();
    };
  });

  safePatch(Game_BattlerBase.prototype.setHp, function () {
    var _origSetHp = Game_BattlerBase.prototype.setHp;
    Game_BattlerBase.prototype.setHp = function (hp) {
      _origSetHp.call(this, hp);
      autoSendState();
    };
  });

  safePatch(Game_BattlerBase.prototype.setMp, function () {
    var _origSetMp = Game_BattlerBase.prototype.setMp;
    Game_BattlerBase.prototype.setMp = function (mp) {
      _origSetMp.call(this, mp);
      autoSendState();
    };
  });

  safePatch(Game_Actor.prototype.changeLevel, function () {
    var _origChangeLevel = Game_Actor.prototype.changeLevel;
    Game_Actor.prototype.changeLevel = function (level, showEffect) {
      _origChangeLevel.call(this, level, showEffect);
      autoSendState();
    };
  });

  safePatch(Game_Actor.prototype.changeExp, function () {
    var _origChangeExp = Game_Actor.prototype.changeExp;
    Game_Actor.prototype.changeExp = function (exp, showEffect) {
      _origChangeExp.call(this, exp, showEffect);
      autoSendState();
    };
  });

  safePatch(Game_Party.prototype.gainItem, function () {
    var _origGainItem = Game_Party.prototype.gainItem;
    Game_Party.prototype.gainItem = function (item, amount, includeEquip) {
      _origGainItem.call(this, item, amount, includeEquip);
      autoSendState();
    };
  });

  window.__octopus_hooksReady = true;
  try { window.__octopus_setGameSpeed(window.__octopus_gameSpeed || 1); } catch (e) {}
  sendState();
}

var _enginePoll = setInterval(function () {
  if (typeof Scene_Map === "undefined" ||
      typeof Game_Variables === "undefined" ||
      typeof Game_Switches === "undefined" ||
      typeof Game_Party === "undefined" ||
      typeof Game_Player === "undefined" ||
      typeof Game_BattlerBase === "undefined" ||
      typeof Game_Actor === "undefined") { return; }
  clearInterval(_enginePoll);
  try {
    installHooks();
    try { console.log("[octopus] RPGM hooks installed"); } catch (e) {}
  } catch (e) {
    try { console.warn("[octopus] hook install failed: " + e); } catch (e2) {}
  }
}, 400);
}
"""


_TRANSLATION_PAYLOAD = r"""
if (!window.__octopus_trInit) {
  window.__octopus_trInit = true;
  window.__octopus_tr = {};

  window.__octopus_trApply = function (text) {
    if (typeof text !== "string" || text.length === 0) return text;
    var d = window.__octopus_tr;
    if (Object.prototype.hasOwnProperty.call(d, text)) {
      var exact = d[text];
      return (exact === undefined || exact === null) ? text : exact;
    }
    // Склеенные 401-строки ("line1\nline2"): словарь хранит построчно.
    // Построчная замена идемпотентна (повторный проход — no-op),
    // «дублей» оригинал+перевод не даёт (в отличие от substring-замен).
    if (text.indexOf("\n") >= 0) {
      var parts = text.split("\n");
      var changed = false;
      for (var i = 0; i < parts.length; i++) {
        if (Object.prototype.hasOwnProperty.call(d, parts[i])) {
          parts[i] = d[parts[i]];
          changed = true;
        } else {
          var trim = parts[i].trim();
          if (trim !== parts[i]
              && Object.prototype.hasOwnProperty.call(d, trim)) {
            parts[i] = d[trim];
            changed = true;
          }
        }
      }
      if (changed) return parts.join("\n");
    }
    var whole = text.trim();
    if (whole !== text
        && Object.prototype.hasOwnProperty.call(d, whole)) {
      return d[whole];
    }
    return text;
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

  // ── автоперенос длинных строк под ширину окна ──
  // Русский перевод в 1.5-2 раза длиннее японского оригинала, а окно
  // сообщений RPG Maker слова само не переносит: длинные строки
  // обрезаются за краем бокса. Переносим по словам с замером реальной
  // ширины шрифтом окна. ТОЛЬКО диалоги/прокрутка: однострочные меню
  // трогать нельзя (поедет вёрстка). Любая ошибка замера = старый
  // текст без переноса (хуже не будет).
  window.__octopus_trWrap = true;
  var obCodeTokRe = /\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z]|\\[{}\\|.!^_\\]/g;

  function obMeasureWidth(win, text) {
    try {
      var bmp = window.__octopus_measureBmp || null;
      if (!bmp) {
        bmp = new Bitmap(8, 8);
        window.__octopus_measureBmp = bmp;
      }
      if (win && win.contents) {
        try { bmp.fontFace = win.contents.fontFace; } catch (e1) {}
        try { bmp.fontSize = win.contents.fontSize; } catch (e2) {}
      }
      return bmp.measureTextWidth(text);
    } catch (e) { return -1; }
  }

  function obResolveNameCode(code) {
    // \N[n]/\P[n] подставляем настоящими именами для замера
    try {
      var m = /\\([NP])\[(\d+)\]/.exec(code);
      if (!m) return null;
      var idx = parseInt(m[2], 10);
      if (m[1] === "N" && window.$gameActors) {
        var a = window.$gameActors.actor(idx);
        if (a) return a.name();
      }
      if (m[1] === "P" && window.$gameParty) {
        var mem = window.$gameParty.members();
        if (mem && mem[idx - 1]) return mem[idx - 1].name();
      }
    } catch (e) {}
    return null;
  }

  function obPlainForMeasure(text) {
    return text.replace(obCodeTokRe, function (code) {
      var head = code.charAt(1);
      if (head === "V" || head === "N" || head === "P") {
        var resolved = obResolveNameCode(code);
        // переменные неизвестны заранее: закладываемся с запасом,
        // лучше перенести раньше, чем вылезти за край
        return (resolved !== null && resolved !== undefined)
          ? String(resolved) : "\u3042\u3042\u3042\u3042";
      }
      if (head === "I") return "  ";  // иконка ~32px
      if (head === "G") {
        try {
          if (window.$dataSystem && window.$dataSystem.currencyUnit) {
            return window.$dataSystem.currencyUnit;
          }
        } catch (e) {}
        return "";
      }
      return "";
    });
  }

  function obWrapLine(line, maxWidth, win) {
    if (!line || maxWidth <= 0) return line;
    // коды размера шрифта (\FS[n], \{, \}) меняют метрику на лету —
    // такие строки не трогаем (как было, без регрессий)
    if (/\\FS\[|\\[{}]/.test(line)) return line;
    if (obMeasureWidth(win, obPlainForMeasure(line)) <= maxWidth) {
      return line;  // влезает: поведение 1-в-1 как раньше
    }
    // токены: коды клеятся к следующему слову
    var toks = [], tre = /(\\[A-Za-z]+\[[^\]]*\]|\\[A-Za-z]|\\[{}\\|.!^_\\]|[^\s\\]+|\s+)/g, m;
    while ((m = tre.exec(line))) toks.push(m[0]);
    var atoms = [], pend = "", i, t;
    for (i = 0; i < toks.length; i++) {
      t = toks[i];
      if (t.charAt(0) === "\\") { pend += t; continue; }
      if (/^\s+$/.test(t)) continue;  // пробелы-перегородки: join даст один
      atoms.push({raw: pend + t, vis: t});
      pend = "";
    }
    if (pend) {
      if (atoms.length) atoms[atoms.length - 1].raw += pend;
      else atoms.push({raw: pend, vis: ""});
    }
    // коды без слов — к соседям (состояние цвета должно сохраниться):
    // ведущие — вперёд (красят следующий текст), хвостовые — назад
    var clean = [], carry = "";
    for (i = 0; i < atoms.length; i++) {
      if (!atoms[i].vis) { carry += atoms[i].raw; continue; }
      atoms[i].raw = carry + atoms[i].raw;
      carry = "";
      clean.push(atoms[i]);
    }
    if (carry) {
      if (clean.length) clean[clean.length - 1].raw += carry;
      else return line;  // одни коды без слов — нечего переносить
    }
    if (!clean.length) return line;
    // жадная упаковка по измеренной ширине; мерим всегда через
    // obPlainForMeasure (коды -> подстановки), иначе замеры упаковки
    // и проверки разъедутся (напр. \V[1] = 0 против запаса 8)
    var out = [], cur = [];
    function curW(list) {
      var raws = [];
      for (var k = 0; k < list.length; k++) raws.push(list[k].raw);
      return obMeasureWidth(win, obPlainForMeasure(raws.join(" ")));
    }
    function atomW(a) {
      return obMeasureWidth(win, obPlainForMeasure(a.raw));
    }
    for (i = 0; i < clean.length; i++) {
      var a = clean[i];
      if (!cur.length && atomW(a) > maxWidth) {
        // слово длиннее строки целиком (URL, CJK без пробелов):
        // режем посимвольно, коды — на первый кусок
        var chunks = obSplitAtom(a, maxWidth, win);
        for (var c = 0; c < chunks.length - 1; c++) out.push([chunks[c]]);
        cur = [chunks[chunks.length - 1]];
        continue;
      }
      var trial = cur.concat([a]);
      if (cur.length && curW(trial) > maxWidth) {
        out.push(cur);
        cur = [a];
      } else {
        cur = trial;
      }
    }
    if (cur.length) out.push(cur);
    if (out.length <= 1) return line;
    var res = [];
    for (i = 0; i < out.length; i++) {
      var raws = [];
      for (var k = 0; k < out[i].length; k++) raws.push(out[i][k].raw);
      res.push(raws.join(" "));
    }
    return res.join("\n");
  }

  function obSplitAtom(atom, maxWidth, win) {
    // делит переполненное слово посимвольно: [{raw,vis}...]
    // ведущие коды — на первый кусок, хвостовые (сброс цвета) — на последний
    var codeSrc = "\\\\[A-Za-z]+\\[[^\\]]*\\]|\\\\[A-Za-z]|\\\\[{}\\\\|.!^_\\\\]";
    var lead = new RegExp("^((?:" + codeSrc + ")*)([\\s\\S]*)$").exec(atom.raw);
    var prefix = lead ? lead[1] : "";
    var rest = lead ? lead[2] : atom.vis;
    var trail = new RegExp("((?:" + codeSrc + ")*)$").exec(rest);
    var suffix = trail ? trail[1] : "";
    var core = rest.slice(0, rest.length - suffix.length);
    if (!core) return [atom];
    // замер с префиксом: коды дают ширину подстановок (напр. \V[1])
    var prePlain = obPlainForMeasure(prefix);
    var chunks = [], curV = "";
    for (var i = 0; i < core.length; i++) {
      var trial = curV + core.charAt(i);
      if (curV && obMeasureWidth(win, prePlain + trial) > maxWidth) {
        chunks.push(curV);
        curV = core.charAt(i);
      } else {
        curV = trial;
      }
    }
    if (curV) chunks.push(curV);
    if (!chunks.length) return [atom];
    var out = [];
    for (var j = 0; j < chunks.length; j++) {
      out.push({raw: (j === 0 ? prefix : "")
        + chunks[j] + (j === chunks.length - 1 ? suffix : ""),
        vis: chunks[j]});
    }
    return out;
  }

  function obWrapForWindow(win, text) {
    // точка входа из convertEscapeCharacters: только окна сообщений
    try {
      if (window.__octopus_trWrap === false) return text;
      if (typeof text !== "string") return text;
      var isMsg = false, isScroll = false;
      try {
        isMsg = (typeof Window_Message !== "undefined")
          && (win instanceof Window_Message);
        isScroll = !isMsg && (typeof Window_ScrollText !== "undefined")
          && (win instanceof Window_ScrollText);
      } catch (e) {}
      if (!isMsg && !isScroll) return text;
      var maxW = -1;
      try { maxW = win.contentsWidth ? win.contentsWidth() : -1; } catch (e) {}
      if (!(maxW > 0)) return text;
      if (isMsg) {
        // строка с портретом уже: текст начинается правее
        try {
          if (window.$gameMessage && window.$gameMessage.faceName
              && window.$gameMessage.faceName()) {
            maxW -= 168;
          }
        } catch (e) {}
        if (!(maxW > 0)) return text;
      }
      var lines = String(text).split("\n"), i, changed = false, res = [];
      for (i = 0; i < lines.length; i++) {
        var w = obWrapLine(lines[i], maxW, win);
        if (w !== lines[i]) changed = true;
        res.push(w);
      }
      return changed ? res.join("\n") : text;
    } catch (e) { return text; }
  }
  window.__octopus_trWrapForWindow = obWrapForWindow;

  var _trPoll = setInterval(function () {
    if (typeof Window_Base === "undefined"
        || typeof Bitmap === "undefined") return;
    clearInterval(_trPoll);
    // диалоги/сообщения: подменяем строку ДО раскрытия escape-кодов,
    // чтобы перевод сохранил \N[..] / \C[..] как есть
    trSafePatch(Window_Base.prototype.convertEscapeCharacters, function () {
      var obCvt = Window_Base.prototype.convertEscapeCharacters;
      Window_Base.prototype.convertEscapeCharacters = function (text) {
        var translated = obCvt.call(this, window.__octopus_trApply(text));
        // автоперенос под ширину окна — только диалоги/прокрутка
        // (внутри obWrapForWindow проверяется тип окна)
        return window.__octopus_trWrapForWindow
          ? window.__octopus_trWrapForWindow(this, translated)
          : translated;
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
    // ── catch-all для меню/титулов/опций ──
    // Часть меню рисуется НЕ через convertEscapeCharacters и НЕ из
    // $data-таблиц (строки уже закэшированы плагинами из parameters
    // при загрузке, либо собраны кодом). Перехватываем финальную
    // отрисовку: Bitmap.drawText — точка, через которую проходят
    // вообще все меню/заголовки/опции. Идемпотентно: повторный
    // проход по уже переведённому тексту — no-op (ключа нет).
    trSafePatch(Bitmap.prototype.drawText, function () {
      var obDraw = Bitmap.prototype.drawText;
      Bitmap.prototype.drawText = function (text, x, y, w, h, align) {
        return obDraw.call(this, window.__octopus_trApply(text),
                           x, y, w, h, align);
      };
    });
    // drawTextEx — текст с escape-кодами (\C[n]...): подменяем ДО
    // разбора кодов, чтобы перевод сохранил их как есть
    trSafePatch(Window_Base.prototype.drawTextEx, function () {
      var obEx = Window_Base.prototype.drawTextEx;
      Window_Base.prototype.drawTextEx = function (text, x, y) {
        return obEx.call(this, window.__octopus_trApply(text), x, y);
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
    // Ключи-ссылки на файлы (имена героев/лиц/врагов/фонов/параллакса):
    // перевод имени файла = "Failed to load" в игре. Такие строки
    // никогда не попадают в словарь (см. resrefs.py), это второй рубеж.
    function obIsResKey(k) {
      return k === "characterName" || k === "faceName"
        || k === "battlerName" || k === "parallaxName"
        || k === "battleback1Name" || k === "battleback2Name"
        || k === "title1Name" || k === "title2Name";
    }
    // Аудио-объект {name,volume,pitch,pan}: name — имя файла.
    function obIsAudio(o) {
      return o && typeof o === "object" && !Array.isArray(o)
        && typeof o.name === "string"
        && (typeof o.volume !== "undefined"
          || typeof o.pitch !== "undefined"
          || typeof o.pan !== "undefined");
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
        if (obIsResKey(k)) continue; // имя файла ресурса
        var v2 = node[k];
        if (v2 && typeof v2 === "object") {
          if (obIsAudio(v2)) continue; // аудио-объект целиком
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
    function obSplitKV(s) {
      // «KEY = value» -> {head, val}, иначе null. Ключ — компактный
      // идентификатор без пробелов (зеркало parser._split_kv_line).
      if (typeof s !== "string") return null;
      var eq = s.indexOf("=");
      if (eq < 0) return null;
      var key = s.slice(0, eq).replace(/^\s+|\s+$/g, "");
      if (!key || key.length > 40 || /\s/.test(key)) return null;
      var val = s.slice(eq + 1).replace(/^\s+|\s+$/g, "");
      if (!val) return null;
      return {head: s.slice(0, eq + 1), val: val};
    }
    function obApplyKVParam(ps, i) {
      // Целое совпадение — как обычно; иначе подмена только value-части
      // («KEY = value»): ключ, по которому плагин разбирает строку,
      // остаётся байт-в-байт.
      var v = ps[i];
      if (typeof v !== "string") return;
      if (obHas(v)) { ps[i] = obDict[v]; return; }
      var kv = obSplitKV(v);
      if (kv && obHas(kv.val)) {
        var tail = v.slice(kv.head.length);
        if (tail.replace(/^\s+|\s+$/g, "") === kv.val) {
          ps[i] = kv.head + tail.replace(kv.val, obDict[kv.val]);
        }
      }
    }
    function obWalkCmd(cmd) {
      if (cmd.code === 657) {
        var ps657 = cmd.parameters || [];
        for (var q657 = 0; q657 < ps657.length; q657++) {
          obApplyKVParam(ps657, q657);
        }
        return;
      }
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
      // параметры плагинов ($plugins[i].parameters): часть плагинных
      // меню уже закэшировала значения при загрузке (до нашего хука),
      // но всё что читается лениво — подхватит перевод здесь
      try { window.__octopus_trWalk(window["$plugins"], 0); }
      catch (e) {}
    }
    // PluginManager.parameters(): ленивые чтения после нашего хука —
    // отдаём переведённую копию (оригинал $plugins не портим)
    trSafePatch(PluginManager.parameters, function () {
      var obParams = PluginManager.parameters;
      PluginManager.parameters = function (name) {
        var p = obParams.call(this, name);
        if (!p || typeof p !== "object") return p;
        var out = {};
        for (var k in p) {
          if (!Object.prototype.hasOwnProperty.call(p, k)) continue;
          var v = p[k];
          out[k] = (typeof v === "string")
            ? window.__octopus_trApply(v) : v;
        }
        return out;
      };
    });
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
