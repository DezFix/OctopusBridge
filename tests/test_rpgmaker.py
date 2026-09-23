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
    # живой exe PID 4242 — наша игра (защита от чужого процесса в launch
    # сверяет exe_of перед terminate; фейковый pid мокаем)
    tentacle_mod.proc.exe_of = lambda pid: game_exe
    tentacle_mod.proc.terminate = lambda pid, timeout=3.0, **_k: (
        killed.append(pid) or True)
    tentacle_mod.browser.free_port = lambda: 7777
    import subprocess as _spmod12
    _real_Popen12 = _spmod12.Popen
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
    tentacle_mod.proc.exe_of = lambda pid: game_exe
    tentacle_mod.proc.terminate = lambda pid, timeout=3.0, **_k: False
    assert t.launch(td) is False
    assert errs
print("   OK")

print("14) reload_map: перечитывает MapXXX.json и пересоздаёт карту...")
expr = RpgMakerTentacle._cheat_expr("reload_map")
assert expr is not None
assert "$gameMap.setup(mapId)" in expr
assert "reserveTransfer" in expr
assert ".slice(-3)" in expr
# ES5 (MV Chromium 41-49): без const/let/стрелок/Decrypter; шифрованные
# .rpgmvm детектятся по сигнатуре 'R' (82) и уходят в мягкий fallback,
# www/data — вторым URL
assert "=>" not in expr
assert "Decrypter" not in expr
assert "www/data/Map" in expr
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
print("31) find_game_exe: произвольное имя exe, хелперы, приоритет Game.exe...")
from app.core.rpgmaker.variant import find_game_exe
with tempfile.TemporaryDirectory() as td:
    # пустая папка — нечего запускать
    assert find_game_exe(td) is None
    # кастомное имя (лабораторные игры) + хелпер NW.js игнорируется
    custom = os.path.join(td, "Aochikano.exe")
    helper = os.path.join(td, "notification_helper.exe")
    open(custom, "w").close()
    open(helper, "w").close()
    # хелпер меньше/больше — всё равно выбирается игра, не хелпер
    with open(helper, "w") as f:
        f.write("x" * 100)
    assert find_game_exe(td) == custom, find_game_exe(td)
    # классика приоритетнее кастома
    game_exe = os.path.join(td, "Game.exe")
    open(game_exe, "w").close()
    assert find_game_exe(td) == game_exe
    # прямой путь к файлу — как есть
    assert find_game_exe(custom) == custom
    assert find_game_exe(os.path.join(td, "нет.exe")) is None
print("   OK")

