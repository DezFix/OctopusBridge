# -*- coding: utf-8 -*-
"""Единый кэш переводов всех движков (octopus_cache.json).

Единый формат файла (в папке игры, переносится вместе с ней):

    {
        "format": 1,              # версия формата
        "engine": "rpgmaker",     # движок игры
        "pairs": {"原文": "Перевод", ...},
        "skip": ["...", ...]      # необязательно: строки без перевода (identity)
    }

При чтении поддерживаются старые форматы (плоский словарь и файлы
tyrano_cache.json / .translation_cache.json / .octopus_cache.json) —
их переводы подхватываются автоматически, сами файлы не трогаются.
При сохранении всегда пишется единый формат (атомарно: tmp + rename).
"""
from __future__ import annotations

import json
import os

CACHE_FILENAME = "octopus_cache.json"
FORMAT_VERSION = 1

# Максимальная длина ключа: длинные строки в кэш не кладём
MAX_KEY_LEN = 500

# Старые имена файлов кэша по движкам (порядок = приоритет).
# twine: единый файл и раньше назывался octopus_cache.json (обёрнутый
# {"pairs": ...}) — отдельный legacy-список не нужен.
_LEGACY_FILES: dict[str, tuple[str, ...]] = {
    "rpgmaker": (".translation_cache.json", ".octopus_cache.json"),
    "renpy": (".octopus_cache.json",),
    "tyrano": ("tyrano_cache.json", ".octopus_cache.json"),
    "twine": (),
}


def _read_json(path: str):
    """Читает JSON-файл; None при любых проблемах (нет файла, битый)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _sanitize(data) -> dict[str, str]:
    """Оставляет только валидные пары str->str, без identity-записей."""
    out: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        k = k.strip()
        if not k or not v or v == k or len(k) > MAX_KEY_LEN:
            continue
        out[k] = v
    return out


def _pairs_from(data) -> dict[str, str] | None:
    """Пары из прочитанного файла: единый формат или плоский словарь."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("pairs"), dict):
        return _sanitize(data["pairs"])
    if data.get("format") is None:
        return _sanitize(data)
    return None


def load_game_cache(game_dir: str, engine: str = "") -> dict[str, str]:
    """Переводы из единого файла кэша (или из старых форматов).

    Старые файлы не перезаписываются и не удаляются — они читаются
    как fallback, пока не появится единый octopus_cache.json.
    """
    pairs = _pairs_from(_read_json(os.path.join(game_dir, CACHE_FILENAME)))
    if pairs is not None:
        return pairs
    for legacy in _LEGACY_FILES.get(engine, ()):
        pairs = _pairs_from(_read_json(os.path.join(game_dir, legacy)))
        if pairs is not None:
            return pairs
    return {}


def save_game_cache(game_dir: str, engine: str, pairs: dict,
                    skip: list | set | None = None) -> bool:
    """Пишет единый формат кэша (атомарно: tmp + os.replace)."""
    payload: dict = {"format": FORMAT_VERSION, "engine": engine,
                     "pairs": dict(pairs)}
    if skip:
        payload["skip"] = sorted(str(x) for x in skip)
    path = os.path.join(game_dir, CACHE_FILENAME)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
