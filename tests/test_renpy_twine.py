# -*- coding: utf-8 -*-
"""Ren'Py и Twine: детект, извлечение, внедрение (tl/HTML), дедупликация,
патч шрифтов Ren'Py, LZ-сейвы Twine."""
import io
import os
import re
import shutil
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

print("2d) Ren'Py: многострочные диалоги в .rpy извлекаются и пишутся как \\\\n...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    script = ('define e = Character("Айра")\n'
              'label start:\n'
              '    e "Первая строка\n'
              '        вторая строка"\n')
    with open(os.path.join(td, "game", "script.rpy"), "w",
              encoding="utf-8") as f:
        f.write(script)
    entries = renpy.extract(td)
    texts = [e.original for e in entries]
    assert "Первая строка\n        вторая строка" in texts, texts
    for e in entries:
        e.translation = "TR:" + e.original
    stats = renpy.apply(td, entries, "ru")
    content = open(os.path.join(stats["out_dir"], "ob_game__script.rpy"),
                   encoding="utf-8").read()
    assert 'old "Первая строка\\n        вторая строка"' in content, content
print("   OK")

print("2e) Ren'Py: .rpyc — тексты-списки (интерполяция) разбиваются на части...")
from app.core.renpy import parser as _renpy


class _Var:
    pass


class _FakeSay:
    pass


class _FakeMenu:
    pass