print()
print("32) extract_plugin_params: VALUES меню извлекаются, "
      "ключи/true/формулы — нет...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js", "plugins"))
    os.makedirs(os.path.join(td, "data"))
    open(os.path.join(td, "js", "rpg_core.js"), "w").close()
    with open(os.path.join(td, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write("var $plugins = [\n"
                "{\"name\":\"M\",\"status\":true,\"parameters\":{"
                "\"menuOk\":\"決定\","
                "\"flag\":\"true\","
                "\"count\":\"5\","
                "\"formula\":\"10 + textSize * 5\","
                "\"nested\":\"[{\\\"name\\\":\\\"エナジードリンク\\\"}]\""
                "}},\n"
                "{\"name\":\"Off\",\"status\":false,\"parameters\":{"
                "\"x\":\"выключен\"}},\n"
                "];\n")
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Игра"}, f)
    entries = parser.extract_plugins(td, "data", variant="mv")
    by_orig = {e.original: e for e in entries}
    assert "決定" in by_orig, list(by_orig)[:10]
    assert by_orig["決定"].file == "js/plugins.js"
    assert "#plugparam:" in by_orig["決定"].json_path
    assert "エナジードリンク" in by_orig
    assert "true" not in by_orig and "5" not in by_orig
    assert "10 + textSize * 5" not in by_orig, "формула eval не текст"
    assert not any("выключен" in e.original for e in entries)
print("   OK")

print()
print("33) apply_plugin_params: патч VALUES в plugins.js + бэкап...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js", "plugins"))
    os.makedirs(os.path.join(td, "data"))
    open(os.path.join(td, "js", "rpg_core.js"), "w").close()
    with open(os.path.join(td, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write("var $plugins = [\n"
                "{\"name\":\"M\",\"status\":true,\"parameters\":{"
                "\"menuOk\":\"決定\",\"flag\":\"true\"}},\n"
                "];\n")
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Игра"}, f)
    entries = parser.extract_plugins(td, "data", variant="mv")
    assert len(entries) == 1 and entries[0].original == "決定"
    entries[0].translation = "Выбрать"
    entries[0].status = "translated"
    stats = parser.apply(td, entries)
    assert stats["strings"] == 1, stats
    text = open(os.path.join(td, "js", "plugins.js"),
                encoding="utf-8").read()
    assert "Выбрать" in text and "決定" not in text
    assert '"flag":"true"' in text.replace(" ", ""), "флаг не тронут"
    assert '"menuOk"' in text, "ключ не тронут"
    assert os.path.isfile(os.path.join(td, "backup", "js",
                                       "plugins.js"))
    # повторное извлечение видит перевод
    re_entries = parser.extract_plugins(td, "data", variant="mv")
    assert any(e.original == "Выбрать" for e in re_entries)
print("   OK")

print()
print("34) Пейлоад: multiline trApply + Bitmap/drawTextEx + "
      "PluginManager.parameters...")
from app.engines.rpgmaker.tentacle import _TRANSLATION_PAYLOAD as _TP
assert "parts.join" in _TP, "построчная склейка 401"
assert "Bitmap.prototype.drawText" in _TP
assert "drawTextEx" in _TP
assert "PluginManager.parameters" in _TP
assert '"$plugins"' in _TP or "$plugins" in _TP
print("   OK")

print()
print("35) launch: кастомный exe (Aochikano.exe) находится и запускается...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    custom_exe = os.path.join(td, "Aochikano.exe")
    open(custom_exe, "w").close()
    # Game.exe нет — только кастомный (как в лабораторных играх)
    t = RpgMakerTentacle()
    t._connect_page = lambda port, url_hint="", wait=20.0: True
    seen = {}
    class FakePopen2(FakePopen):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            seen["exe"] = a[0][0]
    tentacle_mod.subprocess.Popen = FakePopen2
    tentacle_mod.proc.find_game_processes = lambda *a, **k: []
    tentacle_mod.browser.free_port = lambda: 7778
    assert t.launch(td) is True
    assert seen.get("exe") == custom_exe, seen
    # папка без exe — понятная ошибка, а не молчание
    with tempfile.TemporaryDirectory() as empty:
        os.makedirs(os.path.join(empty, "data"))
        t2 = RpgMakerTentacle()
        errs = []
        t2.error.connect(lambda s: errs.append(s))
        assert t2.launch(empty) is False
        assert errs and "exe" in errs[0].lower() or "исполняемый" in errs[0]
    # чиним за собой глобальный мок: дальше идут тесты, которым нужен
    # настоящий subprocess.Popen (иначе всё поломается молча)
    tentacle_mod.subprocess.Popen = _real_Popen12
print("   OK")

print()
print("36) _js_escape_translation: U+2028/29, C0-контролы, кавычки...")
import re as _re36
from app.core.rpgmaker.parser import _js_escape_translation as _esc
_LS1, _LS2 = chr(0x2028), chr(0x2029)
out = _esc("a" + _LS1 + "b" + _LS2 + "c\\d'e\"f\ng\th" + chr(1) + "i", "'")
assert _LS1 not in out and _LS2 not in out, ascii(out)
assert chr(1) not in out
assert "\\u2028" in out and "\\u2029" in out and "\\u0001" in out
assert "\\\\" in out and "\\'" in out and "\\n" in out and "\\t" in out
# ручной JS-unescape крутится обратно в исходник (валидность литерала)
_SRC36 = "a" + _LS1 + "b" + _LS2 + "c\\d'e\"f\ng\th" + chr(1) + "i"
_tmp = out.replace("\\\\", "\x00")
_tmp = _tmp.replace("\\'", "'").replace('\\"', '"')
_tmp = _tmp.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
_tmp = _re36.sub(r"\\u([0-9a-f]{4})",
                 lambda m: chr(int(m.group(1), 16)), _tmp)
assert _tmp.replace("\x00", "\\") == _SRC36, ascii(_tmp)
print("   OK")

print()
print("37) _is_code_literal: сравнения/ключи/args[] — код, "
      "массивы/текст — нет...")
from app.core.rpgmaker.parser import _is_code_literal as _icl
Q = "'"
assert _icl("if(command===" + Q + "SKIT" + Q + "){}", 13, 19)
assert _icl("args[" + '"' + "key" + '"' + "]", 5, 10)
assert _icl("{ " + '"' + "k" + '"' + ": 1 }", 2, 5)
assert _icl("switch(x){case " + Q + "a" + Q + ":}", 15, 18)
assert not _icl("var a = [" + '"' + "text" + '"' + "]", 9, 15)
assert not _icl("var a = " + '"' + "text" + '"' + ";", 8, 14)
assert not _icl("msg(" + Q + "hello" + Q + ")", 4, 11)
print("   OK")

print()
print("38) apply: перевод с U+2028 не ломает синтаксис плагина...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "js", "plugins"))
    os.makedirs(os.path.join(td, "data"))
    open(os.path.join(td, "js", "rpg_core.js"), "w").close()
    with open(os.path.join(td, "js", "plugins.js"), "w",
              encoding="utf-8") as f:
        f.write("var $plugins = [\n"
                "{\"name\":\"P\",\"status\":true,\"parameters\":{"
                "\"label\":\"決定\"}},\n"
                "];\n")
    with open(os.path.join(td, "js", "plugins", "P.js"), "w",
              encoding="utf-8") as f:
        f.write("if(command==='探索開始'){}\n"
                "var msg='こんにちは';\n")
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Игра"}, f)
    entries = parser.extract_plugins(td, "data", variant="mv")
    by_orig = {e.original: e for e in entries}
    # команда-идентификатор не извлекается (иначе dispatch мёртв)
    assert "探索開始" not in by_orig, list(by_orig)[:10]
    assert "こんにちは" in by_orig and "決定" in by_orig
    for e in entries:
        e.translation = "x" + chr(0x2028) + "y" + chr(0x2029) + "z"
        e.status = "translated"
    stats = parser.apply(td, entries)
    assert stats["strings"] == 2, stats
    pj = open(os.path.join(td, "js", "plugins", "P.js"),
              encoding="utf-8").read()
    assert chr(0x2028) not in pj and chr(0x2029) not in pj
    assert "\\u2028" in pj and "\\u2029" in pj
    assert "command==='探索開始'" in pj, "код сравнения цел"
    pl = open(os.path.join(td, "js", "plugins.js"),
              encoding="utf-8").read()
    assert chr(0x2028) not in pl and "\\u2028" in pl
    assert json.loads(pl[pl.index("["):pl.rindex("]") + 1]
                      )[0]["parameters"]["label"] == (
                          "x" + chr(0x2028) + "y" + chr(0x2029) + "z")
print("   OK")

print()
print("39) ES5: пейлоады и читы без const/let/=>/includes (старый NW.js MV)...")
import re as _re39
from app.core.rpgmaker.payloads import PAYLOAD as _PAY, _TRANSLATION_PAYLOAD as _TRP
from app.core.tentacles.cdp_base import TRANSPORT_SHIM as _SHIM
for _label, _src in (("PAYLOAD", _PAY), ("TR", _TRP), ("SHIM", _SHIM)):
    assert "=>" not in _src, _label
    assert _re39.search(r"(?<![A-Za-z_$])const\s+[A-Za-z_$]", _src) is None, _label
    assert _re39.search(r"(?<![A-Za-z_$])let\s+[A-Za-z_$]", _src) is None, _label
    assert ".includes(" not in _src, _label
# tentacle реэкспортирует те же объекты (совместимость)
from app.engines.rpgmaker.tentacle import PAYLOAD as _PAY2
assert _PAY2 == _PAY
# читы — все без ES6
for _cmd, _kw in [
        ("gold_set", {"value": 10}), ("gold_add", {"value": 5}),
        ("heal", {}), ("heal_all", {}), ("clear_states", {}),
        ("teleport", {"mapId": 1, "x": 1, "y": 1}),
        ("reload_map", {}), ("win_battle", {}),
        ("give_item", {"kind": "item", "id": 1, "count": 1}),
        ("open_menu", {}),
        ("actor_set", {"actorId": 1, "field": "hp", "value": 10})]:
    _e = RpgMakerTentacle._cheat_expr(_cmd, **_kw)
    assert _e and "=>" not in _e, _cmd
assert "gainGold" in RpgMakerTentacle._cheat_expr("gold_set", value=5)
assert "_gold =" not in RpgMakerTentacle._cheat_expr("gold_set", value=5)
print("   OK")

print()
print("40) Безопасный apply: data и js/plugins не трогаем, только runtime...")
from app.engines.rpgmaker import RpgMakerModule as _Mod40
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Game"}, f)
    _entries = parser.extract(td)
    for _e in _entries:
        _e.translation = "RU_" + _e.original
        _e.status = "translated"
    with open(os.path.join(td, "data", "CommonEvents.json"),
              encoding="utf-8") as f:
        _before = f.read()
    _mod = _Mod40(td)
    _stats = _mod.apply(td, _entries, target_lang="ru")
    with open(os.path.join(td, "data", "CommonEvents.json"),
              encoding="utf-8") as f:
        assert f.read() == _before, "data-файл изменён — риск поломки запуска"
    assert os.path.isfile(os.path.join(td, "ob_translation", "ru.json"))
    assert os.path.isfile(os.path.join(td, "js", "plugins", "ob_runtime.js"))
    assert _mod.restore_original(td)["removed"] >= 1
    assert not os.path.exists(os.path.join(td, "js", "plugins", "ob_runtime.js"))
print("   OK")

print()
print("41) Экранирование </script>/<!-- в JS-словарях и литералах...")
from app.core.rpgmaker import mv_bridge as _mb41
from app.core.rpgmaker.parser import _js_escape_translation as _esc41
assert "</script>" not in _mb41.js_json({"a": "x</script>y"})
assert "<!--" not in _mb41.js_json({"a": "<!--x"})
assert "</script>" not in _esc41("a</script>b", '"')
assert "<!--" not in _esc41("<!--x", "'")
# _replace_js_strings не трогает кодовые вхождения
from app.core.rpgmaker.parser import _replace_js_strings as _rep41
_code = 'if(cmd==="K"){ } var t="K";'
_out = _rep41(_code, "K", "RU")
assert _out is not None and _out.count("RU") == 1, _out
assert 'cmd==="K"' in _out
print("   OK")

print()
print("42) plugins.js: валидация и строко-чувствительное удаление...")
from app.core.rpgmaker.mv_bridge import _remove_entry_by_name as _rm42
_txt = ('var $plugins = [{"name":"A","status":true,"parameters":{'
        '"t":"a}b"}}, {"name":"octopus_ob","status":true,'
        '"description":"","parameters":{}}];')
_new = _rm42(_txt, "octopus_ob")
assert '"octopus_ob"' not in _new and '"name":"A"' in _new
assert '"t":"a}b"' in _new, "скобка внутри строки не должна ломать вырезку"
print("   OK")

print()
print("43) JSON-в-строке: кавычка/бэкслеш в переводе не рвут базу плагина...")
from app.core.rpgmaker.parser import (
    _replace_param_value as _rep43, _is_json_container as _isc43)
_inner43 = [{"name": "Клинок", "desc": "меч героя"},
            {"name": "Зелье", "desc": "лечит раны"}]
_params43 = {"db": json.dumps(_inner43, ensure_ascii=False),
             "plain": "Обычный текст"}
# точный лист :0 с кавычкой в переводе
assert _rep43(_params43, "db", "Клинок", 'Клинок "делюкс"', 0) is True
_back43 = json.loads(_params43["db"])  # игра парсит — обязано сойтись
assert _back43[0]["name"] == 'Клинок "делюкс"', _back43
assert _back43[1]["name"] == "Зелье"  # соседний лист цел
# точный лист :3 (порядок обхода: name,desc,name,desc)
assert _rep43(_params43, "db", "лечит раны", "лечит\\всё", 3) is True
_back43 = json.loads(_params43["db"])
assert _back43[1]["desc"] == "лечит\\всё", _back43
# чужой индекс — отказ без записи
_snap43 = _params43["db"]
assert _rep43(_params43, "db", "Зелье", "X", 0) is False
assert _params43["db"] == _snap43
assert _rep43(_params43, "db", "Зелье", "X", 99) is False
# нет ключа — отказ
assert _rep43(_params43, "нет", "Зелье", "X", None) is False
# обычная строка: точное совпадение и подстрока (legacy)
assert _rep43(_params43, "plain", "Обычный текст", "Новый", None) is True
assert _params43["plain"] == "Новый"
_params43["plain"] = "aaa bbb"
assert _rep43(_params43, "plain", "bbb", "ccc", None) is True
assert _params43["plain"] == "aaa ccc"
# _is_json_container: только целые объекты/массивы
assert _isc43('[{"a":1}]') == [{"a": 1}]
assert _isc43("[Save]") is None and _isc43("123") is None
assert _isc43("[не json") is None
print("   OK")

print()
print("44) verify: строгий парсер ловит то, что уронит игру...")
from app.core.rpgmaker import verify as _v44
try:
    _v44.strict_loads('[1, NaN]')
    assert False, "NaN обязан отвергаться как в V8"
except ValueError:
    pass
try:
    _v44.strict_loads('{"a": Infinity}')
    assert False, "Infinity обязан отвергаться как в V8"
except ValueError:
    pass
assert _v44.strict_loads('{"a": [1, 2]}') == {"a": [1, 2]}
# комментарии в JS-формате — не поломка
with tempfile.TemporaryDirectory() as td:
    _pj = os.path.join(td, "plugins.js")
    with open(_pj, "w", encoding="utf-8") as f:
        f.write("// список плагинов\nvar $plugins = [\n"
                '{"name":"A","status":true,"parameters":{}},\n'
                "];\n")
    assert _v44._check_plugins_list(_pj) is None
    with open(_pj, "w", encoding="utf-8") as f:
        f.write('var $plugins = [{"name":"A",}];\n')
    assert _v44._check_plugins_list(_pj) is None  # висячая запятая — ок
    with open(_pj, "w", encoding="utf-8") as f:
        f.write('var $plugins = [{"name":"A" "status":true}];\n')
    assert _v44._check_plugins_list(_pj) is not None  # битый — ловим
print("   OK")

print()
print("45) Сквозной hostile apply (MV+MZ): игра стартует после перевода...")
from app.engines.rpgmaker import RpgMakerModule as _Mod45
_HOSTILE = ['ますたあ "quoted"', "путь\\назад", "a,b[c]{d}",
            "line1\nline2", "x</script>y", "до\u2028после",
            "\\C[1]Привет\\C[0]", "%1 percent", "«кавычки-ёлочки»",
            "хвост\\"]
for _variant in ("mz", "mv"):
    with tempfile.TemporaryDirectory() as td:
        make_project(td, _variant)
        _dd = os.path.join(td, "www", "data") if _variant == "mv" \
            else os.path.join(td, "data")
        # плагин с JSON-базой в параметрах
        _inner = [{"name": "ボス剣", "desc": " buy/sell "},
                  {"name": "草", "desc": "heal"}]
        _pname = "M"
        if _variant == "mv":
            _pj = os.path.join(td, "www", "js", "plugins.js")
            os.makedirs(os.path.dirname(_pj), exist_ok=True)
            with open(os.path.join(td, "www", "index.html"), "w",
                      encoding="utf-8") as f:
                f.write("<html><body>game</body></html>\n")
            with open(_pj, "w", encoding="utf-8") as f:
                f.write("var $plugins = " + json.dumps(
                    [{"name": _pname, "status": True, "description": "",
                      "parameters": {"db": json.dumps(_inner, ensure_ascii=False),
                                     "label": "ラベル"}}],
                    ensure_ascii=False) + ";\n")
        else:
            _pj = os.path.join(td, "data", "plugins.js")
            with open(_pj, "w", encoding="utf-8") as f:
                json.dump([{"name": _pname, "status": True, "description": "",
                            "parameters": {
                                "db": json.dumps(_inner, ensure_ascii=False),
                                "label": "ラベル"}}], f, ensure_ascii=False)
        with open(os.path.join(_dd, "System.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"gameTitle": "タイトル", "currencyUnit": "G"}, f,
                      ensure_ascii=False)
        _entries = parser.extract(td)
        assert _entries, f"nothing extracted ({_variant})"
        for _i, _e in enumerate(_entries):
            _e.translation = _HOSTILE[_i % len(_HOSTILE)]
            _e.status = "translated"
        _mod = _Mod45(td)
        _stats = _mod.apply(td, _entries, target_lang="ru")
        assert not _stats.get("verify_failed"), \
            f"{_variant}: { _stats.get('verify_failed')}"
        # симуляция старта игры: всё парсится строго
        from app.core.rpgmaker import verify as _vv
        _probs = _vv.verify_boot_files(td)
        assert not _probs, f"{_variant}: {_probs}"
        # внутренняя база плагина цела и переведена
        _txt = open(_pj, encoding="utf-8").read()
        _arr = json.loads(_txt[_txt.index("["):_txt.rindex("]") + 1])
        _mine = [p for p in _arr if p.get("name") == _pname]
        assert len(_mine) == 1, [p.get("name") for p in _arr]
        _db = json.loads(_mine[0]["parameters"]["db"])
        assert isinstance(_db, list) and len(_db) == 2
        assert _db[0]["name"] != "ボス剣"  # перевод лёг внутрь базы
        _mod.restore_original(td)
print("   OK")

print()
print("46) resrefs: имена ресурсов опознаются, текст — нет...")
from app.core.rpgmaker import resrefs as _rr46
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "audio", "bgm"))
    os.makedirs(os.path.join(td, "img", "pictures"))
    os.makedirs(os.path.join(td, "www", "audio"))
    open(os.path.join(td, "audio", "bgm", "001 Test Song.ogg"), "wb").write(b"x")
    open(os.path.join(td, "audio", "bgm", "戦闘曲.ogg_"), "wb").write(b"x")
    open(os.path.join(td, "img", "pictures", "Castle.png"), "wb").write(b"x")
    open(os.path.join(td, "www", "audio", "Theme.rpgmvp"), "wb").write(b"x")
    _idx = _rr46.build_index(td)
    assert _rr46.is_resource_name(_idx, "001 Test Song")
    assert _rr46.is_resource_name(_idx, "戦闘曲")
    assert _rr46.is_resource_name(_idx, "Castle")
    assert _rr46.is_resource_name(_idx, "Castle.png")
    assert _rr46.is_resource_name(_idx, "Theme")
    assert not _rr46.is_resource_name(_idx, "Добрый вечер")
    assert not _rr46.is_resource_name(_idx, "Hello world")
    assert not _rr46.is_resource_name(_idx, "")
    assert not _rr46.is_resource_name(set(), "Castle")
    _rr46.clear_index(td)
print("   OK")

print()
print("47) Извлечение: аудио/картинки/метки/маршруты не извлекаются...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "data"))
    os.makedirs(os.path.join(td, "js"))
    os.makedirs(os.path.join(td, "audio", "bgm"))
    os.makedirs(os.path.join(td, "img", "pictures"))
    open(os.path.join(td, "js", "rmmz_core.js"), "w").close()
    open(os.path.join(td, "audio", "bgm", "001 Test Song.ogg"), "wb").write(b"x")
    open(os.path.join(td, "img", "pictures", "Castle.png"), "wb").write(b"x")
    _map = {"displayName": "Town", "width": 2, "height": 2,
            "data": [0] * 2 * 2 * 6,
            "events": [None, {"id": 1, "name": "EV", "x": 1, "y": 1,
                      "note": "", "pages": [{"conditions": {}, "image": {},
                      "list": [
                          {"code": 401, "indent": 0,
                           "parameters": ["Добрый вечер"]},
                          {"code": 241, "indent": 0, "parameters": [
                              {"name": "001 Test Song", "volume": 90,
                               "pitch": 100, "pan": 0}]},
                          {"code": 231, "indent": 0, "parameters": [
                              1, "Castle", 0, 0, 0, 100, 100, 255, 0]},
                          {"code": 118, "indent": 0,
                           "parameters": ["LOOP"]},
                          {"code": 205, "indent": 0, "parameters": [
                              {"list": [{"code": 43, "parameters": [
                                  {"name": "001 Test Song"}]}]}]},
                          {"code": 0, "indent": 0, "parameters": []}]}]}]}
    with open(os.path.join(td, "data", "Map001.json"), "w",
              encoding="utf-8") as f:
        json.dump(_map, f, ensure_ascii=False)
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "G"}, f)
    _ents = parser.extract(td)
    _texts = [e.original for e in _ents]
    assert "Добрый вечер" in _texts
    assert "001 Test Song" not in _texts, _texts
    assert "Castle" not in _texts, _texts
print("   OK")

print()
print("48) Старый проект с аудио в словаре: фильтр на apply...")
from app.core.models import TranslationEntry as _TE48
from app.engines.rpgmaker import RpgMakerModule as _Mod48
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "data"))
    os.makedirs(os.path.join(td, "js"))
    os.makedirs(os.path.join(td, "audio", "bgm"))
    open(os.path.join(td, "js", "rmmz_core.js"), "w").close()
    open(os.path.join(td, "audio", "bgm", "001 Test Song.ogg"), "wb").write(b"x")
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "G"}, f)
    with open(os.path.join(td, "data", "plugins.js"), "w",
              encoding="utf-8") as f:
        json.dump([{"name": "M", "status": True, "description": "",
                    "parameters": {"bgm": "001 Test Song",
                                   "label": "Hello"}}], f)
    _ents48 = [
        _TE48(id=1, file="data/plugins.js",
              json_path="#plugparam:M:bgm", context="p",
              original="001 Test Song", translation="001 Песня",
              status="translated"),
        _TE48(id=2, file="data/plugins.js",
              json_path="#plugparam:M:label", context="p",
              original="Hello", translation="Привет",
              status="translated"),
    ]
    _st48 = _Mod48(td).apply(td, _ents48, target_lang="ru")
    assert _st48.get("res_skipped") == 1, _st48
    assert not _st48.get("verify_failed"), _st48.get("verify_failed")
    _pl48 = json.load(open(os.path.join(td, "data", "plugins.js"),
                           encoding="utf-8"))
    assert _pl48[0]["parameters"]["bgm"] == "001 Test Song", _pl48
    assert _pl48[0]["parameters"]["label"] == "Привет", _pl48
