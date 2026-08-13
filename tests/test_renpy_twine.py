# -*- coding: utf-8 -*-
"""Ren'Py и Twine: детект, извлечение, внедрение (tl/HTML), дедупликация,
патч шрифтов Ren'Py, LZ-сейвы Twine."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.renpy import parser as renpy
from app.core.twine import parser as twine
from app.core.models import TranslationEntry

# ── Ren'Py ──

SCRIPT = '''define e = Character("Айра")
label start:
    e "Привет, я ведьма."
    "Повествование без имени."
    $ x = _("Явная строка")
    menu:
        "Первый выбор":
            pass
        "Второй выбор":
            pass
'''


def make_renpy(root: str) -> None:
    os.makedirs(os.path.join(root, "game"))
    with open(os.path.join(root, "game", "script.rpy"), "w",
              encoding="utf-8") as f:
        f.write(SCRIPT)


print("1) Ren'Py: детект и извлечение...")
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    assert renpy.detect(td)
    entries = renpy.extract(td)
    texts = [e.original for e in entries]
    assert "Привет, я ведьма." in texts
    assert "Первый выбор" in texts
    assert "Явная строка" in texts
    assert "some_label" not in texts and "не текст" not in texts
    print("   OK:", len(entries), "строк")

print("2) Ren'Py: генерация tl + идемпотентность + дедуп...")
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    entries = renpy.extract(td)
    for e in entries:
        e.translation = "TR:" + e.original
    stats = renpy.apply(td, entries, "ru")
    out = os.path.join(stats["out_dir"], "ob_game__script.rpy")
    content = open(out, encoding="utf-8").read()
    assert "translate russian strings:" in content
    assert 'old "Привет, я ведьма."' in content
    assert 'new "TR:Привет, я ведьма."' in content
    assert renpy.apply(td, entries, "ru")  # повторная генерация не падает
    dup = entries[:1] + entries[:1]
    for i, e in enumerate(dup):
        e.id = i + 1
    stats2 = renpy.apply(td, dup, "ru")
    c2 = open(os.path.join(stats2["out_dir"], "ob_game__script.rpy"),
              encoding="utf-8").read()
    assert c2.count('old "Привет, я ведьма."') == 1
print("   OK")

print("2b) Ren'Py: многострочные строки уходят как \\\\n (Ren'Py 8.2 не парсит сырые переводы строк)...")
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    entries = renpy.extract(td)
    entries.append(TranslationEntry(
        999, "game/script.rpy", "", "",
        "Первая строка\nВторая строка",
        "Первый перевод\nВторой перевод", "translated"))
    stats = renpy.apply(td, entries, "ru")
    out = os.path.join(stats["out_dir"], "ob_game__script.rpy")
    content = open(out, encoding="utf-8").read()
    assert 'old "Первая строка\\nВторая строка"' in content, content
    assert 'new "Первый перевод\\nВторой перевод"' in content, content
    for line in content.splitlines():
        if 'old "' in line or 'new "' in line:
            assert line.rstrip().endswith('"'), \
                f"строка old/new не однострочная: {line!r}"
    renpy.apply(td, entries, "ru")  # повторная генерация не падает
print("   OK")

print("2c) Ren'Py: многоязычность (tl/<lang>) — выбор одного языка...")
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    tl = os.path.join(td, "game", "tl")
    os.makedirs(os.path.join(tl, "english"), exist_ok=True)
    os.makedirs(os.path.join(tl, "french"), exist_ok=True)
    with open(os.path.join(tl, "english", "adv.rpy"), "w",
              encoding="utf-8") as f:
        f.write('translate english strings:\n'
                '    old "Hello, witch."\n'
                '    new "Hi, witch."\n')
    with open(os.path.join(tl, "french", "adv.rpy"), "w",
              encoding="utf-8") as f:
        f.write('translate french strings:\n'
                '    old "Bonjour, sorcière."\n'
                '    new "Salut, sorcière."\n')
    langs = renpy.list_languages(td)
    assert langs == ["english", "french"], langs
    base = {e.original for e in renpy.extract(td)}
    assert "Привет, я ведьма." in base
    assert "Hello, witch." in base and "Bonjour, sorcière." in base
    en = {e.original for e in renpy.extract(td, "english")}
    assert "Hello, witch." in en and "Bonjour, sorcière." not in en, en
    fr = {e.original for e in renpy.extract(td, "french")}
    assert "Bonjour, sorcière." in fr and "Hello, witch." not in fr, fr
    assert "Привет, я ведьма." in en and "Привет, я ведьма." in fr
print("   OK")

# ── Twine ──

STORY_HTML = """<!DOCTYPE html>
<html><head><title>Test Story</title></head>
<body><tw-storydata name="Test Story" startnode="1" creator="Twine"
  creator-version="2.3.9" format="SugarCube" format-version="2.36.1"
  hidestoryicons=""><tw-passagedata pid="1" name="Start" tags="">You wake up in a forest.
