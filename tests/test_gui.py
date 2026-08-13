# -*- coding: utf-8 -*-
"""GUI offscreen: главное окно, вкладки, детект движков на синтетических
проектах, настройки (включая «ИИ корректор»), читы (выражения)."""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox

app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)

from app.engines.registry import MODULES, detect_engine
from app.engines.rpgmaker import RpgMakerModule
from app.engines.renpy import RenPyModule
from app.engines.twine import TwineModule
from app.engines.tyrano import TyranoModule
from app.ui.i18n import TR
from app.ui.main_window import MainWindow


def make_rpgm(root: str, variant: str = "mv") -> None:
    data = os.path.join(root, "www", "data") if variant == "mv" \
        else os.path.join(root, "data")
    os.makedirs(data)
    if variant == "mv":
        os.makedirs(os.path.join(root, "www", "js"))
        open(os.path.join(root, "www", "js", "rpg_core.js"), "w").close()
    else:
        os.makedirs(os.path.join(root, "js"))
        open(os.path.join(root, "js", "rmmz_core.js"), "w").close()
    with open(os.path.join(data, "System.json"), "w", encoding="utf-8") as f:
        json.dump({"gameTitle": "T", "variables": ["", "Мана"],
                   "switches": ["", "Голая"]}, f, ensure_ascii=False)
    with open(os.path.join(data, "Map001.json"), "w", encoding="utf-8") as f:
        json.dump({"events": [], "data": [0] * 36, "width": 3, "height": 3,
                   "displayName": "Старт"}, f, ensure_ascii=False)


def make_renpy(root: str) -> None:
    os.makedirs(os.path.join(root, "game"))
    with open(os.path.join(root, "game", "script.rpy"), "w",
              encoding="utf-8") as f:
        f.write('label start:\n    "Привет."\n')


def make_twine(root: str) -> None:
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as f:
        f.write('<tw-storydata name="T"><tw-passagedata pid="1" name="S">'
                "Hi!</tw-passagedata></tw-storydata>")


def make_tyrano(root: str) -> None:
    os.makedirs(os.path.join(root, "data", "scenario"))
    os.makedirs(os.path.join(root, "tyrano"))
    with open(os.path.join(root, "data", "scenario", "main.ks"),
              "w", encoding="utf-8") as f:
        f.write("こんにちは。\n[wait time=\"500\"]\n")


print("1) Реестр движков...")
assert MODULES == [RpgMakerModule, RenPyModule, TwineModule, TyranoModule]
with tempfile.TemporaryDirectory() as td:
    make_rpgm(td, "mv")
    mod = detect_engine(td)
    assert isinstance(mod, RpgMakerModule) and mod.variant == "mv"
    assert {"files", "cheats", "resources", "font"} <= mod.features
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    assert isinstance(detect_engine(td), RenPyModule)
with tempfile.TemporaryDirectory() as td:
    make_twine(td)
    assert isinstance(detect_engine(td), TwineModule)
with tempfile.TemporaryDirectory() as td:
    make_tyrano(td)
    assert isinstance(detect_engine(td), TyranoModule)
with tempfile.TemporaryDirectory() as td:
    assert detect_engine(td) is None
print("   OK")

print("2) Главное окно: вкладки и заголовок с версией...")
w = MainWindow()
assert "v" in w.windowTitle()
assert w.tabs.indexOf(w.welcome_tab) == 0
assert w.tabs.indexOf(w.projects_tab) == 1
assert w.cheat_tab is None and w._engine_tabs == []
print("   OK:", w.windowTitle())

print("3) Открытие проектов -> вкладки движка...")
with tempfile.TemporaryDirectory() as td:
    make_rpgm(td, "mv")
    assert w.open_project(td) == "mv"
    roles = [r for _, r in w._engine_tabs]
    assert "cheats" in roles and roles.count("module") >= 1
    assert w.cheat_tab is not None
    assert w.engine_module.extract(td)
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    assert w.open_project(td) == "renpy"
    assert not w.welcome_tab.font_box.isHidden()
with tempfile.TemporaryDirectory() as td:
    make_twine(td)
    assert w.open_project(td) == "twine"
    roles = [r for _, r in w._engine_tabs]
    assert "translate" in roles
with tempfile.TemporaryDirectory() as td:
    make_tyrano(td)
    assert w.open_project(td) == "tyrano"
    roles = [r for _, r in w._engine_tabs]
    # переменных в Tyrano нет (только внутренний конфиг движка) —
    # вкладка читов/переменных не добавляется
    assert roles == ["translate"]
    assert "cheats" not in w.engine_module.features
print("   OK")

print("4) Настройки: 3 вкладки (Основные/Файлы/ИИ корректор)...")
from app.ui.settings_tab import SettingsDialog
d = SettingsDialog(w)
tabs = [d.tabs.tabText(i) for i in range(d.tabs.count())]
assert len(tabs) == 3, tabs
assert "ИИ корректор" in tabs or "AI Corrector" in tabs
assert hasattr(d, "glossary_use_ai")
assert d.glossary_use_ai.isChecked()
old_lang = w.settings.value("ui_lang", "en")
d._save_and_close()
assert w.settings.value("glossary_use_ai", True, type=bool)
w.settings.setValue("ui_lang", old_lang)
print("   OK:", tabs)

print("5) Ручная правка строки перевода...")
with tempfile.TemporaryDirectory() as td:
    make_rpgm(td, "mz")
    w.open_project(td)
    w.project.entries = w.engine_module.extract(td)
    w.refresh_all()
    assert w.translate_tab.table.rowCount() > 0
    item = w.translate_tab.table.item(0, 3)
    item.setText("Ручной перевод")
    entry_id = item.data(0x0100)
    e = next(x for x in w.project.entries if x.id == entry_id)
    assert e.translation == "Ручной перевод" and e.status == "manual"
print("   OK")

print("6) Чит-выражения RPGM (без игры)...")
from app.engines.rpgmaker.tentacle import RpgMakerTentacle as RT
assert RT._cheat_expr("gold_set", value=5) == "$gameParty._gold = 5"
assert RT._cheat_expr("var_set", index=2, value="x") == \
    '$gameVariables.setValue(2, "x")'
assert RT._cheat_expr("switch_set", index=7, value=True) == \
    "$gameSwitches.setValue(7, true)"
assert RT._cheat_expr("teleport", mapId=3, x=1, y=2) == \
    "$gamePlayer.reserveTransfer(3, 1, 2, 0, 0), 'teleported'"
assert RT._cheat_expr("no_such_cheat") is None
print("   OK")

print("7) Ключи i18n для новых функций...")
for key in ("settings_corr_tab", "settings_glossary_box",
            "settings_glossary_ai", "welcome_open_folder",
            "glossary_search", "glossary_count", "glossary_lang_ja",
            "update_title", "update_found", "update_open_release",
            "tr_translate_done", "tr_translate_done_skipped",
            "tr_file_target_lang", "tr_file_target_lang_hint"):
    assert TR(key), key
print("   OK")

w.close()
print()
print("GUI OFFSCREEN: ВСЕ ПРОВЕРКИ ПРОШЛИ")
sys.stdout.flush()
os._exit(0)
