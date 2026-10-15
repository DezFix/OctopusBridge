# -*- coding: utf-8 -*-
"""Перевод Ren'Py уходит в ОДИН strings:-блок, который игра понимает.

По документации (renpy.org/doc/html/translation) `translate <lang>
strings:` с old/new — штатный путь для меню, _()-строк И для реплик
без перевода ("String translations are also applied to dialogue
strings that are not translated as dialogue"). Подмена — во время
показа, код игры не трогается.

Старый формат (`translate <lang> <label>:` и `translate <lang>
screens:` с old/new внутри) документацией не определён — движок
такие блоки молча глотает и ничего не подменяет (проверено на живой
игре). Штатный формат реплик (`translate <lang> <label>_<hash>:`)
нам недоступен: идентификаторы генерируются движком, в .rpyc их
нет. Поэтому apply() пишет ОДИН game/tl/<lang>/ob_strings.rpy,
а старые пофайловые ob_*.rpy вычищаются orphan-cleanup.
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

print("1) метка реплики видна в записи...")
rp._reset_label()
rp._reset_screen_stack()
got = []
collect = lambda f, c, o, *rest: got.append((c, o))
rp._extract_line("t.rpy", 1, "label start:", collect)
rp._extract_line("t.rpy", 2, '    e "Alpha marker"', collect)
assert got[-1][1] == "Alpha marker", got
print("   OK")

print("2) в strings: идут все с целым переводом, кроме маркера/чужого...")
# Правило для БЛОКОВ теперь одно: все записи с целым переводом
# (_is_interp_safe), кроме string-marker и other-language. Метка,
# вид узла (dialogue/screen/python/...) на попадание в блок НЕ
# влияют: подмена при показе, код не трогается.


def mk(orig, ctx, label, trans):
    jp = ("label:%s|" % label if label else "") + "ctx:" + ctx
    return TranslationEntry(id=1, file="t.rpy", json_path=jp,
                            context=ctx, original=orig, translation=trans)


say = mk("Alpha dialogue marker", "t.rpy:2:dialogue", "start",
         "TR Alpha dialogue marker")
ui = mk("Beta screen marker", "t.rpy:9:screen", "start",
        "TR Beta screen marker")
py = mk("Gamma python marker", "t.rpy:11:python:gold_text", "start",
        "TR Gamma python marker")
nolab = mk("Delta nolabel marker", "t.rpy:12:dialogue", "",
           "TR Delta nolabel marker")
mark = mk("Epsilon marker text", "t.rpy:5:_()", "start", "TR Epsilon")
other = mk("Zeta other text", "t.rpy:3:translated_string", "start",
           "TR Zeta")
# _entry_skip_reason остался для детальной классификации (см. словарь
# хука в test_renpy_coverage.py): маркер и чужой язык отведены,
# остальные — нет
assert rp._entry_skip_reason(mark) == "string-marker", \
    rp._entry_skip_reason(mark)
assert rp._entry_skip_reason(other) == "other-language", \
    rp._entry_skip_reason(other)
assert rp._entry_skip_reason(say) == "", rp._entry_skip_reason(say)
assert rp._entry_skip_reason(ui) == "", rp._entry_skip_reason(ui)
print("   OK")

print("3) apply пишет ОДИН ob_strings.rpy, а не блоки по меткам...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    res = rp.apply(td, [say, ui, py, nolab, mark, other],
                   target_lang="ru")
    out = os.path.join(td, "game", "tl", "russian")
    assert os.path.isfile(os.path.join(out, "ob_strings.rpy")), \
        os.listdir(out) if os.path.isdir(out) else "нет tl/russian"
    # старых пофайловых файлов нет — только единый strings:-файл
    rpy_files = [f for f in os.listdir(out) if f.endswith(".rpy")]
    assert rpy_files == ["ob_strings.rpy"], rpy_files
    text = io.open(os.path.join(out, "ob_strings.rpy"),
                   encoding="utf-8").read()
    assert text.count("translate russian strings:") == 1, text
    # НИКАКИХ label/screens блоков с old/new: движок их игнорировал
    assert not re.search(r"^translate russian (?!strings:)\S+:",
                         text, re.M), text
    for orig in ("Alpha dialogue marker", "Beta screen marker",
                 "Gamma python marker", "Delta nolabel marker"):
        assert 'old "%s"' % orig in text, (orig, text)
    # экранный текст — в ТОМ ЖЕ strings:-блоке, а не в screens:
    assert "translate russian screens:" not in text, text
    assert res.get("files") == 1, res
    assert res.get("strings") == 4, res
    assert res.get("skipped_by") == {"string-marker": 1,
                                     "other-language": 1}, res
print("   OK")

print("3a) имена персонажей (who=) тоже идут в strings:...")
who = mk("Alice marker name", "t.rpyc:speaker", "start",
         "TR Alice marker name")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, "game"))
    rp.apply(td, [who], target_lang="ru")
    text = io.open(os.path.join(td, "game", "tl", "russian",
                                "ob_strings.rpy"), encoding="utf-8").read()
    assert 'old "Alice marker name"' in text, text
    assert 'new "TR Alice marker name"' in text, text
print("   OK")

print("4) метка не теряется при извлечении...")
with tempfile.TemporaryDirectory() as td:
    g = os.path.join(td, "game")
    os.makedirs(g)
    io.open(os.path.join(g, "script.rpy"), "w", encoding="utf-8").write(
        'label intro:\n'
        '    e "Alpha intro marker"\n'
        '    menu:\n'
        '        "Beta choice marker":\n'
        '            pass\n'
        'label other:\n'
        '    e "Gamma second marker"\n')
    entries = rp.extract(td)
    by_orig = {e.original: rp._entry_label(e) for e in entries}
    assert by_orig.get("Alpha intro marker") == "intro", by_orig
    assert by_orig.get("Beta choice marker") == "intro", by_orig
    assert by_orig.get("Gamma second marker") == "other", by_orig
print("   OK")

print("ALL RENPY TRANSLATION-BLOCK TESTS GREEN")
