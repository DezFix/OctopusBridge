# -*- coding: utf-8 -*-
"""Общие пути приложения.

В сборке PyInstaller __file__ указывает во временную папку распаковки,
поэтому все пути считаем через эти хелперы:

- bundle_dir():  папка ресурсов (внутри exe / рядом с исходниками);
- user_data_dir(): пользовательские данные — %APPDATA%\\OctopusBridge
  (проекты, база перевода, crash.log), переживают переустановку;
- icon_path(): иконка приложения.
"""
from __future__ import annotations

import os
import sys

__version__ = "0.6.3"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> str:
    """Папка, где лежат ресурсы приложения (распакованный exe / репозиторий)."""
    if is_frozen():
        return sys._MEIPASS  # noqa: SLF001
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def user_data_dir() -> str:
    """Папка пользовательских данных (создаётся при необходимости)."""
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "OctopusBridge")
    os.makedirs(d, exist_ok=True)
    return d


def projects_dir() -> str:
    """Папка проектов (.ob.json, tm.sqlite, glossary.json)."""
    d = os.path.join(user_data_dir(), "projects")
    os.makedirs(d, exist_ok=True)
    return d


def icon_path() -> str:
    return os.path.join(bundle_dir(), "ico.ico")


def crash_log_path() -> str:
    return os.path.join(user_data_dir(), "crash.log")
