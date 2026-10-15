# -*- coding: utf-8 -*-
"""Конформность Rust-порта `ob_renpy` с `app/core/renpy/sourcetr.py`.

Генерирует 60+ случайных входов программно (литералы с кавычками,
переносами и backslash'ами, строки кода с eval/import, пути, меню,
кириллица/CJK/эмодзи, странные пробелы U+00A0/U+001C/U+3000/U+200B,
пустые ключи и переводы) и сверяет выход Rust (через `_ob_renpy_py`)
с Python один в один: новый текст, число замен, `missed` С ПОРЯДКОМ.
Плюс спаны `find_literals` (символьные индексы) и правило `choose_method`
на синтетических папках. Расхождение = провал скрипта (код 1).

Битый вход (bytes, не-строки в словаре) обязан дать TypeError, а не
падение интерпретатора.
"""
import io
import os
import random
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OBOB = os.path.dirname(os.path.dirname(HERE))
PYMOD = os.path.join(OBOB, "rust", "ob_renpy_py")
sys.path.insert(0, PYMOD)    # _ob_renpy_py.pyd + libunwind.dll
sys.path.insert(0, OBOB)     # app.*

import _ob_renpy_py as rust
from app.core.renpy import sourcetr as py
from app.core.renpy import universal as u

SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 777
R = random.Random(SEED)

WORDS = ["Hello", "Privet", "Yes", "Da", "Go", "menu", "say", "text",
         "Привет", "там", "日本語", "é", "e", "a", "ab", "b", "X", "No",
         "and", "or", "is", "None", "True", "if", "else", "for",
         "file.png", "a/b", "x=y", "a:b", "100%", "what?", "a!b",
         "x.rpy", "song.ogg", "a\\b", ".py", "x.py!", "f", ""]
QUOTES = ['"', "'", "\\", "\\n", "\\t"]
SPACES = [" ", "  ", "\t", " ", "　", " ", " ", " "]
CODE_LINES = ["import os", "from x import y", "def f():", "class C:",
              "return 1", "else:", "if x:", "  while 1:",
              'x = eval("ZZZ")', "EXEC (qq)", "compile\t(z)",
              "print x", "lambda q: q", "eval (x)", "eval(x)"]
WRAPS = ['e "%s"', '"%s"', '    "%s":', "menu \"%s\":" ,
         "'%s'", 'x "%s" y "%s"', '"%s""%s"', "e \\%s\"%s\""]


def rand_word():
    w = R.choice(WORDS)
    if R.random() < 0.25:
        w += R.choice(QUOTES) + R.choice(WORDS)
    if R.random() < 0.10:
        w += "\n" + R.choice(WORDS)
    return w


def rand_line(pool):
    r = R.random()
    if r < 0.12:
        return R.choice(CODE_LINES)
    if r < 0.06:
        return ""
    lit = rand_word()
    pat = R.choice(WRAPS)
    try:
        line = pat % ((lit,) * pat.count("%s"))
    except TypeError:
        line = '"%s"' % lit
    if R.random() < 0.3:
        line = R.choice(SPACES) + line
    for p in pool:
        if R.random() < 0.35 and p:
            line = line.replace("ZZZ", '"%s"' % p.replace('"', '\\"'),
                                1) if "ZZZ" in line else line
    return line


def rand_text(pool):
    return "\n".join(rand_line(pool) for _ in range(R.randint(1, 8)))


def rand_mapping(pool):
    m = {}
    for _ in range(R.randint(1, 5)):
        k = rand_word() if R.random() < 0.7 else R.choice(pool)
        v = rand_word()
        if R.random() < 0.15:
            v = ""
        m[k] = v
    return m


