# -*- coding: utf-8 -*-
"""ИИ-корректор (M5): второй проход поверх машинного перевода.

LLM получает пачки «оригинал + черновик» с соседними строками (контекст
диалога) и правит орфографию, пунктуацию, согласования и стиль, не меняя
смысл. Плейсхолдеры <xN/> сохраняются. Работает с любым LLM-провайдером
(Ollama, OpenAI-совместимый API/OpenRouter).
"""
from __future__ import annotations

import json
from typing import Callable

from app.core.models import TranslationEntry
from .engines import BaseEngine, EngineError

BATCH = 8


class CorrectionDiff:
    """Одно предложение об исправлении (до принятия/отклонения)."""

    def __init__(self, entry: TranslationEntry,
                 old_text: str, new_text: str):
        self.entry = entry
        self.old_text = old_text
        self.new_text = new_text
        self.accepted = False


class Corrector:
    def __init__(self, engine: BaseEngine):
        if not hasattr(engine, "complete"):
            raise EngineError(
                "AI Correction requires an LLM provider "
                "(Ollama or OpenAI-compatible API)")
        self.engine = engine
        self.cancelled = False
        self.diffs: list[CorrectionDiff] = []

    def cancel(self):
        self.cancelled = True

    def _build_prompt(self, items: list[dict], tgt_lang: str) -> str:
        return (
            "You are a proofreader for a JRPG fan translation into "
            f"{'Russian' if tgt_lang == 'ru' else 'English'}. For each "
            "item you get JSON {\"o\": original, \"d\": draft}. Fix "
            "spelling, punctuation, grammar, gender/case agreement and "
            "style of the draft; keep the meaning; keep character names "
            "consistent; keep every placeholder like <x0/> exactly as-is. "
            "If a draft is already good, return it unchanged. Answer with "
            "ONLY a JSON array of corrected draft strings, same length.\n"
            + json.dumps(items, ensure_ascii=False)
        )

    def _parse_response(self, response: str, expected: int) -> list[str] | None:
        try:
            start = response.index("[")
            end = response.rindex("]") + 1
            fixed = json.loads(response[start:end])
        except (ValueError, json.JSONDecodeError):
            return None
        if isinstance(fixed, list) and len(fixed) == expected:
            return [str(x).strip() for x in fixed]
        return None

    def compute_corrections(
        self,
        entries: list[TranslationEntry],
        tgt_lang: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[CorrectionDiff]:
        """Вычисляет предложения об исправлении, не изменяя записи."""
        targets = [e for e in entries
                   if e.translation.strip()
                   and e.status in ("translated", "manual")]
        total = len(targets)
        done = 0
        diffs: list[CorrectionDiff] = []
        for i in range(0, total, BATCH):
            if self.cancelled:
                break
            batch = targets[i:i + BATCH]
            items = [{"o": e.original, "d": e.translation} for e in batch]
            prompt = self._build_prompt(items, tgt_lang)
            response = self.engine.complete(prompt)
            fixed = self._parse_response(response, len(batch))
            if fixed:
                for e, new_text in zip(batch, fixed):
                    if new_text and new_text != e.translation:
                        diffs.append(CorrectionDiff(
                            e, e.translation, new_text))
            done += len(batch)
            if progress:
                progress(done, total)
        return diffs

    def correct_all(
        self,
        entries: list[TranslationEntry],
        tgt_lang: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Вычисляет все исправления и сохраняет их в self.diffs.

        Возвращает число предложенных исправлений. Результат доступен в
        self.diffs для показа в диалоге подтверждения (UI не применяет
        исправления автоматически).
        """
        self.diffs = self.compute_corrections(entries, tgt_lang, progress)
        return len(self.diffs)

    def correct_entries(
        self,
        entries: list[TranslationEntry],
        tgt_lang: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Корректирует переведённые записи на месте. Возвращает число исправленных."""
        diffs = self.compute_corrections(entries, tgt_lang, progress)
        for d in diffs:
            d.entry.translation = d.new_text
            d.entry.status = "corrected"
        return len(diffs)
