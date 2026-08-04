# -*- coding: utf-8 -*-
"""Фабрика щупалец: движок -> канал управления живым процессом игры."""
from __future__ import annotations

from app.core.tentacles.base import Tentacle


def create_tentacle(engine_key: str) -> Tentacle | None:
    """Создаёт щупальце для движка (None — движок не поддерживается).

    Щупальца хранятся в модулях движков (app.engines.*).tentacle,
    но фабрика осталась здесь для обратной совместимости.
    """
    if engine_key == "rpgmaker":
        from app.engines.rpgmaker.tentacle import RpgMakerTentacle
        return RpgMakerTentacle()
    if engine_key == "renpy":
        from app.engines.renpy.tentacle import RenPyTentacle
        return RenPyTentacle()
    if engine_key == "twine":
        from app.engines.twine.tentacle import TwineTentacle
        return TwineTentacle()
    if engine_key == "tyrano":
        from app.engines.tyrano.tentacle import TyranoTentacle
        return TyranoTentacle()
    return None
