from __future__ import annotations

import sentencepiece as spm


class Tokenizer:
    def __init__(self, source_model: str, target_model: str | None = None):
        self._src = spm.SentencePieceProcessor(model_file=source_model)
        self._tgt = spm.SentencePieceProcessor(model_file=target_model or source_model)

    def encode(self, text: str) -> list[str]:
        return self._src.encode(text, out_type=str)

    def decode(self, tokens: list[str]) -> str:
        return self._tgt.decode(tokens)
