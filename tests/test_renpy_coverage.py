# -*- coding: utf-8 -*-
"""Покрытие перевода Ren'Py: правило «брать/не брать» и его следствия.

Правило для БЛОКОВ теперь одно: в `translate <lang> strings:`
идут все записи с целым переводом (_is_interp_safe), кроме
string-marker (обрывки разметки) и other-language (уже не исходный
язык). Метка, вид узла (dialogue/screen/python/...) на попадание
в блок НЕ влияют: подмена при показе, код не трогается.

Детальная таблица видов ниже осталась для СЛОВАРЯ хука: хук
подменяет текст только в момент отрисовки, поэтому ему видны и
python/no-label строки (если они показываются на экране —
переведутся, логика игры не затрагивается). _entry_skip_reason
как функция НЕ удалена — она теперь отвечает «пойдёт ли в
словарь / какая структурная причина», а для БЛОКОВ решает одно
правило выше (см. test_renpy_strings_block.py).
"""
import io
import os
import pickle
import sys
import tempfile
import types
import zlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.renpy import parser as rp

print("1) решение «брать/не брать» — по виду УЗЛА, не по виду текста...")
from app.core.models import TranslationEntry  # noqa: E402


def entry(orig, ctx, label, trans="TR"):
    jp = ("label:%s|" % label if label else "") + "ctx:" + ctx
    return TranslationEntry(id=1, file="t.rpyc", json_path=jp,
                            context=ctx, original=orig, translation=trans)


# вид узла -> (блок старой классификации / причина пропуска).
# Таблица осталась для СЛОВАРЯ хука (куда идут и python-expression,
# и no-label — хук render-only, код не трогает). Для БЛОКОВ правило
# теперь одно: в strings: всё, кроме string-marker/other-language.
RULE = [
    # сказать что: узел Say внутри метки — обычный переводимый текст
    ("dialogue", "start", "label", ""),
    # TranslateSay — реплика официального перевода, тот же случай
    ("translate-block", "start", "label", ""),
    # меню: пункт и заголовок
    ("choice", "start", "label", ""),
    ("menu-caption", "start", "label", ""),
    # имя персонажа Say.who — тоже ОТОБРАЖАЕМЫЙ текст, Ren'Py официально
    # переводит его old/new в блоке метки
    ("speaker", "start", "label", ""),
    # текст экрана — отдельный блок screens:
    ("screen", "start", "screens", ""),
    # тот же экран без метки — метка ему не нужна, блок экранов общий
    ("screen", "", "screens", ""),
    # отображаемый текст ВНЕ метки: блока translate <lang> <label> не
    # существует, а `strings:` запрещён
    ("dialogue", "", "no-label", ""),
    ("speaker", "", "no-label", ""),
    # python-узлы и всё, что внутри них
    ("python", "start", "python-expression", ""),
    ("python:action_image", "start", "python-expression", ""),
    ("python:key=q1", "start", "python-expression", ""),
    ("code", "start", "python-expression", ""),
    # маркер _() — переводится самим Ren'Py через функцию перевода,
    # подменять строку в коде нельзя
    ("_()", "start", "string-marker", ""),
    # old-строка чужого перевода
    ("translated_string", "start", "other-language", ""),
    # неизвестный узел
    ("some_new_node", "start", "other-node", ""),
]
for kind, label, block_or_reason, _ in RULE:
    e = entry("Alpha marker text", "t.rpyc:" + kind, label)
    reason = rp._entry_skip_reason(e)
    if reason:
        assert reason == block_or_reason, (kind, label, reason)
        assert rp._entry_block(e) == "", (kind, rp._entry_block(e))
    else:
        assert rp._entry_block(e) == block_or_reason, \
            (kind, label, rp._entry_block(e), rp._entry_kind(e))
print("   OK: %d правил" % len(RULE))

