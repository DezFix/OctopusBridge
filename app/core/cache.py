# -*- coding: utf-8 -*-
"""Кеш проектов: размер папки %APPDATA%\\OctopusBridge\\projects,
очистка временных проектов (tmp*.ob.json), автоочистка по порогу."""
from __future__ import annotations

import os

from app import projects_dir


def projects_size() -> tuple[int, int]:
    """Суммарный размер папки проектов в байтах и число файлов."""
    root = projects_dir()
    total = 0
    files = 0
    if not os.path.isdir(root):
        return 0, 0
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isfile(p):
            try:
                total += os.path.getsize(p)
            except OSError:
                continue
            files += 1
    return total, files


def is_tmp_project(name: str) -> bool:
    """Временный проект (обрывок/мусор) — имя начинается с 'tmp'."""
    return name.startswith("tmp") and name.endswith(".ob.json")


def clean_cache() -> int:
    """Удаляет временные проекты tmp*.ob.json. Возвращает байты."""
    root = projects_dir()
    freed = 0
    if not os.path.isdir(root):
        return 0
    for name in os.listdir(root):
        if not is_tmp_project(name):
            continue
        p = os.path.join(root, name)
        try:
            freed += os.path.getsize(p)
            os.remove(p)
        except OSError:
            pass
    return freed


def maybe_auto_clean(settings) -> bool:
    """Автоочистка при старте: если размер кеша превысил порог (МБ)
    и автоочистка включена — удаляет временные проекты."""
    if not settings.value("cache_auto_clean", False, type=bool):
        return False
    limit_mb = settings.value("cache_auto_clean_mb", 200, type=int)
    total, _ = projects_size()
    if total <= limit_mb * 1024 * 1024:
        return False
    return clean_cache() > 0


def format_size(bytes_: int, lang: str = "ru") -> str:
    """Человекочитаемый размер: '12.3 МБ' / '1.2 ГБ'."""
    unit = "МБ" if lang == "ru" else "MB"
    gb = "ГБ" if lang == "ru" else "GB"
    if bytes_ >= 1024 ** 3:
        return f"{bytes_ / 1024 ** 3:.2f} {gb}"
    return f"{bytes_ / 1024 ** 2:.1f} {unit}"