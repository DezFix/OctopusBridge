# -*- coding: utf-8 -*-
"""Замена шрифтов Wolf RPG Editor на кириллический NotoSans.

Шрифты лежат в корне игры (*.ttf рядом с Game.exe, имена заданы
в Game.dat: font_base/sub1..3). Заменяются только файлы, в cmap
которых НЕТ кириллицы (U+0400–U+04FF). Оригиналы — в ob_fonts_orig/
(манифест manifest.json). restore_font() возвращает оригиналы.

Живое применение к запущенной игре невозможно (нативный exe без
канала в процесс) — шрифт вступает в силу после перезапуска игры.
"""
from __future__ import annotations

import json
import os
import shutil

FONT_EXTS = (".ttf", ".otf", ".ttc", ".otc")
ORIG_DIR = "ob_fonts_orig"
MANIFEST = "manifest.json"


def _bundled_font() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "assets",
                        "fonts", "NotoSans-Regular.ttf")


def _manifest_path(game_dir: str) -> str:
    return os.path.join(game_dir, ORIG_DIR, MANIFEST)


def _load_manifest(game_dir: str) -> dict:
    try:
        with open(_manifest_path(game_dir), encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_manifest(game_dir: str, m: dict) -> None:
    os.makedirs(os.path.join(game_dir, ORIG_DIR), exist_ok=True)
    with open(_manifest_path(game_dir), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1)


def _iter_fonts(game_dir: str):
    try:
        names = os.listdir(game_dir)
    except OSError:
        return
    for n in sorted(names):
        if n.lower().endswith(FONT_EXTS):
            yield os.path.join(game_dir, n)


def is_patched(game_dir: str) -> bool:
    return os.path.isfile(_manifest_path(game_dir))


def patch_font(game_dir: str, font_path: str | None = None) -> dict:
    """Заменяет шрифты без кириллицы (или все при своём font_path)."""
    if font_path:
        try:
            with open(font_path, "rb") as f:
                new_bytes = f.read()
        except OSError as e:
            raise RuntimeError(f"Не удалось прочитать свой шрифт: {e}")
    else:
        src = _bundled_font()
        if not os.path.isfile(src):
            raise RuntimeError("NotoSans-Regular.ttf не найден в комплекте")
        with open(src, "rb") as f:
            new_bytes = f.read()
    custom = bool(font_path)
    from app.core.renpy.fontpatch import font_supports_cyrillic
    manifest = _load_manifest(game_dir)
    patched: dict[str, str] = dict(manifest.get("patched", {}))
    replaced = 0
    orig_dir = os.path.join(game_dir, ORIG_DIR)
    os.makedirs(orig_dir, exist_ok=True)
    for path in _iter_fonts(game_dir):
        rel = os.path.basename(path)
        if not custom and font_supports_cyrillic(path):
            continue
        try:
            with open(path, "rb") as f:
                cur = f.read()
        except OSError as e:
            raise RuntimeError(f"Не удалось прочитать {rel}: {e}")
        if cur == new_bytes:
            continue
        if rel not in patched:
            back = f"_b{len(patched)}_{rel}"
            try:
                with open(os.path.join(orig_dir, back), "wb") as f:
                    f.write(cur)
            except OSError as e:
                raise RuntimeError(
                    f"Не удалось сохранить оригинал {rel}: {e}")
            patched[rel] = back
        try:
            with open(path, "wb") as f:
                f.write(new_bytes)
        except OSError:
            raise RuntimeError(
                "Не удалось перезаписать шрифт — закройте игру и повторите")
        replaced += 1
        _save_manifest(game_dir, {"patched": patched})
    return {"replaced": replaced, "total": len(patched)}


def restore_font(game_dir: str) -> bool:
    manifest = _load_manifest(game_dir)
    patched = manifest.get("patched", {})
    if not patched:
        return False
    orig_dir = os.path.join(game_dir, ORIG_DIR)
    for rel, back in patched.items():
        src = os.path.join(orig_dir, back)
        dst = os.path.join(game_dir, os.path.basename(rel))
        if os.path.isfile(src):
            try:
                shutil.copy2(src, dst)
            except OSError as e:
                raise RuntimeError(f"Не удалось восстановить {rel}: {e}")
    shutil.rmtree(orig_dir, ignore_errors=True)
    return True
