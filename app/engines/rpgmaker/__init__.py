# -*- coding: utf-8 -*-
"""Модуль RPG Maker MV/MZ — извлечение, внедрение, живое подключение.

Один модуль на обе формы игры:
- обычная: data/*.json, img/, js/ лежат прямо в папке игры;
- Electron: всё упаковано в resources/app.asar — файлы читаются лениво
  через AsarFileView, переводы пишутся в архив «на месте» (пересборка
  только если файл вырос), вкладки карт/ресурсов/читов работают по тем же
  относительным путям.

Весь функционал RPG Maker хранится в этой папке:
- parser: извлечение/внедрение текста в data/*.json
- asar: детект Electron-игр (resources/app.asar)
- crypto: расшифровка ресурсов
- fontpatch: замена шрифта на кириллический
- varnames: имена переменных/переключателей
- maprender: данные для карт
- textwrap: подгонка текста под рамки диалогов
- tentacle: CDP-подключение к живой игре
"""
from __future__ import annotations

import os
from datetime import datetime

from app.core.rpgmaker.fileview import AsarFileView, DiskFileView, FileView
from app.engines.base import EngineModule
from app.ui.i18n import TR

_FEATURES = {"files", "live", "cheats", "resources", "maps"}
_FEATURES_FONT = {"files", "live", "cheats", "resources", "font", "maps"}


class RpgMakerModule(EngineModule):
    key = "rpgmaker"
    title = "RPG Maker"

    @property
    def features(self) -> set[str]:
        # замена шрифта (js/rmmz_core + fonts внутри архива) — только для
        # обычных игр; у Electron-версии кнопка скрыта
        return _FEATURES if self._asar else _FEATURES_FONT

    @classmethod
    def detect(cls, game_dir: str) -> int:
        from . import asar
        from . import parser
        variant = asar.detect_variant(game_dir)
        if variant:
            return {"mz": 110, "mv": 100}.get(variant, 0)
        engine = parser.detect_engine(game_dir)
        if engine == "mz":
            return 100
        if engine == "mv":
            return 90
        return 0

    def __init__(self, game_dir: str):
        from . import asar
        from . import parser
        self._asar = bool(asar.detect_variant(game_dir))
        self.variant = (asar.detect_variant(game_dir)
                        if self._asar else parser.detect_engine(game_dir))
        self._views: dict[str, FileView] = {}

    @property
    def display(self) -> str:
        suffix = " (Electron)" if self._asar else ""
        return f"RPG Maker {self.variant.upper()}{suffix}"

    def file_view(self, game_dir: str) -> FileView:
        """Файловый доступ для вкладок: диск или ленивый asar.

        View кэшируется на время сессии: AsarFileView перечитывает заголовок
        архива при каждом создании, а это может быть несколько мегабайт JSON.
        """
        view = self._views.get(game_dir)
        if view is None:
            if self._asar:
                from . import asar as asarlib
                view = AsarFileView(
                    asarlib.asar_path(game_dir),
                    backup_dir=os.path.join(game_dir, "backup", "maps"))
            else:
                view = DiskFileView(game_dir)
            self._views[game_dir] = view
        return view

    def extract(self, game_dir: str) -> list:
        from . import parser
        if self._asar:
            return self._extract_asar(game_dir)
        return parser.extract(game_dir)

    def _extract_asar(self, game_dir: str) -> list:
        from .asar import _temp_project
        from . import parser
        with _temp_project(game_dir) as proj:
            return parser.extract(proj)

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        if self._asar:
            return self._apply_asar(game_dir, entries, **kwargs)
        from . import parser
        return parser.apply(game_dir, entries,
                            target_lang=kwargs.get("target_lang", "ru"))

    def _apply_asar(self, game_dir: str, entries: list, **kwargs) -> dict:
        """Переводит data/*.json во временном проекте и правит asar."""
        from .asar import _temp_project
        from . import asar as asarlib
        from . import parser
        from app.core import asar as asarcore
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = os.path.join(game_dir, "backup", ts)
        with _temp_project(game_dir) as proj:
            stats = parser.apply(
                proj, entries,
                backup_root=backup_root,
                target_lang=kwargs.get("target_lang", "ru"))
            # какие файлы реально изменились — только их и правим в архиве
            ar = asarcore.AsarArchive(asarlib.asar_path(game_dir))
            patches: dict[str, bytes] = {}
            for root, _dirs, files in os.walk(os.path.join(proj, "data")):
                for fn in files:
                    rel = os.path.relpath(os.path.join(root, fn), proj) \
                        .replace(os.sep, "/")
                    with open(os.path.join(root, fn), "rb") as f:
                        blob = f.read()
                    old = ar.read_file(f"{asarlib.PROJECT_PREFIX}/{rel}")
                    if old is not None and blob != old:
                        patches[f"{asarlib.PROJECT_PREFIX}/{rel}"] = blob
        if patches:
            astats = asarcore.apply_patches(
                asarlib.asar_path(game_dir), patches, backup_dir=backup_root)
            stats["files"] = astats["files"]
            stats["backups"] = stats.get("backups", []) + astats["backups"]
            if astats["repacked"]:
                stats["repacked"] = True
        return stats

    def ui_tabs(self, main_window) -> list[tuple]:
        from app.ui.cheat_tab import CheatTab
        from app.ui.map_tab import MapTab
        from app.ui.resource_tab import ResourceTab
        translate = main_window.translate_tab
        cheats = CheatTab(main_window)
        maps = MapTab(main_window)
        resources = ResourceTab(main_window)
        main_window.cheat_tab = cheats
        return [
            (translate, TR("tab_translate"), "translate"),
            (cheats, TR("tab_cheats"), "cheats"),
            (maps, TR("tab_maps"), "module"),
            (resources, TR("tab_resources"), "module"),
        ]
