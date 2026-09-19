# -*- coding: utf-8 -*-
"""AjinSyoujyo (Electron Tyrano + asar + override): детект, слои, .ks, читы.

Синтетика только своя (без текста реальной игры): структура папки
собирается во временном каталоге — exe-пустышка, package.json/main.js
с маркерами перехватчика, override/data/scenario/*.ks с нейтральными
строками. Сети и реальной игры нет.
"""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.ajin import layout as ajin_layout
from app.core.ajin import parser as ajin_parser
from app.core.ajin.layered import LayeredView
from app.core.tentacles import create_tentacle
from app.engines.ajin import AjinModule
from app.engines.registry import detect_engine

SAMPLE_KS = """\
;synthetic comment — must be skipped
*synthetic_label
[l][r]
SAMPLE_HELLO_WORLD
[wait time="500"]
SAMPLE_SECOND_LINE[lr]
[link target="*c1"]SAMPLE_LINK_BODY[/link]
[button name="ok" text="SAMPLE_BTN" target="*yes"][r]
%synthetic_var SAMPLE_WITH_VAR
[iscript]
var MizunoYukiNozomi123 = 1;
[endscript]
"""

MAIN_JS = """\
const ASAR = path.join(process.resourcesPath, 'app.asar');
const overrides = new Map();
protocol.interceptFileProtocol('file', (request, callback) => {
  callback({ path: target });
});
"""


def make_minimal_asar(path: str) -> None:
    """Минимальный валидный asar (пустое дерево) — без игровых данных."""
    from app.core import asar as asar_mod
    with open(path, "wb") as f:
        asar_mod._write_header(f, {"files": {}})


def make_asar_with_files(path: str, files: dict[str, bytes]) -> None:
    """Валидный asar с файлами {rel: bytes} (для проверки рекурсии)."""
    from app.core import asar as asar_mod
    tree: dict = {"files": {}}
    offset = 0
    ordered = sorted(files)
    for rel in ordered:
        node = tree
        parts = rel.split("/")
        for p in parts[:-1]:
            node = node.setdefault("files", {}).setdefault(p, {"files": {}})
        data = files[rel]
        node.setdefault("files", {})[parts[-1]] = {
            "size": len(data), "offset": str(offset)}
        offset += len(data)
    with open(path, "wb") as f:
        asar_mod._write_header(f, tree)
        for rel in ordered:
            f.write(files[rel])


def make_game(root: str, with_saves: bool = True) -> str:
    open(os.path.join(root, "ajin_syoujyo.exe"), "w").close()
    app_dir = os.path.join(root, "resources", "app")
    os.makedirs(os.path.join(app_dir, "override", "data", "scenario"))
    make_minimal_asar(os.path.join(root, "resources", "app.asar"))
    with open(os.path.join(app_dir, "package.json"), "w",
              encoding="utf-8") as f:
        json.dump({"name": "ajin_syoujyo", "main": "main.js",
                   "window": {"width": 1920, "height": 1080}}, f)
    with open(os.path.join(app_dir, "main.js"), "w",
              encoding="utf-8") as f:
        f.write(MAIN_JS)
    with open(os.path.join(app_dir, "override", "data", "scenario",
                            "sample.ks"), "w", encoding="utf-8") as f:
        f.write(SAMPLE_KS)
    if with_saves:
        open(os.path.join(root, "ajin_syoujyo_tyrano_data.sav"),
             "w").close()
    return root


print("1) Детект: exe + asar + override + перехватчик -> вес 110/120...")
with tempfile.TemporaryDirectory() as td:
    make_game(td, with_saves=True)
    assert ajin_parser.detect(td) == 120
    assert AjinModule.detect(td) == 120
    mod = detect_engine(td)
    assert mod is not None and mod.key == "ajin", type(mod)
with tempfile.TemporaryDirectory() as td:
    make_game(td, with_saves=False)
    assert ajin_parser.detect(td) == 110
with tempfile.TemporaryDirectory() as td:
    # без перехватчика — не Ajin (обычный Tyrano или ничего)
    make_game(td)
    os.remove(os.path.join(td, "resources", "app", "main.js"))
    assert ajin_parser.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    assert ajin_parser.detect(td) == 0
print("   OK")

