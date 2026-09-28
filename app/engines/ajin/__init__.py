# -*- coding: utf-8 -*-
"""Модуль AjinSyoujyo — Electron-сборка TyranoScript с asar + override.

Детект/извлечение/внедрение — app.core.ajin.parser (слоёный доступ,
запись только в override/). Живая сессия — CDP к Electron
(app.engines.ajin.tentacle): переменные kag.variables / kag.tmp,
поэтому features включает cheats (у базового Tyrano — только files).
"""
from __future__ import annotations

from app.engines.base import EngineModule


class AjinModule(EngineModule):
    key = "ajin"
    title = "AjinSyoujyo (Electron Tyrano)"
    variant = "electron-tyrano"
    features = {"files", "cheats"}
    maturity = "frozen"  # фокус — RPG-семья; только критические фиксы

    @classmethod
    def detect(cls, game_dir: str) -> int:
        from app.core.ajin import parser
        return parser.detect(game_dir)

    def __init__(self, game_dir: str):
        self.game_dir = game_dir

    @property
    def display(self) -> str:
        return "AjinSyoujyo"

    def extract(self, game_dir: str) -> list:
        from app.core.ajin import parser
        return parser.extract(game_dir)

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        from app.core.ajin import parser
        return parser.apply(game_dir, entries,
                            target_lang=kwargs.get("target_lang", "ru"))

    def restore_original(self, game_dir: str) -> dict:
        from app.core.ajin import parser
        return parser.restore_original(game_dir)

    def file_view(self, game_dir: str):
        from app.core.ajin.layered import LayeredView

        view = LayeredView(game_dir)

        class _Adapter:
            """Минимальный адаптер под интерфейс FileView (read-only + walk)."""

            def read_bytes(self, rel: str):
                return view.read_bytes(rel)

            def exists(self, rel: str) -> bool:
                return view.exists(rel)

            def walk(self, rel: str) -> list[str]:
                rel = rel.strip("/")
                if rel in ("data/scenario", "data\\scenario"):
                    return view.list_scenario_files()
                return []

        return _Adapter()
