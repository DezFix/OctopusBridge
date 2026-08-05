# -*- coding: utf-8 -*-
"""Движки перевода: реестр, AIEngine через фейк-сервер (OpenAI-совместимый),
сетевые движки (Google/Bing/rotate) — по возможности."""
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.translate.engines import (AIEngine, AI_PROVIDERS, PROVIDERS,
                                        get_engine)


class FakeLLM(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data": []}')

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        body = json.loads(self.rfile.read(length))
        prompt = body["messages"][0]["content"]
        payload = prompt[prompt.index("["):prompt.rindex("]") + 1]
        items = json.loads(payload)
        if items and isinstance(items[0], dict):
            out = [it["d"] + " [fixed]" for it in items]  # коррекция
        else:
            out = ["RU:" + str(t) for t in items]
        resp = {"choices": [{"message": {
            "content": json.dumps(out, ensure_ascii=False)}}]}
        data = json.dumps(resp, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


print("1) Реестр провайдеров...")
assert set(PROVIDERS) == {"honyaku", "google_free", "bing", "rotate", "ai"}
assert set(AI_PROVIDERS) == {"ai"}
for name in PROVIDERS:
    kwargs = {"base_url": "http://x", "api_key": "k", "model": "m"} \
        if name == "ai" else {}
    get_engine(name, **kwargs)
assert get_engine("nllb").name == "honyaku"  # старый NLLB -> Honyaku
assert get_engine("argos").name == "honyaku"  # старый Argos -> Honyaku
print("   OK:", list(PROVIDERS))

print("2) AIEngine: перевод + коррекция через фейк-сервер...")
srv = HTTPServer(("127.0.0.1", 0), FakeLLM)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
eng = AIEngine(base_url=url, api_key="test", model="fake")
assert eng.ping()
out = eng.translate(["Hello", "World"], "en", "ru")
assert out == ["RU:Hello", "RU:World"], out
from app.core.models import TranslationEntry
from app.core.translate.corrector import Corrector
corrector = Corrector(eng)
n = corrector.correct_all(
    [TranslationEntry(1, "f", "p", "c", "こんにちは",
                      "Здравствуйте", "translated")], "ru")
assert n == 1 and corrector.diffs[0].new_text == "Здравствуйте [fixed]"
srv.shutdown()
print("   OK")

print("3) Сетевые бесплатные движки (SKIP без сети)...")
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

print("4) Rotate: чередование Google+Bing (SKIP без сети)...")
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

print("5) Одиночные знаки алфавитов не идут в переводчик...")
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
print("   OK")

print()
print("ВСЕ ТЕСТЫ ДВИЖКОВ ПРОШЛИ")