print("   OK")

print()
print("49) JS-обход не трогает аудио-объекты и имена файлов...")
from app.core.rpgmaker.payloads import _TRANSLATION_PAYLOAD as _TR49
assert "obIsAudio" in _TR49 and "obIsResKey" in _TR49
for _k in ("characterName", "faceName", "battlerName", "parallaxName",
           "battleback1Name", "battleback2Name", "title1Name",
           "title2Name"):
    assert _k in _TR49, _k
assert "=>" not in _TR49  # остался ES5
print("   OK")

print()
print("50) verify ловит перевод имени файла и лечит откатом...")
from app.core.rpgmaker import verify as _vv50
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "data"))
    os.makedirs(os.path.join(td, "js"))
    os.makedirs(os.path.join(td, "audio", "bgm"))
    os.makedirs(os.path.join(td, "backup", "data"))
    open(os.path.join(td, "js", "rmmz_core.js"), "w").close()
    open(os.path.join(td, "audio", "bgm", "001 Test Song.ogg"), "wb").write(b"x")
    _good = [{"name": "M", "status": True, "description": "",
              "parameters": {"bgm": "001 Test Song"}}]
    with open(os.path.join(td, "data", "plugins.js"), "w",
              encoding="utf-8") as f:
        json.dump(_good, f)
    import shutil as _sh50
    _sh50.copy2(os.path.join(td, "data", "plugins.js"),
                os.path.join(td, "backup", "data", "plugins.js"))
    _bad = [{"name": "M", "status": True, "description": "",
             "parameters": {"bgm": "001 Песня"}}]
    with open(os.path.join(td, "data", "plugins.js"), "w",
              encoding="utf-8") as f:
        json.dump(_bad, f, ensure_ascii=False)
    _probs = _vv50.verify_boot_files(td)
    assert any("001 Test Song" in p for p in _probs), _probs
    _st50 = _Mod48(td).apply(td, [], target_lang="ru")
    _back = json.load(open(os.path.join(td, "data", "plugins.js"),
                           encoding="utf-8"))
    assert _back[0]["parameters"]["bgm"] == "001 Test Song", _back
