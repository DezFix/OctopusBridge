# -*- coding: utf-8 -*-
"""Чистые хелперы вкладки перевода: группировка/фильтр по языку оригинала.

Без Qt — можно тестировать и переиспользовать без GUI.
Раньше жили в app/ui/translate_tab.py.
"""
from __future__ import annotations

from app.core.translate.detect import detect_lang


def group_entries_by_src_lang(
        entries: list) -> list[tuple[str | None, int]]:
    """Группировка записей по детекту языка оригинала: [(lang, count)].

    Чистая, без Qt — для чекбоксов диалога перевода. Порядок: сначала
    по убыванию count, None (без букв) в конце.
    """
    from collections import Counter
    counts: Counter = Counter()
    for e in entries:
        try:
            original = getattr(e, "original", "") or ""
        except Exception:  # noqa: BLE001
            continue
        if not original.strip():
            continue
        try:
            counts[detect_lang(original)] += 1
        except Exception:  # noqa: BLE001
            counts[None] += 1
    ranked = sorted(counts.items(),
                    key=lambda kv: (kv[0] is None, -(kv[1] or 0), str(kv[0])))
    return ranked


def translate_busy(tab) -> bool:
    """Идёт ли фоновый перевод (воркер мутирует записи)."""
    w = getattr(tab, "worker", None)
    return bool(w is not None and w.isRunning())


def extract_busy(tab) -> bool:
    """Идёт ли фоновое извлечение (скоро подменит p.entries)."""
    w = getattr(getattr(tab, "main", None), "_extract_worker", None)
    return bool(w is not None and w.isRunning())


def project_lang_options(engine_module, project) -> list[str]:
    """Официальные языки игры (Ren'Py: game/tl/*). Отбрасываем
    «None» (системные строки) и папки, где лежат только переводы,
    созданные самим приложением (ob_*-файлы) — это не языки
    разработчика."""
    import os
    if not (engine_module and project
            and hasattr(engine_module, "list_languages")):
        return []
    try:
        langs = list(engine_module.list_languages(project.game_dir) or [])
    except Exception:  # noqa: BLE001
        return []
    res = []
    for lang in langs:
        if not lang or lang == "None":
            continue
        tl_dir = os.path.join(project.game_dir, "game", "tl", lang)
        if os.path.isdir(tl_dir):
            try:
                files = [f for f in os.listdir(tl_dir)
                         if not f.endswith((".rpyc", ".json"))]
            except OSError:
                files = []
            if files and all(f.startswith("ob_") for f in files):
                continue
        res.append(lang)
    return res


def filter_entries_by_src_lang(
        entries: list, selected: set | None) -> list:
    """Только записи выбранных языков оригинала (None — все).

    Записи без детекта (цифры/знаки, lang None) всегда пропускаем в работу:
    движок их не трогает, сервис помечает skip сам.
    """
    if not selected:
        return list(entries)
    out = []
    for e in entries:
        try:
            original = getattr(e, "original", "") or ""
        except Exception:  # noqa: BLE001
            continue
        try:
            lang = detect_lang(original) if original.strip() else None
        except Exception:  # noqa: BLE001
            lang = None
        if lang is None or lang in selected:
            out.append(e)
    return out
