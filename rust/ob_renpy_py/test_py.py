# -*- coding: utf-8 -*-
"""Python-тест PyO3-обёртки `_ob_renpy_py`: Rust вместо `sourcetr` на синтетике.

Гоняет `translate_text`/`find_literals`/`choose_method` из Rust и сверяет
с Python-эталоном (`app/core/renpy/sourcetr.py`, `universal.py`) на тех же
входах. Строки — выдуманные маркеры, не текст игр.

Запуск после `build_mod.py` (рядом лежат `_ob_renpy_py.pyd` и libunwind.dll).
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OBOB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)     # _ob_renpy_py.pyd + libunwind.dll
sys.path.insert(0, OBOB)     # app.*

import _ob_renpy_py as rust
from app.core.renpy import sourcetr as py
from app.core.renpy import universal as u

print("pyo3: translate_text vs sourcetr.translate_text...")
cases = [
    ('e "Hello"', {"Hello": "Privet"}),
    ('"Yes"\n"No"\n', {"Yes": "Da", "No": "Net"}),
    ("label start:\n    e \"Hi there\"\n    menu:\n"
     '        "Go":\n            pass\n',
     {"Hi there": "Privet tam", "Go": "Idti"}),
    # код не трогаем, путь не трогаем
    ('x = eval("A")\ne "B"',
     {"A": "NeTrogaem", "B": "Trogaem"}),
    ('e "file.png"\ne "plain"',
     {"file.png": "X", "plain": "Prostaya"}),
    # экранирование в обе стороны
    ('e "a\\"b"\ne "c"', {"a\"b": "X", "c": "Y\nZ"}),
    # пустые и странные входы
    ("", {"": ""}),
    ("e \"A\"", {}),
    ("e \"A\"", {"A": ""}),
]
for src, mapping in cases:
    want = py.translate_text(src, mapping)
    got = rust.translate_text(src, mapping)
    assert (got[0], got[1], list(got[2])) == (want[0], want[1], want[2]), \
        (src, mapping, want, got)
    print("   %-40r замен=%d missed=%d OK"
          % (src[:40], want[1], len(want[2])))

print("pyo3: find_literals vs _find_literal_patterns...")
for text, lit in [('e "A" B', "A"), ('"AA"', "A"),
                  ("е \"Привет\" да", "Привет"),
                  ('e "a\\"b"', 'a"b'), ('""', "")]:
    want = list(py._find_literal_patterns(text, lit))
    got = [tuple(s) for s in rust.find_literals(text, lit)]
    assert got == want, (text, lit, want, got)
    print("   %-30r %r -> %s OK" % (text[:30], lit, got))

print("pyo3: escape/line_is_code_position/is_source_rpy_name...")
assert rust.escape('skazal "myau"\n') == py._escape('skazal "myau"\n')
for line in ["import os", 'x = eval("A")', "e \"Hi\"", "  Else:"]:
    assert rust.line_is_code_position(line) == \
        py._line_is_code_position(line), line
for name in ["a.rpy", "ob_x.rpy", "zz_ob_lang.rpy", "x.rpyc"]:
    assert rust.is_source_rpy_name(name) == (
        name.endswith(".rpy")
        and not name.startswith(("ob_", "zz_ob_"))), name
print("   OK")

print("pyo3: choose_method на синтетических папках...")
for files, want_method in [
    ([], "hooks"),
    (["a.rpy"], "hooks"),
    (["a.rpy", "b.rpy"], "hooks"),
    (["a.rpy", "b.rpy", "c.rpy"], "source"),
    (["ob_x.rpy", "zz_ob_lang.rpy", "a.rpy"], "hooks"),
    (["a.rpy", "b.rpy", "c.rpy", "d.rpy", "e.rpy"], "source"),
]:
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "game"))
        for n in files:
            open(os.path.join(td, "game", n), "w").close()
        want = u.choose_method(td)
        got = rust.choose_method(want["loose_rpy"],
                                 want["has_identifiers"])
        assert dict(got) == want, (files, want, dict(got))
        assert got["method"] == want_method, (files, got)
        print("   %s -> %s (loose=%d) OK"
              % (files, got["method"], want["loose_rpy"]))
# Ветка native напрямую (синтезировать .rpyc с идентификаторами — не здесь).
got = rust.choose_method(1, True)
assert got["method"] == "native" and got["has_identifiers"] is True
assert "идентификаторы" in got["reason"]
print("   native-ветка OK")

print("pyo3: битый вход -> TypeError, а не падение...")
for bad_text, bad_map in [(b"e \"A\"", {"A": "B"}),
                          ("e \"A\"", {"A": 5}),
                          ("e \"A\"", {5: "B"}),
                          (None, {})]:
    try:
        rust.translate_text(bad_text, bad_map)
        raise SystemExit("FAIL: rust проглотил %r" % (bad_text,))
    except TypeError:
        pass
try:
    rust.find_literals(b"e \"A\"", "A")
    raise SystemExit("FAIL: find_literals проглотил bytes")
except TypeError:
    pass
print("   OK")

print()
print("PYO3 ТЕСТ ОБЁРТКИ ЗЕЛЁНЫЙ")
