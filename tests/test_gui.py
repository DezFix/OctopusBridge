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
from app.engines.ajin import AjinModule
from app.engines.rpgmaker import RpgMakerModule
from app.engines.renpy import RenPyModule
from app.engines.twine import TwineModule
from app.engines.tyrano import TyranoModule
from app.engines.unity import UnityModule
from app.engines.wolf import WolfModule
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


def make_wolf(root: str) -> None:
    os.makedirs(os.path.join(root, "Data"))
    open(os.path.join(root, "Game.exe"), "w").close()
    with open(os.path.join(root, "Game.ini"), "w", encoding="utf-8") as f:
        f.write("Start=0\nSoftModeFlag=0\nWindowModeFlag=1\n")
    with open(os.path.join(root, "Data", "BasicData.wolf"), "wb") as f:
        f.write(b"DX\x08\x00" + b"\x00" * 100)


print("1) Реестр движков...")
assert MODULES == [AjinModule, RpgMakerModule, RenPyModule, TwineModule,
                   TyranoModule, WolfModule, UnityModule]
from app.engines.registry import DISABLED_ENGINES, enabled_modules
assert DISABLED_ENGINES >= {"ajin", "twine", "tyrano", "wolf", "unity"}
assert {c.key for c in enabled_modules()} == {"rpgmaker", "renpy"}
with tempfile.TemporaryDirectory() as td:
    make_rpgm(td, "mv")
    mod = detect_engine(td)
    assert isinstance(mod, RpgMakerModule) and mod.variant == "mv"
    assert {"files", "cheats", "resources", "font"} <= mod.features
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    assert isinstance(detect_engine(td), RenPyModule)
# Отложенные движки: код на месте (прямой detect класса работает),
# но общий детект их не видит — фокус на RPGM и Ren'Py.
with tempfile.TemporaryDirectory() as td:
    make_twine(td)
    assert TwineModule.detect(td) > 0
    assert detect_engine(td) is None
with tempfile.TemporaryDirectory() as td:
    make_tyrano(td)
    assert detect_engine(td) is None
with tempfile.TemporaryDirectory() as td:
    make_wolf(td)
    assert WolfModule.detect(td) > 0
    assert detect_engine(td) is None
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
    dash = w.welcome_tab
    assert dash.btn_font_choose is not None
    assert dash.spin_font_size.minimum() == 12
    assert dash.spin_font_size.maximum() == 64
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    assert w.open_project(td) == "renpy"
    assert not w.welcome_tab.font_box.isHidden()
# Отложенные движки не открываются как проекты: детект их не видит.
# Код и тесты движков на месте — вернутся отдельной задачей.
with tempfile.TemporaryDirectory() as td:
    make_twine(td)
    assert w.open_project(td) == "unknown"
    assert w.engine_module is None
with tempfile.TemporaryDirectory() as td:
    make_tyrano(td)
    assert w.open_project(td) == "unknown"
    assert w.engine_module is None
with tempfile.TemporaryDirectory() as td:
    make_wolf(td)
    assert w.open_project(td) == "unknown"
    assert w.engine_module is None
print("   OK")

print("4) Настройки: 3 вкладки (Основные/Файлы/Система, без нейро)...")
from app.ui.settings_tab import SettingsDialog
d = SettingsDialog(w)
tabs = [d.tabs.tabText(i) for i in range(d.tabs.count())]
assert len(tabs) == 3, tabs
assert "Система" in tabs or "System" in tabs
assert not hasattr(d, "glossary_use_ai")
assert not hasattr(d, "corr_eng")
# движок один, без выбора: combo нет, только почта MyMemory
assert d.files_eng["engine"] == "rotate"
assert "base_url" not in d.files_eng and "api_key" not in d.files_eng, \
    "Libre-поля должны быть удалены"
assert not d.files_eng["email"].isHidden()
d.files_eng["email"].setText("test@example.com")
assert hasattr(d, "cache_size_label") and d.cache_size_label.text()
assert hasattr(d, "btn_clean_cache") and hasattr(d, "auto_clean")
assert hasattr(d, "btn_open_cache") and d.btn_open_cache.icon().isNull() is False
assert d.cache_limit_spin.value() == w.settings.value("cache_auto_clean_mb", 200, type=int)
old_lang = w.settings.value("ui_lang", "en")
was_auto = d.auto_clean.isChecked()
d._save_and_close()
assert w.settings.value("cache_auto_clean", False, type=bool) == was_auto
assert w.settings.value("engine_files") == "rotate"
assert w.settings.value("mymemory_email") == "test@example.com"
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
# 7.7: gold_set идёт через gainGold(diff) — срабатывают хуки и UI,
# teleport — с защитой от боя (ES5-IIFE)
_gs = RT._cheat_expr("gold_set", value=5)
assert "gainGold" in _gs and "_gold =" not in _gs, _gs
assert RT._cheat_expr("var_set", index=2, value="x") == \
    '$gameVariables.setValue(2, "x")'
