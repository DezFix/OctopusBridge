# -*- coding: utf-8 -*-
"""RPG Maker: фиксы аудита MV/MZ.

- вариантные коды «сменить имя/прозвище/профиль» (MV 320/322,
  MZ 321/323/324), таблицы не смешиваются;
- cmd 101 (заголовок диалога) — 4 параметра, текста нет;
- автотайл-таблицы: shape за границами не падает;
- apply(): компактный JSON остаётся компактным;
- resrefs: кэш потокобезопасен;
- runtime: перевод с маркерами {{LANG}}/{{COUNT}} не
  переподставляется (единственный проход).
"""
import io
import json
import os
import sys
import tempfile
import threading

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.rpgmaker import parser
from app.core.rpgmaker import maprender
from app.core.rpgmaker import resrefs
from app.core.rpgmaker import runtime


def make_project(root: str, variant: str = "mz") -> str:
    # маркеры детекта варианта + список плагинов (как в test_rpgmaker)
    if variant == "mv":
        data = os.path.join(root, "www", "data")
        os.makedirs(data)
        os.makedirs(os.path.join(root, "www", "js"))
        open(os.path.join(root, "www", "js", "rpg_core.js"), "w").close()
        with open(os.path.join(root, "www", "js", "plugins.js"), "w",
                  encoding="utf-8") as f:
            f.write("var $plugins = [];\n")
    else:
        data = os.path.join(root, "data")
        os.makedirs(data)
        os.makedirs(os.path.join(root, "js"))
        open(os.path.join(root, "js", "rmmz_core.js"), "w").close()
        with open(os.path.join(root, "js", "plugins.js"), "w",
                  encoding="utf-8") as f:
            f.write("var $plugins = [];\n")
    return data


def write_map(data_dir: str, page_list: list,
              display_name: str = "Мапа") -> None:
    mp = {
        "displayName": display_name,
        "width": 4, "height": 4,
        "data": [0] * 96,
        "events": [{"id": 1, "name": "EV001", "x": 0, "y": 0,
                    "pages": [{"conditions": {}, "image": {},
                               "list": page_list, "trigger": 0,
                               "switchId": 1}]}]
    }
    with open(os.path.join(data_dir, "Map001.json"), "w",
              encoding="utf-8") as f:
        json.dump(mp, f, ensure_ascii=False, separators=(",", ":"))


print("1) MZ: коды 321/323/324 — имя/прозвище/профиль...")
with tempfile.TemporaryDirectory() as td:
    data = make_project(td, "mz")
    write_map(data, [
        {"code": 321, "indent": 0, "parameters": [1, "Михаил"]},
        {"code": 323, "indent": 0, "parameters": [1, "Миша"]},
        {"code": 324, "indent": 0, "parameters": [1, "Профиль героя"]},
        {"code": 401, "indent": 0, "parameters": ["Привет"]},
        # 320 в MZ — экипировка: params[1] не имя, rename не давать
        {"code": 320, "indent": 0, "parameters": [1, "НеИмя"]},
    ])
    entries = parser.extract(td)
    rename = {e.original: e for e in entries
              if e.context.endswith("/ rename")}
    assert "Михаил" in rename, [e.original for e in entries]
    assert "Миша" in rename
    assert "Профиль героя" in rename
    for e in rename.values():
        assert e.file == "data/Map001.json"
        assert e.json_path.endswith(".parameters[1]")
    # таблицы не смешаны: MZ-код 320 не даёт rename
    assert "НеИмя" not in rename
print("   OK")

print("2) MV: коды 320/322 — имя/прозвище...")
with tempfile.TemporaryDirectory() as td:
    data = make_project(td, "mv")
    write_map(data, [
        {"code": 320, "indent": 0, "parameters": [1, "Михаил"]},
        {"code": 322, "indent": 0, "parameters": [1, "Миша"]},
        {"code": 401, "indent": 0, "parameters": ["Привет"]},
        # 324 в MV отсутствует (это MZ-профиль): rename не давать
        {"code": 324, "indent": 0, "parameters": [1, "НеПрозвище"]},
    ])
    entries = parser.extract(td)
    rename = {e.original: e for e in entries
              if e.context.endswith("/ rename")}
    assert "Михаил" in rename, [e.original for e in entries]
    assert "Миша" in rename
    for e in rename.values():
        assert e.file == "www/data/Map001.json"
        assert e.json_path.endswith(".parameters[1]")
    assert "НеПрозвище" not in rename
print("   OK")

print("3) cmd 101: ровно 4 параметра, текста нет...")
with tempfile.TemporaryDirectory() as td:
    data = make_project(td, "mz")
    write_map(data, [
        # 101 = [faceName, faceIndex, background, position] —
        # params[4] не существует, faceName — имя файла (не текст)
        {"code": 101, "indent": 0, "parameters": ["テスト顔", 0, 0, 0]},
        {"code": 401, "indent": 0, "parameters": ["Диалог"]},
    ])
    entries = parser.extract(td)
    originals = [e.original for e in entries]
    assert "Диалог" in originals
    # ничего из команды 101: ни имя файла лица, ни «имя говорящего»
    assert not [e for e in entries
                if e.json_path.startswith(
                    "events[0].pages[0].list[0]")]
    assert "テスト顔" not in originals
