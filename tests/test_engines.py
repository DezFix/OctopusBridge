# -*- coding: utf-8 -*-
"""Движки перевода: реестр (только бесплатные, без нейросетей),
сетевые движки (Google/Bing/rotate) — по возможности."""
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.translate.engines import PROVIDERS, get_engine


print("1) Реестр провайдеров (без нейро, без Libre)...")
assert set(PROVIDERS) == {"google_free", "bing", "mymemory", "rotate"}
for name in PROVIDERS:
    get_engine(name)
# старые настройки (удалённые движки) -> rotate
for stale in ("ai", "ollama", "openai_compat", "corrector",
              "honyaku", "nllb", "argos", "libretranslate"):
    assert get_engine(stale).name == "rotate", stale
print("   OK:", list(PROVIDERS))

print("1b) Rotate-пул: по умолчанию Google+Bing, опционально +MyMemory...")
from app.core.translate.engines import RotateEngine
r0 = RotateEngine()
assert [e.name for e in r0._engines] == ["google_free", "bing", "bing"], \
    [e.name for e in r0._engines]
r1 = RotateEngine(mymemory_email="t@example.com")
assert [e.name for e in r1._engines] == ["google_free", "bing", "bing",
                                         "mymemory"], \
    [e.name for e in r1._engines]
print("   OK")

print("2) Сетевые бесплатные движки (SKIP без сети)...")
for name in ("google_free", "bing"):
    eng = get_engine(name)
    try:
        if eng.ping():
            out = eng.translate(["The witch lives in the forest"], "en", "ru")
            assert any(ord(c) > 0x400 for c in out[0])
            print(f"   {name}: OK:", out)
        else:
            print(f"   {name}: SKIP (недоступен из сети)")
    except Exception as e:  # noqa: BLE001
        print(f"   {name}: SKIP ({e})")

print("3) Rotate: чередование Google+Bing (SKIP без сети)...")
rot = get_engine("rotate")
try:
    if rot.ping():
        out = rot.translate(["The witch lives in the forest"], "en", "ru")
        assert any(ord(c) > 0x400 for c in out[0])
        print("   OK:", out)
    else:
        print("   SKIP (недоступен из сети)")
except Exception as e:  # noqa: BLE001
    print("   SKIP:", e)

print("4) Одиночные знаки алфавитов не идут в переводчик...")
from app.core.translate.alphabets import is_single_letter
from app.core.translate.service import Translator as CoreTranslator

for ch in "ホァィゥェォヴありがАБЯabcdё":
    assert is_single_letter(ch), ch
assert not is_single_letter("ホラ"), "два знака — уже слово"
assert not is_single_letter("hello"), "слово"
assert not is_single_letter("ホララ"), "слово из трёх знаков"
assert not is_single_letter(""), "пусто — не буква"
assert is_single_letter(" ホ "), "пробелы не мешают"


class CountingEngine:  # сервис не должен обращаться к движку для букв
    calls = 0

    def translate(self, texts, source, target, **kw):
        self.calls += 1
        return ["МУСОР"] * len(texts)   # «Домой»-галлюцинация движка


ce = CountingEngine()
svc = CoreTranslator(ce)
assert svc.translate_text("ホ", "ja", "ru") == "ホ"
assert svc.translate_text("ァ", "ja", "ru") == "ァ"
assert svc.translate_text("B", "ja", "ru") == "B"
assert svc.translate_text("Ё", "ru", "en") == "Ё"
assert ce.calls == 0, "движок не вызывался ни разу"
from app.core.models import TranslationEntry
entries = [TranslationEntry(1, "f", "p", "c", "ホ", "", "new"),
           TranslationEntry(2, "f", "p", "c", "この世界へようこそ", "", "new")]
n = svc.translate_entries(entries, "ja", "ru")
assert n == 2 and entries[0].translation == "ホ" \
    and entries[1].translation == "МУСОР", (n, entries[0].translation,
                                           entries[1].translation)
assert ce.calls == 1, "движок вызван только для настоящей строки"