assert RT._cheat_expr("switch_set", index=7, value=True) == \
    "$gameSwitches.setValue(7, true)"
_tp = RT._cheat_expr("teleport", mapId=3, x=1, y=2)
assert "reserveTransfer" in _tp and "3, 1, 2" in _tp, _tp
assert RT._cheat_expr("no_such_cheat") is None
print("   OK")

print("7) Ключи i18n для новых функций...")
for key in ("settings_corr_tab", "settings_glossary_box",
            "settings_glossary_ai", "welcome_open_folder",
            "glossary_search", "glossary_count", "glossary_lang_ja",
            "update_title", "update_found", "update_open_release",
            "tr_translate_done", "tr_translate_done_skipped",
            "tr_file_target_lang", "tr_file_target_lang_hint",
            "tr_translate_lang", "tr_lang_all", "tr_lang_dialog_title",
            "tr_lang_dialog_question", "tr_lang_dialog_remember",
            "tr_lang_applied", "cheat_box_battle", "cheat_box_movement",
            "cheat_kind_all", "cheat_kind_items", "cheat_kind_weapons",
            "cheat_kind_armor", "tbl_col_idx", "tbl_col_id", "tbl_col_name",
            "tbl_col_value", "tbl_col_type", "tbl_col_count", "tbl_col_on",
            "party_col_class", "party_col_level", "party_col_hp",
            "party_col_mp", "party_col_exp", "party_col_inparty",
            "sv_search_ph", "sv_open_title", "sv_params", "sv_unsaved",
            "sv_save_err", "settings_status_ping",
            "cheat_names_translating", "tr_copy_original",
            "tr_copy_translation", "tr_copy_row",
            "settings_system_tab", "settings_cache_box",
            "settings_cache_size", "settings_cache_clean",
            "settings_cache_auto", "settings_cache_limit",
            "settings_cache_cleaned", "settings_cache_nothing",
            "settings_cache_open",
            "tr_verify_failed", "tr_verify_restored", "tr_verify_broken",
            "tr_apply_skipped", "tr_apply_longlines",
            "dash_font_live_ok", "dash_font_need_restart"):
    assert TR(key), key
print("   OK")

print("8) Ren'Py: диалог перевода (язык tl/* + режим)...")
from app.ui.translate_tab import _TranslateDialog
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    tl = os.path.join(td, "game", "tl")
    for lang in ("english", "french"):
        os.makedirs(os.path.join(tl, lang), exist_ok=True)
        with open(os.path.join(tl, lang, "adv.rpy"), "w",
                  encoding="utf-8") as f:
            f.write('translate %s strings:\n    old "Hello."\n    new "Hi."\n'
                    % lang)
    assert w.open_project(td) == "renpy"
    assert w.translate_tab._lang_options() == ["english", "french"]
    dlg = _TranslateDialog(["english", "french"], "english", w)
    assert dlg.lang() == "english"  # текущий язык игры выбран
    assert dlg.overwrite() is False  # по умолчанию — только новые
    dlg._select_mode(dlg._opt_all)
    assert dlg.overwrite() is True
    dlg.cb_lang.setCurrentIndex(0)  # «весь текст игры»
    assert dlg.lang() is None
print("   OK")

print("9) Мастер первоначальной настройки...")
from app.ui.setup_wizard import SetupWizard
s = w.settings
s.setValue("setup_done", False)
wiz = SetupWizard(w)
assert wiz._stack.count() == 4
assert wiz.btn_back.isHidden()
wiz._on_next()  # → языки
# Исходный язык не выбирается с 7.22 — всегда auto (см. setup_wizard).
assert wiz.cb_source is None
wiz.cb_target.setCurrentIndex(wiz.cb_target.findData("en"))
wiz.cb_ui_lang.setCurrentIndex(1)  # пересборка, выборы не теряются
assert wiz.cb_target.currentData() == "en"
assert wiz.cb_ui_lang.currentIndex() == 1
wiz._on_next()  # → переводчик
# выбора движка нет: один Автопилот, Libre-полей нет
assert not hasattr(wiz, "cb_provider")
assert not hasattr(wiz, "ed_base_url")
assert not hasattr(wiz, "ed_api_key")
wiz._on_next()  # → поведение
wiz._on_next()  # → готово
assert s.value("setup_done", False, type=bool) is True
assert s.value("source_lang") == "auto"
assert s.value("target_lang") == "en"
assert s.value("ui_lang") == "en"
assert s.value("engine_files") == "rotate"
# «Пропустить» — просто ставит флаг
s.setValue("setup_done", False)
wiz2 = SetupWizard(w)
wiz2._on_skip()
assert s.value("setup_done", False, type=bool) is True
s.setValue("ui_lang", "ru")
s.setValue("setup_done", True)
print("   OK")

