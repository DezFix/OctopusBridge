# -*- coding: utf-8 -*-
"""Модуль Ren'Py — извлечение текста, агент для подключения."""
from __future__ import annotations

from app.engines.base import EngineModule
from app.ui.i18n import TR


class RenPyModule(EngineModule):
    key = "renpy"
    title = "Ren'Py"
    features = {"files", "cheats", "resources", "font", "langs"}

    @classmethod
    def detect(cls, game_dir: str) -> int:
        import os
        # Реальные игры почти всегда без .rpy: только скомпилированные
        # .rpyc (в т.ч. внутри .rpa). Раньше здесь проверялись только
        # .rpy в корне game/ — такие игры не распознавались вовсе.
        game_sub = os.path.join(game_dir, "game")
        best = 0
        if os.path.isdir(game_sub):
            for _root, _dirs, files in os.walk(game_sub):
                for f in files:
                    if f.endswith(".rpy"):
                        return 80
                    if f.endswith(".rpyc") and best < 75:
                        best = 75
                    if f.lower().endswith(".rpa") and best < 70:
                        best = 70
        if best:
            return best
        renpy_dir = os.path.join(game_dir, "renpy")
        if os.path.isdir(renpy_dir):
            return 60
        return 0

    def __init__(self, game_dir: str):
        pass

    @property
    def display(self) -> str:
        return "Ren'Py"

    def extract(self, game_dir: str, extract_lang: str | None = None) -> list:
        from app.core.renpy import parser
        return parser.extract(game_dir, extract_lang)

    def list_languages(self, game_dir: str) -> list[str]:
        """Языки официальных переводов игры (game/tl/* на диске и в RPA)."""
        from app.core.renpy import parser
        return parser.list_languages(game_dir)

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
