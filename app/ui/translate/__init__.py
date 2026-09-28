# -*- coding: utf-8 -*-
"""Вкладка перевода, разрезанная на модули (модульный монолит).

Бывший монолит app/ui/translate_tab.py (2608 строк): TranslateTab +
воркеры + диалоги + делегаты + глоссарий в одном файле. Теперь:

- helpers.py — чистые группировка/фильтр по языку (без Qt);
- workers.py — фоновые QThread (извлечение/перевод);
- table.py — виджеты таблицы (донат, items, делегаты, пилюли);
- dialogs.py — диалог перевода;
- glossary_ui.py — диалоги глоссария (ручное ведение, без LLM);
- app/ui/translate_tab.py — только TranslateTab-оркестратор
  (+ реэкспорты для совместимости импортов).

Правило: app/core и app/engines НЕ импортируют этот пакет.
"""
from __future__ import annotations

from app.ui.translate.dialogs import _TranslateDialog
from app.ui.translate.glossary_ui import GlossaryDialog, _TermEditDialog
from app.ui.translate.helpers import (filter_entries_by_src_lang,
                                      group_entries_by_src_lang)
from app.ui.translate.table import (COL_CTX, COL_IDX, COL_ORIG, COL_STATUS,
                                    COL_TRANS, STATE_DONE, STATE_DRAFT,
                                    STATE_EMPTY, STATE_SKIP, _STATE_LABEL,
                                    _STATE_TO_STATUS, _Donut, _FileItem,
                                    _StatusDelegate, _TransDelegate,
                                    _TransEditor, _ctx_short, _entry_matches,
                                    _file_is_target_lang, _fmt, _pill_colors,
                                    _state_of, _step_icon)
from app.ui.translate.workers import ExtractWorker, TranslateWorker

__all__ = [
    "GlossaryDialog",
    "ExtractWorker",
    "TranslateWorker",
    "filter_entries_by_src_lang",
    "group_entries_by_src_lang",
    "COL_CTX",
    "COL_IDX",
    "COL_ORIG",
    "COL_STATUS",
    "COL_TRANS",
    "STATE_DONE",
    "STATE_DRAFT",
    "STATE_EMPTY",
    "STATE_SKIP",
    "_STATE_LABEL",
    "_STATE_TO_STATUS",
    "_Donut",
    "_FileItem",
    "_StatusDelegate",
    "_TermEditDialog",
    "_TransDelegate",
    "_TransEditor",
    "_TranslateDialog",
    "_ctx_short",
    "_entry_matches",
    "_file_is_target_lang",
    "_fmt",
    "_pill_colors",
    "_state_of",
    "_step_icon",
]
