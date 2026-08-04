from __future__ import annotations

import json
from pathlib import Path

import ctranslate2

from .tokenizer import Tokenizer

_COMPUTE_CANDIDATES = ("int8_float16", "int8", "float16", "float32")


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


class Engine:
    def __init__(
        self,
        model_dir: Path,
        source_spm: Path,
        target_spm: Path | None = None,
        device: str = "cpu",
        threads: int | None = None,
        use_vmap: bool = False,
        max_length: int = 512,
    ):
        self._tok = Tokenizer(str(source_spm), str(target_spm) if target_spm else None)
        self._ct = _resolve_translator(model_dir, device, threads)
        self._max_length = max_length
        self._vmap = _check_vmap(self._ct, self._tok.encode("test")) if use_vmap else False

    def translate(self, texts: list[str], beam_size: int = 1) -> list[str]:
        if not texts:
            return []
        kwargs: dict = {
            "beam_size": beam_size,
            "max_decoding_length": self._max_length,
            "repetition_penalty": 1.5,
            "no_repeat_ngram_size": 3,
        }
        if self._vmap:
            kwargs["use_vmap"] = True
        results = self._ct.translate_batch([self._tok.encode(t) for t in texts], **kwargs)
        return [self._tok.decode(r.hypotheses[0]) for r in results]


class NLLBEngine:
    def __init__(
        self,
        model_dir: Path,
        src_code: str,
        tgt_code: str,
        device: str = "cpu",
        threads: int | None = None,
        use_vmap: bool = False,
        max_length: int = 1024,
    ):
        self._tok = Tokenizer(str(model_dir / "sentencepiece.bpe.model"))
        self._ct = _resolve_translator(model_dir, device, threads)
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

    def translate(self, texts: list[str], beam_size: int = 1) -> list[str]:
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
        }
        if self._vmap:
            kwargs["use_vmap"] = True
        results = self._ct.translate_batch(sources, **kwargs)
        out = []
        for r in results:
            tokens = r.hypotheses[0]
            if tokens and tokens[0] == self._tgt_tok:
                tokens = tokens[1:]
            out.append(self._tok.decode(tokens))
        return out
