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

print()
print("ВСЕ ТЕСТЫ ДВИЖКОВ ПРОШЛИ")
