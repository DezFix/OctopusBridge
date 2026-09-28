# -*- coding: utf-8 -*-
"""Базовый класс движкового модуля (модульный монолит).

Слой 1 — чистый протокол (app.engines.protocol.EngineParser):
detect/extract/apply/verify без Qt, без UI, без live.
Слой 2 — EngineModule: тонкий адаптер для старого UI
(ui_tabs/file_view). Новый код UI должен идти через
app.ui.engine_tabs, а не через движок.
"""
from __future__ import annotations

from abc import abstractmethod

from app.engines.protocol import EngineParser


class EngineModule(EngineParser):
    key: str = "base"                 # 'rpgmaker', 'renpy', ...
    title: str = "Базовый движок"
    variant: str = ""                 # уточнение версии: 'mz', 'mv', ...
    # возможности: 'cheats', 'resources', 'font', 'files'
    features: set[str] = {"files"}

    @classmethod
    @abstractmethod
    def detect(cls, game_dir: str) -> int:
        """Вес совпадения: 0 — не наш движок, больше — увереннее."""

    @abstractmethod
    def extract(self, game_dir: str) -> list:
        """Извлечь переводимые строки -> list[TranslationEntry]."""

    @abstractmethod
    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        """Внедрить переводы. Возвращает статистику."""

    def ui_tabs(self, main_window) -> list[tuple]:
        """DEPRECATED: движок не должен знать про Qt.

        Оставлен для совместимости. Новый код — app.ui.engine_tabs.
        """
        return []

    def file_view(self, game_dir: str):
        """Файловый доступ для вкладок движка (по умолчанию — диск).

        Без статического импорта rpgmaker: база ничего не знает
        о конкретных движках (иначе граница пробита).
        """
        from app.core.rpgmaker.fileview import DiskFileView
        return DiskFileView(game_dir)
