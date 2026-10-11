# -*- coding: utf-8 -*-
"""HTML (generic): детект-приоритеты, инжекция без SugarCube,
tr_request->tr_result, webapp-обёртка в своей папке."""
import io
import os
import sys
import tempfile
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.engines.html import HtmlModule
from app.engines.twine import TwineModule

TWINE_HTML = ("<!DOCTYPE html><html><head><title>T</title></head>"
              "<body><tw-storydata name=\"T\">"
              "<tw-passagedata pid=\"1\" name=\"Start\">Hello</tw-passagedata>"
              "</tw-storydata></body></html>")
PLAIN_HTML = ("<!DOCTYPE html><html><head><title>My Game</title></head>"
              "<body><h1>Hello plain game</h1>"
              "<p>Some text to translate.</p>"
              "<script>var x = 1;</script></body></html>")


def write(path: str, text: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


print("1) detect: twine-игра -> Twine wins (60>10)...")
with tempfile.TemporaryDirectory() as td:
    write(os.path.join(td, "index.html"), TWINE_HTML)
    assert TwineModule.detect(td) == 60
    assert HtmlModule.detect(td) == 0
    from app.engines.registry import detect_engine, enabled_modules
    assert "html" in [c.key for c in enabled_modules()]
    mod = detect_engine(td)
    assert mod is not None and mod.key == "twine", mod
print("   OK")

print("2) detect: plain index.html -> html==10...")
with tempfile.TemporaryDirectory() as td:
    page = write(os.path.join(td, "index.html"), PLAIN_HTML)
    assert TwineModule.detect(td) == 0
    assert HtmlModule.detect(td) == 10
    from app.engines.registry import detect_engine
    mod = detect_engine(td)
    assert mod is not None and mod.key == "html", mod
    # цель-файл напрямую
    assert HtmlModule.detect(page) == 10
    # .htm верхнего регистра + подуровень
    sub = os.path.join(td, "sub")
    os.makedirs(sub)
    write(os.path.join(sub, "GAME.HTM"), PLAIN_HTML)
    assert HtmlModule.detect(td) == 10
print("   OK")

print("3) detect: rpgm/renpy-маркеры -> html 0...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "data"))
    write(os.path.join(td, "data", "System.json"), "{}")
    write(os.path.join(td, "index.html"), PLAIN_HTML)
    assert HtmlModule.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "www", "js"))
    write(os.path.join(td, "www", "js", "rpg_core.js"), "var a=1;")
    write(os.path.join(td, "index.html"), PLAIN_HTML)
    assert HtmlModule.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    write(os.path.join(td, "Map001.rpgmvm"), "x")
    write(os.path.join(td, "index.html"), PLAIN_HTML)
    assert HtmlModule.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "resources"))
    write(os.path.join(td, "resources", "app.asar"), "x")
    write(os.path.join(td, "index.html"), PLAIN_HTML)
    assert HtmlModule.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    write(os.path.join(td, "game", "script.rpy"), "label start:\n")
    write(os.path.join(td, "index.html"), PLAIN_HTML)
    assert HtmlModule.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    write(os.path.join(td, "game", "archive.rpa"), "x")
    assert HtmlModule.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "renpy"))
    write(os.path.join(td, "index.html"), PLAIN_HTML)
    assert HtmlModule.detect(td) == 0
with tempfile.TemporaryDirectory() as td:
    write(os.path.join(td, "notes.txt"), "hello")
    assert HtmlModule.detect(td) == 0
    assert HtmlModule.detect(os.path.join(td, "notes.txt")) == 0
print("   OK")

print("4) модуль: live-only, extract/apply no-op...")
m = HtmlModule(".")
assert HtmlModule.key == "html" and HtmlModule.title == "HTML"
assert HtmlModule.maturity == "experimental"
assert "live" in HtmlModule.features and "files" not in HtmlModule.features
assert m.extract(".") == []
assert m.apply(".", []) == {"files": 0, "strings": 0}
assert m.display == "HTML"
print("   OK")

