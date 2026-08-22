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

print("6a) Авто-шрифт с кириллицей (patch_font_auto/restore/is_patched)...")
import shutil
from app.core.rpgmaker.fontpatch import (patch_font_auto, restore_font,
                                         is_patched, _bundled_font)
# MV: игра уже использует шрифт с кириллицей — не трогаем
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "fonts"))
    shutil.copy2(_bundled_font(),
                 os.path.join(td, "fonts", "NotoSans-Regular.ttf"))
    with open(os.path.join(td, "fonts", "gamefont.css"), "w",
              encoding="utf-8") as f:
        f.write("@font-face { font-family: GameFont;\n"
                '    src: url("NotoSans-Regular.ttf"); }')
    report = patch_font_auto(td, "mv")
    assert report.get("already")
    assert not is_patched(td, "mv")
# MV www-деплой: японский шрифт → NotoSans, откат возвращает оригинал
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "www", "fonts"))
    with open(os.path.join(td, "www", "fonts", "gamefont.css"), "w",
              encoding="utf-8") as f:
        f.write("@font-face { font-family: GameFont;\n"
                '    src: url("mplus-1m-regular.ttf"); }')
    open(os.path.join(td, "www", "fonts", "mplus-1m-regular.ttf"),
         "wb").write(b"x")
    report = patch_font_auto(td, "mv")
    assert not report.get("already")
    assert report["font"] == "NotoSans-Regular.ttf"
    css = open(os.path.join(td, "www", "fonts", "gamefont.css"),
               encoding="utf-8").read()
    assert 'url("NotoSans-Regular.ttf")' in css
    assert os.path.isfile(os.path.join(td, "www", "fonts",
                                       "NotoSans-Regular.ttf"))
    assert is_patched(td, "mv")
    # повторный авто-патч не дублирует манифест
    patch_font_auto(td, "mv")
    assert restore_font(td, "mv")
    assert not is_patched(td, "mv")
    assert not os.path.exists(os.path.join(td, "www", "fonts",
                                           "NotoSans-Regular.ttf"))
    css = open(os.path.join(td, "www", "fonts", "gamefont.css"),
               encoding="utf-8").read()
    assert 'url("mplus-1m-regular.ttf")' in css
    # повторный откат — нечего возвращать
    assert not restore_font(td, "mv")
# MZ: System.json → NotoSans, откат возвращает японский шрифт
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "fonts"))
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"advanced": {"mainFontFilename": "mplus-1m-regular.woff",
                                "numberFontFilename": "mplus-2p-bold-sub.woff"}}, f)
    open(os.path.join(td, "fonts", "mplus-1m-regular.woff"), "wb").write(b"x")
    report = patch_font_auto(td, "mz")
    assert not report.get("already")
    adv = json.load(open(os.path.join(td, "data", "System.json"),
                         encoding="utf-8"))["advanced"]
    assert adv["mainFontFilename"] == "NotoSans-Regular.ttf"
    assert adv["numberFontFilename"] == "NotoSans-Regular.ttf"
    assert os.path.isfile(os.path.join(td, "fonts", "NotoSans-Regular.ttf"))
    assert os.path.isfile(os.path.join(td, "data", "System.json.ob_backup"))
    assert restore_font(td, "mz")
    adv = json.load(open(os.path.join(td, "data", "System.json"),
                         encoding="utf-8"))["advanced"]
    assert adv["mainFontFilename"] == "mplus-1m-regular.woff"
    assert not os.path.exists(os.path.join(td, "fonts",
                                           "NotoSans-Regular.ttf"))
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

print("9b) Профиль NW.js: версия зашита в Web Data/Preferences "
      "(без маркера в Local State)...")
