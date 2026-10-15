# -*- coding: utf-8 -*-
"""Конформность Rust-порта `ob_pck` с `app/core/godot/pck.py`.

Собирает ОДИН синтетический .pck хелпером `pack_files` из `pck.py`
(та же синтетика, что в `tests/test_godot.py`, строки — выдуманные
ASCII-маркеры), читает его Python-версией и Rust-бинарником
`ob_pck_dump`, сравнивает число записей, пути, ofs/size/md5/flags
один в один. Расхождение = провал скрипта (код 1).

Проверяются v2, v3 и v3 с каталогом в хвосте (настоящая раскладка
Godot 4.6), плюс совпадение отказов на битом входе.
"""
import hashlib
import io
import os
import struct
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
OBOB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, OBOB)

from app.core.godot import pck

CSV_SRC = "keys,en\nT1,T2 alpha bravo\nT2,T2 charlie delta\n"
TSN_SRC = "[node name=\"Btn\" type=\"Button\"]\ntext = \"T5 golf hotel\"\n"


def _pack(root, name="game.pck", **kw):
    path = os.path.join(root, name)
    pck.pack_files(path, {
        "res://locale/translation.csv": CSV_SRC.encode("utf-8"),
        "res://scenes/main.tscn": TSN_SRC.encode("utf-8"),
        "res://data/x.bin": bytes(range(256)),
    }, **kw)
    return path


def _rust_dump(path):
    r = subprocess.run(
        ["cargo", "run", "--quiet", "--bin", "ob_pck_dump", "--", path],
        cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssertionError(
            f"ob_pck_dump упал на {path}: rc={r.returncode}\n{r.stderr[-2000:]}")
    return r.stdout


def _compare(label, path):
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    blob = {e.path: pck.read_blob(path, e) for e in entries
            if not e.removal and not e.delta and not e.encrypted}
    dump = _rust_dump(path)
    got = {}
    rust_entries = []
    for line in dump.splitlines():
        if line.startswith("entry\t"):
            _, p, ofs, size, md5, flags = line.split("\t")
            rust_entries.append((p, int(ofs), int(size), md5, int(flags)))
        else:
            k, v = line.split("=", 1)
            got[k] = v
    for field in ("version", "ver_major", "ver_minor", "ver_patch",
                  "pack_flags", "file_base", "file_count", "base",
                  "filesize", "embedded", "dir_offset"):
        want = getattr(header, field)
        if field == "embedded":
            want = 1 if want else 0
        assert str(want) == got[field], \
            f"{label}: {field}: python={want} rust={got[field]}"
    want_res = ",".join(str(v) for v in header.reserved)
    assert want_res == got["reserved"], \
        f"{label}: reserved: python={want_res!r} rust={got['reserved']!r}"
    assert len(rust_entries) == len(entries) == header.file_count, \
        f"{label}: число записей: python={len(entries)} rust={len(rust_entries)}"
    for e, (p, ofs, size, md5, flags) in zip(entries, rust_entries):
        assert (e.path, e.ofs, e.size, e.md5.hex(), e.flags) == \
            (p, ofs, size, md5, flags), f"{label}: запись {e.path!r}: " \
            f"python={(e.path, e.ofs, e.size, e.md5.hex(), e.flags)} " \
            f"rust={(p, ofs, size, md5, flags)}"
    # И блобы по смещениям обеих версий — те же байты.
    raw = open(path, "rb").read()
    for e in entries:
        assert raw[e.ofs:e.ofs + e.size] == blob[e.path], \
            f"{label}: блоб {e.path!r}"
        assert hashlib.md5(blob[e.path]).digest() == e.md5
    print(f"   {label}: {len(entries)} записей совпали один в один")


def _v3_dir_to_end(path):
    """Каталог v3 в хвост пакета (зеркало хелпера из test_godot.py)."""
    header = pck.read_header(path)
    entries = pck.read_entries(path, header)
    raw = open(path, "rb").read()
    dir_size = sum(pck.ENTRY_OVERHEAD + len(e.path.encode("utf-8"))
                   for e in entries)
    cat_start = header.dir_offset
    cat_end = cat_start + 4 + dir_size
    catalog = raw[cat_start:cat_end]
    body = raw[:cat_start] + b"\x00" * (cat_end - cat_start) + raw[cat_end:]
    out = body + catalog
    new_dir = len(body)
    blob = bytearray(out[:pck.HEADER_SIZE_V3])
    struct.pack_into("<Q", blob, 32, new_dir)
    with open(path, "wb") as f:
        f.write(bytes(blob) + out[pck.HEADER_SIZE_V3:])


def main():
    print("конформность ob_pck vs pck.py:")
    with tempfile.TemporaryDirectory() as td:
        _compare("v2", _pack(td, version=2, ver_major=4, ver_minor=2,
                             ver_patch=1, file_base=4096, reserved=[7] * 16))
        _compare("v3", _pack(td, "v3.pck", version=pck.FORMAT_VERSION_46,
                             ver_major=4, ver_minor=6, ver_patch=2,
                             pack_flags=pck.PACK_REL_FILEBASE))
        tail = _pack(td, "v3tail.pck", version=pck.FORMAT_VERSION_46,
                     ver_major=4, ver_minor=6,
                     pack_flags=pck.PACK_REL_FILEBASE)
        _v3_dir_to_end(tail)
        _compare("v3-каталог-в-хвосте", tail)
        # Битый вход: обе версии отказываются (Python — PckError,
        # Rust — ненулевой код), а не молчат и не паникуют.
        path = _pack(td, "bad.pck")
        raw = bytearray(open(path, "rb").read())
        struct.pack_into("<Q", raw, 100 + 4 + 28, len(raw) + 1000)
        open(path, "wb").write(bytes(raw))
        try:
            pck.read_entries(path, pck.read_header(path))
            raise SystemExit("FAIL: python проглотил битое смещение")
        except pck.PckError:
            pass
        r = subprocess.run(
            ["cargo", "run", "--quiet", "--bin", "ob_pck_dump", "--", path],
            cwd=HERE, capture_output=True, text=True)
        assert r.returncode != 0, "FAIL: rust проглотил битое смещение"
        assert "panick" not in r.stderr.lower(), r.stderr[-500:]
        print("   битое смещение: обе версии отказались без паники")
    print("КОНФОРМНОСТЬ: OK")


if __name__ == "__main__":
    main()
