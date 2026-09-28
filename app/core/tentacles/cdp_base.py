# -*- coding: utf-8 -*-
"""DEPRECATED shim: CDP-база переехала в app/live/cdp_base.py.

Оставлен для совместимости импортов. Новый код — `from app.live ...`.
"""
from __future__ import annotations

from app.live.cdp_base import (
    BINDING_NAME,
    CONSOLE_PREFIX,
    DEFAULT_SCAN_PORTS,
    TRANSPORT_SHIM,
    CDPTentacle,
    bruteforce_port,
    cdp_page_is_game,
    probe_game_port,
)

__all__ = [
    "BINDING_NAME",
    "CONSOLE_PREFIX",
    "DEFAULT_SCAN_PORTS",
    "TRANSPORT_SHIM",
    "CDPTentacle",
    "bruteforce_port",
    "cdp_page_is_game",
    "probe_game_port",
]
