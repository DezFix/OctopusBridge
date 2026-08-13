# -*- coding: utf-8 -*-
"""Ядро перевода: детект языка, маска кодов, глоссарий, память переводов,
сервис Translator, фиксеры, ИИ-корректор. Без сети — фейковый движок."""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.translate.corrector import Corrector
from app.core.translate.detect import detect_lang
from app.core.translate import fixers
from app.core.translate.glossary import Glossary
from app.core.translate.mask import (is_code_only, mask, split_edge_codes,
                                     unmask, validate)
from app.core.translate.memory import TranslationMemory
from app.core.translate.service import Translator


class FakeEngine:
    """Фейковый движок: переводит верхним регистром, сохраняет токены <xN/>."""

    def __init__(self, name="fake"):
        self.name = name

    def translate(self, texts, source, target, context_before=None,
                  context_after=None):
        return [t.upper() for t in texts]

    def complete(self, prompt):
        items = prompt[prompt.index("["):prompt.rindex("]") + 1]
        import json
        batch = json.loads(items)
        return json.dumps([it["d"] + " [fixed]" for it in batch],
                          ensure_ascii=False)

    def ping(self):
        return True


def mk(id_, original, translation="", status="new"):
    return TranslationEntry(id_, "data/A.json", f"[{id_}]", "ctx",
                            original, translation, status)


print("1) detect_lang...")
assert detect_lang("私は魔女です") == "ja"
assert detect_lang("打撃/物理") == "zh"
assert detect_lang("Skip the opening?") == "en"
assert detect_lang("Привет, мир") == "ru"
assert detect_lang("\\V[1] + 50") is None
print("   OK")

print("2) mask/unmask: коды и интерполяция Ren'Py...")
for s in (r'テスト\V[1]と\N[2]、\C[3]赤\C[0] \{大\} 100\%1',
          "Hello [name]! {w} [gold]",
          "Misc [[Requires Restart]",
          "[Save] обычный текст в скобках"):
    m, codes = mask(s)
    assert validate(m, codes) and unmask(m, codes) == s, s
assert unmask("без маркера", ["[x]"]) == "без маркера"
assert is_code_only(mask(r'\V[1]')[0])
assert not is_code_only("текст \\V[1]")
lead, mid, trail = split_edge_codes(r'\V[1]привет\c[8]')
assert lead == [r'\V[1]'] and trail == [r'\c[8]'] and mid == "привет"
print("   OK")

print("3) Глоссарий + память переводов...")
with tempfile.TemporaryDirectory() as td:
    g = Glossary(os.path.join(td, "glossary.json"))
    g.set_terms("en", "ru", {"Aira": "Айра", "Memory Orb": "Сфера памяти"})
    segs = g.split_by_terms("Aira used the Memory Orb!", "en", "ru")
    assert ("Aira", "Айра") in segs and ("Memory Orb", "Сфера памяти") in segs
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    tr = Translator(FakeEngine(), tm=tm, glossary=g)
    out = tr.translate_text("Aira used the Memory Orb!", "auto", "ru")
    assert "Айра" in out and "Сфера памяти" in out
    assert tm.get("Aira used the Memory Orb!", "en", "ru") == out
    tm.close()
print("   OK:", out)

print("4) Сервис: auto-язык, батчи, дедупликация, коды...")
with tempfile.TemporaryDirectory() as td:
    tm = TranslationMemory(os.path.join(td, "tm.sqlite"))
    tr = Translator(FakeEngine(), tm=tm)
    assert tr.translate_text("Уже по-русски", "auto", "ru") == "Уже по-русски"
    assert tr.translate_text("\\V[1]", "auto", "ru") == "\\V[1]"
    entries = [mk(1, "こんにちは"), mk(2, "Hello there"),
               mk(3, "Уже русский"), mk(4, "こんにちは")]
    n = tr.translate_entries(entries, "auto", "ru")
    assert n == 3, n
    assert entries[0].translation == "こんにちは".upper()
    assert entries[1].status == "translated"
    assert entries[3].translation == entries[0].translation  # дедуп
    assert entries[2].translation == ""
    tm.close()
print("   OK")

print("5) Фиксеры...")
f = fixers.apply_fixers
assert f("v[config.version]", "en", "ru", "v[config.version]") == "v[config.version]"
assert f("Видимый день: 1", "en", "ru", "Visible Day: -1") == "Видимый день: -1"
assert f("Хорошая погода。", "ja", "ru", "Good weather") == "Хорошая погода."
assert f("Привет", "en", "ru", "Привет") == "Привет"
assert fixers.fix_leading_case("V[config.version]", "v[config.version]") == "v[config.version]"
assert fixers.fix_number("Собрано 1 2 предметов", "Собрано ① ② предметов") == "Собрано ① ② предметов"
print("   OK")

print("6) ИИ-корректор (новый API correct_all/diffs)...")
corrector = Corrector(FakeEngine())
entries = [mk(1, "こんにちは", "Здравствуйте", "translated"),
           mk(2, "ありがとう", "Спасибо", "translated"),
           mk(3, "さようなら", "", "new")]
n = corrector.correct_all(entries, "ru")
assert n == 2, n
assert len(corrector.diffs) == 2
assert corrector.diffs[0].new_text == "Здравствуйте [fixed]"
assert entries[0].translation == "Здравствуйте"  # не применено до подтверждения
assert entries[2].status == "new"
corrector.cancel()
print("   OK")

print("7) Кеш проектов (размер/очистка/автоочистка)...")
import app.core.cache as app_cache
with tempfile.TemporaryDirectory() as td:
    app_cache.projects_dir = lambda: td
    for name in ("tmp_1.ob.json", "tmp_2.ob.json", "game.ob.json"):
        with open(os.path.join(td, name), "w", encoding="utf-8") as f:
            f.write("x" * 512)
    total, files = app_cache.projects_size()
    assert total == 512 * 3 and files == 3
    assert app_cache.is_tmp_project("tmp_x.ob.json")
    assert not app_cache.is_tmp_project("game.ob.json")
    freed = app_cache.clean_cache()
    assert freed == 1024
    total, files = app_cache.projects_size()
    assert total == 512 and files == 1  # настоящий проект цел
    # автоочистка: порог 1 МБ, кеш 512 байт — не чистим
    class S:
        @staticmethod
        def value(key, default=None, type=None):
            if key == "cache_auto_clean":
                return True
            if key == "cache_auto_clean_mb":
                return 1
            return default
    assert app_cache.maybe_auto_clean(S) is False
    # порог 0 — чистим
    class S2(S):
        @staticmethod
        def value(key, default=None, type=None):
            if key == "cache_auto_clean_mb":
                return 0
            return True
    assert app_cache.maybe_auto_clean(S2) is False  # tmp уже удалены
    assert app_cache.format_size(1536, "ru") == "0.0 МБ"
    assert app_cache.format_size(1024 ** 2 * 3, "ru") == "3.0 МБ"
    assert app_cache.format_size(1024 ** 3, "en") == "1.00 GB"
print("   OK")

print()
print("ВСЕ ТЕСТЫ ЯДРА ПРОШЛИ")
