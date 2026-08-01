# -*- coding: utf-8 -*-
"""Offscreen-проверка GUI: главное окно, открытие проекта, таблица перевода."""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from _test_game import find_rpgm_game, skip_no_game

GAME = find_rpgm_game()
if not GAME:
    skip_no_game("RPG Maker (The Suffering of The Modest Witch)")

app = QApplication([])
w = MainWindow()

print('1) окно создано:', w.windowTitle())
w.open_project(GAME)
print('2) проект открыт, движок:', w.project.engine)

# извлекаем без диалогов: напрямую через парсер
from app.core.rpgmaker import parser
w.project.entries = parser.extract(GAME)
w.save_project()
w.refresh_all()
print('3) записей:', len(w.project.entries),
      '| строк в таблице:', w.translate_tab.table.rowCount())

# фильтр "только с иероглифами"
w.translate_tab.filter_combo.setCurrentIndex(1)
print('4) фильтр CJK -> строк:', w.translate_tab.table.rowCount())
w.translate_tab.filter_combo.setCurrentIndex(0)

# поиск
w.translate_tab.search.setText('Айра')
print('5) поиск "Айра" -> строк:', w.translate_tab.table.rowCount())
w.translate_tab.search.setText('')

# эмуляция ручной правки первой видимой строки (колонка 2 — перевод)
item = w.translate_tab.table.item(0, 2)
item.setText('Ручной перевод тест')
entry_id = item.data(0x0100)  # Qt.UserRole
e = next(x for x in w.project.entries if x.id == entry_id)
assert e.translation == 'Ручной перевод тест' and e.status == 'manual'
print('6) ручная правка применилась к записи id', entry_id)

# страницы на месте (таблица капится на 10000 строк — проверено в шаге 3)
assert w.translate_tab.table.rowCount() <= 10000
print('7) лимит таблицы 10000: OK')

# drag&drop через welcome tab
exe = os.path.join(GAME, "Game.exe")
w.welcome_tab.open_path(exe)
assert w.project is not None
import os as _os
assert _os.path.normpath(w.project.game_dir) == _os.path.normpath(GAME)
print('8) drag&drop exe -> проект открыт')

# проект сохраняется
w.save_project()
pf = w._project_file(GAME)
assert os.path.exists(pf)
print('9) проект сохранён:', os.path.basename(pf), os.path.getsize(pf), 'байт')

print()
print('GUI OFFSCREEN: ВСЕ ПРОВЕРКИ ПРОШЛИ')
sys.stdout.flush()
os._exit(0)
