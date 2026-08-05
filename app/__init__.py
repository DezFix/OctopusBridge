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

__version__ = "0.5.3"


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


def models_dir() -> str:
    """Каталог офлайн-моделей рядом с приложением (для автономной работы).

    Сборка: папка models/ рядом с exe; исходники: models/ в корне проекта.
    Пустая строка — каталог не существует (модели не установлены).
    """
    d = os.path.join(_app_base(), "models")
    return d if os.path.isdir(d) else ""


def ensure_honyaku_env() -> str:
    """Выбирает каталог офлайн-моделей и прописывает HONYAKU_MODEL_DIR.

    Приоритет — models/ рядом с приложением: приложение автономно,
    скачивание тоже идёт сюда. Если рядом писать нельзя (Program Files
    и т.п.) — оставляем стандартный каталог пользователя
    (%LOCALAPPDATA%/honyaku/models) и env не трогаем.
    Возвращает выбранный каталог ("" — стандартный пользовательский).
    """
    d = os.path.join(_app_base(), "models")
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".wtest")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        os.remove(probe)
    except OSError:
        return ""
    os.environ["HONYAKU_MODEL_DIR"] = d
    return d


def _app_base() -> str:
    """Папка рядом с приложением: exe (сборка) или корень проекта."""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def crash_log_path() -> str:
    return os.path.join(user_data_dir(), "crash.log")
