# -*- coding: utf-8 -*-
"""Ren'Py и Twine: детект, извлечение, внедрение (tl/HTML), дедупликация,
патч шрифтов Ren'Py, LZ-сейвы Twine."""
import io
import json
import os
import pickle
import random
import re
import shutil
import sys
import tempfile
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.renpy import parser as renpy
from app.core.twine import parser as twine

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
    dup = [e for e in entries if e.original == "Привет, я ведьма."] \
        + [e for e in entries if e.original == "Привет, я ведьма."]
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

print("2d2) Ren'Py: осиротевшие ob_*.rpy от старых билдов удаляются...")
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    entries = renpy.extract(td)
    for e in entries:
        e.translation = "TR:" + e.original
    stats = renpy.apply(td, entries, "ru")
    tl_dir = stats["out_dir"]
    stale = os.path.join(tl_dir, "ob_tl__english__Code__Old.rpy")
    with open(stale, "w", encoding="utf-8") as f:
        f.write("translate russian strings:\n"
                '    old "Старая строка\n'
                '        с переносом"\n'
                '    new "Устаревший перевод"\n')
    with open(stale + "c", "wb") as f:
        f.write(b"RENPY RPC2" + b"\x00" * 36)  # скомпилированный вариант
    stats2 = renpy.apply(td, entries, "ru")
    assert not os.path.exists(stale), "осиротевший ob_*.rpy не удалён"
    assert not os.path.exists(stale + "c"), "осиротевший ob_*.rpyc не удалён"
    assert stats2["removed_orphans"] == 2, stats2
    remaining = [f for f in os.listdir(tl_dir)
                 if f.startswith("ob_") and f.endswith(".rpy")]
    assert "ob_activate.rpy" in remaining and "ob_game__script.rpy" in remaining
    for f in remaining:
        content = open(os.path.join(tl_dir, f), encoding="utf-8").read()
        for line in content.splitlines():
            if 'old "' in line or 'new "' in line:
                assert line.rstrip().endswith('"'), \
                    f"строка old/new не однострочная в {f}: {line!r}"

    # сценарий краша игры: старый билд сгенерировал ob_game__tl__* с теми же
    # old-строками («A translation ... already exists» при старте Ren'Py) —
    # повторный apply обязан вычистить и .rpy, и .rpyc
    dup = os.path.join(tl_dir, "ob_game__tl__russian__ob_Code__Old.rpy")
    with open(dup, "w", encoding="utf-8") as f:
        f.write("translate russian strings:\n"
                '    old "Прощай"\n    new "Старое"\n')
    dupc = dup + "c"
    with open(dupc, "wb") as f:
        f.write(b"RENPY RPC2" + b"\x00" * 36)
    stats3 = renpy.apply(td, entries, "ru")
    assert not os.path.exists(dup), "дубль old-строк не вычищен (.rpy)"
    assert not os.path.exists(dupc), "дубль old-строк не вычищен (.rpyc)"
    assert stats3["removed_orphans"] == 2, stats3

    # защита в apply: записи с источником из наших ob_-артефактов не пишутся
    fake = TranslationEntry(id=999, file="game/tl/russian/ob_Code__Old.rpy",
                            json_path="x", context="x",
                            original="Самоперевод", translation="XXX")
    stats4 = renpy.apply(td, entries + [fake], "ru")
    assert not os.path.exists(
        os.path.join(tl_dir, "ob_game__tl__russian__ob_Code__Old.rpy")), \
        "запись из ob_-артефакта попала в ob_*.rpy"
    assert stats4["removed_orphans"] == 0, stats4
print("   OK")

print("2d3) Ren'Py: наши ob_* артефакты не извлекаются как текст игры...")
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    tl_dir = os.path.join(td, "game", "tl", "russian")
    os.makedirs(tl_dir, exist_ok=True)
    with open(os.path.join(tl_dir, "ob_Code__Old.rpy"), "w",
              encoding="utf-8") as f:
        f.write("translate russian strings:\n"
                '    old "Старый артефакт"\n'
                '    new "Старый перевод"\n')
    with open(os.path.join(td, "game", "ob_dict.json"), "w",
              encoding="utf-8") as f:
        f.write('{"x": "y"}')
    with open(os.path.join(td, "game", "ob_activate.rpy"), "w",
              encoding="utf-8") as f:
        f.write("translate russian strings:\n"
                '    old "Активатор"\n')
    entries = renpy.extract(td)
    texts = [e.original for e in entries]
    assert "Старый артефакт" not in texts, texts
    assert "Активатор" not in texts, texts
    assert "Привет, я ведьма." in texts
print("   OK")

