# -*- coding: utf-8 -*-
"""Безопасный рантайм-хук перевода (возвращён после удаления в 7.35).

История: штатные блоки `translate <lang> <label>:` с old/new внутри
НЕ подменяют реплики (проверено на живой игре — блоки загружены,
а диалог на языке оригинала). Видимый перевод раньше делал хук на
`Text.__init__`; в 7.35 его удалили вместе с опасным `strings:` —
и перевод исчез полностью. Хук возвращён, но БЕЗОПАСНЫЙ:
словарь — только отображаемые строки, python-выражения в него
не попадают. Хук срабатывает при отрисовке и не трогает код/данные.
"""
import io
import os
import re
import sys
import tempfile
import textwrap

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.renpy import parser as rp


def mk(orig, ctx, label, trans, status="translated"):
    jp = ("label:%s|" % label if label else "") + "ctx:" + ctx
    return TranslationEntry(id=1, file="t.rpy", json_path=jp,
                            context=ctx, original=orig,
                            translation=trans, status=status)


print("1) активатор в корне game/, словарь только безопасных строк...")
say = mk("Hello", "t.rpy:2:dialogue", "start", "RU-Hello")
py1 = mk("Gold", "t.rpy:11:python:gold_text", "start", "RU-Gold")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    rp.apply(td, [say, py1], target_lang="ru")
    act = os.path.join(td, "game", rp._ACTIVATE_NAME)
    assert os.path.isfile(act), "активатор не создан"
    body = io.open(act, encoding="utf-8").read()
    assert "_ob_text_init" in body, "хук пропал из активатора"
    assert "config.language" in body
    assert "translate russian strings:" not in body
    dpath = os.path.join(td, "game", "tl", "russian", "ob_dict.json")
    import json
    d = json.load(io.open(dpath, encoding="utf-8"))
    assert d.get("Hello") == "RU-Hello", d
    assert "Gold" not in d, "python-строка попала в словарь хука"
print("   OK")

print("2) python-блоки активатора без синтаксиса только-Python-3...")
body = rp._ACTIVATE_TEMPLATE.format(lang="russian")
blocks = []
cur = []
in_py = False
for line in body.splitlines():
    if re.match(r'^\s*init\s+.*python\s*:\s*$', line):
        if cur:
            blocks.append(textwrap.dedent("\n".join(cur)))
            cur = []
        in_py = True
        continue
    if in_py:
        if line.strip() == "" or line.startswith((" ", "\t")):
            cur.append(line)
        else:
            in_py = False
if cur:
    blocks.append(textwrap.dedent("\n".join(cur)))
assert blocks, "python-блоки не найдены"
for b in blocks:
    compile(b, "<activate>", "exec")
py_code = "\n".join(blocks)
for bad, why in ((r'(?<![A-Za-z0-9_])f["\']', "f-строка"),
                 (r'\bnonlocal\b', "nonlocal"),
                 (r'\byield\s+from\b', "yield from"),
                 (r'\basync\b', "async"),
                 (r'\bawait\b', "await"),
                 (r':=', "walrus")):
    assert not re.search(bad, py_code), \
        "шаблон содержит %s — сломается на Ren'Py 7 (Python 2)" % why
print("   OK")

print("3) хук отказоустойчивый и ищет в двух формах...")
assert body.count("except Exception:") >= 3, \
    "хук обязан гасить свои ошибки, иначе уронит игру"
assert "_ob_dict[s]" in body or "in _ob_dict" in body, \
    "точное совпадение потеряно"
# нормализованный поиск: точное совпадение, потом по пробелам
assert "_ob_norm_index" in body, "нет fallback-поиска по нормализации"
assert "_ob_tr(" in body, "нет единой функции поиска перевода"
# счётчики покрытия (только числа, без текста игры)
assert "_ob_hits" in body, "нет счётчиков попаданий/промахов"
print("   OK")

print("ALL RENPY HOOK TESTS GREEN")
