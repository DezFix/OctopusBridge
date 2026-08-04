from __future__ import annotations

PAIRS = ("ja-ru", "ja-en", "en-ru", "zh-en")
TIERS = ("fast", "best")

FAST_REPOS = {
    "ja-ru": "ooeoeo/opus-mt-ja-ru-ct2-float16",
    "ja-en": "ooeoeo/opus-mt-ja-en-ct2-float16",
    "en-ru": "ooeoeo/opus-mt-en-ru-ct2-float16",
    "zh-en": "ooeoeo/opus-mt-zh-en-ct2-float16",
}

NLLB_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"

NLLB_CODES = {
    "ja": "jpn_Jpan",
    "en": "eng_Latn",
    "ru": "rus_Cyrl",
    "zh": "zho_Hans",
    "ko": "kor_Hang",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
}

LANG_NAMES = {
    "ja": "японский",
    "en": "английский",
    "ru": "русский",
    "zh": "китайский",
    "ko": "корейский",
    "fr": "французский",
    "de": "немецкий",
    "es": "испанский",
    "it": "итальянский",
    "pt": "португальский",
}

TIER_INFO = {
    "fast": "OPUS-MT: отдельная маленькая модель на каждую пару (~60 МБ), очень быстро, база Tatoeba",
    "best": "NLLB-200 distilled 600M: одна модель на все пары (~1.2 ГБ), заметно лучше смысл, медленнее",
}


def check(tier: str, pair: str) -> None:
    if tier not in TIERS:
        raise ValueError(f"Неизвестный tier: {tier!r}. Доступно: {', '.join(TIERS)}")
    src, tgt = pair.split("-", 1)
    if tier == "fast":
        if pair not in PAIRS:
            raise ValueError(f"fast поддерживает только пары: {', '.join(PAIRS)}")
    elif src not in NLLB_CODES or tgt not in NLLB_CODES:
        raise ValueError(
            f"best-модель не поддерживает язык {src if src not in NLLB_CODES else tgt!r}. "
            f"Доступно: {', '.join(NLLB_CODES)}")


def repo_for(tier: str, pair: str) -> str:
    check(tier, pair)
    if tier == "fast":
        return FAST_REPOS[pair]
    return NLLB_REPO
