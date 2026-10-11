# -*- coding: utf-8 -*-
"""Какой exe запускает приложение у Ren'Py-игры.

На SR24 было два файла: SR24.exe (64) и SR24-32.exe. Старый код брал
первый по алфавиту glob, а `-` идёт раньше точки — то есть запускалась
32-битная сборка с адресным пространством ~2 ГБ. При архиве игры 1.5 ГБ
это давало MemoryError на старте: игра не запускалась через приложение,
хотя при обычном двойном клике работала.
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engines.renpy.tentacle import find_launcher

print("1) 32-битная сборка не выбирается, если есть обычная...")
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "SR24-32.exe"), "wb").close()
    open(os.path.join(td, "SR24.exe"), "wb").close()
    got = os.path.basename(find_launcher(td))
    assert got == "SR24.exe", got
print("   OK")

print("2) приоритет одноимённого exe...")
with tempfile.TemporaryDirectory() as td:
    game = os.path.join(td, "MyGame")
    os.makedirs(game)
    for n in ("aaa.exe", "MyGame-x64.exe", "MyGame.exe"):
        open(os.path.join(game, n), "wb").close()
    got = os.path.basename(find_launcher(game))
    assert got == "MyGame.exe", got
print("   OK")

print("3) если 32-битная одна — берём её, а не молчим...")
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "Game32.exe"), "wb").close()
    assert os.path.basename(find_launcher(td)) == "Game32.exe"
print("   OK")

print("4) служебные exe пропускаются, пусто не ломает...")
with tempfile.TemporaryDirectory() as td:
    for n in ("unins000.exe", "setup.exe", "uninstall.exe"):
        open(os.path.join(td, n), "wb").close()
    assert find_launcher(td) is None
print("   OK")

print("ALL RENPY LAUNCHER TESTS GREEN")
