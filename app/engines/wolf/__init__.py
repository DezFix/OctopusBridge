# -*- coding: utf-8 -*-
"""Модуль Wolf RPG Editor (Woditor) — извлечение, внедрение, запуск.

Структура игры: Game.exe + Game.ini + Data/*.wolf (DXA-v8 архивы).
Текст: BasicData.wolf (Game.dat, *Database.dat, CommonEvent.dat),
MapData.wolf (*.mps). Внедрение — loose-файлы Data/<Папка>/<inner>
с бэкапом .wolf (перепаковка архива не требуется). Читов нет
(нативный процесс без канала); шрифт — заменой TTF в корне игры.
Статус: экспериментальный (покрытие проверено на vd23-подобных
сборках с 32-байтным ключом; другие ключи/версии — best-effort).
"""
from __future__ import annotations

from app.engines.base import EngineModule
from app.ui.i18n import TR


class WolfModule(EngineModule):
    key = "wolf"
    title = "Wolf RPG"
    variant = ""
    features = {"files", "font"}

    @classmethod
    def detect(cls, game_dir: str) -> int:
        from app.core.wolf import parser
        return parser.detect(game_dir)

    def __init__(self, game_dir: str):
        pass

    @property
    def display(self) -> str:
        return "Wolf RPG"

    def extract(self, game_dir: str) -> list:
        from app.core.wolf import parser
        return parser.extract(game_dir)

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        from app.core.wolf import parser
        return parser.apply(game_dir, entries,
                            target_lang=kwargs.get("target_lang", "ru"))

    def restore_original(self, game_dir: str) -> dict:
        from app.core.wolf import parser
        return parser.restore_original(game_dir)

    def ui_tabs(self, main_window) -> list[tuple]:
        translate = main_window.translate_tab
        return [
            (translate, TR("tab_translate"), "translate"),
        ]
