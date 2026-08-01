# -*- coding: utf-8 -*-
"""Подгонка переведённого текста под ширину окна диалога RPG Maker.

RPG Maker MZ/MV: окно диалога ~816px (стандарт), 4 строки по умолчанию.
Шрифт: 28px. Если перевод длиннее оригинала — текст вылезает за рамки.

Алгоритм:
1. Вычисляем реальную ширину текста (по таблице ширины символов шрифта)
2. Если текст не влезает — переносим по словам на новую строку
3. Если строк больше чем visibleRows — уменьшаем шрифт (до MIN_FONT_SIZE)
4. Если всё ещё не влезает — обрезаем с многоточием

Используется при JSON-внедрении (apply) для предварительного переноса,
и как утилита для live-режима.
"""
from __future__ import annotations

import re

# Стандартные размеры RPG Maker MZ/MZ
DEFAULT_WINDOW_WIDTH = 816
DEFAULT_VISIBLE_ROWS = 4
BASE_FONT_SIZE = 28
MIN_FONT_SIZE = 16
MAX_WRAP_RETRIES = 8

# Упрощённая таблица ширины символов для CJK-шрифта (пиксели при 28px)
# Латиница и кириллица: ~14-16px, CJK: ~28px, пробел: ~7px
_CJK_RANGE = re.compile(
    r'[　-鿿\uac00-\ud7af\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]'
)
_CYRILLIC_RANGE = re.compile(r'[А-яЁё]')
_LATIN_RANGE = re.compile(r'[A-Za-z]')
_DIGIT_RANGE = re.compile(r'[0-9]')
_PUNCT_RANGE = re.compile(r'[!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>/?`]')


def _char_width(ch: str, font_size: int = BASE_FONT_SIZE) -> int:
    """Ширина символа в пикселях (приближение)."""
    scale = font_size / 28.0
    if _CJK_RANGE.match(ch):
        return int(28 * scale)
    if _CYRILLIC_RANGE.match(ch) or _LATIN_RANGE.match(ch):
        return int(14 * scale)
    if _DIGIT_RANGE.match(ch):
        return int(14 * scale)
    if ch == ' ':
        return int(7 * scale)
    if _PUNCT_RANGE.match(ch):
        return int(8 * scale)
    return int(10 * scale)


def _strip_codes(text: str) -> str:
    """Убираем управляющие коды RPG Maker для замера ширины."""
    s = text
    s = re.sub(r'\\[Vv]\[\d+\]', '9999', s)
    s = re.sub(r'\\[Nn]\[\d+\]', 'ИмяИмя', s)
    s = re.sub(r'\\[Pp]\[\d+\]', 'ИмяИмя', s)
    s = re.sub(r'\\[Cc]\[\d+\]', '', s)
    s = re.sub(r'\\[Ii]\[\d+\]', '  ', s)
    s = re.sub(r'\\[G$.|!<>^\\]', '', s)
    return s


def text_width(text: str, font_size: int = BASE_FONT_SIZE) -> int:
    """Общая ширина текста в пикселях."""
    clean = _strip_codes(text)
    return sum(_char_width(ch, font_size) for ch in clean)


def wrap_text(text: str, max_width: int,
              font_size: int = BASE_FONT_SIZE) -> list[str]:
    """Переносит текст по словам, чтобы каждая строка не превышала max_width.

    Возвращает список строк.
    """
    tokens = re.split(r'(\s+)', text)
    lines: list[str] = []
    current = ""

    for tok in tokens:
        candidate = current + tok
        if text_width(candidate, font_size) > max_width and current.strip():
            lines.append(current.rstrip())
            current = tok.lstrip()
        else:
            current = candidate

    if current.strip():
        lines.append(current.rstrip())

    return lines if lines else [""]


def fit_to_window(text: str,
                  window_width: int = DEFAULT_WINDOW_WIDTH,
                  visible_rows: int = DEFAULT_VISIBLE_ROWS,
                  start_font_size: int = BASE_FONT_SIZE) -> tuple[list[str], int]:
    """Подгоняет текст под окно диалога.

    Возвращает (строки, размер_шрифта).
    Алгоритм уменьшает шрифт, если текст не влезает в visibleRows.
    """
    font_size = start_font_size
    # отступы окна: ~12px с каждой стороны + padding
    content_width = window_width - 48

    for _retry in range(MAX_WRAP_RETRIES):
        lines = []
        for paragraph in text.split("\n"):
            if paragraph.strip():
                lines.extend(wrap_text(paragraph, content_width, font_size))
            else:
                lines.append("")

        if len(lines) <= visible_rows:
            return lines, font_size

        font_size -= 2
        if font_size < MIN_FONT_SIZE:
            break

    # Если всё ещё не влезает — обрезаем с многоточием
    result = lines[:visible_rows]
    if len(lines) > visible_rows and result:
        last = result[-1]
        if len(last) > 3:
            result[-1] = last[:-3] + "..."
    return result, font_size


def rewrap_game_message(texts: list[str],
                        window_width: int = DEFAULT_WINDOW_WIDTH,
                        visible_rows: int = DEFAULT_VISIBLE_ROWS) -> list[str]:
    """Переносит список строк $gameMessage._texts под реальную ширину.

    Используется при JSON-внедрении для предварительного переноса
    переведённого текста перед записью в файл.
    """
    full = "\n".join(texts)
    lines, _font_size = fit_to_window(full, window_width, visible_rows)
    return lines