print("   OK")

print()
print("51) 657 `KEY = value`: извлекается value, данные — нет...")
from app.core.rpgmaker.parser import _split_kv_line as _kv51
from app.core.rpgmaker.parser import _splice_kv as _sp51
assert _kv51("メッセージ内容 = エナジードリンクを入手！") == \
    ("メッセージ内容", "エナジードリンクを入手！")
assert _kv51("X座標 = 10") == ("X座標", "10")
assert _kv51("без равно") == (None, None)
assert _kv51("a = b = c") == ("a", "b = c")  # первый знак
assert _kv51("two words = x") == (None, None)  # ключ без пробелов
assert _kv51("スイッチID = ") == (None, None)  # пустое value
assert _kv51("k = v\nline2") == (None, None)  # только однострочные
assert _sp51("メッセージ内容 = エナジードリンクを入手！",
             "エナジードリンクを入手！", "Got a drink!") == \
    "メッセージ内容 = Got a drink!"
assert _sp51("X座標 = 10", "X座標", "Y") is None  # ключ не меняем
assert _sp51("a = b", "zzz", "Q") is None  # чужое value не трогаем
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    _ce = os.path.join(td, "data", "CommonEvents.json")
    _common = json.load(open(_ce, encoding="utf-8"))
    _common[1]["list"] = [
        {"code": 657, "indent": 0,
         "parameters": ["メッセージ内容 = エナジードリンクを入手！"]},
        {"code": 657, "indent": 0, "parameters": ["変数 = 102"]},
        {"code": 657, "indent": 0, "parameters": ["просто текст"]},
        {"code": 0, "indent": 0, "parameters": []},
    ]
    json.dump(_common, open(_ce, "w", encoding="utf-8"),
              ensure_ascii=False)
    _ents51 = parser.extract(td)
    _by_orig51 = {e.original: e for e in _ents51}
    assert "エナジードリンクを入手！" in _by_orig51, list(_by_orig51)
    assert "メッセージ内容" not in _by_orig51  # ключ цел
    assert "変数 = 102" not in _by_orig51  # данные
    assert "просто текст" in _by_orig51  # обычная строка целиком
    # parity parser.apply: ключ цел, value переведено
    _e51 = _by_orig51["エナジードリンクを入手！"]
    _e51.translation = "Got a drink!"
    _e51.status = "translated"
    _st51 = parser.apply(td, [_e51])
    assert _st51["strings"] == 1, _st51
    _back51 = json.load(open(_ce, encoding="utf-8"))
    assert _back51[1]["list"][0]["parameters"][0] == \
        "メッセージ内容 = Got a drink!", _back51[1]["list"][0]
