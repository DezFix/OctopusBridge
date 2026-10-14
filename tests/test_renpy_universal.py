# -*- coding: utf-8 -*-
"""Универсальный выбор способа перевода Ren'Py под любую игру.

Не один трюк, а каскад: смотрим, что есть в игре, выбираем самый
безопасный рабочий способ. Проверяем на синтетике и на реальных играх
(только диагностика choose_method, без записи).
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.renpy import universal as u

print("1) пустая папка — hooks по умолчанию (нечего терять)...")
with tempfile.TemporaryDirectory() as td:
    c = u.choose_method(td)
    assert c["method"] == "hooks", c
    assert c["loose_rpy"] == 0
print("   OK")

print("2) три .rpy на диске — source...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    for n in ("a.rpy", "b.rpy", "c.rpy"):
        open(os.path.join(td, "game", n), "w").close()
    c = u.choose_method(td)
    assert c["method"] == "source", c
    assert c["loose_rpy"] == 3, c
print("   OK")

print("3) служебные ob_/zz_ не считаются исходниками игры...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    for n in ("ob_x.rpy", "zz_ob_lang.rpy"):
        open(os.path.join(td, "game", n), "w").close()
    c = u.choose_method(td)
    assert c["method"] == "hooks", c
    assert c["loose_rpy"] == 0, c
print("   OK")

print("4) реальные игры: SR24 и Shoretown — hooks (только .rpyc)...")
for g in (r"E:\Temp\IDM\SR24-0.17.0-pc",
          r"E:\Temp\IDM\Shoretown_Saga-0.7-pc"):
    if not os.path.isdir(g):
        print("   SKIP: нет %s" % g)
        continue
    c = u.choose_method(g)
    assert c["method"] == "hooks", (g, c)
    assert c["has_identifiers"] is False, (g, c)
    print("   %s -> hooks OK" % os.path.basename(g))
print("   OK")

print("ALL RENPY UNIVERSAL TESTS GREEN")