print("2) Слои: override перекрывает asar, запись идёт в override...")
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    view = LayeredView(td)
    files = view.list_scenario_files()
    assert files == ["data/scenario/sample.ks"], files
    lines = view.read_lines("data/scenario/sample.ks")
    assert any("SAMPLE_HELLO_WORLD" in ln for ln in lines)
    out = view.write_lines("data/scenario/sample.ks", lines)
    assert out.replace(os.sep, "/").endswith(
        "resources/app/override/data/scenario/sample.ks")
    assert os.path.isfile(out)
print("   OK")

print("3) Извлечение: сегменты + text-атрибуты, служебное пропущено...")
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    entries = ajin_parser.extract(td)
    texts = [e.original for e in entries]
    assert "SAMPLE_HELLO_WORLD" in texts
    assert "SAMPLE_SECOND_LINE" in texts
    assert "SAMPLE_LINK_BODY" in texts
    assert "SAMPLE_BTN" in texts
    assert "%synthetic_var SAMPLE_WITH_VAR" in texts
    assert "synthetic comment — must be skipped" not in texts
    assert "synthetic_label" not in texts
    assert "MizunoYukiNozomi123" not in " ".join(texts)
    assert all(e.file == "data/scenario/sample.ks" for e in entries)
    assert any(".seg[" in e.json_path for e in entries)
    assert any(".tag[" in e.json_path and ".text" in e.json_path
               for e in entries)
print("   OK:", len(entries), "entries")

print("4) Внедрение в override + restore (asar не трогаем)...")
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    asar_bytes = open(os.path.join(td, "resources", "app.asar"), "rb").read()
    entries = ajin_parser.extract(td)
    for e in entries:
        e.translation = "RU_" + e.original
        e.status = "translated"
    stats = ajin_parser.apply(td, entries)
    assert stats["strings"] == len(entries), stats
    assert stats["out_dir"].replace(os.sep, "/").endswith(
        "resources/app/override")
    with open(os.path.join(td, "resources", "app.asar"), "rb") as f:
        assert f.read() == asar_bytes  # asar не менялся
    again = ajin_parser.extract(td)
    assert all(x.original.startswith("RU_") for x in again), \
        [x.original for x in again][:3]
    rest = ajin_parser.restore_original(td)
    assert rest["restored"] >= 1, rest
    fresh = ajin_parser.extract(td)
    assert any(x.original == "SAMPLE_HELLO_WORLD" for x in fresh)
print("   OK")

print("5) Переменные: запись без %var пропускается...")
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    entries = ajin_parser.extract(td)
    target = next(e for e in entries if "%synthetic_var" in e.original)
    target.translation = "RU_WITHOUT_VAR"
    target.status = "translated"
    stats = ajin_parser.apply(td, entries)
    assert stats["unsafe_skipped"] >= 1, stats
print("   OK")

print("6) Щупальце: фабрика + чит-выражения без запуска игры...")
tent = create_tentacle("ajin")
assert tent is not None and tent.key == "ajin"
expr = tent._cheat_expr("var_set", name="tf.flag", value=1)
assert "variable.tf" in expr and "flag" in expr
expr2 = tent._cheat_expr("var_set", name="f.money", value=500)
assert "stat.f" in expr2 and "500" in expr2
expr3 = tent._cheat_expr("var_set", name="sf.opt", value=2)
assert "variable.sf" in expr3
assert tent._cheat_expr("nope") is None
assert "TYRANO" in tent.PAYLOAD and "__octopus_collectState" in tent.PAYLOAD
assert "__octopus_kag" in tent.PAYLOAD and "KAGV.stat" in tent.PAYLOAD
print("   OK")

print("7) layout(): только структура, без чтения сценариев...")
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    info = ajin_layout.layout(td)
    assert info["exe"] and info["exe"].endswith("ajin_syoujyo.exe")
    assert info["asar"] and info["asar"].endswith("app.asar")
    assert info["override"] and info["override"].endswith("override")
    assert info["has_interceptor"] is True
    assert info["has_saves"] is True
print("   OK")

print("8) Вкладки читов: live-переменные обновляются, правка уходит в игру...")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import json as _json

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow

