# -*- coding: utf-8 -*-
"""Тесты M6 (Ren'Py): детект, извлечение из .rpy, генерация tl-файлов."""
import io
import json
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.renpy import parser as renpy

SCRIPT = '''define e = Character("Айра")
# комментарий "не текст"

label start:
    e "Привет, я ведьма."
    "Повествование без имени."
    jump "some_label"
    show "bg forest"
    play music "theme.ogg"
    e "С кавычкой \\"внутри\\"."
    $ x = _("Явная строка")
menu:
    "Первый выбор":
        pass
    "Второй выбор":
        pass
    call "sub_label"

translate english start_1:
    old "Старый текст"
    new "Old text"
'''

print("1) Детект Ren'Py...")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, 'game', 'sub'))
    os.makedirs(os.path.join(td, 'renpy'))
    with open(os.path.join(td, 'game', 'script.rpy'), 'w', encoding='utf-8') as f:
        f.write(SCRIPT)
    with open(os.path.join(td, 'game', 'sub', 'inner.rpy'), 'w',
              encoding='utf-8') as f:
        f.write('label inner:\n    "Вложенный диалог."\n')
    assert renpy.detect(td)
    with tempfile.TemporaryDirectory() as empty:
        assert not renpy.detect(empty)
    print('   OK')

    print('2) Извлечение...')
    entries = renpy.extract(td)
    texts = [e.original for e in entries]
    for t in texts:
        print('  ', t)
    assert "Привет, я ведьма." in texts
    assert "Повествование без имени." in texts
    assert "Первый выбор" in texts and "Второй выбор" in texts
    assert "Явная строка" in texts
    assert "Старый текст" in texts          # из translate-блока (old)
    assert "Вложенный диалог." in texts
    # команды/комментарии не извлекаются
    assert "some_label" not in texts
    assert "bg forest" not in texts
    assert "theme.ogg" not in texts
    assert "не текст" not in texts
    assert "Old text" not in texts          # new не извлекаем
    print('   OK, записей:', len(entries))

    print('3) Генерация tl...')
    for e in entries:
        e.translation = "TR:" + e.original
    stats = renpy.apply(td, entries, "ru")
    out = os.path.join(stats["out_dir"], "ob_game__script.rpy")
    content = open(out, encoding='utf-8').read()
    assert "translate russian strings:" in content
    assert 'old "Привет, я ведьма."' in content
    assert 'new "TR:Привет, я ведьма."' in content
    assert 'old "С кавычкой \\\\\\\\внутри\\\\\\\\."' in content or '\\\\"' in content
    assert os.path.exists(os.path.join(stats["out_dir"],
                                       "ob_game__sub__inner.rpy"))
    print('   файлов:', stats["files"], 'строк:', stats["strings"])

    print('4) Идемпотентность повторной генерации...')
    stats2 = renpy.apply(td, entries, "ru")
    content2 = open(out, encoding='utf-8').read()
    assert content2 == content
    print('   OK')

    print('5) Дедупликация old-строк...')
    dup_entries = []
    for i, txt in enumerate(["Одинаковая строка", "Одинаковая строка", "Другая строка"], 1):
        from app.core.rpgmaker.models import TranslationEntry
        dup_entries.append(TranslationEntry(
            id=i, file="game/script.rpy", json_path=f"line:{i}",
            context=f"script.rpy:{i} тест", original=txt,
            translation=f"TR:{txt}"))
    stats3 = renpy.apply(td, dup_entries, "ru")
    out3 = os.path.join(stats3["out_dir"], "ob_game__script.rpy")
    content3 = open(out3, encoding='utf-8').read()
    old_count = content3.count('old "Одинаковая строка"')
    assert old_count == 1, f"Expected 1 old, got {old_count}"
    assert content3.count('old "Другая строка"') == 1
    print('   OK')

print()
print('ВСЕ ТЕСТЫ RENPY ПРОШЛИ')