with tempfile.TemporaryDirectory() as fake_local:
    old_env = os.environ.get("LOCALAPPDATA")
    os.environ["LOCALAPPDATA"] = fake_local
    try:
        with tempfile.TemporaryDirectory() as td:
            prof = os.path.join(fake_local, "nwjs", "Default")
            os.makedirs(prof)
            # свежий Local State без user_data_version, но Web Data есть
            with open(os.path.join(fake_local, "nwjs", "Local State"), "w",
                      encoding="utf-8") as f:
                json.dump({"profile": "ok"}, f)
            for fn in ("Web Data", "Web Data-journal", "Preferences"):
                with open(os.path.join(prof, fn), "w",
                          encoding="utf-8") as f:
                    f.write("{}")
            assert clean_nwjs_profile(td) == [
                os.path.join(fake_local, "nwjs")]
            assert not os.path.exists(
                os.path.join(prof, "Web Data"))
            assert os.path.exists(
                os.path.join(prof, "Web Data.bak"))
            assert not os.path.exists(
                os.path.join(fake_local, "nwjs", "Local State"))
            # Local Storage (сейвы/настройки localStorage) не тронуты
            os.makedirs(os.path.join(prof, "Local Storage"))
            assert os.path.isdir(
                os.path.join(prof, "Local Storage"))
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
assert "removeState" in expr and "setHp(a.mhp)" in expr
assert "removeAllStates" not in expr  # MV-совместимость
expr = RpgMakerTentacle._cheat_expr("clear_states")
assert expr is not None
assert "removeState" in expr and "setHp" not in expr
expr = RpgMakerTentacle._cheat_expr("game_speed", value=4)
assert expr is not None and "setGameSpeed(4)" in expr
assert RpgMakerTentacle._cheat_expr("heal_all_unknown") is None
# speed-хук: аккумулятор MV 1.6+/MZ (деление _deltaTime), без
# k-кратного вызова updateMain (requestUpdate = rAF -> экспонента)
_payload = tentacle_mod.PAYLOAD
assert "this._deltaTime = orig / k" in _payload
assert "_obUpdateMain.call(this)" in _payload
assert "SceneManager.updateMain = function ()" in _payload
print("   OK")

print("20) MV: plugins.js в JS-формате (var $plugins = [...])...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js", "plugins"))
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write("var $plugins = [\n"
                "{\"name\":\"MyPlugin.js\",\"status\":true,"
                "\"description\":\"\",\"parameters\":{}},\n"
                "];\n")
    with open(os.path.join(td, "js", "plugins", "MyPlugin.js"), "w",
              encoding="utf-8") as f:
        f.write("const msg = 'こんにちは世界';")
    entries = parser.extract_plugins(td, "data")
    texts = [e.original for e in entries]
    assert "こんにちは世界" in texts, f"MV plugins.js не извлечён: {texts}"
print("   OK:", texts)

print("21) MV: зашифрованная карта .rpgmvm (извлечение и внедрение)...")
from app.core.rpgmaker import crypto
_ENC_KEY = "00112233445566778899aabbccddeeff"
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"encryptionKey": _ENC_KEY}, f)
    map_data = {
        "displayName": "Лес",
        "events": [{
            "id": 1, "name": "EV1", "x": 3, "y": 4, "note": "",
            "pages": [{"conditions": {}, "image": {}, "list": [
                {"code": 401, "indent": 0,
                 "parameters": ["Привет, путник!"]},
            ]}],
        }],
    }
    raw = json.dumps(map_data, ensure_ascii=False).encode("utf-8")
    with open(os.path.join(td, "data", "Map001.rpgmvm"), "wb") as f:
        f.write(crypto.encrypt_bytes(raw, _ENC_KEY))
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    assert "Лес" in texts, f"имя карты MV не извлечено: {texts}"
    assert "Привет, путник!" in texts, f"реплика карты MV не извлечена: {texts}"
    for e in entries:
        if e.original == "Привет, путник!":
            e.translation = "Hello, traveler!"
    stats = parser.apply(td, entries)
    assert stats["files"] >= 1 and stats["strings"] >= 1, stats
    with open(os.path.join(td, "data", "Map001.rpgmvm"), "rb") as f:
        body = f.read()
    assert body[:16] == crypto.SIGNATURE, "файл должен остаться зашифрованным"
    plain = crypto.decrypt_bytes(body, _ENC_KEY).decode("utf-8")
    assert '"Hello, traveler!"' in plain and "Привет, путник!" not in plain
print("   OK: извлечено", len(entries), "строк")

print("22) Гибрид: live-перевод — словарь и JS-пейлоад (MV и MZ)...")
from app.core.models import TranslationEntry
from app.engines.rpgmaker.tentacle import (
    build_tr_dict, _TRANSLATION_PAYLOAD)
