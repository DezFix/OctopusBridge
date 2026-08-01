# -*- coding: utf-8 -*-
"""Автоглоссарий: извлечение имён и терминов из текстов игры через LLM.

Пользователь жмёт «Анализ терминов» — LLM выделяет из выборки текстов
имена персонажей/мест/предметов и предлагает их переводы, которые
добавляются в Glossary (закреплённый перевод, сохраняется при переводе).
"""
from __future__ import annotations

import json
import re

from .engines import LANG_NAMES


def analyze_terms(engine, texts: list[str], src_lang: str, tgt_lang: str,
                  max_chars: int = 12000) -> dict[str, str]:
    """Просит LLM выделить имена и ключевые термины с переводом.

    Возвращает {термин: перевод} после фильтрации мусора.
    engine должен быть LLM-движком (AIEngine) с методом complete().
    """
    sample: list[str] = []
    seen: set[str] = set()
    total = 0
    for t in texts:
        t = t.strip()
        if not t or len(t) > 200 or t in seen:
            continue
        seen.add(t)
        sample.append(t)
        total += len(t)
        if total >= max_chars:
            break
    if len(sample) < 5:
        return {}
    src = LANG_NAMES.get(src_lang, src_lang)
    tgt = LANG_NAMES.get(tgt_lang, tgt_lang)
    payload = json.dumps(sample[:80], ensure_ascii=False)
    prompt = (
        f"Here are game texts in {src}. Extract proper nouns and key terms:\n"
        f"- character, place, item, skill, status, faction names\n"
        f"- keep terms longer than 2 characters and up to 40 characters\n"
        f"- skip common words, numbers and lines that are already in {tgt}\n"
        f"Return a JSON array: [{{\"term\": \"original\", "
        f"\"trans\": \"translation to {tgt}\"}}].\n"
        f"Only include terms you are confident about.\n"
        f"Texts:\n{payload}"
    )
    content = engine.complete(prompt)
    found = _parse_terms(content)
    # для CJK-источников термин обязан содержать CJK/кану/хангыль —
    # иначе модель вернула переведённый текст, а не термин
    cjk_src = src_lang in ("ja", "zh", "ko")
    cjk_re = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")
    out: dict[str, str] = {}
    for term, trans in found.items():
        if not term or not trans or len(term) > 40:
            continue
        if term == trans:
            continue
        if cjk_src and not cjk_re.search(term):
            continue
        if re.search(r"</?x\d+\s*/?>", term):
            continue
        if "[" in term and "]" in term:
            continue
        out[term] = trans
    return out


def _parse_terms(content: str) -> dict[str, str]:
    """Разбирает ответ LLM: JSON-массив или JSONL-строки."""
    result: dict[str, str] = {}
    if not content:
        return result
    try:
        start = content.index("[")
        end = content.rindex("]") + 1
        arr = json.loads(content[start:end])
        if isinstance(arr, list):
            for obj in arr:
                if isinstance(obj, dict) and obj.get("term"):
                    result[str(obj["term"])] = str(obj.get("trans", ""))
            if result:
                return result
    except (ValueError, json.JSONDecodeError):
        pass
    for line in content.splitlines():
        line = line.strip().strip(",")
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("term"):
            result[str(obj["term"])] = str(obj.get("trans", ""))
    return result
