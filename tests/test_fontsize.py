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

def make_ajin(root: str) -> str:
    path = os.path.join(root, "resources", "app", "override",
                        "data", "scenario", "first.ks")
    os.makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        f.write("[deffont size=42 face=mfrules bold=false]\n"
                "SAMPLE_LINE\n")
    cfg = os.path.join(root, "resources", "app", "override",
                       "data", "system", "Config.tjs")
    os.makedirs(os.path.dirname(cfg))
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(";config\n;defaultFontSize=37 ;defaultLineSpacing=4\n")
    return path


def make_ajin_asar(path: str, content: bytes) -> None:
    """Минимальный asar с одним first.ks (без игровых данных)."""
    from app.core import asar as asar_mod
    tree = {"files": {"data": {"files": {
        "scenario": {"files": {
            "first.ks": {"size": len(content), "offset": "0"}}}}}}}
    with open(path, "wb") as f:
        asar_mod._write_header(f, tree)
        f.write(content)


print("6) Ajin: [deffont] + Config.tjs через override-слой...")
with tempfile.TemporaryDirectory() as td:
    p = make_ajin(td)
    cfg = os.path.join(td, "resources", "app", "override",
                       "data", "system", "Config.tjs")
    assert fontsize.get_font_size(td, "ajin") == 42  # first.ks в приоритете
    r = fontsize.set_font_size(td, "ajin", 30)
    assert r["size"] == 30, r
    with open(p, encoding="utf-8") as f:
        text = f.read()
    assert "[deffont size=30 " in text and "SAMPLE_LINE" in text
    with open(cfg, encoding="utf-8") as f:
        assert "defaultFontSize=30" in f.read()
    assert os.path.exists(p + fontsize.BACKUP_SUFFIX)
    assert os.path.exists(cfg + fontsize.BACKUP_SUFFIX)
    assert fontsize.get_font_size(td, "ajin") == 30
    assert fontsize.restore_font_size(td, "ajin") is True
    assert fontsize.get_font_size(td, "ajin") == 42
    with open(cfg, encoding="utf-8") as f:
        assert "defaultFontSize=37" in f.read()
    # нет тегов — честно None/ошибка, а не выдуманное значение
    with open(p, "w", encoding="utf-8") as f:
        f.write("SAMPLE_LINE\n")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(";config\n")
    assert fontsize.get_font_size(td, "ajin") is None
    try:
        fontsize.set_font_size(td, "ajin", 30)
        raise AssertionError("должен был упасть")
    except FileNotFoundError:
        pass
with tempfile.TemporaryDirectory() as td:
    # файл только в asar: читаем оттуда, пишем в override с бэкапом
    os.makedirs(os.path.join(td, "resources", "app", "override"))
    asar_p = os.path.join(td, "resources", "app.asar")
    make_ajin_asar(asar_p, "[deffont size=42]\n".encode("utf-8"))
    assert fontsize.get_font_size(td, "ajin") == 42
    r = fontsize.set_font_size(td, "ajin", 28)
    assert r["size"] == 28
    ovr = os.path.join(td, "resources", "app", "override",
                       "data", "scenario", "first.ks")
    with open(ovr, encoding="utf-8") as f:
        assert "[deffont size=28]" in f.read()
    with open(ovr + fontsize.BACKUP_SUFFIX, "rb") as f:
        assert f.read() == "[deffont size=42]\n".encode("utf-8")
    assert fontsize.restore_font_size(td, "ajin") is True
with tempfile.TemporaryDirectory() as td:
    assert fontsize.get_font_size(td, "ajin") is None
print("   OK")

print()
print("ВСЕ ТЕСТЫ РАЗМЕРА ШРИФТА ПРОШЛИ")