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
    if engine_key == "rpgmaker_asar":
        # старые профили (до слияния движков) — то же щупальце RPG Maker
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
    if engine_key == "ajin":
        from app.engines.ajin.tentacle import AjinTentacle
        return AjinTentacle()
    if engine_key == "wolf":
        from app.engines.wolf.tentacle import WolfTentacle
        return WolfTentacle()
    if engine_key == "unity":
        from app.engines.unity.tentacle import UnityTentacle
        return UnityTentacle()
    return None
