from __future__ import annotations

TIERS = ("best",)

NLLB_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"

# Код языков в терминологии NLLB-200. Модель знает все 200 языков NLLB —
# достаточно добавить код сюда (и в LANG_NAMES) одной строкой.
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
    "best": "NLLB-200 distilled 600M: одна модель на все пары (~1.2 ГБ), 200 языков, int8",
}


def check(tier: str, pair: str) -> None:
    if tier not in TIERS:
        raise ValueError(f"Неизвестный tier: {tier!r}. Доступно: {', '.join(TIERS)}")
    src, tgt = pair.split("-", 1)
    if src not in NLLB_CODES or tgt not in NLLB_CODES:
        raise ValueError(
            f"Модель не поддерживает язык {src if src not in NLLB_CODES else tgt!r}. "
            f"Доступно: {', '.join(NLLB_CODES)}"
        )


def repo_for(tier: str, pair: str) -> str:
    check(tier, pair)
    return NLLB_REPO