print("2d5) Ren'Py: пустой прогон (files==0) чистит битые ob_*.rpy/.rpyc старых билдов...")
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    tl_dir = os.path.join(td, "game", "tl", "russian")
    os.makedirs(tl_dir, exist_ok=True)
    # битый файл старого билда: сырые переносы строк в old («Could not
    # parse string») — как в реальном краше Demon Boy Saga
    broken = os.path.join(tl_dir, "ob_tl__english__Code__Old.rpy")
    with open(broken, "w", encoding="utf-8") as f:
        f.write("translate russian strings:\n"
                '    old "{b}-{/b} {i}Love you Shawty.\n'
                '    From : Peter Shaw  {/i}"\n'
                '    new "Люблю тебя"\n')
    with open(broken + "c", "wb") as f:
        f.write(b"RENPY RPC2" + b"\x00" * 36)
    # самоперевод старого билда: извлечён из наших же ob_* (дубль old,
    # «A translation ... already exists»)
    dup = os.path.join(tl_dir, "ob_game__tl__russian__ob_Code__Old.rpy")
    with open(dup, "w", encoding="utf-8") as f:
        f.write("translate russian strings:\n"
                '    old "Прощай"\n    new "Старое"\n')
    with open(dup + "c", "wb") as f:
        f.write(b"RENPY RPC2" + b"\x00" * 36)
    # здоровые файлы текущего билда (экранированный \\n) — трогать нельзя
    good = os.path.join(tl_dir, "ob_tl__english__Code__Good.rpy")
    with open(good, "w", encoding="utf-8") as f:
        f.write("translate russian strings:\n"
                '    old "Hello \\nwith \\\\n escape"\n'
                '    new "Привет"\n')
    with open(good + "c", "wb") as f:
        f.write(b"RENPY RPC2" + b"\x00" * 36)

    stats = renpy.apply(td, [], "ru")  # пустой прогон: переводов нет
    assert not os.path.exists(broken), "битый ob_*.rpy не вычищен"
    assert not os.path.exists(broken + "c"), "битый ob_*.rpyc не вычищен"
    assert not os.path.exists(dup), "самоперевод не вычищен"
    assert not os.path.exists(dup + "c"), "самоперевод .rpyc не вычищен"
    assert os.path.exists(good) and os.path.exists(good + "c"), \
        "здоровый ob_*.rpy/.rpyc удалён зря"
    assert stats["removed_orphans"] == 4, stats
print("   OK")

print("2d4) Ren'Py: одинаковые old из разных скриптов пишутся один раз...")
with tempfile.TemporaryDirectory() as td:
    make_renpy(td)
    os.makedirs(os.path.join(td, "game", "tl"))
    for e in renpy.extract(td):
        e.translation = "TR:" + e.original
    entries = [TranslationEntry(1, "game/script.rpy", "", "",
                                "Общая реплика.", "TR:Общая реплика.",
                                "translated"),
               TranslationEntry(2, "game/other.rpy", "", "",
                                "Общая реплика.", "TR:Общая реплика.",
                                "translated"),
               TranslationEntry(3, "game/other.rpy", "", "",
                                "Уникальная реплика.",
                                "TR:Уникальная реплика.", "translated")]
    stats = renpy.apply(td, entries, "ru")
    tl_dir = stats["out_dir"]
    c1 = open(os.path.join(tl_dir, "ob_game__script.rpy"),
              encoding="utf-8").read()
    c2 = open(os.path.join(tl_dir, "ob_game__other.rpy"),
              encoding="utf-8").read()
    assert c1.count('old "Общая реплика."') == 1, c1
    assert 'old "Общая реплика."' not in c2, c2
    assert c2.count('old "Уникальная реплика."') == 1, c2
    assert stats["dup_skipped"] == 1, stats
print("   OK")
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

# ── Ren'Py: скомпилированные .rpyc и .rpa ──

# Стабы renpy.ast/renpy.astsupport/renpy.sl2.slast — имитируют классы,
# которыми Ren'Py пикалит скрипты в .rpyc (СВЕРЕНЫ с renpy/ast.py,
# renpy/sl2/slast.py и launcher/game/archiver.rpy из Ren'Py 8.2.3).
_RENPY_AST_STUB = '''
class Node(object):
    pass

class Say(Node):
    pass

class Menu(Node):
    pass

class Define(Node):
    pass

class Python(Node):
    pass

class Default(Node):
    pass

class Screen(Node):
    pass

class PyCode(object):
    def __getstate__(self):
        return (1, self.source, self.location, self.mode, self.py)
    def __setstate__(self, state):
        if len(state) == 4:
            (_, self.source, self.location, self.mode) = state
            self.py = 2
        else:
            (_, self.source, self.location, self.mode, self.py) = state
        self.bytecode = None

class PyExpr(str):
    """Ren'Py 7.4+/8.x: PyExpr — str-подкласс, значение == python-код."""
    __slots__ = ["filename", "linenumber", "py"]
    def __new__(cls, s, filename="<none>", linenumber=1, py=3):
        self = str.__new__(cls, s)
        self.filename = filename
        self.linenumber = linenumber
        self.py = py
        return self
'''

_RENPY_ASTSUPPORT_STUB = '''
class PyExpr(str):
    """Ren'Py 8.x (astsupport.pyx): PyExpr — str-подкласс с __reduce__,
    возвращающим (PyExpr, (source, filename, linenumber, py, hashcode,
    column)) — исходник python-выражения первым аргументом."""
    __slots__ = ["filename", "linenumber", "py", "hashcode", "column"]
    def __new__(cls, source, filename="<none>", linenumber=1, py=3,
                hashcode=0, column=0):
        self = str.__new__(cls, source)
        self.filename = filename
        self.linenumber = linenumber
        self.py = py
        self.hashcode = hashcode
        self.column = column
        return self
    def __reduce__(self):
        return (PyExpr, (str(self), self.filename, self.linenumber,
                         self.py, self.hashcode, self.column))
'''

_RENPY_SLAST_STUB = '''
class SLNode(object):
    pass

class SLBlock(SLNode):
    pass

class SLScreen(SLBlock):
    pass

class SLDisplayable(SLBlock):
    pass

class SLIf(SLNode):
    pass

class SLFor(SLBlock):
    pass
'''

