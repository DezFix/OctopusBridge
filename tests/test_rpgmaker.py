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
from app.core.rpgmaker.fontpatch import patch_font_mz, patch_font_mv


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

print("5) Патчер шрифта MZ (System.json)...")
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

print("8) Профиль NW.js: чистим Local State от более новой версии...")
from app.engines.rpgmaker.tentacle import clean_nwjs_profile
with tempfile.TemporaryDirectory() as fake_local:
    old_env = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = fake_local
    try:
        with tempfile.TemporaryDirectory() as td:
            # нет файла — нечего чинить
            assert clean_nwjs_profile(td) == []
            # свежий профиль без маркера версии не трогаем
            with open(os.path.join(td, "Local State"), "w",
                      encoding="utf-8") as f:
                json.dump({"profile": "ok"}, f)
            assert clean_nwjs_profile(td) == []
            assert os.path.exists(os.path.join(td, "Local State"))
            # профиль от более новой версии — переименовываем
            with open(os.path.join(td, "Local State"), "w",
                      encoding="utf-8") as f:
                json.dump({"user_data_version": 9999}, f)
            assert clean_nwjs_profile(td) == [td]
            assert not os.path.exists(os.path.join(td, "Local State"))
            assert os.path.exists(os.path.join(td, "Local State.bak"))
            # повторный запуск: новой записи нет — чинить нечего
            assert clean_nwjs_profile(td) == []
            # битый JSON — не трогаем
            with open(os.path.join(td, "Local State"), "w",
                      encoding="utf-8") as f:
                f.write("{not-json")
            assert clean_nwjs_profile(td) == []
            assert os.path.exists(os.path.join(td, "Local State"))
    finally:
        if old_env is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_env
print("   OK")