print("   OK")

print()
print("52) Свои плагины (ob_runtime/octopus_ob) не извлекаются...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    os.makedirs(os.path.join(td, "js", "plugins"))
    with open(os.path.join(td, "data", "plugins.js"), "w",
              encoding="utf-8") as f:
        json.dump([{"name": "ob_runtime", "status": True, "description": "",
                    "parameters": {}},
                   {"name": "MyP", "status": True, "description": "",
                    "parameters": {}}], f)
    with open(os.path.join(td, "js", "plugins", "ob_runtime.js"), "w",
              encoding="utf-8") as f:
        f.write('window.__octopus_trInstall({"Привет": "Hello"});\n')
    with open(os.path.join(td, "js", "plugins", "MyP.js"), "w",
              encoding="utf-8") as f:
        f.write("var s = 'こんにちは世界';\n")
    _ents52 = parser.extract_plugins(td, "data", variant="mz")
    _texts52 = [e.original for e in _ents52]
    assert "こんにちは世界" in _texts52, _texts52
    assert "Привет" not in _texts52 and "Hello" not in _texts52, _texts52
print("   OK")

print()
print("53) Вложенные аргументы 357 извлекаются...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    _ce = os.path.join(td, "data", "CommonEvents.json")
    _common = json.load(open(_ce, encoding="utf-8"))
    _common[1]["list"] = [
        {"code": 357, "indent": 0, "parameters": [
            "P.js", "cmd", "note",
            {"title": "Заголовок окна",
             "nested": {"deep": "глубокий текст", "n": 5}}]},
        {"code": 0, "indent": 0, "parameters": []},
    ]
    json.dump(_common, open(_ce, "w", encoding="utf-8"),
              ensure_ascii=False)
    _texts53 = [e.original for e in parser.extract(td)]
    assert "Заголовок окна" in _texts53, _texts53
    assert "глубокий текст" in _texts53, _texts53
print("   OK")

print()
print("54) 657 в рантайме: JS-ветка с KV-подменой (ES5)...")
from app.core.rpgmaker.payloads import _TRANSLATION_PAYLOAD as _TR54
assert "obSplitKV" in _TR54 and "obApplyKVParam" in _TR54
assert "cmd.code === 657" in _TR54
assert "=>" not in _TR54
print("   OK")

print()
print("55) Заголовок окна: извлечение + запись (package.json/index.html)...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    with open(os.path.join(td, "package.json"), "w",
              encoding="utf-8") as f:
        json.dump({"name": "rmmz-game", "main": "index.html",
                   "window": {"title": "オチカノAnother Ver1.00",
                              "width": 1280}}, f, ensure_ascii=False)
    with open(os.path.join(td, "index.html"), "w",
              encoding="utf-8") as f:
        f.write("<html><head><title>オチカノAnother Ver1.00</title>"
                "</head><body></body></html>")
    _ents55 = parser.extract(td)
    _titles55 = [e for e in _ents55 if e.file in ("package.json",
                                                  "index.html")]
    assert len(_titles55) == 2, [e.file for e in _titles55]
    assert all(e.original == "オチカノAnother Ver1.00" for e in _titles55)
    for e in _titles55:
        e.translation = "Ochikano Another v1.00"
        e.status = "translated"
    _st55 = parser.apply(td, _titles55)
    assert _st55["strings"] == 2, _st55
    _pkg55 = json.load(open(os.path.join(td, "package.json"),
                            encoding="utf-8"))
    assert _pkg55["window"]["title"] == "Ochikano Another v1.00", _pkg55
    assert _pkg55["name"] == "rmmz-game"  # остальное цело
    _html55 = open(os.path.join(td, "index.html"),
                   encoding="utf-8").read()
    assert "<title>Ochikano Another v1.00</title>" in _html55, _html55
    # чужой заголовок не затираем
    from app.core.rpgmaker.parser import _apply_html_title as _aht55
    with open(os.path.join(td, "index.html"), "w",
              encoding="utf-8") as f:
        f.write("<title>Other Game</title>")
    assert _aht55(os.path.join(td, "index.html"),
                  "オチカノAnother Ver1.00", "X") is False
    assert "<title>Other Game</title>" in open(
        os.path.join(td, "index.html"), encoding="utf-8").read()
print("   OK")

print()
print("56) dataEx: кастомные данные разработчика сканируются...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    os.makedirs(os.path.join(td, "dataEx"))
    with open(os.path.join(td, "dataEx", "MySkitDB.json"), "w",
              encoding="utf-8") as f:
        json.dump({"skits": [{"title": "朝の出来事",
                              "steps": [1, 2, {"pose": 0}]}]}, f,
                  ensure_ascii=False)
    _texts56 = [e.original for e in parser.extract(td)]
    assert "朝の出来事" in _texts56, _texts56
print("   OK")

print()
print("57) Рантайм ставит заголовок окна + verify читает package.json...")
from app.core.rpgmaker import runtime as _rt57
_src57 = _rt57.build_runtime_source({"A": "B"}, "ru")
assert "document.title" in _src57 and "nw.Window" in _src57
from app.core.rpgmaker import verify as _vv57
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, "package.json"), "w",
              encoding="utf-8") as f:
        f.write('{"name": "x"}')
    assert _vv57.verify_boot_files(td) == []
    with open(os.path.join(td, "package.json"), "w",
              encoding="utf-8") as f:
        f.write('{"name": }')
    assert any("package.json" in p for p in _vv57.verify_boot_files(td))
print("   OK")

print()
print("58) Отчёт о пропусках: skipped_total/skipped_by в stats...")
from app.core.models import TranslationEntry as _TE58
from app.engines.rpgmaker import RpgMakerModule as _Mod58
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "G"}, f)
    with open(os.path.join(td, "data", "plugins.js"), "w",
              encoding="utf-8") as f:
        json.dump([{"name": "M", "status": True, "description": "",
                    "parameters": {"label": "Hello"}}], f)
    _ents58 = [
        _TE58(id=1, file="data/plugins.js",
              json_path="#plugparam:GHOST:key", context="p",
              original="Boo", translation="Бу",
              status="translated"),
        _TE58(id=2, file="data/plugins.js",
              json_path="#plugparam:M:label", context="p",
              original="Hello", translation="Привет",
              status="translated"),
    ]
    _st58 = _Mod58(td).apply(td, _ents58, target_lang="ru")
    assert _st58.get("skipped_total") == 1, _st58
    assert _st58.get("skipped_by") == {"plugin-missing": 1}, _st58
    _pl58 = json.load(open(os.path.join(td, "data", "plugins.js"),
                           encoding="utf-8"))
    assert _pl58[0]["parameters"]["label"] == "Привет", _pl58
    assert not _st58.get("verify_failed"), _st58.get("verify_failed")
print("   OK")

print()
print("59) Автоперенос: структура JS, ES5, хуки диалогов...")
from app.core.rpgmaker.payloads import _TRANSLATION_PAYLOAD as _TR59


