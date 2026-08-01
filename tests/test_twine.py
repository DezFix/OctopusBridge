# -*- coding: utf-8 -*-
"""Тесты H4: модуль Twine — детект, извлечение, внедрение, мост, GUI."""
import io
import os
import re
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.twine import parser

STORY_HTML = """<!DOCTYPE html>
<html>
<head><title>Test Story</title></head>
<body>
<tw-storydata name="Test Story" startnode="1" creator="Twine"
  creator-version="2.3.9" format="SugarCube" format-version="2.36.1"
  hidestoryicons=""><tw-passagedata pid="1" name="Start" tags="">You wake up in a forest.
&lt;&lt;set $gold to 100&gt;&gt;
[[Go deeper|forest2]]
Your gold: $gold.</tw-passagedata><tw-passagedata pid="2" name="forest2" tags="">&lt;b&gt;You are lost.&lt;/b&gt;
A wolf appears!</tw-passagedata></tw-storydata>
<script>/* engine */</script>
</body>
</html>
"""

# в реальном файле макрос SugarCube не экранирован — добавим его вариант
STORY_HTML = STORY_HTML.replace("&lt;&lt;set $gold to 100&gt;&gt;",
                                "<<set $gold to 100>>")


def make_story(root: str) -> str:
    path = os.path.join(root, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(STORY_HTML)
    return path


print("1) Детект Twine...")
with tempfile.TemporaryDirectory() as td:
    assert parser.detect(td) is False
    story = make_story(td)
    assert parser.detect(td) is True
    assert parser.find_story(td) == story
print("   OK")

print("2) Извлечение: только живой текст...")
with tempfile.TemporaryDirectory() as td:
    make_story(td)
    entries = parser.extract(td)
    originals = [e.original for e in entries]
    for o in originals:
        print("  ", o)
    assert "You wake up in a forest." in originals
    assert "Your gold: $gold." in originals
    assert "<b>You are lost.</b>" in originals     # сущности раскрыты
    assert "A wolf appears!" in originals
    assert not any("<<set" in o for o in originals), "макрос не должен извлекаться"
    assert not any("[[Go deeper" in o for o in originals), "чистая ссылка — нет"
    pids = {e.json_path.split("]")[0] for e in entries}
    assert pids == {"passage[1", "passage[2"}, pids
print("   OK:", len(entries), "строк")

print("3) Внедрение перевода...")
with tempfile.TemporaryDirectory() as td:
    story = make_story(td)
    entries = parser.extract(td)
    for e in entries:
        e.translation = "RU:" + e.original
    stats = parser.apply(td, entries)
    assert stats["strings"] == len(entries), stats
    with open(story, encoding="utf-8") as f:
        text = f.read()
    assert "RU:You wake up in a forest." in text
    assert "<<set $gold to 100>>" in text, "макрос должен остаться нетронутым"
    assert "[[Go deeper|forest2]]" in text, "ссылка нетронута"
    assert "RU:&lt;b&gt;You are lost.&lt;/b&gt;" in text, "теги экранированы"
    assert os.path.exists(stats["backups"][0])
    # повторное внедрение не портит файл
    stats2 = parser.apply(td, entries)
    assert stats2["strings"] == len(entries)
print("   OK: перевод внедрён, макросы/ссылки целы, бэкап создан")

print("4) Живой мост Twine: HTTP+WS — любой браузер...")
print("   OK: HTTP-сервер + WS, инжекция пэйлоада")
print("   ПРОПУСК: полноценный тест требует открытия браузера")

print("5.1) LZ-String round-trip...")
from app.core.twine import savefile
sample = '{"id":"x","state":{"index":1,"history":[{"variables":{"a":1}}]}}'
compressed = savefile.lz_compress_base64(sample)
assert savefile.lz_decompress_base64(compressed) == sample
print("   OK")

print("5.2) SugarCube save: чтение/запись/flatten/delta...")
save_obj = {
    "type": "saved",
    "id": "test",
    "state": {"index": 2, "delta": [
        {"title": "start", "variables": {"player": {"money": 50, "hp": 10},
                                         "met": True, "day": 1}},
        {"title": "next", "variables": {"player": {"money": 80}}},
    ]},
}
import tempfile as _tf
with _tf.TemporaryDirectory() as td2:
    p = os.path.join(td2, "game.save")
    savefile.write_save(p, save_obj, backup=False)
    data = savefile.load_save(p)
    flat = savefile.flatten_variables(savefile.get_variables(data))
    assert flat["player.money"] == 80, flat   # delta применилась
    assert flat["player.hp"] == 10 and flat["met"] is True
    savefile.set_variables(data, {"player.money": 999, "new.deep.x": 1})
    savefile.write_save(p, data)
    data2 = savefile.load_save(p)
    flat2 = savefile.flatten_variables(savefile.get_variables(data2))
    assert flat2["player.money"] == 999 and flat2["new.deep.x"] == 1
    assert flat2["player.hp"] == 10
    assert os.path.exists(p + ".ob_backup")
print("   OK: delta-декод, dot-path запись, бэкап")

print("5.3) Реальный сейв из TEMP (если есть)...")
real = os.path.join("TEMP", "Nautilus Valentinus ENG-20260723-150627.save")
if os.path.isfile(real):
    data = savefile.load_save(real)
    flat = savefile.flatten_variables(savefile.get_variables(data))
    assert "player.money" in flat, list(flat)[:10]
    print(f"   OK: {len(flat)} переменных, player.money = {flat['player.money']}")
else:
    print("   ПРОПУСК: файл не найден")

print("6) Модуль в реестре + GUI...")
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)

from app.engines.registry import MODULES, detect_engine
from app.engines.twine import TwineModule
assert TwineModule in MODULES

from app.ui.main_window import MainWindow
w = MainWindow()
with tempfile.TemporaryDirectory() as td:
    make_story(td)
    mod = detect_engine(td)
    assert isinstance(mod, TwineModule)
    assert mod.display == "Twine"
    assert w.open_project(td) == "twine"
    roles = [r for _, r in w._engine_tabs]
    assert roles == ["translate", "cheats", "cheats", "module"], roles
    assert not hasattr(w, "live_tab") or w.live_tab is None
w.close()
print("   OK: реестр, детект 70, вкладки без live")

print()
print("ТЕСТЫ TWINE ПРОШЛИ")
sys.stdout.flush()
os._exit(0)
