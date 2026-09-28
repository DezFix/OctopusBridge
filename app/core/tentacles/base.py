# -*- coding: utf-8 -*-
"""DEPRECATED shim: live-классы переехали в app/live/tentacle.py.

Оставлен для совместимости импортов. Новый код — `from app.live ...`.
"""
from __future__ import annotations

from app.live.tentacle import LaunchResult, Tentacle

__all__ = ["LaunchResult", "Tentacle"]