print("2) подсказка вида не маскирует python-узел...")
# контекст = "<путь>:<вид>", вид python-узла составной и может содержать
# двоеточия (это кусок исходника игры). Вид должен остаться 'python'.
for hint in ("action_image", "key=q1", 'botlore_answer.append("{mark}...")'):
    e = entry("Alpha marker", "t.rpyc:python:" + hint, "start")
    assert rp._entry_kind(e) == "python", (hint, rp._entry_kind(e))
    assert rp._entry_skip_reason(e) == "python-expression", hint
print("   OK")

print("3) .rpyc: метка восстанавливается при обходе AST...")
_FAKE_MOD = "ob_fake_renpy_ast"
if _FAKE_MOD not in sys.modules:
    sys.modules[_FAKE_MOD] = types.ModuleType(_FAKE_MOD)


class Say(rp._MockNode):
    """Узел Say. Имя класса = 'Say' — по нему _walk_ast выбирает ветку."""


class Label(rp._MockNode):
    pass


class Python(rp._MockNode):
    """Узел `python:`/`init python:` — источник строковых литералов."""


class Code(rp._MockNode):
    """PyCode-подобный узел с полем source."""


Say.__module__ = _FAKE_MOD
Say.__qualname__ = "Say"
Label.__module__ = _FAKE_MOD
Label.__qualname__ = "Label"
Python.__module__ = _FAKE_MOD
Python.__qualname__ = "Python"
Code.__module__ = _FAKE_MOD
Code.__qualname__ = "Code"
# pickle ищет класс по имени в sys.modules[...] — модуль-заглушка должен
# их видеть, иначе он подставит свои _MockNode вместо наших узлов
for _c in (Say, Label, Python, Code):
    setattr(sys.modules[_FAKE_MOD], _c.__qualname__, _c)
# узлы синтетики регистрируются в БЕЛОМ списке mock-классов парсера:
# без этого unpickler подменил бы их своими заглушками
for _c in (Say, Label, Python, Code):
    rp._RENPY_MOCKS[(_FAKE_MOD, _c.__qualname__)] = _c


def python(src):
    p = Python()
    c = Code()
    c.source = src
    p.code = c
    return p


def say(what, who=None):
    s = Say()
    s.what = what
    s.who = who
    return s


def label(name, block):
    lb = Label()
    lb.name = name
    lb.block = block
    return lb


triples = rp._walk_ast([
    label("chapter_one", [say("Alpha first marker", who="Beta guest marker"),
                          say("Gamma second marker")]),
    label("chapter_two", [say("Delta third marker")]),
    say("Epsilon stray marker"),
], labeled=True)
got = {(k, t): lab for k, t, lab in triples}
assert got[("dialogue", "Alpha first marker")] == "chapter_one", got
assert got[("speaker", "Beta guest marker")] == "chapter_one", got
assert got[("dialogue", "Gamma second marker")] == "chapter_one", got
# метка ПЕРЕКЛЮЧАЕТСЯ на следующем Label, а не остаётся последней
assert got[("dialogue", "Delta third marker")] == "chapter_two", got
assert got[("dialogue", "Epsilon stray marker")] == "", got
# обратная совместимость вызова без labeled=
assert rp._walk_ast([label("x", [say("Zeta only marker")])]) == \
    [("dialogue", "Zeta only marker")], \
    rp._walk_ast([label("x", [say("Zeta only marker")])])
print("   OK")

print("4) сквозная проверка на синтетике: .rpyc + .rpy -> apply...")
SCRIPT_RPY = (
    'label intro:\n'
    '    e "Alpha source marker"\n'
    '    menu:\n'
    '        "Beta forest marker":\n'
    '            pass\n'
    'screen main_menu:\n'
    '    text "Gamma start marker"\n'
    '    textbutton "Delta exit marker"\n'
    'init python:\n'
    '    title_text = "Epsilon python title marker"\n'
)
stmts = [
    label("chapter_one", [say("Zeta first marker", who="Eta guest marker"),
                          say("Theta second marker")]),
    label("chapter_two", [say("Iota third marker")]),
    python('items = {"key=first": "Kappa python desc marker"}'),
    say("Lambda stray marker"),
]
rpyc = zlib.compress(pickle.dumps(({"_ob": True}, stmts), protocol=2))

