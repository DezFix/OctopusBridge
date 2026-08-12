# -*- coding: utf-8 -*-
"""Сервис перевода: склеивает определение языка, маскирование, глоссарий,
движок и память переводов."""
from __future__ import annotations

import re
from typing import Callable

from app.core.models import TranslationEntry
from .alphabets import is_single_letter
from .detect import detect_lang
from .engines import BaseEngine
from .fixers import apply_fixers
from .glossary import Glossary
from .mask import (is_code_only, mask, split_edge_codes, tokens_present,
                   unmask, validate)
from .memory import TranslationMemory

# батчи для LLM ограничиваем по примерному числу токенов, а не только
# по числу строк: длинные строки обрывают ответ модели.
# Пакеты крупнее = меньше запросов: Google отдаёт до 200 строк за раз,
# LLM-движки режут батч сами.
TARGET_TOKENS = 1500
MAX_BATCH_LINES = 100


def _estimate_tokens(text: str) -> int:
    """Грубая оценка токенов: CJK ~1 токен на символ, латиница ~1/4."""
    if re.search(r"[\u3000-\u9fff\uf900-\ufaff\uac00-\ud7af]", text):
        return max(len(text), 1)
    return max(len(text) // 4, 1)


def _reattach(text: str, lead: list[str], trail: list[str]) -> str:
    """Приклеивает краевые коды, если переводчик их не сохранил.

    Порядок кодов сохраняется: находим самый длинный префикс/суффикс,
    который движок уже вернул, и вставляем недостающие коды рядом,
    не дублируя сохранённые.
    """
    if lead:
        for j in range(len(lead), -1, -1):
            prefix = "".join(lead[:j])
            if text.startswith(prefix):
                if j < len(lead):
                    text = "".join(lead) + text[len(prefix):]
                break
    if trail:
        found = False
        for j in range(len(trail)):
            suffix = "".join(trail[j:])
            if text.endswith(suffix):
                text = text[:-len(suffix)] + "".join(trail)
                found = True
                break
        if not found:
            text = text + "".join(trail)
    return text


class Translator:
    def __init__(self, engine: BaseEngine, tm: TranslationMemory | None = None,
                 glossary: Glossary | None = None):
        self.engine = engine
        self.tm = tm
        self.glossary = glossary
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    # ---------- одна строка ----------
    def translate_text(self, text: str, src_lang: str, tgt_lang: str) -> str:
        """Переводит одну строку: TM -> глоссарий-сегменты -> движок."""
        if src_lang == "auto":
            detected = detect_lang(text)
            if not detected or detected == tgt_lang:
                return text
            src_lang = detected

        # одиночный знак алфавита (кана/кириллица/латиница) — не слово,
        # перевода не имеет; раньше чем TM: старый мусор «Домой» не должен
        # вылезать из кеша
        if is_single_letter(text):
            return text

        cached = self.tm.get(text, src_lang, tgt_lang) if self.tm else None
        if cached:
            return cached

        # TextPreserve prefix/suffix: краевые коды не отправляем движку,
        # приклеиваем к результату (переводчики их теряют чаще всего)
        lead, mid, trail = split_edge_codes(text)
        masked, codes = mask(mid)
        if is_code_only(masked):
            return "".join(lead) + mid + "".join(trail)
        segments = (self.glossary.split_by_terms(masked, src_lang, tgt_lang)
                    if self.glossary else [(masked, None)])
        out_parts: list[str] = []
        for segment, fixed in segments:
            if fixed is not None:
                out_parts.append(fixed)
                continue
            if not segment.strip():
                out_parts.append(segment)
                continue
            # TextPreserve check: строка только из кодов — движку не нужна
            if is_code_only(segment.strip()):
                out_parts.append(segment)
                continue
            # одиночный знак алфавита (кнопка кана-клавиатуры, хоткей) —
            # движку не отправляем, отдаём как есть
            if is_single_letter(segment.strip()):
                out_parts.append(segment)
                continue
            # движки нормализуют пробелы по краям — сохраняем их сами
            lead_ws = segment[:len(segment) - len(segment.lstrip())]
            trail_ws = segment[len(segment.rstrip()):]
            translated = self.engine.translate([segment.strip()],
                                               src_lang, tgt_lang)[0]
            # движок вернул пустое (звуки/короткие возгласы) — оригинал,
            # иначе текст в игре просто исчезает
            if not translated.strip() and segment.strip():
                translated = segment.strip()
            # мягкая проверка: unmask восстановит что сможет
            restored = (unmask(translated, codes)
                        if validate(translated, codes)
                        or tokens_present(translated)
                        else translated)
            # фиксерам нужен оригинал с кодами, а не с токенами <xN/>:
            # иначе fix_codes сочтёт все коды перевода "лишними" и сотрёт
            orig_codes = unmask(segment, codes) if codes else segment
            restored = apply_fixers(restored, src_lang, tgt_lang,
                                    orig_codes.strip())
            out_parts.append(lead_ws + restored + trail_ws)
        result = "".join(out_parts)
        result = _reattach(result, lead, trail)
        # В память переводов пишем только реальные переводы: иначе при
        # сбое движка (результат == оригинал) INSERT OR REPLACE затирает
        # хороший перевод мусором.
        if self.tm and result != text and result.strip():
            self.tm.put(text, result, src_lang, tgt_lang)
        return result

    # ---------- записи проекта ----------
    def translate_entries(
        self,
        entries: list[TranslationEntry],
        src_lang: str,
        tgt_lang: str,
        progress: Callable[[int, int], None] | None = None,
        overwrite: bool = False,
    ) -> int:
        """Переводит записи на месте. Возвращает число переведённых строк."""
        targets = [
            e for e in entries
            if e.status != "skip" and (overwrite or not e.translation.strip())
        ]
        total = len(targets)
        done = [0]  # общий счётчик для прогресса

        def report():
            if progress:
                progress(done[0], total)

        if src_lang == "auto":
            groups: dict[str, list[TranslationEntry]] = {}
            skipped = 0
            for e in targets:
                lang = detect_lang(e.original)
                if not lang or lang == tgt_lang:
                    skipped += 1
                    continue
                groups.setdefault(lang, []).append(e)
            done[0] += skipped
            report()
            for lang, group in groups.items():
                if self.cancelled:
                    break
                self._translate_group(group, lang, tgt_lang, done, report)
            return done[0] - skipped

        self._translate_group(targets, src_lang, tgt_lang, done, report)
        return done[0]

    def _translate_group(self, targets: list[TranslationEntry],
                         src_lang: str, tgt_lang: str,
                         done: list[int], report: Callable[[], None]):
        # дедупликация: одинаковые оригиналы переводим один раз
        unique: dict[str, list[TranslationEntry]] = {}
        for e in targets:
            unique.setdefault(e.original, []).append(e)

        # build ordered list of all originals for context lookup
        all_originals = [e.original for e in targets]

        batch_src: list[str] = []
        batch_holders: list[tuple[list[TranslationEntry], list[str],
                                  list[str], list[str]]] = []
        batch_indices: list[int] = []
        batch_tokens: list[int] = [0]

        def flush():
            if not batch_src:
                return
            if self.cancelled:
                batch_src.clear()
                batch_holders.clear()
                batch_indices.clear()
                batch_tokens[0] = 0
                return
            # collect context: neighbors of the batch
            first_idx = batch_indices[0] if batch_indices else 0
            last_idx = batch_indices[-1] if batch_indices else 0
            ctx_before = all_originals[max(0, first_idx - 3):first_idx] \
                if first_idx > 0 else None
            ctx_after = all_originals[last_idx + 1:last_idx + 4] \
                if last_idx < len(all_originals) - 1 else None

            translated = self.engine.translate(
                batch_src, src_lang, tgt_lang,
                context_before=ctx_before, context_after=ctx_after)
            tm_pairs: list[tuple[str, str]] = []
            for (holders, codes, lead, trail), masked_tr in \
                    zip(batch_holders, translated):
                if validate(masked_tr, codes):
                    text = unmask(masked_tr, codes)
                else:
                    text = self.engine.translate(
                        [holders[0].original], src_lang, tgt_lang)[0]
                if not text.strip():
                    text = holders[0].original   # пустое -> оригинал
                text = _reattach(text, lead, trail)
                text = apply_fixers(text, src_lang, tgt_lang,
                                    holders[0].original)
                for e in holders:
                    e.translation = text
                    e.status = "translated"
                    done[0] += 1
                if text != holders[0].original and text.strip():
                    tm_pairs.append((holders[0].original, text))
            if self.tm and tm_pairs:
                self.tm.put_many(tm_pairs, src_lang, tgt_lang)
            batch_src.clear()
            batch_holders.clear()
            batch_indices.clear()
            batch_tokens[0] = 0
            report()

        for idx, (original, holders) in enumerate(unique.items()):
            if self.cancelled:
                break
            cached = self.tm.get(original, src_lang, tgt_lang) if self.tm else None
            if cached:
                for e in holders:
                    e.translation = cached
                    e.status = "translated"
                    done[0] += 1
                continue
            # строки с терминами из глоссария — поштучно, чтобы сегментировать
            if self.glossary and any(
                    t in original for t in self.glossary.terms(src_lang, tgt_lang)):
                text = self.translate_text(original, src_lang, tgt_lang)
                for e in holders:
                    e.translation = text
                    e.status = "translated"
                    done[0] += 1
                continue
            # TextPreserve prefix/suffix: краевые коды уводим из батча
            lead, mid, trail = split_edge_codes(original)
            masked, codes = mask(mid)
            if is_code_only(masked):
                # TextPreserve check: строка только из кодов — без движка
                for e in holders:
                    e.translation = original
                    e.status = "translated"
                    done[0] += 1
                continue
            # одиночный знак алфавита — без движка, как есть
            if is_single_letter(masked):
                for e in holders:
                    e.translation = original
                    e.status = "translated"
                    done[0] += 1
                continue
            tokens = _estimate_tokens(masked)
            # строка не влезает в лимит — завершаем текущий батч
            # (строки не режем: длинная уйдёт отдельно)
            if batch_tokens[0] > 0 and batch_tokens[0] + tokens > TARGET_TOKENS:
                flush()
            batch_src.append(masked)
            batch_holders.append((holders, codes, lead, trail))
            # find actual position in the targets list for context
            pos = next((i for i, e in enumerate(targets) if e is holders[0]), idx)
            batch_indices.append(pos)
            batch_tokens[0] += tokens
            if batch_tokens[0] >= TARGET_TOKENS or len(batch_src) >= MAX_BATCH_LINES:
                flush()

        flush()
