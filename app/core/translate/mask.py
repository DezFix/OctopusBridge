# -*- coding: utf-8 -*-
"""Маскирование управляющих кодов (RPG Maker, Ren'Py) перед машинным переводом.

\\V[1], \\fs[14], \\C[3], \\{, теги плагинов <center>, printf %1,
интерполяция Ren'Py [expr!t] заменяются на XML-токены <x0/> —
Honyaku и LLM сохраняют их, в отличие от ⟦0⟧.
"""
from __future__ import annotations

import re

# порядок важен: от более специфичных к менее специфичным
_CODE_RE = re.compile(
    r'(\\\\'                      # \\
    r'|\\[A-Za-z]*\[[^\]]*\]'     # \V[1], \fs[14], \PX[0], \I[4]...
    r'|\\[A-Za-z]+'               # \C \FS ...
    r'|\\[{}<>|.!^_]'             # \{ \} \< \> \. \| \! \^ \_
    r'|\\'                        # одиночный \
    r'|%[0-9]+'                   # %1 (printf в terms.messages)
    r'|</?[A-Za-z][^>]{0,30}>'    # <center>, </center> — теги плагинов
    r'|\[\['                      # [[ — экранированная скобка Ren'Py
    r'|\[[^\[\]\n]{1,120}\]'      # [expr] — интерполяция Ren'Py (см. guard)
    r')'
)

# содержимое [..] маскируем только если похоже на код (переменная/вызов),
# а не на обычный текст в скобках
_CJK_CYR_RE = re.compile(r'[぀-ヿㇰ-ㇿ一-鿿㐀-䶿가-힯Ѐ-ӿ]')
_CODE_HINT_RE = re.compile(r'[._()$\'"+*/%=<>&|!]')
_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_ ]*$')


def _looks_like_code(inner: str) -> bool:
    """'picked_option.title', '$x', 'fn(1)' — код; '[Save]' — текст."""
    inner = inner.strip()
    if not inner or _CJK_CYR_RE.search(inner):
        return False
    return bool(_CODE_HINT_RE.search(inner) or _IDENT_RE.match(inner))

# толерантно к искажениям движка: <x0/>, <x0>, </x0>, <x0 / >
_token_re = re.compile(r'</?x(\d+)\s*/?>')


def token(index: int) -> str:
    return f"<x{index}/>"


def mask(text: str) -> tuple[str, list[str]]:
    """Возвращает (замаскированный текст, список вырезанных кодов).

    Кандидаты [..] маскируются только если похожи на код Ren'Py —
    переводчик иначе ломает интерполяцию ([picked_option.title] ->
    'picked option.title' -> SyntaxError в игре). Обычный текст
    в скобках остаётся переводимым.
    """
    codes: list[str] = []

    def repl(m: re.Match) -> str:
        g = m.group(0)
        if g.startswith("[") and g != "[[":
            if not _looks_like_code(g[1:-1]):
                return g
        codes.append(g)
        return token(len(codes) - 1)

    return _CODE_RE.sub(repl, text), codes


def unmask(text: str, codes: list[str]) -> str:
    """Восстанавливает коды по токенам <xN/>."""
    def repl(m: re.Match) -> str:
        i = int(m.group(1))
        return codes[i] if i < len(codes) else m.group(0)

    return _token_re.sub(repl, text)


def validate(text: str, codes: list[str]) -> bool:
    """Проверяет, что все токены на месте после перевода."""
    found = sorted(int(m.group(1)) for m in _token_re.finditer(text))
    return found == list(range(len(codes)))


def tokens_present(text: str) -> bool:
    """Есть ли в тексте хоть какие-то токены (для мягкой проверки)."""
    return bool(_token_re.search(text))


# ---------- TextPreserve: check / prefix / suffix ----------

# краевой код: {tag} — теги Ren'Py (не входят в _CODE_RE)
_EDGE_EXTRA_RE = re.compile(r"\{[^}\n]{1,120}\}")


def split_edge_codes(text: str) -> tuple[list[str], str, list[str]]:
    """TextPreserve prefix/suffix: вырезает коды с краёв строки.

    Краевые коды ([person], {image=x}, \\V[1] в начале/конце строки)
    переводчики теряют чаще всего. Возвращает (коды_в_начале, середина,
    коды_в_конце) — середину можно безопасно отправлять движку,
    коды приклеиваются обратно к результату.
    """
    lead: list[str] = []
    rest = text
    while True:
        m = _CODE_RE.match(rest) or _EDGE_EXTRA_RE.match(rest)
        if not m:
            break
        g = m.group(0)
        if g.startswith("[") and g != "[[" and not _looks_like_code(g[1:-1]):
            break
        lead.append(g)
        rest = rest[m.end():]
    trail: list[str] = []
    end = rest
    while True:
        # самый правый код, доходящий до конца строки
        cands = []
        for rx in (_CODE_RE, _EDGE_EXTRA_RE):
            ms = list(rx.finditer(end))
            if ms:
                cands.append(ms[-1])
        if not cands:
            break
        m = max(cands, key=lambda mm: mm.start())
        if m.end() != len(end):
            break
        g = m.group(0)
        if g.startswith("[") and g != "[[" and not _looks_like_code(g[1:-1]):
            break
        trail.insert(0, g)
        end = end[:m.start()]
    return lead, end, trail


def is_code_only(masked: str) -> bool:
    """TextPreserve check: True, если после маскирования в строке не
    осталось букв/цифр — только токены и пунктуация. Такую строку
    (например [config.version]) не отправляем движку перевода."""
    return not re.search(r"\w", _token_re.sub("", masked))
