# -*- coding: utf-8 -*-
"""Мост Twine: то, из-за чего «читов нет», и память перевода.

Главный баг: формат истории вычислялся ОДИН раз в момент внедрения
скрипта. Мост вклеивается в начало документа, а движок (SugarCube/
Harlowe) грузится позже — поэтому fmt навсегда оставался 'unknown',
и collectState()/setVar() молча отдавали пустоту. Теперь формат
определяется лениво, в момент обращения.
"""
import io
import os
import re
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.twine import live_tr
from app.engines.twine.tentacle import PAYLOAD_SCRIPT

JS = PAYLOAD_SCRIPT

print("1) формат НЕ вычисляется один раз при внедрении...")
assert not re.search(r"__OT\._fmt\s*=\s*\(function", JS), \
    "формат снова вычисляется один раз — на живой игре будет unknown"
assert "__OT.fmt = function" in JS, "нет ленивого определения формата"
assert "__OT.varsRoot = function" in JS, "нет ленивого доступа к переменным"
assert "__OT._fmt" not in JS, "остались обращения к мёртвому __OT._fmt"
assert "window.SugarCube && window.SugarCube.State" in JS, \
    "нет поддержки SugarCube 2 (window.SugarCube.State)"
print("   OK")

print("2) setVar не создаёт пути на лету...")
setvar = JS.split("__OT.setVar = function")[1].split("};")[0]
assert "return false" in setvar, "setVar должен отказывать"
assert "__OT.repaint()" in setvar, "нет перерисовки после правки"
assert "genericRoots" not in JS, \
    "общий поиск по окну страницы удалён — на реальных HTML-играх " \
    "он ничего не находит, читы оставлены только для Twine"
print("   OK")

print("3) collectState разворачивает вложенные переменные...")
assert "variablesFlat" in JS
assert "s.variablesFlat[n] = v" in JS
print("   OK")

print("4) память перевода: накапливается, не теряется, изолирована...")
with tempfile.TemporaryDirectory() as td:
    game = os.path.join(td, "Game A")
    assert live_tr.load(game) == {}
    assert live_tr.add(game, {"Hello": "Привет"}) == 1
    assert live_tr.add(game, {"Coins": "Монеты"}) == 1
    got = live_tr.load(game)
    assert got["Hello"] == "Привет" and got["Coins"] == "Монеты", got
    live_tr.add(game, {"Hello": "Иное"}, max_new=10)
    assert live_tr.load(game)["Hello"] == "Привет", "перевод перебит"
    assert live_tr.add(game, {"X": "", "Y": "Y"}) == 0
    assert live_tr.load(os.path.join(td, "Game B")) == {}
    with open(live_tr.memory_path(game), "w", encoding="utf-8") as f:
        f.write("{ не json")
    assert live_tr.load(game) == {}
    import shutil
    shutil.rmtree(live_tr.memory_dir(), ignore_errors=True)
print("   OK")

print("ALL TWINE BRIDGE TESTS GREEN")
