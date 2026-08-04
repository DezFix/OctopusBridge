# -*- coding: utf-8 -*-
"""Модуль TyranoScript / TyranoBuilder — извлечение, внедрение, живой перевод.

Весь функционал Tyrano хранится в этой папке:
- core/tyrano/parser: извлечение/внедрение текста в data/scenario/*.ks
- tentacle: CDP-подключение к живой игре (NW.js/Chromium) — перевод
  текста в DOM, переменные, консоль
"""
from __future__ import annotations

from app.engines.base import EngineModule
from app.ui.i18n import TR


class TyranoModule(EngineModule):
    key = "tyrano"
    title = "TyranoScript"
    variant = ""                # 'tyranoscript' | 'tyranobuilder' — не различаем
    # в переменных движка (kag.variables/kag.tmp) только внутренний
    # конфиг (громкость, галерея CG) — вкладка читов не нужна
    features = {"files", "live"}

    @classmethod
    def detect(cls, game_dir: str) -> int:
        from app.core.tyrano import parser
        return parser.detect(game_dir)

    def __init__(self, game_dir: str):
        pass

    @property
    def display(self) -> str:
        return "TyranoScript"

    def extract(self, game_dir: str) -> list:
        from app.core.tyrano import parser
        return parser.extract(game_dir)

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        from app.core.tyrano import parser
        return parser.apply(game_dir, entries,
                            target_lang=kwargs.get("target_lang", "ru"))

    def ui_tabs(self, main_window) -> list[tuple]:
        translate = main_window.translate_tab
        return [
            (translate, TR("tab_translate"), "translate"),
        ]
