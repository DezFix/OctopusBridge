# -*- coding: utf-8 -*-
"""Конформность Rust-порта `ob_renpy_rpyc` с `app/core/renpy/parser.py`.

Сверяет `extract_rpyc` (Rust, через `_ob_renpy_rpyc_py`) с эталоном
`_unpickle_rpyc` + `_walk_ast(labeled=True)` один в один: упорядоченные
тройки `(kind, text, label)`. Источники — только синтетика (игр у нас
нет): полные AST-формы, протоколы 0–4, legacy/RPC2-фрейминги,
рукописные опкоды, корпус python-исходников, генератор случайных AST
(200 шт.), враждебные входы (только отказ, без падений).

Расхождение = провал скрипта (код 1). Битый вход обязан дать ValueError
(Rust-`Err`), а не падение интерпретатора.
"""
import io
import os
import pickle
import random
import struct
import sys
import tempfile
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OBOB = os.path.dirname(os.path.dirname(HERE))
PYMOD = os.path.join(OBOB, "rust", "ob_renpy_rpyc_py")
sys.path.insert(0, PYMOD)    # _ob_renpy_rpyc_py.pyd + libunwind.dll
sys.path.insert(0, OBOB)     # app.*

import _ob_renpy_rpyc_py as rust
from app.core.renpy import parser as py

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20261014

N_COMPARE = 0
N_HOSTILE = 0


def py_extract(data: bytes):
    """Эталон: None (не разобралось) или список троек.

    Исключение наружу (struct.error на обрезанном RPC2-заголовке —
    `struct.unpack` в `_unpickle_rpyc` вне try) тоже означает «не
    разобралось»: вызывающий `extract()` в parser.py держит вызов в
    try/except и пропускает файл. Здесь — то же самое.
    """
    try:
        parsed = py._unpickle_rpyc(data)
    except Exception:
        return None
    if parsed is None:
        return None
    return py._walk_ast(parsed[1], labeled=True)


def check(data: bytes, tag: str):
    """Один вход: упорядоченные тройки обязаны совпасть; None == Err."""
    global N_COMPARE
    N_COMPARE += 1
    want = py_extract(data)
    try:
        got = [tuple(t) for t in rust.extract_rpyc(data)]
    except ValueError:
        got = None
    if want is None and got is None:
        return
    if want is None or got is None:
        print("РАСХОЖДЕНИЕ %s: python=%s rust=%s" % (
            tag,
            "None" if want is None else "%d троек" % len(want),
            "ValueError" if got is None else "%d троек" % len(got)))
        if want is not None:
            print("  python=%r" % (want[:8],))
        raise SystemExit(1)
    if got != want:
        print("РАСХОЖДЕНИЕ %s (%d vs %d):" % (tag, len(want), len(got)))
        for i, (w, g) in enumerate(zip(want, got)):
            if w != g:
                print("  первая разница #%d:\n    py=%r\n    rs=%r"
                      % (i, w, g))
                break
        if len(want) != len(got):
            print("  длины: %d vs %d" % (len(want), len(got)))
            only_w = [x for x in want if x not in got][:5]
            only_g = [x for x in got if x not in want][:5]
            print("  только py: %r" % (only_w,))
            print("  только rs: %r" % (only_g,))
        raise SystemExit(1)


def check_hostile(data: bytes, tag: str):
    """Враждебный вход: Rust обязан отказать (ValueError), не упасть."""
    global N_HOSTILE
    N_HOSTILE += 1
    try:
        got = rust.extract_rpyc(data)
    except ValueError:
        return
    print("FAIL hostile %s: принят (%d троек)" % (tag, len(got)))
    raise SystemExit(1)


def rpc2(payload: bytes, compress_level: int = 3) -> bytes:
    data = zlib.compress(payload, compress_level)
    buf = io.BytesIO()
    buf.write(b"RENPY RPC2")
    for _i in range(3):
        buf.write(struct.pack("III", 0, 0, 0))
    start = buf.tell()
    buf.write(data)
    buf.seek(len(b"RENPY RPC2"))
    buf.write(struct.pack("III", 1, start, len(data)))
    return buf.getvalue()


def legacy(payload: bytes) -> bytes:
    return zlib.compress(payload)


