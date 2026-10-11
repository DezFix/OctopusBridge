# -*- coding: utf-8 -*-
"""Перевод Ren'Py прямо в исходнике игры.

Зачем так, а не через tl/:

* `translate <lang> ...` — механизм движка, и он не одинаков у версий.
  На старой игре он ломал загрузку (мод-лоадер получал строку вместо
  словаря). Прямая правка исходника никак не пересекается с движком
  переводов: игра выполняет СВОЙ код, просто с русским текстом.

Как игра это подхватывает:

* Ren'Py берёт `.rpyc` только если он новее одноимённого `.rpy`. В игре
  `.rpyc` лежит в архиве и старый, поэтому наш `.rpy` сложенный рядом в
  `game/` (он всегда новее) будет скомпилирован и запущен вместо него.

Что делаем:

* читаем `.rpy` из архива (или с диска);
* заменяем строковые литералы на переводы;
* кладём результат туда же в `game/`, с бэкапом оригинала.

Модуль чистый: без Qt, без сети. Наружу отдаются только пути, счётчики
и размеры — не текст игры.
"""
from __future__ import annotations

import os

from app.core.io import BackupStore, atomic_write_text


def _escape(text: str) -> str:
    """Текст -> содержимое rpy-литерала (внутри кавычек)."""
    out = str(text or "")
    out = out.replace("\\", "\\\\")
    out = out.replace("\n", "\\n")
    out = out.replace('"', '\\"')
    return out


def _find_literal_patterns(text: str, literal: str):
    """Места в тексте, где литерал стоит в ДВОЙНЫХ кавычках.

    Только двойные: подстановка внутри одинарных кавычек испортила бы
    файл (`e 'Hello'` -> `e '"Privet"'` — сломанный синтаксис). В .rpy
    двойные кавычки — подавляющее большинство, остальное обходим самим
    исходником. Ещё проверяем границы: перед кавычкой не должно быть
    экранирования, а сам литерал должен быть отдельным токеном.
    """
    needle = '"%s"' % _escape(literal)
    if not needle:
        return
    start = 0
    while True:
        pos = text.find(needle, start)
        if pos == -1:
            return
        before = text[pos - 1] if pos else ""
        after = text[pos + len(needle)] if pos + len(needle) < len(text) \
            else ""
        start = pos + len(needle)
        if before in ('"', "'", "\\"):
            continue        # внутри другого литерала или экранирование
        if after in ('"', "'"):
            continue
        yield pos, pos + len(needle)


def translate_text(text: str, mapping: dict) -> tuple[str, int, list]:
    """Заменить литералы в тексте .rpy на переводы.

    mapping: {оригинал (без кавычек): перевод}.
    Возвращает (новый текст, сколько заменено, пропущенные оригиналы).
    """
    if not mapping:
        return text, 0, []
    hits: list[tuple[int, int, str]] = []
    missed: list[str] = []
    for orig, tr in mapping.items():
        span = None
        for span in _find_literal_patterns(text, orig):
            hits.append((span[0], span[1], tr))
            break
        if span is None:
            missed.append(orig)
    if not hits:
        return text, 0, missed
    hits.sort()
    out: list[str] = []
    last = 0
    for start, end, tr in hits:
        out.append(text[last:start])
        out.append('"%s"' % _escape(tr))
        last = end
    out.append(text[last:])
    return "".join(out), len(hits), missed


def apply_sourced(game_dir: str, entries, lang: str = "") -> dict:
    """Перевести исходники .rpy игры и сложить их рядом.

    Исходники берём из архива .rpa либо с диска (оба варианта перебирает
    parser._iter_rpy) и кладём переведённую копию в `game/<путь>`.
    Ren'Py берёт `.rpyc` только если он новее `.rpy`, поэтому наш файл,
    записанный сейчас, выигрывает у старого архивного — игра компилирует
    и запускает его. Никакого tl/, никакого config.language.

    Перед записью делаем бэкап оригинала (папка backup рядом с файлом),
    запись атомарная. Если перевод строки не влез в оригинальный файл
    (литерал не найден) — строку не трогаем, а не пишем мусор.
    """
    from app.core.renpy import parser as rp
    from app.core.renpy.rpa import RpaArchive

    # группируем переводы по файлу-источнику
    by_file: dict[str, dict] = {}
    for e in entries:
        tr = (getattr(e, "translation", "") or "").strip()
        orig = getattr(e, "original", "")
        if not orig or not tr or getattr(e, "status", "") == "skip":
            continue
        by_file.setdefault(getattr(e, "file", ""), {})[orig] = tr

    stats = {"files": 0, "strings": 0, "written": [], "missed": 0,
             "errors": [], "backup_dir": ""}
    if not by_file:
        return stats

    archives: dict[str, RpaArchive | None] = {}
    from app.core.renpy.rpa import find_rpa_archives  # noqa: WPS433
    for arc_path in find_rpa_archives(game_dir):
        try:
            archives[os.path.normpath(arc_path)] = RpaArchive(arc_path)
        except Exception:
            archives[os.path.normpath(arc_path)] = None

    for path, rel in rp._iter_rpy(game_dir):
        if not rel.endswith(".rpy"):
            continue
        mapping = by_file.get(rel)
        if not mapping:
            continue
        from_archive = path.startswith("rpa://")
        try:
            if from_archive:
                rest = path[len("rpa://"):]
                if "\x00" not in rest:
                    continue
                arc_key, fname = rest.split("\x00", 1)
                arc = archives.get(os.path.normpath(arc_key))
                if arc is None:
                    continue
                raw = arc.read(fname)
                text = raw.decode("utf-8", "replace")
            else:
                with open(path, encoding="utf-8", errors="replace") as f:
                    text = f.read()
        except Exception as e:  # noqa: BLE001
            stats["errors"].append("%s: %s" % (rel, str(e)[:60]))
            continue

        new_text, count, missed = translate_text(text, mapping)
        stats["missed"] += len(missed)
        if not count:
            continue
        # Дисковый файл правим на месте. Архивный кладём в game/<путь>:
        # Ren'Py читает game/ в первую очередь, поэтому наш файл
        # перекроет архивный .rpyc.
        if from_archive:
            out_path = os.path.join(game_dir, "game", *rel.split("/"))
        else:
            out_path = os.path.join(game_dir, *rel.split("/"))
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            store = BackupStore(os.path.join(
                os.path.dirname(out_path), "backup"))
            try:
                stats["backup_dir"] = store.backup_dir
                store.backup(out_path)
            except Exception:
                pass    # оригинала нет — нечего бэкапить
            atomic_write_text(out_path, new_text, encoding="utf-8")
        except OSError as e:
            stats["errors"].append("%s: %s" % (rel, str(e)[:60]))
            continue
        stats["files"] += 1
        stats["strings"] += count
        stats["written"].append(rel)
    return stats
