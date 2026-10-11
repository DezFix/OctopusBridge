# -*- coding: utf-8 -*-
"""Фиксы Twine по аудиту: пустой LZ-сейв (IndexError), индексные
строковые литералы макросов ($inv["sword"]), детект .htm/.HTML/
подпапок, стабильное имя файла слота при date:0."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.twine import parser as twine
from app.core.twine import savefile
from app.engines.twine import TwineModule

# ── 1) пустой/пробельный .save: None вместо IndexError ──

print("1) lz_decompress_base64: пустая/пробельная строка → None...")
assert savefile.lz_decompress_base64("") is None
assert savefile.lz_decompress_base64("   ") is None
assert savefile.lz_decompress_base64("\t\n ") is None
with tempfile.TemporaryDirectory() as td:
    for name, content in (("empty.save", ""), ("ws.save", "  \t\n")):
        p = os.path.join(td, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        try:
            savefile.load_save(p)
            raise AssertionError(
                "load_save(%r) должен бросить ValueError" % name)
        except ValueError:
            pass
print("   OK")

# ── 2) индексный литерал макроса — код, а не переводимый текст ──

MACRO_HTML = (
    "<!DOCTYPE html>\n<html><head><title>T</title></head>\n"
    "<body><tw-storydata name=\"T\" startnode=\"1\" creator=\"Twine\""
    " creator-version=\"2.3.9\" format=\"SugarCube\""
    " format-version=\"2.36.1\" hidestoryicons=\"\">"
    "<tw-passagedata pid=\"1\" name=\"Shop\" tags=\"\">Items:\n"
    "&lt;&lt;print $inv[\"sword\"]&gt;&gt;\n"
    "Greeting: &lt;&lt;print \"hello there\"&gt;&gt;\n"
    "Price: &lt;&lt;print $prices[\"sword\"]&gt;&gt;"
    "</tw-passagedata></tw-storydata></body></html>\n"
)

print('2) <<print $inv["sword"]>>: индексный литерал не извлекается...')
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, "game.html"), "w", encoding="utf-8") as f:
        f.write(MACRO_HTML)
    entries = twine.extract(td)
    originals = [e.original for e in entries]
    assert "sword" not in originals, originals
    assert "hello there" in originals, originals
print("   OK")

# ── 3) детект: .htm / .HTML / подпапка на уровень глубже ──

STORY = ("<html><body><tw-storydata name=\"T\">"
         "</tw-storydata></body></html>")

print("3) detect(): .htm / .HTML / sub/index.html → 60...")
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, "story.htm"), "w", encoding="utf-8") as f:
        f.write(STORY)
    assert TwineModule.detect(td) == 60
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, "STORY.HTML"), "w", encoding="utf-8") as f:
        f.write(STORY)
    assert TwineModule.detect(td) == 60
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "sub"))
    with open(os.path.join(td, "sub", "index.html"), "w",
              encoding="utf-8") as f:
        f.write(STORY)
    assert TwineModule.detect(td) == 60
with tempfile.TemporaryDirectory() as td:
    # отрицательный контроль: тег в .txt — не игра
    with open(os.path.join(td, "readme.txt"), "w", encoding="utf-8") as f:
        f.write("<tw-storydata>")
    assert TwineModule.detect(td) == 0
print("   OK")

# ── 4) write_slots: date:0 → стабильное имя файла ──

print("4) write_slots: date:0 — повторный синк перезаписывает тот же файл...")
SLOTS = [{"id": "0", "date": 0, "data": "x"}]
with tempfile.TemporaryDirectory() as td:
    p1 = savefile.write_slots(td, "MyGame", SLOTS)
    p2 = savefile.write_slots(td, "MyGame", SLOTS)
    assert p1 == p2, (p1, p2)
    saves = sorted(f for f in os.listdir(td) if f.endswith(".save"))
    assert len(saves) == 1, saves
    assert saves[0] == "MyGame-19700101-000000-slot0.save", saves
    # date отсутствует — та же стабильная заглушка
    p3 = savefile.write_slots(td, "MyGame", [{"id": "1", "data": "y"}])
    p4 = savefile.write_slots(td, "MyGame", [{"id": "1", "data": "y"}])
    assert p3 == p4, (p3, p4)
    # настоящая дата — не эпоха
    p5 = savefile.write_slots(
        td, "MyGame", [{"id": "2", "date": 1700000000000, "data": "z"}])
    assert p5 and "19700101" not in p5[0], p5
print("   OK")

print("ALL TWINE FIXES OK")

# -- 5) soft-disable: files off, cheats stay --
print('5) soft-disable: TwineModule.features has no files...')
assert 'files' not in TwineModule.features
assert 'cheats' in TwineModule.features
print('   OK')

# -- 6) extract writes no index.json beside the game --
print('6) soft-disable: TwineModule.extract writes no index.json...')
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, 'game.html'), 'w', encoding='utf-8') as f:
        f.write(MACRO_HTML)
    mod = TwineModule(td)
    entries = mod.extract(td)
    assert len(entries) > 0, entries
    leftovers = [f for f in os.listdir(td) if f.endswith('.json')]
    assert leftovers == [], leftovers
print('   OK')

# -- 7) parser.apply frozen but callable directly --
print('7) frozen: parser.apply still works when called directly...')
assert hasattr(twine, 'apply')
assert hasattr(twine, 'restore_original')
assert hasattr(twine, 'write_story_json')
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, 'game.html'), 'w', encoding='utf-8') as f:
        f.write(MACRO_HTML)
    entries = twine.extract(td)
    assert len(entries) > 0, entries
    for e in entries:
        e.translation = e.original + ' RU'
    res = twine.apply(td, entries, target_lang='ru')
    assert res.get('files') == 1, res
    out = res.get('out_file')
    assert out and os.path.isfile(out), res
    with open(out, encoding='utf-8') as f:
        txt = f.read()
    assert ' RU' in txt, txt
print('   OK')

print('ALL TWINE SOFT-DISABLE OK')
