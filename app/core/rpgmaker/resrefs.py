# -*- coding: utf-8 -*-
"""Защита ссылок на файлы ресурсов RPG Maker от перевода.

Корень регрессии «Failed to load audio/bgm/001 ... .ogg»: имя аудиофайла
(без расширения!) извлекалось как текст, переводилось, и игра просила
у диска несуществующий файл. Слэша и расширения в таких строках нет,
поэтому старые эвристики их пропускали.

Правило: строка, совпадающая с именем существующего ресурса игры
(audio/img/movies, включая шифрованные .ogg_/.rpgmvp и www-деплой),
— это ссылка на файл, а не текст. Её нельзя извлекать, подменять
ни файлом, ни в памяти: ни один такой перевод не должен попасть
в словарь (см. parser._Extractor, engine.apply, payloads obIsAudio).
"""
from __future__ import annotations

import os

# где живут ресурсы (и www-варианты деплоя)
_RES_DIRS = ("audio", "img", "movies",
             os.path.join("www", "audio"),
             os.path.join("www", "img"),
             os.path.join("www", "movies"))

# шифрованные имена: MZ клеит "_" к расширению (x.ogg_),
# MV меняет расширение (.rpgmvp/.rpgmvo)
_ENC_SUFFIXES = (".png_", ".ogg_", ".m4a_",
                 ".rpgmvp", ".rpgmvo", ".rpgmvm")
_MV_ENC_EXT = {".png": ".rpgmvp", ".ogg": ".rpgmvo", ".m4a": ".rpgmvm"}

_cache: dict[str, set[str]] = {}


def _stems_of(filename: str) -> set[str]:
    """Все ключи файла: полное имя и ствол, нижний регистр."""
    low = filename.lower()
    out = {low}
    # x.ogg_ -> x.ogg (шифрованный MZ)
    if low.endswith("_") and "." in low[:-1]:
        low = low[:-1]
        out.add(low)
    if "." in low:
        stem = low.rsplit(".", 1)[0]
        out.add(stem)
        # MV: x.rpgmvp <-> x.png
        for plain, enc in _MV_ENC_EXT.items():
            if low.endswith(enc):
                out.add(stem + plain)
    else:
        out.add(low)
    return out


def build_index(game_dir: str) -> set[str]:
    """Множество имён ресурсов игры (кэш на сессию).

    Сканирует audio/img/movies (+www). Пустая игра = пустой индекс
    (фильтр молча отключён, поведение как раньше).
    """
    norm = os.path.normpath(game_dir)
    hit = _cache.get(norm)
    if hit is not None:
        return hit
    idx: set[str] = set()
    try:
        for rel in _RES_DIRS:
            base = os.path.join(game_dir, rel)
            if not os.path.isdir(base):
                continue
            for _r, _dirs, files in os.walk(base):
                for fn in files:
                    idx.update(_stems_of(fn))
    except OSError:
        pass
    _cache[norm] = idx
    return idx


def clear_index(game_dir: str | None = None) -> None:
    """Сбросить кэш (после добавления файлов в игру)."""
    if game_dir is None:
        _cache.clear()
    else:
        _cache.pop(os.path.normpath(game_dir), None)


def is_resource_name(idx: set[str] | None, text: str) -> bool:
    """True — текст совпадает с файлом ресурса (ссылка, не переводить)."""
    if not idx or not isinstance(text, str):
        return False
    t = text.strip()
    if not t or len(t) > 128:
        return False
    low = t.lower()
    if low in idx:
        return True
    base = low.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base in idx:
        return True
    return False
