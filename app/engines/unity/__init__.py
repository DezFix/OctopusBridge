# -*- coding: utf-8 -*-
"""Модуль Unity (Mono) — детект, извлечение и внедрение.

Текст лежит в .assets/.bundle/.resource/level* (TextAsset, MonoBehaviour,
TextMesh/GUIText, TextMeshProUGUI/TextMeshPro) + текстовые файлы
StreamingAssets — парсинг через UnityPy (см. app/core/unity/parser.py,
ленивый импорт; без UnityPy extract -> [], apply -> no-unitypy).
IL2CPP вне скоупа (признанное ограничение). Читов нет (нативного канала
к процессу Unity нет, вкладка только translate); шрифт — замена m_FontData
классических Font через font_patch() (TMP SDF — только детект: нужен Editor).
"""
from __future__ import annotations

from app.engines.base import EngineModule


class UnityModule(EngineModule):
    key = "unity"
    title = "Unity"
    variant = ""
    maturity = "experimental"  # файловый перевод Mono работает, читов нет
    # Конвенция базы (app/engines/base.py): только 'cheats', 'resources',
    # 'font', 'files'.
    # 'cheats' намеренно НЕТ: в базе этот флаг гейтит автозапуск игры при
    # открытии проекта (app/ui/main_window.py), а живой канал Unity
    # поднимается по запросу — когда пользователь сам нажал «Запустить».
    # Сам канал есть (см. app/transport/unity_rpc), просто не автоматический.
    features = {"files", "font"}

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
        """Замена m_FontData классических Font на TTF с кириллицей.

        Делегирует parser.font_patch (BackupStore + atomic + verify);
        TMP SDF не трогаем (нужен Unity Editor) — их счётчик в stats.
        """
        from app.core.unity import parser
        return parser.font_patch(
            game_dir or self.game_dir,
            ttf_path=kwargs.get("ttf_path"),
            backup=kwargs.get("backup", True),
            backup_root=kwargs.get("backup_root"))

    def restore_original(self, game_dir: str) -> dict:
        """Откат перевода: вернуть бэкапы BackupStore (backup/unity)."""
        from app.core.io import BackupStore
        import os
        store = BackupStore(os.path.join(game_dir, "backup", "unity"))
        return store.restore_all()

    def file_view(self, game_dir: str):
        from app.core.rpgmaker.fileview import DiskFileView
        return DiskFileView(game_dir)
