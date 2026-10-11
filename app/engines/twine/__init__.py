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
    features = {"cheats"}
    maturity = "frozen"  # фокус — RPG-семья; только критические фиксы

    @classmethod
    def detect(cls, game_dir: str) -> int:
        # Если это сам .html/.htm файл - проверяем сразу
        if os.path.isfile(game_dir) \
                and game_dir.lower().endswith((".html", ".htm")):
            try:
                with open(game_dir, encoding="utf-8", errors="ignore") as fh:
                    if "<tw-storydata" in fh.read(2 * 1024 * 1024):
                        return 60
            except OSError:
                pass
            return 0
        # Ищем .html/.htm с <tw-storydata в папке и на уровень вглубь
        # (как parser.find_story: .htm, регистр имени, 2 МБ головы)
        try:
            entries = os.listdir(game_dir)
        except OSError:
            return 0
        for f in entries:
            if not f.lower().endswith((".html", ".htm")):
                continue
            path = os.path.join(game_dir, f)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8",
                          errors="ignore") as fh:
                    if "<tw-storydata" in fh.read(2 * 1024 * 1024):
                        return 60
            except OSError:
                continue
        for f in entries:
            sub = os.path.join(game_dir, f)
            if not os.path.isdir(sub):
                continue
            try:
                sub_entries = os.listdir(sub)
            except OSError:
                continue
            for sf in sub_entries:
                if not sf.lower().endswith((".html", ".htm")):
                    continue
                try:
                    with open(os.path.join(sub, sf), encoding="utf-8",
                              errors="ignore") as fh:
                        if "<tw-storydata" in fh.read(2 * 1024 * 1024):
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
        # soft-disable: no index.json side-effect (overlay-only).
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
