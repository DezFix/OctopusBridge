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
    app_cache.temp_dir = lambda: os.path.join(td, "temp")
    os.makedirs(app_cache.temp_dir(), exist_ok=True)
    for name in ("tmp_1.ob.json", "tmp_2.ob.json", "game.ob.json"):
        with open(os.path.join(td, name), "w", encoding="utf-8") as f:
            f.write("x" * 512)
    total, files = app_cache.projects_size()
    assert total == 512 * 3 and files == 3
    assert app_cache.is_tmp_project("tmp_x.ob.json")
    assert not app_cache.is_tmp_project("game.ob.json")
    # кеш живёт в temp-папке
    with open(os.path.join(app_cache.temp_dir(), "tmp_t.ob.json"),
              "w", encoding="utf-8") as f:
        f.write("x" * 1024)
    assert app_cache.temp_size() == (1024, 1)
    freed = app_cache.clean_cache()
    assert freed == 1024
    assert app_cache.temp_size() == (0, 0)
    # автоочистка: порог 1 МБ, кеш пуст — не чистим
    class S:
        @staticmethod
        def value(key, default=None, type=None):
            if key == "cache_auto_clean":
                return True
            if key == "cache_auto_clean_mb":
                return 1
            return default
    assert app_cache.maybe_auto_clean(S) is False
    # tmp-файлы в projects — старый формат, кнопкой не удаляются,
    # только миграцией при старте
    assert app_cache.format_size(1536, "ru") == "0.0 МБ"
    assert app_cache.format_size(1024 ** 2 * 3, "ru") == "3.0 МБ"
    assert app_cache.format_size(1024 ** 3, "en") == "1.00 GB"
print("   OK")

print("8) Миграция структуры APPDATA (temp/glossary)...")
import app as app_paths
with tempfile.TemporaryDirectory() as td:
    old = os.environ.get("APPDATA")
    os.environ["APPDATA"] = td
    try:
        root = app_paths.user_data_dir()
        os.makedirs(os.path.join(root, "projects"), exist_ok=True)
        for p in (os.path.join(root, "glossary.json"),
                  os.path.join(root, "projects", "tmp_old.ob.json"),
                  os.path.join(root, "projects", "game.ob.json")):
            with open(p, "w", encoding="utf-8") as f:
                f.write("{}")
        app_paths.migrate_appdata()
        assert os.path.isfile(os.path.join(root, "glossary",
                                           "glossary.json"))
        assert not os.path.isfile(os.path.join(root, "glossary.json"))
        assert os.path.isfile(os.path.join(root, "temp",
                                           "tmp_old.ob.json"))
        assert os.path.isfile(os.path.join(root, "projects",
                                           "game.ob.json"))
        assert not os.path.isfile(os.path.join(root, "projects",
                                               "tmp_old.ob.json"))
    finally:
        if old is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old
print("   OK")

print("9) atomic_write: цел при обрыве + read_json_safe...")
import json as _json2
from app.core.io import (atomic_write_bytes, atomic_write_json,
                         atomic_write_text, read_json_safe)
with tempfile.TemporaryDirectory() as td:
    # базовые записи
    p_txt = os.path.join(td, "a.txt")
    atomic_write_text(p_txt, "привет")
    assert open(p_txt, encoding="utf-8").read() == "привет"
    p_bin = os.path.join(td, "a.bin")
    atomic_write_bytes(p_bin, b"\x00\x01\x02")
    assert open(p_bin, "rb").read() == b"\x00\x01\x02"
    p_js = os.path.join(td, "a.json")
    big = {"entries": [{"id": i, "t": "x" * 100} for i in range(2000)]}
    atomic_write_json(p_js, big)
    with open(p_js, encoding="utf-8") as f:
        assert _json2.load(f)["entries"][0]["id"] == 0
    orig_bytes = open(p_js, "rb").read()
    # read_json_safe: успех и ошибка без исключений
    obj, err = read_json_safe(p_js)
    assert err is None and obj["entries"][1999]["id"] == 1999
    obj2, err2 = read_json_safe(os.path.join(td, "nope.json"))
    assert obj2 is None and isinstance(err2, Exception)
    with open(os.path.join(td, "bad.json"), "w", encoding="utf-8") as f:
        f.write("{не json")
    obj3, err3 = read_json_safe(os.path.join(td, "bad.json"))
    assert obj3 is None and err3 is not None
    # симуляция обрыва: os.replace падает — оригинал обязан уцелеть
    import app.core.io as _io_mod
    real_replace = os.replace
    def _boom(src, dst):
        raise OSError("simulated crash before replace")
    os.replace = _boom
    try:
        try:
            atomic_write_json(p_js, {"broken": True})
            assert False, "должно было упасть"
        except OSError:
            pass
    finally:
        os.replace = real_replace
    assert open(p_js, "rb").read() == orig_bytes, "оригинал затёрт при обрыве!"
    # tmp-мусор после обрыва не остаётся
    leftovers = [n for n in os.listdir(td) if n.startswith(".tmp-")]
    assert leftovers == [], leftovers
    # ошибка сериализации тоже не трогает оригинал
    try:
        atomic_write_json(p_js, {"x": object()})
        assert False, "должно было упасть на TypeError"
    except TypeError:
        pass
    assert open(p_js, "rb").read() == orig_bytes
print("   OK")