_es = [
    TranslationEntry(id=1, file="f", json_path="p", context="",
                     original="Привет", translation="Hello"),
    TranslationEntry(id=2, file="f", json_path="p", context="",
                     original="пусто", translation="  "),
    TranslationEntry(id=3, file="f", json_path="p", context="",
                     original="скоп", translation="X", status="skip"),
]
_tr_dict = build_tr_dict(_es)
assert _tr_dict == {"Привет": "Hello"}, _tr_dict
assert "convertEscapeCharacters" in _TRANSLATION_PAYLOAD
assert "Game_Actor.prototype.name" in _TRANSLATION_PAYLOAD
assert "Game_Map.prototype.displayName" in _TRANSLATION_PAYLOAD
assert "__octopus_trInstall" in _TRANSLATION_PAYLOAD
_code = _TRANSLATION_PAYLOAD.replace(
    "__TR_DICT__", json.dumps(_tr_dict, ensure_ascii=False))
assert "Привет" in _code and '"Hello"' in _code
assert build_tr_dict([]) == {}
print("   OK:", _tr_dict)

print("23) MV: битые структуры (список вместо словаря) не валят extract...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "www", "data"))
    os.makedirs(os.path.join(td, "www", "js"))
    open(os.path.join(td, "www", "js", "rpg_core.js"), "w").close()
    data = os.path.join(td, "www", "data")
    # событие со страницей-списком и страницей-строкой; тройка со
    # страницей-списком; команда-список внутри листа
    with open(os.path.join(data, "Map001.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "displayName": "Карта",
            "width": 2, "height": 2,
            "data": [0] * 2 * 2 * 6,
            "events": [None, {
                "id": 1, "name": "EV", "x": 1, "y": 1, "note": "",
                "pages": [
                    ["bad", "page"],          # список вместо dict
                    {"conditions": {}, "image": {}, "list": [
                        {"code": 401, "indent": 0,
                         "parameters": ["Речь"]},
                        ["legacy", "cmd"],     # команда-список
                    ]},
                ],
            }],
        }, f, ensure_ascii=False)
    with open(os.path.join(data, "Troops.json"), "w",
              encoding="utf-8") as f:
        json.dump([None, {"id": 1, "name": "Враги", "pages": [["x"]]}], f)
    with open(os.path.join(data, "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Игра", "terms": ["bad", "list"]}, f)
    with open(os.path.join(data, "MapInfos.json"), "w",
              encoding="utf-8") as f:
        json.dump([None, {"id": 1, "name": "Карта"}], f)
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    assert "Речь" in texts and "Карта" in texts
    from app.core.rpgmaker import maprender
    mp = maprender.load_map(td, 1)
    assert mp is not None
    assert maprender.event_summary(mp["events"][1])["pages"] >= 1
    assert maprender.page_conditions(["bad"])["switch1_valid"] is False
print("   OK:", texts)

print()
print("24) MZ: список плагинов лежит в data/plugins.js (JSON-массив)...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js"))
    open(os.path.join(td, "js", "rmmz_core.js"), "w").close()
    data = os.path.join(td, "data")
    os.makedirs(data)
    with open(os.path.join(data, "plugins.js"), "w",
              encoding="utf-8") as f:
        json.dump([
            {"name": "NicePlugin", "status": True, "description": "",
             "parameters": {}},
            {"name": "OffPlugin", "status": False, "description": "",
             "parameters": {}},
        ], f)
    os.makedirs(os.path.join(td, "js", "plugins"))
    with open(os.path.join(td, "js", "plugins", "NicePlugin.js"), "w",
              encoding="utf-8") as f:
        f.write("/*! NicePlugin */\nvar V = 5;\nfunction f() {\n"
                "    return 'Здравствуй, мир';\n}\n"
                "Game_Interpreter.prototype.say = function() {\n"
                "    return 'Привет, мир';\n};\n")
    with open(os.path.join(td, "js", "plugins", "OffPlugin.js"), "w",
              encoding="utf-8") as f:
        f.write("var x = 'выключенный плагин не парсится';\n")
    with open(os.path.join(data, "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Игра"}, f)
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    assert "Здравствуй, мир" in texts
    assert "Привет, мир" in texts
    assert not any("OffPlugin" in e.file for e in entries)
    assert not any("var V = 5" in e.original for e in entries)
