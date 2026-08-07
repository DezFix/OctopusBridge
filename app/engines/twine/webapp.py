#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebView2-режим запуска Twine-игры: обёртка ставится в папку игры
и раздаётся тем же HTTP-сервером тентакля, игра открывается в окне
приложения (WebView2/pywebview). Перевод — встроенный в страницу
(Google gtx / MyMemory), мост и инжекция пэйлоада не нужны."""
import html
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import webbrowser
from urllib.parse import quote

APP_TITLE = "OctopusBridge"

# Перехватывает ошибки страницы, чтобы WebView2 не показывал диалог
# "An error has occurred..." на баги самой игры. Вставляется ДО скриптов игры.
ERROR_SHIELD_JS = (
    "<script>"
    "window.addEventListener('error',function(e){e.preventDefault();return true;},true);"
    "window.addEventListener('unhandledrejection',function(e){e.preventDefault();},true);"
    "window.onerror=function(){return true;};"
    "</script>"
)

WRAPPER_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
{ERROR_SHIELD}
<meta charset="utf-8">
<title>{GAME_TITLE}</title>
<style>
  body {{ margin:0; font-family: system-ui, sans-serif; background:#111; color:#ddd; }}
  #bar {{ display:flex; align-items:center; gap:10px; padding:6px 12px; background:#1d1d1d; border-bottom:1px solid #333; flex-wrap:wrap; }}
  #bar button {{ background:#333; color:#eee; border:1px solid #555; border-radius:4px; padding:4px 10px; cursor:pointer; }}
  #bar button:hover {{ background:#444; }}
  #bar select {{ background:#333; color:#eee; border:1px solid #555; border-radius:4px; padding:3px 6px; }}
  #status {{ font-size:12px; color:#8a8; }}
  #frame-wrap {{ position:fixed; inset:42px 0 0 0; }}
  iframe {{ width:100%; height:100%; border:0; background:#fff; }}
</style>
</head>
<body>
  <div id="bar">
    <button id="btnTr">Перевод: ВКЛ</button>
    <button id="btnClr">Сброс кэша перевода</button>
    <label>→ <select id="langSel" title="Язык перевода">
      <option value="ru">RU</option><option value="en">EN</option>
      <option value="de">DE</option><option value="fr">FR</option>
      <option value="es">ES</option><option value="uk">UK</option>
    </select></label>
    <span id="status">…</span>
  </div>
  <div id="frame-wrap"><iframe id="game" src="{IFRAME_URL}"></iframe></div>
  <script src="plugin.js"></script>
</body>
</html>
"""