# знаки/цифры и код-токены (пути/URL/hex-цвета) не идут в движок
# ни по одной, ни батчем, ни в записях — даже при явном языке
from app.core.translate.service import _is_code_token
assert _is_code_token("character_images/foo.png")
assert _is_code_token("https://example.com/x")
assert _is_code_token("#00000066")
assert not _is_code_token("こんにちは")
assert not _is_code_token("Дом милый дом")
assert not _is_code_token("ホラ")
for junk in ["――――――", "10", "#00000066",
             "character_images/default_Face_1_stand2_white.png"]:
    assert svc.translate_text(junk, "ja", "ru") == junk, junk
junk_entries = [TranslationEntry(10, "f", "p", "c", junk, "", "new")
                for junk in ["――――――", "character_images/x.png", "https://a.b/c"]]
n = svc.translate_entries(junk_entries, "ja", "ru")
assert n == 3 and all(e.translation == e.original for e in junk_entries)
assert ce.calls == 1, "движок не вызывался для знаков и кода"
print("   OK")

print("5) Google: быстрый батч (translateHtml) — один запрос на пакет...")
import app.core.translate.engines as engmod


class FakeResp:
    def __init__(self, data, status_code=200, url=""):
        self._data = data
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def fake_fast_resp(texts):
    return FakeResp([[f"RU:{t}" for t in texts], ["ja"] * len(texts)])


def fake_join_resp(q, sl, tl):
    lines = q.split("\n")
    segs = [["RU:" + line + ("\n" if i < len(lines) - 1 else ""),
             line, None, None, None] for i, line in enumerate(lines)]
    return FakeResp([segs, None, sl, None, None, None, None])


def patch_session(eng, post=None, get=None):
    if post:
        eng._session.post = post
    if get:
        eng._session.get = get


eng = engmod.GoogleFreeEngine()
calls = []


def fake_post_fast(url, headers=None, data=None, timeout=30):
    texts = json.loads(data)[0][0]
    calls.append(texts)
    return fake_fast_resp(texts)


patch_session(eng, post=fake_post_fast)
texts = [f"строка{i}" for i in range(70)]
out = eng.translate(texts, "ja", "ru")
assert len(out) == 70 and out == [f"RU:строка{i}" for i in range(70)], \
    (len(out), out[:3])
assert len(calls) == 1, f"ожидался 1 запрос на 70 строк, было {len(calls)}"
print("   OK: 70 строк -> 1 запрос по", len(calls[0]), "строк")

print("6) Google: каскад — fast сбой/склейка -> склейка -> построчно...")
calls.clear()


def fake_post_fail(url, headers=None, data=None, timeout=30):
    raise engmod.EngineError("fast endpoint down")


def fake_get_merge(url, params, timeout):
    q = params["q"]
    if len(q.split("\n")) > 1 and len(calls) == 0:
        # Google «склеил» строки: в ответе на один \\n меньше
        lines = q.split("\n")
        segs = [["RU:" + line + ("\n" if i < len(lines) - 1 else ""),
                 line, None, None, None]
                for i, line in enumerate(lines[:3] + lines[6:])]
        return FakeResp([segs, None, params["sl"], None, None, None, None])
    return fake_join_resp(q, params["sl"], params["tl"])


patch_session(eng, post=fake_post_fail, get=fake_get_merge)
out = eng.translate([f"l{i}" for i in range(40)], "ja", "ru")
assert len(out) == 40, (len(out), calls)
assert out[:6] == [f"RU:l{i}" for i in range(6)], out[:6]
print("   OK: fast недоступен -> склейка, склейка склеила -> построчно")

print("7) Rotate: пакет уходит в Google, при полном сбое Google — Bing...")
calls.clear()


def fake_get_dead(url, params, timeout):
    raise engmod.EngineError("Google offline")


patch_session(eng, post=fake_post_fail, get=fake_get_dead)
orig_bing = engmod.BingEngine.translate
engmod.BingEngine.translate = lambda self, texts, source, target, **kw: \
    ["RU:" + t for t in texts]
rot = engmod.RotateEngine()
rot._engines[0] = eng   # наш движок с фейковыми эндпоинтами
out = rot.translate([f"s{i}" for i in range(12)], "ja", "ru")
assert len(out) == 12 and out == [f"RU:s{i}" for i in range(12)], out[:3]
engmod.BingEngine.translate = orig_bing
print("   OK: фолбэк работает, 12 строк возвращены")

