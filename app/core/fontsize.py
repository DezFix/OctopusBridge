# -*- coding: utf-8 -*-
"""Регулировка размера шрифта игры (без смены шрифта).

Где лежит размер текста:
- RPG Maker MZ:  data/System.json -> advanced.fontSize (читается через
  $gameSystem.mainFontSize()); у части игр — js/rmmz_windows.js,
  Window_Base.prototype.standardFontSize (return 28);
- RPG Maker MV:  www/js/rpg_windows.js — Window_Base.prototype.
  standardFontSize (return 28);
- Ren'Py:        game/gui.rpy — define gui.text_size = 33.
- AjinSyoujyo:  data/scenario/first.ks — [deffont size=42 ...]
  (базовый кегль сообщений Tyrano). Чтение слоистое (override/
  поверх app.asar), запись только в override/.

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

# Кегль Tyrano задаётся в ДВУХ местах (оба читаются при старте):
# - data/scenario/first.ks: [deffont size=42 ...] (дефолт сообщений);
# - data/system/Config.tjs: defaultFontSize=37 (им kag.js init
#   перезаписывает default_font + считает line-height для руби).
# Патчим ОБА (только ПЕРВОЕ вхождение в каждом файле; поздние
# режиссёрские [deffont] в сценариях не трогаем). Чтение слоистое
# (override/ поверх app.asar), запись только в override/.
_RE_AJIN_DEFFONT = re.compile(
    r"(\[deffont\b[^\]]*?\bsize\s*=\s*)(\d+)", re.IGNORECASE)
_RE_AJIN_CONFIG_SIZE = re.compile(r"(defaultFontSize\s*=\s*)(\d+)")

AJIN_FIRST_KS = "data/scenario/first.ks"
AJIN_CONFIG_TJS = "data/system/Config.tjs"
# (rel, regex, подпись): порядок = приоритет чтения для UI
_AJIN_SIZE_FILES = (
    (AJIN_FIRST_KS, _RE_AJIN_DEFFONT, "first.ks"),
    (AJIN_CONFIG_TJS, _RE_AJIN_CONFIG_SIZE, "Config.tjs"),
)


def _ajin_override_path(game_dir: str, rel: str) -> str:
    from app.core.ajin import layout as layout_mod
    return os.path.join(game_dir, layout_mod.OVERRIDE_REL,
                        *rel.split("/"))


def _ajin_size_of_text(text: str, pat) -> int | None:
    m = pat.search(text)
    return int(m.group(2)) if m else None


def _ajin_read_size(game_dir: str) -> int | None:
    """Первый найденный кегль (first.ks, иначе Config.tjs) или None."""
    from app.core.ajin.layered import LayeredView
    try:
        view = LayeredView(game_dir)
    except (OSError, ValueError):
        return None
    for rel, pat, _label in _AJIN_SIZE_FILES:
        try:
            raw = view.read_bytes(rel)
        except OSError:
            continue
        if raw is None:
            continue
        try:
            text = raw.decode("utf-8-sig")
        except (UnicodeDecodeError, ValueError):
            try:
                text = raw.decode("cp932")
            except (UnicodeDecodeError, ValueError):
                continue
        size = _ajin_size_of_text(text, pat)
        if size is not None:
            return size
    return None


def _ajin_ensure_override(view, game_dir: str, rel: str) -> str:
    """Физический override-путь с бэкапом asar-оригинала при создании."""
    out_path = _ajin_override_path(game_dir, rel)
    if view.has_override(rel):
        _backup(out_path)
        return out_path
    raw = view.read_bytes(rel)
    if raw is None:
        raise FileNotFoundError(f"Не удалось прочитать {rel} из app.asar")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path + BACKUP_SUFFIX, "wb") as f:
        f.write(raw)
    return out_path


def _set_ajin(game_dir: str, size: int) -> dict:
    from app.core.ajin.layered import LayeredView
    try:
        view = LayeredView(game_dir)
    except (OSError, ValueError) as e:
        raise FileNotFoundError(f"Нет доступа к файлам игры: {e}")
    changed: list[str] = []
    for rel, pat, label in _AJIN_SIZE_FILES:
        if not view.exists(rel):
            continue
        try:
            lines = view.read_lines(rel)
        except (OSError, UnicodeDecodeError):
            continue
        idx = next((i for i, ln in enumerate(lines)
                    if pat.search(ln)), None)
        if idx is None:
            continue
        out_path = _ajin_ensure_override(view, game_dir, rel)
        lines[idx] = pat.sub(lambda m: m.group(1) + str(size),
                             lines[idx], count=1)
        view.write_lines(rel, lines)
        changed.append(f"{label}→{os.path.basename(out_path)}")
    if not changed:
        raise FileNotFoundError(
            "Не найден [deffont size=...] / defaultFontSize в игре")
    return {"path": ", ".join(changed), "size": size}


def _ajin_restore(game_dir: str) -> bool:
    """Откат обоих файлов кегля. True — хоть один откачен."""
    ok = False
    for rel, _pat, _label in _AJIN_SIZE_FILES:
        backup = _ajin_override_path(game_dir, rel) + BACKUP_SUFFIX
        if os.path.isfile(backup):
            try:
                shutil.copy2(backup, backup[:-len(BACKUP_SUFFIX)])
                os.remove(backup)
            except OSError as e:
                raise RuntimeError(f"Не удалось восстановить {rel}: {e}")
            ok = True
    return ok


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
    if engine == "ajin":
        return _ajin_read_size(game_dir)
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
    if engine == "ajin":
        return _set_ajin(game_dir, size)
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
    if engine == "ajin":
        return _ajin_restore(game_dir)
    else:
        candidates = _renpy_candidates(game_dir) \
            if engine == "renpy" else [os.path.join(game_dir, "game",
                                                    "gui.rpy")]
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