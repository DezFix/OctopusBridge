# -*- coding: utf-8 -*-
"""RPG Maker: парсер (извлечение MZ/MV, внедрение с бэкапами и защитой
от структурных сдвигов), патчер шрифтов, геометрия карт."""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.rpgmaker import parser
from app.core.rpgmaker.fontpatch import patch_font_mz, patch_font_mv, restore_font_mz


def make_project(root: str, variant: str = "mz") -> None:
    if variant == "mv":
        data = os.path.join(root, "www", "data")
        os.makedirs(data)
        os.makedirs(os.path.join(root, "www", "js"))
        open(os.path.join(root, "www", "js", "rpg_core.js"), "w").close()
    else:
        data = os.path.join(root, "data")
        os.makedirs(data)
        os.makedirs(os.path.join(root, "js"))
        open(os.path.join(root, "js", "rmmz_core.js"), "w").close()
    common = [None, {"id": 1, "name": "テスト", "list": [
        {"code": 401, "indent": 0, "parameters": ["私は魔女です"]},
        {"code": 356, "indent": 0, "parameters": ["ShowText こんにちは"]},
        {"code": 102, "indent": 0, "parameters": [
            ["Первый", "Второй"], 0, 1, 0]},
        {"code": 0, "indent": 0, "parameters": []},
    ], "switchId": 1, "trigger": 0}]
    with open(os.path.join(data, "CommonEvents.json"), "w",
              encoding="utf-8") as f:
        json.dump(common, f, ensure_ascii=False)


print("1) Детект MV/MZ и find_data_dir...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mv")
    assert parser.detect_engine(td) == "mv"
    assert parser.find_data_dir(td) == "www/data"
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    assert parser.detect_engine(td) == "mz"
    assert parser.find_data_dir(td) == "data"
print("   OK")

print("2) Извлечение: диалоги, плагин-команды, выборы...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mv")
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    assert "私は魔女です" in texts
    assert "ShowText こんにちは" in texts
    assert "Первый" in texts and "Второй" in texts
    assert all(e.file.startswith("www/data/") for e in entries)
print("   OK:", [e.original for e in entries])

print("3) Внедрение: бэкапы + перевод + повторное извлечение...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    entries = parser.extract(td)
    for e in entries:
        e.translation = "ТЕСТ: " + e.original
        e.status = "translated"
    stats = parser.apply(td, entries)
    assert stats["strings"] == len(entries)
    assert stats["backups"]
    re_entries = parser.extract(td)
    assert all(x.original.startswith("ТЕСТ: ") for x in re_entries)
print("   OK")

print("4) Защита от структурного сдвига: строка на месте параметров...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    entries = parser.extract(td)
    # моделируем сдвиг: параметры диалога стали строкой, пути изменились
    data = os.path.join(td, "data", "CommonEvents.json")
    common = json.load(open(data, encoding="utf-8"))
    common[1]["list"][0]["parameters"] = "сломанная структура"
    json.dump(common, open(data, "w", encoding="utf-8"), ensure_ascii=False)
    skipped = []
    for e in entries:
        e.translation = "ТЕСТ: " + e.original
        e.status = "translated"
    stats = parser.apply(td, entries, on_skip=lambda e, why: skipped.append(why))
    assert skipped, "сдвинутая структура обязана быть пропущена, а не крашить"
    # сломанная запись не внедрена, остальные — да
    re_entries = parser.extract(td)
    ok = sum(1 for x in re_entries if x.original.startswith("ТЕСТ: "))
    assert ok == len(entries) - len(skipped), (ok, len(entries), len(skipped))
    assert not any(x.original.startswith("ТЕСТ: 私は魔女です")
                   for x in re_entries)
print("   OK: пропущено:", len(skipped))

print("5) Патчер шрифта MZ (System.json) с откатом...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "fonts"))
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"advanced": {"mainFontFilename": "mplus-1m-regular.woff",
                                "numberFontFilename": "mplus-2p-bold-sub.woff"}}, f)
    fake = os.path.join(td, "MyFont.ttf")
    open(fake, "wb").write(b"fake-font-bytes")
    report = patch_font_mz(td, fake)
    adv = json.load(open(os.path.join(td, "data", "System.json"),
                         encoding="utf-8"))["advanced"]
    assert adv["mainFontFilename"] == "MyFont.ttf"
    assert os.path.exists(os.path.join(td, "fonts", "MyFont.ttf"))
    assert report["backup"]
    assert restore_font_mz(td)
    adv = json.load(open(os.path.join(td, "data", "System.json"),
                         encoding="utf-8"))["advanced"]
    assert adv["mainFontFilename"] == "mplus-1m-regular.woff"
print("   OK")

print("6) Патчер шрифта MV (gamefont.css)...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "fonts"))
    fake = os.path.join(td, "Rus.ttf")
    open(fake, "wb").write(b"fake")
    report = patch_font_mv(td, fake)
    css = open(report["css"], encoding="utf-8").read()
    assert "GameFont" in css and "Rus.ttf" in css
print("   OK")

print("7) Геометрия карт (maprender.tile_source)...")
from app.core.rpgmaker import maprender
assert maprender.tile_source(0) is None
assert maprender.tile_source(1) == (maprender.PAGE_B, 48, 0)
assert maprender.tile_source(16) == (maprender.PAGE_B, 0, 96)
assert maprender.tile_source(128) == (maprender.PAGE_B, 384, 0)
assert maprender.tile_source(1536) == (maprender.PAGE_A5, 0, 0)
assert maprender.tile_source(2048)[0] == maprender.PAGE_A1
assert maprender.tile_source(2816)[0] == maprender.PAGE_A2
assert maprender.tile_source(99999) is None
print("   OK")

print()
print("ВСЕ ТЕСТЫ RPG MAKER ПРОШЛИ")
