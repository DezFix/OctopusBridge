# -*- coding: utf-8 -*-
"""Базовый класс движкового модуля.

Ядро приложения (OctopusBridge) не знает деталей движков: каждый модуль
сам умеет определять свою игру, извлекать/внедрять текст и создавать
свои вкладки GUI. Чтобы добавить новый движок — создаём модуль здесь
и регистрируем в registry.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class EngineModule(ABC):
    key: str = "base"                 # 'rpgmaker', 'renpy', ...
    title: str = "Базовый движок"
    variant: str = ""                 # уточнение версии: 'mz', 'mv', ...
    # возможности: 'live', 'cheats', 'resources', 'font', 'files'
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
        """Движковые вкладки: [(widget, заголовок, роль)].
        Роль: 'live' | 'cheats' | 'module' — для профилей видимости."""
        return []
