# -*- coding: utf-8 -*-
"""Обнаружение Chromium-отладчика: HTTP-эндпоинты /json, выбор цели.

Любой Chromium (NW.js RPG Maker, Edge, Chrome) с флагом
--remote-debugging-port=PORT отдаёт список отладочных целей по HTTP.
"""
from __future__ import annotations

import json
import os
import time

import requests


def debugger_ready(port: int, timeout: float = 0.8) -> bool:
    """Отвечает ли отладчик на порту."""
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json/version",
                         timeout=timeout)
        return r.ok
    except requests.RequestException:
        return False


def wait_for_debugger(port: int, timeout: float = 20.0) -> bool:
    """Ждёт, пока процесс поднимет отладочный порт."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if debugger_ready(port):
            return True
        time.sleep(0.25)
    return False


def list_targets(port: int) -> list[dict]:
    """Все отладочные цели (page, background_page, ...)."""
    try:
        r = requests.get(f"http://127.0.0.1:{port}/json", timeout=2)
        r.raise_for_status()
        return json.loads(r.text)
    except (requests.RequestException, ValueError):
        return []


def pick_page_target(port: int, url_hint: str = "") -> dict | None:
    """Выбирает page-цель. url_hint — подстрока URL (например 'index.html').
    Цели без webSocketDebuggerUrl бесполезны — пропускаем."""
    targets = [t for t in list_targets(port)
               if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    if not targets:
        return None
    if url_hint:
        hint = url_hint.lower().replace("\\", "/")
        for t in targets:
            if hint in (t.get("url") or "").lower():
                return t
    for t in targets:
        url = (t.get("url") or "").lower()
        if url and not url.startswith("about:") and not url.startswith(
                "chrome:") and not url.startswith("edge:"):
            return t
    return targets[0]


def free_port(preferred: int = 0) -> int:
    """Свободный localhost-порт (0 — любой от ОС)."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", preferred))
        return s.getsockname()[1]


def port_from_devtools_file(exe_path: str, game_dir: str = "") -> int:
    """Порт из файла DevToolsActivePort, который Chromium пишет в свой
    user-data-dir при включённом --remote-debugging-port.

    Ищем в типичных местах NW.js: рядом с игрой, в подпапках профиля,
    в %LOCALAPPDATA%/<имя exe>.
    """
    bases = []
    if game_dir:
        bases.append(game_dir)
    if exe_path:
        bases.append(os.path.dirname(exe_path))
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            stem = os.path.splitext(os.path.basename(exe_path))[0]
            bases.append(os.path.join(local, stem))
    subs = ("", "User Data", "UserData", "userdata", "Default",
            "user-data", "data")
    seen = set()
    for base in bases:
        for sub in subs:
            path = os.path.join(base, sub, "DevToolsActivePort")
            if path in seen:
                continue
            seen.add(path)
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8",
                              errors="ignore") as f:
                        return int(f.readline().strip())
                except (ValueError, OSError):
                    continue
    return 0


def scan_ports(ports, timeout: float = 0.35) -> list[int]:
    """Параллельно проверяет порты на живой CDP-эндпоинт."""
    from concurrent.futures import ThreadPoolExecutor

    def probe(p: int):
        return p if debugger_ready(p, timeout=timeout) else None

    with ThreadPoolExecutor(max_workers=32) as ex:
        return sorted(p for p in ex.map(probe, ports) if p)
