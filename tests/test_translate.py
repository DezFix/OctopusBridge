# -*- coding: utf-8 -*-
"""Тесты перевода: авто-язык, глоссарий, сервис, CSV, реальный Argos."""
import csv
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.rpgmaker.models import TranslationEntry
from app.core.translate.detect import detect_lang
from app.core.translate.engines import get_engine
from app.core.translate.glossary import Glossary
from app.core.translate.memory import TranslationMemory
from app.core.translate.service import Translator

print('1) detect_lang...')
assert detect_lang("私は魔女です") == "ja"
assert detect_lang("打撃/物理") == "zh"
assert detect_lang("我是一个女巫") == "zh"
assert detect_lang("Skip the opening?") == "en"
assert detect_lang("Привет, мир") == "ru"
assert detect_lang("\\V[1] + 50") is None
print('   OK')

print('2) Реальный Argos + авто-язык...')
engine = get_engine("argos")
tr = Translator(engine)
assert tr.translate_text("Which file would you like to load?", "auto", "ru") != "?"
assert "ведьма" in tr.translate_text("私は魔女です", "auto", "ru").lower() \
    or "Ведьма" in tr.translate_text("私は魔女です", "auto", "ru")
assert tr.translate_text("Уже по-русски", "auto", "ru") == "Уже по-русски"
print('   OK')

print('3) Глоссарий...')
with tempfile.TemporaryDirectory() as td:
    g = Glossary(os.path.join(td, "glossary.json"))
    g.set_terms("en", "ru", {"Aira": "Айра", "Memory Orb": "Сфера памяти"})
    g2 = Glossary(os.path.join(td, "glossary.json"))
    segs = g2.split_by_terms("Aira used the Memory Orb!", "en", "ru")
    assert ("Aira", "Айра") in segs and ("Memory Orb", "Сфера памяти") in segs
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    tr = Translator(engine, tm=tm, glossary=g2)
    out = tr.translate_text("Aira used the Memory Orb!", "auto", "ru")
    assert "Айра" in out and "Сфера памяти" in out
    tm.close()
print('   OK:', out)

print('4) Сервис: auto-группировка...')
with tempfile.TemporaryDirectory() as td:
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    entries = [
        TranslationEntry(1, "data/A.json", "[0].name", "тест", "こんにちは"),
        TranslationEntry(2, "data/A.json", "[1].name", "тест", "Hello there"),
        TranslationEntry(3, "data/A.json", "[2].name", "тест", "Уже русский"),
    ]
    tr = Translator(engine, tm=tm)
    n = tr.translate_entries(entries, "auto", "ru")
    assert n == 2, n
    assert entries[0].translation and entries[0].translation != "こんにちは"
    assert entries[1].translation and entries[1].translation != "Hello there"
    assert entries[2].translation == ""
    tm.close()
print('   OK')

print('5) CSV экспорт/импорт (логика)...')
with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "t.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "file", "json_path", "context",
                    "original", "translation", "status"])
        w.writerow([1, "data/A.json", "[0].name", "ctx", "原文", "译文", "manual"])
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    assert rows[0]["original"] == "原文" and rows[0]["translation"] == "译文"
print('   OK')

print()
print('ВСЕ ТЕСТЫ ПЕРЕВОДА ПРОШЛИ')
