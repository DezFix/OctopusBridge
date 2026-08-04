# -*- coding: utf-8 -*-
"""Фиксеры результата перевода.

LLM-модели «доделывают» текст: переводят CJK-пунктуацию в ASCII,
экраннируют слэши, превращают кружочные цифры ① в обычные и
вставляют собственные коды (например скопированный [name]).

Каждый фиксер — чистая функция; применяется после движка, до
возврата результата. Срабатывает только если кандидат (CJK-знак,
двойной слэш, кружочная цифра, лишний код) реально есть в тексте.
"""
from __future__ import annotations

import re

# ---------- code: лишние коды ----------


def fix_codes(text: str, original: str) -> str:
    """Удаляет лишние коды, которых нет в оригинале (модель их сочинила).

    Работает на восстановленном тексте: mask() снова вытащит
    все [..]/{..}/\\V[..]. Удаляются только экземпляры сверх
    количества, встречающегося в оригинале.
    """
    if not text or text == original:
        return text
    from .mask import mask

    _, codes = mask(text)
    if not codes:
        return text
    result = text
    for code in dict.fromkeys(codes):
        have = result.count(code)
        want = original.count(code)
        if have <= want:
            continue
        for _ in range(have - want):
            result = result.replace(code, "", 1)
    return result


# ---------- escape: слэши ----------


def fix_escape(text: str, original: str) -> str:
    """Снимает лишнее экранирование слэшей, внесённое моделью.

    Если в оригинале не было двойного слэша, а в переводе он
    появился (``\\\\``), снимаем дубль — один `\\` оставляем.
    """
    if "\\\\" not in text or "\\\\" in original:
        return text
    return text.replace("\\\\", "\\")


# ---------- number: кружочные цифры ----------

_CIRCLE_RE = re.compile("[①-⑳]")


def _mask_groups(text: str) -> tuple[str, list[str]]:
    """Маскирует все сбалансированные [..]/{..} группы (числа внутри
    кодов не должны попасть под замену кружочными цифрами)."""
    codes: list[str] = []
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] in "[{":
            start = i
            depth = 1
            i += 1
            while i < n and depth > 0:
                if text[i] in "[{":
                    depth += 1
                elif text[i] in "]}":
                    depth -= 1
                i += 1
            group = text[start:i]
            if depth == 0:
                codes.append(group)
                out.append(f"\x00N{len(codes) - 1}\x00")
                continue
            out.append(group)
            continue
        out.append(text[i])
        i += 1
    return "".join(out), codes


def fix_number(text: str, original: str) -> str:
    """Возвращает кружочные цифры ①-⑳ на место.

    В оригинале были ①② — модель перевела их как "1 2".
    Сопоставляем по порядку появления: первые N обычных чисел
    в переводе заменяются на кружочные из оригинала. Числа
    внутри кодов [..]/{..} не трогаем.
    """
    if not text or text == original:
        return text
    circles = _CIRCLE_RE.findall(original)
    if not circles:
        return text
    masked, codes = _mask_groups(text)
    if not re.search(r"\d", masked):
        return text
    # токены \x00Nk\x00 содержат цифры — временно прячем их
    tmp = re.sub(r"\x00N\d+\x00", "\x00X\x00", masked)
    i = 0

    def repl(m: re.Match) -> str:
        nonlocal i
        if i < len(circles):
            c = circles[i]
            i += 1
            return c
        return m.group(0)

    replaced = re.sub(r"\d+", repl, tmp, count=len(circles))
    if not codes:
        return replaced
    restored = []
    k = 0
    j = 0
    while j < len(replaced):
        if replaced[j:j + 3] == "\x00X\x00":
            restored.append(codes[k])
            k += 1
            j += 3
        else:
            restored.append(replaced[j])
            j += 1
    return "".join(restored)


# ---------- punctuation: CJK-знаки ----------