PLUGIN_JS = r"""/* Плагин перевода для обёртки Twine-игры.
   Перевод прямо в странице, без моста:
     * Google Translate (gtx-эндпоинт, им же пользуется Chrome) — основной;
     * MyMemory — запасной.
   Кэш переводов — localStorage (по языку), сейвы игры — родные (один origin). */
(function () {
    var iframe = document.getElementById('game');
    var enabled = true;
    var cache = {};
    var inflight = {};       // text -> Promise
    var PREF = 'octopus_tr_target';
    var TARGET = localStorage.getItem(PREF) || 'ru';
    var KEY = 'octopus_tr_cache_' + TARGET;

    var ENGINES = [
        {
            name: 'Google',
            build: function (text) {
                return 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl='
                    + TARGET + '&dt=t&q=' + encodeURIComponent(text);
            },
            parse: function (data) {
                if (!data || !Array.isArray(data[0])) return null;
                var out = '';
                for (var i = 0; i < data[0].length; i++) {
                    var seg = data[0][i];
                    if (seg && seg[0]) out += seg[0];
                }
                return out || null;
            }
        },
        {
            name: 'MyMemory',
            build: function (text) {
                var src = TARGET === 'en' ? 'ru' : 'en';
                return 'https://api.mymemory.translated.net/get?q=' + encodeURIComponent(text)
                    + '&langpair=' + src + '|' + TARGET;
            },
            parse: function (data) {
                var s = data && data.responseData && data.responseData.translatedText;
                return s || null;
            }
        }
    ];

    function setStatus(s) {
        var el = document.getElementById('status');
        if (el) el.textContent = s;
    }

    try { cache = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { cache = {}; }
    function saveCache() {
        try { localStorage.setItem(KEY, JSON.stringify(cache)); } catch (e) {}
    }

    function _isTargetLang(s) {
        if (TARGET === 'ru') return /[а-яА-ЯЁё]/.test(s);
        if (TARGET === 'en') return /[a-zA-Z]/.test(s) && !/[а-яА-ЯЁё]/.test(s);
        return false;
    }

    function _tr(s) {
        return s.length >= 2 && /[a-zA-Zа-яА-Я\u4e00-\u9fff]/.test(s) && !_isTargetLang(s);
    }

    function translate(text) {
        var s = text.trim();
        if (cache[s] !== undefined) return Promise.resolve(cache[s]);
        if (inflight[s]) return inflight[s];
        var resolveP;
        var p = new Promise(function (res) { resolveP = res; });
        inflight[s] = p;

        (function tryEngine(i) {
            if (i >= ENGINES.length) {
                delete inflight[s];
                resolveP(s);
                return;
            }
            var e = ENGINES[i];
            var ctrl = new AbortController();
            var timer = setTimeout(function () { ctrl.abort(); }, 15000);
            fetch(e.build(s), { signal: ctrl.signal })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    clearTimeout(timer);
                    var tr = e.parse(data);
                    if (tr && tr !== s) {
                        delete inflight[s];
                        cache[s] = tr;
                        saveCache();
                        resolveP(tr);
                    } else {
                        tryEngine(i + 1);
                    }
                })
                .catch(function () { clearTimeout(timer); tryEngine(i + 1); });
        })(0);
        return p;
    }

    function splitSentences(t) {
        return t.split(/(?<=[.!?\u2026])\s+(?=[\u00ab\u201c"'A-Z\u0410-\u042f0-9$\[])/)
            .filter(function (s) { return _tr(s); });
    }

    function walkText(root) {
        var nodes = [];
        var w = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode: function (n) {
                var pe = n.parentElement;
                if (!pe) return NodeFilter.FILTER_REJECT;
                var tag = pe.tagName.toUpperCase();
                if (tag === 'STYLE' || tag === 'SCRIPT' || tag === 'TW-PASSAGEDATA' || tag === 'TW-STORYDATA')
                    return NodeFilter.FILTER_REJECT;
                if (n.textContent.trim() && _tr(n.textContent)) return NodeFilter.FILTER_ACCEPT;
                return NodeFilter.FILTER_REJECT;
            }
        }, false);
        while (w.nextNode()) nodes.push(w.currentNode);
        return nodes;
    }

    function applyCache(n, s, tr) {
        if (tr !== undefined && tr !== s && n.isConnected)
            n.textContent = n.textContent.replace(s, tr);
    }

    function translateDOM() {
        if (!enabled) return;
        var doc = iframe.contentDocument;
        if (!doc) return;
        var c = doc.querySelector('#passages .passage, tw-passage, .passage, #passages');
        if (!c) return;
        walkText(c).forEach(function (n) {
            var t = n.textContent, s = t.trim();
            if (!_tr(s)) return;
            if (cache[s] !== undefined) { applyCache(n, s, cache[s]); return; }
            var segs = splitSentences(t);
            if (segs.length === 1) {
                if (!inflight[s]) translate(s).then(function (tr) { applyCache(n, s, tr); });
                return;
            }
            segs.forEach(function (seg) {
                if (cache[seg] !== undefined) { applyCache(n, seg, cache[seg]); return; }
                if (inflight[seg]) return;
                translate(seg).then(function (tr) { applyCache(n, seg, tr); });
            });
        });
    }

    var timer;
    iframe.addEventListener('load', function () {
        var doc = iframe.contentDocument;
        if (!doc || !doc.body) return;
        injectWrapCss(doc);
        try {
            var win = iframe.contentWindow;
            if (win.$ && win.$.fn) win.$(win.document).on(':passagedisplay', function () { setTimeout(translateDOM, 50); });
        } catch (e) {}
        new MutationObserver(function () {
            clearTimeout(timer);
            timer = setTimeout(translateDOM, 150);
        }).observe(doc.body, { childList: true, subtree: true, characterData: true });
        setTimeout(translateDOM, 300);
    });

    // Переводы длиннее оригинала ломают вёрстку движка: длинные слова
    // вылезают за рамки пассажей/кнопок. Мягкие CSS-правила заставляют
    // текст переноситься по буквам, не трогая остальные стили игры.
    var WRAP_CSS =
        '#passages .passage, tw-passage, .passage, tw-hook, ' +
        '#passages, #story, tw-story { ' +
        'max-width:100%; overflow-wrap:anywhere; word-break:break-word; } ' +
        '#passages .passage, tw-passage, .passage { ' +
        'overflow-y:auto; box-sizing:border-box; } ' +
        'tw-passage img, .passage img, #passages img { ' +
        'max-width:100%; height:auto; }';
    function injectWrapCss(doc) {
        if (!doc || !doc.head) return;
        try {
            if (doc.getElementById('octopus-wrap-css')) return;
            var st = doc.createElement('style');
            st.id = 'octopus-wrap-css';
            st.textContent = WRAP_CSS;
            doc.head.appendChild(st);
        } catch (e) {}
    }

    setInterval(function () {
        var has = false;
        for (var k in inflight) { has = true; break; }
        if (has) translateDOM();
    }, 3000);

    document.getElementById('btnTr').onclick = function () {
        enabled = !enabled;
        this.textContent = 'Перевод: ' + (enabled ? 'ВКЛ' : 'ВЫКЛ');
        if (enabled) translateDOM();
    };
    document.getElementById('btnClr').onclick = function () {
        cache = {};
        try { localStorage.removeItem(KEY); } catch (e) {}
        iframe.contentWindow.location.reload();
    };
    var sel = document.getElementById('langSel');
    if (sel) {
        sel.value = TARGET;
        sel.onchange = function () {
            TARGET = sel.value;
            KEY = 'octopus_tr_cache_' + TARGET;
            try { localStorage.setItem(PREF, TARGET); } catch (e) {}
            try { cache = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { cache = {}; }
            iframe.contentWindow.location.reload();
        };
    }
    // ── Синк сейвов с приложением ──
    // SugarCube держит слоты в localStorage профиля окна — файлов на
    // диске нет, поэтому редактор сейвов их не видит. Плагин читает
    // слоты (Save API в окне игры — тот же origin, доступ напрямую)
    // и присылает их серверу приложения; тот пишет .save файлы.
    function scSave() {
        var w = iframe.contentWindow;
        if (!w) return null;
        var S = w.Save;
        if (!S || typeof S.serialize !== 'function' || typeof S.slots === 'undefined')
            return null;
        return S;
    }
    function collectSlots() {
        var S = scSave();
        if (!S) return null;
        var out = [], n = 0;
        try { n = S.slots.size(); } catch (e) { return null; }
        for (var i = 0; i < n; i++) {
            try {
                var slot = S.slots.get(String(i));
                if (!slot || !slot.data) continue;
                var b64 = S.serialize(slot.data);
                if (!b64) continue;
                out.push({ id: String(i),
                           date: slot.saveDate ? slot.saveDate.getTime() : 0,
                           size: b64.length,
                           data: b64 });
            } catch (e) {}
        }
        return out;
    }
    var lastSig = '';
    function pushSaves() {
        var slots = collectSlots();
        if (!slots) return;
        var sig = '';
        for (var i = 0; i < slots.length; i++)
            sig += slots[i].id + ':' + slots[i].date + ':' + slots[i].size + '|';
        if (sig === lastSig) return;
        lastSig = sig;
        try {
            fetch('/api/saves', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ saves: slots })
            }).then(function (r) { return r.json(); })
              .then(function (j) {
                  if (j && j.ok) setStatus('сейвы: ' + j.count + ' синхронизировано');
              })
              .catch(function () { lastSig = ''; });
        } catch (e) { lastSig = ''; }
    }
    function pollImport() {
        try {
            fetch('/api/saves/pending-import', { cache: 'no-store' })
                .then(function (r) { return r.json(); })
                .then(function (p) {
                    if (!p || !p.data || !scSave()) return;
                    var S = scSave(), ok = false;
                    try {
                        var obj = S.deserialize(p.data);
                        if (p.slot !== undefined && p.slot !== null && p.slot !== '') {
                            S.slots.set(String(p.slot), obj);
                        } else {
                            S.slots.set(String(S.slots.size()), obj);
                        }
                        ok = true;
                    } catch (e) { ok = false; }
                    if (ok) {
                        setStatus('сейв загружен в игру');
                        fetch('/api/saves/import', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: '{"applied":1}'
                        }).catch(function () {});
                    }
                })
                .catch(function () {});
        } catch (e) {}
    }
    setInterval(pushSaves, 8000);
    setInterval(pollImport, 5000);
    setTimeout(pushSaves, 5000);
    setTimeout(pollImport, 3000);

    setStatus('перевод встроенный: Google / MyMemory');
})();
"""