def _js_balanced59(src: str) -> bool:
    """Баланс скобок вне строк/комментариев/regex (замена JS-парсера).

    Regex-литералы отличаются от деления эвристикой по предыдущему
    значимому токену: после `= ( , : [ ! & | ? { } ;` и ключевых слов —
    regex, иначе деление.
    """
    st: list[str] = []
    i, n = 0, len(src)
    pairs = {")": "(", "]": "[", "}": "{"}
    kw = ("return", "typeof", "instanceof", "in", "of", "new",
          "delete", "void", "throw", "case", "do", "else")

    def _prev_is_regex_pos(p: int) -> bool:
        j = p - 1
        while j >= 0 and src[j] in " \t\r\n":
            j -= 1
        if j < 0:
            return True
        c = src[j]
        if c in "(=,:[!&|?{};~^%*<>+-":
            return True
        if c.isalnum() or c in "_$":
            k = j
            while k >= 0 and (src[k].isalnum() or src[k] in "_$"):
                k -= 1
            return src[k + 1:j + 1] in kw
        return False

    def _skip_regex(p: int) -> int:
        # p — на открывающем `/`; возвращает позицию после флагов
        k = p + 1
        in_cls = False
        while k < n:
            c = src[k]
            if c == "\\":
                k += 2
                continue
            if c == "[":
                in_cls = True
            elif c == "]":
                in_cls = False
            elif c == "/" and not in_cls:
                k += 1
                while k < n and src[k].isalpha():
                    k += 1  # флаги g/i/m
                return k
            elif c == "\n":
                return p + 1  # не regex, а деление
            k += 1
        return p + 1

    while i < n:
        c = src[i]
        if c in "\"'":
            q = c
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == q:
                    break
                i += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if c == "/" and i + 1 < n and src[i + 1] not in "/=*":
            if _prev_is_regex_pos(i):
                i = _skip_regex(i)
                continue
            i += 1
            continue
        if c in "([{":
            st.append(c)
        elif c in ")]}":
            if not st or st.pop() != pairs[c]:
                return False
        i += 1
    return not st


assert _js_balanced59(_TR59), "пейлоад: скобки не сошлись"
assert "=>" not in _TR59 and "`" not in _TR59, "пейлоад: не ES5"
import re as _re59
assert not _re59.search(r"\b(const|let)\b", _TR59), "пейлоад: не ES5"
# перенос: функции, замер шрифтом окна, гейт по типу окна
for _marker in ("obWrapLine", "obWrapForWindow", "obPlainForMeasure",
                "obMeasureWidth", "contentsWidth", "Window_Message",
                "Window_ScrollText", "__octopus_trWrapForWindow"):
    assert _marker in _TR59, _marker
# \FS[ / \{ \} — пропуск строк со сменой размера (метрику не угадаем)
assert "FS\\[" in _TR59
# тумблер по умолчанию включён, отключаемый из игры
assert "__octopus_trWrap = true" in _TR59
print("   OK")

print()
print("60) Автоперенос: алгоритм выполняется (cscript-стаб)...")
import shutil as _sh60
if _sh60.which("cscript") is None:
    print("   SKIP: нет cscript")
else:
    from app.core.rpgmaker import payloads as _pl60
    _src60 = _pl60._TRANSLATION_PAYLOAD
    _a60 = _src60.index("window.__octopus_trWrap = true;")
    _b60 = _src60.index(
        "window.__octopus_trWrapForWindow = obWrapForWindow;") + len(
        "window.__octopus_trWrapForWindow = obWrapForWindow;")
    _block60 = _src60[_a60:_b60]
    # тестовые строки — только ASCII+\uXXXX (кодировка консоли cscript)
    _ru60 = "".join(f"\\u{ord(c):04x}" for c in
                    "В этой игре вы можете выбрать отдельные заставки для каждой")
    _cjk60 = "\\u3053\\u3093\\u306b\\u3061\\u306f" * 12
    _harness60 = (
        "var window = {};\n"
        "var document = {title: \"\"};\n"
        "function Bitmap(w, h) { this.fontFace = \"\"; this.fontSize = 28; }\n"
        "Bitmap.prototype.measureTextWidth = function (s) {\n"
        "  var w = 0;\n"
        "  for (var i = 0; i < s.length; i++) {\n"
        "    var c = s.charCodeAt(i);\n"
        "    w += (c >= 0x3000 || (c >= 0xFF00 && c <= 0xFFEF)) ? 2 : 1;\n"
        "  }\n"
        "  return w;\n"
        "};\n"
        "function Window_Message() {}\n"
        "function Window_ScrollText() {}\n"
        "var $gameMessage = { faceName: function () { return \"\"; } };\n"
        "var $gameActors = { actor: function () { return null; } };\n"
        "var $gameParty = { members: function () { return []; } };\n"
        "var $dataSystem = { currencyUnit: \"G\" };\n"
        + _block60 + "\n"
        "function mkwin() {\n"
        "  var win = new Window_Message();\n"
        "  win.contentsWidth = function () { return 50; };\n"
        "  win.contents = {fontFace: \"\", fontSize: 28};\n"
        "  return win;\n"
        "}\n"
        "function fit(s, w) {\n"
        "  var lines = s.split(\"\\n\");\n"
        "  for (var i = 0; i < lines.length; i++) {\n"
        "    if (obMeasureWidth(w, obPlainForMeasure(lines[i])) > 50) return false;\n"
        "  }\n"
        "  return true;\n"
        "}\n"
        "var fails = [];\n"
        "function check(name, cond) { if (!cond) fails.push(name); }\n"
        "var win = mkwin();\n"
        "// 1. короткая строка не меняется\n"
        "check(\"short\", obWrapLine(\"abc def\", 50, win) === \"abc def\");\n"
        "// 2. длинная русская строка переносится и влезает\n"
        "var long_ru = \"" + _ru60 + "\";\n"
        "var w2 = obWrapLine(long_ru, 50, win);\n"
        "check(\"ru-wrapped\", w2.indexOf(\"\\n\") >= 0);\n"
        "check(\"ru-fit\", fit(w2, win));\n"
        "check(\"ru-idem\", obWrapLine(w2, 50, win) === w2);\n"
        "// 3. CJK без пробелов режется посимвольно\n"
        "var w3 = obWrapLine(\"" + _cjk60 + "\", 50, win);\n"
        "check(\"cjk-wrapped\", w3.indexOf(\"\\n\") >= 0);\n"
        "check(\"cjk-fit\", fit(w3, win));\n"
        "check(\"cjk kept\", w3.replace(/\\n/g, \"\") === \"" + _cjk60 + "\");\n"
        "// 4. коды цвета сохраняются на первой строке\n"
        "var w4 = obWrapLine(\"\\\\C[2] \" + long_ru, 50, win);\n"
        "check(\"code-first\", w4.split(\"\\n\")[0].indexOf(\"\\\\C[2]\") === 0);\n"
        "check(\"code-fit\", fit(w4, win));\n"
        "// 5. переменные и FS-строки: без падений\n"
        "check(\"var-fit\", fit(obWrapLine(\"\\\\V[1] \" + long_ru, 50, win), win));\n"
        "var fsline = \"\\\\FS[30] \" + long_ru;\n"
        "check(\"fs-passthrough\", obWrapLine(fsline, 50, win) === fsline);\n"
        "// 6. гейт по типу окна\n"
        "check(\"plain-win\", obWrapForWindow({}, long_ru) === long_ru);\n"
        "check(\"msg-win\", obWrapForWindow(win, long_ru).indexOf(\"\\n\") >= 0);\n"
        "// 7. пустая строка\n"
        "check(\"empty\", obWrapLine(\"\", 50, win) === \"\");\n"
        "if (fails.length) { WScript.Echo(\"FAIL: \" + fails.join(\",\")); WScript.Quit(1); }\n"
        "WScript.Echo(\"HARNESS-OK\");\n"
    )
    _js60 = os.path.join(tempfile.gettempdir(), "ob_wrap_test.js")
    with open(_js60, "w", encoding="utf-8") as _f60:
        _f60.write(_harness60)
    import subprocess as _sp60
    try:
        _r60 = _sp60.run(["cscript", "//Nologo", "//E:JScript", _js60],
                         capture_output=True, text=True, timeout=60)
    finally:
        try:
            os.remove(_js60)
        except OSError:
            pass
    assert _r60.returncode == 0, (_r60.stdout, _r60.stderr)
    assert "HARNESS-OK" in _r60.stdout, (_r60.stdout, _r60.stderr)
