# -*- coding: utf-8 -*-
"""Реестр движковых модулей. Новый движок = новый класс в этом списке."""
from __future__ import annotations

from app.engines.base import EngineModule
from app.engines.ajin import AjinModule
from app.engines.renpy import RenPyModule
from app.engines.rpgmaker import RpgMakerModule
from app.engines.twine import TwineModule
from app.engines.tyrano import TyranoModule
from app.engines.unity import UnityModule
from app.engines.wolf import WolfModule

MODULES: list[type[EngineModule]] = [
    AjinModule, RpgMakerModule, RenPyModule, TwineModule, TyranoModule,
    WolfModule, UnityModule]

#: Отложенные движки: код и тесты на месте, но детект и интерфейс
#: их не видят — фокус на RPG Maker и Ren'Py. Вернуть движок =
#: убрать его ключ отсюда (ничего больше трогать не нужно).
DISABLED_ENGINES = frozenset({"ajin", "twine", "tyrano", "wolf", "unity"})


def enabled_modules() -> list[type[EngineModule]]:
    """Модули, видимые детекту и интерфейсу."""
    return [cls for cls in MODULES if cls.key not in DISABLED_ENGINES]


def detect_engine(game_dir: str) -> EngineModule | None:
    """Определяет движок игры и возвращает его модуль (или None)."""
    best_cls = None
    best_weight = 0
    for cls in enabled_modules():
        weight = cls.detect(game_dir)
        if weight > best_weight:
            best_cls, best_weight = cls, weight
    return best_cls(game_dir) if best_cls else None
