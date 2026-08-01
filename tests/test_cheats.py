# -*- coding: utf-8 -*-
"""Тесты читов OctopusBridge: имена RPGM, выражения щупальца, таблицы GUI.

Новое ядро: читы выполняются прямым Runtime.evaluate в игре (CDP),
без файлов-плагинов. GUI проверяется через записывающее тестовое
щупальце — без реальной игры.
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox
from _test_game import find_rpgm_game

app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

GAME = find_rpgm_game()

print('1) Имена из System.json (реальная игра, если есть)...')
if os.path.isdir(GAME):
    from app.core.rpgmaker.varnames import extract_names, extract_maps
    var_names, switch_names = extract_names(GAME)
    assert var_names.get(1) == "淫乱度"
    assert var_names.get(2) == "セックス回数"
    assert switch_names.get(1) == "裸"
    assert switch_names.get(2) == "普段着"
    maps = extract_maps(GAME)
    assert len(maps) >= 10 and maps[0][1]
    print(f'   OK: переменных {len(var_names)}, карт {len(maps)}')
else:
    print('   ПРОПУСК: тестовая игра не найдена')

print('2) Чит-выражения щупальца RPGM (_cheat_expr)...')
from app.engines.rpgmaker.tentacle import RpgMakerTentacle as RT

cases = [
    ("gold_set", {"value": 5}, "$gameParty._gold = 5"),
    ("gold_add", {"value": -3}, "$gameParty.gainGold(-3)"),
    ("var_set", {"index": 2, "value": "x"},
     '$gameVariables.setValue(2, "x")'),
    ("switch_set", {"index": 7, "value": True},
     "$gameSwitches.setValue(7, true)"),
    ("switch_set", {"index": 7, "value": False},
     "$gameSwitches.setValue(7, false)"),
    ("speed", {"value": 6}, "$gamePlayer.setMoveSpeed(6)"),
    ("through", {"value": True}, "$gamePlayer.setThrough(true)"),
    ("click_tp", {"value": True}, "window.__octopus.clickTp = true"),
    ("teleport", {"mapId": 3, "x": 1, "y": 2},
     "$gamePlayer.reserveTransfer(3, 1, 2, 0, 0), 'teleported'"),
]
for cmd, kw, expected in cases:
    got = RT._cheat_expr(cmd, **kw)
    assert got == expected, (cmd, got, expected)
for cmd in ("heal", "win_battle", "give_item", "actor_set"):
    assert RT._cheat_expr(cmd, kind="item", id=1, count=1,
                          actorId=1, field="level", value=1), cmd
assert RT._cheat_expr("no_such_cheat") is None
print(f'   OK: {len(cases)} точных выражения + составные команды')

print('3) Полный цикл: записывающее щупальце <-> CheatTab...')
from app.core.session import GameSession
from app.core.tentacles.base import Tentacle
from app.ui.main_window import MainWindow

STATE = {
    "type": "state", "gold": 777, "mapId": 5, "inBattle": False,
    "party": [
        {"id": 1, "name": "Aira", "className": "Witch", "level": 12,
         "hp": 100, "mhp": 150, "mp": 40, "mmp": 80, "exp": 500,
         "inParty": True, "params": [150, 80, 20, 18, 30, 25, 22, 10]},
    ],
    "items": [
        {"kind": "item", "id": 1, "name": "Potion", "count": 3},
        {"kind": "weapon", "id": 2, "name": "Staff", "count": 1},
    ],
    "variables": [0, 99, 7],
    "switches": [False, True],
}


class RecTentacle(Tentacle):
    """Тестовое щупальце: записывает команды, отдаёт фейковый снимок."""

    key = "rpgmaker"

    def __init__(self):
        super().__init__()
        self._att = False
        self.sent = []

    def launch(self, target):
        self._att = True
        self.attached.emit()
        return True

    def attach(self, pid):
        return self.launch("")

    def detach(self):
        self._att = False
        self.detached.emit("")

    def is_attached(self):
        return self._att

    def game_pid(self):
        return os.getpid()

    def request_state(self):
        self.state_received.emit(dict(STATE))
        return True

    def send_cheat(self, cmd, **kwargs):
        self.sent.append((cmd, kwargs))
        self.cheat_ack.emit(cmd, True, "", "")
        return True


import tempfile

with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "www", "data"))
    os.makedirs(os.path.join(td, "www", "js", "plugins"))
    open(os.path.join(td, "Game.exe"), "w").write("fake")
    open(os.path.join(td, "www", "js", "rpg_core.js"), "w").write("//")
    with open(os.path.join(td, "www", "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "T",
                   "variables": ["", "Мана", "Усталость"],
                   "switches": ["", "Голая", "Юбка"]}, f,
                  ensure_ascii=False)
    with open(os.path.join(td, "www", "data", "Map001.json"), "w",
              encoding="utf-8") as f:
        json.dump({"events": []}, f)

    w = MainWindow()
    w.settings.setValue("auto_launch", False)
    assert w.open_project(td) == "mv"

    rec = RecTentacle()
    assert w.session.launch(rec, td)
    assert w.channel() is rec

    # состояние -> таблицы
    w.cheat_tab._request_state()
    for _ in range(50):
        app.processEvents()
        time.sleep(0.01)
    assert w.cheat_tab.gold_value.value() == 777   # живое золото
    assert w.cheat_tab.party_table.rowCount() == 1
    assert w.cheat_tab.party_table.item(0, 1).text() == "Aira"
    assert w.cheat_tab.party_table.item(0, 4).text() == "100/150"
    assert w.cheat_tab.items_table.rowCount() == 2
    print('   таблицы партии и предметов заполнены')

    # переменные/переключатели по списку имён System.json
    # (индексы дополняются значениями из снимка состояния)
    n_rows = w.cheat_tab.vars_table.rowCount()
    assert n_rows >= 2, n_rows
    names = [w.cheat_tab.vars_table.item(r, 1).text()
             for r in range(n_rows)]
    assert "Мана" in names and "Усталость" in names, names
    assert w.cheat_tab.sw_table.rowCount() >= 2
    print('   переменные и переключатели из System.json на месте')

    # чит-команды уходят в щупальце
    w.cheat_tab._cheat("win_battle")
    w.cheat_tab._cheat("give_item", kind="item", id=1, count=5)
    w.cheat_tab._cheat("actor_set", actorId=1, field="level", value=99)
    cmds = [c for c, _ in rec.sent]
    assert cmds == ["win_battle", "give_item", "actor_set"], cmds
    assert rec.sent[1][1]["count"] == 5
    assert rec.sent[2][1]["value"] == 99
    print('   команды win_battle / give_item / actor_set доставлены')

    # ручное имя переменной сохраняется в проект
    item = w.cheat_tab.vars_table.item(0, 1)
    w.cheat_tab._loading = False
    item.setText("Любовь принцессы")
    idx = item.data(0x0100)
    assert w.project.var_names[str(idx)] == "Любовь принцессы"
    print('   ручное имя переменной сохранено в проект:', idx)

    w.stop_session(kill_game=False)
    assert w.channel() is None
    print('   отключение чистое')

print()
print('ВСЕ ТЕСТЫ ЧИТ-МЕНЮ ПРОШЛИ')
sys.stdout.flush()
os._exit(0)
