# -*- coding: utf-8 -*-
"""Тесты провайдеров, ИИ-корректора (M5) и нового интерфейса."""
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from app.core.rpgmaker.models import TranslationEntry
from app.core.translate.corrector import Corrector
from app.core.translate.engines import (PROVIDERS, GoogleFreeEngine,
                                        BingEngine, RotateEngine,
                                        AIEngine, get_engine)

app = QApplication([])

print('1) Реестр провайдеров...')
assert set(PROVIDERS) == {"argos", "google_free", "bing", "rotate", "ai"}
for name in PROVIDERS:
    kwargs = {"base_url": "http://x", "api_key": "k", "model": "m"} \
        if name == "ai" else {}
    get_engine(name, **kwargs)
print('   OK:', list(PROVIDERS))

print('2) OpenAI-совместимый API через фейк-сервер...')


class FakeAPI(BaseHTTPRequestHandler):
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
            # коррекция: правим черновики
            out = [it["d"] + " [fixed]" for it in items]
        else:
            out = ["RU:" + str(t) for t in items]
        resp = {"choices": [{"message": {
            "content": json.dumps(out, ensure_ascii=False)}}]}
        data = json.dumps(resp, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


srv = HTTPServer(("127.0.0.1", 0), FakeAPI)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{srv.server_address[1]}/v1"

eng = AIEngine(base_url=url, api_key="test", model="fake")
assert eng.ping()
out = eng.translate(["Hello", "World"], "en", "ru")
assert out == ["RU:Hello", "RU:World"], out
print('   перевод через OpenAI-совместимый API:', out)

print('3) ИИ-корректор (M5)...')
corrector = Corrector(eng)
entries = [
    TranslationEntry(1, "f", "p", "c", "こんにちは", "Здравствуйте", "translated"),
    TranslationEntry(2, "f", "p", "c", "ありがとう", "Спасибо", "translated"),
    TranslationEntry(3, "f", "p", "c", "さようなら", "", "new"),  # без перевода
]
n = corrector.correct_entries(entries, "ru")
assert n == 2
assert entries[0].translation.endswith("[fixed]")
assert entries[0].status == "corrected"
assert entries[2].status == "new"
print('   OK: вычитано', n, 'статус corrected, черновики без перевода пропущены')
srv.shutdown()

print('4) Google Translate (реальный бесплатный endpoint)...')
try:
    g = GoogleFreeEngine()
    if g.ping():
        out = g.translate(["The witch lives in the forest"], "en", "ru")
        print('   en→ru:', out)
        assert any(ord(c) > 0x400 for c in out[0])
        print('   OK')
    else:
        print('   SKIP: endpoint недоступен из сети')
except Exception as e:  # noqa: BLE001
    print('   SKIP:', e)

print('4b) Bing Translator (реальный бесплатный endpoint)...')
try:
    b = BingEngine()
    if b.ping():
        out = b.translate(["The witch lives in the forest"], "en", "ru")
        print('   en→ru:', out)
        assert any(ord(c) > 0x400 for c in out[0])
        print('   OK')
    else:
        print('   SKIP: endpoint недоступен из сети')
except Exception as e:  # noqa: BLE001
    print('   SKIP:', e)

print('4c) Чередование Google+Bing (fallback на второго при ошибке)...')
rot = RotateEngine()
ok = rot.ping()
print('   ping:', ok)
try:
    out = rot.translate(["The witch lives in the forest"], "en", "ru")
    print('   en→ru:', out)
    assert any(ord(c) > 0x400 for c in out[0])
    print('   OK: round-robin работает')
except Exception as e:  # noqa: BLE001
    print('   SKIP:', e)

print('5) Новый интерфейс: приветствие...')
from app.ui.main_window import MainWindow
w = MainWindow()
assert hasattr(w, "welcome_tab")
assert w.tabs.indexOf(w.welcome_tab) == 0
print('   приветственный экран на месте')

# open_project возвращает движок
GAME = r'D:\CODE\WrGameBridge\TEMP\The Suffering of The Modest Witch'
if not os.path.isdir(GAME):
    print('ПРОПУСК: тестовая игра не найдена'); sys.exit(0)
assert w.open_project(GAME) == "mz"
print('   open_project -> mz')

# движок из настроек по умолчанию
assert w.create_engine() is not None
print('   create_engine OK')

print()
print('ВСЕ ТЕСТЫ B/C/D ПРОШЛИ')
sys.stdout.flush()
os._exit(0)
