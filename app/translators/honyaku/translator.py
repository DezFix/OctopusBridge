from __future__ import annotations

import re

from . import registry
from .download import ensure_model
from .engine import Engine, NLLBEngine
from .preprocess import chunk_text, has_letters, normalize, split_sentences, split_templates


# ── короткие строки: без модели ──────────────────────────────────────
# OPUS-MT на "A"/"AA" галлюцинирует простыни, NLLB добавляет знаки
# ("A" -> "А.", "C" -> "В)"). Буквенные хоткеи и коды меню (A, B, AA,
# DDD, HP…) переводим детерминированной транслитерацией в кириллицу.
_LATIN2CYR = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "АВСДЕФГХИЙКЛМНОПКРСТУВВХЫЗавсдефгхийклмнопкрстуввхыз",
)
_SHORT_LATIN_RE = re.compile(r"^[A-Za-z]{1,3}$")
_VOWELS = set("aeiouyAEIOUY")


def _short_latin(text: str, tgt: str) -> str | None:
    """Детерминированный перевод короткой латинской строки.

    Хоткей (одиночная буква), буквенный код без гласных (DDD, HP)
    или повторяющиеся буквы (AA, DDD, FF) транслитерируются в
    кириллицу — только для целевого русского. Слова (No, OK, Yes)
    отдаём модели. Возвращает None, если заглушка неприменима.
    """
    if tgt != "ru" or not _SHORT_LATIN_RE.match(text):
        return None
    if len(text) == 1:
        return text.translate(_LATIN2CYR)
    if not any(c in _VOWELS for c in text):
        return text.translate(_LATIN2CYR)
    if len(set(text)) == 1:
        return text.translate(_LATIN2CYR)
    return None


# NLLB/OPUS-MT любят добавлять знаки в конец коротких слов:
# "OK" -> "Хорошо.", "Yes" -> "Да , это так .". Для нормальных
# предложений пунктуация модели корректна — трим только короткие
# входы (меню, кнопки), у которых знаков в оригинале не было.
_TRAIL_PUNCT_RE = re.compile(r"\s*[.,!?;:]+$")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")


def _trim_model_punct(text: str, source: str) -> str:
    if not text or not source:
        return text
    s = source.strip()
    if len(s) <= 4 and not _TRAIL_PUNCT_RE.search(s):
        text = _TRAIL_PUNCT_RE.sub("", text)
        # "C" -> "В)": скобка добавлена моделью — убрать, если нет пары
        if text.endswith(")") and text.count("(") < text.count(")"):
            text = text[:-1].rstrip()
        text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    return text


# OPUS-MT на коротких строках галлюцинирует простыни ("OK" -> сотни
# слов). Если перевод непропорционально длиннее оригинала — это мусор,
# отдаём оригинал как есть (лучше без перевода, чем простыня).
def _guard_length(text: str, source: str) -> str:
    if source and len(text) > max(len(source) * 8, 20):
        return source
    return text


class Translator:
    def __init__(
        self,
        pair: str = "ja-ru",
        tier: str = "fast",
        device: str | None = None,
        threads: int | None = None,
        model_base=None,
        beam_size: int = 1,
        max_source_chars: int = 400,
        use_vmap: bool = False,
    ):
        registry.check(tier, pair)
        self.pair = pair
        self.tier = tier
        self._src, self._tgt = pair.split("-")
        self._device = device or "cpu"
        self._threads = threads
        self._model_base = model_base
        self._beam = beam_size
        self._max_chars = max_source_chars
        self._use_vmap = use_vmap
        self._engine = None

    @property
    def src_lang(self) -> str:
        return registry.LANG_NAMES[self._src]

    @property
    def tgt_lang(self) -> str:
        return registry.LANG_NAMES[self._tgt]

    def _ensure_engine(self):
        if self._engine is None:
            model_dir = ensure_model(self.tier, self.pair, self._model_base)
            if self.tier == "fast":
                self._engine = Engine(
                    model_dir=model_dir,
                    source_spm=model_dir / "source.spm",
                    target_spm=model_dir / "target.spm",
                    device=self._device,
                    threads=self._threads,
                    use_vmap=self._use_vmap,
                )
            else:
                self._engine = NLLBEngine(
                    model_dir=model_dir,
                    src_code=registry.NLLB_CODES[self._src],
                    tgt_code=registry.NLLB_CODES[self._tgt],
                    device=self._device,
                    threads=self._threads,
                    use_vmap=self._use_vmap,
                )
        return self._engine

    def translate(self, text: str, beam_size: int | None = None) -> str:
        return self.translate_batch([text], beam_size=beam_size)[0]

    def translate_batch(self, texts: list[str], beam_size: int | None = None) -> list[str]:
        if not texts:
            return []
        beam = self._beam if beam_size is None else beam_size
        engine = self._ensure_engine()
        plans = []
        jobs: list[str] = []
        quick: dict[int, str] = {}
        for i, text in enumerate(texts):
            s = _short_latin(text, self._tgt)
            if s is not None:
                quick[i] = s
                continue
            frags, temps = split_templates(normalize(text))
            plan = []
            for frag in frags:
                if not frag:
                    continue
                for p in split_sentences(frag, self._src):
                    if has_letters(p):
                        chunks = chunk_text(p, self._src, self._max_chars)
                        plan.append(("t", len(jobs), len(chunks)))
                        jobs.extend(chunks)
                    else:
                        plan.append(("p", p))
            for tpl in temps:
                plan.append(("k", tpl))
            plans.append(plan)
        translations = engine.translate(jobs, beam) if jobs else []
        out = [""] * len(texts)
        for i, plan in enumerate(plans):
            pieces = []
            for item in plan:
                if item[0] == "t":
                    _, start, n = item
                    pieces.extend(translations[start : start + n])
                else:
                    pieces.append(item[1])
            out[i] = _guard_length(
                _trim_model_punct("".join(pieces), texts[i]), texts[i])
        for i, s in quick.items():
            out[i] = s
        return out