_RENPY_TEXT_STUB = '''
class Text(object):
    pass
'''

_RENPY_UI_STUB = '''
def _textbutton(*args, **kwargs):
    return None
'''


def make_renpy_stub(root: str) -> None:
    pkg = os.path.join(root, "renpy")
    os.makedirs(os.path.join(pkg, "sl2"), exist_ok=True)
    os.makedirs(os.path.join(pkg, "text"), exist_ok=True)
    with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(pkg, "ast.py"), "w", encoding="utf-8") as f:
        f.write(_RENPY_AST_STUB)
    with open(os.path.join(pkg, "astsupport.py"), "w", encoding="utf-8") as f:
        f.write(_RENPY_ASTSUPPORT_STUB)
    with open(os.path.join(pkg, "sl2", "__init__.py"), "w",
              encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(pkg, "sl2", "slast.py"), "w",
              encoding="utf-8") as f:
        f.write(_RENPY_SLAST_STUB)
    with open(os.path.join(pkg, "text", "__init__.py"), "w",
              encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(pkg, "text", "text.py"), "w",
              encoding="utf-8") as f:
        f.write(_RENPY_TEXT_STUB)
    with open(os.path.join(pkg, "ui.py"), "w", encoding="utf-8") as f:
        f.write(_RENPY_UI_STUB)


def build_rpyc_stmts():
    """Скрипт как после парсинга Ren'Py 8.x: Say/Menu/Define с
    интерполированными списками (PyExpr — str-подкласс) и экран SL2
    с text/textbutton."""
    import importlib
    import pickle
    import sys

    stub_dir = os.path.join(tempfile.gettempdir(), "ob_renpy_stub_tests")
    make_renpy_stub(stub_dir)
    if stub_dir not in sys.path:
        sys.path.insert(0, stub_dir)
    importlib.import_module("renpy.ast")
    importlib.import_module("renpy.astsupport")
    importlib.import_module("renpy.sl2.slast")
    importlib.import_module("renpy.text.text")
    importlib.import_module("renpy.ui")
    from renpy.ast import Define, Menu, PyCode, PyExpr, Say, Screen
    from renpy.astsupport import PyExpr as AstPyExpr
    from renpy.sl2.slast import SLDisplayable, SLScreen
    from renpy.text.text import Text
    from renpy.ui import _textbutton

    def make_say(what, who=None):
        s = Say()
        s.what = what
        s.who = who
        s.rollback = "normal"
        s.interact = True
        return s

    def make_text_disp(source):
        d = SLDisplayable()
        d.displayable = Text
        d.positional = [PyExpr(source, "script.rpy", 10)]
        d.children = []
        return d

    stmts = [
        make_say("Привет, я ведьма.", who="Айра"),
        make_say(["Часть ", PyExpr("player.name", "script.rpy", 3),
                  " конец"]),
    ]
    m = Menu()
    m.items = [(["Идти ", PyExpr("x", "script.rpy", 6), " дальше"], None,
                [make_say("внутри")]),
               ("Второй выбор", None, [])]
    stmts.append(m)
    stmts += [
        make_say("Строка без интерполяции"),
        make_say(["Строка с ", PyExpr("menu_music['title']", "script.rpy", 9),
                  " вставкой"]),
    ]
    # screen main_menu:
    #     text "Играть"
    #     textbutton "Параметры" action Return()
    #     text "Счёт: [score]"
    scr = Screen()
    slscreen = SLScreen()
    slscreen.children = [
        make_text_disp('"Играть"'),
        make_text_disp('_("Загрузить")'),
        make_text_disp('"Счёт: [score]"'),
    ]
    tb = SLDisplayable()
    tb.displayable = _textbutton
    # реальные Ren'Py 8.x хранят позиционные аргументы как
    # renpy.astsupport.PyExpr (6-аргументный __reduce__)
    tb.positional = [AstPyExpr('"Параметры"', "script.rpy", 12, 3, 0, 0)]
    tb.children = []
    slscreen.children.append(tb)
    scr.screen = slscreen
    stmts.append(scr)
    define = Define()
    code = PyCode()
    code.source = 'define e = Character("Айра")'
    code.location = ("script.rpy", 1)
    code.mode = "exec"
    code.py = 3
    define.code = code
    define.varname = "e"
    stmts.append(define)
    return pickle.dumps(({"_ob": True}, stmts), protocol=2)


def build_rpc2_rpyc(payload: bytes) -> bytes:
    """RPC2-упаковка как в Script.write_rpyc (renpy/script.py 8.2.3):
    заголовок + 3 нулевые записи, данные в конец, запись слота 1 — на
    свою позицию."""
    import struct
    import zlib
    data = zlib.compress(payload, 3)
    buf = io.BytesIO()
    buf.write(b"RENPY RPC2")
    for _i in range(3):
        buf.write(struct.pack("III", 0, 0, 0))
    start = buf.tell()
    buf.write(data)
    buf.seek(len(b"RENPY RPC2") + 12 * (1 - 1))
    buf.write(struct.pack("III", 1, start, len(data)))
    return buf.getvalue()


