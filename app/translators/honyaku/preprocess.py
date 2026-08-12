from __future__ import annotations

import re
import unicodedata

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACES = re.compile(r"[ \t\f\v]+")

_JA_BOUND = re.compile(r"(?<=[。！？!?…])|(?<=\n)")
# Точка/вопрос/восклицание, за которыми пробел или конец строки; вторая
# ветка — ещё и закрывающая кавычка/скобка между знаком и пробелом
# ("Hi." Then …). Обе ветки фиксированной ширины — допустимы в lookbehind.
_EN_BOUND = re.compile(
    r"(?<=[.!?…])(?=\s|$)|(?<=[.!?…][\"'»”’)\]}])(?=\s|$)|(?<=\n)"
)
_JA_HARD = re.compile(r"(?<=[、，,;；])")
_EN_HARD = re.compile(r"(?<=[,;])")

_PLACEHOLDER = re.compile(r"(\\[A-Za-z]\s*\[[^\[\]]*\]|<[^<>]{1,60}>|\{[^{}]{0,60}\})")

# Аббревиатуры, после которых точка не означает конец предложения.
# Проверка заякорена на конец строки: "Mr. Smith…" не склеивается,
# а "…, etc." склеивается со следующей частью.
_EN_ABBR = re.compile(
    r"(?:^|\s)(?:mr|mrs|ms|dr|prof|sr|jr|st|etc|e\.g|i\.e|vs|inc|ltd|co|fig|al)\."
    r"\s*$",
    re.IGNORECASE,
)


# Одиночный символ, не требующий перевода: цифра, пунктуация, символ/эмодзи,
# пробел или латинская буква-хоткей (A, a). Одиночные иероглифы/кириллица
# передаются модели.
_SINGLE_CATS = set("PSONZ")


def is_single_letter(text: str) -> bool:
    if len(text) != 1:
        return False
    ch = text
    if ch.isascii() and ch.isalpha():
        return True
    return ch.isdigit() or unicodedata.category(ch)[0] in _SINGLE_CATS


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = _CTRL.sub("", text)
    text = _SPACES.sub(" ", text)
    return text


def split_sentences(text: str, lang: str = "ja") -> list[str]:
    bound = _JA_BOUND if lang == "ja" else _EN_BOUND
    parts = [s for s in bound.split(text) if s]
    if lang != "ja":
        parts = _merge_en(parts)
    return parts


def _merge_en(parts: list[str]) -> list[str]:
    """Склеивает разорванные по точке предложения: после аббревиатур
    (e.g., etc., Mr. — нет: заякорено на конец) вроде "…, etc."."""
    merged: list[str] = []
    for part in parts:
        if merged and _EN_ABBR.search(merged[-1]):
            merged[-1] = merged[-1] + part
        else:
            merged.append(part)
    return merged


def has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)
