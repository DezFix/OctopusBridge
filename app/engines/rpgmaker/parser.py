# -*- coding: utf-8 -*-
"""Парсер RPG Maker MV/MZ (v2 с плагинами) живёт в ядре:
app/core/rpgmaker/parser.py. Этот модуль — тонкая обёртка для обратной
совместимости (движок и старые импорты используют from . import parser)."""
from __future__ import annotations

from app.core.rpgmaker.parser import (  # noqa: F401
    CMD_CHANGE_NAME, CMD_CHANGE_NICK, CMD_CHOICES, CMD_CHOICE_BRANCH,
    CMD_COMMENT, CMD_COMMENT_CONT, CMD_DIALOG, CMD_PLUGIN, CMD_PLUGIN_CONT,
    CMD_PLUGIN_MV, CMD_SCROLL, CMD_SCRIPT, CMD_SCRIPT_CONT, CMD_SHOW_TEXT_HDR,
    DB_FIELDS, SYSTEM_LIST_FIELDS, TERMS_LIST_FIELDS, TranslationEntry,
    annotations, apply, detect_engine, extract, find_data_dir, get_by_path,
    iter_js_strings, js_text_candidate, json, os, parse_path, re,
    restore_original, set_by_path, shutil,
)