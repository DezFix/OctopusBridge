# -*- coding: utf-8 -*-
"""Дымовой тест PyO3-обёртки `_ob_renpy_rpyc_py`: синтетический .rpyc
(Say + Menu, протокол 2, RPC2-упаковка) разбирается в те же тройки, что
`_unpickle_rpyc` + `_walk_ast` Python-эталона. Только синтетика."""
import io
import os
import pickle
import struct
import sys
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OBOB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)      # _ob_renpy_rpyc_py.pyd + libunwind.dll
sys.path.insert(0, OBOB)      # app.*

import _ob_renpy_rpyc_py as rust
from app.core.renpy import parser as py


class Say(py._MockNode):
    pass


class Menu(py._MockNode):
    pass


# Имена как у настоящих .rpyc (иначе pickle запишет модуль __main__,
# которого нет в белом списке Rust-VM).
Say.__module__ = "renpy.ast"
Say.__qualname__ = "Say"
Menu.__module__ = "renpy.ast"
Menu.__qualname__ = "Menu"
# pickle ищет класс по имени в sys.modules — подкладываем заглушки
# (как tests/test_renpy_coverage.py с ob_fake_renpy_ast).
import types as _types

for _mod in ("renpy", "renpy.ast"):
    if _mod not in sys.modules:
        sys.modules[_mod] = _types.ModuleType(_mod)
sys.modules["renpy.ast"].Say = Say
sys.modules["renpy.ast"].Menu = Menu


def main():
    s = Say()
    s.what = "Тестовая реплика"
    s.who = "Герой"
    m = Menu()
    m.items = [("Идти дальше", None, [])]
    payload = pickle.dumps(({"_ob": True}, [s, m]), protocol=2)
    data = zlib.compress(payload)
    buf = io.BytesIO()
    buf.write(b"RENPY RPC2")
    for _i in range(3):
        buf.write(struct.pack("III", 0, 0, 0))
    start = buf.tell()
    buf.write(data)
    buf.seek(len(b"RENPY RPC2"))
    buf.write(struct.pack("III", 1, start, len(data)))
    rpyc = buf.getvalue()

    parsed = py._unpickle_rpyc(rpyc)
    assert parsed is not None
    want = py._walk_ast(parsed[1], labeled=True)
    got = [tuple(t) for t in rust.extract_rpyc(rpyc)]
    assert got == want, (got, want)
    print("test_py: OK (%d троек совпали)" % len(want))

    # Битый вход — ValueError, не падение.
    for bad in (b"", b"RENPY RPC2", b"\x00" * 100):
        try:
            rust.extract_rpyc(bad)
            print("FAIL: проглочен вход %r" % (bad[:20],))
            raise SystemExit(1)
        except ValueError:
            pass
    print("test_py: битый вход OK")


if __name__ == "__main__":
    main()
