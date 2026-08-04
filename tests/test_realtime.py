# -*- coding: utf-8 -*-
"""Реалтайм-пути: фиксеры строк, Ren'Py-escape [[, перевод через серверный
хук, шаблон агента (компилируется), фолбэк-шрифт. Без Frida/браузера."""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("1) _protect_interp/_restore_interp (Ren'Py-escape [[ и [expr])...")
from app.engines.renpy.tentacle import _protect_interp, _restore_interp
cases = [
    ("Misc [[Requires Restart]", ["[["]),
    ("A [[b] c", ["[["]),
    ("Hello [name]! {w} [gold]\n", ["[name]", "{w}", "[gold]", "\n"]),
    ("{size=16}{b}x[/b]{/size}", ["{size=16}", "{b}", "[/b]", "{/size}"]),
]
for s, expected in cases:
    masked, codes = _protect_interp(s)
    assert codes == expected, (s, codes)
    assert _restore_interp(masked, codes) == s
assert _restore_interp("без маркера", ["[x]"]) is None
print("   OK")

print("2) Серверный хук _on_translate...")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
from app.engines.renpy.tentacle import RenPyTentacle
t = RenPyTentacle()
t.set_translate_fn(lambda s: s.upper())
seen = []
t.text_seen.connect(lambda o, tr: seen.append((o, tr)))
t._on_translate({"type": "translate", "id": 1, "text": "Misc [[Requires Restart]"})
assert seen == [("Misc [[Requires Restart]", "MISC [[REQUIRES RESTART]")], seen
print("   OK")

print("3) Шаблон агента компилируется, шрифт-карта на месте...")
from app.engines.renpy.agent import agent_source, agent_rpy_source
s = agent_source(1, "ob_fonts/NotoSans-Regular.ttf",
                 r"C:\x\NotoSans-Regular.ttf")
compile(s, "<agent>", "exec")
assert "class _OB_FontMap" in s and "renpy.substitutions" in s
assert "FontGroup(" not in s
rpy = agent_rpy_source(1, "ob_fonts/NotoSans-Regular.ttf", r"C:\x\a.ttf")
body = "\n".join(ln[4:] for ln in rpy.split("\n")[1:])
compile(body, "<rpy_body>", "exec")
print("   OK")

print("4) Фолбэк-шрифт доступен вне игры...")
from app.engines.renpy.tentacle import _fallback_font_path, FONT_NAME
p = _fallback_font_path()
assert p and os.path.basename(p) == FONT_NAME and os.path.isfile(p)
with open(p, "rb") as f:
    assert f.read(4) == b"\x00\x01\x00\x00"  # TTF
print("   OK")

print("5) Установка/очистка game/ob_agent.rpy...")
import tempfile
from app.engines.renpy.tentacle import (install_agent_rpy, cleanup_agent_rpy,
                                        AGENT_RPY)
with tempfile.TemporaryDirectory() as td:
    game = os.path.join(td, "game")
    os.makedirs(game)
    assert install_agent_rpy(td, 5555)
    dst = os.path.join(game, AGENT_RPY)
    assert os.path.isfile(dst) and "5555" in open(dst, encoding="utf-8").read()
    assert install_agent_rpy(td, 5556)
    assert "5556" in open(dst, encoding="utf-8").read()
    cleanup_agent_rpy(td)
    assert not os.path.isfile(dst)
    empty = tempfile.mkdtemp()
    try:
        assert install_agent_rpy(empty, 5557) is False
    finally:
        import shutil
        shutil.rmtree(empty, ignore_errors=True)
print("   OK")

print()
print("ВСЕ ТЕСТЫ РЕАЛТАЙМА ПРОШЛИ")
