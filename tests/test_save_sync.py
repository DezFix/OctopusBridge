# -*- coding: utf-8 -*-
"""Синк сейвов Twine: write_slots → .save, HTTP-эндпоинты /api/saves
(плагин окна → файлы), pending-import/import (приложение → игра)."""
import io
import json
import os
import sys
import tempfile
import threading
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.twine import savefile
from app.engines.twine.tentacle import (
    TwineTentacle,
    _InjectingHTTPHandler,
    _ThreadedHTTPServer,
)

GAME_HTML = '''<!DOCTYPE html>
<html><head><title>Test</title></head><body>
<tw-storydata name="Test Game" startnode="1"><tw-passagedata pid="1"></tw-passagedata></tw-storydata>
<script>var x = 1;</script>
</body></html>
'''

SAVE_DATA = {
    "id": "test-game",
    "state": {
        "index": 1,
        "history": [{
            "title": "start",
            "variables": {
                "money": 10,
                "name": "Valentin",
                "player": {"age": 21, "ava": True},
                "day": {"mast": 0, "piss": 1},
                "flags": [1, 2, 3],
            },
        }],
    },
}


def make_slot_b64(variables: dict) -> str:
    data = {
        "id": SAVE_DATA["id"],
        "state": {"index": 1, "history": [{"title": "start",
                                           "variables": variables}]},
    }
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return savefile.lz_compress_base64(text)


print("1) write_slots: слоты → .save файлы, round-trip через load_save...")
with tempfile.TemporaryDirectory() as td:
    b64 = make_slot_b64(SAVE_DATA["state"]["history"][0]["variables"])
    paths = savefile.write_slots(
        td, "Nautilus Valentinus ENG", [
            {"id": "0", "date": 1785744111343, "size": len(b64), "data": b64},
        ])
    assert len(paths) == 1, paths
    assert os.path.isfile(paths[0]), paths
    assert "slot0" in os.path.basename(paths[0]), paths
    data = savefile.load_save(paths[0])
    vars_ = savefile.get_variables(data)
    assert vars_["money"] == 10
    assert vars_["player"]["age"] == 21
    assert vars_["day"]["mast"] == 0
    assert savefile.flatten_variables(vars_)["player.ava"] is True
    # повторный синк перезаписывает тот же файл, дублей нет
    paths2 = savefile.write_slots(
        td, "Nautilus Valentinus ENG", [
            {"id": "0", "date": 1785744111343, "size": len(b64), "data": b64},
        ])
    assert paths2 == paths, (paths2, paths)
    saves = [f for f in os.listdir(td) if f.endswith(".save")]
    assert len(saves) == 1, saves
    print("   OK:", os.path.basename(paths[0]))

