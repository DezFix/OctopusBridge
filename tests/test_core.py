# -*- coding: utf-8 -*-
"""Smoke-тесты ядра OctopusBridge на реальной игре (без изменения файлов игры)."""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.rpgmaker import parser, crypto
from app.core.translate.mask import mask, unmask, validate
from _test_game import find_rpgm_game, skip_no_game

GAME = find_rpgm_game()
if not GAME:
    skip_no_game("RPG Maker (The Suffering of The Modest Witch)")

print('1) detect_engine:', parser.detect_engine(GAME))

print('2) extract...')
entries = parser.extract(GAME)
cjk = sum(1 for e in entries if parser.has_cjk(e.original))
print(f'   записей всего: {len(entries)}, с CJK: {cjk}')
for e in entries[:3]:
    print('  ', e.file, '|', e.context, '|', e.original[:60])

print('3) mask/unmask round-trip...')
samples = [r'テスト\V[1]と\N[2]、\C[3]赤\C[0] \{大\} 100\%1 \\ end',
           r'Обычный текст без кодов',
           r'\I[10]Предмет \V[5] шт.']
for s in samples:
    m, codes = mask(s)
    assert validate(m, codes), s
    assert unmask(m, codes) == s, (s, m)
print('   OK')

print('4) crypto .png_...')
key = crypto.get_key_mz(GAME)
pic = os.path.join(GAME, 'img', 'pictures',
                   os.listdir(os.path.join(GAME, 'img', 'pictures'))[0])
raw = crypto.decrypt_file(pic, key)
assert raw[:8] == b'\x89PNG\r\n\x1a\n', raw[:8]
print('   OK, PNG расшифрован, размер:', len(raw))

print('5) apply на копии одного файла...')
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, 'data'))
    shutil.copy2(os.path.join(GAME, 'data', 'Map002.json'),
                 os.path.join(td, 'data', 'Map002.json'))
    sub = [e for e in parser.extract(td) if e.file.endswith('Map002.json')]
    for e in sub[:5]:
        e.translation = 'ТЕСТ: ' + e.original
    stats = parser.apply(td, sub)
    re_entries = parser.extract(td)
    assert any(x.original.startswith('ТЕСТ: ') for x in re_entries)
    print('   OK', stats['files'], 'файл(ов),', stats['strings'], 'строк, бэкапов:', len(stats['backups']))

print()
print('ВСЕ ТЕСТЫ ПРОШЛИ')
