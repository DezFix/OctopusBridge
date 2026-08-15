# -*- coding: utf-8 -*-
"""Ren'Py и Twine: детект, извлечение, внедрение (tl/HTML), дедупликация,
патч шрифтов Ren'Py, LZ-сейвы Twine."""
import io
import os
import pickle
import random
import shutil
import sys
import tempfile
import zlib

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
    stats2 = renpy.apply(td, entries, "ru")
    assert not os.path.exists(stale), "осиротевший ob_*.rpy не удалён"
    assert stats2["removed_orphans"] == 1, stats2
    remaining = [f for f in os.listdir(tl_dir)
                 if f.startswith("ob_") and f.endswith(".rpy")]
    assert "ob_activate.rpy" in remaining and "ob_game__script.rpy" in remaining
    for f in remaining:
        content = open(os.path.join(tl_dir, f), encoding="utf-8").read()
        for line in content.splitlines():
            if 'old "' in line or 'new "' in line:
                assert line.rstrip().endswith('"'), \
                    f"строка old/new не однострочная в {f}: {line!r}"
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
class PyExpr(object):
    """Ren'Py 7.0-7.3: PyExpr — объект с атрибутом source."""
    __slots__ = ["source", "loc"]
    def __init__(self, source, loc=("<none>", 1)):
        self.source = source
        self.loc = loc
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
    import pickle
    import sys
    import importlib

    stub_dir = os.path.join(tempfile.gettempdir(), "ob_renpy_stub_tests")
    make_renpy_stub(stub_dir)
    if stub_dir not in sys.path:
        sys.path.insert(0, stub_dir)
    importlib.import_module("renpy.ast")
    importlib.import_module("renpy.astsupport")
    importlib.import_module("renpy.sl2.slast")
    importlib.import_module("renpy.text.text")
    importlib.import_module("renpy.ui")
    from renpy.ast import Say, Menu, Define, PyCode, Screen, PyExpr
    from renpy.sl2.slast import SLScreen, SLDisplayable
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
    tb.positional = [PyExpr('"Параметры"', "script.rpy", 12)]
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
from app.engines.renpy.agent import agent_source, agent_rpy_source
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
