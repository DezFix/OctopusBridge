# -*- coding: utf-8 -*-
"""TyranoScript: детект, извлечение .ks (сегменты + атрибуты тегов),
внедрение с бэкапами и защитой переменных, кодировки, реестр, щупальце."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.tyrano import parser
from app.engines.tyrano import TyranoModule
from app.engines.registry import detect_engine

SAMPLE_KS = """\
;これはコメントです
*start
[l][r]
こんにちは、世界。
[wait time="500"]
[bg storage="bg_room.png"][r]
ルナ「はじめまして」
[link target="*choice1"]選んでください[/link]
[button name="ok" text="はい" target="*yes"][r]
[ruby text="日本語" ruby="にほんご"]と書く
%player_name のターン
[if exp="tf.flag == 1"]
[emb expr="tf.result"][r]
[iscript]
var x = 1; // JS-код не переводим
[endscript]
[er]
"""


def make_project(root: str) -> None:
    scenario = os.path.join(root, "data", "scenario")
    os.makedirs(scenario)
    os.makedirs(os.path.join(root, "tyrano"))
    with open(os.path.join(scenario, "main.ks"), "w",
              encoding="utf-8") as f:
        f.write(SAMPLE_KS)


print("1) Детект: tyrano/ + data/scenario -> вес, реестр находит модуль...")
with tempfile.TemporaryDirectory() as td:
    make_project(td)
    assert parser.detect(td) == 95
    mod = detect_engine(td)
    assert mod is not None and mod.key == "tyrano"
    assert TyranoModule.detect(td) == 95
# без tyrano/, но с .ks — тоже Tyrano
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "data", "scenario"))
    open(os.path.join(td, "data", "scenario", "a.ks"), "w").close()
    assert parser.detect(td) == 80
# чужая папка — не Tyrano
with tempfile.TemporaryDirectory() as td:
    assert parser.detect(td) == 0
print("   OK")

print("2) Извлечение: текст-сегменты, теги не входят в строки...")
with tempfile.TemporaryDirectory() as td:
    make_project(td)
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    assert "こんにちは、世界。" in texts
    assert "ルナ「はじめまして」" in texts
    assert "%player_name のターン" in texts
    # атрибуты тегов link/button/ruby
    assert "選んでください" in texts            # содержимое [link]...[/link]
    assert "はい" in texts                       # [button text="..."]
    assert "日本語" in texts                     # [ruby text="..."]
    # служебное не попало
    assert "これはコメントです" not in texts     # ;
    assert "start" not in texts                 # *label
    assert "bg_room.png" not in texts           # атрибуты bg не переводятся
    assert "var x = 1" not in texts             # [iscript] блок
    assert not any("[" in t for t in texts), texts  # тегов в строках нет
    # путь: line[N].seg[M] / line[N].tag[K].text
    paths = [e.json_path for e in entries]
    assert any(p.endswith(".tag[0].text") and "はい" == e.original
               for p, e in zip(paths, entries))
print("   OK:", [e.original for e in entries])

print("3) Внедрение: бэкап + перевод + повторное извлечение...")
with tempfile.TemporaryDirectory() as td:
    make_project(td)
    entries = parser.extract(td)
    for e in entries:
        e.translation = "ТЕСТ: " + e.original
        e.status = "translated"
    stats = parser.apply(td, entries)
    assert stats["strings"] == len(entries), stats
    assert len(stats["backups"]) == 1
    re_entries = parser.extract(td)
    assert all(x.original.startswith("ТЕСТ: ") for x in re_entries)
    # теги остались на месте после внедрения
    content = open(os.path.join(td, "data", "scenario", "main.ks"),
                   encoding="utf-8").read()
    assert '[link target="*choice1"]' in content
    assert '[button name="ok" text="' in content
print("   OK")

print("4) Защита от сдвига: оригинал изменился — запись пропускается...")
with tempfile.TemporaryDirectory() as td:
    make_project(td)
    entries = parser.extract(td)
    # портим вторую текстовую строку: "こんにちは、世界。" -> "こんばんは"
    ks = os.path.join(td, "data", "scenario", "main.ks")
    content = open(ks, encoding="utf-8").read()
    open(ks, "w", encoding="utf-8").write(
        content.replace("こんにちは、世界。", "こんばんは"))
    for e in entries:
        e.translation = "ТЕСТ: " + e.original
        e.status = "translated"
    stats = parser.apply(td, entries)
    re_entries = parser.extract(td)
    ok = sum(1 for x in re_entries if x.original.startswith("ТЕСТ: "))
    assert ok == len(entries) - 1, (ok, len(entries))
    assert not any(x.original.startswith("ТЕСТ: こんにちは")
                   for x in re_entries)
print("   OK")

print("5) Безопасность переменных: %var пропавший из перевода — пропуск...")
with tempfile.TemporaryDirectory() as td:
    make_project(td)
    entries = parser.extract(td)
    assert parser._is_var_safe("%player_name のターン",
                               "%player_name ходит")
    assert not parser._is_var_safe("%player_name のターン",
                                   "ходит")
    assert parser._is_var_safe("tf.x", "tf.x")
    assert not parser._is_var_safe("f.flag", "флаг")
    bad = next(e for e in entries if e.original == "%player_name のターン")
    bad.translation = "ходит"
    bad.status = "translated"
    stats = parser.apply(td, entries)
    assert stats["unsafe_skipped"] == 1
print("   OK")

print("6) Shift-JIS файлы читаются и пишутся в той же кодировке...")
with tempfile.TemporaryDirectory() as td:
    scenario = os.path.join(td, "data", "scenario")
    os.makedirs(scenario)
    path = os.path.join(scenario, "sjis.ks")
    raw = "こんにちは\n".encode("cp932")
    open(path, "wb").write(raw)
    entries = parser.extract(td)
    assert len(entries) == 1 and entries[0].original == "こんにちは"
    entries[0].translation = "Здравствуйте"
    entries[0].status = "translated"
    parser.apply(td, entries)
    data = open(path, "rb").read()
    assert data.decode("cp932") == "Здравствуйте\n"
print("   OK")

print("7) Electron-сборка TyranoBuilder: приложение в resources/app/...")
with tempfile.TemporaryDirectory() as td:
    app_dir = os.path.join(td, "resources", "app")
    os.makedirs(os.path.join(app_dir, "data", "scenario"))
    os.makedirs(os.path.join(app_dir, "tyrano"))
    with open(os.path.join(app_dir, "data", "scenario", "main.ks"),
              "w", encoding="utf-8") as f:
        f.write("こんにちは、世界。\n[wait time=\"500\"]\n")
    assert parser.detect(td) == 95
    entries = parser.extract(td)
    assert len(entries) == 1
    assert entries[0].file == "resources/app/data/scenario/main.ks"
    entries[0].translation = "Привет, мир."
    entries[0].status = "translated"
    stats = parser.apply(td, entries)
    assert stats["strings"] == 1
    out = open(os.path.join(app_dir, "data", "scenario", "main.ks"),
               encoding="utf-8").read()
    assert "Привет, мир." in out
    assert os.path.isdir(os.path.join(td, "backup"))
print("   OK")

print("8) Щупальце: выражения читов и пейлоад (без подключения)...")
from app.engines.tyrano.tentacle import TyranoTentacle
expr = TyranoTentacle._cheat_expr("get_vars")
assert "collectState" in expr
expr = TyranoTentacle._cheat_expr("var_set", name="%hp", value=100)
assert 'kag.variables["%hp"]' in expr and "100" in expr
expr = TyranoTentacle._cheat_expr("var_set", name="tf.flag", value=True)
assert "kag.tmp" in expr
expr = TyranoTentacle._cheat_expr("exec", code="1 + 1")
assert "1 + 1" in expr
assert TyranoTentacle._cheat_expr("nope") is None
# пейлоад — валидный JS: состояние/переменные для чит-вкладок,
# переводов в нём нет
payload = TyranoTentacle.PAYLOAD
assert "%d" not in payload
assert "collectState" in payload and "variablesFlat" in payload
assert "translate" not in payload
assert "MutationObserver" not in payload
print("   OK")

print("9) Щупальце: состояние/переменные через evaluate (без игры)...")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
_qapp = QApplication([])
t = TyranoTentacle()
results = {}
t.vars_received.connect(lambda v: results.update(vars=v))
t.state_received.connect(lambda s: results.update(state=s))
t.cheat_ack.connect(lambda *a: results.update(ack=a))
t.evaluate = lambda expr, **kw: (True, '{"variablesFlat": {"gold": 5}}')
assert t.request_vars()
assert results["vars"] == [{"name": "gold", "value": 5}], results
t.evaluate = lambda expr, **kw: (True, '{"type": "state", "gold": 7}')
assert t.request_state()
assert results["state"]["gold"] == 7, results
t.evaluate = lambda expr, **kw: (False, "boom")
assert not t.request_state()
assert not t.send_cheat("var_set", name="x", value=1)
assert results["ack"][0] == "var_set" and results["ack"][1] is False
t.deleteLater()
print("   OK")

print("10) Вложенные ] в атрибутах: text=\"a[b]\" переводится, тег цел...")
with tempfile.TemporaryDirectory() as td:
    scenario = os.path.join(td, "data", "scenario")
    os.makedirs(scenario)
    os.makedirs(os.path.join(td, "tyrano"))
    ks = os.path.join(scenario, "main.ks")
    content = ("[link text=\"a[b]\" target=\"*x\"]\n"
               "[emb expr=\"arr[0]\"]\n"
               "選択肢：\n"
               "[link text=\"選択肢[1]\" target=\"*y\"]\n")
    with open(ks, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    # текст атрибута со вложенной ] извлекается и переводится
    assert "a[b]" in texts
    assert "選択肢[1]" in texts
    assert "選択肢：" in texts
    # мусора от обрезанных тегов нет (хвосты атрибутов не уходят в перевод)
    assert not any("target" in t for t in texts)
    assert not any("]" in t and t not in ("a[b]", "選択肢[1]")
                   for t in texts), texts
    for e in entries:
        e.translation = "ТЕСТ: " + e.original
        e.status = "translated"
    stats = parser.apply(td, entries)
    assert stats["strings"] == len(entries), stats
    out = open(ks, encoding="utf-8").read()
    # теги целы, text="..." заменён внутри атрибута
    assert '[link text="ТЕСТ: a[b]" target="*x"]' in out
    assert '[emb expr="arr[0]"]' in out
    assert '[link text="ТЕСТ: 選択肢[1]" target="*y"]' in out
print("   OK:", texts)

print("11) CRLF и завершающий перевод строки сохраняются при внедрении...")
with tempfile.TemporaryDirectory() as td:
    scenario = os.path.join(td, "data", "scenario")
    os.makedirs(scenario)
    os.makedirs(os.path.join(td, "tyrano"))
    ks = os.path.join(scenario, "main.ks")
    raw = "こんにちは。\r\n[wait time=\"500\"]\r\n".encode("utf-8")
    with open(ks, "wb") as f:
        f.write(raw)
    entries = parser.extract(td)
    assert len(entries) == 1
    entries[0].translation = "Здравствуйте."
    entries[0].status = "translated"
    parser.apply(td, entries)
    out = open(ks, "rb").read()
    assert out == "Здравствуйте.\r\n[wait time=\"500\"]\r\n".encode("utf-8"), out
print("   OK")

print()
print("ВСЕ ТЕСТЫ TYRANO ПРОШЛИ")