print("   OK")

print("4) Автотайлы: shape за границами таблицы — без падений...")
# A3 (WALL, 16 записей): shape = (4369 - 2048) % 48 = 17
parts = maprender.tile_parts(4369)
assert len(parts) == 4
# A1-водопад (WATERFALL, 4 записи): kind 5 нечётный, shape 40
parts = maprender.tile_parts(2048 + 5 * 48 + 40)
assert len(parts) == 4
# A4, нечётная строка (WALL, 16 записей): kind 88, ty 11, shape 20
parts = maprender.tile_parts(2048 + 88 * 48 + 20)
assert len(parts) == 4
# tile_source тоже не падает (вызывает tile_parts)
assert maprender.tile_source(4369) is not None
assert maprender.tile_source(2048 + 5 * 48 + 40) is not None
print("   OK")

print("5) apply(): компактный JSON остаётся компактным...")
with tempfile.TemporaryDirectory() as td:
    data = make_project(td, "mz")
    write_map(data, [
        {"code": 401, "indent": 0, "parameters": ["Оригинал"]},
    ])
    entries = parser.extract(td)
    for e in entries:
        e.translation = "ТР: " + e.original
        e.status = "translated"
    stats = parser.apply(td, entries)
    assert stats["files"] == 1 and stats["strings"] == len(entries)
    with open(os.path.join(data, "Map001.json"),
              encoding="utf-8") as f:
        text = f.read()
    # пересборка с компактными разделителями даёт тот же текст
    assert json.dumps(json.loads(text), ensure_ascii=False,
                      separators=(",", ":")) == text
    assert ": " not in text.replace("ТР: ", "")
print("   OK")

print("6) resrefs: кэш под потоками...")
with tempfile.TemporaryDirectory() as td:
    make_project(td, "mz")
    os.makedirs(os.path.join(td, "audio", "bgm"))
    with open(os.path.join(td, "audio", "bgm", "Тема.ogg"),
              "w", encoding="utf-8") as f:
        f.write("x")
    results: list[set] = []
    barrier = threading.Barrier(8)

    def _worker():
        barrier.wait()
        results.append(resrefs.build_index(td))

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8
    assert all(r == results[0] for r in results)
    assert "тема" in results[0] and "тема.ogg" in results[0]
    resrefs.clear_index(td)
    assert resrefs.build_index(td)  # пересборился после сброса
    resrefs.clear_index(td)
print("   OK")

print("7) runtime: маркеры внутри перевода не переподставляются...")
src = runtime.build_runtime_source(
    {"Ключ": "{{LANG}}/{{COUNT}}"}, "ru")
# маркер внутри перевода остался как есть (единственный проход)
assert "{{LANG}}/{{COUNT}}" in src
# обычные подстановки отработали
assert "targetLang=ru" in src
assert "entries=1" in src
assert "__octopus_trApply" in src
print("   OK")

print("\nВСЕ ПРОВЕРКИ test_rpgmaker_fixes ПРОЙДЕНЫ")

print("8) MV bridge pid matches renderer child...")
import subprocess as _ob8_sp
from http.server import BaseHTTPRequestHandler as _ob8_Handler
from http.server import HTTPServer as _ob8_HTTPServer
import threading as _ob8_threading
from app.core.rpgmaker import mv_bridge as _ob8_mvb
assert _ob8_mvb._pid_matches(os.getpid(), os.getpid()) is True
assert _ob8_mvb._pid_matches(os.getppid(), os.getpid()) is False
assert _ob8_mvb._pid_matches(None, os.getpid()) is False
assert _ob8_mvb._pid_matches(os.getpid(), None) is True
_ob8_child = _ob8_sp.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
try:
    assert _ob8_child.pid != os.getpid()
    assert _ob8_mvb._pid_matches(_ob8_child.pid, os.getpid()) is True
    assert _ob8_mvb._pid_matches(1073741824, os.getpid()) is False
    _ob8_probe_pid = _ob8_child.pid
    class _ob8_ProbeHandler(_ob8_Handler):
        def do_POST(self):
            _ob8_n = int(self.headers.get("Content-Length", "0"))
            try:
                self.rfile.read(_ob8_n)
            except Exception:
                pass
            _ob8_payload = json.dumps({"name": "octopus_ob", "pid": _ob8_probe_pid}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(_ob8_payload)))
            self.end_headers()
            self.wfile.write(_ob8_payload)
        def log_message(self, *args):
            pass
    _ob8_srv = _ob8_HTTPServer(("127.0.0.1", 0), _ob8_ProbeHandler)
    _ob8_port = _ob8_srv.server_address[1]
    _ob8_thr = _ob8_threading.Thread(target=_ob8_srv.serve_forever, daemon=True)
    _ob8_thr.start()
    try:
        assert _ob8_mvb.bridge_probe(_ob8_port, os.getpid()) is True
    finally:
        _ob8_srv.shutdown()
        _ob8_thr.join(timeout=5)
finally:
    _ob8_child.terminate()
    try:
        _ob8_child.wait(timeout=10)
    except Exception:
        _ob8_child.kill()
print("   OK")
