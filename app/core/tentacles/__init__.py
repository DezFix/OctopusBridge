# -*- coding: utf-8 -*-
"""DEPRECATED shim: фабрика щупалец переехала в app/live.

Оставлен для совместимости импортов. Новый код — `from app.live ...`.
"""
from __future__ import annotations

from app.live import Tentacle, create_tentacle

__all__ = ["Tentacle", "create_tentacle"]
