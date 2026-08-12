# -*- coding: utf-8 -*-
"""Работа с процессами ОС: поиск запущенных игр, информация о PID.

Обёртка над psutil, чтобы ядро не размазывало sys-код по модулям.
"""
from __future__ import annotations

import os

import psutil

# Характерные имена исполняемых файлов движков (нижний регистр, без пути)
_RPGM_NAMES = {"game.exe", "nw.exe", "nwjs.exe", "rpgmaker.exe"}
_RENPY_NAMES_SUFFIX = (".exe",)
_RENPY_HINTS = ("renpy",)


def pid_exists(pid: int) -> bool:
    try:
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        return False


def exe_of(pid: int) -> str:
    """Полный путь к exe процесса или ''."""
    try:
        return psutil.Process(pid).exe() or ""
    except (psutil.Error, OSError):
        return ""


def terminate(pid: int, timeout: float = 3.0) -> bool:
    """Мягко завершает процесс (и детей — Chromium плодит subprocess'ы)."""
    try:
        proc = psutil.Process(pid)
        victims = proc.children(recursive=True) + [proc]
        for p in victims:
            try:
                p.terminate()
            except (psutil.Error, OSError):
                pass
        _, alive = psutil.wait_procs(victims, timeout=timeout)
        for p in alive:                      # кто не умер — добиваем
            try:
                p.kill()
            except (psutil.Error, OSError):
                pass
        return True
    except (psutil.Error, OSError):
        return False


def _looks_like_renpy(exe_path: str, game_dir: str = "") -> bool:
    """Ren'Py-игры называются как угодно — ориентируемся на renpy/ рядом
    с exe, либо на пару game/+lib/ (стандартная поставка Ren'Py SDK),
    либо на .rpyc/.rpa в game/."""
    base = os.path.basename(exe_path).lower()
    if any(h in base for h in _RENPY_HINTS):
        return True
    root = os.path.dirname(exe_path)
    # Случай 1: рядом лежит SDK-папка renpy/
    if os.path.isdir(os.path.join(root, "renpy")):
        return True
    # Случай 2: классическая поставка Ren'Py — game/+lib/ рядом с exe
    game_sub = os.path.join(root, "game")
    lib_dir = os.path.join(root, "lib")
    if os.path.isdir(game_sub) and os.path.isdir(lib_dir):
        return True
    # Случай 3: .rpyc/.rpa прямо в game/ (надёжный признак Ren'Py)
    if os.path.isdir(game_sub):
        try:
            for fn in os.listdir(game_sub):
                if fn.endswith(".rpyc") or fn.endswith(".rpa"):
                    return True
        except OSError:
            pass
    return False


def cmdline_of(pid: int) -> list[str]:
    try:
        return psutil.Process(pid).cmdline()
    except (psutil.Error, OSError):
        return []


def is_main_chromium_process(cmdline: list[str]) -> bool:
    """У дочерних процессов Chromium (renderer, gpu, utility) в командной
    строке есть --type=...; главный (browser) процесс — без него.
    У NW.js-игры RPG Maker «главная» Game.exe именно одна."""
    return not any(a.startswith("--type=") for a in cmdline)


def debug_port_from_cmdline(cmdline: list[str]) -> int:
    """--remote-debugging-port=N (или через пробел) -> N."""
    for i, arg in enumerate(cmdline):
        if arg.startswith("--remote-debugging-port="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                return 0
        if arg == "--remote-debugging-port" and i + 1 < len(cmdline):
            try:
                return int(cmdline[i + 1])
            except ValueError:
                return 0
    return 0


def find_game_processes(engine_key: str,
                        game_dir: str = "") -> list[dict]:
    """Ищет запущенные процессы, похожие на игру данного движка.

    engine_key: 'rpgmaker' | 'renpy' ('twine' живёт в браузере — ищется
    через CDP, а не через psutil).
    Для RPG Maker возвращаются только ГЛАВНЫЕ процессы Game.exe
    (без renderer/gpu-детей Chromium).
    Возвращает [{"pid", "name", "exe", "port"}], exe внутри
    game_dir (если задан) идут первыми.
    """
    found: list[dict] = []
    norm_dir = os.path.normpath(game_dir).lower() if game_dir else ""
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = proc.info
            exe = info.get("exe") or ""
            name = (info.get("name") or "").lower()
            if not exe:
                continue
            match = False
            cmdline: list[str] = []
            if engine_key == "rpgmaker":
                if name in _RPGM_NAMES:
                    cmdline = cmdline_of(info["pid"])
                    match = is_main_chromium_process(cmdline)
            elif engine_key == "renpy":
                match = name.endswith(_RENPY_NAMES_SUFFIX) and \
                    _looks_like_renpy(exe, game_dir)
            if match:
                found.append({"pid": info["pid"], "name": info.get("name"),
                              "exe": exe,
                              "port": debug_port_from_cmdline(cmdline)})
        except (psutil.Error, OSError):
            continue
    if norm_dir:
        found.sort(key=lambda r: 0 if os.path.normpath(
            r["exe"]).lower().startswith(norm_dir) else 1)
    return found
