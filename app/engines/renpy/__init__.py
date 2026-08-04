# -*- coding: utf-8 -*-
"""Модуль Ren'Py — извлечение текста, агент для живого перевода."""
from __future__ import annotations

from app.engines.base import EngineModule
from app.ui.i18n import TR


class RenPyModule(EngineModule):
    key = "renpy"
    title = "Ren'Py"
    features = {"files", "live", "cheats", "resources", "font"}

    @classmethod
    def detect(cls, game_dir: str) -> int:
        import os
        # game/ subdirectory with .rpy files or renpy SDK
        game_sub = os.path.join(game_dir, "game")
        if os.path.isdir(game_sub):
            for f in os.listdir(game_sub):
                if f.endswith(".rpy"):
                    return 80
        renpy_dir = os.path.join(game_dir, "renpy")
        if os.path.isdir(renpy_dir):
            return 70
        return 0

    def __init__(self, game_dir: str):
        pass

    @property
    def display(self) -> str:
        return "Ren'Py"

    def extract(self, game_dir: str) -> list:
        from app.core.renpy import parser
        return parser.extract(game_dir)

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        from app.core.renpy import parser
        return parser.apply(game_dir, entries,
                            target_lang=kwargs.get("target_lang", "ru"))

    def ui_tabs(self, main_window) -> list[tuple]:
        from app.ui.renpy_cheat_tab import VariablesTab, TriggersTab
        from app.ui.resource_tab import ResourceTab
        translate = main_window.translate_tab
        var_tab = VariablesTab(main_window)
        trg_tab = TriggersTab(main_window)
        resources = ResourceTab(main_window)
        main_window.cheat_tab = var_tab
        return [
            (translate, TR("tab_translate"), "translate"),
            (var_tab, TR("tab_cheats"), "cheats"),
            (trg_tab, TR("tab_triggers"), "triggers"),
            (resources, TR("tab_resources"), "module"),
        ]
