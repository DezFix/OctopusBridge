# -*- coding: utf-8 -*-
"""Регулировка размера шрифта игры (без смены шрифта).

Где лежит размер текста:
- RPG Maker MZ:  data/System.json -> advanced.fontSize (читается через
  $gameSystem.mainFontSize()); у части игр — js/rmmz_windows.js,
  Window_Base.prototype.standardFontSize (return 28);
- RPG Maker MV:  www/js/rpg_windows.js — Window_Base.prototype.
  standardFontSize (return 28);
- Ren'Py:        game/gui.rpy — define gui.text_size = 33.

Оригинал файла бэкапится рядом (*.ob_backup), повторные правки идут по
актуальному содержимому. Размер ограничен разумными пределами, чтобы
не сломать вёрстку окон (RPG Maker) и не растянуть интерфейс (Ren'Py).
"""
from __future__ import annotations

import json
import os
import re
import shutil

BACKUP_SUFFIX = ".ob_backup"
MIN_SIZE = 12
MAX_SIZE = 64

# Window_Base.prototype.standardFontSize = function() { return 28; };
_RE_RPGM_JS = re.compile(
    r"(standardFontSize\s*=\s*function\s*\(\s*\)\s*\{\s*return\s+)(\d+)")
# define gui.text_size = 33  (бывает default / просто gui.text_size,
# в т.ч. с отступом внутри init python:; \s* после ключевого слова —
# из-за особенности PyRE-движка Python 3.13, где ^\s* перед
# опциональной группой с \s+ ломает матч)
_RE_RENPY = re.compile(
    r"(^(?:define|default\s+)?\s*gui\.text_size\s*=\s*)(\d+)",
    re.MULTILINE)


RENPY_DEFAULT_SIZE = 33


def _renpy_candidates(game_dir: str) -> list[str]:
    """Файлы Ren'Py, где может задаваться gui.text_size."""
    return [os.path.join(game_dir, "game", "gui.rpy"),
            os.path.join(game_dir, "game", "screens.rpy")]


def _renpy_source(game_dir: str) -> tuple[str, str] | None:
    """(путь, текст) с gui.text_size для Ren'Py.

    Сначала ищет физические файлы, затем gui.rpy/screens.rpy внутри
    .rpa-архивов (архивированные игры). Для физического файла возвращает
    его же; для архивного — имя файла, куда запишем перекрывающую копию.
    Если исходника нет, но есть скомпилированный gui.rpyc — возвращает
    (game/gui.rpy, "") — ряд «Размер» показывается со стандартным
    значением, а первая правка создаёт перекрывающий gui.rpy.
    """
    for path in _renpy_candidates(game_dir):
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    return path, f.read()
            except OSError:
                continue
    try:
        from app.core.renpy.rpa import find_rpa_archives, RpaArchive
    except ImportError:
        return None
    has_rpyc = False
    for arch_path in find_rpa_archives(game_dir):
        try:
            arch = RpaArchive(arch_path)
        except ValueError:
            continue
        for name in ("gui.rpy", "screens.rpy"):
            if name not in arch.files:
                continue
            try:
                text = arch.read(name).decode("utf-8")
            except (KeyError, UnicodeDecodeError):
                continue
            return os.path.join(game_dir, "game", name), text
        for name in ("gui.rpyc", "screens.rpyc"):
            if any(n.endswith(name) for n in arch.files):
                has_rpyc = True
    if has_rpyc:
        return os.path.join(game_dir, "game", "gui.rpy"), ""
    return None


def _js_paths(game_dir: str, engine: str) -> list[str]:
    """Кандидаты в JS-файлы с standardFontSize (порядок = приоритет)."""
    if engine == "mv":
        return [os.path.join(game_dir, "www", "js", "rpg_windows.js"),
                os.path.join(game_dir, "js", "rpg_windows.js")]
    if engine == "mz":
        return [os.path.join(game_dir, "js", "rmmz_windows.js"),
                os.path.join(game_dir, "js", "rmmz_core.js")]
    return []


def _system_json(game_dir: str, engine: str) -> str:
    if engine != "mz":
        return ""
    return os.path.join(game_dir, "data", "System.json")


def _json_font_size(path: str) -> int | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    advanced = data.get("advanced") or {}
    size = advanced.get("fontSize")
    return int(size) if isinstance(size, int) else None


def _js_font_size(path: str, pat) -> int | None:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    return _js_font_size_text(text, pat)


