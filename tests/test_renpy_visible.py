# -*- coding: utf-8 -*-
"""Ren'Py player-visible text coverage: conditional menu choices,
two-word speakers (image tags), single quotes, show/scene text,
screen label/textbutton/input, menu caption, __()/_p(), f-/rf-
prefixes, triple quotes, backslash continuations, long strings,
skip-words followed by a literal, color/file false positives."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.renpy import parser as renpy


def make_game(root, script):
    os.makedirs(os.path.join(root, "game"), exist_ok=True)
    with open(os.path.join(root, "game", "script.rpy"), "w",
              encoding="utf-8") as f:
        f.write(script)


def texts_of(script):
    renpy._reset_screen_stack()
    with tempfile.TemporaryDirectory() as td:
        make_game(td, script)
        return [e.original for e in renpy.extract(td)]


print("1) Conditional menu choice (P1) ...")
t = texts_of("label start:\n"
             "    menu:\n"
             '        "Go to the forest" if can_go:\n'
             "            pass\n"
             '        "Stay at home":\n'
             "            pass\n")
assert "Go to the forest" in t, t
assert "Stay at home" in t, t
print("   OK")

print("2) Speaker with image tag (P2) ...")
t = texts_of("label start:\n" '    e happy "Hello there!"\n')
assert "Hello there!" in t, t
print("   OK")

print("3) Single quotes (P3) ...")
t = texts_of("label start:\n"
             "    e 'Good evening'\n"
             "    'Quiet narration'\n"
             '    e "do not worry"\n'
             "translate russian strings:\n"
             "    old 'Farewell'\n"
             "    new 'Goodbye'\n")
assert "Good evening" in t, t
assert "Quiet narration" in t, t
assert "do not worry" in t, t
assert "Farewell" in t, t
assert not any(x in ("t worry", "do not") for x in t), t
print("   OK")

print("4) show text / scene text, .rpy and .rpyc (P4) ...")
t = texts_of("label start:\n"
             '    show text "Chapter One"\n'
             '    scene text "Three years later"\n'
             "    show eileen happy\n")
assert "Chapter One" in t, t
assert "Three years later" in t, t
assert not any("eileen" in x for x in t), t


class _Sh4(object):
    pass


_Sh4.__name__ = "Show"
sh4 = _Sh4()
sh4.imspec = [renpy._MockPyExpr('"Chapter from rpyc"')]


class _Sc4(object):
    pass


_Sc4.__name__ = "Scene"
sc4 = _Sc4()
sc4.text = "Scene from rpyc"
sh4b = _Sh4()
sh4b.imspec = ["eileen", "happy"]
out4 = renpy._walk_ast([sh4, sc4])
assert ("screen", "Chapter from rpyc") in out4, out4
assert ("screen", "Scene from rpyc") in out4, out4
assert renpy._walk_ast([sh4b]) == [], renpy._walk_ast([sh4b])
print("   OK")

print("5) Screen label/textbutton/input (P5) ...")
t = texts_of("screen prefs:\n"
             '    text "Settings"\n'
             '    textbutton "Start game" action Start()\n'
             '    label "Volume"\n'
             '    input default "Enter name"\n'
             "label start:\n"
             '    e "Plain line"\n')
assert "Settings" in t, t
assert "Start game" in t, t
assert "Volume" in t, t
assert "Enter name" in t, t
assert "Plain line" in t, t
print("   OK")

print("6) Menu caption (P6) ...")
t = texts_of("label start:\n"
             '    menu (caption="What to do?"):\n'
             '        "Go to the forest":\n'
             "            pass\n")
assert "What to do?" in t, t
assert "Go to the forest" in t, t
print("   OK")

print("7) .rpyc Menu caption/prompt/who (P7) ...")


class _M7(object):
    pass


_M7.__name__ = "Menu"
m7 = _M7()
m7.items = [("Menu item", None, [])]
m7.caption = "What to do?"
m7.prompt = "Choose wisely"
m7.who = "Guide"
out7 = renpy._walk_ast([m7])
assert ("choice", "Menu item") in out7, out7
assert ("choice", "What to do?") in out7, out7
assert ("choice", "Choose wisely") in out7, out7
assert ("choice", "Guide") in out7, out7
print("   OK")

print("8) .rpyc screen Label/Input/Button + keywords (P8) ...")


class _SLD8(object):
    pass


_SLD8.__name__ = "SLDisplayable"


class _Lbl8(object):
    pass


_Lbl8.__name__ = "Label"
d8a = _SLD8()
d8a.displayable = _Lbl8
d8a.positional = [renpy._MockPyExpr('"Hero name"')]
d8a.children = []
d8a.keyword = {}


class _Inp8(object):
    pass


_Inp8.__name__ = "Input"
d8b = _SLD8()
d8b.displayable = _Inp8
d8b.positional = []
d8b.children = []
d8b.keyword = {"default": renpy._MockPyExpr('"Enter name"')}


class _Img8(object):
    pass


_Img8.__name__ = "Image"
d8c = _SLD8()
d8c.displayable = _Img8
d8c.positional = [renpy._MockPyExpr('"images/bg.png"')]
d8c.children = []
d8c.keyword = {}
out8 = renpy._walk_ast([d8a, d8b, d8c])
assert ("screen", "Hero name") in out8, out8
assert ("screen", "Enter name") in out8, out8
assert not any("bg.png" in x for _, x in out8), out8
print("   OK")

print("9) __() and _p() (P9) ...")
t = texts_of("screen s:\n"
             '    text __("Start")\n'
             "label start:\n"
             '    e "Line"\n')
assert "Start" in t, t
got9 = []
renpy._reset_screen_stack()
renpy._extract_line("t.rpy", 1, '    x = _p("One more line")', lambda f, c, o: got9.append(o))
assert "One more line" in got9, got9
print("   OK")

print("10) f-/rf- prefixes (P10) ...")
t = texts_of("label start:\n"
             '    e f"Hello {name}"\n'
             '    rf"Raw text"\n')
assert "Hello {name}" in t, t
assert "Raw text" in t, t
got10 = []
renpy._reset_screen_stack()
renpy._extract_line("t.rpy", 1, '    x = _(f"Gold: {gold}")', lambda f, c, o: got10.append(o))
assert "Gold: {gold}" in got10, got10
print("   OK")

print("11) Triple-quoted monologue (P11) ...")
t = texts_of("label start:\n"
             '    e """Long\n'
             '    hero monologue"""\n')
