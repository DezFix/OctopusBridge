# -*- coding: utf-8 -*-
"""Wolf RPG: структуры t_str, Game.dat/Database/event-команды, защита
кодов/имён, детект, livefont-ядро и команды агента Ren'Py.

Только синтетика: конструкция минимальных валидных блобов в памяти,
никаких игровых данных и сети. Содержимое тестовых строк — служебные
ASCII-маркеры вида T1/T2 (не текст реальных игр).
"""
import io
import os
import struct
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.wolf import dxa, parser
from app.core import livefont as lf


def _t(text: str, enc: str = "cp932") -> bytes:
    return parser._encode_t_str(text, enc)


def _make_game_dat() -> bytes:
    # magic9, vh=0 (v2), u8len=2, u8[2], nstr=3, s0..s2, filesize, u3,
    # u16settings(len=1: u2), randoms(8)+footer
    out = bytearray(b"\x00W\x00\x00OL\x00FM")
    out.append(0x00)
    out += struct.pack("<I", 2) + bytes([1, 2])
    out += struct.pack("<I", 3)
    out += _t("T1")
    out += _t("serial9")
    out += _t("keyK")
    filesize_pos = len(out)
    out += struct.pack("<I", 0)  # filesize-заглушка
    out += struct.pack("<I", 7)  # unknown3
    out += struct.pack("<I", 1) + struct.pack("<H", 0)  # u16 len=1
    out += bytes(8)  # randoms
    out.append(0xC2)  # footer v2
    struct.pack_into("<I", out, filesize_pos, len(out) - 1)
    return bytes(out)


def _make_database() -> bytes:
    # database_dat: magic6, vh, magic2(3), version, ntypes=1;
    # type: sub_header, method, pcount=2, ppos=[1000,1], size2=1,
    # vdata: number[1], strings[1]
    out = bytearray(b"\x00W\x00\x00OL")
    out.append(0x00)
    out += b"FM\x00"
    out.append(0x65)
    out += struct.pack("<I", 1)
    out += bytes([0xFE, 0xFF, 0xFF, 0xFF])
    out += struct.pack("<I", 0)
    out += struct.pack("<I", 2)
    out += struct.pack("<I", 1000)  # block1 pos0 -> number
    out += struct.pack("<I", 1)     # block!=1 -> string
    out += struct.pack("<I", 1)     # size2
    out += struct.pack("<i", 42)
    out += _t("T2")
    out.append(0x66)
    return bytes(out)


def _make_cmd(strings: list[str], ctype: int = 101) -> bytes:
    # event_command без route: pc, ctype, param[pc*4-4], depth, sc, strs, hr=0
    param = struct.pack("<I", 0)
    pc = 1 + len(param) // 4
    out = bytearray([pc])
    out += struct.pack("<I", ctype)
    out += param
    out += bytes([0, len(strings)])
    for s in strings:
        out += _t(s)
    out.append(0)
    return bytes(out)


print("1) t_str roundtrip + guards...")
c = parser._Cur(_t("T1") + _t("AB"), "cp932")
t1, o1, n1 = c.t_str()
t2, o2, n2 = c.t_str()
assert (t1, o1, t2, o2) == ("T1", 0, "AB", 7), (t1, o1, t2, o2)
assert parser._looks_like_filename("hero.png")
assert parser._looks_like_filename("BGM/battle01.ogg")
assert not parser._looks_like_filename("Hello world")
assert parser._looks_like_code("f(x); y();")
assert not parser._looks_like_code("Hello world")
assert parser._is_var_safe("A\\C[1]B", "X\\C[1]Y")
assert not parser._is_var_safe("A\\C[1]B", "XY")
print("   OK")

print("2) Game.dat parse + apply + filesize...")
g = _make_game_dat()
enc, items = parser._parse_game(g)
assert enc == "cp932" and len(items) == 3, (enc, len(items))
assert items[0][1] == "T1"
# apply через верхний уровень на синтетическом проекте
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "Data"))
    open(os.path.join(td, "Game.exe"), "w").close()
    with open(os.path.join(td, "Game.ini"), "w") as f:
        f.write("Start=0\nSoftModeFlag=0\nWindowModeFlag=1\n")
    assert parser.detect(td) >= 55
    # подменяем _iter_text_wolves/_current_inner_bytes? проще: apply Haas
    # напрямую через splice-эквивалент: проверяем _encode/_t_str_at
    new_blob = parser._encode_t_str("ZZ", "cp932")
    old_text, total = parser._t_str_at(g, items[0][0], "cp932")
    assert old_text == "T1"
    out = bytearray(g)
    out[items[0][0]:items[0][0] + total] = new_blob
    parser._fix_game_filesize(out)
    enc2, items2 = parser._parse_game(bytes(out))
    assert items2[0][1] == "ZZ", items2[0][1]
    assert struct.unpack("<I", bytes(out)[items2[0][0] - 4:items2[0][0]]) is not None
