# -*- coding: utf-8 -*-
"""Реестр движковых модулей. Новый движок = новый класс в этом списке."""
from __future__ import annotations

from app.engines.base import EngineModule
from app.engines.renpy import RenPyModule
from app.engines.rpgmaker import RpgMakerModule
from app.engines.twine import TwineModule

MODULES: list[type[EngineModule]] = [RpgMakerModule, RenPyModule, TwineModule]


def detect_engine(game_dir: str) -> EngineModule | None:
    """Определяет движок игры и возвращает его модуль (или None)."""
    best_cls = None
    best_weight = 0
    for cls in MODULES:
        weight = cls.detect(game_dir)
        if weight > best_weight:
            best_cls, best_weight = cls, weight
    return best_cls(game_dir) if best_cls else None