print("2) HTTP: POST /api/saves пишет файлы, GET pending-import, import...")
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, "index.html"), "w", encoding="utf-8") as f:
        f.write(GAME_HTML)

    received = {}

    def sync_cb(payload):
        received["payload"] = payload
        return len(savefile.write_slots(td, "Test Game",
                                        payload.get("saves", [])))

    _InjectingHTTPHandler.directory = td
    _InjectingHTTPHandler._game_html_rel = "index.html"
    _InjectingHTTPHandler._inject_html = False
    _InjectingHTTPHandler._shield_html = True
    _InjectingHTTPHandler._save_sync_cb = sync_cb
    with _InjectingHTTPHandler._import_lock:
        _InjectingHTTPHandler._import_payload = {}

    srv = _ThreadedHTTPServer(("127.0.0.1", 0), _InjectingHTTPHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        b64 = make_slot_b64(SAVE_DATA["state"]["history"][0]["variables"])
        body = json.dumps({"saves": [
            {"id": "0", "date": 1785744111343, "size": len(b64), "data": b64}]})
        req = urllib.request.Request(
            base + "/api/saves", data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            resp = json.loads(r.read().decode("utf-8"))
        assert resp == {"ok": True, "count": 1}, resp
        assert received["payload"]["saves"][0]["id"] == "0"
        files = [f for f in os.listdir(td) if f.endswith(".save")]
        assert len(files) == 1, files
        assert savefile.load_save(os.path.join(td, files[0]))["state"][
            "history"][0]["variables"]["money"] == 10

        with urllib.request.urlopen(base + "/api/saves/pending-import",
                                    timeout=5) as r:
            assert json.loads(r.read().decode("utf-8")) == {}

        with _InjectingHTTPHandler._import_lock:
            _InjectingHTTPHandler._import_payload = {
                "data": b64, "slot": "3"}
        with urllib.request.urlopen(base + "/api/saves/pending-import",
                                    timeout=5) as r:
            p = json.loads(r.read().decode("utf-8"))
        assert p == {"data": b64, "slot": "3"}, p

        req = urllib.request.Request(
            base + "/api/saves/import", data=b'{"applied":1}',
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            assert json.loads(r.read().decode("utf-8")) == {"ok": True}
        with _InjectingHTTPHandler._import_lock:
            assert _InjectingHTTPHandler._import_payload == {}

        # файл игры отдаётся с экраном ошибок и ЕДИНЫМ пэйлоадом моста
        # (состояние/читы/сейвы + live-перевод) — как в браузере
        with urllib.request.urlopen(base + "/index.html", timeout=5) as r:
            html = r.read().decode("utf-8")
        assert "error" in html.lower()
        assert "onerror" in html
        assert "twineInjected" in html
        assert "__octopus" in html
        assert "octopus-wrapper" in html  # гард обёртки окна в пэйлоаде
    finally:
        srv.shutdown()
        srv.server_close()

print("3) push_save_to_game: payload ставится, detach() сбрасывает...")
tent = TwineTentacle(use_webapp_window=True)
assert tent.push_save_to_game("ABC123", None) is True
with _InjectingHTTPHandler._import_lock:
    assert _InjectingHTTPHandler._import_payload == {"data": "ABC123",
                                                     "slot": None}
assert tent.push_save_to_game("DEF", "5") is True
with _InjectingHTTPHandler._import_lock:
    assert _InjectingHTTPHandler._import_payload == {"data": "DEF", "slot": "5"}
tent.detach()
with _InjectingHTTPHandler._import_lock:
    assert _InjectingHTTPHandler._import_payload == {}
assert _InjectingHTTPHandler._save_sync_cb is None
# браузерный режим не умеет пушить
tent2 = TwineTentacle(use_webapp_window=False)
assert tent2.push_save_to_game("X", None) is False
print("   OK")

print("3b) Live-перевод по WebSocket: tr_set/tr_dict/tr_state/tr_request...")


class FakeWS:
    """Замена _WSServer: ловит исходящие сообщения."""

    def __init__(self):
        self.sent = []

    def send(self, obj):
        self.sent.append(obj)
        return True

    def has_client(self):
        return True

    def stop(self):
        pass


tent = TwineTentacle(use_webapp_window=False)
fake = FakeWS()
tent._ws_server = fake

# подключение страницы: состояние перевода + словарь проекта
tent._tr_dict = {"Open door": "Открыть дверь"}
tent._on_ws_connect()
msgs = [m["type"] for m in fake.sent]
assert msgs == ["tr_set", "tr_dict"], fake.sent
assert fake.sent[0]["from"] == "auto" and fake.sent[0]["to"] == "ru"
assert fake.sent[0]["enabled"] is True
assert fake.sent[1]["data"] == {"Open door": "Открыть дверь"}

# смена языка программно → tr_set в игру
fake.sent.clear()
tent.set_tr_state("ja", "ru", True)
assert len(fake.sent) == 1 and fake.sent[0]["type"] == "tr_set"
assert fake.sent[0]["from"] == "ja"
assert tent.tr_state() == {"from": "ja", "to": "ru", "enabled": True}

# пользователь поменял язык/выключил прямо в игре → tr_state запоминается
# и уйдёт tr_set при следующем подключении страницы
tent._on_ws_message({"type": "tr_state", "enabled": False,
                     "from": "ja", "to": "en"})
assert tent.tr_state() == {"from": "ja", "to": "en", "enabled": False}
# частичное сообщение не ломает состояние
tent._on_ws_message({"type": "tr_state", "from": "zh"})
assert tent.tr_state() == {"from": "zh", "to": "en", "enabled": False}
fake.sent.clear()
tent._on_ws_connect()
assert fake.sent[0]["type"] == "tr_set"
assert fake.sent[0]["from"] == "zh" and fake.sent[0]["to"] == "en"
assert fake.sent[0]["enabled"] is False

# батч-перевод: колбэк приложения -> tr_result, статус ошибки очищен
calls = []
fake.sent.clear()
tent.set_tr_callback(lambda texts, f, t: calls.append((texts, f, t)) or [
    "Дверь открыта" if x == "Open door" else x for x in texts])
tent._on_ws_message({"type": "tr_request", "id": 7,
                     "lang_from": "auto", "lang_to": "ru",
                     "texts": ["Open door", "Hello"]})
assert calls == [(["Open door", "Hello"], "auto", "ru")], calls
tr = [m for m in fake.sent if m["type"] == "tr_result"]
assert tr and tr[0]["id"] == 7, fake.sent
assert tr[0]["results"] == ["Дверь открыта", "Hello"], tr[0]

# колбэк вернул неверное число строк -> оригиналами
fake.sent.clear()
tent.set_tr_callback(lambda texts, f, t: ["x"])
tent._on_ws_message({"type": "tr_request", "id": 8, "texts": ["a", "b"]})
tr = [m for m in fake.sent if m["type"] == "tr_result"]
assert tr[0]["results"] == ["a", "b"], tr[0]

# сбой провайдера -> оригиналами + один tr_status с причиной
def boom(texts, f, t):
    raise RuntimeError("LM Studio не запущен")

fake.sent.clear()
tent.set_tr_callback(boom)
tent._on_ws_message({"type": "tr_request", "id": 9, "texts": ["Hi"]})
tr = [m for m in fake.sent if m["type"] == "tr_result"]
st = [m for m in fake.sent if m["type"] == "tr_status"]
assert tr[0]["results"] == ["Hi"], tr[0]
assert st and "недоступен" in st[0]["msg"] and "LM Studio" in st[0]["msg"], st
# повторный сбой не спамит статус
tent._on_ws_message({"type": "tr_request", "id": 10, "texts": ["Hi"]})
assert len([m for m in fake.sent if m["type"] == "tr_status"]) == 1

# без колбэка -> дефолтный бесплатный Google (щупальце самодостаточно),
# а не «переводчик не настроен»
fake.sent.clear()
tent.set_tr_callback(None)
assert tent._tr_cb is not None and callable(tent._tr_cb)
# подменяем дефолт заглушкой, чтобы не ходить в сеть
orig_cb = tent._tr_cb
tent._tr_cb = lambda texts, f, t: ["Привет" if x == "Hi" else x
                                   for x in texts]
tent._on_ws_message({"type": "tr_request", "id": 11, "texts": ["Hi"]})
tr = [m for m in fake.sent if m["type"] == "tr_result"]
assert tr[0]["results"] == ["Привет"], tr[0]
tent._tr_cb = orig_cb

# мусорные типы сообщений не роняют
tent._on_ws_message({"type": "tr_applied", "count": 5})
tent.detach()
print("   OK")

print("4) flatten_variables: ВСЕ параметры (списки/глубина) + set по индексам...")
vars_ = {
    "money": 10,
    "player": {"age": 21, "ava": True},
    "day": {"mast": 0},
    "flags": [1, 2, 3],
    "inv": [{"id": 1, "qty": 2}, {"id": 5, "qty": 0}],
    "empty": {},
    "empty_list": [],
    "deep": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}},
    "none": None,
}
flat = savefile.flatten_variables(vars_)
assert flat["money"] == 10
assert flat["player.age"] == 21
assert flat["flags[0]"] == 1 and flat["flags[2]"] == 3
assert flat["inv[0].qty"] == 2
assert flat["deep.a.b.c.d.e.f"] == 1
assert flat["empty"] == "{}"
assert flat["empty_list"] == "[]"
assert flat["none"] is None
# round-trip через set_variables: индексы списков пишутся обратно
# (редактор шлёт все листья, включая неизменённые)
data = {"id": "t",
        "state": {"index": 1,
                  "history": [{"title": "s", "variables": {}}]}}
savefile.set_variables(data, {
    "flags[0]": 9, "flags[1]": 2, "flags[2]": 3,
    "inv[0].id": 1, "inv[0].qty": 2, "inv[1].id": 5, "inv[1].qty": 7,
    "player.age": 30, "new[2]": "x"})
v = savefile.get_variables(data)
assert v["flags"] == [9, 2, 3], v["flags"]
assert v["inv"][1]["qty"] == 7, v["inv"]
assert v["player"]["age"] == 30
assert v["new"] == [None, None, "x"], v["new"]
# глубокое дерево тоже собирается обратно
savefile.set_variables(data, {"deep.a.b.c": 5})
assert savefile.get_variables(data)["deep"]["a"]["b"]["c"] == 5
print("   OK")

print("ALL OK")
