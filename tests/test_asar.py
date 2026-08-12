# -*- coding: utf-8 -*-
"""ASAR (Electron) и движок RPG Maker (Electron): чтение архивов,
патчинг на месте, пересборка, детект, извлечение/внедрение переводов."""
import io
import json
import os
import shutil
import struct
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import asar as asarlib
from app.engines.registry import detect_engine
from app.engines.rpgmaker import RpgMakerModule


# ── независимый билдер asar по спецификации @electron/asar ──
def write_asar(path: str, files: dict[str, bytes]) -> None:
    """files: {rel_path: bytes} — дерево в порядке вставки (порядок данных)."""
    tree, _total = _build_flat(files)

    blob = json.dumps(tree, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    pad = (-len(blob)) % 4
    with open(path, "wb") as f:
        f.write(struct.pack("<I", 4))
        f.write(struct.pack("<I", 8 + len(blob) + pad))
        f.write(struct.pack("<I", 4 + len(blob) + pad))
        f.write(struct.pack("<I", len(blob)))
        f.write(blob)
        f.write(b"\x00" * pad)
        for rel, data in files.items():
            f.write(data)


def _build_flat(files: dict[str, bytes]) -> tuple[dict, int]:
    """Простое дерево: каждый путь разбивается на вложенные каталоги."""
    tree: dict = {"files": {}}
    offset = 0
    for rel, data in files.items():
        parts = rel.split("/")
        cur = tree["files"]
        for p in parts[:-1]:
            nxt = cur.get(p)
            if nxt is None:
                nxt = {"files": {}}
                cur[p] = nxt
            cur = nxt["files"]
        cur[parts[-1]] = {"size": len(data), "offset": str(offset)}
        offset += len(data)
    return tree, offset


def _make_game(td: str, map_text: str = "こんにちは、世界。") -> str:
    """Синтетическая Electron-игра: resources/app.asar с MZ-проектом."""
    game = os.path.join(td, "game")
    os.makedirs(os.path.join(game, "resources"))
    map_data = {
        "displayName": "Старт",
        "width": 3, "height": 3,
        "data": [0] * 36,
        "events": [{"pages": [{"list": [
            {"code": 401, "parameters": [map_text]},
            {"code": 0, "parameters": []},
        ]}]}],
    }
    system = {"gameTitle": "Тест", "variables": ["", "Мана"],
              "switches": ["", "Голая"], "terms": {},
              "encryptionKey": "0123456789abcdef0123456789abcdef"}
    files = {
        "project/game.rmmzproject": b"RPGMV",
        "project/js/rmmz_core.js": b"var RMMZ = true;",
        "project/data/System.json":
            json.dumps(system, ensure_ascii=False).encode("utf-8"),
        "project/data/Map001.json":
            json.dumps(map_data, ensure_ascii=False).encode("utf-8"),
        "project/data/MapInfos.json": b"[]",
        "project/img/pics/logo.png": b"\x89PNG-fake",
    }
    write_asar(os.path.join(game, "resources", "app.asar"), files)
    return game


print("1) ASAR: чтение файлов, дерево, префиксы...")
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "a.asar")
    files = {
        "dir/файл.txt": "привет мир".encode("utf-8"),
        "dir/sub/b.bin": b"\x00\x01\x02\x03",
        "root.txt": b"root",
    }
    write_asar(p, files)
    ar = asarlib.AsarArchive(p)
    assert ar.read_file("dir/файл.txt") == "привет мир".encode("utf-8")
    assert ar.read_file("dir/sub/b.bin") == b"\x00\x01\x02\x03"
    assert ar.read_file("root.txt") == b"root"
    assert ar.read_file("нет.txt") is None
    assert [r for r, _ in ar.iter_files()] == list(files)
    out = os.path.join(td, "out")
    os.makedirs(out)
    assert ar.extract_prefix("dir", out) == 2
    assert open(os.path.join(out, "файл.txt"), "rb").read() == \
        "привет мир".encode("utf-8")
    assert open(os.path.join(out, "sub", "b.bin"), "rb").read() == \
        b"\x00\x01\x02\x03"
print("   OK")

print("2) ASAR: патчинг на месте (файл ужался — заголовок не тронут)...")
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "a.asar")
    files = {
        "a.txt": b"A" * 100,
        "b.bin": b"B" * 50,
    }
    write_asar(p, files)
    size_before = os.path.getsize(p)
    bak = os.path.join(td, "bak")
    stats = asarlib.apply_patches(p, {"a.txt": b"new" * 10}, backup_dir=bak)
    assert stats == {"files": 1, "in_place": 1, "repacked": False,
                     "backups": [os.path.join(bak, "a.txt")]}
    # размер не изменился (дополнено пробелами до исходной длины)
    assert os.path.getsize(p) == size_before
    ar = asarlib.AsarArchive(p)
    blob = ar.read_file("a.txt")
    assert blob == b"new" * 10 + b" " * 70, blob
    assert ar.read_file("b.bin") == b"B" * 50
    assert open(os.path.join(bak, "a.txt"), "rb").read() == b"A" * 100
    # заголовок не переписывался: смещения прежние
    assert ar.find("a.txt")["offset"] == "0"
    assert ar.find("b.bin")["offset"] == "100"
print("   OK")

