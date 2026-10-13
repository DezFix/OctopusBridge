# -*- coding: utf-8 -*-
"""Покрытие перевода Ren'Py: правило «брать/не брать» и его следствия.

Было: из 6562 записей реальной игры в перевод попадали 3158 (48.1%) —
это блоки меток; остальные 3291 молча терялись, потому что решение
«писать/не писать» принималось по белому списку видов, а обещанный
рантайм-хук Text.__init__, который их якобы переводил, удалён (dd3ffe6).

Стало: решение принимается по ВИДУ УЗЛА Ren'Py, из которого строка
получена, а не по виду текста:

    Say / TranslateSay / Menu / экран  -> отображаемый текст, БЕРЁМ
                                          (метка / `translate <lang> screens:`)
    Define / Default / Python / python: -> литерал внутри ВЫРАЖЕНИЯ, НЕ БЕРЁМ
                                          (ключ словаря или значение, которое
                                          игра ищет и сравнивает сама)
    отображаемый текст без метки        -> НЕ БЕРЁМ (блока без метки нет)

`translate <lang> strings:` не возвращается НИКОГДА: он подменяет
python-строки прямо в коде игры и ломает игры на строковых словарях.
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


def entry(orig, ctx, label, trans="ПЕР"):
    jp = ("label:%s|" % label if label else "") + "ctx:" + ctx
    return TranslationEntry(id=1, file="t.rpyc", json_path=jp,
                            context=ctx, original=orig, translation=trans)


# вид узла -> (пишем?, причина пропуска)
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
    e = entry("Text here", "t.rpyc:" + kind, label)
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
    e = entry("Text", "t.rpyc:python:" + hint, "start")
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
    label("chapter_one", [say("Первая реплика", who="Гость"),
                          say("Вторая реплика")]),
    label("chapter_two", [say("Третья реплика")]),
    say("Реплика вне метки"),
], labeled=True)
got = {(k, t): lab for k, t, lab in triples}
assert got[("dialogue", "Первая реплика")] == "chapter_one", got
assert got[("speaker", "Гость")] == "chapter_one", got
assert got[("dialogue", "Вторая реплика")] == "chapter_one", got
# метка ПЕРЕКЛЮЧАЕТСЯ на следующем Label, а не остаётся последней
assert got[("dialogue", "Третья реплика")] == "chapter_two", got
assert got[("dialogue", "Реплика вне метки")] == "", got
# обратная совместимость вызова без labeled=
assert rp._walk_ast([label("x", [say("Только")])]) == \
    [("dialogue", "Только")], rp._walk_ast([label("x", [say("Только")])])
print("   OK")

print("4) сквозная проверка на синтетике: .rpyc + .rpy -> apply...")
SCRIPT_RPY = (
    'label intro:\n'
    '    e "Текст из исходника"\n'
    '    menu:\n'
    '        "Идти в лес":\n'
    '            pass\n'
    'screen main_menu:\n'
    '    text "Начать игру"\n'
    '    textbutton "Выход"\n'
    'init python:\n'
    '    title_text = "Заголовок из python"\n'
)
stmts = [
    label("chapter_one", [say("Первая реплика", who="Гость"),
                          say("Вторая реплика")]),
    label("chapter_two", [say("Третья реплика")]),
    python('items = {"key=first": "Описание из python"}'),
    say("Реплика вне метки"),
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
    assert kinds["Гость"] == "speaker", kinds
    assert kinds["Начать игру"] == "screen", kinds
    assert kinds["Заголовок из python"] == "python", kinds
    assert kinds["Описание из python"] == "python", kinds

    taken = [e for e in entries if not rp._entry_skip_reason(e)]
    coverage_now = 100.0 * len(taken) / len(entries)
    # правило ДО фикса: белый список видов, speaker в него не входил
    _OLD_KINDS = {"dialogue", "choice", "menu-caption", "translate-block",
                  "screen"}
    coverage_old = 100.0 * sum(
        1 for e in entries
        if rp._entry_kind(e) in _OLD_KINDS and rp._entry_label(e)) / len(entries)
    assert coverage_now > coverage_old, (coverage_now, coverage_old)

    for e in entries:
        e.translation = "ПЕР:" + e.original
    res = rp.apply(td, entries, target_lang="ru")
    assert res["skipped_total"] == 3, res
    assert res["skipped_by"] == {"no-label": 1,
                                 "python-expression": 2}, res
    assert res["strings"] == len(taken), res

    out_dir = os.path.join(td, "game", "tl", "russian")
    text = ""
    for name in sorted(os.listdir(out_dir)):
        if name.endswith(".rpy"):
            text += io.open(os.path.join(out_dir, name),
                            encoding="utf-8").read()
    assert text, os.listdir(out_dir)
    # 1) блока strings: быть не должно НИГДЕ
    assert "translate russian strings:" not in text, \
        "strings: подменяет python-строки в коде игры"
    # 2) ни одна python-строка не заменена переводом
    for py_text in ("Заголовок из python", "Описание из python"):
        assert "ПЕР:" + py_text not in text, \
            "python-строка заменена переводом в файле перевода"
        assert py_text not in text, py_text
    # 3) отображаемый текст вне метки тоже не записан
    assert "Реплика вне метки" not in text, "запись без метки записана"
    # 4) блоки на месте: метки + screens
    assert "translate russian chapter_one:" in text, text
    assert "translate russian chapter_two:" in text, text
    assert "translate russian intro:" in text, text
    assert "translate russian screens:" in text, text
    # 5) точечно: имя персонажа и реплики — в блоке СВОЕЙ метки
    def block_of(label_name):
        marker = "translate russian %s:\n" % label_name
        i = text.index(marker) + len(marker)
        j = text.find("\ntranslate russian ", i)
        return text[i:j if j > 0 else len(text)]

    ch1 = block_of("chapter_one")
    assert "ПЕР:Гость" in ch1, ch1
    assert "ПЕР:Первая реплика" in ch1, ch1
    assert "ПЕР:Третья реплика" not in ch1, ch1
    assert "ПЕР:Начать игру" not in ch1, \
        "текст экрана не должен попадать в блок метки"
    scr = block_of("screens")
    assert "ПЕР:Начать игру" in scr and "ПЕР:Выход" in scr, scr
    print("   OK: покрытие %.1f%% (было по старому правилу %.1f%%), "
          "пропущено %d" % (coverage_now, coverage_old,
                            res["skipped_total"]))

print("ALL RENPY COVERAGE TESTS GREEN")