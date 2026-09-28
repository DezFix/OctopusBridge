# -*- coding: utf-8 -*-
"""Протокол движков — чистая граница модульного монолита.

Правила:
- Этот файл НЕ импортирует Qt, app.ui, тентакли, сеть.
  Только stdlib + dataclasses. Нарушение ловит tests/test_boundaries.py.
- Каждый движок игр (rpgmaker, renpy, tyrano, twine, wolf, unity, ajin)
  реализует extract/apply/verify как ЧИСТЫЕ функции над файлами:
  диск -> диск, без GUI, без потоков, без CDP/Frida.
- UI и live-сессии (CDP/Frida/HTTP) живут СНАРУЖИ и общаются
  с движком только через этот протокол.

Схема:
    detect(game_dir) -> вес (0 = не наш движок)
    extract(game_dir) -> list[TranslationEntry]
    apply(game_dir, entries) -> ApplyReport (файлы НЕ ломают запуск)
    verify(game_dir) -> list[str] (пусто = игра стартует)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ApplyReport:
    """Итог apply. Движок обязан вернуть, UI обязан показать."""

    files: int = 0
    strings: int = 0
    # overlay-режим (оригиналы целы, перевод рядом/live)
    runtime: bool = False
    # пропуски с причинами: {"resources": 12, "changed": 3, ...}
    skipped_total: int = 0
    skipped_by: dict[str, int] = field(default_factory=dict)
    # страховка запуска (см. rpgmaker/verify.py как эталон)
    verify_failed: list[str] = field(default_factory=list)
    verify_restored: bool = True
    backups: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "files": self.files,
            "strings": self.strings,
            "runtime": self.runtime,
            "skipped_total": self.skipped_total,
            "skipped_by": dict(self.skipped_by),
            "verify_failed": list(self.verify_failed),
            "verify_restored": self.verify_restored,
            "backups": list(self.backups),
        }

    @staticmethod
    def from_legacy(stats: dict | None) -> "ApplyReport":
        s = stats or {}
        return ApplyReport(
            files=int(s.get("files", 0) or 0),
            strings=int(s.get("strings", 0) or 0),
            runtime=bool(s.get("runtime", False)),
            skipped_total=int(s.get("skipped_total", 0) or 0),
            skipped_by=dict(s.get("skipped_by", {}) or {}),
            verify_failed=list(s.get("verify_failed", []) or []),
            verify_restored=bool(s.get("verify_restored", True)),
            backups=list(s.get("backups", []) or []),
        )


class EngineParser(ABC):
    """Чистый парсер движка. Без Qt, без UI, без live."""

    key: str = "base"
    title: str = "Базовый движок"
    variant: str = ""
    features: set[str] = {"files"}
    # Зрелость движка (фокус проекта — RPG-семья):
    # - "stable" — RPG Maker MV/MZ: полный цикл + verify, чинить в первую очередь;
    # - "experimental" — Wolf: файловый перевод работает, читов нет;
    # - "frozen" — остальные: код и тесты живут, но только критические
    #   фиксы (краш/потеря данных). Новых фич нет, пока не станет
    #   железным stable-ядро. Заморозку снимает только явное решение.
    maturity: str = "experimental"

    @classmethod
    @abstractmethod
    def detect(cls, game_dir: str) -> int:
        """Вес совпадения: 0 — не наш движок, больше — увереннее."""

    @abstractmethod
    def extract(self, game_dir: str) -> list:
        """Извлечь переводимые строки -> list[TranslationEntry]."""

    @abstractmethod
    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        """Внедрить переводы. Вернуть статистику (dict, см. ApplyReport).

        Инвариант: после apply игра обязана запускаться.
        Лучше пропустить строку, чем убить игру.
        """

    def verify(self, game_dir: str) -> list[str]:
        """Проверить, что игра стартует после apply. Пусто = ок."""
        return []

    def restore_original(self, game_dir: str) -> dict:
        """Откатить все изменения движка. Вернуть статистику."""
        return {"restored": 0}
