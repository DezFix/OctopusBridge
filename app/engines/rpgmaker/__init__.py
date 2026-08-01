# -*- coding: utf-8 -*-
"""Модуль RPG Maker MV/MZ — извлечение, внедрение, живое подключение.

Весь функционал RPG Maker хранится в этой папке:
- parser: извлечение/внедрение текста в data/*.json
- crypto: расшифровка ресурсов
- fontpatch: замена шрифта на кириллический
- varnames: имена переменных/переключателей
- maprender: данные для карт
- textwrap: подгонка текста под рамки диалогов
- tentacle: CDP-подключение к живой игре
"""
from __future__ import annotations

from app.engines.base import EngineModule
from app.ui.i18n import TR


class RpgMakerModule(EngineModule):
    key = "rpgmaker"
    title = "RPG Maker"
    features = {"files", "live", "cheats", "resources", "font", "maps"}

    @classmethod
    def detect(cls, game_dir: str) -> int:
        from . import parser
        engine = parser.detect_engine(game_dir)
        if engine == "mz":
            return 100
        if engine == "mv":
            return 90
        return 0

    def __init__(self, game_dir: str):
        from . import parser
        self.variant = parser.detect_engine(game_dir)

    @property
    def display(self) -> str:
        return f"RPG Maker {self.variant.upper()}"

    def extract(self, game_dir: str) -> list:
        from . import parser
        return parser.extract(game_dir)

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        from . import parser
        return parser.apply(game_dir, entries,
                            target_lang=kwargs.get("target_lang", "ru"))

    def ui_tabs(self, main_window) -> list[tuple]:
        from app.ui.cheat_tab import CheatTab
        from app.ui.map_tab import MapTab
        from app.ui.resource_tab import ResourceTab
        translate = main_window.translate_tab
        cheats = CheatTab(main_window)
        maps = MapTab(main_window)
        resources = ResourceTab(main_window)
        main_window.cheat_tab = cheats
        return [
            (translate, TR("tab_translate"), "translate"),
            (cheats, TR("tab_cheats"), "cheats"),
            (maps, TR("tab_maps"), "module"),
            (resources, TR("tab_resources"), "module"),
        ]
