# -*- coding: utf-8 -*-
"""`translate <lang> strings:` больше НЕ пишется никогда.

Этот блок Ren'Py подменяет python-строки прямо в коде игры. На SR24
из-за него мод-лоадер падал на старте: игра строит словари из строк,
перевод ключа приходил текстом вместо dict, и .get() давал AttributeError.
Структурные блоки (метки и screens) безопасны — они трогают только
отображаемые строки.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.renpy import parser as rp


def mk(orig, ctx, label, trans):
    jp = ("label:%s|" % label if label else "") + "ctx:" + ctx
    return TranslationEntry(id=1, file="t.rpy", json_path=jp,
                            context=ctx, original=orig, translation=trans)


print("1) python-строки не попадают ни в один блок...")
say = mk("Hello", "t.rpy:2:dialogue", "start", "Привет")
ui = mk("Settings", "t.rpy:9:screen", "start", "Настройки")
py1 = mk("Gold", "t.rpy:11:python:gold_text", "start", "Золото")
nolab = mk("Plain", "t.rpy:12:dialogue", "", "Просто")
# '' — некуда писать: 'strings:' запрещён, метки нет
assert rp._entry_block(py1) == ""
assert rp._entry_block(nolab) == ""

with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    res = rp.apply(td, [say, ui, py1, nolab], target_lang="ru")
    out = os.path.join(td, "game", "tl", "russian")
    text = ""
    for f in os.listdir(out):
        if f.endswith(".rpy"):
            cand = io.open(os.path.join(out, f), encoding="utf-8").read()
            if "translate russian" in cand:
                text += cand
    assert text, os.listdir(out)
    assert "translate russian strings:" not in text, \
        "strings: ломает игры, построенные на строковых словарях"
    assert "translate russian start:" in text, text
    assert "translate russian screens:" in text, text
    assert "Hello" in text and "Settings" in text
    # опасные строки не записаны вообще
    assert "Gold" not in text, "python-строка записана в файл перевода"
    assert "Plain" not in text, "строка без метки записана в файл перевода"
    assert res.get("strings_dropped", 0) == 2, res
    # ... и каждая пропущенная строка объяснена (AGENTS.md 5A: причина
    # пропуска обязательна — иначе «применил, а в игре пусто» без ответа)
    assert res.get("skipped_total") == 2, res
    assert res.get("skipped_by") == {"python-expression": 1,
                                     "no-label": 1}, res
    assert res.get("strings") == 2, res
print("   OK")

print("2) блок без структурных строк не создаётся...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    rp.apply(td, [py1, nolab], target_lang="ru")
    out = os.path.join(td, "game", "tl", "russian")
    written = []
    for f in os.listdir(out):
        if f.endswith(".rpy") and "dict" not in f:
            t = io.open(os.path.join(out, f), encoding="utf-8").read()
            if "translate russian" in t:
                written.append(f)
    assert not written, written
print("   OK")

print("ALL RENPY STRINGS-BLOCK TESTS GREEN")
