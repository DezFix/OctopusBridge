#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebView2-режим запуска HTML-игры: обёртка ставится в папку игры
и раздаётся тем же HTTP-сервером тентакля, игра открывается в окне
приложения (WebView2/pywebview).

Отличия от Twine-обёртки:
- своя папка octopus_htmlapp/ (не octopus_webapp/ — без коллизий);
- plugin.js минимальный (heartbeat/status only, БЕЗ Save API —
  у обычных HTML-игр игрового API сейвов нет, синкать нечего).
"""
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
  #frame-wrap {{ position:fixed; inset:0; }}
  iframe {{ width:100%; height:100%; border:0; background:#fff; }}
</style>
</head>
<body>
  <div id="octopus-wrapper" hidden></div>
  <div id="frame-wrap"><iframe id="game" src="{IFRAME_URL}"></iframe></div>
  <script src="plugin.js"></script>
</body>
</html>
"""

PLUGIN_JS = r"""/* Плагин окна HTML-игры: heartbeat/status only.
   У обычных HTML-игр нет игрового API сейвов, поэтому синкать
   нечего: окно только держит iframe с игрой, перевод идёт live через
   мост тентакля (тот же origin). */
(function () {
    function ping() {
        try { console.log('[octopus] html wrapper alive'); } catch (e) {}
    }
    setInterval(ping, 30000);
    setTimeout(ping, 3000);
})();
"""


def game_title(path: str) -> str:
    """Заголовок игры: <title> страницы, иначе имя файла."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(200000)
        m = re.search(r"<title[^>]*>(.*?)</title>", head,
                      re.IGNORECASE | re.DOTALL)
        if m:
            title = html.unescape(re.sub(r"\s+", " ", m.group(1)).strip())
            if title:
                return title
    except OSError:
        pass
    base = os.path.splitext(os.path.basename(path))[0]
    return base or "HTML Game"


def install_webapp(game_dir: str, game_rel: str, title: str) -> str:
    """Пишет octopus_htmlapp/index.html + plugin.js в папку игры.

    Обёртку раздаёт тот же HTTP-сервер тентакля (папка игры — корень).
    Возвращает относительный путь к обёртке ('octopus_htmlapp/index.html')."""
    out = os.path.join(game_dir, "octopus_htmlapp")
    os.makedirs(out, exist_ok=True)
    iframe_url = quote("../" + game_rel.replace("\\", "/"), safe="/")
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(WRAPPER_HTML.format(
            GAME_TITLE=html.escape(title, quote=True),
            IFRAME_URL=iframe_url,
            ERROR_SHIELD=ERROR_SHIELD_JS))
    with open(os.path.join(out, "plugin.js"), "w", encoding="utf-8") as f:
        f.write(PLUGIN_JS)
    return "octopus_htmlapp/index.html"


def profile_dir_for(game_path: str) -> str:
    """Постоянный профиль WebView2 на игру: данные переживают перезапуск
    (localStorage привязан к профилю, не к порту)."""
    base = os.path.splitext(os.path.basename(game_path))[0]
    root = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(root, "OctopusBridgeWebApp", base + "_html_profile")


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
    icon = icon_path or os.path.join(_repo_root(), "assets", "ico.ico")
    if not os.path.isfile(icon):
        icon = ""
    frozen = getattr(sys, "frozen", False)
    if frozen:
        # PyInstaller: pythonw.exe рядом с exe нет, а повторный запуск
        # exe без флага открыл бы ещё одно окно приложения — второй
        # экземпляр с флагом выступит только окном WebView2 (см. main.py)
        launcher = [sys.executable, "--webapp-window",
                    url, title, profile_dir, icon]
    else:
        exe = sys.executable
        pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if not os.path.isfile(pythonw):
            pythonw = exe
        launcher = [pythonw, "-m", "app.engines.html.webapp",
                    url, title, profile_dir, icon]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        return subprocess.Popen(
            launcher,
            cwd=_repo_root() if not frozen else None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("html.webapp").warning(
            "Не удалось запустить окно WebView2 (%s) — открываю в браузере", e)
        webbrowser.open(url)
        return None


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _run_window(url: str, title: str, profile_dir: str, icon_path: str):
    import webview
    # Экспорт сейвов игры = скачивание файла; по умолчанию pywebview
    # отменяет загрузки (ALLOW_DOWNLOADS=False).
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.create_window(
        title, url, width=1100, height=750,
        resizable=True, background_color="#1d1d1d")
    threading.Thread(
        target=_set_window_icon_by_title, args=(title, icon_path),
        daemon=True).start()
    try:
        webview.start(private_mode=False, storage_path=profile_dir)
    except Exception:  # noqa: BLE001 — профиль занят другим окном
        try:
            webview.start(private_mode=False,
                          storage_path=profile_dir + "_alt")
        except Exception:  # noqa: BLE001 — не открылось и с запасным
            pass


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


if __name__ == "__main__":
    sys.path.insert(0, _repo_root())
    _run_window(sys.argv[1], sys.argv[2], sys.argv[3],
                sys.argv[4] if len(sys.argv) > 4 else "")
