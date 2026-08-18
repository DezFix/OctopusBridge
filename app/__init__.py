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

__version__ = "7.1"


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
    """Папка проектов (.ob.json, tm.sqlite)."""
    d = os.path.join(user_data_dir(), "projects")
    os.makedirs(d, exist_ok=True)
    return d


def temp_dir() -> str:
    """Папка временных файлов (tmp-проекты, кеш)."""
    d = os.path.join(user_data_dir(), "temp")
    os.makedirs(d, exist_ok=True)
    return d


def glossary_dir() -> str:
    """Папка глоссария (glossary.json)."""
    d = os.path.join(user_data_dir(), "glossary")
    os.makedirs(d, exist_ok=True)
    return d


def migrate_appdata() -> None:
    """Одноразовая миграция старой структуры %APPDATA%\\OctopusBridge:

    - glossary.json из корня/проектов -> glossary\\glossary.json;
    - временные проекты tmp*.ob.json из projects\\ -> temp\\.
    """
    root = user_data_dir()
    for src in (os.path.join(root, "glossary.json"),
                os.path.join(projects_dir(), "glossary.json")):
        if os.path.isfile(src):
            try:
                os.replace(src, os.path.join(glossary_dir(), "glossary.json"))
            except OSError:
                pass
    proj = os.path.join(root, "projects")
    if os.path.isdir(proj):
        for name in os.listdir(proj):
            if name.startswith("tmp") and name.endswith(".ob.json"):
                try:
                    os.replace(os.path.join(proj, name),
                               os.path.join(temp_dir(), name))
                except OSError:
                    pass


def icon_path() -> str:
    return os.path.join(bundle_dir(), "assets", "ico.ico")


def crash_log_path() -> str:
    return os.path.join(user_data_dir(), "crash.log")