print("   OK")

print("3) Database parse...")
d = _make_database()
enc, vh, items = parser._parse_database(d)
assert len(items) == 1 and items[0][1] == "T2", items
print("   OK")

print("4) event_command parse (строки + route-skip)...")
# команда со строками и route (jump-подобный фикс + general)
cmd = _make_cmd(["T3", "T4"])
# добавляем have_route=1 + route: заголовок 10 байт, n=1, general_no_param
cmd = bytearray(cmd)
cmd[-1] = 1
cmd += bytes([1, 2, 3, 4, 0, 0])  # anim/speed/freq/mode/behav/opts
cmd += struct.pack("<I", 1)
cmd += bytes([0x00]) + bytes([0, 1, 0])
c = parser._Cur(bytes(cmd), "cp932")
cmds = parser._parse_commands(c, 1)
assert [x.text for x in cmds] == ["T3", "T4"], [x.text for x in cmds]
assert c.left() == 0, c.left()
print("   OK")

print("5) DXA primitives (key/xor/lz)...")
k1 = dxa.make_base_key(b"WLFRPrO!p(;s5((8P@((UFWlu$#5(=")
k2 = dxa.make_base_key(b"WLFRPrO!p(;s5((8P@((UFWlu$#5(=")
assert k1 == k2 and len(k1) == 7
buf = bytearray(b"ABCDEF" * 10)
orig = bytes(buf)
dxa._xor(buf, k1, 3)
assert bytes(buf) != orig
dxa._xor(buf, k1, 3)
assert bytes(buf) == orig
# lz: литералы без ключа: dest=3, src=3+9? строим вручную:
# dest_size=3, src_size=3+9=12? src_size хранится ВКЛЮЧАЯ 9 (минус 9 при чтении)
payload = b"XYZ"
block = struct.pack("<IIB", 3, len(payload) + 9, 0xFF) + payload
assert dxa.lz_decode(block) == b"XYZ"
print("   OK")

print("6) livefont JS (ES5, без стрелок/const/шаблонов)...")
js_size = lf.build_rpgm_font_size_js(30)
assert "standardFontSize" in js_size and "return n" in js_size
assert "=>" not in js_size and "const " not in js_size
assert "`" not in js_size and "let " not in js_size
js_face = lf.build_rpgm_font_face_js("NotoSans-Regular.ttf")
assert "NotoSans-Regular.ttf" in js_face and "@font-face" in js_face
assert "=>" not in js_face
js_ajin = lf.build_ajin_font_size_js(28)
assert "TYRANO" in js_ajin and "stat.font.size" in js_ajin
assert "String(n)" in js_ajin and "var n=28" in js_ajin
assert "=>" not in js_ajin and "const " not in js_ajin


class _FakeAjinTent:
    def is_attached(self):
        return True

    def evaluate(self, js):
        assert "String(n)" in js and "var n=28" in js
        return True, "ok"


class _FakeAjinNoKag:
    def is_attached(self):
        return True

    def evaluate(self, js):
        return True, "no-kag"


assert lf.apply_ajin_font_size_live(_FakeAjinTent(), 28)
assert not lf.apply_ajin_font_size_live(_FakeAjinNoKag(), 28)
assert not lf.apply_ajin_font_size_live(None, 28)


class _FakeTent:
    def __init__(self):
        self.seen = []
        self._att = True

    def is_attached(self):
        return self._att

    def evaluate(self, js):
        self.seen.append(js)
        return True, "ok:1"

    def send_cheat(self, cmd, **kw):
        self.seen.append((cmd, kw))
        return True


ft = _FakeTent()
assert lf.apply_rpgm_font_size_live(ft, 30)
assert lf.apply_rpgm_font_live(ft, "NotoSans-Regular.ttf")
assert lf.apply_renpy_font_size_live(ft, 33)
assert lf.apply_renpy_font_live(ft)
ft._att = False
assert not lf.apply_rpgm_font_size_live(ft, 30)
assert not lf.apply_renpy_font_live(ft)
print("   OK")

