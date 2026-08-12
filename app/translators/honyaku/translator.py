from __future__ import annotations

import re
import threading
from collections import OrderedDict

from . import registry
from .download import ensure_model
from .engine import Engine
from .preprocess import _PLACEHOLDER, has_letters, is_single_letter, normalize, split_sentences
from .quality import suspicious
# Одиночные кана/кириллица (кнопки кана-клавиатуры ホ, ァ; хоткеи Б, Д) —
# не слова: NLLB галлюцинирует на них («Домой» вместо ホ). В preprocess
# их нет — добавляем из общих словарей алфавитов приложения.
from app.core.translate.alphabets import is_single_letter as _is_alphabet_letter


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


# ── глоссарий ────────────────────────────────────────────────────────
# Термины подменяются плейсхолдерами {g0}, {g1}… до перевода и
# восстанавливаются после — до модели плейсхолдеры не доходят.
_LATIN_TERM = re.compile(r"^[A-Za-z0-9 _'.-]+$")


def _glossary_regex(term: str) -> re.Pattern | None:
    if _LATIN_TERM.match(term):
        return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])", re.IGNORECASE)
    if term and all(ch.isalnum() for ch in term):
        return re.compile(re.escape(term))
    return None


class Translator:
    FALLBACKS = ("off", "source", "best")

    def __init__(
        self,
        pair: str = "ja-ru",
        device: str | None = None,
        threads: int | None = None,
        model_base=None,
        beam_size: int = 1,
        max_tokens: int = 480,
        use_vmap: bool = False,
        glossary: dict[str, str] | None = None,
        cache_size: int = 4096,
        fallback: str = "source",
    ):
        registry.check("best", pair)
        if fallback not in self.FALLBACKS:
            raise ValueError(f"Неизвестный fallback: {fallback!r}. Доступно: {', '.join(self.FALLBACKS)}")
        self.pair = pair
        self._src, self._tgt = pair.split("-")
        self._device = device or "cpu"
        self._threads = threads
        self._model_base = model_base
        self._beam = beam_size
        self._max_tokens = max_tokens
        self._use_vmap = use_vmap
        self._fallback = fallback
        self._engine = None
        self._fallback_engine = None
        self._glossary: dict[str, str] = dict(glossary or {})
        self._cache: OrderedDict = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        # Модель НЕ потокобезопасна: sentencepiece-токенизатор и вызовы
        # движка делят один экземпляр между потоками (реалтайм + файлы +
        # корректор используют один общий Translator из кэша _WARMED) —
        # одновременный translate_batch с разных потоков роняет процесс
        # в _sentencepiece.pyd (access violation). Сериализуем модель.
        self._model_lock = threading.Lock()

    @property
    def src_lang(self) -> str:
        return registry.LANG_NAMES[self._src]

    @property
    def tgt_lang(self) -> str:
        return registry.LANG_NAMES[self._tgt]

    def _ensure_engine(self):
        if self._engine is None:
            model_dir = ensure_model("best", self.pair, self._model_base)
            self._engine = Engine(
                model_dir=model_dir,
                src_code=registry.NLLB_CODES[self._src],
                tgt_code=registry.NLLB_CODES[self._tgt],
                device=self._device,
                threads=self._threads,
                use_vmap=self._use_vmap,
                max_tokens=self._max_tokens,
            )
        return self._engine

    def _ensure_fallback_engine(self):
        """Подстраховка галлюцинаций: тот же NLLB, но с beam=4 —
        дорогой повторный поиск часто исправляет «уверенную чушь»."""
        if self._fallback_engine is None:
            self._fallback_engine = self._engine
        return self._fallback_engine

    def _glossary_inject(self, text: str) -> tuple[str, dict[str, str]]:
        if not self._glossary:
            return text, {}
        replacements: dict[str, str] = {}
        out = text
        for n, (term, value) in enumerate(sorted(self._glossary.items(), key=lambda kv: len(kv[0]), reverse=True)):
            if not term or term == value:
                continue
            ph = f"{{g{n}}}"
            rx = _glossary_regex(term)
            if rx is None:
                continue
            new, count = rx.subn(ph, out)
            if count:
                out = new
                replacements[ph] = value
        return out, replacements

    def _cache_get(self, key: tuple) -> str | None:
        with self._lock:
            val = self._cache.get(key)
            if val is not None:
                self._cache.move_to_end(key)
            return val

    def _cache_set(self, key: tuple, value: str) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def translate(self, text: str, beam_size: int | None = None) -> str:
        return self.translate_batch([text], beam_size=beam_size)[0]

    def translate_batch(self, texts: list[str], beam_size: int | None = None) -> list[str]:
        if not texts:
            return []
        beam = self._beam if beam_size is None else beam_size

        # Pass 1: хоткеи/одиночные символы и кэш — без модели; остальное
        # разбивается на предложения (модель нужна только для них).
        quick: dict[int, str] = {}
        skeleton: list[tuple[int, str, list]] = []
        for i, text in enumerate(texts):
            s = _short_latin(text, self._tgt)
            if s is not None:
                quick[i] = s
                continue
            if is_single_letter(text) or _is_alphabet_letter(text):
                quick[i] = text
                continue
            norm = normalize(text)
            cached = self._cache_get((norm, beam))
            if cached is not None:
                quick[i] = cached
                continue
            with_terms, replacements = self._glossary_inject(norm)
            items: list[tuple[str, str]] = []
            # Плейсхолдеры (в т.ч. глоссарные {gN}) остаются на своих
            # позициях, фрагменты текста режутся на предложения.
            for idx, part in enumerate(_PLACEHOLDER.split(with_terms)):
                if not part:
                    continue
                if idx % 2 == 1:
                    items.append(("k", part))
                else:
                    for p in split_sentences(part, self._src):
                        if has_letters(p):
                            items.append(("s", p))
                        else:
                            items.append(("p", p))
            skeleton.append((i, norm, replacements, items))

        with self._model_lock:
            needs_model = any(("s" in [it[0] for it in items])
                              for _, _, _, items in skeleton)
            engine = self._ensure_engine() if needs_model else None

            # Pass 2: чанкинг по токенам движка (не режем посреди слова и
            # не превышаем лимит контекста модели), перевод единым батчем.
            plans: list[tuple[int, str, dict, list]] = []
            jobs: list[str] = []
            for i, norm, replacements, items in skeleton:
                plan = []
                for kind, val in items:
                    if kind == "s":
                        for chunk in engine.chunk(val):
                            plan.append(("t", len(jobs)))
                            jobs.append(chunk)
                    else:
                        plan.append((kind, val))
                plans.append((i, norm, replacements, plan))

            detect = self._fallback != "off"
            results = (engine.translate(jobs, beam, return_scores=detect)
                       if jobs else [])

            # Детекция галлюцинаций: повторы, чужое письмо, низкий скор.
            translations: list[str] = []
            flagged: list[int] = []
            if detect:
                for idx, (text, score) in enumerate(results):
                    if suspicious(text, self._tgt, score):
                        flagged.append(idx)
                        translations.append("")
                    else:
                        translations.append(text)
            else:
                translations = list(results)

            if flagged:
                if self._fallback == "best":
                    fb = self._ensure_fallback_engine()
                    fb_res = fb.translate([jobs[i] for i in flagged],
                                          beam_size=4)
                    for k, i in enumerate(flagged):
                        val = fb_res[k]
                        # Если и NLLB дал мусор — вернуть оригинал.
                        translations[i] = (
                            val if not suspicious(val, self._tgt, 0.0)
                            else jobs[i])
                else:  # "source": лучше без перевода, чем простыня
                    for i in flagged:
                        translations[i] = jobs[i]

            out = [""] * len(texts)
            for i, norm, replacements, plan in plans:
                pieces = []
                for item in plan:
                    if item[0] == "t":
                        pieces.append(translations[item[1]])
                    else:
                        pieces.append(item[1])
                translated = "".join(pieces)
                translated = _guard_length(
                    _trim_model_punct(translated, texts[i]), texts[i])
                for ph, value in replacements.items():
                    translated = translated.replace(ph, value)
                out[i] = translated
                self._cache_set((norm, beam), translated)
        for i, s in quick.items():
            out[i] = s
        return out