with tempfile.TemporaryDirectory() as td:
    g = os.path.join(td, "game")
    os.makedirs(g)
    with open(os.path.join(g, "script.rpyc"), "wb") as f:
        f.write(rpyc)
    with open(os.path.join(g, "extra.rpy"), "w", encoding="utf-8") as f:
        f.write(SCRIPT_RPY)

    entries = rp.extract(td)
    kinds = {e.original: rp._entry_kind(e) for e in entries}
    assert len(entries) == 11, sorted(kinds)
    assert kinds["Eta guest marker"] == "speaker", kinds
    assert kinds["Gamma start marker"] == "screen", kinds
    assert kinds["Epsilon python title marker"] == "python", kinds
    assert kinds["Kappa python desc marker"] == "python", kinds

    # покрытие считается по попаданию в strings: (а не в label-блоки):
    # все 11 идут в strings (пропуски — только string-marker /
    # other-language, которых здесь нет). Старое правило (белый список
    # видов + обязательная метка, speaker вне списка) давало меньше.
    taken_strings = [e for e in entries
                     if rp._entry_skip_reason(e)
                     not in ("string-marker", "other-language")]
    coverage_now = 100.0 * len(taken_strings) / len(entries)
    _OLD_KINDS = {"dialogue", "choice", "menu-caption", "translate-block",
                  "screen"}
    coverage_old = 100.0 * sum(
        1 for e in entries
        if rp._entry_kind(e) in _OLD_KINDS and rp._entry_label(e)) / len(entries)
    assert coverage_now > coverage_old, (coverage_now, coverage_old)
    assert coverage_now == 100.0, coverage_now

    for e in entries:
        e.translation = "TR " + e.original
    res = rp.apply(td, entries, target_lang="ru")
    assert res["skipped_total"] == 0, res
    assert res["skipped_by"] == {}, res
    assert res["strings"] == len(taken_strings) == 11, res
    assert res["files"] == 1, res

    out_dir = os.path.join(td, "game", "tl", "russian")
    assert os.path.isfile(os.path.join(out_dir, "ob_strings.rpy")), \
        os.listdir(out_dir)
    text = io.open(os.path.join(out_dir, "ob_strings.rpy"),
                    encoding="utf-8").read()
    assert text, os.listdir(out_dir)
    # 1) ОДИН блок strings: — и никаких label/screens блоков с old/new
    # (движок их игнорировал)
    assert text.count("translate russian strings:") == 1, text
    import re as _re
    assert not _re.search(r"^translate russian (?!strings:)\S+:",
                          text, _re.M), text
    # 2) python-строки ТОЖЕ в strings: (подмена при показе, код цел)
    for py_text in ("Epsilon python title marker",
                    "Kappa python desc marker"):
        assert 'old "%s"' % py_text in text, py_text
        assert "TR %s" % py_text in text, py_text
    # 3) отображаемый текст вне метки тоже записан (хук и strings:
    # его берут — раньше он молча терялся)
    assert 'old "Lambda stray marker"' in text, text
    # 4) точечно: имя персонажа, реплики, экраны — все в ОДНОМ блоке
    for want in ("Eta guest marker", "Zeta first marker",
                 "Iota third marker", "Gamma start marker",
                 "Delta exit marker", "Alpha source marker",
                 "Beta forest marker"):
        assert 'old "%s"' % want in text, (want, text)
    print("   OK: покрытие %.1f%% (было по старому правилу %.1f%%), "
          "пропущено %d" % (coverage_now, coverage_old,
                            res["skipped_total"]))

print("ALL RENPY COVERAGE TESTS GREEN")