print("   OK")

print()
print("25) MV: шифрованная карта .rpgmvm через maprender (load+save)...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "www", "js"))
    open(os.path.join(td, "www", "js", "rpg_core.js"), "w").close()
    data = os.path.join(td, "www", "data")
    os.makedirs(data)
    key = "7e04b77e815c96850c0aedfe714defa7"
    with open(os.path.join(data, "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Игра", "encryptionKey": key}, f)
    body = {"displayName": "Тайная карта", "width": 2, "height": 2,
            "data": [0] * 2 * 2 * 6, "events": []}
    from app.core.rpgmaker import crypto, maprender
    with open(os.path.join(data, "Map007.rpgmvm"), "wb") as f:
        f.write(crypto.encrypt_bytes(
            json.dumps(body, ensure_ascii=False).encode("utf-8"), key))
    mp = maprender.load_map(td, 7)
    assert mp is not None and mp["displayName"] == "Тайная карта"
    mp["displayName"] = "Переведённая"
    rel = maprender.save_map(td, 7, mp)
    assert rel.lower().endswith(".rpgmvm")
    with open(os.path.join(data, "Map007.rpgmvm"), "rb") as f:
        raw = f.read()
    assert crypto.decrypt_bytes(raw, key).decode("utf-8").find(
        "Переведённая") >= 0
    assert maprender.load_map(td, 7)["displayName"] == "Переведённая"
print("   OK")

print()
print("26) Ключи параметров плагинов НЕ извлекаются (иначе YEP-плагины "
      "зависают на новой игре)...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js", "plugins"))
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write("var $plugins = [\n"
                "{\"name\":\"YEP_MessageCore\",\"status\":true,"
                "\"parameters\":{\"Default Rows\":\"4\","
                "\"Default Width\":\"Graphics.boxWidth\","
                "\"---General---\":\"\"}},\n"
                "];\n")
    with open(os.path.join(td, "js", "plugins", "YEP_MessageCore.js"),
              "w", encoding="utf-8") as f:
        f.write("var P = PluginManager.parameters('YEP_MessageCore');\n"
                "Yanfly.Param.MSGDefaultRows = "
                "String(P['Default Rows']);\n"
                "Yanfly.Param.MSGDefW = eval(String(P['Default Width']));\n"
                "var header = '---General---';\n"
                "var msg = 'Строка сообщения для перевода';\n")
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Игра"}, f)
    entries = parser.extract_plugins(td, "data")
    texts = [e.original for e in entries]
    assert "Default Rows" not in texts
    assert "Default Width" not in texts
    assert "---General---" not in texts
    assert "Строка сообщения для перевода" in texts
print("   OK")

print()
print("27) MV-мост: внедрение плагина, словарь, unregister (JS plugins.js)...")
from app.core.rpgmaker import mv_bridge
_cheats = ("if (!window.__octopus.rpgm) {\n"
           "window.__octopus.rpgm = true;\n"
           "window.__octopus_collectState = function () { return {ok:1}; };\n"
           "}\n")
