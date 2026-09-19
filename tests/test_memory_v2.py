# -*- coding: utf-8 -*-
"""Память переводов v2: WAL, нормализация, батчи, reuse между проектами."""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.translate.memory import TranslationMemory, normalize_source
from app.core.translate.service import Translator


class FakeEngine:
    def __init__(self):
        self.calls = 0

    def translate(self, texts, source, target, context_before=None,
                  context_after=None):
        self.calls += 1
        return [t.upper() for t in texts]

    def cancel(self):
        pass


def mk(id_, original, translation="", status="new"):
    return TranslationEntry(id_, "data/A.json", f"[{id_}]", "ctx",
                            original, translation, status)


def write_project(path, src, tgt, pairs):
    data = {
        "game_dir": "fake",
        "engine": "mz",
        "source_lang": src,
        "target_lang": tgt,
        "entries": [
            {"id": i, "file": "f", "json_path": f"[{i}]", "context": "",
             "original": s, "translation": t, "status": "new"}
            for i, (s, t) in enumerate(pairs)
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


print("1) точное совпадение (старый API get/put/put_many жив)...")
with tempfile.TemporaryDirectory() as td:
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    tm.put("Hello world", "Привет, мир", "en", "ru")
    assert tm.get("Hello world", "en", "ru") == "Привет, мир"
    assert tm.get("Hello world", "en", "de") is None
    assert tm.get("Unknown", "en", "ru") is None
    tm.close()
print("   OK")

print("2) совпадение по пробелам/переносам (нормализация)...")
assert normalize_source("  Привет\n\t мир  ") == "Привет мир"
with tempfile.TemporaryDirectory() as td:
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    tm.put("Hello   world", "Привет, мир", "en", "ru")
    assert tm.get("Hello world", "en", "ru") == "Привет, мир"
    assert tm.get("Hello\nworld", "en", "ru") == "Привет, мир"
    assert tm.get("  Hello\t\tworld  ", "en", "ru") == "Привет, мир"
    tm.close()
print("   OK")

print("3) put_many батч (одна транзакция, всё долетает)...")
with tempfile.TemporaryDirectory() as td:
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    pairs = [(f"source line {i}", f"перевод {i}") for i in range(1000)]
    tm.put_many(pairs, "en", "ru")
    assert tm.get("source line 0", "en", "ru") == "перевод 0"
    assert tm.get("source line 999", "en", "ru") == "перевод 999"
    assert tm.stats()["total"] == 1000, tm.stats()
    tm.close()
print("   OK")

print("4) WAL включён...")
with tempfile.TemporaryDirectory() as td:
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    mode = tm.db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal", mode
    tm.close()
print("   OK")

print("5) import_projects: второй проект подхватывает перевод первого...")
with tempfile.TemporaryDirectory() as td:
    proj_dir = os.path.join(td, "projects")
    os.makedirs(proj_dir)
    write_project(os.path.join(proj_dir, "game1.ob.json"), "en", "ru", [
        ("The sword is broken.", "Меч сломан."),
        ("Open the door.", "Открой дверь."),
        ("Not translated yet", ""),
    ])
    write_project(os.path.join(proj_dir, "game2.ob.json"), "en", "ru", [
        ("Уникальная строка второго", "Unique second"),
    ])
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    n = tm.import_projects(proj_dir)
    assert n == 3, n  # пустой translation не импортируется
    # reuse без движка: prefill находит перевод из game1
    tr = Translator(FakeEngine(), tm=tm)
    entries = [mk(1, "The   sword\nis broken."),  # другой whitespace — norm
               mk(2, "Open the door."),
               mk(3, "Something brand new")]
    hits = tr.prefill_from_memory(entries, "en", "ru")
    assert hits == 2, hits
    assert entries[0].translation == "Меч сломан."
    assert entries[0].status == "translated"
    assert entries[1].translation == "Открой дверь."
    assert entries[2].translation == "" and entries[2].status == "new"
    assert tr.engine.calls == 0  # движок не дёргался
    tm.close()
print("   OK")

print("6) обратная совместимость: legacy-таблица tm мигрирует в tm2...")
with tempfile.TemporaryDirectory() as td:
    import sqlite3
    db_path = os.path.join(td, "tm.sqlite")
    old = sqlite3.connect(db_path)
    old.execute("CREATE TABLE tm (source TEXT NOT NULL, src_lang TEXT NOT NULL,"
                " tgt_lang TEXT NOT NULL, target TEXT NOT NULL,"
                " PRIMARY KEY (source, src_lang, tgt_lang))")
    old.execute("INSERT INTO tm VALUES (?,?,?,?)",
                ("Legacy line", "en", "ru", "Наследие"))
    old.commit()
    old.close()
    tm = TranslationMemory(db_path)
    assert tm.get("Legacy line", "en", "ru") == "Наследие"
    assert tm.get("Legacy   line", "en", "ru") == "Наследие"  # norm после миграции
    tm.close()
print("   OK")

print("7) get_fuzzy / suggest_all / stats...")
with tempfile.TemporaryDirectory() as td:
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    tm.put("The ancient sword is broken.", "Древний меч сломан.", "en", "ru")
    hit = tm.get_fuzzy("The ancient sword is broke.", "en", "ru")
    assert hit is not None and hit[1] == "Древний меч сломан.", hit
    assert tm.get_fuzzy("Совсем другая строка здесь.", "en", "ru") is None
    sug = tm.suggest_all("The ancient sword is broke.", "en", "ru")
    assert sug and sug[0]["target"] == "Древний меч сломан.", sug
    assert tm.get("The ancient sword is broken.", "en", "ru") \
        == "Древний меч сломан."
    st = tm.stats()
    assert st["total"] == 1 and st["hits"] >= 1, st
    tm.close()
print("   OK")

print()
print("ВСЕ ТЕСТЫ ПАМЯТИ v2 ПРОШЛИ")
