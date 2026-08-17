# -*- coding: utf-8 -*-
"""Различия RPG Maker MV и MZ — единая точка правды.

Сюда вынесено всё, что у MV и MZ различается, чтобы код под каждый
вариант выбирался явно, а не угадывался по содержимому:
- детект варианта по файлам движка (диск или FileView);
- где лежит список включённых плагинов (MV: js/plugins.js, JS-скрипт;
  MZ: data/plugins.js, JSON-массив);
- коды плагин-команд событий (MV: 356; MZ: 357/657);
- шифрованные карты (MV: MapXXX.rpgmvm; MZ карты не шифрует).
"""
from __future__ import annotations

import os

from .fileview import DiskFileView

MZ = "mz"
MV = "mv"

# маркеры ядра движка: обычная игра и деплой в www/
CORE_JS_RELS = {
    MZ: ("js/rmmz_core.js", "www/js/rmmz_core.js"),
    MV: ("js/rpg_core.js", "www/js/rpg_core.js"),
}

# проектные файлы редактора (на случай, если js/ вырезан)
PROJECT_FILE_RELS = {
    MZ: ("game.rmmzproject",),
    MV: ("Game.rpgproject",),
}

# где лежит список включённых плагинов. У MV это JS-скрипт
# (var $plugins = [...]) в js/, у MZ — JSON-массив в data/.
# Порядок внутри кортежа — приоритет; чужой путь в конце — страховка
# для нестандартных деплоев.
PLUGINS_LIST_RELS = {
    MZ: ("data/plugins.js", "www/data/plugins.js",
          "js/plugins.js", "www/js/plugins.js"),
    MV: ("js/plugins.js", "www/js/plugins.js",
          "data/plugins.js", "www/data/plugins.js"),
}

# коды плагин-команд в списках команд событий
PLUGIN_COMMANDS = {
    MZ: (357, 657),
    MV: (356,),
}

# шифрованные карты: MV — MapXXX.rpgmvm; MZ карты не шифрует
ENCRYPTED_MAP_SUFFIX = {
    MZ: None,
    MV: ".rpgmvm",
}


def is_mz(variant: str) -> bool:
    return variant == MZ


def is_mv(variant: str) -> bool:
    return variant == MV


def detect_variant(game_dir: str, view=None) -> str:
    """'mz' | 'mv' | 'unknown' по файлам движка (диск или FileView)."""
    view = view or DiskFileView(game_dir)
    for variant, rels in CORE_JS_RELS.items():
        for rel in rels:
            if view.exists(rel):
                return variant
    for variant, rels in PROJECT_FILE_RELS.items():
        for rel in rels:
            if view.exists(rel):
                return variant
    return "unknown"


def plugins_list_rel(variant: str, game_dir: str,
                     data_dir: str = "data") -> str | None:
    """Первый существующий на диске путь к списку плагинов.

    Для неизвестного варианта пробуем оба формата в порядке MV
    (js/plugins.js), затем MZ (data/plugins.js).
    """
    rels = PLUGINS_LIST_RELS.get(variant)
    if not rels:
        rels = []
        for v in (MV, MZ):
            for rel in PLUGINS_LIST_RELS[v]:
                if rel not in rels:
                    rels.append(rel)
    for rel in rels:
        if os.path.isfile(os.path.join(game_dir, rel.replace("/", os.sep))):
            return rel
    return None
