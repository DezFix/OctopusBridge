# -*- coding: utf-8 -*-
"""Универсальный выбор способа перевода Ren'Py под любую игру.

Проблема: один механизм не покрывает все игры. У каждой игры свой набор:
- есть исходники .rpy или только .rpyc;
- есть идентификаторы реплик или нет;
- Ren'Py 7 (Python 2) или Ren'Py 8 (Python 3);
- строки в коде, которые переводить нельзя.

Решение — не один трюк, а каскад: определяем, что есть в игре, выбираем
самый безопасный рабочий способ, проверяем результат. Каждый способ
независим и отказоустойчив; если способ неприменим — честный отказ,
а не молчаливая порча.

Способы (от безопасного к хрупкому):
1. "source" — прямой перевод исходников .rpy (sourcetr). Не трогает
   движок переводов вообще. Работает везде, где есть .rpy.
2. "native" — штатные блоки translate по идентификаторам. Только если
   идентификаторы реально есть в .rpyc (редкость, но бывает).
3. "hooks" — хуки на отрисовку и реплики. Для .rpyc без идентификаторов.
   Переводит весь видимый текст, код не трогает.

Что НЕ делаем никогда: strings: (ломает код), синтез идентификаторов
(не угадаешь — строка молча не подставится).
"""
from __future__ import annotations

import os


def _count_loose_rpy(game_dir: str) -> int:
    """Сколько .rpy лежит на диске (не в архивах)."""
    n = 0
    root = os.path.join(game_dir, "game")
    if not os.path.isdir(root):
        return 0
    for _dir, _sub, files in os.walk(root):
        # служебное OctopusBridge не считаем исходниками игры
        for f in files:
            if f.endswith(".rpy") and not f.startswith(("ob_", "zz_ob_")):
                n += 1
    return n


def _has_identifiers(game_dir: str) -> bool:
    """Есть ли идентификаторы Say в .rpyc (нужны для native-блоков)."""
    from app.core.renpy import parser as rp
    from app.core.renpy.rpa import RpaArchive, find_rpa_archives

    checked = 0

    def _walk(n, seen):
        if id(n) in seen:
            return
        seen.add(id(n))
        if isinstance(n, (list, tuple)):
            for x in n:
                yield from _walk(x, seen)
            return
        if isinstance(n, (str, bytes, int, float, bool, type(None))):
            return
        yield n
        for a in ("block", "statements", "body", "items", "child",
                  "children"):
            v = getattr(n, a, None)
            if isinstance(v, (list, tuple)):
                yield from _walk(v, seen)

    # сначала диск (дешевле), потом архивы
    for path, rel in rp._iter_rpy(game_dir):
        if not path.endswith(".rpyc") or path.startswith("rpa://"):
            continue
        try:
            with open(path, "rb") as f:
                parsed = rp._unpickle_rpyc(f.read())
        except Exception:
            continue
        if not parsed:
            continue
        _, stmts = parsed
        for node in _walk(stmts, set()):
            tn = type(node).__name__
            base = tn[6:] if tn.startswith("_mock_") else tn
            if base == "Say":
                checked += 1
                if getattr(node, "identifier", None):
                    return True
                if checked >= 50:
                    return False
    if checked:
        return False
    # диск пуст — смотрим архивы
    try:
        arcs = find_rpa_archives(game_dir)
    except Exception:
        return False
    for arc_path in arcs:
        try:
            arc = RpaArchive(arc_path)
        except Exception:
            continue
        for name in arc.files:
            n = str(name)
            if not n.endswith(".rpyc"):
                continue
            try:
                parsed = rp._unpickle_rpyc(arc.read(n))
            except Exception:
                continue
            if not parsed:
                continue
            _, stmts = parsed
            for node in _walk(stmts, set()):
                tn = type(node).__name__
                base = tn[6:] if tn.startswith("_mock_") else tn
                if base == "Say":
                    checked += 1
                    if getattr(node, "identifier", None):
                        return True
                    if checked >= 50:
                        return False
    return False


def choose_method(game_dir: str) -> dict:
    """Выбрать способ перевода для игры. Только диагностика, без записи.

    Возвращает {"method": "source"|"native"|"hooks", "reason": ...,
    "loose_rpy": N, "has_identifiers": bool}.
    """
    loose = _count_loose_rpy(game_dir)
    # source: исходники есть — самый безопасный путь
    if loose >= 3:
        return {"method": "source", "loose_rpy": loose,
                "has_identifiers": False,
                "reason": "на диске %d .rpy: перевод пишется прямо "
                          "в исходники, движок переводов не трогается" % loose}
    has_id = _has_identifiers(game_dir)
    if has_id:
        return {"method": "native", "loose_rpy": loose,
                "has_identifiers": True,
                "reason": "в .rpyc есть идентификаторы реплик: пишем "
                          "штатные блоки translate"}
    return {"method": "hooks", "loose_rpy": loose,
            "has_identifiers": False,
            "reason": "только .rpyc без идентификаторов: перевод "
                      "видимого текста хуками, код не трогаем"}
