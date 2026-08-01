# -*- coding: utf-8 -*-
"""Глоссарий: закреплённые переводы терминов и имён.

Формат файла (JSON): {"ja->ru": {"アイラ": "Айра"}, ...}
При переводе строка режется на сегменты по найденным терминам: термины
подставляются из глоссария как есть, остальное переводится движком.
"""
from __future__ import annotations

import json
import os
import re


class Glossary:
    def __init__(self, path: str):
        self.path = path
        self.data: dict[str, dict[str, str]] = {}
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
        return self.data.get(f"{src}->{tgt}", {})

    def set_terms(self, src: str, tgt: str, terms: dict[str, str]):
        self.data[f"{src}->{tgt}"] = {k: v for k, v in terms.items() if k}
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
