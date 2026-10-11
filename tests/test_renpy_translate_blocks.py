# -*- coding: utf-8 -*-
"""Перевод Ren'Py уходит в блоки, которые игра вообще понимает.

Проверено по исходникам движка (renpy/translation/__init__.py,
lookup_translate): реплика ищет перевод ПО ИМЕНОВАНИЮ УЗЛА
(`translate <lang> <label>:`), экраны — в `screens:`, а `strings:` —
словарь для python-строк, который реплики не переводит. Раньше всё
лежало в `strings:`, и штатный механизм Ren'Py молча ничего не переводил
(текст спасал только наш runtime-хук `Text.__init__`, а он ловит не всё).
"""
import io
import os
import re
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.renpy import parser as rp

print("1) метка реплики видна в записи...")
rp._reset_label()
rp._reset_screen_stack()
got = []
collect = lambda f, c, o, *rest: got.append((c, o))
rp._extract_line("t.rpy", 1, "label start:", collect)
rp._extract_line("t.rpy", 2, '    e "Hello"', collect)
assert got[-1][1] == "Hello", got
print("   OK")

print("2) запись разносится по блокам: метка / screens / strings...")


def mk(orig, ctx, label, trans):
    jp = ("label:%s|" % label if label else "") + "ctx:" + ctx
    return TranslationEntry(id=1, file="t.rpy", json_path=jp,
                            context=ctx, original=orig, translation=trans)


say = mk("Hello", "t.rpy:2:dialogue", "start", "Привет")
ui = mk("Settings", "t.rpy:9:screen", "start", "Настройки")
py = mk("Gold", "t.rpy:11:_()", "start", "Золото")
nolab = mk("Plain", "t.rpy:12:dialogue", "", "Просто")
assert rp._entry_block(say) == "label", rp._entry_block(say)
assert rp._entry_block(ui) == "screens", rp._entry_block(ui)
assert rp._entry_block(py) == "strings", rp._entry_block(py)
assert rp._entry_block(nolab) == "strings", "без метки перевод не подставится"
print("   OK")

print("3) apply пишет блоки по меткам, а не один strings:...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    res = rp.apply(td, [say, ui, py, nolab], target_lang="ru")
    out = os.path.join(td, "game", "tl", "russian")
    files = [f for f in os.listdir(out)
             if f.endswith(".rpy") and "dict" not in f]
    assert files, res
    text = ""
    for f in files:
        cand = io.open(os.path.join(out, f), encoding="utf-8").read()
        if "translate russian" in cand:
            text = cand
            break
    assert text, files
    assert "translate russian start:" in text, text
    assert "translate russian screens:" in text, text
    assert "translate russian strings:" in text, text
    blocks = dict(re.findall(
        r"^translate russian ([^:\r\n]+):\r?\n((?:(?:    .*)?\r?\n)+)",
        text, re.M))
    assert "Hello" in blocks.get("start", ""), blocks
    assert "Settings" not in blocks.get("start", ""), \
        "текст экрана не должен попадать в блок метки"
    assert "Settings" in blocks.get("screens", ""), blocks
    assert "Gold" in blocks.get("strings", ""), blocks
    assert "Plain" in blocks.get("strings", ""), blocks
print("   OK")

print("4) метка не теряется при извлечении...")
with tempfile.TemporaryDirectory() as td:
    g = os.path.join(td, "game")
    os.makedirs(g)
    io.open(os.path.join(g, "script.rpy"), "w", encoding="utf-8").write(
        'label intro:\n'
        '    e "Hello there"\n'
        '    menu:\n'
        '        "Yes":\n'
        '            pass\n'
        'label other:\n'
        '    e "Second"\n')
    entries = rp.extract(td)
    by_orig = {e.original: rp._entry_label(e) for e in entries}
    assert by_orig.get("Hello there") == "intro", by_orig
    assert by_orig.get("Yes") == "intro", by_orig
    assert by_orig.get("Second") == "other", by_orig
print("   OK")

print("ALL RENPY TRANSLATION-BLOCK TESTS GREEN")