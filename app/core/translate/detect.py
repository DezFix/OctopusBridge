# -*- coding: utf-8 -*-
"""Эвристическое определение языка строки для режима 'auto'.

Приоритет: кана → ja; иероглифы без каны → zh; кириллица → ru; латиница → en.
"""
from __future__ import annotations

import re

KANA_RE = re.compile(r'[぀-ヿㇰ-ㇿ]')
HAN_RE = re.compile(r'[一-鿿㐀-䶿]')
CYRILLIC_RE = re.compile(r'[Ѐ-ӿ]')
LATIN_RE = re.compile(r'[A-Za-z]')

# управляющие коды RPG Maker не учитываем при определении языка
CODES_RE = re.compile(r'\\[A-Za-z]?\[[^\]]*\]|\\[{}<>|.!^_]?|\\[A-Za-z]+|%[0-9]+')


def detect_lang(text: str) -> str | None:
    """Возвращает 'ja' | 'zh' | 'ru' | 'en' | None (нечего переводить)."""
    text = CODES_RE.sub('', text)
    if KANA_RE.search(text):
        return "ja"
    if HAN_RE.search(text):
        return "zh"
    if CYRILLIC_RE.search(text):
        return "ru"
    if LATIN_RE.search(text):
        return "en"
    return None