def game_title(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            head = f.read(200000)
        m = re.search(r'<tw-storydata[^>]*\bname="([^"]*)"', head)
        if m:
            return m.group(1)
    except OSError:
        pass
    return os.path.splitext(os.path.basename(path))[0]


def install_webapp(game_dir: str, game_rel: str, title: str) -> str:
    """Пишет octopus_webapp/index.html + plugin.js в папку игры.

    Обёртку раздаёт тот же HTTP-сервер тентакля (папка игры — корень).
    Возвращает относительный путь к обёртке ('octopus_webapp/index.html')."""
    out = os.path.join(game_dir, 'octopus_webapp')
    os.makedirs(out, exist_ok=True)
    iframe_url = quote('../' + game_rel.replace('\\', '/'), safe='/')
    with open(os.path.join(out, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(WRAPPER_HTML.format(
            GAME_TITLE=html.escape(title, quote=True),
            IFRAME_URL=iframe_url,
            ERROR_SHIELD=ERROR_SHIELD_JS))
    with open(os.path.join(out, 'plugin.js'), 'w', encoding='utf-8') as f:
        f.write(PLUGIN_JS)
    return 'octopus_webapp/index.html'


def profile_dir_for(game_path: str) -> str:
    """Постоянный профиль WebView2 на игру: сейвы и кэш переживают
    перезапуск (localStorage привязан к профилю, не к порту)."""
    base = os.path.splitext(os.path.basename(game_path))[0]
    root = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    return os.path.join(root, 'OctopusBridgeWebApp', base + '_profile')


def open_game_window(title: str, url: str, profile_dir: str,
                     icon_path: str | None = None):
    """Окно приложения (WebView2) в отдельном процессе: pywebview обязан
    работать на главном потоке, а приложение не должно блокироваться.
    Возвращает Popen окна (для закрытия через detach) или None —
    если pywebview недоступен и открыт браузер."""
    try:
        import webview  # noqa: F401
    except ImportError:
        webbrowser.open(url)
        return None
    # Плагин перевода ходит на translate.googleapis.com без CORS-заголовков.
    os.environ.setdefault(
        'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', '--disable-web-security')
    icon = icon_path or os.path.join(_repo_root(), 'ico.ico')
    if not os.path.isfile(icon):
        icon = ''
    frozen = getattr(sys, 'frozen', False)
    if frozen:
        # PyInstaller: pythonw.exe рядом с exe нет, а повторный запуск
        # exe без флага открыл бы ещё одно окно приложения — второй
        # экземпляр с флагом выступит только окном WebView2 (см. main.py)
        launcher = [sys.executable, '--webapp-window',
                    url, title, profile_dir, icon]
    else:
        exe = sys.executable
        pythonw = os.path.join(os.path.dirname(exe), 'pythonw.exe')
        if not os.path.isfile(pythonw):
            pythonw = exe
        launcher = [pythonw, '-m', 'app.engines.twine.webapp',
                    url, title, profile_dir, icon]
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        return subprocess.Popen(
            launcher,
            cwd=_repo_root() if not frozen else None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags)
    except Exception as e:  # noqa: BLE001
        logging.getLogger('twine.webapp').warning(
            'Не удалось запустить окно WebView2 (%s) — открываю в браузере', e)
        webbrowser.open(url)
        return None


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _run_window(url: str, title: str, profile_dir: str, icon_path: str):
    import webview
    # Экспорт сейвов игры = скачивание файла; по умолчанию pywebview
    # отменяет загрузки (ALLOW_DOWNLOADS=False).
    webview.settings['ALLOW_DOWNLOADS'] = True
    win = webview.create_window(
        title, url, width=1100, height=750,
        resizable=True, background_color='#1d1d1d')
    threading.Thread(
        target=_set_window_icon_by_title, args=(title, icon_path),
        daemon=True).start()
    try:
        webview.start(private_mode=False, storage_path=profile_dir)
    except Exception:  # noqa: BLE001 — профиль занят другим окном
        webview.start(private_mode=False, storage_path=profile_dir + '_alt')


def _set_window_icon_by_title(title: str, icon_path: str):
    """Иконка окна через Win32 (WM_SETICON) — pywebview не даёт доступа
    к форме, а процесс под pythonw показывает дефолтную иконку питона."""
    import ctypes
    import time
    if not icon_path or not os.path.isfile(icon_path):
        return
    try:
        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE)
        if not hicon:
            return
        hwnd = 0
        for _ in range(60):  # окно появляется не мгновенно (до 15 с)
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                break
            time.sleep(0.25)
        if hwnd:
            user32.SendMessageW(hwnd, WM_SETICON, 1, hicon)  # большая (таскбар)
            user32.SendMessageW(hwnd, WM_SETICON, 0, hicon)  # маленькая
    except Exception:  # noqa: BLE001 — иконка не критична
        pass


if __name__ == '__main__':
    sys.path.insert(0, _repo_root())
    _run_window(sys.argv[1], sys.argv[2], sys.argv[3],
                sys.argv[4] if len(sys.argv) > 4 else '')