def check_rpyc_texts(texts: list[str]) -> None:
    assert "Привет, я ведьма." in texts, texts
    assert "Часть " in texts and " конец" in texts, texts
    assert "Идти " in texts and " дальше" in texts, texts
    assert "Второй выбор" in texts, texts
    assert "внутри" in texts, texts
    assert "Строка с " in texts and " вставкой" in texts, texts
    assert "Айра" in texts, texts
    # экранные тексты SL2 (text/textbutton) извлекаются
    assert "Играть" in texts and "Загрузить" in texts, texts
    assert "Параметры" in texts, texts
    assert "Счёт: [score]" in texts, texts
    # вставки переменных (PyExpr) НЕ считаются текстом
    assert not any(t in ("player.name", "x", "menu_music['title']")
                   for t in texts), texts
    assert len(texts) == 15, texts


print("2l) Ren'Py: python-код в .rpy — тексты квестов, промпты, уведомления, f-строки...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    script = (
        'define quest_desc = "Найди меч в пещере"\n'
        'default gold_text = "Золото: {gold}"\n'
        'init python:\n'
        '    quests = {\n'
        '        "q1": "Победи дракона",\n'
        '        "quest_1": "Спаси принцессу из башни",\n'
        '    }\n'
        '    renpy.notify("Квест принят")\n'
        '    name = renpy.input("Как тебя зовут?")\n'
        '    hp_text = f"HP: {hp}"\n'
        '    logo = "images/logo.png"\n'
        '    url = "https://example.com"\n'
        '    color = "#ff8800"\n'
        '    count = 42\n'
        '    def helper():\n'
        '        """Секретный докстринг разработчика"""\n'
        '        return None\n'
        '$ renpy.notify("Выбор сделан")\n'
    )
    with open(os.path.join(td, "game", "script.rpy"), "w",
              encoding="utf-8") as f:
        f.write(script)
    extracted = renpy.extract(td)
    texts = [e.original for e in extracted]
    for want in ("Найди меч в пещере", "Золото: {gold}",
                 "Победи дракона", "Спаси принцессу из башни",
                 "Квест принят", "Как тебя зовут?", "HP: {hp}",
                 "Выбор сделан"):
        assert want in texts, (want, texts)
    for bad in ("q1", "quest_1", "images/logo.png", "https://example.com",
                "#ff8800", "42", "gold_text",
                "Секретный докстринг разработчика"):
        assert bad not in texts, (bad, texts)
    # подсказки-контекст: видно, что это за строка
    ctx = {e.original: e.context for e in extracted}
    assert "quest_desc" in ctx["Найди меч в пещере"], ctx["Найди меч в пещере"]
    assert "key=q1" in ctx["Победи дракона"], ctx["Победи дракона"]
    assert "key=quest_1" in ctx["Спаси принцессу из башни"], \
        ctx["Спаси принцессу из башни"]
    assert "renpy.notify" in ctx["Выбор сделан"], ctx["Выбор сделан"]
    assert "gold_text" in ctx["Золото: {gold}"], ctx["Золото: {gold}"]
print("   OK")

