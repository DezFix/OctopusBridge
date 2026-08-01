# -*- coding: utf-8 -*-
"""Реалтайм-фиксы перевода Ren'Py (issue: краши/непереведённые строки).

Юнит-уровень: фиксеры маски и Ren'Py-escape [[ в _protect_interp.
Живые проверки хука translate_string и префильтров агента —
в test_tentacles_renpy.py.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.translate import fixers

print("1) fix_leading_case...")
f = fixers.fix_leading_case
assert f("V[config.version]", "v[config.version]") == "v[config.version]"
assert f("Доброе утро", "Good morning") == "Доброе утро"
assert f("abc", "abc") == "abc"
assert f("", "") == ""
assert f("Привет", "Пока") == "Привет"
print("   OK")

print("2) fix_number_signs...")
g = fixers.fix_number_signs
assert g("Видимый день: 1", "Visible Day: -1") == "Видимый день: -1"
assert g("День доставки: 1", "Delivery Day: -1") == "День доставки: -1"
assert g("Дней: 1, Макс: 1", "Days: -1, Max: -1") == "Дней: -1, Макс: -1"
assert g("Рост: 0,92", "Height: 0.92") == "Рост: 0,92"   # минусов нет — не трогаем
assert g("Очки: -5", "Score: 5") == "Очки: -5"           # минус в переводе уже есть
assert g("Счёт 1 2", "Счёт 12") == "Счёт 1 2"            # число токенов не совпало
print("   OK")

print("3) apply_fixers (связка из реального лога)...")
h = fixers.apply_fixers
assert h("V[config.version]", "en", "ru", "v[config.version]") == "v[config.version]"
assert h("Видимый день: 1", "en", "ru", "Visible Day: -1") == "Видимый день: -1"
assert h("День доставки: 1", "en", "ru", "Delivery Day: -1") == "День доставки: -1"
print("   OK")

print("4) _protect_interp: Ren'Py-escape [[ ...")
try:
    from app.engines.renpy.tentacle import (_protect_interp, _restore_interp,
                                            RenPyTentacle)
except ImportError:
    print("   ПРОПУСК: tentacle не импортировался (нет frida?)")
    sys.exit(0)

p = _protect_interp
r = _restore_interp
masked, codes = p("Misc [[Requires Restart]")
assert codes == ["[["], codes
assert masked.count("[") == 0, masked
assert r(masked, codes) == "Misc [[Requires Restart]"

masked, codes = p("A [[b] c")
assert codes == ["[["], codes
assert r(masked, codes) == "A [[b] c"

masked, codes = p("Hello [name]! {w} [gold]\n")
assert codes == ["[name]", "{w}", "[gold]", "\n"], codes
assert r(masked, codes) == "Hello [name]! {w} [gold]\n"

masked, codes = p("{size=16}{b}x[/b]{/size}")
assert codes == ["{size=16}", "{b}", "[/b]", "{/size}"], codes
assert r(masked, codes) == "{size=16}{b}x[/b]{/size}"

assert r("без маркера", ["[x]"]) is None
print("   OK")

print("5) Серверный путь _on_translate: [[ доезжает до перевода...")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
app = QApplication([])
t = RenPyTentacle()
t.set_translate_fn(lambda s: s.upper())
out = []
t.text_seen.connect(lambda o, tr: out.append((o, tr)))
t._on_translate({"type": "translate", "id": 1, "text": "Misc [[Requires Restart]"})
assert out == [("Misc [[Requires Restart]", "MISC [[REQUIRES RESTART]")], out
out.clear()
t._on_translate({"type": "translate", "id": 2,
                 "text": "Hello [name]! {w} [gold]\nsecond line"})
assert out == [("Hello [name]! {w} [gold]\nsecond line",
                "HELLO [name]! {w} [gold]\nSECOND LINE")], out
print("   OK")

print("6) Шрифт доступен ВСЕГДА (фолбэк вне игры)...")
from app.engines.renpy.tentacle import _fallback_font_path, FONT_NAME
p = _fallback_font_path()
assert p and os.path.basename(p) == FONT_NAME and os.path.isfile(p), p
with open(p, "rb") as fh:
    assert fh.read(4) == b"\x00\x01\x00\x00"  # TTF/OTF header
print("   OK")

print("7) Шрифт: глобальная font_replacement_map (файлы игры не трогаются)...")
from app.engines.renpy.agent import agent_source, agent_rpy_source
s = agent_source(1, "ob_fonts/NotoSans-Regular.ttf",
                 r"C:\Users\x\AppData\Local\OctopusBridge\fonts\NotoSans-Regular.ttf")
compile(s, "<agent>", "exec")
assert "FontGroup(" not in s and "font.FontGroup" not in s, \
    "метод FontGroup должен быть выпилен"
assert "renpy.style.default.font = _g" not in s, "стили не правятся"
assert "_font_restore" in s and "_font_available" in s
assert "_OB_FONT_ABS, 0x0100" not in s
assert "class _OB_FontMap" in s, "wildcard-карта шрифтов должна быть в шаблоне"
assert "_OB_FontMap" in s
# интерполированные строки (меню "[item.title!i]") — хук подстановки
assert "renpy.substitutions" in s and "def _ob_sub" in s
# пути ассетов (DynamicImage) не переводятся: уважаем translate=False
assert "_OB_ASSET_RE" in s and "if _did and translate:" in s
print("   OK")

print("8) Встроенный RPY-агент (game/ob_agent.rpy)...")
rpy = agent_rpy_source(1, "ob_fonts/NotoSans-Regular.ttf",
                       r"C:\x\NotoSans-Regular.ttf")
assert rpy.startswith("init python:\n"), rpy[:40]
body = "\n".join(ln[4:] for ln in rpy.split("\n")[1:])
compile(body, "<rpy_body>", "exec")
import tempfile
with tempfile.TemporaryDirectory() as td:
    from app.engines.renpy.tentacle import (
        install_agent_rpy, cleanup_agent_rpy, AGENT_RPY)
    game = os.path.join(td, "game")
    os.makedirs(game)
    assert install_agent_rpy(td, 5555) is True
    dst = os.path.join(game, AGENT_RPY)
    assert os.path.isfile(dst)
    with open(dst, encoding="utf-8") as fh:
        assert "init python:" in fh.read()
    assert install_agent_rpy(td, 5556) is True
    with open(dst, encoding="utf-8") as fh:
        assert "5556" in fh.read()
    cleanup_agent_rpy(td)
    assert not os.path.isfile(dst)
    # вне структуры game/ — install невозможен
    empty_dir = tempfile.mkdtemp()
    try:
        assert install_agent_rpy(empty_dir, 5557) is False
    finally:
        import shutil
        shutil.rmtree(empty_dir, ignore_errors=True)
print("   OK")

print()
print("ВСЕ ТЕСТЫ РЕАЛТАЙМ-ФИКСОВ ПРОШЛИ")
sys.stdout.flush()