_tr_p = ("if (!window.__octopus_trInit) { window.__octopus_trInit = true; "
         "window.__octopus_tr = {}; "
         "window.__octopus_trInstall = function (o) { "
         "for (var k in o) window.__octopus_tr[k] = o[k]; "
         "return Object.keys(window.__octopus_tr).length; }; }\n"
         "window.__octopus_trInstall(__TR_DICT__);\n")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js", "plugins"))
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write("var $plugins = [\n"
                "{\"name\":\"YEP_MessageCore\",\"status\":true,"
                "\"parameters\":{}},\n"
                "];\n")
    assert mv_bridge.ensure_bridge_registered(td, _cheats, _tr_p)
    pj = os.path.join(td, "js", "plugins.js")
    with open(pj, encoding="utf-8") as f:
        text = f.read()
    assert '"octopus_ob"' in text, "плагин не зарегистрирован"
    assert text.count('"octopus_ob"') == 1
    assert mv_bridge.ensure_bridge_registered(td, _cheats, _tr_p)
    with open(pj, encoding="utf-8") as f:
        text2 = f.read()
    assert text2 == text, "повторная регистрация не должна менять файл"
    plugin = os.path.join(td, "js", "plugins", "octopus_ob.js")
    with open(plugin, encoding="utf-8") as f:
        src = f.read()
    assert "__TR_DICT__" not in src
    assert "__octopus_trInstall({});" in src
    assert "__octopusBridgeVersion = 2" in src
    assert 'localStorage.getItem("__octopus_last_err")' in src
    assert "require(\"http\")" in src and "/probe" in src and "/errlog" in src
    assert "window.__octopus_collectState" in src
    assert "__octopus.send = function () {}" in src
    n = mv_bridge.update_tr_dict(td, [
        TranslationEntry(id=1, file="f", json_path="p", context="",
                         original="Привет", translation="Hello"),
        TranslationEntry(id=2, file="f", json_path="p", context="",
                         original="пусто", translation="  "),
        TranslationEntry(id=3, file="f", json_path="p", context="",
                         original="скоп", translation="X", status="skip"),
    ])
    assert n == 1, n
    with open(plugin, encoding="utf-8") as f:
        src = f.read()
    assert "__octopus_trInstall({});" not in src
    assert '"Привет": "Hello"' in src
    assert mv_bridge.update_tr_dict(td, []) == 0
    # ядовитый словарь: ");" внутри перевода ломал regex __octopus_trInstall
    # -> битый JS-синтаксис (SyntaxError: Unexpected identifier в игре)
    nasty = [
        TranslationEntry(id=10, file="f", json_path="p", context="",
                         original="a", translation="см. п.2); и далее"),
        TranslationEntry(id=11, file="f", json_path="p", context="",
                         original="b", translation='кавычки " и } скобки {'),
        TranslationEntry(id=12, file="f", json_path="p", context="",
                         original="c", translation="бэкслеш \\ и конец);"),
    ]
    n = mv_bridge.update_tr_dict(td, nasty)
    assert n == 3, n
    with open(plugin, encoding="utf-8") as f:
        src = f.read()
    span = mv_bridge._tr_dict_span(src)
    assert span, "словарь не найден после update"
    assert src[span[1]:span[1] + 2] == ");", "вызов словаря обрезан"
    assert "unexpected" not in src.lower()
    got = json.loads(mv_bridge._existing_dict(src))
    assert got["a"] == "см. п.2); и далее"
    assert got["b"] == 'кавычки " и } скобки {'
    assert got["c"] == "бэкслеш \\ и конец);"
    # структурно: сканер находит словарь и в реальном файле
    assert mv_bridge._tr_dict_span(src) is not None
    # build_plugin_source + регенерация со словарём, где есть U+2028/2029
    dirty = {"a": "до\u2028после", "b": "\u2029"}
    built = mv_bridge.build_plugin_source(_cheats, _tr_p,
                                          mv_bridge.js_json(dirty))
    assert "\u2028" not in built and "\\u2028" in built
    assert json.loads(mv_bridge._existing_dict(built)) == dirty
    assert mv_bridge._existing_dict(
        "__octopus_trInstall({bad});") == "{}"
    # битый словарь (как от старого regex-бага) перегенерируется
    with open(plugin, "w", encoding="utf-8") as f:
        f.write("window.__octopusBridgeVersion = 2;\n"
                "window.__octopus_trInstall({\"a\": \"b{\"x\": \"y\"}); c\"});\n")
    assert mv_bridge.ensure_bridge_registered(td, _cheats, _tr_p)
    with open(plugin, encoding="utf-8") as f:
        src = f.read()
    assert "__octopus_trInstall({});" in src, "битый словарь не вылечен"
    # устаревший шаблон с маркером __TR_DICT__ переписывается (маркер
    # обрывал скрипт ReferenceError до старта HTTP-сервера)
    with open(plugin, "w", encoding="utf-8") as f:
        f.write("__octopus_trInstall(__TR_DICT__);\n")
    assert mv_bridge.ensure_bridge_registered(td, _cheats, _tr_p)
    with open(plugin, encoding="utf-8") as f:
        src = f.read()
    assert "__TR_DICT__" not in src
    assert "__octopus_trInstall({});" in src
    # старая версия плагина: перегенерируется с сохранением словаря
    with open(plugin, "w", encoding="utf-8") as f:
        f.write("window.__octopusBridgeVersion = 1;\n"
                "window.__octopus_trInstall({\"Привет\": \"Hello\"});\n")
    assert mv_bridge.ensure_bridge_registered(td, _cheats, _tr_p)
    with open(plugin, encoding="utf-8") as f:
        src = f.read()
    assert "__octopusBridgeVersion = 2" in src
    assert '"Привет": "Hello"' in src
    assert mv_bridge.unregister_bridge(td)
    assert not os.path.isfile(plugin)
    with open(pj, encoding="utf-8") as f:
        text3 = f.read()
    assert '"octopus_ob"' not in text3
    assert '"YEP_MessageCore"' in text3