_CJK_PUNCT = {
    "\u3002": ".",   # 。
    "\uff01": "!",   # ！
    "\uff1f": "?",   # ？
    "\uff0c": ",",   # ，
    "\uff1a": ":",   # ：
    "\uff1b": ";",   # ；
    "\u3001": ",",   # 、
    "\uff5e": "~",   # ～
}
# пробел между кириллическими словами, слипшимися вокруг знака
_WORD_GAP_RE = re.compile("([А-Яа-яЁё])([.!?,;:])([А-Яа-яЁё])")
# символы, после которых не ставим пробел (знаки, кавычки, скобки)
_NO_GAP_AFTER = set(" \t.!?,;:)]}>»»“”\"'…")


def fix_punctuation(text: str, src: str, tgt: str) -> str:
    """Заменяет CJK-пунктуацию на знаки целевого языка.

    Для таргета ja/zh — ничего не делаем. После заменённого знака
    вставляется пробел (если дальше идёт слово), а вокруг уже
    существующих .!? между кириллическими словами пробел
    восстанавливается.
    """
    if tgt in ("ja", "zh"):
        return text
    chars = list(text)
    n = len(chars)
    out = []
    for i, ch in enumerate(chars):
        repl = _CJK_PUNCT.get(ch)
        if repl is not None:
            out.append(repl)
            nxt = chars[i + 1] if i + 1 < n else ""
            if nxt and nxt not in _NO_GAP_AFTER:
                out.append(" ")
        else:
            out.append(ch)
    text = "".join(out)
    return _WORD_GAP_RE.sub(r"\1\2 \3", text)


# ---------- case: регистр первой буквы ----------


def fix_leading_case(text: str, original: str) -> str:
    """Восстанавливает регистр первой буквы, изменённый моделью.

    Honyaku (NLLB-200/OPUS-MT) капитализирует начало строки; если
    строка начиналась с маскированного кода (v[config.version]), под
    удар попадает первая буква: "v[config.version]" -> "V[config.version]".
    """
    if not text or not original or text == original:
        return text
    if (text[0].isalpha() and original[0].isalpha()
            and text[0].lower() == original[0].lower()
            and text[0] != original[0]):
        return original[0] + text[1:]
    return text


# ---------- numbers: знаки чисел ----------

_NUM_TOKEN_RE = re.compile(r"-?\d+")


def fix_number_signs(text: str, original: str) -> str:
    """Возвращает потерянные знаки минуса у чисел.

    Honyaku (NLLB-200/OPUS-MT) выбрасывает ведущий минус: "Visible Day: -1"
    -> "Видимый день: 1". Сопоставляем числа по порядку появления;
    если цифры совпадают, а знак оригинала был минусом — возвращаем.
    """
    if not text or not original or text == original:
        return text
    src_toks = _NUM_TOKEN_RE.findall(original)
    dst_toks = _NUM_TOKEN_RE.findall(text)
    if len(src_toks) != len(dst_toks) or not src_toks:
        return text
    if not any(s != d and s.startswith("-")
               and s.lstrip("-") == d.lstrip("-")
               for s, d in zip(src_toks, dst_toks)):
        return text
    it = iter(src_toks)

    def repl(m: re.Match) -> str:
        s = next(it)
        if s.startswith("-") and m.group(0).lstrip("-") == s.lstrip("-"):
            return s
        return m.group(0)

    return _NUM_TOKEN_RE.sub(repl, text)


# ---------- сборка ----------


def apply_fixers(text: str, src: str, tgt: str, original: str) -> str:
    """Применяет все фиксеры в порядке:
    code → escape → number → number_signs → punctuation → leading_case."""
    if text == original:
        return text
    text = fix_codes(text, original)
    text = fix_escape(text, original)
    text = fix_number(text, original)
    text = fix_number_signs(text, original)
    text = fix_punctuation(text, src, tgt)
    text = fix_leading_case(text, original)
    return text