_app = QApplication([])
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    w = MainWindow()
    assert w.open_project(td) == "electron-tyrano"
    roles = [r for _, r in w._engine_tabs]
    assert roles == ["translate", "cheats", "triggers"], roles
    var_tab = w.cheat_tab
    trg_tab = next(t for t, r in w._engine_tabs if r == "triggers")
    assert type(var_tab).__name__ == "AjinVariablesTab"
    assert type(trg_tab).__name__ == "AjinTriggersTab"
    # живой снимок из игры: число + триггер
    live = _json.dumps([{"name": "money", "value": 100},
                        {"name": "flag", "value": True}],
                       ensure_ascii=False)
    var_tab._on_vars(live)
    trg_tab._on_vars(live)
    assert [r["name"] for r in var_tab._model.rows] == ["money"]
    assert [r["name"] for r in trg_tab._model.rows] == ["flag"]
    # игра изменила число — следующий тик обновляет таблицу
    var_tab._on_vars(_json.dumps([{"name": "money", "value": 250},
                                  {"name": "flag", "value": True}]))
    assert var_tab._model.rows[0]["value"] == 250
    # правка числа уходит в игру через var_set (фейковый канал)
    sent = {}

    class _FakeTentacle:
        def is_attached(self):
            return True

        def send_cheat(self, cmd, **kw):
            sent.update(cmd=cmd, **kw)
            return True

    w.session._tentacle = _FakeTentacle()
    idx = var_tab._model.index(0, 1)
    assert var_tab._model.setData(idx, "999")
    var_tab._on_model_edit(idx, idx)
    assert sent == {"cmd": "var_set", "name": "money", "value": 999}, sent
    assert var_tab._model.rows[0]["value"] == 999
    w.session._tentacle = None
    # лишней кнопки запуска нет, ошибки чтения видны в статусе
    assert not hasattr(var_tab, "btn_ajin_launch")
    assert not hasattr(trg_tab, "btn_ajin_launch")
    var_tab._on_ack("get_vars", False, "boom", "")
    assert "boom" in var_tab.lbl_status.text()
    trg_tab._on_ack("get_vars", False, "boom", "")
    assert "boom" in trg_tab.lbl_status.text()
    w.close()
print("   OK")

print("9) Подпапки: рекурсивный обход override + asar...")
NESTED_KS = "NESTED_HELLO_EVENT\n[wait time=\"100\"]\n"
ASAR_ONLY_KS = "SYNTH_ASAR_ONLY_HOME\n"
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "ajin_syoujyo.exe"), "w").close()
    app_dir = os.path.join(td, "resources", "app")
    nested_dir = os.path.join(app_dir, "override", "data", "scenario",
                              "event")
    os.makedirs(nested_dir)
    with open(os.path.join(nested_dir, "nested.ks"), "w",
              encoding="utf-8") as f:
        f.write(NESTED_KS)
    make_asar_with_files(
        os.path.join(td, "resources", "app.asar"),
        {"data/scenario/home/asar_only.ks":
            ASAR_ONLY_KS.encode("utf-8")})
    view = LayeredView(td)
    assert view.list_scenario_files() == [
        "data/scenario/event/nested.ks",
        "data/scenario/home/asar_only.ks"], view.list_scenario_files()
    entries = ajin_parser.extract(td)
    by_file = {e.file for e in entries}
    assert by_file == {"data/scenario/event/nested.ks",
                       "data/scenario/home/asar_only.ks"}, by_file
    assert any(e.original == "NESTED_HELLO_EVENT" for e in entries)
    assert any(e.original == "SYNTH_ASAR_ONLY_HOME" for e in entries)
    for e in entries:
        e.translation = "RU_" + e.original
        e.status = "translated"
    stats = ajin_parser.apply(td, entries)
    assert stats["strings"] == len(entries), stats
    # asar-файл дополнен в override, сам asar цел
    assert os.path.isfile(os.path.join(
        app_dir, "override", "data", "scenario", "home", "asar_only.ks"))
    again = ajin_parser.extract(td)
    assert all(x.original.startswith("RU_") for x in again)
    rest = ajin_parser.restore_original(td)
    assert rest["restored"] >= 2, rest
    assert not os.path.isfile(os.path.join(
        app_dir, "override", "data", "scenario", "home", "asar_only.ks"))
    fresh = ajin_parser.extract(td)
    texts = [x.original for x in fresh]
    assert "NESTED_HELLO_EVENT" in texts
    assert "SYNTH_ASAR_ONLY_HOME" in texts  # снова виден asar-оригинал
print("   OK")

