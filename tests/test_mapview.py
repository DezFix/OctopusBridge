# -*- coding: utf-8 -*-
"""Тесты H1 (превью карт RPG Maker) и H2 (загрузка ресурсов/расшифровка).

Создаёт синтетический MZ-проект во временной папке: карта 3x3 с известными
тайлами, тайлсет с цветными клетками, зашифрованный .png_ ресурс.
"""
import io
import json
import os
import struct
import sys
import tempfile
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.rpgmaker import crypto, maprender


def make_png_bytes(width: int, height: int, color_fn) -> bytes:
    """Минимальный PNG без Qt (чтобы ядро тестировалось отдельно)."""
    raw = bytearray(width * height * 4 + height)
    pos = 0
    for y in range(height):
        raw[pos] = 0
        pos += 1
        for x in range(width):
            raw[pos:pos + 4] = bytes(color_fn(x, y))
            pos += 4
    raw = bytes(raw)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + \
            struct.pack(">I", zlib.crc32(tag + data))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_project(root: str) -> dict:
    """Синтетический MZ-проект. Возвращает словарь с параметрами."""
    os.makedirs(os.path.join(root, "js"))
    os.makedirs(os.path.join(root, "data"))
    os.makedirs(os.path.join(root, "img", "tilesets"))
    os.makedirs(os.path.join(root, "img", "characters"))
    with open(os.path.join(root, "js", "rmmz_core.js"), "w") as f:
        f.write("// mz")

    key = "00112233445566778899aabbccddeeff"
    with open(os.path.join(root, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"gameTitle": "Test", "encryptionKey": key,
                   "hasEncryptedImages": True}, f)

    # B-лист 16x16 тайлов: тайл N — сплошной цвет (N, 0, 0)
    b_png = make_png_bytes(768, 768,
                           lambda x, y: ((x // 48) % 8 + (8 if (x // 48) >= 8 else 0)
                                         + (y // 48) * 8 % 256, 10, 20, 255))
    with open(os.path.join(root, "img", "tilesets", "TestB.png"), "wb") as f:
        f.write(b_png)
    # A5-лист 8x16
    a5_png = make_png_bytes(384, 768, lambda x, y: (30, (x // 48 + y // 48) % 256, 60, 255))
    with open(os.path.join(root, "img", "tilesets", "TestA5.png_"), "wb") as f:
        head = bytes(b ^ bytes.fromhex(key)[i] for i, b in enumerate(a5_png[:16]))
        f.write(crypto.SIGNATURE + head + a5_png[16:])
    # персонаж 3x4
    ch_png = make_png_bytes(144, 192, lambda x, y: (200, 100, 50, 255))
    with open(os.path.join(root, "img", "characters", "$Hero.png"), "wb") as f:
        f.write(ch_png)

    with open(os.path.join(root, "data", "Tilesets.json"), "w",
              encoding="utf-8") as f:
        json.dump([None, {"id": 1, "name": "Test",
                          "tilesetNames": ["", "", "", "", "TestA5",
                                           "TestB", "", "", ""]}], f)
    with open(os.path.join(root, "data", "MapInfos.json"), "w",
              encoding="utf-8") as f:
        json.dump([None, {"id": 1, "name": "Старт", "order": 1,
                          "parentId": 0, "scrollType": 0, "expanded": True}],
                  f, ensure_ascii=False)

    w = h = 3
    # ground: B-тайлы 1..9; overlay: пусто; shadow: 0; region: 0
    data = list(range(1, 10)) + [0] * 9 + [0] * 9 + [0] * 9
    ev = {
        "id": 1, "name": "Стражник", "note": "", "x": 1, "y": 1,
        "pages": [{
            "conditions": {"actorId": 1, "actorValid": False,
                           "itemId": 1, "itemValid": False,
                           "selfSwitchCh": "A", "selfSwitchValid": False,
                           "switch1Id": 7, "switch1Valid": True,
                           "switch2Id": 1, "switch2Valid": False,
                           "variableId": 1, "variableValid": False,
                           "variableValue": 0},
            "directionFix": False,
            "image": {"characterIndex": 0, "characterName": "$Hero",
                      "direction": 2, "pattern": 1, "tileId": 0},
            "list": [], "moveFrequency": 3, "moveRoute": {},
            "moveSpeed": 3, "moveType": 0, "priorityType": 1,
            "stepAnime": False, "through": False, "trigger": 0,
            "walkAnime": True}],
    }
    with open(os.path.join(root, "data", "Map001.json"), "w",
              encoding="utf-8") as f:
        json.dump({"autoplayBgm": False, "autoplayBgs": False,
                   "battleback1Name": "", "battleback2Name": "",
                   "bgm": {}, "bgs": {}, "disableDashing": False,
                   "displayName": "Старт", "encounterList": [],
                   "encounterStep": 30, "height": h, "note": "",
                   "parallaxLoopX": False, "parallaxLoopY": False,
                   "parallaxName": "", "parallaxShow": True,
                   "parallaxSx": 0, "parallaxSy": 0, "scrollType": 0,
                   "specifyBattleback": False, "tilesetId": 1,
                   "width": w, "data": data,
                   "events": [None, ev]}, f, ensure_ascii=False)
    return {"key": key}


print("1) tile_source: геометрия тайлов...")
# B-тайл 0 -> page B(5), (0,0)
assert maprender.tile_source(0) is None         # 0 = пусто
assert maprender.tile_source(1) == (maprender.PAGE_B, 48, 0)
# B-тайл 16 -> sx=0, sy=96 (16//8=2 ряд)
assert maprender.tile_source(16) == (maprender.PAGE_B, 0, 96)
# B-тайл 128 -> правая половина: sx=8*48=384, sy=0
assert maprender.tile_source(128) == (maprender.PAGE_B, 384, 0)
# C-тайл 256+1 -> page C(6)
assert maprender.tile_source(257) == (maprender.PAGE_C, 48, 0)
# A5 1536 -> page A5(4), (0,0)
assert maprender.tile_source(1536) == (maprender.PAGE_A5, 0, 0)
assert maprender.tile_source(1536 + 9) == (maprender.PAGE_A5, 48, 48)
# A1 2048 -> page A1(0)
assert maprender.tile_source(2048)[0] == maprender.PAGE_A1
assert maprender.tile_source(2048 + 48)[0] == maprender.PAGE_A1
# A2/A3/A4 страницы
assert maprender.tile_source(2816)[0] == maprender.PAGE_A2
assert maprender.tile_source(3072)[0] == maprender.PAGE_A3
assert maprender.tile_source(4352)[0] == maprender.PAGE_A4
assert maprender.tile_source(99999) is None
print("   OK: страницы и координаты верны")

with tempfile.TemporaryDirectory() as td:
    params = make_project(td)

    print("2) load_map / map_layers / события...")
    data = maprender.load_map(td, 1)
    assert data["displayName"] == "Старт"
    w, h, ground, overlay, shadow = maprender.map_layers(data)
    assert (w, h) == (3, 3) and ground == list(range(1, 10))
    s = maprender.event_summary(data["events"][1])
    assert s["name"] == "Стражник" and (s["x"], s["y"]) == (1, 1)
    assert s["image"] == "$Hero" and s["pages"] == 1
    c = maprender.page_conditions(data["events"][1]["pages"][0])
    assert c["switch1_valid"] and c["switch1_id"] == 7
    assert "SW 7" in maprender.visibility_text(
        data["events"][1]["pages"][0])
    print("   OK: карта и событие разобраны")

    print("3) tileset страницы + расшифровка .png_...")
    tileset = maprender.tileset_for_map(maprender.load_tilesets(td), 1)
    pages = maprender.tileset_page_paths(td, tileset)
    assert pages == {maprender.PAGE_A5: "img/tilesets/TestA5",
                     maprender.PAGE_B: "img/tilesets/TestB"}
    raw_plain = crypto.read_image(td, "img/tilesets/TestB")
    assert raw_plain[:8] == b"\x89PNG\r\n\x1a\n"
    raw_enc = crypto.read_image(td, "img/tilesets/TestA5")
    assert raw_enc[:8] == b"\x89PNG\r\n\x1a\n", "расшифровка .png_ не вышла"
    assert crypto.get_key(td) == params["key"]
    print("   OK: plain и .png_ читаются, ключ найден")

    print("4) save_map: запись + бэкап...")
    data["events"][1]["x"] = 2
    path = maprender.save_map(td, 1, data)
    assert os.path.exists(path + ".ob_backup")
    reloaded = maprender.load_map(td, 1)
    assert reloaded["events"][1]["x"] == 2
    # бэкап не затирается повторным сохранением
    data["events"][1]["x"] = 0
    maprender.save_map(td, 1, data)
    with open(path + ".ob_backup", encoding="utf-8") as f:
        assert json.load(f)["events"][1]["x"] == 1
    print("   OK: правки сохраняются, бэкап неизменен")

print("5) GUI: MapTab + ResourceTab (offscreen)...")
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
# диалоги не показываем: exec() в offscreen заблокировал бы тест
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)

from app.ui.main_window import MainWindow
w = MainWindow()
with tempfile.TemporaryDirectory() as td:
    make_project(td)
    engine = w.open_project(td)
    assert engine == "mz", engine
    roles = [r for _, r in w._engine_tabs]
    assert roles.count("module") == 2 and "cheats" in roles \
        and "translate" in roles, roles
    map_tab = next(t for t, r in w._engine_tabs
                   if t.__class__.__name__ == "MapTab")
    res_tab = next(t for t, r in w._engine_tabs
                   if t.__class__.__name__ == "ResourceTab")
    # рендер карты
    map_tab.reload()
    assert map_tab.map_list.count() == 1
    map_tab.map_list.setCurrentRow(0)
    pm = map_tab.canvas.pixmap()
    assert pm and not pm.isNull() and pm.width() == 3 * 48 // 2, pm.size()
    # выбор события кликом по канвасу (открывается диалог — подменяем)
    edited: list = []
    orig_edit = map_tab._edit_event_dialog
    def fake_edit(ev):
        ev["name"] = "Стражник II"
        edited.append(ev)
    map_tab._edit_event_dialog = fake_edit
    map_tab.select_event_at(1, 1)
    map_tab._edit_event_dialog = orig_edit
    assert edited, "клик по канвасу не выбрал событие"
    map_tab._save_map()
    reloaded = maprender.load_map(td, 1)
    assert reloaded["events"][1]["name"] == "Стражник II"
    # телепорт перенесён в MapTab (из читов убран)
    assert hasattr(map_tab, "_send_teleport")
    assert not hasattr(w.cheat_tab, "maps_table"), \
        "карта в читах и карта отдельно — одно и то же: оставляем MapTab"
    print("   MapTab: карта отрисована, правка сохранена, телепорт на месте")

    # ресурсы: список и превью
    res_tab.reload()
    assert res_tab.dir_combo.count() >= 1
    idx = res_tab.dir_combo.findText("img/tilesets")
    assert idx >= 0
    res_tab.dir_combo.setCurrentIndex(idx)
    names = [res_tab.list.item(i).text()
             for i in range(res_tab.list.count())]
    assert "TestB.png" in names and "TestA5.png_" in names, names
    # превью зашифрованного файла
    for i in range(res_tab.list.count()):
        if res_tab.list.item(i).text() == "TestA5.png_":
            res_tab.list.setCurrentRow(i)
            break
    pm = res_tab.image_label.pixmap()
    assert pm and not pm.isNull(), "превью .png_ не отрисовалось"
    print("   ResourceTab: список + превью .png_ OK")

w.close()
print()
print("ТЕСТЫ H1/H2 ПРОШЛИ")
sys.stdout.flush()
os._exit(0)
