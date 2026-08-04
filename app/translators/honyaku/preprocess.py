from __future__ import annotations

import re
import unicodedata

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACES = re.compile(r"[ \t\f\v]+")

_JA_BOUND = re.compile(r"(?<=[。！？!?…])|(?<=\n)")
_EN_BOUND = re.compile(r"(?<=[.!?…])(?=\s|$)|(?<=\n)")
_JA_HARD = re.compile(r"(?<=[、，,;；])")
_EN_HARD = re.compile(r"(?<=[,;])")

_PLACEHOLDER = re.compile(r"(\\[A-Za-z]\s*\[[^\[\]]*\]|<[^<>]{1,60}>|\{[^{}]{0,60}\})")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _CTRL.sub("", text)
    text = _SPACES.sub(" ", text)
    return text


def split_sentences(text: str, lang: str = "ja") -> list[str]:
    bound = _JA_BOUND if lang == "ja" else _EN_BOUND
    return [s for s in bound.split(text) if s]


def chunk_text(text: str, lang: str = "ja", max_chars: int = 300) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    hard = _JA_HARD if lang == "ja" else _EN_HARD
    pieces = hard.split(text)
    chunks: list[str] = []
    cur = ""
    for p in pieces:
        while len(p) > max_chars:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:max_chars])
            p = p[max_chars:]
        if cur and len(cur) + len(p) > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        chunks.append(cur)
    return chunks


def has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def split_templates(text: str) -> tuple[list[str], list[str]]:
    parts = _PLACEHOLDER.split(text)
    return parts[0::2], parts[1::2]