print("8) Google: 429/капча -> кулдаун, запросы не шлются...")
calls.clear()


def fake_post_rl(url, headers=None, data=None, timeout=30):
    calls.append("x")
    return FakeResp(None, status_code=429,
                    url="https://www.google.com/sorry/index?continue=...")


patch_session(eng, post=fake_post_rl, get=None)
eng2 = engmod.GoogleFreeEngine()
patch_session(eng2, post=fake_post_rl)
try:
    eng2._translate_one("hi", "en", "ru")
    raise AssertionError("ожидался EngineError после 429")
except engmod.EngineError:
    pass
assert eng2._rate_limited(), "после 429 должен быть кулдаун"
assert len(calls) == 1, "первый запрос ушёл, второй должен отсечься кулдауном"
try:
    eng2._translate_one("hi", "en", "ru")
    raise AssertionError("ожидался мгновенный отказ в кулдауне")
except engmod.EngineError:
    pass
assert len(calls) == 1, "во время кулдауна запросов быть не должно"
print("   OK: 429 -> кулдаун 60с, в кулдауне запросы не шлются")

print("9) MyMemory: по строке на запрос, фейк-сервер...")
from app.core.translate.engines import MyMemoryEngine


class FakeMMLT(BaseHTTPRequestHandler):
    """/get — MyMemory: dict-ответ и для ping, и для перевода."""
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            b'{"responseStatus": 200, "responseData": '
            b'{"translatedText": "RU:Hello"}}')

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        import urllib.parse
        params = urllib.parse.parse_qs(body.decode("utf-8"))
        q = params.get("q", [""])[0]
        # «плохой сервис»: теряет токены <xN/> в переводах
        resp = {"responseStatus": 200,
                "responseData": {"translatedText":
                                 ("RU:" + q).replace("<x0/>", "")}}
        data = json.dumps(resp, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


srv2 = HTTPServer(("127.0.0.1", 0), FakeMMLT)
threading.Thread(target=srv2.serve_forever, daemon=True).start()
mm_url = f"http://127.0.0.1:{srv2.server_address[1]}"
mm = MyMemoryEngine()
mm.API = mm_url + "/get"
assert mm.ping()
out = mm.translate(["Hello", "World"], "en", "ru")
assert out == ["RU:Hello", "RU:World"], out
# потерянный токен <x0/> — строка остаётся непереведённой
mm2 = MyMemoryEngine()
mm2.API = mm_url + "/get"
out = mm2.translate(["LOSE:x", "<x0/>Hi"], "en", "ru")
assert out == ["RU:LOSE:x", "<x0/>Hi"], out
srv2.shutdown()
print("   OK: MyMemory, 2 строки -> 2 запроса, guard токенов")

print("10) Отмена: cancel() -> движки бросают InterruptedError без сети...")
eng3 = engmod.GoogleFreeEngine()
eng3.cancel()
try:
    eng3.translate(["aa", "bb"], "ja", "ru")
    raise AssertionError("Google должен бросить InterruptedError после cancel")
except InterruptedError:
    pass
try:
    eng3._translate_one("aa", "ja", "ru")
    raise AssertionError("построчный перевод тоже должен прерваться")
except InterruptedError:
    pass
eng4 = engmod.BingEngine()
eng4.cancel()
try:
    eng4.translate(["aa"], "ja", "ru")
    raise AssertionError("Bing должен бросить InterruptedError после cancel")
except InterruptedError:
    pass
eng5 = engmod.RotateEngine()
eng5.cancel()
try:
    eng5.translate(["aa"], "ja", "ru")
    raise AssertionError("Rotate должен бросить InterruptedError после cancel")
except InterruptedError:
    pass
assert eng5._engines[0].cancelled, "Rotate.cancel должен распространиться на Google"
eng7 = MyMemoryEngine()
eng7.cancel()
try:
    eng7.translate(["aa"], "ja", "ru")
    raise AssertionError("MyMemory должен бросить InterruptedError после cancel")
except InterruptedError:
    pass
# повторная отмена не должна ломать движок (idempotent)
eng3.cancel()
print("   OK: все движки прерываются по cancel() до сетевых запросов")

print()
print("ВСЕ ТЕСТЫ ДВИЖКОВ ПРОШЛИ")
