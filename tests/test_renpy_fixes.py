# -*- coding: utf-8 -*-
"""Фиксы аудита Ren'Py-парсера: декод escape-последовательностей
строковых литералов (\" \n \u00e9), запись→чтение round-trip,
крахоустойчивость (RecursionError в глубоко вложенном python),
валидация target_lang (path traversal / перевод строки), BOM в
.rpy, пункты меню 2-кортежами, cp1251 .rpy внутри .rpa."""
import io
import json
import os
import pickle
import random
import sys
import tempfile
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.renpy import parser as renpy
from app.core.renpy.parser import _decode_rpy_literal


def make_game(root: str, script: str) -> None:
    os.makedirs(os.path.join(root, "game"), exist_ok=True)
    with open(os.path.join(root, "game", "script.rpy"), "w",
              encoding="utf-8") as f:
        f.write(script)


print("1) Декод escape-последовательностей строковых литералов...")
# юнит-текущий: полный набор escape-правил Python
assert _decode_rpy_literal(r"a\nb\tc\"d\\e") == "a\nb\tc\"d\\e"
assert _decode_rpy_literal(r"café") == "café"
assert _decode_rpy_literal(r"é") == "é"
assert _decode_rpy_literal(
    r"\N{LATIN SMALL LETTER E WITH ACUTE}") == "é"
assert _decode_rpy_literal(r"\U0001F600") == "\U0001F600"
assert _decode_rpy_literal("\x41") == "A"
assert _decode_rpy_literal("без escape") == "без escape"
# неизвестный escape — best effort: оставляем как есть
assert _decode_rpy_literal(r"a\qb") == "a\\qb"

with tempfile.TemporaryDirectory() as td:
    # Ren'Py раскодирует литералы при парсинге скрипта:
    # извлечение обязано вернуть РАНТАЙМНУЮ строку, иначе
    # old-ключи в tl/<lang>/*.rpy и ключи ob_dict.json
    # никогда не совпадут со строками игры
    make_game(td, 'label start:\n'
                  '    e "Он сказал \\"привет\\" и ушёл"\n'
                  '    "Строка с \\n переносом и caf\\u00e9"\n'
                  '    _("Функция \\u00e9")\n')
    entries = renpy.extract(td)
    texts = [e.original for e in entries]
    assert "Он сказал \"привет\" и ушёл" in texts, texts
    assert "Строка с \n переносом и café" in texts, texts
    assert "Функция é" in texts, texts
print("   OK")

print("2) Запись→чтение: экранирование симметрично декодированию...")
with tempfile.TemporaryDirectory() as td:
    make_game(td, 'label start:\n'
                  '    e "Он сказал \\"привет\\" и ушёл"\n'
                  '    "Строка с \\n переносом и caf\\u00e9"\n')
    entries = renpy.extract(td)
    for e in entries:
        e.translation = "TR:" + e.original
    stats = renpy.apply(td, entries, "ru")
    # единый strings:-файл (один на язык), а не пофайловые ob_*.rpy:
    # старые `translate <lang> <label>:` с old/new движок игнорировал
    out = os.path.join(stats["out_dir"], "ob_strings.rpy")
    content = open(out, encoding="utf-8").read()
    assert content.count("translate russian strings:") == 1, content
    # запись экранирует обратно: кавычка — \\", перенос — \\n
    assert 'old "Он сказал \\"привет\\" и ушёл"' in content, content
    assert 'old "Строка с \\n переносом и café"' in content, content
    assert 'new "TR:Строка с \\n переносом и café"' in content, content
    # ob_dict.json: ключи — рантаймные (раскодированные) строки
    dict_path = os.path.join(td, "game", "tl", "russian",
                             "ob_dict.json")
    with open(dict_path, encoding="utf-8") as f:
        ob = json.load(f)
    assert "Он сказал \"привет\" и ушёл" in ob, list(ob)
    assert ob["Строка с \n переносом и café"] == \
        "TR:Строка с \n переносом и café"
# Активатор языка лежит в КОРНЕ game/, а не в tl/russian/:
    # Ren'Py не исполняет файлы из tl/<язык>/ (проверено на игре —
    # init-блок с config.language там не выполнялся).
    assert os.path.isfile(os.path.join(td, "game", renpy._ACTIVATE_NAME))
    assert not os.path.isfile(os.path.join(
        td, "game", "tl", "russian", "ob_activate.rpy"))
    # повторная генерация идемпотентна (old читается и
    # раскодируется обратно)
    renpy.apply(td, entries, "ru")
print("   OK")

print("3) Глубоко вложенный python-блок не роняет извлечение...")
with tempfile.TemporaryDirectory() as td:
    deep = "python:\n    x = " + "[" * 6000 + "]" * 6000 + "\n"
    make_game(td, deep + 'label start:\n    e "После глубокого блока"\n')
    entries = renpy.extract(td)  # не должно падать
    texts = [e.original for e in entries]
    assert "После глубокого блока" in texts, texts
print("   OK")

print("4) target_lang с path traversal / переводом строки — ValueError...")
with tempfile.TemporaryDirectory() as td:
    make_game(td, 'label start:\n    e "Текст"\n')
    entries = renpy.extract(td)
    for e in entries:
        e.translation = "TR"
    for bad in ("../../evil", "ru\n", "evil/ru"):
        try:
            renpy.apply(td, entries, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"невалидный target_lang не отловлен: {bad!r}")
    # файла ВНЕ game/tl не появилось
    assert not os.path.exists(os.path.join(td, "evil")), \
        "файл записан ВНЕ game/tl"
print("   OK")

print("5) BOM в начале .rpy не съедает первую строку...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    first = '"Первая строка"\n    e "Вторая строка"\n'
    with open(os.path.join(td, "game", "script.rpy"), "wb") as f:
        f.write(b"\xef\xbb\xbf" + first.encode("utf-8"))
    texts = [e.original for e in renpy.extract(td)]
    assert "Первая строка" in texts, texts
    assert "Вторая строка" in texts, texts
print("   OK")

print("6) Пункты меню 2-кортежами (label, блок) — блок извлекается...")


class _Say2:
    pass


_Say2.__name__ = "Say"
say2 = _Say2()
say2.what = "внутри пункта меню"
say2.who = None


class _Menu2:
    pass


_Menu2.__name__ = "Menu"
menu2 = _Menu2()
menu2.items = [("Выбор с блоком", [say2])]
out = renpy._walk_ast([menu2])
assert ("choice", "Выбор с блоком") in out, out
assert ("dialogue", "внутри пункта меню") in out, out
print("   OK")

print("7) cp1251 .rpy внутри .rpa читается без кракозябр...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    blob = ('label start:\n    e "Русская реплика"\n'
            ).encode("cp1251")
    key = random.getrandbits(32)
    path = os.path.join(td, "game", "archive.rpa")
    with open(path, "wb") as f:
        f.write(b"RPA-3.0 XXXXXXXXXXXXXXXX XXXXXXXX\n")
        offset = f.tell()
        f.write(blob)
        index = {"script.rpy": [(offset ^ key, len(blob) ^ key, b"")]}
        indexoff = f.tell()
        f.write(zlib.compress(
            pickle.dumps(index, pickle.HIGHEST_PROTOCOL)))
        f.seek(0)
        f.write(b"RPA-3.0 %016x %08x\n" % (indexoff, key))
    texts = [e.original for e in renpy.extract(td)]
    assert "Русская реплика" in texts, texts
print("   OK")

print("OK: все фиксы Ren'Py проверены")