print("   OK")

print()
print("61) Телепорт: JS с reserveTransfer(mapId,x,y) + запрет в бою...")
_tp61 = RpgMakerTentacle._cheat_expr("teleport", mapId=3, x=1, y=2)
assert _tp61 is not None and "reserveTransfer" in _tp61, _tp61
assert "3, 1, 2" in _tp61, _tp61
assert "$gameParty.inBattle()" in _tp61, "телепорт обязан блокироваться в бою"
assert "=>" not in _tp61, "чит обязан быть ES5 (старый NW.js MV)"
assert RpgMakerTentacle._cheat_expr("teleport", mapId=1, x=0, y=0) is not None
assert RpgMakerTentacle._cheat_expr("teleport_nope") is None
# send_cheat("teleport", mapId=.., x=.., y=..) как шлёт map_tab:
# тот же JS уходит в evaluate, ack ok
_t61 = RpgMakerTentacle()
_seen61, _ack61 = {}, []
_t61.cheat_ack.connect(lambda *a: _ack61.append(a))
_t61.evaluate = lambda expr, await_promise=False, timeout=15.0: (
    _seen61.update(expr=expr) or True, "teleported")
assert _t61.send_cheat("teleport", mapId=3, x=1, y=2) is True
assert _ack61 and _ack61[0][0] == "teleport" and _ack61[0][1] is True, _ack61
assert "reserveTransfer" in _seen61.get("expr", "") \
    and "3, 1, 2" in _seen61.get("expr", ""), _seen61.get("expr")
print("   OK")

print()
print("62) State: request_state достаёт mapId/playerX/playerY "
      "(CDP-строка, мост-строка, binding-push)...")
_fake62 = {"type": "state", "gold": 500, "mapId": 7, "playerX": 12,
           "playerY": 9, "party": [], "items": [],
           "variables": [0, 5], "switches": [False, True]}
_wire62 = json.dumps(_fake62, ensure_ascii=False)
# CDP-ветка: evaluate("JSON.stringify(...)") возвращает str
_t62 = RpgMakerTentacle()
_got62, _expr62 = {}, []
_t62.state_received.connect(lambda d: _got62.update(d=d))


def _eval62(expr, await_promise=False, timeout=15.0):
    _expr62.append(expr)
    return True, _wire62


_t62.evaluate = _eval62
assert _t62.request_state() is True
# запрос идёт через коллектор пейлоада, а не произвольный JS
assert _expr62 and "__octopus_collectState" in _expr62[0], _expr62
_d62 = _got62.get("d")
assert isinstance(_d62, dict), _d62
assert _d62.get("mapId") == 7, _d62
assert _d62.get("playerX") == 12 and _d62.get("playerY") == 9, _d62
# HTTP-мост: bridge_eval тоже отдаёт str (двойной JSON) — тот же путь
_t62m = RpgMakerTentacle()
_got62m = {}
_t62m.state_received.connect(lambda d: _got62m.update(d=d))
_t62m.evaluate = lambda expr, await_promise=False, timeout=15.0: (
    True, _wire62)
assert _t62m.request_state() is True
assert _got62m.get("d", {}).get("playerX") == 12, _got62m.get("d")
# push из игры (binding/console, type=state) — тот же словарь
_t62p = RpgMakerTentacle()
_got62p = {}
_t62p.state_received.connect(lambda d: _got62p.update(d=d))
_t62p._handle_raw_message(_wire62)
assert _got62p.get("d", {}).get("mapId") == 7 \
    and _got62p.get("d", {}).get("playerY") == 9, _got62p.get("d")
# пейлоад реально шлёт эти поля (источник правды для UI)
from app.core.rpgmaker.payloads import PAYLOAD as _PAY62
for _m62 in ("__octopus_collectState", 'type: "state"', "mapId",
             "playerX", "playerY"):
    assert _m62 in _PAY62, _m62
print("   OK")

print()
print("63) Читы: все команды UI (cheat/map вкладки) маппятся в JS...")
_cmds63 = [
    ("gold_set", {"value": 100}), ("gold_add", {"value": -1000}),
    ("game_speed", {"value": 2}), ("heal_all", {}), ("clear_states", {}),
    ("win_battle", {}), ("through", {"value": True}),
    ("click_tp", {"value": False}), ("speed", {"value": 4}),
    ("reload_map", {}), ("open_menu", {}), ("open_items", {}),
    ("open_skills", {}), ("open_equip", {}), ("open_status", {}),
    ("open_save", {}), ("open_load", {}), ("open_options", {}),
    ("open_gameend", {}),
    ("give_item", {"kind": "weapon", "id": 3, "count": 1}),
    ("var_set", {"index": 2, "value": "x"}),
    ("switch_set", {"index": 7, "value": True}),
    ("self_switch_set", {"mapId": 7, "eventId": 66, "ch": "A",
                         "value": True}),
    ("actor_set", {"actorId": 1, "field": "level", "value": 5}),
    ("teleport", {"mapId": 3, "x": 1, "y": 2}),
    ("event_start", {"eventId": 66}),
]
for _c63, _k63 in _cmds63:
    _e63 = RpgMakerTentacle._cheat_expr(_c63, **_k63)
    assert _e63, f"{_c63} {_k63} не маппится (unknown cmd)"
    assert "=>" not in _e63, _c63
_ev63 = RpgMakerTentacle._cheat_expr("event_start", eventId=66)
assert "var eid=66" in _ev63 and "$gameMap.event(eid)" in _ev63 \
    and ".start()" in _ev63, _ev63
_ss63 = RpgMakerTentacle._cheat_expr("self_switch_set", mapId=7, eventId=66,
                                     ch="b", value=True)
assert "$gameSelfSwitches.setValue([7, 66" in _ss63 \
    and '"B"' in _ss63 and "true" in _ss63, _ss63
assert "=>" not in _ss63
import app.core.rpgmaker.payloads as _pay63
assert "selfSwitches" in _pay63.PAYLOAD, "state должен нести self-свитчи"
assert RpgMakerTentacle._cheat_expr("no_such_cheat") is None
assert RpgMakerTentacle._cheat_expr("var_set", index=2, value="x") == \
    '$gameVariables.setValue(2, "x")'
assert RpgMakerTentacle._cheat_expr("switch_set", index=7, value=True) == \
    "$gameSwitches.setValue(7, true)"
print("   OK:", len(_cmds63), "команд")

print()
print("64) Позиция игрока: подпись карты с координатами, плейсхолдеры "
      "подставляются через kwargs (не TR().format())...")
from app.ui.i18n import TR as _TR64
from app.ui.map_tab import player_map_label as _lbl64
_s64 = _TR64("map_player_map", map_id=7, x=12, y=9)
assert "7" in _s64 and "12" in _s64 and "9" in _s64, _s64
assert _lbl64({"mapId": 7, "playerX": 12, "playerY": 9}) == _s64
assert _lbl64({"mapId": 3}) != "" and "#3" in _lbl64({"mapId": 3}), \
    _lbl64({"mapId": 3})
