# -*- coding: utf-8 -*-
"""Обратная совместимость: модели вынесены в app.core.models."""
from app.core.models import TranslationEntry, Project

__all__ = ["TranslationEntry", "Project"]
