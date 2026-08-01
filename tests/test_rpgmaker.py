# -*- coding: utf-8 -*-
"""Тесты M4: патчер шрифтов (MZ/MV) и поддержка MV в парсере."""
import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.rpgmaker import parser
from app.core.rpgmaker.fontpatch import patch_font_mz, patch_font_mv, restore_font_mz

print('1) Патчер шрифта MZ...')
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, 'fonts'))
    os.makedirs(os.path.join(td, 'data'))
    with open(os.path.join(td, 'data', 'System.json'), 'w', encoding='utf-8') as f:
        json.dump({"advanced": {"mainFontFilename": "mplus-1m-regular.woff",
                                "numberFontFilename": "mplus-2p-bold-sub.woff"}}, f)
    fake_font = os.path.join(td, 'MyFont.ttf')
    with open(fake_font, 'wb') as f:
        f.write(b'fake-font-bytes')

    report = patch_font_mz(td, fake_font)
    with open(os.path.join(td, 'data', 'System.json'), encoding='utf-8') as f:
        adv = json.load(f)['advanced']
    assert adv['mainFontFilename'] == 'MyFont.ttf'
    assert adv['numberFontFilename'] == 'MyFont.ttf'
    assert os.path.exists(os.path.join(td, 'fonts', 'MyFont.ttf'))
    assert os.path.exists(report['backup'])
    assert restore_font_mz(td) is True
    with open(os.path.join(td, 'data', 'System.json'), encoding='utf-8') as f:
        assert json.load(f)['advanced']['mainFontFilename'] == 'mplus-1m-regular.woff'
print('   OK: шрифт прописан, бэкап, откат работает')

print('2) Патчер шрифта MV (gamefont.css)...')
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, 'fonts'))
    fake_font = os.path.join(td, 'Rus.ttf')
    with open(fake_font, 'wb') as f:
        f.write(b'fake')
    report = patch_font_mv(td, fake_font)
    css = open(report['css'], encoding='utf-8').read()
    assert 'GameFont' in css and 'Rus.ttf' in css
print('   OK')

print('3) MV: detect_engine и www/data...')
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, 'www', 'js'))
    os.makedirs(os.path.join(td, 'www', 'data'))
    open(os.path.join(td, 'www', 'js', 'rpg_core.js'), 'w').close()
    assert parser.detect_engine(td) == 'mv'
    assert parser.find_data_dir(td) == 'www/data'
print('   OK')

print('4) MV: извлечение плагин-команды 356...')
with tempfile.TemporaryDirectory() as td:
    os.makedirs(os.path.join(td, 'www', 'data'))
    common = [None, {"id": 1, "name": "テスト", "list": [
        {"code": 356, "indent": 0, "parameters": ["ShowText こんにちは"]},
        {"code": 401, "indent": 0, "parameters": ["私は魔女です"]},
        {"code": 0, "indent": 0, "parameters": []},
    ], "switchId": 1, "trigger": 0}]
    with open(os.path.join(td, 'www', 'data', 'CommonEvents.json'), 'w',
              encoding='utf-8') as f:
        json.dump(common, f, ensure_ascii=False)
    entries = parser.extract(td)
    texts = [e.original for e in entries]
    assert "ShowText こんにちは" in texts and "私は魔女です" in texts
    assert all(e.file.startswith('www/data/') for e in entries)
print('   OK:', texts)

print()
print('ВСЕ ТЕСТЫ M4 ПРОШЛИ')
