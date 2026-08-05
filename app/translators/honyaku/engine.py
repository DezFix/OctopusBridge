from __future__ import annotations

import json
from pathlib import Path

import ctranslate2

from .tokenizer import Tokenizer

_COMPUTE_CANDIDATES = ("int8_float16", "int8", "float16", "float32")

# Токены, после которых безопасно резать длинный текст (не разрывая слово).
_CUT_CHARS = set("，。、！？…；：」』）】.,!?…;:)]}》")


def _build_translator(model_dir: Path, device: str, compute_type: str, threads: int | None) -> ctranslate2.Translator:
    kwargs: dict = {"compute_type": compute_type}
    if threads:
        kwargs["intra_threads"] = threads
    return ctranslate2.Translator(str(model_dir), device=device, **kwargs)


def _resolve_translator(model_dir: Path, device: str, threads: int | None) -> ctranslate2.Translator:
    """Подбирает compute_type и возвращает уже построенный движок.

    Автоподбор строит CTranslate2.Translator с каждым кандидатом; на CPU
    некоторые типы (int8_float16) могут быть не поддержаны. Важно: движок
    возвращается готовым, чтобы не строить его дважды (память ×2).
    """
    last_error: Exception | None = None
    for candidate in _COMPUTE_CANDIDATES:
        try:
            return _build_translator(model_dir, device, candidate, threads)
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Не удалось подобрать compute_type для модели: {last_error}")


def _check_vmap(ct: ctranslate2.Translator, probe: list[str]) -> bool:
    try:
        ct.translate_batch([probe], max_decoding_length=1, use_vmap=True)
        return True
    except Exception:
        return False


def _chunk_tokens(tokens: list[str], max_tokens: int) -> list[list[str]]:
    """Режет список токенов на чанки по max_tokens, предпочитая границы
    после пунктуации (не разрывая слово и не обрезая длинный текст —
    иначе модель молча обрежет вход по лимиту 512 токенов)."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    for tok in tokens:
        if len(cur) == max_tokens:
            cut = None
            for j in range(len(cur) - 1, len(cur) // 2 - 1, -1):
                if cur[j][-1] in _CUT_CHARS:
                    cut = j + 1
                    break
            if cut is not None:
                head, cur = cur[:cut], cur[cut:]
                chunks.append(head)
            else:
                chunks.append(cur)
                cur = []
        cur.append(tok)
    if cur:
        chunks.append(cur)
    return chunks


class Engine:
    """NLLB-200: одна мультиязычная модель, направление через target_prefix."""

    def __init__(
        self,
        model_dir: Path,
        src_code: str,
        tgt_code: str,
        device: str = "cpu",
        threads: int | None = None,
        use_vmap: bool = False,
        max_tokens: int = 500,
        max_length: int = 1024,
    ):
        self._tok = Tokenizer(str(model_dir / "sentencepiece.bpe.model"))
        self._ct = _resolve_translator(model_dir, device, threads)
        self._max_tokens = max_tokens
        self._max_length = max_length
        self._vmap = _check_vmap(self._ct, self._tok.encode("test")) if use_vmap else False
        json_path = model_dir / "shared_vocabulary.json"
        txt_path = model_dir / "shared_vocabulary.txt"
        if json_path.exists():
            self._vocab = json.loads(json_path.read_text(encoding="utf-8"))
        elif txt_path.exists():
            self._vocab = txt_path.read_text(encoding="utf-8").splitlines()
        else:
            raise FileNotFoundError(
                f"Не найден shared_vocabulary (.json/.txt) в {model_dir}"
            )
        self._src_tok = self._lang_token(src_code)
        self._tgt_tok = self._lang_token(tgt_code)

    def _lang_token(self, code: str) -> str:
        if code not in self._vocab:
            raise RuntimeError(f"Языковой код {code!r} отсутствует в словаре модели")
        return code

    def chunk(self, text: str, max_tokens: int | None = None) -> list[str]:
        # Пара токенов сверху уходит на <src_lang> и </s>.
        limit = (max_tokens or self._max_tokens) - 2
        # Декод токен-слайса может оставить литеральный ▁ в начале чанка —
        # это артефакт SentencePiece, а не текст.
        return [self._tok.decode(t).lstrip("▁") for t in _chunk_tokens(self._tok.encode(text), limit)]

    def translate(
        self, texts: list[str], beam_size: int = 1, return_scores: bool = False
    ) -> list[str] | list[tuple[str, float]]:
        if not texts:
            return []
        sources = [[self._src_tok] + self._tok.encode(t) + ["</s>"] for t in texts]
        prefix = [[self._tgt_tok]] * len(texts)
        kwargs: dict = {
            "beam_size": beam_size,
            "max_decoding_length": self._max_length,
            "target_prefix": prefix,
            "repetition_penalty": 1.5,
            "no_repeat_ngram_size": 3,
            "length_penalty": 0.2,
            "replace_unknowns": True,
            "batch_type": "tokens",
            "max_batch_size": 8192,
        }
        if return_scores:
            kwargs["return_scores"] = True
        if self._vmap:
            kwargs["use_vmap"] = True
        results = self._ct.translate_batch(sources, **kwargs)
        out = []
        for r in results:
            tokens = r.hypotheses[0]
            if tokens and tokens[0] == self._tgt_tok:
                tokens = tokens[1:]
            value = self._tok.decode(tokens)
            if return_scores:
                score = r.scores[0] / max(len(tokens), 1)
                out.append((value, score))
            else:
                out.append(value)
        return out
