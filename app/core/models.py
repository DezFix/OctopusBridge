# -*- coding: utf-8 -*-
"""Общие модели данных: TranslationEntry, Project.

Используются всеми модулями движков (RPG Maker, Ren'Py, Twine)
и сервисом перевода. Ранее жили в rpgmaker/models.py — вынесены
сюда, чтобы ядро не зависело от конкретного движка.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, asdict


def project_file_for(game_dir: str, projects_root: str | None = None) -> str:
    """Путь .ob.json проекта для папки игры (общий с UI).

    Имя детерминированное: <базовое имя, очищенное>_<md5 пути>.
    projects_root — переопределение каталога проектов (тесты).
    """
    from app import projects_dir
    root = projects_root or projects_dir()
    name = hashlib.md5(os.path.abspath(game_dir).encode()).hexdigest()[:12]
    base = os.path.basename(os.path.normpath(game_dir)) or "game"
    safe = "".join(c if c.isalnum() else "_" for c in base)[:40]
    return os.path.join(root, f"{safe}_{name}.ob.json")


@dataclass
class TranslationEntry:
    """Одна извлечённая строка текста игры."""
    id: int
    file: str            # относительный путь, напр. data/Map001.json
    json_path: str       # путь внутри JSON / внутренний ключ
    context: str         # человекочитаемый контекст
    original: str
    translation: str = ""
    status: str = "new"  # new | translated | manual | corrected | skip

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "TranslationEntry":
        return TranslationEntry(**d)


@dataclass
class Project:
    """Профиль проекта перевода (хранится отдельно от файлов игры)."""
    game_dir: str
    engine: str = "mz"           # mz | mv
    source_lang: str = "auto"   # код языка: auto | ja | zh | ko | en | ...
    target_lang: str = "ru"      # код языка: ru | en | uk | de | ...
    entries: list[TranslationEntry] = field(default_factory=list)
    var_names: dict[str, str] = field(default_factory=dict)
    switch_names: dict[str, str] = field(default_factory=dict)
    extract_lang: str | None = None  # Ren'Py: какой tl/<lang> извлекать (None = все)
    lang_asked: bool = False  # пользователь уже выбрал язык перевода для проекта

    def to_dict(self) -> dict:
        return {
            "game_dir": self.game_dir,
            "engine": self.engine,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "entries": [e.to_dict() for e in self.entries],
            "var_names": self.var_names,
            "switch_names": self.switch_names,
            "extract_lang": self.extract_lang,
            "lang_asked": self.lang_asked,
        }

    @staticmethod
    def from_dict(d: dict) -> "Project":
        p = Project(
            game_dir=d["game_dir"],
            engine=d.get("engine", "mz"),
            source_lang=d.get("source_lang", "auto"),
            target_lang=d.get("target_lang", "ru"),
        )
        p.entries = [TranslationEntry.from_dict(e) for e in d.get("entries", [])]
        p.var_names = d.get("var_names", {})
        p.switch_names = d.get("switch_names", {})
        p.extract_lang = d.get("extract_lang")
        p.lang_asked = bool(d.get("lang_asked", False))
        return p
