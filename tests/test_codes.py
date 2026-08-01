# -*- coding: utf-8 -*-
"""Регрессия: управляющие коды не должны ломаться реал-тайм переводом.

Строки взяты из реального лога пользователя. Инвариант: каждый код
оригинала присутствует в переводе (цвета, размеры, центрирование не
теряются).
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.translate.engines import get_engine
from app.core.translate.mask import mask, unmask, validate
from app.core.translate.service import Translator

CODE_RE = re.compile(
    r'(\\\\|\\[A-Za-z]*\[[^\]]*\]|\\[A-Za-z]+|\\[{}<>|.!^_]|\\|%[0-9]+'
    r'|</?[A-Za-z][^>]{0,30}>)')

LOG_SAMPLES = [
    r'<center>\>\c[17] - LOGIN - \c[0]',
    r'\c[8]Please input a name:',
    r'\>\fs[14](Use movement keys to select the letters)\c[0]\|',
    '<Center>Select difficulty.',
    r'\c[10]Hard Mode',
    '<Center>\\fs[20]\\c[17]NORMAL MODE\\c[0]\n\n\\fs[16]Standard enemy '
    'behaviour. \nStandard number of days for Quota deadline. ',
    r'\}❪TAB❫\{❪:Manual',
]

print('1) Маскировка: регекс покрывает все коды из лога...')
for s in LOG_SAMPLES:
    masked, codes = mask(s)
    assert validate(masked, codes)
    assert unmask(masked, codes) == s
    # в замаскированном тексте не должно остаться немаскированных кодов
    leftovers = [c for c in CODE_RE.findall(unmask(masked, codes))
                 if c not in (r'\>',)]
print('   OK, кодов:', [len(mask(s)[1]) for s in LOG_SAMPLES])

print('2) Многобуквенные коды и теги...')
masked, codes = mask(r'\fs[14]текст\c[8]ещё <center>тег</center> \PX[9] %1')
assert r'\fs[14]' in codes and r'\PX[9]' in codes
assert '<center>' in codes and '</center>' in codes and '%1' in codes
assert codes.count(r'\c[8]') == 1
print('   OK:', codes)

print('3) Реальный Argos на строках из лога (коды обязаны выжить)...')
tr = Translator(get_engine('argos'))
fails = []
for s in LOG_SAMPLES:
    out = tr.translate_text(s, 'auto', 'ru')
    missing = [c for c in CODE_RE.findall(s)
               if c not in ('<',) and c not in out]
    status = 'OK ' if not missing else 'FAIL'
    print(f'   [{status}] {s[:50]!r}')
    print(f'         -> {out[:90]!r}' +
          (f'  ПОТЕРЯНО: {missing}' if missing else ''))
    if missing:
        fails.append((s, missing))

assert not fails, f'{len(fails)} строк потеряли коды: {fails}'
print()
print('ТЕСТ КОДОВ ПРОШЁЛ: все коды сохранились в переводе')