def _js_font_size_text(text: str, pat) -> int | None:
    m = pat.search(text)
    return int(m.group(2)) if m else None


def get_font_size(game_dir: str, engine: str) -> int | None:
    """Текущий размер шрифта игры (из файла) или None, если не найден."""
    if engine == "renpy":
        src = _renpy_source(game_dir)
        if src is None:
            return None
        path, text = src
        if not text:
            return RENPY_DEFAULT_SIZE
        size = _js_font_size_text(text, _RE_RENPY)
        return size if size is not None else RENPY_DEFAULT_SIZE
    sys_json = _system_json(game_dir, engine)
    if sys_json and os.path.isfile(sys_json):
        size = _json_font_size(sys_json)
        if size is not None:
            return size
    for path in _js_paths(game_dir, engine):
        if not os.path.isfile(path):
            continue
        size = _js_font_size(path, _RE_RPGM_JS)
        if size is not None:
            return size
    return None


def set_font_size(game_dir: str, engine: str, size: int) -> dict:
    """Переписывает размер шрифта в файле игры. Возвращает отчёт."""
    size = max(MIN_SIZE, min(MAX_SIZE, int(size)))
    if engine == "renpy":
        return _set_renpy(game_dir, size)
    sys_json = _system_json(game_dir, engine)
    if sys_json and os.path.isfile(sys_json) and \
            _json_font_size(sys_json) is not None:
        return _set_json_font_size(sys_json, size)
    for path in _js_paths(game_dir, engine):
        if not os.path.isfile(path):
            continue
        if _js_font_size(path, _RE_RPGM_JS) is None:
            continue
        return _set_js_font_size(path, _RE_RPGM_JS, size)
    raise FileNotFoundError(
        "Не найден файл, задающий размер шрифта игры")


def _backup(path: str):
    backup = path + BACKUP_SUFFIX
    if not os.path.exists(backup):
        try:
            shutil.copy2(path, backup)
        except OSError as e:
            raise RuntimeError(f"Не удалось создать бэкап: {e}")
    return backup


def _set_json_font_size(path: str, size: int) -> dict:
    _backup(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise RuntimeError(f"Не удалось прочитать {path}: {e}")
    data.setdefault("advanced", {})["fontSize"] = size
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise RuntimeError(f"Не удалось записать {path}: {e}")
    return {"path": os.path.basename(path), "size": size}


def _set_js_font_size(path: str, pat, size: int) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise RuntimeError(f"Не удалось прочитать {path}: {e}")
    _backup(path)
    new = pat.sub(lambda m: m.group(1) + str(size), text)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    except OSError as e:
        raise RuntimeError(f"Не удалось записать {path}: {e}")
    return {"path": os.path.basename(path), "size": size}


def _set_renpy(game_dir: str, size: int) -> dict:
    src = _renpy_source(game_dir)
    if src is None:
        raise FileNotFoundError(
            "Не найден файл, задающий размер шрифта игры")
    path, text = src
    if not text:
        # Исходника нет (только .rpyc в архиве) — создаём перекрывающий
        # gui.rpy, который Ren'Py скомпилирует и выполнит ПОСЛЕДНИМ
        # (init offset перекрывает порядок архива).
        new = (f"# Created by OctopusBridge (in-game font size override)\n"
               f"init offset = 999999999\n\n"
               f"define gui.text_size = {size}\n")
    else:
        m = _RE_RENPY.search(text)
        if m is None:
            raise FileNotFoundError(
                "Не найден файл, задающий размер шрифта игры")
        _backup(path) if os.path.isfile(path) else None
        new = _RE_RENPY.sub(lambda mm: mm.group(1) + str(size), text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
    except OSError as e:
        raise RuntimeError(f"Не удалось записать {path}: {e}")
    return {"path": os.path.basename(path), "size": size}


def restore_font_size(game_dir: str, engine: str) -> bool:
    """Возвращает оригинал из бэкапа (True — откат выполнен)."""
    candidates = _renpy_candidates(game_dir) \
        if engine == "renpy" else [os.path.join(game_dir, "game", "gui.rpy")]
    sys_json = _system_json(game_dir, engine)
    if sys_json:
        candidates.append(sys_json)
    candidates += _js_paths(game_dir, engine)
    for path in candidates:
        backup = path + BACKUP_SUFFIX
        if os.path.isfile(backup):
            try:
                shutil.copy2(backup, path)
                os.remove(backup)
            except OSError as e:
                raise RuntimeError(f"Не удалось восстановить {path}: {e}")
            return True
    return False