def main():
    print("конформность ob_renpy vs sourcetr.py:")
    pool = ["Hello", "Yes", "No", "Go", "Привет", "A", "B", "text"]
    n_case = 70
    for i in range(n_case):
        if i % 10 == 0:
            pool = [rand_word() for _ in range(6)]
        text = rand_text(pool)
        mapping = rand_mapping(pool)
        want = py.translate_text(text, mapping)
        got = rust.translate_text(text, mapping)
        got = (got[0], got[1], list(got[2]))
        if got != want:
            print("РАСХОЖДЕНИЕ translate_text #%d" % i)
            print("  text=%r" % text)
            print("  mapping=%r" % (mapping,))
            print("  python=%r" % (want,))
            print("  rust  =%r" % (got,))
            raise SystemExit(1)
    print("   translate_text: %d сгенерированных входов совпали один в один"
          % n_case)

    print("   find_literals: спаны...")
    for _ in range(30):
        text = rand_text(pool)
        lit = rand_word()
        want = list(py._find_literal_patterns(text, lit))
        got = [tuple(s) for s in rust.find_literals(text, lit)]
        if got != want:
            print("РАСХОЖДЕНИЕ find_literals: %r %r: %r != %r"
                  % (text, lit, want, got))
            raise SystemExit(1)
    # Точечно: символьные (не байтовые) индексы на кириллице.
    assert [tuple(s) for s in
            rust.find_literals("е \"Привет\" да", "Привет")] == [(2, 10)]
    print("   find_literals: 30 входов + кириллица OK")

    print("   guards/escape/имена...")
    for _ in range(40):
        line = rand_line(pool)
        if rust.line_is_code_position(line) != \
                py._line_is_code_position(line):
            print("РАСХОЖДЕНИЕ guard: %r" % line)
            raise SystemExit(1)
        w = rand_word()
        if rust.escape(w) != py._escape(w):
            print("РАСХОЖДЕНИЕ escape: %r" % w)
            raise SystemExit(1)
        n = R.choice(["a.rpy", "ob_x.rpy", "zz_ob_1.rpy", "x.rpyc",
                      "A.RPY", "d/e.rpy", "ob_.rpy"])
        if rust.is_source_rpy_name(n) != (
                n.endswith(".rpy")
                and not n.startswith(("ob_", "zz_ob_"))):
            print("РАСХОЖДЕНИЕ rpy_name: %r" % n)
            raise SystemExit(1)
    print("   guards/escape/имена: 40 входов OK")

    print("   choose_method на синтетических папках...")
    plans = [[], ["a.rpy"], ["a.rpy", "b.rpy"],
             ["a.rpy", "b.rpy", "c.rpy"],
             ["ob_1.rpy", "zz_ob_2.rpy"],
             ["a.rpy", "b.rpy", "ob_c.rpy", "zz_ob_d.rpy", "e.rpy",
              "f.rpy"],
             ["x%d.rpy" % i for i in range(10)]]
    for files in plans:
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "game"))
            for n in files:
                open(os.path.join(td, "game", n), "w").close()
            want = u.choose_method(td)
            got = dict(rust.choose_method(want["loose_rpy"],
                                          want["has_identifiers"]))
            if got != want:
                print("РАСХОЖДЕНИЕ choose_method %r: %r != %r"
                      % (files, want, got))
                raise SystemExit(1)
    # Ветка native (флаг True, loose < 3) — напрямую.
    got = dict(rust.choose_method(1, True))
    assert got["method"] == "native" and got["has_identifiers"] is True
    assert got["reason"] == ("в .rpyc есть идентификаторы реплик: пишем "
                             "штатные блоки translate"), got
    print("   choose_method: %d папок + native OK" % len(plans))

    print("   битый вход: TypeError без падения...")
    for bt, bm in [(b"e \"A\"", {"A": "B"}), ("e \"A\"", {"A": 1}),
                   (None, {}), ("e \"A\"", None)]:
        try:
            rust.translate_text(bt, bm)
            print("FAIL: проглочен вход %r" % (bt,))
            raise SystemExit(1)
        except TypeError:
            pass
    # Пустые и огромные входы — штатный результат, не паника.
    assert rust.translate_text("", {})[1] == 0
    big = "e \"A\"\n" * 20000
    out, n, _ = rust.translate_text(big, {"A": "B"})
    assert n == 20000 and out.count('"B"') == 20000
    print("   битый вход: OK")

    print("КОНФОРМНОСТЬ: OK (0 расхождений)")


if __name__ == "__main__":
    main()