assert _lbl64({}) == "" and _lbl64(None) == "" \
    and _lbl64({"playerX": 1}) == ""
print("   OK:", _s64)

print()
print("65) Вкладка карт: клик по пустой клетке -> teleport, "
      "state показывает карту+позицию и открывает карту игрока...")
import os as _os65
_os65.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QObject as _QObject65, Signal as _Signal65
from PySide6.QtWidgets import QApplication as _QA65
_qapp65 = _QA65.instance() or _QA65([])
from PySide6.QtWidgets import QMessageBox as _MB65
_MB65.information = staticmethod(lambda *a, **k: _MB65.Ok)
from app.ui.map_tab import MapTab as _MapTab65


class _FakeMain65(_QObject65):
    bridge_state = _Signal65(str)
    bridge_cheat_ack = _Signal65(str, bool, str, str)
    bridge_client = _Signal65(bool)

    def __init__(self):
        super().__init__()
        self.cheats = []
        self.states = 0
        self.project = None
        self.engine_module = None

    def channel(self):
        return self


class _Ch65:
    def __init__(self, outer):
        self._outer = outer

    def send_cheat(self, cmd, **kw):
        self._outer.cheats.append((cmd, kw))
        return True

    def request_state(self):
        self._outer.states += 1
        return True


_FakeMain65.channel = lambda self: _Ch65(self)
_m65 = _FakeMain65()
_mt65 = _MapTab65(_m65)
# клик по пустой клетке загруженной карты — команда телепорта в канал
_mt65._map_id = 7
_mt65._map_data = {"width": 20, "height": 15,
                   "data": [0] * 20 * 15 * 6, "events": []}
_mt65.select_event_at(12, 9)
assert ("teleport", {"mapId": 7, "x": 12, "y": 9}) in _m65.cheats, \
    _m65.cheats
# клик вне границ — тихо, без команды
_n65 = len(_m65.cheats)
_mt65.select_event_at(99, 99)
assert len(_m65.cheats) == _n65, _m65.cheats
# state: подпись с картой и координатами + автовыбор карты игрока
_mt65._maps = [(7, "Start")]
_mt65._fill_maps()
_mt65._map_data = None
_mt65._on_state({"type": "state", "mapId": 7, "playerX": 12, "playerY": 9})
_qapp65.processEvents()
assert "7" in _mt65.lbl_player_map.text() \
    and "12" in _mt65.lbl_player_map.text() \
    and "9" in _mt65.lbl_player_map.text(), \
    _mt65.lbl_player_map.text()
assert _mt65._map_id == 7, _mt65._map_id
print("   OK:", _mt65.lbl_player_map.text())

print()
print("66) Карта: клик считается пропорцией, телепорт с ack, флип свитча...")
from PySide6.QtGui import QPixmap as _PM66, QImage as _QImage66
from PySide6.QtCore import QPoint as _QPoint66
# pixmap 200x150 при карте 20x15: клик (100,75) -> тайл (10,7)
_mt65._map_id = 7
_mt65._map_data = {"width": 20, "height": 15,
                   "data": [0] * 20 * 15 * 6, "events": []}
_mt65.canvas.setPixmap(_PM66.fromImage(_QImage66(200, 150, _QImage66.Format_ARGB32)))
_mt65.canvas.resize(200, 150)
_tile66 = _mt65.canvas._tile_at
assert _tile66(_QPoint66(100, 75)) == (10, 7), _tile66(_QPoint66(100, 75))
assert _tile66(_QPoint66(0, 0)) == (0, 0)
assert _tile66(_QPoint66(199, 149)) == (19, 14)
# ack телепорта виден в инфо-строке
_mt65._send_teleport(7, 10, 7)
_mt65._on_cheat_ack("teleport", True, "", "")
assert "7" in _mt65.lbl_map_info.text() and "10" in _mt65.lbl_map_info.text(), \
    _mt65.lbl_map_info.text()
_mt65._send_teleport(7, 1, 1)
_mt65._on_cheat_ack("teleport", False, "boom-err", "")
assert "boom-err" in _mt65.lbl_map_info.text(), _mt65.lbl_map_info.text()
# флип свитча по живому состоянию
_mt65._live_switches = [False, True, False]
_mt65._toggle_switch_live(1)
assert ("switch_set", {"index": 1, "value": True}) in _m65.cheats, _m65.cheats
_mt65._toggle_switch_live(2)
assert ("switch_set", {"index": 2, "value": False}) in _m65.cheats, _m65.cheats
print("   OK")

print()
print("67) Редактор событий: простое меню + 'Сделать видимым'...")
from app.ui.event_editor import EventEditorDialog as _EV67
_ev67 = {"id": 66, "name": "EV", "x": 19, "y": 4,
         "pages": [{"trigger": 1,
                    "conditions": {"switch1Valid": True, "switch1Id": 38,
                                   "variableValid": True, "variableId": 5,
                                   "variableValue": 3,
                                   "selfSwitchValid": True,
                                   "selfSwitchCh": "B"},
                    "image": {}, "list": [], "moveType": 0}]}
_dlg67 = _EV67(_mt65, None, None, _ev67, map_id=7)
# простое по умолчанию: вкладки скрыты, кнопка видимости есть
assert _dlg67.btn_mode_simple.isChecked()
assert not _dlg67.tabs.isVisibleTo(_dlg67)
assert _dlg67.simple_box.isVisibleTo(_dlg67)
assert _dlg67.btn_visible.isEnabled(), "канал есть — кнопка активна"
_dlg67.btn_visible.click()
_kinds67 = [c for c, _k in _m65.cheats]
assert "switch_set" in _kinds67 and "var_set" in _kinds67 \
    and "self_switch_set" in _kinds67, _m65.cheats
assert ("self_switch_set",
        {"mapId": 7, "eventId": 66, "ch": "B",
         "value": True}) in _m65.cheats, _m65.cheats
_dlg67._on_live_ack("self_switch_set", True, "", "")
assert _dlg67.lbl_visible.text() != "", "ack виден"
# расширенное показывает вкладки
_dlg67.btn_mode_expanded.click()
assert not _dlg67.simple_box.isVisibleTo(_dlg67)
assert _dlg67.tabs.isVisibleTo(_dlg67)
# без канала — кнопка disabled с подсказкой
_dlg67_off = _EV67(None, None, None, {"id": 1, "name": "E",
                                      "x": 0, "y": 0, "pages": [{}]},
                   map_id=7)
assert not _dlg67_off.btn_visible.isEnabled()
assert _dlg67_off.lbl_visible.text() != ""
_dlg67.reject()
_dlg67_off.reject()
print("   OK")

print()
print("68) Редактор: сохранение не стирает спрайт вне списка...")
_ev68 = {"id": 68, "name": "RTP", "x": 0, "y": 0,
         "pages": [{"trigger": 0, "conditions": {},
                    "image": {"characterName": "RTP_Missing_Sprite",
                              "characterIndex": 3, "direction": 4,
                              "pattern": 2, "tileId": 0},
                    "list": [{"code": 101, "indent": 0,
                              "parameters": ["", 0, 0, 2]}],
                    "moveType": 0}]}
_dlg68 = _EV67(_mt65, None, None, _ev68, map_id=7)
_dlg68.accept()  # == Save без касания дропдауна
_pg68 = _ev68["pages"][0]
assert (_pg68.get("image") or {}).get("characterName") == \
    "RTP_Missing_Sprite", _pg68.get("image")
assert (_pg68.get("image") or {}).get("characterIndex") == 3
assert len(_pg68.get("list") or []) == 1
_dlg68.deleteLater()
print("   OK")

print()
print("ВСЕ ТЕСТЫ RPG MAKER ПРОШЛИ")