print("5) инжекция: plain-страница сервится с PAYLOAD+TR без исключений...")
from app.engines.html.tentacle import HtmlTentacle, _HtmlHTTPHandler
with tempfile.TemporaryDirectory() as td:
    page = write(os.path.join(td, "index.html"), PLAIN_HTML)
    t = HtmlTentacle(use_webapp_window=False)
    t._game_path = page
    t._game_dir = td
    rel = "index.html"
    assert t._start_http(rel)
    try:
        _HtmlHTTPHandler._ws_url = "ws://127.0.0.1:9"
        _HtmlHTTPHandler._inject_html = True
        _HtmlHTTPHandler._shield_html = False
        url = f"http://127.0.0.1:{t._http_port}/{rel}"
        with urllib.request.urlopen(url, timeout=10) as r:
            assert r.status == 200
            body = r.read().decode("utf-8")
        assert "Hello plain game" in body  # оригинал цел
        assert "twineInjected" in body  # маркер PAYLOAD
        assert "__octopus" in body  # маркер моста
        assert "tr_request" in body  # маркер TR_SCRIPT
        # синка сейвов нет: любой POST — 404
        req = urllib.request.Request(url, data=b"{}", method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("POST обязан вернуть 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404, e.code
    finally:
        t._stop_http()
        t.deleteLater()
print("   OK")

print("6) tr_request->tr_result без SugarCube (стаб _tr_cb)...")
t2 = HtmlTentacle(use_webapp_window=False)
try:
    t2.set_tr_callback(lambda texts, lf, lt: ["RU:" + x for x in texts])
    sent: list = []

    class _FakeWS:
        def send(self, obj):
            sent.append(obj)
            return True

        def has_client(self):
            return True

    t2._ws_server = _FakeWS()
    t2._on_tr_request({"type": "tr_request", "id": 7,
                       "texts": ["Hello", "World"],
                       "lang_from": "auto", "lang_to": "ru"})
    res = [x for x in sent if x.get("type") == "tr_result"]
    assert len(res) == 1, sent
    assert res[0]["id"] == 7 and res[0]["results"] == ["RU:Hello", "RU:World"]
    # tr_state из игры запоминается
    t2._on_ws_message({"type": "tr_state", "enabled": False,
                       "from": "en", "to": "ru"})
    assert t2.tr_state() == {"from": "en", "to": "ru", "enabled": False}
    # коннект шлёт tr_set + tr_dict
    t2._tr_dict = {"Hi": "Hi"}
    sent.clear()
    t2._on_ws_connect()
    kinds = [x["type"] for x in sent]
    assert "tr_set" in kinds and "tr_dict" in kinds, kinds
    # словарь из entries
    t2._ws_server = _FakeWS()
    e = TranslationEntry(1, "f", "", "", "Hi", "Hi", "translated")
    assert t2.push_tr_dict([e]) is True
    # set_tr_callback(None) возвращает дефолт
    t2.set_tr_callback(None)
    assert t2._tr_cb == t2._default_tr_cb
    # записи переменных у HTML нет: общий поиск по окну страницы на
    # реальных HTML-играх ничего не находит, читы оставлены для Twine
    assert t2.set_variable("a", 1) is False
    assert t2.send_cheat("exec", code="1") is False
    assert not hasattr(t2, "_on_saves_sync")
    from app.engines.twine.tentacle import TwineTentacle
    assert hasattr(TwineTentacle, "_on_saves_sync")  # twine не тронут
finally:
    t2.deleteLater()
print("   OK")

print("7) webapp: своя папка, <title>, plugin без Save API...")
from app.engines.html import webapp as hweb
with tempfile.TemporaryDirectory() as td:
    page = write(os.path.join(td, "game.html"), PLAIN_HTML)
    assert hweb.game_title(page) == "My Game"
    no_title = write(os.path.join(td, "notitle.html"),
                     "<html><body>hi</body></html>")
    assert hweb.game_title(no_title) == "notitle"
    rel = hweb.install_webapp(td, "game.html", "My Game")
    assert rel == "octopus_htmlapp/index.html", rel
    assert not os.path.exists(os.path.join(td, "octopus_webapp"))
    wrapper = os.path.join(td, "octopus_htmlapp", "index.html")
    plug = os.path.join(td, "octopus_htmlapp", "plugin.js")
    assert os.path.isfile(wrapper) and os.path.isfile(plug)
    wtext = open(wrapper, encoding="utf-8").read()
    assert "octopus-wrapper" in wtext and "plugin.js" in wtext
    assert "My Game" in wtext
    ptext = open(plug, encoding="utf-8").read()
    assert "Save" not in ptext and "serialize" not in ptext
    assert "slots" not in ptext
    prof = hweb.profile_dir_for(page)
    assert prof.endswith("_html_profile"), prof
print("   OK")

print("8) create_tentacle('html')...")
from app.live import create_tentacle
tn = create_tentacle("html")
assert tn is not None and tn.key == "html", tn
assert tn.title == "HTML (HTTP+WS)"
tn.deleteLater()
assert create_tentacle("twine").key == "twine"
print("   OK")

print("ALL HTML TESTS PASSED")

print("9) TR_SCRIPT: menu markers (attrs/shadow/iframe/OPTION/tick/dedup)...")
import re as _re9
from app.engines.twine import tentacle as _tw9
_TR9 = _tw9.TR_SCRIPT
assert "shadowRoot" in _TR9, "no shadow DOM pierce"
assert "placeholder" in _TR9, "no placeholder"
assert "contentDocument" in _TR9, "no iframe walk"
for _a9 in ('"value"', '"placeholder"', '"title"', '"alt"'):
    assert _a9 in _TR9, "no attr " + _a9
_m9 = _re9.search(r"var SKIP_TAGS\s*=\s*\{([^}]*)\}", _TR9)
assert _m9, "SKIP_TAGS literal not found"
_skip9 = _m9.group(1)
assert "OPTION" not in _skip9, "OPTION must stay un-skipped: " + _skip9
for _t9 in ("SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA", "TEMPLATE",
            "INPUT", "SELECT", "CODE", "PRE"):
    assert _t9 in _skip9, "lost " + _t9
assert "setInterval" in _TR9 and "2000" in _TR9, "no 2000ms tick"
for _d9 in ("flying", "seen", "cache", "batchSeen", "hasWork"):
    assert _d9 in _TR9, "no dedup " + _d9
assert "500" in _TR9, "no 500 length cap"
assert "40" in _TR9 and "1800" in _TR9, "batch caps lost"
assert "=>" not in _TR9, "arrow functions banned (ES5)"
assert _re9.search(r"(?m)^\s*(const|let)\b", _TR9) is None, "const/let banned (ES5)"
assert ":passagedisplay" in _TR9, "SugarCube trigger lost"
print("   OK")

print("10) served synthetic menu page smoke...")
from app.engines.html.tentacle import HtmlTentacle as _HT10
from app.engines.html.tentacle import _HtmlHTTPHandler as _HH10
_MENU_HTML = ("<!DOCTYPE html><html><head><title>Menu Game</title></head>"
             "<body><h1>Main Menu</h1>"
             "<input type=\"button\" value=\"Start Game\">"
             "<input type=\"text\" placeholder=\"Enter name\">"
             "<button title=\"Options tooltip\">Options</button>"
             "<img src=\"x.png\" alt=\"Hero portrait\">"
             "<select><option>Easy</option><option>Hard</option></select>"
             "</body></html>")
with tempfile.TemporaryDirectory() as td:
    _page10 = write(os.path.join(td, "menu.html"), _MENU_HTML)
    _t10 = _HT10(use_webapp_window=False)
    _t10._game_path = _page10
    _t10._game_dir = td
    assert _t10._start_http("menu.html")
    try:
        _HH10._ws_url = "ws://127.0.0.1:9"
        _HH10._inject_html = True
        _HH10._shield_html = False
        _url10 = "http://127.0.0.1:%d/menu.html" % _t10._http_port
        with urllib.request.urlopen(_url10, timeout=10) as _r10:
            assert _r10.status == 200
            _body10 = _r10.read().decode("utf-8")
        for _o10 in ("Main Menu", "Start Game", "Enter name",
                     "Options tooltip", "Hero portrait", "Easy"):
            assert _o10 in _body10, "original lost: " + _o10
        for _k10 in ("twineInjected", "__octopus", "tr_request",
                     "shadowRoot", "placeholder", "contentDocument"):
            assert _k10 in _body10, "marker lost: " + _k10
    finally:
        _t10._stop_http()
        _t10.deleteLater()
print("   OK")

print("11) tr_request->tr_result regression...")
from app.engines.html.tentacle import HtmlTentacle as _HT11
_t11 = _HT11(use_webapp_window=False)
try:
    _t11.set_tr_callback(lambda texts, lf, lt: ["RU:" + x for x in texts])
    _sent11 = []
    class _FakeWS11:
        def send(self, obj):
            _sent11.append(obj)
            return True
        def has_client(self):
            return True
    _t11._ws_server = _FakeWS11()
    _t11._on_tr_request({"type": "tr_request", "id": 77,
                         "texts": ["Start Game", "Enter name"],
                         "lang_from": "auto", "lang_to": "ru"})
    _res11 = [x for x in _sent11 if x.get("type") == "tr_result"]
    assert len(_res11) == 1, _sent11
    assert _res11[0]["id"] == 77
    assert _res11[0]["results"] == ["RU:Start Game", "RU:Enter name"], _res11[0]
finally:
    _t11.deleteLater()
print("   OK")

print("ALL HTML TESTS PASSED (EXTENDED)")
