# -*- coding: utf-8 -*-
"""Глоссарий: закреплённые переводы терминов и имён.

Формат файла (JSON): {"ja->ru": {"アイラ": "Айра" | {"tr": "Айра", "group": "имена"}}}
Значение может быть строкой (старый формат) или словарём с полями
tr (перевод) и group (категория). При переводе строка режется на
сегменты по найденным терминам: термины подставляются из глоссария
как есть, остальное переводится движком.
"""
from __future__ import annotations

import json
import os
import re


def _norm(value) -> tuple[str, str]:
    """Нормализация значения термина -> (перевод, категория)."""
    if isinstance(value, dict):
        return (str(value.get("tr", "")), str(value.get("group", "")))
    return (str(value), "")


class Glossary:
    def __init__(self, path: str):
        self.path = path
        self.data: dict[str, dict] = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)

    def terms(self, src: str, tgt: str) -> dict[str, str]:
        """Термины как {термин: перевод} — для трансляторов."""
        return {t: _norm(v)[0]
                for t, v in (self.data.get(f"{src}->{tgt}") or {}).items()
                if t and _norm(v)[0]}

    def entries(self, src: str, tgt: str) -> dict[str, dict]:
        """Термины с категориями: {термин: {"tr": ..., "group": ...}}."""
        return {t: {"tr": _norm(v)[0], "group": _norm(v)[1]}
                for t, v in (self.data.get(f"{src}->{tgt}") or {}).items()
                if t}

    def groups(self, src: str, tgt: str) -> list[str]:
        """Список категорий (в порядке первого появления)."""
        seen: list[str] = []
        for e in self.entries(src, tgt).values():
            g = e["group"]
            if g and g not in seen:
                seen.append(g)
        return seen

    def set_terms(self, src: str, tgt: str, terms: dict[str, str]):
        """Запись простых терминов (категории сохраняются по ключу)."""
        old = self.entries(src, tgt)
        merged = {}
        for t, tr in terms.items():
            if not t:
                continue
            g = old.get(t, {}).get("group", "") if t in old else ""
            merged[t] = {"tr": tr, "group": g}
        self.data[f"{src}->{tgt}"] = merged
        self.save()

    def set_entries(self, src: str, tgt: str,
                    entries: dict[str, str | dict]):
        """Запись терминов с категориями ({термин: str | {tr, group}})."""
        merged = {}
        for t, v in entries.items():
            if not t:
                continue
            tr, g = _norm(v)
            merged[t] = {"tr": tr, "group": g}
        self.data[f"{src}->{tgt}"] = merged
        self.save()

    def split_by_terms(self, text: str, src: str, tgt: str) -> list[tuple[str, str | None]]:
        """Режет текст на сегменты: (кусок, перевод_из_глоссария|None)."""
        terms = self.terms(src, tgt)
        found = {t: tr for t, tr in terms.items() if t and t in text}
        if not found:
            return [(text, None)]
        pattern = re.compile("(" + "|".join(re.escape(t) for t in sorted(
            found, key=len, reverse=True)) + ")")
        return [(part, found.get(part)) for part in pattern.split(text) if part]