# ── стабы renpy-модулей (как в tests/test_renpy_twine.py) ──

AST_STUB = '''
class Node(object):
    pass

class Say(Node):
    pass

class TranslateSay(Node):
    pass

class Menu(Node):
    pass

class Label(Node):
    pass

class Define(Node):
    pass

class Default(Node):
    pass

class Python(Node):
    pass

class Screen(Node):
    pass

class Translate(Node):
    pass

class TranslateString(Node):
    pass

class TranslateBlock(Node):
    pass

class Show(Node):
    pass

class Scene(Node):
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
    __slots__ = ["filename", "linenumber", "py"]
    def __new__(cls, s, filename="<none>", linenumber=1, py=3):
        self = str.__new__(cls, s)
        self.filename = filename
        self.linenumber = linenumber
        self.py = py
        return self
'''

ASTSUPPORT_STUB = '''
class PyExpr(str):
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

SLAST_STUB = '''
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

class SLPython(SLNode):
    pass

class SLFor(SLBlock):
    pass
'''

REVERTABLE_STUB = '''
class RevertableDict(dict):
    pass
'''

PARAM_STUB = '''
class ArgumentInfo(object):
    pass
'''

PYTHON_STUB = '''
class RawCode(str):
    pass
'''


def make_stub(root: str) -> None:
    pkg = os.path.join(root, "renpy")
    os.makedirs(os.path.join(pkg, "sl2"), exist_ok=True)
    os.makedirs(os.path.join(pkg, "text"), exist_ok=True)
    open(os.path.join(pkg, "__init__.py"), "w").close()
    open(os.path.join(pkg, "ast.py"), "w").write(AST_STUB)
    open(os.path.join(pkg, "astsupport.py"), "w").write(ASTSUPPORT_STUB)
    open(os.path.join(pkg, "sl2", "__init__.py"), "w").close()
    open(os.path.join(pkg, "sl2", "slast.py"), "w").write(SLAST_STUB)
    open(os.path.join(pkg, "revertable.py"), "w").write(REVERTABLE_STUB)
    open(os.path.join(pkg, "parameter.py"), "w").write(PARAM_STUB)
    open(os.path.join(pkg, "python.py"), "w").write(PYTHON_STUB)
    open(os.path.join(pkg, "text", "__init__.py"), "w").close()
    open(os.path.join(pkg, "text", "text.py"), "w").write(
        "class Text(object):\n    pass\n")
    open(os.path.join(pkg, "ui.py"), "w").write(
        "def _textbutton(*args, **kwargs):\n    return None\n")


STUB_DIR = os.path.join(tempfile.gettempdir(), "ob_rpyc_conform_stub")
make_stub(STUB_DIR)
if STUB_DIR not in sys.path:
    sys.path.insert(0, STUB_DIR)
import importlib

for _m in ("renpy.ast", "renpy.astsupport", "renpy.sl2.slast",
           "renpy.revertable", "renpy.parameter", "renpy.python",
           "renpy.text.text", "renpy.ui"):
    try:
        importlib.import_module(_m)
    except ImportError:
        pass

from renpy.ast import (Default, Define, Label, Menu, PyCode, PyExpr, Python,
                       Say, Scene, Screen, Show, Translate, TranslateBlock,
                       TranslateSay, TranslateString)
from renpy.astsupport import PyExpr as AstPyExpr
from renpy.parameter import ArgumentInfo
from renpy.python import RawCode
from renpy.revertable import RevertableDict
from renpy.sl2.slast import (SLBlock, SLDisplayable, SLFor, SLIf, SLPython,
                             SLScreen)
from renpy.text.text import Text
from renpy.ui import _textbutton


def say(what, who=None):
    s = Say()
    s.what = what
    s.who = who
    return s


def lab(name, block):
    lb = Label()
    lb.name = name
    lb.block = block
    return lb


def pyc(src):
    c = PyCode()
    c.source = src
    c.location = ("script.rpy", 1)
    c.mode = "exec"
    c.py = 3
    return c


def disp(cls, positionals, children=None, **kw):
    d = SLDisplayable()
    d.displayable = cls
    d.positional = positionals
    d.children = children or []
    if kw:
        d.keyword = dict(kw)
    return d


def frame(payload: bytes, proto_note: str, tag: str):
    check(legacy(payload), "legacy/%s" % tag)
    check(rpc2(payload), "rpc2/%s" % tag)


# ── A. полные AST-формы ──

def corpus_full(plain_pyexpr=False):
    def px(s, filename="script.rpy", linenumber=1, py=3):
        # Протоколы 0/1 на Python 3.11+ не сериализуют str-подкласс со
        # __slots__ без __getstate__ (TypeError в copyreg._reduce_ex) —
        # такая комбинация (слоты-PyExpr в proto 0/1) в реальных .rpyc
        # и не встречается (слоты появились в Ren'Py 7.4+, пишущем
        # протоколом 2+). Для 0/1 берём голую строку: фрейминг и опкоды
        # 0/1-стиля (INST/OBJ/GLOBAL/STRING/UNICODE/LONG/INT) покрываются
        # тем же корпусом и рукописными опкодами секции C.
        # astsupport.PyExpr (с __reduce__) сериализуется всегда.
        if plain_pyexpr:
            return s
        return PyExpr(s, filename, linenumber, py)

    stmts = [
        say("Привет, я ведьма.", who="Айра"),
        say(["Часть ", px("player.name", "script.rpy", 3), " конец"]),
        say(["Только ", AstPyExpr("x", "script.rpy", 1, 3, 0, 0), " хвост"]),
        say(b"Hi bytes", who=b"Ann"),
        say("", who=""),
        say(["", " "]),
    ]
    ts = TranslateSay()
    ts.what = "Переводная реплика"
    ts.who = "Борис"
    stmts.append(ts)
    m = Menu()
    m.items = [(["Идти ", px("x", "script.rpy", 6), " дальше"], None,
                [say("внутри")]),
               ("Второй выбор", None, []),
               ("Я", None, []),
               ("?", None, []),
               ([], None, [])]
    m.caption = "Что делать?"
    m.prompt = "Выбирай уже"
    m.who = "Менюша"
    stmts.append(m)
    m2 = Menu()
    m2.items = [("Коротко", None)]
    stmts.append(m2)
    stmts.append(lab("start", [say("Первая", who="Гость"), say("Вторая")]))
    stmts.append(lab("next", [say("Третья")]))
    stmts.append(say("Вне метки"))
    tr = Translate()
    tr.block = [say("Внутри перевода")]
    stmts.append(tr)
    tss = TranslateString()
    tss.old = "Старая строка"
    stmts.append(tss)
    tse = TranslateString()
    tse.old = ""
    stmts.append(tse)
    tb = TranslateBlock()
    tb.block = [say("В блоке")]
    stmts.append(tb)
    for src in PY_SOURCES:
        d = Define()
        d.code = pyc(src)
        d.varname = "v"
        stmts.append(d)
    dd = Default()
    dd.value = px('"Найди меч"', "script.rpy", 2)
    stmts.append(dd)
    dd2 = Default()
    dd2.code = pyc('gold_text = "Золото: {gold}"')
    dd2.value = None
    stmts.append(dd2)
    pyn = Python()
    pyn.code = pyc('renpy.notify("Квест принят")')
    stmts.append(pyn)
    scr = Screen()
    sl = SLScreen()
    sl.children = [
        disp(Text, [px('"Играть"', "script.rpy", 10)]),
        disp(Text, [px('_("Загрузить")', "script.rpy", 11)]),
        disp(_textbutton,
             [AstPyExpr('"Параметры"', "script.rpy", 12, 3, 0, 0)]),
        disp(Text, [px('"Счёт: [score]"', "script.rpy", 13)],
             default=px('"Подсказка"', "script.rpy", 14)),
        disp(Text, [px('variable', "script.rpy", 15)]),
        disp(Text, ["plain text here"]),
        disp(Text, ["eileen"]),
        disp(Text, ["#ff8800"]),
        disp(Text, ["images/logo.png"]),
    ]
    import renpy.sl2.slast as _sl
    lbl_cls = type("Label", (), {})
    lbl_cls.__module__ = "renpy.sl2.slast"
    lbl_cls.__name__ = "Label"
    setattr(_sl, "Label", lbl_cls)
    sl.children.append(disp(lbl_cls, [px('"Метка экрана"', "s.rpy", 1)]))
    # не из белого списка — пропуск
    img_cls = type("Image", (), {})
    img_cls.__module__ = "renpy.sl2.slast"
    img_cls.__name__ = "Image"
    setattr(_sl, "Image", img_cls)
    sl.children.append(disp(img_cls, [px('"logo.png"', "s.rpy", 2)]))
    # ветка if
    sif = SLIf()
    sif.entries = [(px("cond", "s.rpy", 3),
                    [disp(Text, [px('"Ветка да"', "s.rpy", 4)])])]
    sl.children.append(sif)
    slp = SLPython()
    slp.code = pyc('screen_var = "Текст экрана из кода"')
    sl.children.append(slp)
    scr.screen = sl
    stmts.append(scr)
    sh = Show()
    sh.imspec = [px('"Глава из rpyc"', "s.rpy", 5)]
    stmts.append(sh)
    sh2 = Show()
    sh2.imspec = ["eileen"]
    stmts.append(sh2)
    sc = Scene()
    sc.text = "Сцена из rpyc"
    stmts.append(sc)
    sc2 = Scene()
    sc2.what = "eileen"
    stmts.append(sc2)
    # RevertableDict в keyword
    rd = RevertableDict({"default": px('"Из словаря"', "s.rpy", 6)})
    rd.attr = "x"
    dkw = disp(Text, [px('"Кнопка" ', "s.rpy", 7)])
    dkw.keywords = rd
    sl.children.append(dkw)
    # ArgumentInfo где-то в дереве
    ai = ArgumentInfo()
    ai.children = [say("После аргумента")]
    stmts.append(ai)
    # RawCode-строка в what (флаг кода — пропуск)
    rc = RawCode("player.name")
    stmts.append(say(["До ", rc, " после"]))
    # Множество и bytearray в невидимых обходу атрибутах: pickler пишет
    # их через REDUCE builtins (на всех протоколах), обход игнорирует.
    # Файл обязан РАЗОБРАТЬСЯ, а не уйти в отказ целиком.
    s_set = Say()
    s_set.what = "После множества"
    s_set.tags = {1, 2}
    s_set.frozen = frozenset(["a"])
    stmts.append(s_set)
    s_ba = Say()
    s_ba.what = "После байтмассива"
    s_ba.blob = bytearray(b"hi")
    stmts.append(s_ba)
    return stmts


PY_SOURCES = [
    'define e = Character("Айра")',
    'quests = {\n    "q1": "Победи дракона",\n}\n'
    'def helper():\n    """Служебный докстринг"""\n    return None\n'
    'renpy.notify("Квест принят")',
    'title_text = "Заголовок"',
    'hp_text = f"HP: {hp}"',
    'items = ["Меч", "Щит"]',
    'name = renpy.input("Как тебя зовут?")',
    'if flag:\n    show_text = "Показать текст"',
    'for i in range(3):\n    t = "Итерация"',
    'x = "a" "b"',
    'd = {"a": "Яблоко", "b": "Банан"}',
    'logo = "images/logo.png"',
    'url = "https://example.com"',
    'color = "#ff8800"',
    'q = cond and "Да" or "Нет"',
    't = "Да" if flag else "Нет"',
    's = "%s очков" % score',
    'm = "Привет, {}".format(username)',
    'c = [str(x) for x in items]',
    'g = {"k": v for k, v in pairs}',
    'f = lambda x="Умолчание": x',
    'assert ok, "Проверка провалена"',
    'with open("f.txt") as fh:\n    data = "Данные"',
    'try:\n    risky()\nexcept ValueError:\n    msg = "Ошибка значения"',
    'x: str = "Аннотация"',
    'y += "Добавка"',
    'a = b = "Двойное"',
    'z = (lambda n="Вложенная": n)("arg")',
    'w = textwrap.dedent("""Много\nстрок\nтекста""")',
    'raw = r"C:\\путь\\файл"',
    'u = "Юникод: \\u00e9"',
    'lst = ["первый", ("второй", {"третий": "глубоко"})]',
    'sub = items[0]',
    'attr = obj.поле',
    'cmp = a < b',
    'un = not flag',
    'neg = -num',
    'yn = yield "Значение"',
    'deco = "после декоратора"',
    'ret = "готово"; second = "второе"',
    'one_line = "один" if True else "два"',
    'while flag:\n    wmsg = "Цикл"',
    'match x:\n    case 1:\n        q = "один"',
    'match x:\n    case {"a": p}:\n        q = "тело"',
    's = f"Счёт: {v}"',
    'счёт = f"итого {v}"',
    'x = f"é{v}"',
    'префикс = 1\ns = f"Счёт: {v}"',
    'h = {k: "значение" for k in ks}',
    'print("питон2-стиль")',
    'сломанный синтаксис ((((',
    '',
    '   ',
    'pass',
]


def main():
    print("конформность ob_renpy_rpyc vs parser.py (seed %d):" % SEED)
    print("A) полные AST-формы...")
    for proto in (2, 0, 1, 3, 4):
        full = corpus_full(plain_pyexpr=(proto in (0, 1)))
        payload = pickle.dumps(({"_ob": True}, full), protocol=proto)
        frame(payload, "proto%d" % proto, "full-proto%d" % proto)
    print("   A: полные формы, протоколы 0-4, legacy+RPC2 OK")

    # B) сломанный первый слот + годный второй
    print("B) фрейминг...")
    payload = pickle.dumps(({"d": 1}, [say("Живая")]), protocol=2)
    good = zlib.compress(payload)
    buf = io.BytesIO()
    buf.write(b"RENPY RPC2")
    buf.write(struct.pack("III", 1, 100, 5))
    buf.write(struct.pack("III", 0, 0, 0))
    pos = buf.tell()
    buf.write(b"xxxxx")
    start2 = buf.tell()
    buf.write(good)
    buf.seek(len(b"RENPY RPC2") + 12)
    buf.write(struct.pack("III", 1, start2, len(good)))
    check(buf.getvalue(), "rpc2-второй-слот")
    # только нулевой слот — оба None/Err
    buf2 = b"RENPY RPC2" + struct.pack("III", 0, 0, 0)
    check(buf2, "rpc2-пусто")
    # мусор вместо zlib
    check(b"RENPY RPC2" + struct.pack("III", 1, 22, 4) + b"zzzz",
          "rpc2-мусор")
    check("не сжатое вообще".encode("utf-8"), "legacy-мусор")
    check(b"", "пусто")
    check(b"RENPY RPC", "короткая-магия")
    check(b"RENPY RPC2" + struct.pack("III", 1, 0, 0), "rpc2-обрезок-слота")
    print("   B: фрейминг OK")

    corpus_opcodes()
    corpus_py_sources()
    corpus_random()
    corpus_hostile()
    corpus_order_files()
    print("СРАВНЕНИЙ: %d, HOSTILE: %d" % (N_COMPARE, N_HOSTILE))
    print("КОНФОРМНОСТЬ: OK (0 расхождений)")


def corpus_opcodes():
    print("C) рукописные опкоды...")
    X = lambda s: b"X" + struct.pack("<I", len(s)) + s  # BINUNICODE
    G = lambda m, n: b"c" + m + b"\n" + n + b"\n"  # GLOBAL

    def say_payload(inner: bytes) -> bytes:
        # (dict, [Say-what=inner]) top
        return (b"\x80\x02}q\x00" + X(b"_ob") + b"q\x01\x88s"
                + b"]q\x02(mark" + G(b"renpy.ast", b"Say")
                + b"q\x03)q\x04\x81q\x05}q\x06(mark"
                + X(b"what") + inner + b"uq\x07b"
                + b"e\x86q\x08.").replace(b"mark", b"\x28")

    # скаляры в what: int/float/None/bool/bytes/list
    for tag, val in [
        ("int", b"Kq\x08"),
        ("neg", b"J" + struct.pack("<i", -5)),
        ("int16", b"M" + struct.pack("<H", 700)),
        ("long", b"L123L\n"),
        ("long-neg", b"L-010L\n"),
        ("long1", b"\x8a\x02\x10\x27"),
        ("long4", b"\x8b" + struct.pack("<i", 2) + b"\x10\x27"),
        ("float", b"F2.5\n"),
        ("binfloat", b"G" + struct.pack(">d", 0.5)),
        ("none", b"N"),
        ("true", b"\x88"),
        ("false", b"\x89"),
        ("int00", b"I00\n"),
        ("int01", b"I01\n"),
        ("int0x", b"I0x10\n"),
        ("int-oct", b"I010\n"),
        ("int-dec", b"I  -42 \n"),
        ("inf", b"Finf\n"),
        ("nan", b"Fnan\n"),
        ("uni", b"V\\u00e9t\xd0\xb0\n"),
        ("unistring", X("Tête".encode("utf-8"))),
        ("short-uni", b"\x8c\x03abc"),
        ("binstr", b"T" + struct.pack("<i", 3) + b"abc"),
        ("short-binstr", b"U\x03abc"),
        ("string", b"S'hi there'\n"),
        ("string-esc", b"S'a\\x41\\101\\n'\n"),
        ("bytes", b"B" + struct.pack("<I", 2) + b"hi"),
        ("short-bytes", b"C\x02hi"),
        ("empty-tuple", b")"),
        ("tuple1", b"K\x01\x85"),
        ("tuple3", b"K\x01K\x02K\x03\x87"),
        ("emptylist", b"]"),
        ("emptydict", b"}"),
        ("emptyset", b"\x8f"),
    ]:
        check(legacy(say_payload(val)), "op/%s" % tag)
    # маркеры без метки — оба падают
    for tag, raw in [
        ("no-mark-tuple", b"\x80\x02Nt."),
        ("no-mark-appends", b"\x80\x02]K\x01e."),
        ("no-mark-setitems", b"\x80\x02}K\x01u."),
        ("no-mark-dict", b"\x80\x02K\x01d."),
        ("no-mark-list", b"\x80\x02K\x01l."),
        ("no-mark-frozenset", b"\x80\x02K\x01\x91."),
        ("pop-empty", b"\x80\x020."),
        ("dup-empty", b"\x80\x022."),
        ("stop-empty", b"\x80\x02."),
        ("bad-opcode", b"\x80\x02\xff."),
        ("proto9", b"\x809."),
        ("trunc", b"\x80\x02X\x05ab"),
        ("trunc-line", b"\x80\x02I12"),
        ("bad-memo", b"\x80\x02h\x00."),
        ("put-neg", b"\x80\x02Np-3\n."),
        ("persid", b"\x80\x02Ppid\n."),
        ("binpersid", b"\x80\x02NQ."),
        ("ext1", b"\x80\x02\x82\x01."),
        ("next-buf", b"\x80\x05\x97."),
        ("uni-badhex", b"V\\uzzz\n."),
        ("uni-range", b"V\\U00110000\n."),
        ("string-noascii", b"S'\xe9'\n."),
        ("string-badx", b"S'a\\x4'\n."),
        ("binstr-noascii", b"T" + struct.pack("<i", 1) + b"\xe9"),
        ("binstr-neg", b"T" + struct.pack("<i", -1)),
        ("long4-neg", b"\x8b" + struct.pack("<i", -2)),
        ("int-garbage", b"I12L\n."),
        ("float-garbage", b"F1_0\n."),
        ("global-evil", b"c" + b"os\nsystem\n."),
        ("global-builtin-evil", b"c" + b"builtins\neval\n."),
        ("stack-global-evil", X(b"os") + X(b"system") + b"\x93"),
        ("newobj-noclass", b"N)q\x00\x81."),
        ("reduce-evil", X(b"x") + b"R"),
        ("build-on-int", b"K\x01K\x02b."),
        ("append-todict", b"}K\x01a."),
        ("setitem-tolist", b"]K\x01K\x02s."),
        ("newobjex-kwargs", G(b"renpy.ast", b"Say") + b")K\x01\x92."),
    ]:
        check(legacy(raw), "op-fail/%s" % tag)
    # INST / OBJ / NEWOBJ_EX / STACK_GLOBAL руками (успех).
    # INST: MARK, пустые аргументы, затем BUILD словарём состояния.
    inst_say = (b"(i" + b"renpy.ast\nSay\n"
                + b"}" + X(b"what") + X("Hi inst".encode()) + b"s" + b"b")
    check(legacy(b"\x80\x02}q\x00" + X(b"k") + b"q\x01K\x01sq\x02"
                + b"]q\x03" + inst_say + b"aq\x04" + b"\x86q\x05."),
          "op/inst")
    # OBJ: MARK, класс, аргументы (съедаются mock), затем BUILD.
    obj_say = (b"(" + G(b"renpy.ast", b"Say")
               + X(b"what") + X(b"Obj hi") + b"o"
               + b"}" + X(b"what") + X(b"Obj hi") + b"s" + b"b")
    check(legacy(b"\x80\x02}q\x00" + X(b"k") + b"q\x01K\x01sq\x02"
                + b"]q\x03" + obj_say + b"aq\x04" + b"\x86q\x05."),
          "op/obj")
    # NEWOBJ_EX: класс, пустой кортеж, пустые kwargs.
    newobj_ex = (G(b"renpy.ast", b"Say") + b")}" + b"\x92"
                 + b"}" + X(b"what") + X(b"Ex hi") + b"s" + b"b")
    check(legacy(b"\x80\x02}q\x00" + X(b"k") + b"q\x01K\x01sq\x02"
                + b"]q\x03" + newobj_ex + b"aq\x04" + b"\x86q\x05."),
          "op/newobj-ex")
    # STACK_GLOBAL: модуль и имя со стека.
    sg = (X(b"renpy.ast") + X(b"Say") + b"\x93)N\x81"
          + b"}" + X(b"what") + X(b"Sg hi") + b"s" + b"b")
    check(legacy(b"\x80\x02}q\x00" + X(b"k") + b"q\x01K\x01sq\x02"
                + b"]q\x03" + sg + b"aq\x04" + b"\x86q\x05."),
          "op/stack-global")
    print("   C: опкоды OK")


def corpus_py_sources():
    print("D) python-исходники (%d)..." % len(PY_SOURCES))
    for i, src in enumerate(PY_SOURCES):
        d = Define()
        d.code = pyc(src)
        d.varname = "v"
        payload = pickle.dumps(({"_ob": True}, [d]), protocol=2)
        check(legacy(payload), "py-src/%d %r" % (i, src[:40]))
        if i % 2 == 0:
            check(rpc2(payload), "py-src-rpc2/%d" % i)
    # Default через value-PyExpr и Python-узел тоже
    for i, src in enumerate(PY_SOURCES[:12]):
        dd = Default()
        dd.value = PyExpr('"%s"' % src.replace('"', '\\"'), "s.rpy", 1)
        payload = pickle.dumps(({"_ob": True}, [dd]), protocol=2)
        check(legacy(payload), "py-default/%d" % i)
    print("   D: python-исходники OK")


WORDS = ["Привет", "там", "Hello", "Yes", "menu", "file.png", "q1",
         "quest_1", "empty_token_small", "https://example.com", "#ff8800",
         "42", "1,000", "a", "", "X", "  ", "e", "日本語", "é",
         "sampler2D blur", "a;b\nc", "don't", 'сказал "мяу"',
         "строка\nс переносом", "[score]", "{gold}", "x", "Идти "]


def corpus_random():
    print("E) случайные AST (200)...")
    r = random.Random(SEED)
    for i in range(200):
        proto = r.choice([0, 1, 2, 2, 3, 4])
        plain = proto in (0, 1)

        def px(s):
            # см. комментарий в corpus_full: слоты-PyExpr не переживают
            # dumps протоколами 0/1 на Python 3.11+.
            return s if plain else PyExpr(s, "s.rpy", 1)

        stmts = []
        for _ in range(r.randint(1, 4)):
            k = r.random()
            if k < 0.35:
                what = r.choice(WORDS)
                if r.random() < 0.4:
                    what = [r.choice(WORDS),
                            px(r.choice(["x", "a.b", "d['k']"])),
                            r.choice(WORDS)]
                stmts.append(say(what, r.choice([None, "Кто", "x"])))
            elif k < 0.5:
                m = Menu()
                items = []
                for _ in range(r.randint(1, 3)):
                    cap = r.choice(WORDS)
                    if r.random() < 0.3:
                        cap = [cap, px("v")]
                    block = [say(r.choice(WORDS))] if r.random() < 0.5 else []
                    items.append((cap, None, block))
                m.items = items
                if r.random() < 0.3:
                    m.caption = r.choice(WORDS)
                stmts.append(m)
            elif k < 0.65:
                d = Define()
                d.code = pyc('%s = "%s"' % (r.choice(["a", "q1", "gold_text"]),
                                            r.choice(WORDS)))
                stmts.append(d)
            elif k < 0.8:
                stmts.append(lab("lb%d" % r.randint(0, 3),
                                 [say(r.choice(WORDS))]))
            else:
                stmts.append(disp(Text, [px('"%s"' % r.choice(WORDS))]))
        payload = pickle.dumps(({"r": i}, stmts), protocol=proto)
        if r.random() < 0.5:
            check(legacy(payload), "rnd/%d/p%d" % (i, proto))
        else:
            check(rpc2(payload), "rnd/%d/p%d" % (i, proto))
    print("   E: случайные OK")


def corpus_hostile():
    print("F) враждебные...")
    X = lambda s: b"X" + struct.pack("<I", len(s)) + s
    cases = [
        ("os-system", b"c" + b"os\nsystem\n" + b"(X\x03cmdtR."),
        ("subprocess", b"c" + b"subprocess\nPopen\n."),
        ("builtins-eval", b"c" + b"builtins\neval\n" + b"(X\x03cmdtR."),
        ("operator", b"c" + b"operator\nsystem\n."),
        ("copyreg-evil", b"c" + b"copyreg\n_pickle\n."),
        ("stack-global-os", X(b"os") + X(b"system") + b"\x93."),
        ("reduce-builtin-list", b"cbuiltins\nlist\n"
         + b"]" + b"R."),
        ("persid", b"Panything\n."),
        ("huge-binunicode",
         b"X" + struct.pack("<I", 0x7fffffff) + b"a"),
        ("huge-frame", b"\x80\x04\x95" + struct.pack("<Q", 2 ** 62)),
        ("neg-long4", b"\x8b" + struct.pack("<i", -1)),
        ("trunc-proto", b"\x80"),
        ("memo-bomb", b"".join(
            [b"\x80\x02"] + [b"K\x01q" + bytes([i % 256]) for i in range(300)]
            + [b"."])),
        ("deep", b"\x80\x02" + b"]" * 1 + b"".join(
            [b"]" for _ in range(50000)]) + b"."),
    ]
    for tag, raw in cases:
        check_hostile(legacy(raw), tag)
    # мутации валидного: 200 шт, только Err/Ok, падений нет
    print("   мутации (200)...")
    r = random.Random(SEED + 1)
    base = rpc2(pickle.dumps(({"k": 1}, [say("Цельсия")]), protocol=2))
    accepted = 0
    for i in range(200):
        buf = bytearray(base)
        for _ in range(r.randint(1, 8)):
            op = r.random()
            if op < 0.5 and len(buf) > 0:
                buf[r.randrange(len(buf))] = r.randrange(256)
            elif op < 0.75 and len(buf) > 0:
                del buf[r.randrange(len(buf))]
            else:
                buf[r.randrange(len(buf) + 1):r.randrange(len(buf) + 1)] = \
                    bytes([r.randrange(256)])
        try:
            rust.extract_rpyc(bytes(buf))
            accepted += 1
        except ValueError:
            pass
        except Exception as e:
            print("FAIL мутация %d: %r" % (i, e))
            raise SystemExit(1)
    print("   мутации: 200 входов, падений 0 (принято %d)" % accepted)
    print("   F: враждебные OK")


def corpus_order_files():
    print("G) порядок на 3 файлах...")
    import hashlib
    for fi in range(3):
        stmts = [
            lab("first", [say("Раз %d" % fi), say("Два %d" % fi)]),
            say("Между %d" % fi),
            lab("second", [say("Три %d" % fi)]),
        ]
        payload = pickle.dumps(({"f": fi}, stmts), protocol=2)
        data = rpc2(payload)
        want = py_extract(data)
        got = [tuple(t) for t in rust.extract_rpyc(data)]
        assert got == want, (fi, got, want)
        # мультимножество + порядок
        from collections import Counter
        assert Counter(got) == Counter(want), fi
        h_w = hashlib.sha1(repr(want).encode()).hexdigest()
        h_g = hashlib.sha1(repr(got).encode()).hexdigest()
        assert h_w == h_g, fi
    print("   G: порядок OK")


if __name__ == "__main__":
    main()
