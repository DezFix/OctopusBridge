# -*- coding: utf-8 -*-
"""Модуль Unity (Mono/IL2CPP) — детект, извлечение и внедрение.

Текст лежит в .assets/.bundle/.resource (TextAsset, MonoBehaviour,
TextMesh/GUIText) — парсинг через UnityPy (см. app/core/unity/parser.py,
ленивый импорт; без UnityPy extract -> [], apply -> no-unitypy).
Читов нет (нативного канала к процессу Unity нет, вкладка только
translate); шрифт — будущий font-patch (заглушка font_patch()).
"""
from __future__ import annotations

from app.engines.base import EngineModule
from app.ui.i18n import TR


class UnityModule(EngineModule):
    key = "unity"
    title = "Unity"
    variant = ""
    features = {"file-translation", "font-patch"}

    @classmethod
    def detect(cls, game_dir: str) -> int:
        from app.core.unity import parser
        return parser.detect(game_dir)

    def __init__(self, game_dir: str):
        self.game_dir = game_dir

    @property
    def display(self) -> str:
        return "Unity"

    def extract(self, game_dir: str) -> list:
        from app.core.unity import parser
        if parser._try_import_unitypy() is None:
            raise RuntimeError(
                "UnityPy отсутствует в сборке — извлечение Unity "
                "невозможно. Переустановите приложение.")
        stats: dict = {}
        entries = parser.extract(game_dir, stats)
        if not entries:
            tail = ""
            if stats.get("parse_err"):
                tail = (f" Разбор: не удалось {stats.get('parse_fail', '?')}, "
                        f"{stats['parse_err']}.")
            raise RuntimeError(
                "Текстов не найдено "
                f"(файлов: {stats.get('candidates', '?')}, "
                f"открыто: {stats.get('loaded', '?')}, "
                f"ошибок: {stats.get('load_failed', '?')}, "
                f"объектов: {stats.get('objects', '?')}, "
                f"текстовых: {stats.get('text_objects', '?')}, "
                f"typetree: {stats.get('typetree', '?')}).{tail} "
                "Пришлите эти цифры разработчику.")
        return entries

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        from app.core.unity import parser
        # target_lang приходит из проекта (Project.target_lang через UI),
        # по умолчанию — 'ru' (контракт как у WolfModule).
        return parser.apply(game_dir, entries,
                            target_lang=kwargs.get("target_lang", "ru"))

    def font_patch(self, game_dir: str = "", **kwargs) -> dict:
        """Заглушка замены шрифта (Font x2 в resources/sharedassets0).

        Реальный патч TMP/Unity-Font — TODO; пока честно отвечаем,
        что ничего не сделано, чтобы UI не врал о «готово».
        """
        _ = (game_dir, kwargs)
        return {"patched": False, "reason": "todo"}

    def restore_original(self, game_dir: str) -> dict:
        """Откат перевода: вернуть бэкапы BackupStore (backup/unity)."""
        from app.core.io import BackupStore
        import os
        store = BackupStore(os.path.join(game_dir, "backup", "unity"))
        return store.restore_all()

    def file_view(self, game_dir: str):
        from app.core.rpgmaker.fileview import DiskFileView
        return DiskFileView(game_dir)

    def ui_tabs(self, main_window) -> list[tuple]:
        translate = main_window.translate_tab
        return [
            (translate, TR("tab_translate"), "translate"),
        ]