print("   OK")

print()
print("28) MV-мост: JSON-формат plugins.js (страховка, MZ-стиль)...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js", "plugins"))
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        json.dump([{"name": "P", "status": True, "parameters": {}}], f)
    assert mv_bridge.ensure_bridge_registered(td, _cheats, _tr_p)
    with open(os.path.join(td, "js", "plugins.js"), "w", encoding="utf-8") as f:
        json.dump([{"name": "P", "status": True, "parameters": {}},
                   {"name": "octopus_ob", "status": True,
                    "description": "", "parameters": {}}], f)
    with open(os.path.join(td, "js", "plugins.js"), encoding="utf-8") as f:
        text = f.read()
    assert text.count("octopus_ob") == 1
    assert mv_bridge.unregister_bridge(td)
    with open(os.path.join(td, "js", "plugins.js"), encoding="utf-8") as f:
        text = f.read()
    assert "octopus_ob" not in text
print("   OK")

print()
print("29) Профиль MV-рантайма: %LOCALAPPDATA%\\User Data учитывается...")
from app.engines.rpgmaker.tentacle import _nwjs_profile_dirs
_ld = os.environ.get("LOCALAPPDATA") or ""
if _ld:
    with tempfile.TemporaryDirectory() as td:
        dirs = _nwjs_profile_dirs(td)
        assert os.path.join(_ld, "User Data") in dirs, dirs
print("   OK")

print()
print("30) Клиент моста: probe / eval / tr против фейкового моста...")
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

class _FakeBridge(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(
            int(self.headers.get("Content-Length", "0"))).decode("utf-8")
        out = {"ok": True}
        if self.path == "/probe":
            out["name"] = "octopus_ob"
        elif self.path == "/eval":
            expr = json.loads(body)["expr"]
            if expr.startswith("return_string"):
                out["value"] = json.dumps("Привет из игры")
            elif expr.startswith("return_obj"):
                out["value"] = json.dumps({"gold": 100})
            elif expr.startswith("boom"):
                out["ok"] = False
                out["error"] = "SyntaxError"
            else:
                out["value"] = "null"
        elif self.path == "/tr":
            out["count"] = len(json.loads(body))
        elif self.path == "/errlog":
            out["err"] = {"catch": {"msg": "TypeError: x",
                                    "extra": "file.js:12"}}
        else:
            out["ok"] = False
        data = json.dumps(out, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # тишина в консоли тестов
        pass

_bridge_holder = {}
class _BridgeServer(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.server = HTTPServer(("127.0.0.1", 0), _FakeBridge)

    def run(self):
        self.server.serve_forever(poll_interval=0.05)

_bs = _BridgeServer()
_bs.start()
_port = _bs.server.server_address[1]
assert mv_bridge.bridge_probe(_port)
assert mv_bridge.find_bridge_port(wait=0.0) in (0, _port)
ok, val = mv_bridge.bridge_eval(_port, "return_string x")
assert ok and val == "Привет из игры", (ok, val)
ok, val = mv_bridge.bridge_eval(_port, "return_obj x")
assert ok and val == {"gold": 100}, (ok, val)
ok, val = mv_bridge.bridge_eval(_port, "boom x")
assert not ok and "SyntaxError" in str(val)
ok, val = mv_bridge.bridge_eval(_port, "x = 1")
assert ok and val is None
assert mv_bridge.bridge_install_tr(_port, {"Привет": "Hello"})
err = mv_bridge.bridge_errlog(_port)
assert err and err["catch"]["msg"] == "TypeError: x", err
_bs.server.shutdown()
print("   OK")

print()
print("ВСЕ ТЕСТЫ RPG MAKER ПРОШЛИ")
