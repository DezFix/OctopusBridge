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


print("1) словарь хука: блоки + no-label + python, без маркеров...")
say = mk("Hello", "t.rpy:2:dialogue", "start", "RU-Hello")
py1 = mk("Gold", "t.rpy:11:python:gold_text", "start", "RU-Gold")
nolab = mk("Plain", "t.rpy:12:dialogue", "", "RU-Plain")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    rp.apply(td, [say, py1, nolab], target_lang="ru")
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
    # хук render-only: python-строка в словаре безвредна для логики,
    # а если она показывается на экране — переведётся
    assert d.get("Gold") == "RU-Gold", d
    # no-label некуда положить блоком, но хук её берёт
    assert d.get("Plain") == "RU-Plain", d
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
# скелетный поиск для строк с [var]: на экране значение, в словаре шаблон
assert "_ob_pat_list" in body and "_ob_tr_pat" in body, \
    "нет поиска по скелету для подстановок"
print("   OK")

print("4) скелетный поиск: шаблон с [var] ловит строку со значением...")
# Симулируем алгоритм из шаблона один в один (re + строки — одинаково
# работают в py2/py3 для этих операций).
_d = {"Hello [name], you have [n] coins": "RU-Hello [name], coins [n]"}
_pl = []
for _k, _v in _d.items():
    _kn = []
    for _m in re.findall(r"\[([^\[\]]+)\]", _k):
        _b = _m.split("!")[0].split(":")[0]
        if _b and _b not in _kn:
            _kn.append(_b)
    _vn = []
    for _m in re.findall(r"\[([^\[\]]+)\]", _v):
        _b = _m.split("!")[0].split(":")[0]
        if _b and _b not in _vn:
            _vn.append(_b)
    assert sorted(_vn) == sorted(_kn)
    _parts = re.split(r"(\[[^\[\]]+\])", _k)
    _rx, _names = [], []
    for _p in _parts:
        _pm = re.match(r"^\[([^\[\]]+)\]$", _p)
        if _pm:
            _names.append(_pm.group(1).split("!")[0].split(":")[0])
            _rx.append("(.+?)")
        else:
            _rx.append(re.escape(_p))
    _pat = re.compile("\\A" + "".join(_rx) + "\\Z")
    _pl.append((_parts[0], _pat, _names, _v))


def _tr_pat(s):
    for _prefix, _pat, _names, _v in _pl:
        if _prefix and not s.startswith(_prefix):
            continue
        _m = _pat.match(s)
        if not _m:
            continue
        _seen = {}
        for _nm, _vv in zip(_names, _m.groups()):
            if _nm not in _seen:
                _seen[_nm] = _vv
        _res = _v
        for _nm, _vv in _seen.items():
            _res, _ = re.subn(r"\[" + re.escape(_nm)
                              + r"(?:![^\[\]]*)?(?::[^\[\]]*)?\]",
                              lambda _mm: _vv, _res)
        return _res
    return s


assert _tr_pat("Hello Han, you have 5 coins") == \
    "RU-Hello Han, coins 5", _tr_pat("Hello Han, you have 5 coins")
# чужой текст не задевает
assert _tr_pat("Goodbye Han, see you") == "Goodbye Han, see you"
# теги {...} не считаются подстановками
assert _tr_pat("Hello {b}Han{/b}") == "Hello {b}Han{/b}"
print("   OK")

print("ALL RENPY HOOK TESTS GREEN")
