# -*- coding: utf-8 -*-
"""Ren'Py-агент: шаблон компилируется для py2/py3, перевода в агенте нет
(только шрифт + читы), фолбэк-шрифт доступен, установка/очистка
game/ob_agent.rpy. Без Frida и игр."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("1) Шаблон агента компилируется для обеих веток (py2/py3)...")
from app.engines.renpy.agent import agent_source, agent_rpy_source
for abi in ("py2", "py3"):
    s = agent_source(1, "ob_fonts/NotoSans-Regular.ttf",
                     r"C:\x\NotoSans-Regular.ttf", abi)
    compile(s, "<agent>", "exec")
    assert "%PORT%" not in s and "%FONT_PATH%" not in s and "%ABI%" not in s
    assert "@@ABI:" not in s, "чужая ветка не вырезана"
    print("   ", abi, "OK:", len(s), "символов")

print("2) В агенте нет перевода — только шрифт, читы, состояние...")
s = agent_source(1, "ob_fonts/NotoSans-Regular.ttf", "", "py3")
assert "class _OB_FontMap" in s and "font_replacement_map" in s
assert "_patch_font" in s and "_font_restore" in s
assert "_run_cheat" in s and "_send_vars" in s and "_send_state" in s
assert "set_paused" not in s
assert "text_seen" not in s
assert "skip_dirty" not in s and "cache_dirty" not in s
assert "translate_string" not in s and "say_menu_text_filter" not in s
assert "FontGroup(" not in s
print("   OK")

print("3) agent_rpy_source: init python: + тело компилируется...")
rpy = agent_rpy_source(1, "ob_fonts/NotoSans-Regular.ttf", r"C:\x\a.ttf")
assert rpy.startswith("init python:")
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
import shutil
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
        shutil.rmtree(empty, ignore_errors=True)
print("   OK")

print()
print("ВСЕ ТЕСТЫ АГЕНТА ПРОШЛИ")
