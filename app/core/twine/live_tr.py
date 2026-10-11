# -*- coding: utf-8 -*-
"""Память live-перевода Twine: переводы, которые игра уже показала.

Зачем. Live-перевод ходит в сеть за каждой новой строкой, и игрок видит
это как «часть текста переводится сразу, часть — через пару секунд».
На самом деле мгновенно выходит только то, что уже есть в словаре
проекта или в памяти сессии. Но результат нигде не сохранялся, поэтому
при каждом запуске игры все строки снова уходили в сеть.

Здесь копится словарь `оригинал -> перевод` по играм. Он НЕ трогает
проект `.ob.json`: его пишет вкладка перевода, и подмешиваться туда из
WS-потока — верный способ портить файл. Своё хранилище, атомарная
запись, ничего не блокируется.

Модуль чистый: без Qt, без сети.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

#: не храним вечно: 180 дней — за это время переводы могли устареть
MAX_AGE_S = 180 * 24 * 3600
#: файл больше этого — считаем, что раздулся (игра с 100k строк)
MAX_BYTES = 8 * 1024 * 1024
_NAME = "twine_tr"


def memory_dir() -> str:
    from app import user_data_dir

    return os.path.join(user_data_dir(), _NAME)


def memory_path(game_dir: str) -> str:
    """Путь памяти переводов для игры (по пути — безопасно для кириллицы)."""
    key = os.path.normcase(os.path.abspath(game_dir or ""))
    digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()[:16]
    stem = "".join(c for c in os.path.basename(key) if c.isalnum())[:40]
    return os.path.join(memory_dir(), "%s-%s.json" % (stem or "game", digest))


def load(game_dir: str) -> dict:
    """Словарь из памяти. Битый/чужой/старый файл — просто пусто."""
    path = memory_path(game_dir)
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return {}
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(obj, dict):
        return {}
    items = obj.get("items")
    if not isinstance(items, dict):
        return {}
    return {str(k): str(v) for k, v in items.items()
            if isinstance(v, str) and v}


def add(game_dir: str, pairs: dict, max_new: int = 400) -> int:
    """Дописать переводы в память. Возвращает, сколько добавилось.

    Пишем сразу, без «окон»: игра отдаёт батч, когда встретила новый
    текст, а не каждый кадр. Если копить и писать раз в 10 секунд, то в
    медленной игре переводы просто терялись бы — и на следующем запуске
    всё снова пошло бы в сеть. Принятый перевод не перебиваем никогда.
    """
    clean = {}
    for k, v in (pairs or {}).items():
        k, v = str(k or ""), str(v or "")
        if k and v and k != v:
            clean[k] = v
    if not clean:
        return 0
    path = memory_path(game_dir)
    now = int(time.time())
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            obj = {}
    except (OSError, ValueError):
        obj = {}
    items = obj.get("items")
    if not isinstance(items, dict):
        items = {}
    items = {str(k): str(v) for k, v in items.items() if isinstance(v, str)}

    added = 0
    for k, v in clean.items():
        if k in items:
            continue    # уже есть: принятый перевод не перебиваем
        items[k] = v
        added += 1
        if added >= max_new:
            break
    if not added:
        return 0

    from app.core.io import atomic_write_bytes

    payload = json.dumps({"at": now, "items": items},
                         ensure_ascii=False, indent=0)
    try:
        atomic_write_bytes(path, payload.encode("utf-8"))
    except OSError:
        return 0
    return added