w.close()

print("10) Выбор языков оригинала для перевода...")
from app.core.models import TranslationEntry as _TE
from app.ui.translate_tab import (filter_entries_by_src_lang,
                                  group_entries_by_src_lang)
_mini = [
    _TE(id=1, file="f", json_path="k1", context="c",
        original="こんにちは勇者"),
    _TE(id=2, file="f", json_path="k2", context="c",
        original="Hello brave Zorblax"),
    _TE(id=3, file="f", json_path="k3", context="c",
        original="12345"),
]
_groups = dict(group_entries_by_src_lang(_mini))
assert _groups.get("ja") == 1 and _groups.get("en") == 1, _groups
assert filter_entries_by_src_lang(_mini, None) == _mini
assert [e.id for e in filter_entries_by_src_lang(_mini, {"en"})] == [2, 3]
assert [e.id for e in filter_entries_by_src_lang(_mini, set())] == [1, 2, 3]
print("   OK")

print("11) Диалог перевода: старый дропдаун + галочки языков...")
from app.ui.translate_tab import _TranslateDialog
# движок без официальных языков: дропдаун скрыт, галочки с суммой
dlg = _TranslateDialog([], None, w,
                       [("en", 30), ("ja", 1632), (None, 5)])
assert dlg.cb_lang.isHidden()
assert dlg.selected_src_langs() == {"en", "ja", None}
assert "1667" in dlg._lbl_src_sum.text(), dlg._lbl_src_sum.text()
dlg._src_checks["ja"].setChecked(False)
assert dlg.selected_src_langs() == {"en", None}
assert "1667" not in dlg._lbl_src_sum.text()
assert "35" in dlg._lbl_src_sum.text()
dlg.reject()
# Ren'Py: дропдаун виден
dlg2 = _TranslateDialog(["french", "german"], None, w, [("en", 10)])
assert not dlg2.cb_lang.isHidden()
assert dlg2.lang() is None
assert dlg2.selected_src_langs() == {"en"}
dlg2.reject()
print("   OK")

print("12) channel_diag: видно расхождение статуса и канала...")
d = w.channel_diag()
assert "tentacle=" in d and "attached=" in d and "pid=" in d, d
assert w.channel() is None, "без запуска канала нет"
print("   OK:", d)

print("13) Заморозка переменных: дожимает только разошедшееся...")
from app.ui.cheat_tab import frozen_corrections
assert frozen_corrections([5, 0], [True], {1: 5}, {}) == []
assert frozen_corrections([0], [True], {1: 5}, {}) == [
    ("var_set", {"index": 1, "value": 5})]
assert frozen_corrections([], [False], {}, {1: True}) == [
    ("switch_set", {"index": 1, "value": True})]
assert frozen_corrections([5], [True], {1: 5, 99: "x"}, {1: True}) == [
    ("var_set", {"index": 99, "value": "x"})]
assert frozen_corrections(None, None, {1: 1}, None) == [
    ("var_set", {"index": 1, "value": 1})]
print("   OK")

print("14) Открытие проекта НЕ стартует перевод сам (только предложение)...")
w2 = MainWindow()
with tempfile.TemporaryDirectory() as td:
    make_rpgm(td, "mz")
    assert w2.open_project(td) == "mz"
    w2.project.entries = w2.engine_module.extract(td)
    assert len(w2.project.entries) > 0
    w2.project.tr_pending = 5
    w2.save_project()
    w2.open_project(td)  # повторное открытие с tr_pending > 0
    tt = w2.translate_tab
    assert tt.worker is None or not tt.worker.isRunning(), \
        "перевод стартовал сам при открытии"
    assert "5" in tt.lbl_status.text(), tt.lbl_status.text()
    # оверлей не показан — висеть нечему
    assert "Перевож" not in w2.loading.lbl_text.text(), \
        w2.loading.lbl_text.text()
w2.close()
print("   OK")

print("15) Ren'Py-приёмник не падает на битом пакете + cleanup останавливает опрос...")
from app.ui.renpy_cheat_tab import VariablesTab as _VT15
_vt15 = _VT15(w)
_vt15._on_vars("{{битый пакет")  # не должно бросить
_vt15._on_vars('[{"name": "gold", "value": 5}]')
assert any(v["name"] == "gold" for v in _vt15._vars), _vt15._vars
assert _vt15._timer.isActive()
_vt15.cleanup()
assert not _vt15._timer.isActive(), "таймер опроса не остановлен"
_vt15.deleteLater()
print("   OK")

print()
print("GUI OFFSCREEN: ВСЕ ПРОВЕРКИ ПРОШЛИ")
sys.stdout.flush()
os._exit(0)