print("2m) Ren'Py: python-узлы в .rpyc (Python/Default) извлекаются...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    import importlib as _importlib
    import sys as _sys
    stub_dir = os.path.join(tempfile.gettempdir(), "ob_renpy_stub_2m")
    make_renpy_stub(stub_dir)
    if stub_dir not in _sys.path:
        _sys.path.insert(0, stub_dir)
    _importlib.import_module("renpy.ast")
    from renpy.ast import Default, PyCode, PyExpr, Python

    def build_py_rpyc():
        import pickle as _pickle
        py = Python()
        code = PyCode()
        code.source = ('quests = {\n'
                       '    "q1": "Победи дракона",\n'
                       '}\n'
                       'def helper():\n'
                       '    """Служебный докстринг"""\n'
                       '    return None\n'
                       'renpy.notify("Квест принят")')
        code.location = ("script.rpy", 1)
        code.mode = "exec"
        code.py = 3
        py.code = code
        d = Default()
        d.value = PyExpr('"Найди меч"', "script.rpy", 2)
        return _pickle.dumps(({"_ob": True}, [py, d]), protocol=2)

    with open(os.path.join(td, "game", "script.rpyc"), "wb") as f:
        f.write(build_rpc2_rpyc(build_py_rpyc()))
    extracted = renpy.extract(td)
    texts = [e.original for e in extracted]
    for want in ("Победи дракона", "Квест принят", "Найди меч"):
        assert want in texts, (want, texts)
    assert "q1" not in texts, texts
    assert "Служебный докстринг" not in texts, texts
    ctx = {e.original: e.context for e in extracted}
    assert "key=q1" in ctx["Победи дракона"], ctx["Победи дракона"]
print("   OK")


print("2e) Ren'Py: legacy .rpyc (Ren'Py < 7.1: zlib(pickle) без RPC2)...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    with open(os.path.join(td, "game", "script.rpyc"), "wb") as f:
        f.write(zlib.compress(build_rpyc_stmts()))
    assert renpy.detect(td)
    check_rpyc_texts([e.original for e in renpy.extract(td)])
print("   OK")

print("2f) Ren'Py: RPC2 .rpyc (Ren'Py 7.1+/8.x)...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    with open(os.path.join(td, "game", "script.rpyc"), "wb") as f:
        f.write(build_rpc2_rpyc(build_rpyc_stmts()))
    assert renpy.detect(td)
    check_rpyc_texts([e.original for e in renpy.extract(td)])
print("   OK")

print("2g) Ren'Py: .rpyc внутри .rpa (v3.0)...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    blob = build_rpc2_rpyc(build_rpyc_stmts())
    key = random.getrandbits(32)
    path = os.path.join(td, "game", "archive.rpa")
    with open(path, "wb") as f:
        f.write(b"RPA-3.0 XXXXXXXXXXXXXXXX XXXXXXXX\n")
        offset = f.tell()
        f.write(blob)
        index = {"script.rpyc": [(offset ^ key, len(blob) ^ key, b"")]}
        indexoff = f.tell()
        f.write(zlib.compress(pickle.dumps(index, pickle.HIGHEST_PROTOCOL)))
        f.seek(0)
        f.write(b"RPA-3.0 %016x %08x\n" % (indexoff, key))
    assert renpy.detect(td)
    texts = [e.original for e in renpy.extract(td)]
    check_rpyc_texts(texts)
    # .rpyc из архива не ломается, если на диске есть ещё и .rpy
    with open(os.path.join(td, "game", "extra.rpy"), "w",
              encoding="utf-8") as f:
        f.write('define e = Character("Айра")\n'
                'label start:\n'
                '    e "Из .rpy"\n')
    texts = [e.original for e in renpy.extract(td)]
    assert "Из .rpy" in texts and "Привет, я ведьма." in texts, texts
print("   OK")

print("2h) Ren'Py: детект по .rpyc/.rpa без .rpy...")
from app.engines.renpy import RenPyModule

with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    with open(os.path.join(td, "game", "script.rpyc"), "wb") as f:
        f.write(build_rpc2_rpyc(build_rpyc_stmts()))
    assert renpy.detect(td)
    assert RenPyModule.detect(td) == 75
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    with open(os.path.join(td, "game", "archive.rpa"), "wb") as f:
        f.write(b"RPA-3.0 XXXXXXXXXXXXXXXX XXXXXXXX\n")
    assert renpy.detect(td)
    assert RenPyModule.detect(td) == 70
print("   OK")

print("2i) Ren'Py: .rpa v2 (RPA-2.0 hex, Ren'Py 6.99-7.3) и v1 (zlib, Ren'Py 6.x)...")
from app.core.renpy import rpa as rpa_mod

blob = build_rpc2_rpyc(build_rpyc_stmts())

# v2: 'RPA-2.0 ' + offset(16 hex), индекс zlib(pickle) без XOR
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    path = os.path.join(td, "game", "archive.rpa")
    index = {"script.rpyc": [(len(b"RPA-2.0 XXXXXXXXXXXXXXXX\n"),
                              len(blob))]}
    idx_blob = zlib.compress(pickle.dumps(index, pickle.HIGHEST_PROTOCOL))
    with open(path, "wb") as f:
        f.write(b"RPA-2.0 " + b"X" * 16 + b"\n")
        data_start = f.tell()
        f.write(blob)
        indexoff = f.tell()
        f.write(idx_blob)
        f.seek(0)
        f.write(b"RPA-2.0 %016x\n" % indexoff)
    arc = rpa_mod.RpaArchive(path)
    assert arc.version == 2, arc.version
    assert arc.read("script.rpyc") == blob
    texts = [e.original for e in renpy.extract(td)]
    assert "Привет, я ведьма." in texts and "Играть" in texts, texts

# v1: 'zlib(pickle индекса) + данные' — индексовые оффсеты указывают
# внутрь файла за пределы сжатого индекса; zlib.decompress игнорирует
# хвост (Ren'Py 6.x). Размер сжатого индекса стабилен для малых int
# (BININT фиксирован), поэтому offset считаем за 2 прохода.
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    path = os.path.join(td, "game", "archive.rpa")
    proto = pickle.HIGHEST_PROTOCOL
    c0 = zlib.compress(pickle.dumps({"script.rpyc": [(0, len(blob))]}, proto))
    data_off = len(c0)
    c1 = zlib.compress(pickle.dumps({"script.rpyc": [(data_off, len(blob))]}, proto))
    assert len(c1) == len(c0)
    with open(path, "wb") as f:
        f.write(c1)
        f.write(blob)
    arc = rpa_mod.RpaArchive(path)
    assert arc.version == 1, arc.version
    assert arc.read("script.rpyc") == blob
print("   OK")

print("2j) Ren'Py: гибрид — один проход берёт текст изо всех источников...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    # .rpy на диске
    with open(os.path.join(td, "game", "script.rpy"), "w",
              encoding="utf-8") as f:
        f.write('define e = Character("Айра")\nlabel start:\n'
                '    e "Диалог из .rpy"\n')
    # .rpyc RPC2 с интерполяцией и экраном
    with open(os.path.join(td, "game", "script.rpyc"), "wb") as f:
        f.write(build_rpc2_rpyc(build_rpyc_stmts()))
    # .rpa v3.0 с ещё одним .rpyc
    blob2 = build_rpc2_rpyc(build_rpyc_stmts())
    key = random.getrandbits(32)
    path = os.path.join(td, "game", "archive.rpa")
    with open(path, "wb") as f:
        f.write(b"RPA-3.0 XXXXXXXXXXXXXXXX XXXXXXXX\n")
        offset = f.tell()
        f.write(blob2)
        index = {"script.rpyc": [(offset ^ key, len(blob2) ^ key, b"")]}
        indexoff = f.tell()
        f.write(zlib.compress(pickle.dumps(index, pickle.HIGHEST_PROTOCOL)))
        f.seek(0)
        f.write(b"RPA-3.0 %016x %08x\n" % (indexoff, key))
    texts = [e.original for e in renpy.extract(td)]
    assert "Диалог из .rpy" in texts
    assert "Привет, я ведьма." in texts
    assert "Играть" in texts and "Параметры" in texts
    # каждый исходник отдан ровно один раз (дедупликация по original)
    assert texts.count("Привет, я ведьма.") == 1, texts
    entries = renpy.extract(td)
    for e in entries:
        e.translation = "TR:" + e.original
    stats = renpy.apply(td, entries, "ru")
    assert os.path.isdir(stats["out_dir"])
print("   OK")

print("2k) Ren'Py: dual-dialect агент — ветки py2 (Ren'Py 7) и py3 (Ren'Py 8)...")
from app.engines.renpy.agent import agent_rpy_source, agent_source
from app.engines.renpy.offsets import RenpyOffsetDB

db = RenpyOffsetDB()
assert db.get_abi_branch("7.4.11") == "py2", db.get_abi_branch("7.4.11")
assert db.get_abi_branch("8.2.3") == "py3"
assert db.get_abi_branch("6.18.3") is None  # не 7.x/8.x → ветки нет
# известные версии из БД дают офсеты; все записи помечены веткой
known = db._data.get("versions", {})
assert known, "renpy_offsets.json пуст"
for _v, _d in known.items():
    assert _d.get("abi") in ("py2", "py3")
    assert isinstance(_d.get("symbols"), dict)
    # офсеты PyRun/GIL могут быть не заполнены (столбец-заглушка) —
    # тогда get_offsets честно отдаёт None, а не мусор
    if any(s is None for s in _d["symbols"].values()):
        assert db.get_offsets(_v) is None
    else:
        assert db.get_offsets(_v) is not None
# генерация обеих веток: чужие ABI-секции вырезаны, маркеры не остаются
s2 = agent_source(1234, abi="py2")
s3 = agent_source(1234, abi="py3")
assert "@@ABI" not in s2 and "@@ABI" not in s3
py2mark = 'if isinstance(_d, type(u"")):'
py3mark = 'return json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\\n"'
assert py2mark in s2 and py2mark not in s3
assert py3mark in s3 and py3mark not in s2
# обе ветки компилируются под CPython (синтаксически валидны)
compile(s2, "agent_py2.py", "exec")
compile(s3, "agent_py3.py", "exec")
# .rpy-обёртка: init python + отступ, маркеров нет
r = agent_rpy_source(1234, abi="py3")
assert r.startswith("init python:") and "\n    " in r
assert "@@ABI" not in r
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
    # лежат на одной строке (seg[0] и seg[2]). Строка-продолжение
    # многострочного сеттера ('to true] ]') — код, не извлекается —
    # 19 записей = 14 строк
    assert stats["strings"] == 14, stats
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
    assert stats["strings"] == 14, stats
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
    assert stats["strings"] == 13, stats
    # длинный макрос <<= either(…)>> (>200 символов): строковые аргументы
    # (варианты фраз) — видимый текст для игрока, теперь переводятся
    # по-аргументно; структура макроса (either('…', '…')) остаётся целой
    either_e = next(e for e in entries
                    if e.original == "Talk with her:")
    either_e.translation = "RU:" + either_e.original
    shutil.copy2(stats["backups"][0], story)
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    import html as html_mod
    assert "<<= either('RU:Option number one: very long text" \
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

print("4c) Twine: кнопки — ключи (имена пассажей, $переменные, селекторы) не переводятся...")
STORY_BTNS = """<!DOCTYPE html>
<html><head><title>Btns</title></head>
<body><tw-storydata name="Btns" startnode="1" creator="Twine"
  creator-version="2.3.9" format="SugarCube" format-version="2.36.1"
  hidestoryicons=""><tw-passagedata pid="1" name="Start" tags="">Shop:
<<link "Open door" "DoorPassage">>
<<button "Buy sword">>
<<goto "Start">>
<<radio "Choose" "$choice">>
<<select "Which?" "$answer">>
<<textbox "Your name" "$name">>
<<linkappend "More" "MorePassage">>
<<addclass "#dialog">>
<<option "Pick" "PickPassage">>
<<prompt "Ask" "$answer" "no">>
[[Enter the cave|cave2]]
</tw-passagedata></tw-storydata></body></html>
"""
with tempfile.TemporaryDirectory() as td:
    story = os.path.join(td, "index.html")
    with open(story, "w", encoding="utf-8") as f:
        f.write(STORY_BTNS)
    entries = twine.extract(story)
    originals = [e.original for e in entries]
    # тексты кнопок/полей извлекаются
    for o in ("Shop:", "Open door", "Buy sword", "Choose", "Which?",
              "Your name", "More", "Pick", "Ask", "Enter the cave"):
        assert o in originals, (o, originals)
    # ключи — никогда (перевод ключа убивает кнопку/ссылку/картинку)
    for bad in ("DoorPassage", "Start", "$choice", "$answer", "$name",
                "MorePassage", "#dialog", "PickPassage", "no", "cave2"):
        assert not any(bad in o for o in originals), bad
    for e in entries:
        e.translation = "RU:" + e.original
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    assert '&lt;&lt;link "RU:Open door" "DoorPassage"&gt;&gt;' in text, text
    assert '<<goto "Start">>' in text, text
    assert '&lt;&lt;radio "RU:Choose" "$choice"&gt;&gt;' in text, text
    assert '&lt;&lt;prompt "RU:Ask" "$answer" "no"&gt;&gt;' in text, text
    assert '<<addclass "#dialog">>' in text, text
    assert "[[RU:Enter the cave|cave2]]" in text, text
    assert stats["strings"] == 10, stats
    # Саботаж: записи, указывающие на ключи/селекторы или с ломающими
    # символами (кавычка, |) — не внедряются вообще
    shutil.copy2(stats["backups"][0], story)
    for e in entries:
        if e.original == "Enter the cave":
            e.translation = "RU:Enter|cave"  # | сломает ссылку
        else:
            e.translation = "RU:" + e.original
    crafted = [
        TranslationEntry(0, "", "passage[1].line[3].seg[0].arg[0]", "",
                         "Start", 'RU:"Старт'),
        TranslationEntry(0, "", "passage[1].line[8].seg[0].arg[0]", "",
                         "#dialog", "Диалог"),
    ]
    stats = twine.apply(td, entries + crafted)
    text = open(story, encoding="utf-8").read()
    assert 'RU:"Старт' not in text, text
    assert "Диалог" not in text, text
    assert "[[Enter the cave|cave2]]" in text, text   # | — не внедрён
    assert '<<goto "Start">>' in text, text
    assert '<<addclass "#dialog">>' in text, text
    assert stats["strings"] == 9, stats   # 10 линий − подпись с |
print("   OK")

print("4d) Twine: Harlowe — (имя:) и [подпись->таргет] не переводятся...")
STORY_HARLOWE = """<!DOCTYPE html>
<html><head><title>H</title></head>
<body><tw-storydata name="H" startnode="1" creator="Twine"
  creator-version="2.9.2" format="Harlowe" format-version="3.3.9"
  hidestoryicons=""><tw-passagedata pid="1" name="Start" tags="">You see a cat.
Open (link: "the door")[(goto: "Door")].
Here is (image: "photo.png").
(if: $x > 3)[Too many.]
[go home->Home]
(link-goto: "Run", "Forest")
(display: "Intro")
</tw-passagedata></tw-storydata></body></html>
"""
with tempfile.TemporaryDirectory() as td:
    story = os.path.join(td, "index.html")
    with open(story, "w", encoding="utf-8") as f:
        f.write(STORY_HARLOWE)
    entries = twine.extract(story)
    originals = [e.original for e in entries]
    assert "You see a cat." in originals, originals
    assert "Here is" in originals, originals
    assert "[Too many.]" in originals, originals   # текст хука переводится
    for bad in ("the door", "Door", "photo", "go home", "Home", "Run",
                "Forest", "Intro", "("):
        assert not any(bad in o for o in originals), bad
    assert not any("->" in o for o in originals)
    for e in entries:
        e.translation = "RU:" + e.original
    stats = twine.apply(td, entries)
    text = open(story, encoding="utf-8").read()
    assert 'RU:Open (link: "the door")[(goto: "Door")].' in text, text
    assert '(image: "photo.png")' in text, text
    assert "[go home->Home]" in text, text
    assert '(link-goto: "Run", "Forest")' in text, text
    assert '(display: "Intro")' in text, text
    assert "(if: $x &gt; 3)RU:[Too many.]" in text, text
    assert "RU:You see a cat." in text, text
    assert stats["strings"] == 4, stats
    # legacy-запись из старого проекта (целая строка с картинкой):
    # макрос в переводе не совпадает с маской — не внедряется
    shutil.copy2(stats["backups"][0], story)
    legacy = TranslationEntry(
        0, "", "passage[1].line[2]", "", 'Here is (image: "photo.png").',
        "Вот (изображение: «фото.png»).")
    stats = twine.apply(td, [legacy])
    text = open(story, encoding="utf-8").read()
    assert "изображение" not in text, text
    assert stats["strings"] == 0, stats
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

print("6) Twine: единый WS-пэйлоад — мост состояния/читов/сейвов...")
from app.core.models import Project, project_file_for
from app.engines.twine.tentacle import PAYLOAD_SCRIPT, build_tr_dict, load_tr_dict

# Единый пэйлоад моста (браузер и webapp-окно): состояние/переменные,
# читы, бэкап/восстановление сейвов. Перевод игры делается в приложении
# (извлечение -> перевод -> новая html-копия), в веб-странице его нет.
assert "{TR_DICT}" not in PAYLOAD_SCRIPT
assert "{WS_URL}" in PAYLOAD_SCRIPT
for marker in ("collectState", "save_backup", "save_restore",
               "octopus-wrapper"):
    assert marker in PAYLOAD_SCRIPT, marker
for marker in ("_trLT", "_trMM", "trApply", "octopus-tr-bar"):
    assert marker not in PAYLOAD_SCRIPT, marker
es = [
    TranslationEntry(0, "", "", "", "Open door", "Открыть дверь"),
    TranslationEntry(0, "", "", "", "Skip me", "", "skip"),
    TranslationEntry(0, "", "", "", "Empty tr", "   "),
    TranslationEntry(0, "", "", "", "No tr", ""),
]
d = build_tr_dict(es)
assert d == {"Open door": "Открыть дверь"}, d
assert build_tr_dict([]) == {}
with tempfile.TemporaryDirectory() as td:
    game = os.path.join(td, "game")
    os.makedirs(game)
    proj = Project(game_dir=game, engine="twine", entries=es)
    projects_root = os.path.join(td, "projects")
    os.makedirs(projects_root)
    pf = project_file_for(game, projects_root=projects_root)
    assert pf.startswith(projects_root) and pf.endswith(".ob.json"), pf
    with open(pf, "w", encoding="utf-8") as f:
        json.dump(proj.to_dict(), f, ensure_ascii=False)
    assert load_tr_dict(game, projects_root=projects_root) == \
        {"Open door": "Открыть дверь"}
    assert load_tr_dict(os.path.join(td, "no_game"),
                        projects_root=projects_root) == {}
print("   OK")

print("7) Twine: человекочитаемый текст игры (код свёрнут в маркеры)...")
from app.core.twine.parser import format_passages, read_passages
with tempfile.TemporaryDirectory() as td:
    make_twine(td)
    passages = read_passages(td)
    # служебные пассажи (widget/StoryInit/init) пропущены
    names = [p.name for p in passages]
    assert "Start" in names and "forest2" in names and "WikiForms" in names
    assert "GameTime" not in names and "StoryInit" not in names
    assert "CodePass" not in names
    start = [p for p in passages if p.name == "Start"][0]
    assert "You wake up in a forest." in start.text
    # макросы/переменные/скрипты свёрнуты в маркеры, текста кода нет
    assert "<<set" not in start.text and "<<$item_name>>" not in start.text
    assert "window.CLOCK" not in start.text
    assert "⟦макрос" in start.text and "⟦$gold⟧" in start.text
    assert "⟦скрипт: 3 строк" in start.text
    # подписи ссылок видны, таргеты скрыты
    wf = [p for p in passages if p.name == "WikiForms"][0]
    assert "⟦ссылка: Go home⟧" in wf.text
    assert "⟦картинка⟧" in wf.text
    assert "$bought to" not in wf.text.replace("⟦", "")  # сеттер скрыт
    # человекочитаемая разметка: заголовки пассажей
    out = format_passages(passages)
    assert "ПАССАЖ «Start» (pid 1)" in out
    assert out.index("ПАССАЖ «Start»") < out.index("ПАССАЖ «forest2»")
    print("   OK:", len(passages), "пассажей,", len(out), "символов")

print("8) Twine: JSON-промежуток и перевод в НОВУЮ html-копию...")
import json as _json
from app.engines.twine import TwineModule
from app.core.twine.parser import story_to_json, write_story_json
with tempfile.TemporaryDirectory() as td:
    make_twine(td)
    module = TwineModule(td)
    # TwineModule.extract дополнительно пишет «игра.json» рядом с игрой
    es = module.extract(td)
    story = os.path.join(td, "index.html")
    jp = os.path.join(td, "index.json")
    assert os.path.isfile(jp), "extract должен писать JSON рядом с игрой"
    doc = story_to_json(td)
    assert doc["game"] == "index.html" and doc["format"] == "SugarCube"
    names = [p["name"] for p in doc["passages"]]
    assert names[0] == "Start" and "forest2" in names and "WikiForms" in names
    assert "GameTime" not in names and "StoryInit" not in names
    start = doc["passages"][0]
    seg0 = start["segments"][0]
    assert seg0["type"] == "text"
    assert seg0["translatable"] == ["You wake up in a forest."]
    macro = [s for s in start["segments"] if s["line"] == 1][0]
    assert macro["type"] == "macro" and macro["translatable"] == []
    link = [s for s in start["segments"] if s["line"] == 2][0]
    assert link["type"] == "link" and link["translatable"] == ["Go deeper"]
    with open(jp, encoding="utf-8") as f:
        saved = _json.load(f)
    assert saved["passages"][0]["segments"][0]["translatable"] == \
        ["You wake up in a forest."]
    jp2 = write_story_json(td)
    assert jp2 == jp and os.path.isfile(jp2)
    # перевод в новую копию: оригинал не трогается
    originals = {e.original: e for e in es}
    for orig, trans in [("You wake up in a forest.", "Ты просыпаешься в лесу."),
                        ("Go deeper", "Идти глубже"),
                        ("starts now.", "начинается сейчас.")]:
        e = originals[orig]
        e.translation = trans
        e.status = "translated"
    with open(story, "rb") as f:
        original_bytes = f.read()
    stats = module.apply(td, es, target_lang="ru")
    assert stats["files"] == 1 and stats["strings"] == 3
    out = stats["out_file"]
    assert os.path.isfile(out) and out.endswith("index_ru.html")
    with open(story, "rb") as f:
        assert f.read() == original_bytes, "оригинал не должен меняться"
    with open(out, encoding="utf-8") as f:
        out_text = f.read()
    assert "Ты просыпаешься в лесу." in out_text
    assert "Идти глубже" in out_text
    assert "начинается сейчас." in out_text
    # код игры цел: макросы, ссылки с таргетами, картинки, скрипты
    assert "<<set $gold to 100>>" in out_text
    assert "[[Идти глубже|forest2]]" in out_text
    assert "[[Go home->Home]]" in out_text
    assert "[img[Go home|home.png][Home][$done to true]]" in out_text
    assert "<script" in out_text and "</script>" in out_text
    # кириллица не залезла внутрь макросов и тегов
    for m in re.findall(r"<<[^>]*>>", out_text):
        assert not re.search(r"[А-Яа-яЁё]", m), m
    for m in re.findall(r"<[^>]+>", out_text):
        assert "Ты" not in m and "Идти" not in m, m
    print("   OK: index_ru.html создан, оригинал цел,",
          stats["strings"], "строк")

print()
print("ВСЕ ТЕСТЫ RENPY + TWINE ПРОШЛИ")
