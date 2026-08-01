# -*- coding: utf-8 -*-
"""Тесты модульной архитектуры: ядро + движковые модули, адаптация GUI."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from app.engines.registry import MODULES, detect_engine
from app.engines.rpgmaker import RpgMakerModule
from app.engines.renpy import RenPyModule
from app.engines.twine import TwineModule
from _test_game import find_rpgm_game, skip_no_game

GAME = find_rpgm_game()
if not GAME:
    skip_no_game("RPG Maker (The Suffering of The Modest Witch)")
app = QApplication([])

print('1) Реестр и детект модулей...')
assert MODULES == [RpgMakerModule, RenPyModule, TwineModule]
mod = detect_engine(GAME)
assert isinstance(mod, RpgMakerModule) and mod.variant == "mz"
assert mod.display == "RPG Maker MZ"
assert {"files", "live", "cheats", "resources", "font"} <= mod.features
print('   RPGM MZ -> модуль rpgmaker, весовой детект OK')


def make_renpy(td):
    os.makedirs(os.path.join(td, 'game'))
    with open(os.path.join(td, 'game', 'script.rpy'), 'w', encoding='utf-8') as f:
        f.write('label start:\n    "Привет."\n')


with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    mod = detect_engine(td)
    assert isinstance(mod, RenPyModule) and {"files", "live", "cheats"} <= mod.features
    print("   Ren'Py -> модуль renpy OK")
with tempfile.TemporaryDirectory() as td:
    assert detect_engine(td) is None
    print('   пустая папка -> None (неподдерживаемый движок) OK')

print('2) GUI подстраивается под движок игры...')
from app.ui.main_window import MainWindow
w = MainWindow()
n_common = w.tabs.count()
assert w.cheat_tab is None and w._engine_tabs == []

# RPGM: появляются вкладки Перевод, Читы, Карты, Ресурсы
assert w.open_project(GAME) == "mz"
assert w.cheat_tab is not None
roles = [r for _, r in w._engine_tabs]
assert "cheats" in roles and roles.count("module") == 2
print('   RPGM: вкладки Читы/Карты/Ресурсы добавлены')

# извлечение/внедрение через модуль
entries = w.engine_module.extract(GAME)
assert len(entries) > 1000
print('   extract через модуль:', len(entries), 'записей')

with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    assert w.open_project(td) == "renpy"
    # RPGM-вкладки (Карты) скрыты, свои вкладки показаны
    assert w.cheat_tab is not None
    roles = [r for _, r in w._engine_tabs]
    assert roles == ["translate", "cheats", "triggers", "module"], roles
    entries = w.engine_module.extract(td)
    assert any(e.original == "Привет." for e in entries)
    print("   Ren'Py: вкладки cheats+triggers+module, extract OK")

with tempfile.TemporaryDirectory() as td:
    assert w.open_project(td) == "unknown"
    assert w.engine_module is None and w._engine_tabs == []
    assert w.tabs.count() == n_common
    print('   неизвестная игра: только ядро (без движковых вкладок)')

print()
print('ТЕСТЫ МОДУЛЬНОЙ АРХИТЕКТУРЫ ПРОШЛИ')
sys.stdout.flush()
os._exit(0)
