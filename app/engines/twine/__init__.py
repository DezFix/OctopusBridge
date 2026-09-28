# -*- coding: utf-8 -*-
"""Модуль Twine (HTML5) — извлечение, внедрение, подключение, сейвы.

Функционал Twine:
- parser: извлечение/внедрение текста из/в .html
- savefile: чтение/запись SugarCube .save (LZ-String)
- tentacle: подключение к живой игре (Chromium-браузеры)
"""
from __future__ import annotations

import os

from app.engines.base import EngineModule


class TwineModule(EngineModule):
    key = "twine"
    title = "Twine"
    features = {"files", "cheats"}
    maturity = "frozen"  # фокус — RPG-семья; только критические фиксы

    @classmethod
    def detect(cls, game_dir: str) -> int:
        # Если это сам .html файл — проверяем сразу
        if os.path.isfile(game_dir) and game_dir.lower().endswith(".html"):
            try:
                with open(game_dir, encoding="utf-8", errors="ignore") as fh:
                    if "<tw-storydata" in fh.read(1024 * 1024):
                        return 60
            except OSError:
                pass
            return 0
        # Ищем .html с <tw-storydata в папке
        try:
            entries = os.listdir(game_dir)
        except OSError:
            return 0
        for f in entries:
            if not f.endswith(".html"):
                continue
            try:
                with open(os.path.join(game_dir, f), encoding="utf-8",
                          errors="ignore") as fh:
                    head = fh.read(1024 * 1024)
                    if "<tw-storydata" in head:
                        return 60
            except OSError:
                continue
        return 0

    def __init__(self, game_dir: str):
        self.game_path: str | None = None
        # Если game_dir — файл .html, запоминаем его
        if os.path.isfile(game_dir) and game_dir.lower().endswith(".html"):
            self.game_path = game_dir

    @property
    def display(self) -> str:
        return "Twine"

    def extract(self, game_dir: str) -> list:
        from app.core.twine import parser
        entries = parser.extract(game_dir)
        # JSON-промежуток: рядом с игрой появляется «игра.json» —
        # структурированный текст пассажей (см. parser.story_to_json),
        # его удобно читать/править отдельно, не трогая html.
        try:
            parser.write_story_json(game_dir)
        except OSError:
            pass
        return entries

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        from app.core.twine import parser
        # Перевод пишется в НОВУЮ html-копию «имя_<язык>.html» рядом
        # с игрой (parser.apply target_lang=...): оригинал не трогается
        # и остаётся бэкапом.
        return parser.apply(game_dir, entries,
                            target_lang=kwargs.get("target_lang"))

    def restore_original(self, game_dir: str) -> dict:
        from app.core.twine import parser
        return parser.restore_original(game_dir)