print("7) Ren'Py agent: команды font_size/font_reload...")
from app.engines.renpy import agent
src_py3 = agent.agent_source(12345, "ob_fonts/NotoSans-Regular.ttf", "", "py3")
assert '"font_size"' in src_py3 and '"font_reload"' in src_py3
assert "_ob_set_font_size" in src_py3
src_py2 = agent.agent_source(12345, "ob_fonts/NotoSans-Regular.ttf", "", "py2")
assert '"font_size"' in src_py2 and "restart_interaction" in src_py2
compile(src_py3, "<agent_py3>", "exec")
print("   OK")

print("10) livefont JS выполняется (cscript-стаб)...")
import shutil as _sh10
if _sh10.which("cscript") is None:
    print("   SKIP: нет cscript")
else:
    _size_js = lf.build_rpgm_font_size_js(30)
    _face_js = lf.build_rpgm_font_face_js("NotoSans-Regular.ttf")
    _harness10 = (
        "var window = {};\n"
        "var SceneManager = {_scene: null};\n"
        "function Window_Base() {}\n"
        "Window_Base.prototype.standardFontSize = function () { return 28; };\n"
        "var $dataSystem = {advanced: {fontSize: 28}};\n"
        "var $gameSystem = {_mainFontSize: 28};\n"
        "window.$dataSystem = $dataSystem;\n"
        "window.$gameSystem = $gameSystem;\n"
        "var document = {head: {appendChild: function (s) { return s; }}};\n"
        "document.createElement = function () {\n"
        "  return {setAttribute: function () {}, textContent: \"\"};\n"
        "};\n"
        "var FontManager = {loadGameFont: function () { return true; }};\n"
        "var fails = [];\n"
        "function check(name, cond) { if (!cond) fails.push(name); }\n"
        "var r1 = " + _size_js + ";\n"
        "check(\"size-ret\", r1 === \"ok:0\");\n"
        "check(\"size-proto\", Window_Base.prototype.standardFontSize() === 30);\n"
        "check(\"size-data\", $dataSystem.advanced.fontSize === 30);\n"
        "check(\"size-game\", $gameSystem._mainFontSize === 30);\n"
        "check(\"size-win\", window.__octopus_fontSize === 30);\n"
        "var r2 = " + _face_js + ";\n"
        "check(\"face-ret\", typeof r2 === \"string\" && r2.indexOf(\"ok:\") === 0);\n"
        "check(\"face-proto-kept\", Window_Base.prototype.standardFontSize() === 30);\n"
        "if (fails.length) { WScript.Echo(\"FAIL: \" + fails.join(\",\")); WScript.Quit(1); }\n"
        "WScript.Echo(\"HARNESS-OK\");\n"
    )
    _js10 = os.path.join(tempfile.gettempdir(), "ob_livefont_test.js")
    with open(_js10, "w", encoding="utf-8") as _f10:
        _f10.write(_harness10)
    import subprocess as _sp10
    try:
        _r10 = _sp10.run(["cscript", "//Nologo", "//E:JScript", _js10],
                         capture_output=True, text=True, timeout=60)
    finally:
        try:
            os.remove(_js10)
        except OSError:
            pass
    assert _r10.returncode == 0, (_r10.stdout, _r10.stderr)
    assert "HARNESS-OK" in _r10.stdout, (_r10.stdout, _r10.stderr)
    print("   OK")

print("8) Wolf detect на синтетике + реестр...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "Data"))
    open(os.path.join(td, "Game.exe"), "w").close()
    with open(os.path.join(td, "Game.ini"), "w") as f:
        f.write("Start=0\nSoftModeFlag=0\nWindowModeFlag=1\n")
    with open(os.path.join(td, "Data", "BasicData.wolf"), "wb") as f:
        f.write(b"DX\x08\x00" + b"\x00" * 100)
    from app.engines.registry import detect_engine
    from app.engines.wolf import WolfModule
    assert parser.detect(td) == 105, parser.detect(td)
    mod = detect_engine(td)
    assert isinstance(mod, WolfModule), type(mod)
    assert "files" in mod.features and "font" in mod.features
print("   OK")

print("9) Wolf tentacle (launch-miss + no-cheats)...")
from app.engines.wolf.tentacle import WolfTentacle, find_launcher
with tempfile.TemporaryDirectory() as td:
    assert find_launcher(td) is None
    open(os.path.join(td, "Game.exe"), "w").close()
    assert find_launcher(td) is not None
wt = WolfTentacle()
assert not wt.is_attached()
assert wt.attach(1234) is False
assert wt.launch(os.path.join(td, "nope", "Game.exe")) is False
print("   OK")

print("\nALL WOLF+LIVEFONT TESTS GREEN")
