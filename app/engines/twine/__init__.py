# -*- coding: utf-8 -*-
"""Модуль Twine (HTML5) — извлечение, внедрение, подключение, сейвы.

Функционал Twine:
- parser: извлечение/внедрение текста из/в .html
- savefile: чтение/запись SugarCube .save (LZ-String)
- tentacle: подключение к живой игре (Chromium-браузеры)
"""
from __future__ import annotations

import os

from app.engines.base import EngineModule
from app.ui.i18n import TR


class TwineModule(EngineModule):
    key = "twine"
    title = "Twine"
    features = {"files", "cheats"}

    @classmethod
    def detect(cls, game_dir: str) -> int:
        # Если это сам .html файл — проверяем сразу
        if os.path.isfile(game_dir) and game_dir.lower().endswith(".html"):
            try:
                with open(game_dir, encoding="utf-8", errors="ignore") as fh:
                    if "<tw-storydata" in fh.read(1024 * 1024):
                        return 60
            except OSError:
                pass
            return 0
        # Ищем .html с <tw-storydata в папке
        try:
            entries = os.listdir(game_dir)
        except OSError:
            return 0
        for f in entries:
            if not f.endswith(".html"):
                continue
            try:
                with open(os.path.join(game_dir, f), encoding="utf-8",
                          errors="ignore") as fh:
                    head = fh.read(1024 * 1024)
                    if "<tw-storydata" in head:
                        return 60
            except OSError:
                continue
        return 0

    def __init__(self, game_dir: str):
        self.game_path: str | None = None
        # Если game_dir — файл .html, запоминаем его
        if os.path.isfile(game_dir) and game_dir.lower().endswith(".html"):
            self.game_path = game_dir

    @property
    def display(self) -> str:
        return "Twine"

    def extract(self, game_dir: str) -> list:
        from app.core.twine import parser
        return parser.extract(game_dir)

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        from app.core.twine import parser
        return parser.apply(game_dir, entries)

    def ui_tabs(self, main_window) -> list[tuple]:
        from app.ui.save_editor_tab import SaveEditorTab
        translate = main_window.translate_tab
        save_tab = SaveEditorTab(main_window)
        # Переменные и триггеры для Twine не нужны: живого моста в
        # webapp-режиме нет, а правка .save — отдельный Save Editor.
        # (renpy_cheat_tab остаётся за Ren'Py — не трогать.)
        return [
            (translate, TR("tab_translate"), "translate"),
            (save_tab, TR("tab_save_editor"), "module"),
        ]
