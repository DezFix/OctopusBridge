# -*- coding: utf-8 -*-
"""Поддержка RPG Maker в Electron-обёртке (данные внутри app.asar).

Игра — обычный проект RPG Maker MV/MZ (project/data/*.json, js/rmmz_*.js),
упакованный в ASAR-архив Electron (resources/app.asar).
"""
from __future__ import annotations

import contextlib
import os
import tempfile

from app.core import asar

PROJECT_PREFIX = "project"


def asar_path(game_dir: str) -> str:
    return os.path.join(game_dir, "resources", "app.asar")


def detect_variant(game_dir: str) -> str:
    """Движок внутри asar: 'mz' | 'mv' | '' ('' — не Electron-игра)."""
    try:
        ar = asar.AsarArchive(asar_path(game_dir))
    except (OSError, asar.AsarError):
        return ""
    if ar.find(f"{PROJECT_PREFIX}/game.rmmzproject") \
            and ar.find(f"{PROJECT_PREFIX}/js/rmmz_core.js"):
        return "mz"
    if ar.find(f"{PROJECT_PREFIX}/js/rpg_core.js"):
        return "mv"
    return ""


@contextlib.contextmanager
def _temp_project(game_dir: str):
    """Временный проект: data/*.json и js/plugins из asar."""
    with tempfile.TemporaryDirectory(prefix="ob_asar_") as td:
        ar = asar.AsarArchive(asar_path(game_dir))
        proj = os.path.join(td, PROJECT_PREFIX)
        data_dir = os.path.join(proj, "data")
        os.makedirs(data_dir)
        ar.extract_prefix(f"{PROJECT_PREFIX}/data", data_dir)
        # js-плагины: список включённых (plugins.js) и сами файлы
        js_dir = os.path.join(proj, "js")
        os.makedirs(js_dir, exist_ok=True)
        blob = ar.read_file(f"{PROJECT_PREFIX}/js/plugins.js")
        if blob is not None:
            with open(os.path.join(js_dir, "plugins.js"), "wb") as f:
                f.write(blob)
        ar.extract_prefix(f"{PROJECT_PREFIX}/js/plugins",
                          os.path.join(js_dir, "plugins"))
        yield proj
