# -*- coding: utf-8 -*-
"""`translate <lang> strings:` — ЕДИНСТВЕННЫЙ блок перевода OctopusBridge.

Почему strings: безопасен: подмена происходит во время показа
(display-time substitution, renpy.org/doc/html/translation: "String
translations are also applied to dialogue strings that are not
translated as dialogue"), код игры не трогается — python-строки,
ключи словарей и выражения остаются как были, переводится только
то, что движок реально рисует на экране. Поэтому в strings: идут
все записи с целым переводом (_is_interp_safe), кроме обрывков
разметки (string-marker) и чужого языка (other-language).

Что было неверно раньше: считалось, что strings: "подменяет
python-строки прямо в коде игры" (страх после SR24) и потому был
запрещён, а вместо него писались пофайловые `translate <lang>
<label>:` и `translate <lang> screens:` с old/new внутри. Этот
формат документацией Ren'Py не определён — движок такие блоки
молча глотает и ничего не подменяет (проверено на живой игре).
Файл переименован из test_renpy_no_strings_block.py: смысл
инвертирован — раньше assert'ил ОТСУТСТВИЕ strings:, теперь
assert'ит ЕГО НАЛИЧИЕ и корректность.
"""
import io
import os
import re
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.models import TranslationEntry
from app.core.renpy import parser as rp


def mk(orig, ctx, label, trans, status="translated"):
    jp = ("label:%s|" % label if label else "") + "ctx:" + ctx
    return TranslationEntry(id=1, file="t.rpy", json_path=jp,
                            context=ctx, original=orig,
                            translation=trans, status=status)


print("1) strings: пишется один, все пары внутри, дубликатов нет...")
say = mk("Alpha dialogue marker", "t.rpy:2:dialogue", "start",
         "TR Alpha dialogue marker")
ui = mk("Beta screen marker", "t.rpy:9:screen", "start",
        "TR Beta screen marker")
py1 = mk("Gamma python marker", "t.rpy:11:python:gold_text", "start",
        "TR Gamma python marker")
nolab = mk("Delta nolabel marker", "t.rpy:12:dialogue", "",
           "TR Delta nolabel marker")
# обрывок разметки и чужой язык — единственные пропуски для блоков
mark = mk("Epsilon marker text", "t.rpy:5:_()", "start", "TR Epsilon")
other = mk("Zeta other text", "t.rpy:3:translated_string", "start",
           "TR Zeta")
# дубликат оригинала: пишется один раз
say_dup = mk("Alpha dialogue marker", "t.rpy:20:dialogue", "other",
             "TR Alpha dialogue marker")
say_dup.id = 2

with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    res = rp.apply(td, [say, ui, py1, nolab, mark, other, say_dup],
                   target_lang="ru")
    out = os.path.join(td, "game", "tl", "russian")
    assert os.path.isfile(os.path.join(out, "ob_strings.rpy")), \
        os.listdir(out) if os.path.isdir(out) else "нет tl/russian"
    text = io.open(os.path.join(out, "ob_strings.rpy"),
                   encoding="utf-8").read()
    # ровно один блок strings:, пофайловых label/screens блоков с
    # old/new больше нет (движок их игнорировал)
    assert text.count("translate russian strings:") == 1, text
    assert not re.search(r"^translate russian (?!strings:)\S+:",
                         text, re.M), text
    # все четыре отображаемые строки внутри — включая python и
    # безметочную: подмена только при показе, код не трогается,
    # поэтому они безопасны и обязательны
    for orig, trans in (("Alpha dialogue marker",
                         "TR Alpha dialogue marker"),
                        ("Beta screen marker", "TR Beta screen marker"),
                        ("Gamma python marker", "TR Gamma python marker"),
                        ("Delta nolabel marker",
                         "TR Delta nolabel marker")):
        assert 'old "%s"' % orig in text, (orig, text)
        assert 'new "%s"' % trans in text, (orig, text)
    # дедуп по original глобальный: дубликат записан один раз
    assert text.count('old "Alpha dialogue marker"') == 1, text
    assert res.get("dup_skipped", 0) == 1, res
    # дубликатов old нет вообще (Ren'Py падает на дублях)
    olds = re.findall(r'^\s*old "(.*)"\s*$', text, re.M)
    assert len(olds) == len(set(olds)), olds
    # маркер и чужой язык не записаны, но объяснены
    assert "Epsilon marker text" not in text, text
    assert "Zeta other text" not in text, text
    assert res.get("strings_dropped", 0) == 2, res
    assert res.get("skipped_total") == 2, res
    assert res.get("skipped_by") == {"string-marker": 1,
                                    "other-language": 1}, res
    assert res.get("strings") == 4, res
    assert res.get("files") == 1, res
print("   OK")

print("2) повторный прогон идемпотентен...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    first = [mk("Alpha dialogue marker", "t.rpy:2:dialogue", "start",
                "TR Alpha dialogue marker"),
             mk("Beta screen marker", "t.rpy:9:screen", "start",
                "TR Beta screen marker")]
    r1 = rp.apply(td, first, target_lang="ru")
    out = os.path.join(td, "game", "tl", "russian", "ob_strings.rpy")
    body1 = io.open(out, encoding="utf-8").read()
    assert r1.get("new_strings") == 2, r1
    r2 = rp.apply(td, first, target_lang="ru")
    body2 = io.open(out, encoding="utf-8").read()
    assert body1 == body2, "повторный прогон изменил файл"
    assert r2.get("new_strings") == 0, r2
    assert r2.get("strings") == 2, r2
    assert r2.get("files") == 1, r2
print("   OK")

print("3) блок без строк не создаётся...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    # только маркер и чужой язык: в strings: им не место
    only_skip = [mk("Epsilon marker text", "t.rpy:5:_()", "start",
                    "TR Epsilon"),
                 mk("Zeta other text", "t.rpy:3:translated_string",
                    "start", "TR Zeta")]
    res = rp.apply(td, only_skip, target_lang="ru")
    assert res.get("files") == 0, res
    assert res.get("strings") == 0, res
    out = os.path.join(td, "game", "tl", "russian")
    if os.path.isdir(out):
        written = []
        for f in os.listdir(out):
            if f.endswith(".rpy"):
                t = io.open(os.path.join(out, f), encoding="utf-8").read()
                if "translate russian strings:" in t:
                    written.append(f)
        assert not written, written
print("   OK")

print("ALL RENPY STRINGS-BLOCK TESTS GREEN")
