# -*- coding: utf-8 -*-
"""Обратная совместимость: agent_source перенесён в app.engines.renpy.agent."""
from app.engines.renpy.agent import agent_source  # noqa: F401

__all__ = ["agent_source"]
