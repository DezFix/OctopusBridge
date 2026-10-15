# -*- coding: utf-8 -*-
"""Python-тест PyO3-обёртки: Rust вместо `pck.read_entries` на синтетике.

Собирает .pck хелпером `pack_files` из `pck.py`, вызывает Rust
(`parse_pck`/`read_blob` из `_ob_pck_py`) и сверяет заголовок, каталог
и байты блобов с выходом `pck.py` один в один. Плюс отказ на битом входе
(ValueError, а не падение интерпретатора).

Сборка модуля — `build_mod.py` рядом (cargo + переименование .dll в .pyd).
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OBOB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)     # _ob_pck_py.pyd + libunwind.dll
sys.path.insert(0, OBOB)     # app.*

from app.core.godot import pck
import _ob_pck_py as rust

CSV_SRC = "keys,en\nT1,T2 alpha bravo\nT2,T2 charlie delta\n"
TSN_SRC = "[node name=\"Btn\" type=\"Button\"]\ntext = \"T5 golf hotel\"\n"

print("pyo3: parse_pck vs pck.read_header/read_entries...")
for kw in (dict(version=2, ver_major=4, ver_minor=2, ver_patch=1,
                file_base=4096, reserved=[7] * 16),
           dict(version=pck.FORMAT_VERSION_46, ver_major=4, ver_minor=6,
                ver_patch=2, pack_flags=pck.PACK_REL_FILEBASE)):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "game.pck")
        pck.pack_files(path, {
            "res://locale/translation.csv": CSV_SRC.encode("utf-8"),
            "res://scenes/main.tscn": TSN_SRC.encode("utf-8"),
            "res://data/x.bin": bytes(range(256)),
        }, **kw)
        raw = open(path, "rb").read()
        header = pck.read_header(path)
        entries = pck.read_entries(path, header)
        rh, rentries = rust.parse_pck(raw)
        assert rh["version"] == header.version == kw["version"]
        for f in ("ver_major", "ver_minor", "ver_patch", "pack_flags",
                  "file_base", "file_count", "base", "filesize",
                  "dir_offset"):
            assert rh[f] == getattr(header, f), (f, rh[f])
        assert list(rh["reserved"]) == header.reserved
        assert rh["embedded"] == header.embedded
        assert len(rentries) == len(entries) == 3
        for e, re in zip(entries, rentries):
            assert re["path"] == e.path
            assert re["ofs"] == e.ofs and re["size"] == e.size
            assert bytes(re["md5"]) == e.md5
            assert re["flags"] == e.flags
            want = pck.read_blob(path, e)
            assert rust.read_blob(raw, re["ofs"], re["size"],
                                  re["flags"]) == want
            assert raw[re["ofs"]:re["ofs"] + re["size"]] == want
        print(f"   v{kw['version']}: 3 записи и блобы совпали")

print("pyo3: битый вход -> ValueError...")
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "game.pck")
    pck.pack_files(path, {"res://a.txt": b"hello"})
    raw = open(path, "rb").read()
    for bad in (b"", b"GD", raw[:50], raw[:99]):
        try:
            rust.parse_pck(bytes(bad))
            raise SystemExit(f"FAIL: rust проглотил {len(bad)} байт")
        except ValueError:
            pass
print("   OK")

print()
print("ВСЕ ТЕСТЫ PYO3 ПРОШЛИ")
