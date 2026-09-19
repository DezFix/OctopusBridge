# -*- coding: utf-8 -*-
"""Раскладка AjinSyoujyo: поиск Electron+asar+override без чтения текста игры.

Здесь только структура: имена файлов, JSON-шапка package.json
(поля window/main, не сценарии), маркеры main.js. Содержимое
data/scenario/*.ks НЕ читается — им занимается parser.py через
слоёный доступ и только по запросу извлечения.
"""
from __future__ import annotations

import json
import os

ASAR_REL = os.path.join("resources", "app.asar")
APP_DIR_REL = os.path.join("resources", "app")
PACKAGE_REL = os.path.join("resources", "app", "package.json")
MAIN_JS_REL = os.path.join("resources", "app", "main.js")
OVERRIDE_REL = os.path.join("resources", "app", "override")

# маркеры main.js патч-сборки (перехват file:// + override-карта)
_MAIN_JS_MARKERS = (
    "interceptFileProtocol",
    "overrides",
    "app.asar",
)

# суффиксы сейвов рядом с exe (структура, не содержимое)
_SAVE_SUFFIXES = (".sav",)


def _read_text_head(path: str, limit: int = 65536) -> str:
    """Первые limit байт текстового файла (для маркеров, не для сценариев)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(limit)
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return ""


def find_exe(game_dir: str) -> str | None:
    """Исполняемый файл игры в корне (первый *.exe, кроме uninstall)."""
    try:
        names = sorted(os.listdir(game_dir))
    except OSError:
        return None
    cands = [n for n in names
             if n.lower().endswith(".exe")
             and "uninstall" not in n.lower()]
    if not cands:
        return None
    # предпочитаем exe, совпадающий с именем папки игры
    base = os.path.basename(os.path.normpath(game_dir)).lower()
    for n in cands:
        if os.path.splitext(n)[0].lower() in (base, base.replace("_", "")):
            return os.path.join(game_dir, n)
    return os.path.join(game_dir, cands[0])


def asar_path(game_dir: str) -> str | None:
    p = os.path.join(game_dir, ASAR_REL)
    return p if os.path.isfile(p) else None


def override_dir(game_dir: str) -> str | None:
    p = os.path.join(game_dir, OVERRIDE_REL)
    return p if os.path.isdir(p) else None


def package_info(game_dir: str) -> dict:
    """Шапка package.json (name/main/window). Пустой dict при отсутствии."""
    p = os.path.join(game_dir, PACKAGE_REL)
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def has_override_interceptor(game_dir: str) -> bool:
    """main.js содержит перехват file:// -> override (маркер патч-сборки)."""
    head = _read_text_head(os.path.join(game_dir, MAIN_JS_REL))
    return bool(head) and all(m in head for m in _MAIN_JS_MARKERS)


def has_saves(game_dir: str) -> bool:
    """Рядом с exe есть *.sav (структурный признак, содержимое не читаем)."""
    try:
        for n in os.listdir(game_dir):
            if n.lower().endswith(_SAVE_SUFFIXES):
                return True
    except OSError:
        return False
    return False


def layout(game_dir: str) -> dict:
    """Сводка раскладки (для detect()/диагностики, без чтения сценариев)."""
    exe = find_exe(game_dir)
    asar = asar_path(game_dir)
    ovr = override_dir(game_dir)
    pkg = package_info(game_dir)
    return {
        "exe": exe,
        "asar": asar,
        "override": ovr,
        "package_name": str(pkg.get("name", "")),
        "package_main": str(pkg.get("main", "")),
        "has_interceptor": has_override_interceptor(game_dir),
        "has_saves": has_saves(game_dir),
    }