_FakeSay.__name__ = "Say"
_FakeMenu.__name__ = "Menu"
say = _FakeSay()
say.what = ["Привет, ", _Var(), "!"]
say.who = None
out = _renpy._walk_ast([say])
assert ("dialogue", "Привет, ") in out, out
assert ("dialogue", "!") in out, out
menu = _FakeMenu()
menu.items = [(["Идти ", _Var(), " дальше"], None)]
out2 = _renpy._walk_ast([menu])
assert ("choice", "Идти ") in out2, out2
assert ("choice", " дальше") in out2, out2
assert _renpy._string_parts("просто строка") == ["просто строка"]
assert _renpy._string_parts(None) == []
assert _renpy._string_parts(["a", 1, "b"]) == ["a", "b"]
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
A wolf appears!
Talk with her: <<= either('Option number one: very long text to exceed two hundred characters limit so the macro gets masked entirely, yes indeed this is the first option text.', 'Second option text which is also quite long to make sure we exceed the masking limit of the parser, absolutely yes.', 'Third option with more words to be safely beyond two hundred characters as well, that is correct.')>>
[[Crapt!|forest2][$pic to 1, $epic to true, $noclick
to true] ]</tw-passagedata><tw-passagedata pid="3" name="GameTime" tags="widget">&lt;&lt;widget "adddays"&gt;&gt;
&quot;Jan&quot;, &quot;Feb&quot;, &quot;Mar&quot;, &quot;Apr&quot;, &quot;May&quot;, &quot;Jun&quot;,
&quot;Jul&quot;, &quot;Aug&quot;, &quot;Sep&quot;, &quot;Oct&quot;, &quot;Nov&quot;, &quot;Dec&quot;
$gameDate to new Date(2489, 1, 24, 22, 0);
&lt;&lt;/widget&gt;&gt;</tw-passagedata><tw-passagedata pid="4" name="StoryInit" tags="">&lt;&lt;set $gold to 5&gt;&gt;</tw-passagedata><tw-passagedata pid="5" name="Fragments" tags="">/* tiny-pastry */</tw-passagedata><tw-passagedata pid="6" name="Setup" tags="">&lt;&lt;set $mcrel = {
faith: 0,
devotion: 20,
extra: 0,
}&gt;&gt;
OK text after.</tw-passagedata><tw-passagedata pid="7" name="WikiForms" tags="">[[Go home->Home]]
[[Home<-Go home]]
[img[Go home|home.png][Home][$done to true]]
[[Grocery][$bought to "milk"]]
$thing["name"] is here
$thing['prop'] and $var.prop.
End of first line \\
continuation text.</tw-passagedata><tw-passagedata pid="8" name="CodePass" tags="init">&lt;&lt;set $cfg to 1&gt;&gt;
init code here</tw-passagedata></tw-storydata></body></html>
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
    # сегментный разбор: текст внутри строки с макросами извлекается
    assert "You are lost." in originals
    assert not any("<<set" in o for o in originals)
    # подписи ссылок [[подпись|таргет]] переводятся: таргет (имя пассажа)
    # замаскирован токеном, подпись остаётся текстом
    assert "Go deeper" in originals
    assert "Go home" in originals
    # вложенная ссылка-сеттер ([[text|passage][$var to ...]]) с висячей
    # [[ (разбита на строки) — код-структура, не переводим; ссылка
    # [[Grocery][...]] без разделителя — подпись == таргет, тоже
    assert not any("Crapt" in o or "epic to" in o for o in originals)
    # макрос внутри строки маскируется: текст по обе стороны извлекается
    # отдельными сегментами, сам макрос не попадает в записи
    assert "You grab" in originals
    assert "from the shelf." in originals
    assert not any("<<" in o or "[[" in o or "<x" in o
                   for o in originals)
    # строка с выполняющим кодом (<<set>>): сам код не извлекается,
    # текст вокруг кода — извлекается (сегментный разбор)
    assert not any("<<set" in o for o in originals)
    assert "Clock:" in originals
    assert "starts now." in originals
    # пассажи-виджеты и служебные (StoryInit) — код, не переводим
    assert not any(("Jan" in o or "widget" in o or "gameDate" in o
                    or "gold to 5" in o) for o in originals)
    # комментарий в коде (/* … */) — не текст для игрока
    assert not any("tiny-pastry" in o for o in originals)
    # многострочный макрос (<<set $x = { … }>>) — строки-продолжения — код
    assert not any(("faith" in o or "devotion" in o or "mcrel" in o
                    or "OK text after" in o and False)
                   for o in originals)
    # а вот обычный текст после макроса — извлекается
    assert any("OK text after" in o for o in originals)
    # img-ссылка и ссылка без разделителя (подпись == таргет) — код
    assert not any(("Grocery" in o or "home.png" in o or "bought to" in o)
                   for o in originals)
    # naked-переменные с индексами/точками — код-сегменты, не извлекаются;
    # текст вокруг них извлекается
    nv = [o for o in originals if "is here" in o]
    assert nv and nv[0] == "is here", nv
    nv2 = [o for o in originals if o.strip() == "and"]
    assert nv2, nv2
    # line continuation: строка с '\' склеивает строки — не переводим,
    # а следующая строка — обычный текст (переводится)
    assert not any("End of first line" in o for o in originals)
    assert any("continuation text" in o for o in originals)
    # пассажи с код-тегами (init) — не переводим
    assert not any("cfg to 1" in o or "init code here" in o
                   for o in originals)
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
    # счётчик считает изменённые СТРОКИ: «You grab» и «from the shelf.»
    # лежат на одной строке (seg[0] и seg[2]) — 17 записей = 15 строк
    assert stats["strings"] == 15, stats
    text = open(story, encoding="utf-8").read()
    assert "RU:You wake up in a forest." in text
    assert "<<set $gold to 100>>" in text
    # подпись ссылки переведена, таргет (имя пассажа) не тронут
    assert "[[RU:Go deeper|forest2]]" in text
    assert "[[RU:Go home-&gt;Home]]" in text
    assert "[[Home&lt;-RU:Go home]]" in text
    assert "&lt;b&gt;RU:You are lost.&lt;/b&gt;" in text
    # макросы/теги внутри строки восстановлены после перевода
    assert "RU:You grab &lt;&lt;$item_name&gt;&gt; RU:from the shelf." in text, text
    assert "RU:Your gold: $gold." in text
    # переводчик добавил макрос в текст сегмента — строка не внедряется,
    # иначе игра упадёт («cannot find a closing tag for macro ...»)
    grab = next(e for e in entries if e.original == "You grab")
    grab.translation = "RU:You grab <<set $x to 1>> item"
    shutil.copy2(stats["backups"][0], story)  # оригинал из бэкапа
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    assert "<<set $x to 1>>" not in text
    # grab-скип не меняет счётчик: строка всё равно меняется сегментом
    # seg[2] («from the shelf.») той же строки
    assert stats["strings"] == 15, stats
    assert stats["backups"]
    # переводчик испортил макрос (перевёл текст внутри <<= either(...)>>,
    # сломав кавычки) — перевод не внедряется, строка остаётся исходной
    lost = next(e for e in entries if e.original == "You are lost.")
    lost.translation = ("RU:<x0/>Потерялся.<x1/> "
                        "<<= either('RU:1', 'RU:2')>>")
    shutil.copy2(stats["backups"][0], story)
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    assert "Потерялся" not in text, text
    assert "&lt;b&gt;You are lost.&lt;/b&gt;" in text
    # строка с испорченным макросом не меняется — счётчик на 1 меньше
    assert stats["strings"] == 14, stats
    # длинный макрос <<= either(…)>> (>200 символов) маскируется целиком
    # и остаётся целым после перевода — иначе кавычки/смысл ломаются
    either_e = next(e for e in entries
                    if e.original == "Talk with her:")
    either_e.translation = "RU:" + either_e.original
    shutil.copy2(stats["backups"][0], story)
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    import html as html_mod
    assert "<<= either('Option number one: very long text to exceed" \
        in html_mod.unescape(text), text[-400:]
    # переводчик добавил свой тег (<br>) — коды сегмента не совпадают,
    # перевод не внедряется
    either_e.translation = "RU:<x0/><br>добавлено"
    shutil.copy2(stats["backups"][0], story)
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    assert "<br>добавлено" not in html_mod.unescape(text)
    # скипы: lost (испорченный макрос) + either (<br>) — строки не меняются
    assert stats["strings"] == 13, stats
    # Ремонт из бэкапа: прошлый перевод сломал макрос (кириллица внутри
    # <<...>>) — строка восстанавливается из backup/-файла; сломанный
    # виджет (переведённые строки массива) — целиком; сломанная ссылка-
    # сеттер (переведены имена пассажей) — тоже
    text = text.replace(
        "You grab &lt;&lt;$item_name&gt;&gt; RU:from the shelf.",
        "You grab &lt;&lt;RU:предмет&gt;&gt; RU:from the shelf.")
    # сломанный виджет: кавычки-«ёлочки» в JS-коде (как в Masters of Raana)
    text = text.replace(
        '&quot;Jan&quot;, &quot;Feb&quot;, &quot;Mar&quot;, &quot;Apr&quot;, '
        '&quot;May&quot;, &quot;Jun&quot;,',
        '«Январь», «Февраль», «Март», «Апрель», «Май», «Июнь»,')
    # сломанная ссылка-сеттер: переведены имя пассажа и текст (Raana)
    text = text.replace(
        "[[Crapt!|forest2][$pic to 1, $epic to true, $noclick",
        "[[Крапт!|лес2][$pic to 1, $epic to true, $noclick")
    with open(story, "w", encoding="utf-8") as f:
        f.write(text)
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    assert "&lt;&lt;RU:предмет&gt;&gt;" not in text, text
    assert "You grab <<$item_name>> from the shelf." in text, text
    assert "Январь" not in text, text  # виджет восстановлен целиком
    assert '&quot;Jan&quot;, &quot;Feb&quot;' in text
    assert "Крапт" not in text, text   # ссылка-сеттер восстановлена
    assert "|forest2][" in text, text
    # строка с выполняющим кодом: перевод из старого проекта не внедряем
    old = [TranslationEntry(id=99, file=story, json_path="passage[1].line[4]",
                            context="", original="Clock: <<set $now to new Date()>> starts now.",
                            translation="RU:Часы: <<set $now to new Date()>> запущены.")]
    shutil.copy2(stats["backups"][0], story)
    stats = twine.apply(td, entries + old)
    text = open(story, encoding="utf-8").read()
    assert "RU:Часы" not in text, text  # перевод с кодом не внедряем
    assert "RU:Clock: &lt;&lt;set $now to new Date()&gt;&gt; RU:starts now." \
        in text, text  # строка цела, перевод сегментов сохранён
    # скипы: lost + either — их строки не меняются
    assert stats["strings"] == 13, stats
    # JS-код в <script>: перевод из старого проекта не внедряем
    old = [TranslationEntry(id=100, file=story, json_path="passage[1].line[6]",
                            context="", original="window.CLOCK.setMinutes(0);",
                            translation="RU:окно.ЧАСЫ.установитьМинуты(0);"),
            TranslationEntry(id=99, file=story, json_path="passage[1].line[4]",
                             context="", original="Clock: <<set $now to new Date()>> starts now.",
                             translation="RU:Часы: <<set $now to new Date()>> запущены.")]
    shutil.copy2(stats["backups"][0], story)
    stats = twine.apply(td, entries + old)
    text = open(story, encoding="utf-8").read()
    assert "window.CLOCK.setMinutes(0);" in text, text
    assert "RU:Clock: &lt;&lt;set $now to new Date()&gt;&gt; RU:starts now." \
        in text, text
    assert stats["strings"] == 13, stats
    # Ремонт: файл уже сломан прошлым переводом (в строке с <<set>> код
    # исчез) — apply восстанавливает оригинал из записи старого проекта
    text = text.replace(
        "RU:Clock: &lt;&lt;set $now to new Date()&gt;&gt; RU:starts now.",
        "RU:Часы: new Date() запущены.")
    with open(story, "w", encoding="utf-8") as f:
        f.write(text)
    stats = twine.apply(td, entries + old)
    text = open(story, encoding="utf-8").read()
    # repair вернул макрос из оригинала, сегменты переведены заново
    assert "RU:Clock: &lt;&lt;set $now to new Date()&gt;&gt; RU:starts now." \
        in text, text
    from app.engines.twine import TwineModule
    shutil.copy2(stats["backups"][0], story)
    mod = TwineModule(td)
    stats = mod.apply(td, entries, target_lang="ru")  # как зовёт UI
    # скипы: lost (испорченный макрос) + either (<br>)
    assert stats["strings"] == 13, stats
print("   OK")

print("4b) Twine: ремонт ссылок — легальная кириллица в подписи не откатывается...")
with tempfile.TemporaryDirectory() as td:
    story = make_twine(td)
    backup_root = os.path.join(td, "backup", "20260101_000000")
    os.makedirs(backup_root)
    shutil.copy2(story, os.path.join(backup_root, os.path.basename(story)))
    # легальный перевод подписи: кириллица ТОЛЬКО в подписи, таргет чист
    text = open(story, encoding="utf-8").read()
    text = text.replace("[[Go deeper|forest2]]", "[[Идти глубже|forest2]]")
    # сломанная ссылка: кириллица в таргете (имени пассажа)
    text = text.replace("[[Go home->Home]]", "[[Домой->Домой]]")
    with open(story, "w", encoding="utf-8") as f:
        f.write(text)
    twine.apply(td, [])
    text = open(story, encoding="utf-8").read()
    assert "[[Идти глубже|forest2]]" in text, text      # подпись сохранена
    assert "[[Домой-&gt;Домой]]" not in text, text        # таргет отремонтирован
    assert "[[Go home->Home]]" in text, text
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
