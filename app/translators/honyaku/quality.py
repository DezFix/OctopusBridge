from __future__ import annotations

import re
from collections import Counter

_WORD = re.compile(r"\w+", re.UNICODE)

# Средний log-prob на токен ниже порога — модель «несла уверенную чушь».
# Калибровано на ja-ru: норма до -0.97 (с флуктуацией ±0.04 между
# запусками), мусор стабильно от -1.1.
SCORE_THRESHOLD = -1.0

# Доля слов, чей «корень» (первые 5 символов) повторяется. Выше порога —
# типичная галлюцинация OPUS-MT ("библиотека библиотека").
REPEAT_THRESHOLD = 0.25

# Доля букв в письме целевого языка. Ниже — модель не перевела текст
# или перевела не в тот язык.
SCRIPT_THRESHOLD = 0.5


def _stem(word: str) -> str:
    return word.lower()[:5]


def repeated_stems_ratio(text: str) -> float:
    """Доля слов с повторяющимся корнем (срабатывает на "библиотека
    библиотека", "эта игра… эта игра", "любимей любят года сак вокра…")."""
    words = _WORD.findall(text)
    if len(words) < 4:
        return 0.0
    stems = [_stem(w) for w in words]
    counts = Counter(stems)
    repeated = sum(1 for s in stems if counts[s] > 1)
    return repeated / len(stems)


def _is_cyrillic(ch: str) -> bool:
    c = ord(ch)
    return 0x0400 <= c <= 0x04FF or ch in "Ёё"

def _is_latin(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()

def _is_japanese(ch: str) -> bool:
    c = ord(ch)
    return (
        0x3040 <= c <= 0x30FF  # хирагана/катакана
        or 0x3400 <= c <= 0x4DBF  # кандзи (ext. A)
        or 0x4E00 <= c <= 0x9FFF  # кандзи
    )


def script_fit(text: str, tgt: str) -> float:
    """Доля букв, принадлежащих письму целевого языка."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 1.0
    if tgt == "ru":
        good = sum(_is_cyrillic(ch) for ch in letters)
    elif tgt == "ja":
        good = sum(_is_japanese(ch) for ch in letters)
    elif tgt == "en":
        good = sum(_is_latin(ch) for ch in letters)
    else:
        return 1.0
    return good / len(letters)


def suspicious(text: str, tgt: str, avg_score: float) -> bool:
    """Перевод — вероятная галлюцинация (повторы, чужое письмо, низкий скор)."""
    if not text:
        return False
    if len(text) > 6 and avg_score < SCORE_THRESHOLD:
        return True
    if len(text) > 3 and repeated_stems_ratio(text) > REPEAT_THRESHOLD:
        return True
    if script_fit(text, tgt) < SCRIPT_THRESHOLD:
        return True
    return False
