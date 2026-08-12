# -*- coding: utf-8 -*-
"""Замена шрифта игры на шрифт с кириллицей.

MZ: шрифт задаётся в data/System.json -> advanced.mainFontFilename
    (FontManager грузит fonts/<имя файла>).
MV: шрифт задаётся в fonts/gamefont.css (@font-face GameFont).

Оригиналы бэкапятся рядом (*.ob_backup).
"""
from __future__ import annotations

import json
import os
import shutil

MZ_BACKUP_SUFFIX = ".ob_backup"


def patch_font_mz(game_dir: str, font_path: str) -> dict:
    """Копирует font_path в fonts/ и прописывает его в System.json (MZ)."""
    fonts_dir = os.path.join(game_dir, "fonts")
    system_json = os.path.join(game_dir, "data", "System.json")
    if not os.path.isdir(fonts_dir) or not os.path.exists(system_json):
        raise FileNotFoundError("Не найдены fonts/ или data/System.json")

    font_name = os.path.basename(font_path)
    shutil.copy2(font_path, os.path.join(fonts_dir, font_name))

    backup = system_json + MZ_BACKUP_SUFFIX
    if not os.path.exists(backup):
        shutil.copy2(system_json, backup)

    with open(system_json, encoding="utf-8") as f:
        data = json.load(f)
    advanced = data.setdefault("advanced", {})
    advanced["mainFontFilename"] = font_name
    advanced["numberFontFilename"] = font_name
    with open(system_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"font": font_name, "backup": backup}


def patch_font_mv(game_dir: str, font_path: str) -> dict:
    """Переписывает fonts/gamefont.css под новый шрифт (MV)."""
    fonts_dir = os.path.join(game_dir, "fonts")
    if not os.path.isdir(fonts_dir):
        # деплой MV: всё в www/
        fonts_dir = os.path.join(game_dir, "www", "fonts")
    if not os.path.isdir(fonts_dir):
        raise FileNotFoundError("Не найдена папка fonts/ (ищется и в www/)")

    font_name = os.path.basename(font_path)
    shutil.copy2(font_path, os.path.join(fonts_dir, font_name))

    css_path = os.path.join(fonts_dir, "gamefont.css")
    if os.path.exists(css_path) and not os.path.exists(css_path + MZ_BACKUP_SUFFIX):
        shutil.copy2(css_path, css_path + MZ_BACKUP_SUFFIX)
    with open(css_path, "w", encoding="utf-8") as f:
        f.write("@font-face {\n"
                "    font-family: GameFont;\n"
                f"    src: url(\"{font_name}\");\n"
                "}\n")
    return {"font": font_name, "css": css_path}


def patch_font(game_dir: str, engine: str, font_path: str) -> dict:
    if engine == "mv":
        return patch_font_mv(game_dir, font_path)
    return patch_font_mz(game_dir, font_path)