print("10) BackupStore: версионирование + restore_all...")
from app.core.io import BackupStore
with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "game.ob.json")
    with open(src, "w", encoding="utf-8") as f:
        f.write('{"v": 1}')
    store_dir = os.path.join(td, "backups")
    st = BackupStore(store_dir)
    b1 = st.backup(src)
    assert b1 and os.path.isfile(b1)
    assert open(b1, encoding="utf-8").read() == '{"v": 1}'
    assert os.path.isfile(os.path.join(store_dir, "manifest.json"))
    # меняем исходник — повторный backup НЕ перезаписывает
    with open(src, "w", encoding="utf-8") as f:
        f.write('{"v": 2}')
    b2 = st.backup(src)
    assert b2 == b1, (b1, b2)
    assert open(b1, encoding="utf-8").read() == '{"v": 1}'
    # restore_all возвращает оригинал из бэкапа (атомарно)
    r = st.restore_all()
    assert r["restored"] == 1, r
    assert open(src, encoding="utf-8").read() == '{"v": 1}'
    # второй стор на той же папке видит манифест
    st2 = BackupStore(store_dir)
    assert st2.backup(src) == b1
print("   OK")

print("11) Битый .ob.json -> карантин + fallback на .bak...")
from app.core.models import Project
with tempfile.TemporaryDirectory() as td:
    pf = os.path.join(td, "game_abc.ob.json")
    bak = pf + ".bak"
    p = Project(game_dir="G", engine="mz")
    from app.core.models import TranslationEntry as _TE
    p.entries = [_TE(1, "data/A.json", "[0]", "ctx", "hello", "привет",
                     "translated")]
    atomic_write_json(pf, p.to_dict())
    # страховка как в save_project: целая копия -> .bak
    atomic_write_bytes(bak, open(pf, "rb").read())
    # старые .ob.json (минимум полей) читаются
    old_path = os.path.join(td, "old.ob.json")
    with open(old_path, "w", encoding="utf-8") as f:
        _json2.dump({"game_dir": "G"}, f, ensure_ascii=False)
    assert Project.from_dict(_json2.load(open(old_path, encoding="utf-8"))).game_dir == "G"
    # бьём основной файл (обрыв JSON)
    with open(pf, "w", encoding="utf-8") as f:
        f.write('{"game_dir": "G", "entries": [{')
    # эмуляция open_project: JSONDecodeError -> карантин + .bak
    import glob as _glob
    import time as _time
    loaded = None
    try:
        with open(pf, encoding="utf-8") as f:
            loaded = Project.from_dict(_json2.load(f))
        assert False, "должно было упасть на JSONDecodeError"
    except _json2.JSONDecodeError:
        ts = int(_time.time())
        corrupt = f"{pf}.corrupt-{ts}.json"
        os.replace(pf, corrupt)
        assert not os.path.exists(pf)
        assert os.path.isfile(corrupt)
        with open(bak, encoding="utf-8") as f:
            loaded = Project.from_dict(_json2.load(f))
    assert loaded is not None and len(loaded.entries) == 1
    assert loaded.entries[0].translation == "привет"
    # оба битые -> пустой Project (не падаем)
    with open(pf, "w", encoding="utf-8") as f:
        f.write("{oops")
    with open(bak, "w", encoding="utf-8") as f:
        f.write("{oops2")
    try:
        with open(pf, encoding="utf-8") as f:
            _json2.load(f)
        ok = True
    except _json2.JSONDecodeError:
        ok = False
    assert not ok
    try:
        with open(bak, encoding="utf-8") as f:
            Project.from_dict(_json2.load(f))
        fell_back = True
    except (_json2.JSONDecodeError, ValueError, KeyError, TypeError):
        fell_back = False
        empty = Project(game_dir="G", engine="mz")
    assert not fell_back
    assert empty.entries == []
print("   OK")

print("12) migrate_appdata не затирает + glossary atomic...")
with tempfile.TemporaryDirectory() as td:
    old = os.environ.get("APPDATA")
    os.environ["APPDATA"] = td
    try:
        root = app_paths.user_data_dir()
        os.makedirs(os.path.join(root, "projects"), exist_ok=True)
        # целевой глоссарий уже есть — его нельзя затирать
        os.makedirs(os.path.join(root, "glossary"), exist_ok=True)
        with open(os.path.join(root, "glossary", "glossary.json"),
                  "w", encoding="utf-8") as f:
            f.write('{"keep": 1}')
        with open(os.path.join(root, "glossary.json"),
                  "w", encoding="utf-8") as f:
            f.write('{"new": 2}')
        app_paths.migrate_appdata()
        assert open(os.path.join(root, "glossary", "glossary.json"),
                    encoding="utf-8").read() == '{"keep": 1}'
        # глоссарий сохраняется атомарно и переживает перезагрузку
        g2 = Glossary(os.path.join(root, "glossary", "glossary.json"))
        # битый корень глоссария не должен был затереть хороший
        g2.set_terms("en", "ru", {"Hi": "Привет"})
        obj, err = read_json_safe(os.path.join(root, "glossary",
                                               "glossary.json"))
        assert err is None and "en->ru" in obj
        assert _glob.glob(os.path.join(root, "glossary", ".tmp-*.new")) == []
    finally:
        if old is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old
print("   OK")

print()
print("ВСЕ ТЕСТЫ ЯДРА ПРОШЛИ")
