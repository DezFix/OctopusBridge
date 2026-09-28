# -*- coding: utf-8 -*-
"""Live-слой: всё, что управляет ЗАПУЩЕННОЙ игрой (Qt + CDP/Frida/HTTP).

Модульный монолит, слой 3:
- app/core — чистые парсеры/перевод/IO (без Qt, без сети);
- app/engines — detect/extract/apply/verify по движкам (без Qt);
- app/live — ЭТОТ пакет: щупальца, сессии, CDP-база (Qt разрешен);
- app/ui — интерфейс (Qt разрешен);
- app/transport — низкоуровневые транспорты (CDP-клиент с Qt-сигналами).

Правило: app/core и app/engines НЕ импортируют app/live.
Направление зависит только наружу: ui -> live -> engines -> core.
Падение щупальца не должно ронять приложение: live — за интерфейсом
Tentacle, сессия переживает пересоздание щупалец.
"""
from __future__ import annotations

from app.live.session import GameSession
from app.live.tentacle import LaunchResult, Tentacle

__all__ = ["GameSession", "LaunchResult", "Tentacle", "create_tentacle"]


def create_tentacle(engine_key: str) -> Tentacle | None:
    """Создаёт щупальце для движка (None — движок не поддерживается).

    Щупальца хранятся в модулях движков (app.engines.*).tentacle.
    """
    if engine_key in ("rpgmaker", "rpgmaker_asar"):
        # rpgmaker_asar — старые профили (до слияния движков)
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