print("9a) Длинные строки: отчёт long_lines без правки текста...")
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    entries = ajin_parser.extract(td)
    long_e = next(e for e in entries
                  if e.original == "SAMPLE_HELLO_WORLD")
    long_e.translation = "X" * 60  # 18 -> 60: кандидат на налезание
    long_e.status = "translated"
    short_e = next(e for e in entries
                   if e.original == "SAMPLE_SECOND_LINE")
    short_e.translation = "RU"
    short_e.status = "translated"
    stats = ajin_parser.apply(td, entries)
    assert stats["long_lines_total"] == 1, stats
    assert len(stats["long_lines"]) == 1
    assert "data/scenario/sample.ks" in stats["long_lines"][0]
    # опасный перевод кнопки (оба вида кавычек) — пропуск, меню цело
    bad = next(e for e in entries if e.original == "SAMPLE_BTN")
    bad.translation = "RU \"Q\" 'Q'"
    bad.status = "translated"
    stats2 = ajin_parser.apply(td, entries)
    assert stats2["skipped_by"].get("tag_unsafe", 0) >= 1, stats2
    view2 = LayeredView(td)
    content = "\n".join(view2.read_lines("data/scenario/sample.ks"))
    assert "RU \"Q\"" not in content
    # сам текст записан как есть (без авто-вставок)
    assert any("X" * 60 in ln for ln in content.splitlines())
print("   OK")

print("9a2) Выражение в text=: литерал переводится, код цел...")
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    ks = os.path.join(td, "resources", "app", "override",
                      "data", "scenario", "expr.ks")
    os.makedirs(os.path.dirname(ks), exist_ok=True)
    with open(ks, "w", encoding="utf-8") as f:
        f.write("[ptext text=\"&'AFFECTION' + f.koko_status[0][5] + ''\"]\n"
                "[ptext text=\"&f.item[1][2]\"]\n")
    entries = ajin_parser.extract(td)
    lits = [e for e in entries if e.file == "data/scenario/expr.ks"]
    assert [(e.original, e.json_path) for e in lits] == [
        ("AFFECTION", "line[1].tag[0].text#0")], lits
    lits[0].translation = "ПРИВЯЗАННОСТЬ"
    lits[0].status = "translated"
    stats = ajin_parser.apply(td, entries)
    assert stats["strings"] >= 1, stats
    view = LayeredView(td)
    out = "\n".join(view.read_lines("data/scenario/expr.ks"))
    assert "text=\"&'ПРИВЯЗАННОСТЬ' + f.koko_status[0][5] + ''\"" in out, out
print("   OK")

print("9b) Кнопки меню: text= у glink извлекается с путём tag/text...")
with tempfile.TemporaryDirectory() as td:
    make_game(td)
    ks = os.path.join(td, "resources", "app", "override",
                      "data", "scenario", "sample.ks")
    with open(ks, "a", encoding="utf-8") as f:
        f.write('[glink color="red" size="20" text="SAMPLE_BTN_TXT" '
                'target="*x"]\n')
    entries = ajin_parser.extract(td)
    hits = [e for e in entries if e.original == "SAMPLE_BTN_TXT"]
    assert len(hits) == 1, [e.original for e in entries]
    assert hits[0].file == "data/scenario/sample.ks"
    assert ".tag[" in hits[0].json_path
    assert hits[0].json_path.endswith(".text")
print("   OK")

print("10) Поиск запущенной игры: свой exe с портом — да, дети/хелперы/чужой каталог — нет...")
from app.core import process as proc_mod
from app.engines.ajin import tentacle as ajin_tent

with tempfile.TemporaryDirectory() as td:
    game_exe = os.path.join(td, "ajin_syoujyo.exe")
    open(game_exe, "w").close()
    os.makedirs(os.path.join(td, "resources"))
    open(os.path.join(td, "resources", "app.asar"), "w").close()

    class _FakeProc:
        def __init__(self, pid, name, exe):
            self.info = {"pid": pid, "name": name, "exe": exe}

    MAIN = _FakeProc(111, "ajin_syoujyo.exe", game_exe)
    CHILD = _FakeProc(112, "ajin_syoujyo.exe", game_exe)
    HELPER = _FakeProc(113, "Uninstall ajin.exe",
                       os.path.join(td, "Uninstall ajin.exe"))
    OUTER = _FakeProc(114, "ajin_syoujyo.exe",
                      os.path.join("E:\\", "other", "ajin_syoujyo.exe"))
    CMDLINES = {
        111: [game_exe, "--remote-debugging-port=9333"],
        112: [game_exe, "--type=renderer"],
        113: [os.path.join(td, "Uninstall ajin.exe")],
        114: [os.path.join("E:\\", "other", "ajin_syoujyo.exe")],
    }

    import psutil as _psutil
    real_iter = _psutil.process_iter
    real_cmdline = proc_mod.cmdline_of
    _psutil.process_iter = lambda *a, **k: iter([MAIN, CHILD, HELPER,
                                                 OUTER])
    proc_mod.cmdline_of = lambda pid: CMDLINES.get(pid, [])
    try:
        hits = proc_mod.find_game_processes("ajin", td)
        assert [(h["pid"], h["port"]) for h in hits] == [(111, 9333)], hits
        assert ajin_tent.pick_running(td) == (111, 9333)
        # процесс есть, но без флага отладки — port=0 (нужен перезапуск)
        CMDLINES[111] = [game_exe]
        assert ajin_tent.pick_running(td) == (111, 0)
        assert ajin_tent.pick_running(os.path.join("E:\\", "other")) is None
    finally:
        _psutil.process_iter = real_iter
        proc_mod.cmdline_of = real_cmdline