print("9) Профиль NW.js: user-data-dir из chromium-args и LOCALAPPDATA...")
with tempfile.TemporaryDirectory() as fake_local:
    old_env = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = fake_local
    try:
        with tempfile.TemporaryDirectory() as td:
            # --user-data-dir в chromium-args манифеста
            data_dir = os.path.join(td, "nwdata")
            os.makedirs(data_dir)
            with open(os.path.join(td, "package.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"chromium-args": "--user-data-dir=./nwdata"}, f)
            with open(os.path.join(data_dir, "Local State"), "w",
                      encoding="utf-8") as f:
                json.dump({"user_data_version": 123}, f)
            assert clean_nwjs_profile(td) == [data_dir]
            assert os.path.exists(
                os.path.join(data_dir, "Local State.bak"))
            # name из манифеста ищет профиль в %LOCALAPPDATA%\<name>\User Data
            os.makedirs(os.path.join(fake_local, "My Game", "User Data"))
            with open(os.path.join(td, "package.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"name": "My Game"}, f)
            stale = os.path.join(
                fake_local, "My Game", "User Data", "Local State")
            with open(stale, "w", encoding="utf-8") as f:
                json.dump({"user_data_version": 456}, f)
            assert clean_nwjs_profile(td) == [os.path.join(
                fake_local, "My Game", "User Data")]
            assert not os.path.exists(stale)
            assert os.path.exists(stale + ".bak")
    finally:
        if old_env is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = old_env
print("   OK")

print("11) launch: игра уже запущена с отладкой — подключаемся, "
      "не запуская второй экземпляр...")
from app.engines.rpgmaker.tentacle import RpgMakerTentacle
import app.engines.rpgmaker.tentacle as tentacle_mod


class FakePopen:
    def __init__(self, *a, **k):
        self.pid = 9999
        self.args = a[0]
        self.cwd = k.get("cwd")

    def poll(self):
        return None


with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    game_exe = os.path.join(td, "Game.exe")
    open(game_exe, "w").close()
    t = RpgMakerTentacle()
    t._connect_page = lambda port, url_hint="", wait=20.0: True
    tentacle_mod.proc.find_game_processes = lambda *a, **k: [{
        "pid": 4242, "name": "Game.exe", "exe": game_exe, "port": 9222}]
    assert t.launch(td) is True
    assert t._pid == 4242
    assert t._proc is None
print("   OK")

print("12) launch: игра запущена без отладки — закрываем "
      "и перезапускаем с портом...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    game_exe = os.path.join(td, "Game.exe")
    open(game_exe, "w").close()
    t = RpgMakerTentacle()
    killed = []
    tentacle_mod.proc.find_game_processes = lambda *a, **k: [{
        "pid": 4242, "name": "Game.exe", "exe": game_exe, "port": 0}]
    tentacle_mod.proc.terminate = lambda pid, timeout=3.0: (
        killed.append(pid) or True)
    tentacle_mod.browser.free_port = lambda: 7777
    tentacle_mod.subprocess.Popen = FakePopen
    t._connect_page = lambda port, url_hint="", wait=20.0: True
    assert t.launch(td) is True
    assert killed == [4242]
    assert t._proc is not None and t._proc.pid == 9999
    assert t._proc.args[-1] == "--remote-debugging-port=7777"
print("   OK")

print("13) launch: старый процесс не закрылся — понятная ошибка...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    game_exe = os.path.join(td, "Game.exe")
    open(game_exe, "w").close()
    t = RpgMakerTentacle()
    errs = []
    t.error.connect(lambda s: errs.append(s))
    tentacle_mod.proc.find_game_processes = lambda *a, **k: [{
        "pid": 4242, "name": "Game.exe", "exe": game_exe, "port": 0}]
    tentacle_mod.proc.terminate = lambda pid, timeout=3.0: False
    assert t.launch(td) is False
    assert errs
print("   OK")

print("14) reload_map: перечитывает MapXXX.json и пересоздаёт карту...")
expr = RpgMakerTentacle._cheat_expr("reload_map")
assert expr is not None
assert "$gameMap.setup(mapId)" in expr
assert "reserveTransfer" in expr
assert "('00' + mapId).slice(-3)" in expr
assert "Decrypter.decrypt" in expr
assert RpgMakerTentacle._cheat_expr("reload_map_unknown") is None
print("   OK")

print("15) map_layers: MV/MZ 6 слоёв (тени z4, регионы z5) + fallback 4 слоя...")
from app.core.rpgmaker import maprender
w, h = 2, 2
n = w * h
m6 = {"width": w, "height": h, "data": list(range(6 * n))}
W, H, lower, upper, shadow, region = maprender.map_layers(m6)
assert (W, H) == (w, h)
assert lower == list(range(0, 2 * n))
assert upper == list(range(2 * n, 4 * n))
assert shadow == list(range(4 * n, 5 * n)), "тени должны быть на z4"
assert region == list(range(5 * n, 6 * n)), "регионы на z5"
# MV-карты такие же 6-слойные (движок читает тени с z4)
mv = {"width": w, "height": h, "data": list(range(6 * n))}
W, H, lower, upper, shadow, region = maprender.map_layers(mv)
assert shadow == list(range(4 * n, 5 * n)), "MV: тени на z4"
assert region == list(range(5 * n, 6 * n)), "MV: регионы на z5"
# 5 слоёв: регионов нет
m5 = {"width": w, "height": h, "data": list(range(5 * n))}
W, H, lower, upper, shadow, region = maprender.map_layers(m5)
assert region == [] and shadow == list(range(4 * n, 5 * n))
# 4-слойный fallback: z2 — верхние тайлы, z3 — тени
m4 = {"width": w, "height": h, "data": list(range(4 * n))}
W, H, lower, upper, shadow, region = maprender.map_layers(m4)
assert upper == list(range(2 * n, 3 * n))
assert shadow == list(range(3 * n, 4 * n))
assert region == []
assert maprender.map_layers({}) == (0, 0, [], [], [], [])
print("   OK")

print("16) extract_plugins: имена в plugins.js уже с .js...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js", "plugins"))
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        json.dump([{"name": "MyPlugin.js", "status": True}], f)
    with open(os.path.join(td, "js", "plugins", "MyPlugin.js"), "w",
              encoding="utf-8") as f:
        f.write("const msg = 'こんにちは世界'; // comment")
    skipped = []
    entries = parser.extract_plugins(
        td, "data", on_skip=lambda name, e: skipped.append(name))
    texts = [e.original for e in entries]
    assert "こんにちは世界" in texts, f"плагин не извлечён, skipped={skipped}"
    assert not skipped
    assert entries[0].file == "js/plugins/MyPlugin.js"
print("   OK:", [e.original for e in entries])

print("17) 357: args-объект (MZ) и args-список (старый MZ)...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    data = os.path.join(td, "data", "CommonEvents.json")
    common = json.load(open(data, encoding="utf-8"))
    common[1]["list"] = [
        {"code": 357, "indent": 0, "parameters": [
            "js/plugins/Foo.js", "showMsg", "note", {"msg": "Привет"}]},
        {"code": 357, "indent": 0, "parameters": [
            "js/plugins/Foo.js", "showMsg2", "note", ["арг1", "арг2"]]},
    ]
    json.dump(common, open(data, "w", encoding="utf-8"), ensure_ascii=False)
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    assert "Привет" in texts
    assert "арг1" in texts and "арг2" in texts
print("   OK:", texts)

print("18) get_key_mv: ключ из System.json (www/data), fallback rpg_core.js...")
from app.core.rpgmaker import crypto
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "www", "data"))
    with open(os.path.join(td, "www", "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"encryptionKey": "00112233445566778899aabbccddeeff"}, f)
    assert crypto.get_key_mv(td) == "00112233445566778899aabbccddeeff"
    assert crypto.get_key(td) == "00112233445566778899aabbccddeeff"
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "www", "js"))
    with open(os.path.join(td, "www", "js", "rpg_core.js"), "w",
              encoding="utf-8") as f:
        f.write("// obfuscated\nencryptionKey = 'ffeeddccbbaa99887766554433221100';\n")
    assert crypto.get_key_mv(td) == "ffeeddccbbaa99887766554433221100"
with tempfile.TemporaryDirectory() as td:
    assert crypto.get_key_mv(td) is None
print("   OK")

print("19) Читы: heal_all / clear_states / турбо-выражения...")
expr = RpgMakerTentacle._cheat_expr("heal_all")
assert expr is not None
assert "removeAllStates" in expr and "setHp(a.mhp)" in expr
assert "setMp(a.mmp)" in expr
expr = RpgMakerTentacle._cheat_expr("clear_states")
assert expr is not None
assert "removeAllStates" in expr and "setHp" not in expr
expr = RpgMakerTentacle._cheat_expr("game_speed", value=4)
assert expr is not None and "setGameSpeed(4)" in expr
assert RpgMakerTentacle._cheat_expr("heal_all_unknown") is None
print("   OK")

print()
print("ВСЕ ТЕСТЫ RPG MAKER ПРОШЛИ")