<<set $gold to 100>>
[[Go deeper|forest2]]
You grab <<$item_name>> from the shelf.
Clock: <<set $now to new Date()>> starts now.
Your gold: $gold.
<script>
window.CLOCK = new Date();
window.CLOCK.setMinutes(0);
</script></tw-passagedata><tw-passagedata pid="2" name="forest2"
  tags="">&lt;b&gt;You are lost.&lt;/b&gt;
A wolf appears!</tw-passagedata></tw-storydata></body></html>
"""


def make_twine(root: str) -> str:
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(STORY_HTML)
    return path


print("3) Twine: детект и извлечение живого текста...")
with tempfile.TemporaryDirectory() as td:
    make_twine(td)
    assert twine.detect(td)
    entries = twine.extract(td)
    originals = [e.original for e in entries]
    assert "You wake up in a forest." in originals
    assert "<x0/>You are lost.<x1/>" in originals
    assert not any("<<set" in o or "[[Go" in o for o in originals)
    # макрос внутри строки маскируется токеном, в файл не лезет
    shelf = next(e for e in entries
                 if e.original.startswith("You grab <x0/> from"))
    assert shelf.original == "You grab <x0/> from the shelf.", shelf.original
    # строка с выполняющим кодом (<<set>>) вообще не извлекается
    assert not any("Clock" in o for o in originals)
    # JS-код внутри <script> не извлекается
    assert not any("window" in o or "CLOCK" in o for o in originals)
    print("   OK:", len(entries), "строк")

print("4) Twine: внедрение — макросы и ссылки целы, бэкап...")
with tempfile.TemporaryDirectory() as td:
    story = make_twine(td)
    entries = twine.extract(td)
    for e in entries:
        e.translation = "RU:" + e.original
    stats = twine.apply(td, entries)
    assert stats["strings"] == len(entries)
    text = open(story, encoding="utf-8").read()
    assert "RU:You wake up in a forest." in text
    assert "<<set $gold to 100>>" in text
    assert "[[Go deeper|forest2]]" in text
    assert "RU:&lt;b&gt;You are lost.&lt;/b&gt;" in text
    # макросы/теги внутри строки восстановлены после перевода
    assert "RU:You grab &lt;&lt;$item_name&gt;&gt; from the shelf." in text, text
    assert "RU:Your gold: $gold." in text
    # переводчик потерял токен макроса — строка не внедряется,
    # иначе игра упадёт («cannot find a closing tag for macro ...»)
    for e in entries:
        if e.original.startswith("You grab <x0/>"):
            e.translation = "RU:You grab item from the shelf."
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    assert "You grab &lt;&lt;$item_name&gt;&gt; from the shelf." in text
    assert stats["strings"] == len(entries) - 1, stats
    assert stats["backups"]
    # строка с выполняющим кодом: перевод из старого проекта не внедряем
    old = [TranslationEntry(id=99, file=story, json_path="passage[1].line[4]",
                            context="", original="Clock: <<set $now to new Date()>> starts now.",
                            translation="RU:Часы: <<set $now to new Date()>> запущены.")]
    stats = twine.apply(td, entries + old)
    text = open(story, encoding="utf-8").read()
    assert "Clock: <<set $now to new Date()>> starts now." in text, text
    assert stats["strings"] == len(entries) - 1, stats
    # JS-код в <script>: перевод из старого проекта не внедряем
    old = [TranslationEntry(id=100, file=story, json_path="passage[1].line[6]",
                            context="", original="window.CLOCK.setMinutes(0);",
                            translation="RU:окно.ЧАСЫ.установитьМинуты(0);")]
    stats = twine.apply(td, entries + old)
    text = open(story, encoding="utf-8").read()
    assert "window.CLOCK.setMinutes(0);" in text, text
    assert stats["strings"] == len(entries) - 1, stats
    twine.apply(td, entries)  # повторное внедрение не портит файл
    from app.engines.twine import TwineModule
    mod = TwineModule(td)
    stats = mod.apply(td, entries, target_lang="ru")  # как зовёт UI
    assert stats["strings"] == len(entries) - 1  # строка без токена скипнута
print("   OK")

print("5) Twine: LZ-сейвы (round-trip + delta)...")
from app.core.twine import savefile
sample = '{"id":"x","state":{"index":1,"history":[{"variables":{"a":1}}]}}'
assert savefile.lz_decompress_base64(savefile.lz_compress_base64(sample)) == sample
save_obj = {"type": "saved", "id": "t", "state": {"index": 2, "delta": [
    {"title": "start", "variables": {"player": {"money": 50, "hp": 10}}},
    {"title": "next", "variables": {"player": {"money": 80}}},
]}}
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "game.save")
    savefile.write_save(p, save_obj, backup=False)
    data = savefile.load_save(p)
    flat = savefile.flatten_variables(savefile.get_variables(data))
    assert flat["player.money"] == 80 and flat["player.hp"] == 10
    savefile.set_variables(data, {"player.money": 999})
    savefile.write_save(p, data)
    assert savefile.flatten_variables(
        savefile.get_variables(savefile.load_save(p)))["player.money"] == 999
    assert os.path.exists(p + ".ob_backup")
print("   OK")

print()
print("ВСЕ ТЕСТЫ RENPY + TWINE ПРОШЛИ")