print("   OK")

print("11) Заморозка: ❄, дожатие в игру, порядок, снятие...")
from PySide6.QtCore import Qt as _Qt

with tempfile.TemporaryDirectory() as td:
    make_game(td)
    w2 = MainWindow()
    assert w2.open_project(td) == "electron-tyrano"
    var_tab = w2.cheat_tab
    trg_tab = next(t for t, r in w2._engine_tabs if r == "triggers")
    live = _json.dumps([{"name": "money", "value": 100},
                        {"name": "hp", "value": 50},
                        {"name": "flag", "value": True}])
    var_tab._on_vars(live)
    trg_tab._on_vars(live)
    assert [r["name"] for r in var_tab._model.rows] == ["hp", "money"]
    # замораживаем money: статус, порядок (вверх сразу), хранение
    mrow = next(i for i, r in enumerate(var_tab._model.rows)
                if r["name"] == "money")
    assert var_tab._model.setData(var_tab._model.index(mrow, 2),
                                  _Qt.Checked, _Qt.CheckStateRole)
    assert var_tab._model.frozen == {"money": 100}
    assert "money" in var_tab.lbl_status.text()
    assert [r["name"] for r in var_tab._model.rows][0] == "money"
    # игра изменила значение — дожатие возвращает 100
    sent2 = {}

    class _FakeTent2:
        def is_attached(self):
            return True

        def send_cheat(self, cmd, **kw):
            sent2.update(cmd=cmd, **kw)
            return True

    w2.session._tentacle = _FakeTent2()
    var_tab._on_vars(_json.dumps([{"name": "money", "value": 30},
                                  {"name": "hp", "value": 50}]))
    assert sent2 == {"cmd": "var_set", "name": "money",
                     "value": 100}, sent2
    # сошлось — повторных посылок нет
    sent2.clear()
    var_tab._on_vars(_json.dumps([{"name": "money", "value": 100},
                                  {"name": "hp", "value": 50}]))
    assert sent2 == {}
    # правка замороженной строки двигает и заморозку (числом, не строкой)
    idx = var_tab._model.index(0, 1)
    assert var_tab._model.setData(idx, "200")
    var_tab._on_model_edit(idx, idx)
    assert sent2 == {"cmd": "var_set", "name": "money", "value": 200}, sent2
    assert var_tab._model.frozen == {"money": 200}
    # снятие: дожатия прекращаются
    assert var_tab._model.setData(var_tab._model.index(0, 2),
                                  _Qt.Unchecked, _Qt.CheckStateRole)
    assert var_tab._model.frozen == {}
    sent2.clear()
    var_tab._on_vars(_json.dumps([{"name": "money", "value": 10},
                                  {"name": "hp", "value": 50}]))
    assert sent2 == {}
    # триггеры: bool тоже морозится
    assert trg_tab._model.setData(trg_tab._model.index(0, 2),
                                  _Qt.Checked, _Qt.CheckStateRole)
    assert trg_tab._model.frozen == {"flag": True}
    sent2.clear()
    trg_tab._on_vars(_json.dumps([{"name": "flag", "value": False}]))
    assert sent2 == {"cmd": "var_set", "name": "flag",
                     "value": True}, sent2
    # смена проекта сбрасывает заморозку
    var_tab.on_project_opened()
    assert var_tab._model.frozen == {}
    w2.session._tentacle = None
    w2.close()
print("   OK")

print()
print("ВСЕ ТЕСТЫ AJIN ПРОШЛИ")