print("3) ASAR: пересборка, когда файл вырос (оригинал -> .ob.bak)...")
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "a.asar")
    files = {
        "a.txt": b"A" * 10,
        "b.bin": b"B" * 50,
    }
    write_asar(p, files)
    orig = open(p, "rb").read()
    grown = b"C" * 500
    stats = asarlib.apply_patches(p, {"a.txt": grown})
    assert stats["repacked"] is True and stats["in_place"] == 0
    assert open(p + ".ob.bak", "rb").read() == orig
    ar = asarlib.AsarArchive(p)
    assert ar.read_file("a.txt") == grown
    assert ar.read_file("b.bin") == b"B" * 50
    assert ar.find("a.txt")["size"] == 500
    # смещения пересчитаны: b.bin начинается после нового a.txt
    assert ar.find("b.bin")["offset"] == "500"
print("   OK")

print("4) Детект Electron-игры RPG Maker MZ (единый модуль)...")
with tempfile.TemporaryDirectory() as td:
    game = _make_game(td)
    mod = detect_engine(game)
    assert isinstance(mod, RpgMakerModule), mod
    assert mod.variant == "mz"
    assert "files" in mod.features and "cheats" in mod.features
    assert "maps" in mod.features and "resources" in mod.features
    assert "font" not in mod.features  # шрифт у Electron-версии скрыт
    assert mod.display == "RPG Maker MZ (Electron)", mod.display
print("   OK")

print("5) Движок: извлечение строк из asar...")
with tempfile.TemporaryDirectory() as td:
    game = _make_game(td, "こんにちは、世界。")
    mod = RpgMakerModule(game)
    entries = mod.extract(game)
    texts = [e.original for e in entries]
    assert "こんにちは、世界。" in texts, texts
    assert any(e.file == "data/Map001.json" for e in entries)
    print("   OK:", texts)

print("6) Движок: внедрение перевода в asar + бэкапы...")
with tempfile.TemporaryDirectory() as td:
    game = _make_game(td, "こんにちは、世界。")
    mod = RpgMakerModule(game)
    entries = mod.extract(game)
    for e in entries:
        if e.original == "こんにちは、世界。":
            e.translation = "Здравствуй, мир."
            e.status = "translated"
    stats = mod.apply(game, entries)
    assert stats["strings"] >= 1, stats
    assert stats["files"] >= 1, stats
    ar = asarlib.AsarArchive(os.path.join(game, "resources", "app.asar"))
    blob = ar.read_file("project/data/Map001.json")
    assert "Здравствуй, мир." in blob.decode("utf-8")
    # оригинал Map001.json сохранён в backup/
    backups = stats.get("backups", [])
    assert backups, stats
    assert any(os.path.basename(b) == "Map001.json" for b in backups)
    # другие файлы архива не тронуты
    assert ar.read_file("project/data/System.json") == \
        json.dumps({"gameTitle": "Тест", "variables": ["", "Мана"],
                    "switches": ["", "Голая"], "terms": {},
                    "encryptionKey": "0123456789abcdef0123456789abcdef"},
                   ensure_ascii=False).encode("utf-8")
print("   OK")

print("7) FileView: ленивое чтение/запись карт и ресурсов в asar...")
with tempfile.TemporaryDirectory() as td:
    game = _make_game(td, "こんにちは、世界。")
    mod = RpgMakerModule(game)
    view = mod.file_view(game)
    assert view.exists("data/System.json")
    assert view.is_dir("img") and view.is_dir("img/pics")
    assert view.read_text("data/System.json") and \
        "Мана" in view.read_text("data/System.json")
    assert view.list_dir("img") == ["pics"]
    assert view.walk("img") == ["img/pics/logo.png"], view.walk("img")
    assert view.size("img/pics/logo.png") == len(b"\x89PNG-fake")
    # несуществующее — None/False/пусто
    assert view.read_bytes("нет.txt") is None
    assert not view.exists("нет.txt") and not view.is_dir("нет.txt")
    assert view.list_dir("нет") == [] and view.size("нет") is None
    # запись карты через view + commit -> asar изменён
    from app.core.rpgmaker import maprender
    maps = maprender.load_map(game, 1, view)
    assert maps is not None
    maps["displayName"] = "Спасение"
    rel = maprender.save_map(game, 1, maps, view=view)
    assert rel == "data/Map001.json", rel
    ar = asarlib.AsarArchive(os.path.join(game, "resources", "app.asar"))
    assert "Спасение" in ar.read_file("project/data/Map001.json").decode("utf-8")
    # повторный контент читается из свежего архива
    assert maprender.load_map(game, 1, view)["displayName"] == "Спасение"
    assert maprender.load_map(game, 1) is None  # без view диск-путь не видит
print("   OK")

print("8) FileView: именные списки читов из asar (varnames/crypto)...")
with tempfile.TemporaryDirectory() as td:
    game = _make_game(td)
    mod = RpgMakerModule(game)
    view = mod.file_view(game)
    from app.core.rpgmaker import crypto, varnames
    names = varnames.extract_names(game, view)
    assert names == ({1: "Мана"}, {1: "Голая"}), names
    assert varnames.extract_maps(game, view) == []  # MapInfos пуст
    # ключ шифрования: System.json внутри архива
    assert crypto.get_key(game, view=view) == \
        "0123456789abcdef0123456789abcdef"
print("   OK")

print()
print("ВСЕ ТЕСТЫ ASAR + RPG MAKER (ELECTRON) ПРОШЛИ")