assert any("hero monologue" in x for x in t), t
print("   OK")

print("12) Backslash continuation (P12) ...")
t = texts_of("label start:\n"
             '    e "Long line \\\n'
             '        continued line"\n')
assert any("continued line" in x for x in t), t
print("   OK")

print("13) Long strings, 4000 -> 20000 (P14) ...")
long_text = "A" * 5000
t = texts_of("label start:\n" '    e "' + long_text + '"\n')
assert long_text in t, len(t)
print("   OK")

print("14) Skip-word with a literal, character named window (P17) ...")
t = texts_of('define window = Character("Window")\n'
             "label start:\n"
             '    window "Hello"\n'
             "    show eileen happy\n"
             "    jump start\n")
assert "Hello" in t, t
assert "Window" in t, t
assert "start" not in t, t
assert not any("eileen" in x for x in t), t
print("   OK")

print("15) Color/file false positives stay out (FP guard) ...")
t = texts_of("screen s:\n"
             '    text "#ff8800"\n'
             '    text "images/logo.png"\n'
             '    textbutton "https://example.com" action OpenURL()\n'
             "label start:\n"
             '    e "Line"\n')
assert "Line" in t, t
assert not any("#ff8800" in x or "logo.png" in x or "example.com" in x
               for x in t), t
print("   OK")

print("OK: visible RenPy coverage checks passed")
