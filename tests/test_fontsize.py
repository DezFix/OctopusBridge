# -*- coding: utf-8 -*-
"""Регулировка размера шрифта игры: MZ (System.json / rmmz_windows.js),
MV (rpg_windows.js), Ren'Py (gui.rpy) — get/set/restore, лимиты, бэкап."""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import fontsize


def make_mz_json(root: str) -> str:
    path = os.path.join(root, "data", "System.json")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"advanced": {"fontSize": 26, "screenWidth": 816}},
                  f, ensure_ascii=False)
    return path


def make_mz_js(root: str) -> str:
    path = os.path.join(root, "js", "rmmz_windows.js")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("// game core\n"
                "Window_Base.prototype.standardFontSize = function() {\n"
                "    return 28;\n"
                "};\n")
    return path


def make_mv_js(root: str) -> str:
    path = os.path.join(root, "www", "js", "rpg_windows.js")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("Window_Base.prototype.standardFontSize = function() {\n"
                "    return 28;\n"
                "};\n")
    return path


def make_renpy(root: str) -> str:
    path = os.path.join(root, "game", "gui.rpy")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("define gui.text_size = 33\n"
                "define gui.name_text_size = 40\n")
    return path


print("1) MZ: System.json advanced.fontSize...")
with tempfile.TemporaryDirectory() as td:
    p = make_mz_json(td)
    assert fontsize.get_font_size(td, "mz") == 26
    r = fontsize.set_font_size(td, "mz", 30)
    assert r["size"] == 30
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    assert data["advanced"]["fontSize"] == 30
    assert os.path.exists(p + fontsize.BACKUP_SUFFIX)
    assert fontsize.get_font_size(td, "mz") == 30
    assert fontsize.restore_font_size(td, "mz") is True
    assert fontsize.get_font_size(td, "mz") == 26
print("   OK")

print("2) MZ: без fontSize в System.json — rmmz_windows.js standardFontSize...")
with tempfile.TemporaryDirectory() as td:
    p = make_mz_js(td)
    os.makedirs(os.path.join(td, "data"))
    with open(os.path.join(td, "data", "System.json"), "w",
              encoding="utf-8") as f:
        json.dump({"advanced": {"gameId": 1}}, f)
    assert fontsize.get_font_size(td, "mz") == 28
    r = fontsize.set_font_size(td, "mz", 34)
    assert r["size"] == 34
    with open(p, encoding="utf-8") as f:
        text = f.read()
    assert "return 34;" in text
    assert fontsize.restore_font_size(td, "mz") is True
    with open(p, encoding="utf-8") as f:
        text = f.read()
    assert "return 28;" in text
print("   OK")

print("3) MV: www/js/rpg_windows.js...")
with tempfile.TemporaryDirectory() as td:
    p = make_mv_js(td)
    assert fontsize.get_font_size(td, "mv") == 28
    fontsize.set_font_size(td, "mv", 24)
    with open(p, encoding="utf-8") as f:
        text = f.read()
    assert "return 24;" in text
    assert fontsize.get_font_size(td, "mv") == 24
    assert fontsize.restore_font_size(td, "mv") is True
print("   OK")

print("4) Ren'Py: game/gui.rpy gui.text_size...")
with tempfile.TemporaryDirectory() as td:
    p = make_renpy(td)
    assert fontsize.get_font_size(td, "renpy") == 33
    r = fontsize.set_font_size(td, "renpy", 40)
    assert r["size"] == 40
    with open(p, encoding="utf-8") as f:
        text = f.read()
    assert "define gui.text_size = 40" in text
    assert "define gui.name_text_size = 40" in text  # вторая строка не тронута
    assert fontsize.get_font_size(td, "renpy") == 40
print("   OK")

print("5) Лимиты: clamp MIN/MAX, None для неподдерживаемого...")
with tempfile.TemporaryDirectory() as td:
    p = make_mz_json(td)
    r = fontsize.set_font_size(td, "mz", 500)
    assert r["size"] == fontsize.MAX_SIZE
    r = fontsize.set_font_size(td, "mz", -5)
    assert r["size"] == fontsize.MIN_SIZE
    assert fontsize.get_font_size(td, "twine") is None
    with tempfile.TemporaryDirectory() as td2:
        assert fontsize.get_font_size(td2, "mz") is None
        try:
            fontsize.set_font_size(td2, "mz", 30)
            raise AssertionError("должен был упасть")
        except FileNotFoundError:
            pass
print("   OK")

print()
print("ВСЕ ТЕСТЫ РАЗМЕРА ШРИФТА ПРОШЛИ")