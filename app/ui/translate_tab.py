# -*- coding: utf-8 -*-
"""Вкладка «Перевод файлов»: TranslateTab-оркестратор.

Бывший монолит (2608 строк) разрезан на app/ui/translate/*:
helpers (чистые группировка/фильтр), workers (фоновые QThread),
table (виджеты таблицы), dialogs (диалог перевода/диффы),
glossary_ui (глоссарий). Здесь только TranslateTab + реэкспорты
для совместимости импортов (main_window, tests)."""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication,
                               QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from app.core.models import TranslationEntry
from app.core.translate.service import Translator
from app.ui.i18n import TR, engine_hint
from app.ui.icons import icon
from app.ui.theme import (C_GROUP_BORDER, C_PILL_EMPTY_FG, C_TEXT,
                          C_TEXT_SECONDARY, AnimatedComboBox, AnimatedMenu)

from app.ui.translate.dialogs import _TranslateDialog
from app.ui.translate.glossary_ui import GlossaryDialog
from app.ui.translate.helpers import (extract_busy, filter_entries_by_src_lang,
                                      group_entries_by_src_lang,
                                      project_lang_options, translate_busy)
from app.ui.translate.table import (COL_CTX, COL_IDX, COL_ORIG, COL_STATUS,
                                    COL_TRANS, STATE_EMPTY, STATE_SKIP,
                                    _STATE_LABEL, _STATE_TO_STATUS, _Donut,
                                    _FileItem, _StatusDelegate, _TransDelegate,
                                    _ctx_short, _entry_matches,
                                    _file_is_target_lang, _fmt, _state_of,
                                    _step_icon)
# ExtractWorker здесь не используется, но реэкспортируется для
# main_window (ленивый импорт). Убирать нельзя.
from app.ui.translate.workers import (ExtractWorker,  # noqa: F401
                                      TranslateWorker)


# ────────────────────────────────────────────────────────
#  Main translate tab
# ────────────────────────────────────────────────────────
class TranslateTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.worker: TranslateWorker | None = None
        self._loading = False
        self._cancelling = False
        self._cancel_elapsed = 0
        self._cancel_timer: QTimer | None = None
        self._status_timer: QTimer | None = None
        self._last_progress = (0, 0)
        self._pending_overwrite = False
        self._pending_src_langs: set | None = None
        self._left_over = 0
        # пользователь нажал «Перевести» во время фонового прогона:
        # его выбор ждёт остановки текущего (см. translate_all)
        self._queued_request = False
        self._selected_file = ""
        self._file_items: list[_FileItem] = []
        self._toast_timer: QTimer | None = None
        self._mem_cache: dict[int, list[dict]] = {}
        # Индекс id -> запись: ручная правка шла линейным сканом
        # по 40k строк на каждое нажатие Enter. Источник валидности —
        # сам список проекта (см. _entry_by_id).
        self._entry_index: dict[int, TranslationEntry] = {}
        self._entry_index_src: list | None = None
        # Дебаунс автосейва: раньше каждая правка синхронно писала
        # весь .ob.json на диск. Теперь правим в памяти сразу,
        # на диск — пачкой через 800 мс тишины.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._flush_save)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── top toolbar: степпер + действия (обычные кнопки) ──
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 8, 10, 8)
        bar.setSpacing(8)

        self.btn_extract = QPushButton(TR("tr_extract"))
        self.btn_extract.setProperty("step", True)
        self.btn_extract.setIcon(_step_icon(1))
        self.btn_extract.setIconSize(QSize(16, 16))
        self.btn_extract.setCursor(Qt.PointingHandCursor)
        self.btn_extract.clicked.connect(self.extract_text)
        bar.addWidget(self.btn_extract)

        self.btn_translate = QPushButton(TR("tr_translate"))
        self.btn_translate.setProperty("step", True)
        self.btn_translate.setIcon(_step_icon(2))
        self.btn_translate.setIconSize(QSize(16, 16))
        self.btn_translate.setCursor(Qt.PointingHandCursor)
        self.btn_translate.clicked.connect(self._translate_with_options)
        bar.addWidget(self.btn_translate)

        self.btn_apply = QPushButton(TR("tr_apply"))
        self.btn_apply.setProperty("step", True)
        self.btn_apply.setIcon(_step_icon(3))
        self.btn_apply.setIconSize(QSize(16, 16))
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        self.btn_apply.clicked.connect(self.apply_to_game)
        bar.addWidget(self.btn_apply)

        self.btn_restore = QPushButton(TR("tr_restore"))
        self.btn_restore.setObjectName("tool_btn")
        self.btn_restore.setIcon(icon("arrows-clockwise", 14, C_TEXT_SECONDARY))
        self.btn_restore.setCursor(Qt.PointingHandCursor)
        self.btn_restore.clicked.connect(self.restore_original)
        bar.addWidget(self.btn_restore)

        self.btn_glossary = QPushButton(TR("tr_glossary"))
        self.btn_glossary.setObjectName("tool_btn")
        self.btn_glossary.setIcon(icon("list-bullets", 14, C_TEXT_SECONDARY))
        self.btn_glossary.clicked.connect(self.edit_glossary)
        bar.addWidget(self.btn_glossary)

        bar.addStretch(1)

        self.btn_export = QPushButton(TR("tr_export"))
        self.btn_export.setObjectName("tool_btn")
        self.btn_export.setIcon(icon("download", 14, C_TEXT_SECONDARY))
        self.btn_export.clicked.connect(self.export_csv)
        bar.addWidget(self.btn_export)

        self.btn_import = QPushButton(TR("tr_import"))
        self.btn_import.setObjectName("tool_btn")
        self.btn_import.setIcon(icon("upload", 14, C_TEXT_SECONDARY))
        self.btn_import.clicked.connect(self.import_csv)
        bar.addWidget(self.btn_import)

        self.btn_cancel = QPushButton(TR("tr_cancel"))
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_translate)
        bar.addWidget(self.btn_cancel)
        root.addLayout(bar)

        # ── splitter: file list | entries ──
        splitter = QSplitter(Qt.Horizontal)

        # left: sidebar
        left = QWidget()
        left.setFixedWidth(403)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(6, 10, 8, 0)
        left_lay.setSpacing(8)

        self.file_search = QLineEdit()
        self.file_search.setObjectName("file_search")
        self.file_search.setPlaceholderText(TR("tr_files_search_ph"))
        self.file_search.addAction(
            icon("search", 14, C_PILL_EMPTY_FG),
            QLineEdit.ActionPosition.LeadingPosition)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._apply_search)
        self.file_search.textChanged.connect(self._on_search_text)
        left_lay.addWidget(self.file_search)

        sum_row = QHBoxLayout()
        sum_row.setSpacing(8)
        h1 = QLabel(TR("tr_files").upper())
        h1.setStyleSheet(
            f"color: {C_PILL_EMPTY_FG}; background: transparent;"
            "font-size: 10.5px; font-weight: 700;")
        sum_row.addWidget(h1)
        sum_row.addStretch(1)
        self.lbl_files_sum = QLabel("")
        self.lbl_files_sum.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; background: transparent;"
            "font-size: 11.5px; font-weight: 600;")
        sum_row.addWidget(self.lbl_files_sum)
        left_lay.addLayout(sum_row)

        self._file_scroll = QScrollArea()
        self._file_scroll.setWidgetResizable(True)
        self._file_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._file_list_inner = QWidget()
        self._file_list_lay = QVBoxLayout(self._file_list_inner)
        self._file_list_lay.setContentsMargins(0, 0, 0, 0)
        self._file_list_lay.setSpacing(2)
        self._file_list_lay.addStretch()
        self._file_scroll.setWidget(self._file_list_inner)
        left_lay.addWidget(self._file_scroll, 1)

        foot = QFrame()
        foot.setStyleSheet(
            f"background: transparent; border-top: 1px solid {C_GROUP_BORDER};")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(14, 12, 14, 12)
        fl.setSpacing(10)
        self.donut = _Donut()
        fl.addWidget(self.donut)
        ft = QVBoxLayout()
        ft.setSpacing(1)
        self.lbl_donut_n = QLabel("0 / 0")
        self.lbl_donut_n.setStyleSheet(
            f"color: {C_TEXT}; background: transparent; font-weight: 700;"
            "font-size: 12.5px;")
        ft.addWidget(self.lbl_donut_n)
        self.lbl_donut_l = QLabel("")
        self.lbl_donut_l.setStyleSheet(
            f"color: {C_PILL_EMPTY_FG}; background: transparent;"
            "font-size: 10.5px;")
        ft.addWidget(self.lbl_donut_l)
        fl.addLayout(ft)
        fl.addStretch(1)
        left_lay.addWidget(foot)
        splitter.addWidget(left)

        # right: header + stacked table/cards
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        hdr = QHBoxLayout()
        hdr.setContentsMargins(14, 10, 14, 10)
        hdr.setSpacing(10)
        self._crumb_holder = QHBoxLayout()
        self._crumb_holder.setSpacing(6)
        hdr.addLayout(self._crumb_holder, 1)
        self.view_filter = AnimatedComboBox()
        self.view_filter.setObjectName("chip_filter")
        self.view_filter.addItems([
            TR("tr_mode_new"), TR("tr_filter_all_lines"),
            TR("tr_filter_untranslated"), TR("tr_filter_drafts"),
            TR("tr_filter_finished"), TR("tr_filter_skipped")])
        self.view_filter.currentIndexChanged.connect(self.fill_table)
        hdr.addWidget(self.view_filter)
        right_lay.addLayout(hdr)

        # ── панель глоссария: совпадения для выбранной строки ──
        self.gloss_bar = QWidget()
        self.gloss_bar.setVisible(False)
        self.gloss_bar_lay = QHBoxLayout(self.gloss_bar)
        gb = self.gloss_bar_lay
        gb.setContentsMargins(14, 2, 14, 2)
        gb.setSpacing(6)
        self.gloss_title = QLabel(TR("tr_gloss_bar"))
        self.gloss_title.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 11px;")
        gb.addWidget(self.gloss_title)
        gb.addStretch(1)
        right_lay.addWidget(self.gloss_bar)

        # ── панель памяти: похожие переводы для выбранной строки ──
        self.mem_bar = QWidget()
        self.mem_bar.setVisible(False)
        self.mem_bar_lay = QHBoxLayout(self.mem_bar)
        mb = self.mem_bar_lay
        mb.setContentsMargins(14, 2, 14, 2)
        mb.setSpacing(6)
        self.mem_title = QLabel(TR("tr_memory_title"))
        self.mem_title.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 11px;")
        mb.addWidget(self.mem_title)
        mb.addStretch(1)
        right_lay.addWidget(self.mem_bar)

        self.stack = QStackedWidget()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            TR("tr_col_idx"), TR("tr_col_context"), TR("tr_col_original"),
            TR("tr_col_translation"), TR("tr_col_status")])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.table.setColumnWidth(COL_IDX, 33)
        self.table.setColumnWidth(COL_CTX, 180)
        self.table.setColumnWidth(COL_ORIG, 343)
        self.table.setColumnWidth(COL_TRANS, 340)
        self.table.setColumnWidth(COL_STATUS, 82)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.currentCellChanged.connect(self._glossary_bar_update)
        self.table.currentCellChanged.connect(self._memory_bar_update)
        self._copy_shortcut = QShortcut(
            QKeySequence.StandardKey.Copy, self.table,
            activated=self._copy_cell)
        self._trans_delegate = _TransDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_TRANS, self._trans_delegate)
        self._status_delegate = _StatusDelegate(self.table)
        self._status_delegate.set_meta_lookup(self._meta_for)
        self._status_delegate.cycled.connect(self._cycle_status)
        self.table.setItemDelegateForColumn(
            COL_STATUS, self._status_delegate)
        self.stack.addWidget(self.table)

        right_lay.addWidget(self.stack, 1)
        splitter.addWidget(right)
        splitter.setSizes([403, 977])
        root.addWidget(splitter, 1)

        # ── bottom bar: прогресс перевода + статус ──
        bottom = QHBoxLayout()
        bottom.setContentsMargins(12, 4, 12, 8)
        bottom.setSpacing(8)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        # Текст ошибки можно выделить мышью и скопировать (Ctrl+C) —
        # иначе пользователи присылают фото вместо текста.
        self.lbl_status.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.lbl_status.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; background: transparent;")
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.lbl_status, 2)
        root.addLayout(bottom)

        # ── toast «Сохранено» ──
        self.toast = QLabel(TR("tr_saved"))
        self.toast.setStyleSheet(
            f"background: #1e2230; border: 1px solid {C_GROUP_BORDER};"
            f"border-radius: 12px; color: {C_TEXT_SECONDARY};"
            "padding: 6px 14px; font-size: 11px;")
        self.toast.hide()
        self.toast.setParent(self)

        self._refresh_crumbs()
        self._update_steps()

    # ── helpers ──

    def _project(self):
        return self.main.project

    def _meta_for(self, entry_id: int) -> tuple[int, str]:
        """Статус-пилюля для строки таблицы: (state, label)."""
        p = self._project()
        if p:
            for e in p.entries:
                if e.id == entry_id:
                    state = _state_of(e)
                    return state, TR(_STATE_LABEL[state])
        return STATE_EMPTY, TR("tr_status_empty")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.toast.isVisible():
            self._place_toast()

    def _place_toast(self):
        self.toast.adjustSize()
        self.toast.move((self.width() - self.toast.width()) // 2,
                        self.height() - 64)

    def _flash_saved(self, text: str | None = None):
        self.toast.setText(text or TR("tr_saved"))
        self.toast.show()
        self.toast.raise_()
        self._place_toast()
        if self._toast_timer:
            self._toast_timer.stop()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)
        self._toast_timer.start(1000)

    # ── индекс записей + дебаунс сейва ──

    def _entry_by_id(self, entry_id: int) -> TranslationEntry | None:
        """Запись по id за O(1). Индекс ленивый: перестраивается,
        когда список проекта сменился (extract) или вырос."""
        p = self._project()
        if not p:
            return None
        entries = p.entries
        if self._entry_index_src is not entries \
                or len(self._entry_index) != len(entries):
            self._entry_index = {e.id: e for e in entries}
            self._entry_index_src = entries
        return self._entry_index.get(entry_id)

    def _schedule_save(self):
        """Отложенная запись проекта (см. _flush_save)."""
        if self._project() is None:
            return
        if not self._save_timer.isActive():
            self._save_timer.start()

    def _flush_save(self):
        """Немедленно записать отложенное. Тост — только после
        реальной записи, иначе «Сохранено» врёт."""
        self._save_timer.stop()
        if self._project() is None:
            return
        try:
            self.main.save_project()
        except Exception:  # noqa: BLE001
            return
        self._flash_saved()

    def flush_save(self):
        """Публичный форс сейва: смена проекта, extract, выход."""
        self._flush_save()

    # ── шаги (степпер) ──

    def _update_steps(self):
        p = self._project()
        n = len(p.entries) if p else 0
        translated = sum(1 for e in p.entries if (e.translation or "").strip()) \
            if p else 0
        busy = bool(self.worker and self.worker.isRunning())
        extract_busy = bool(getattr(self.main, "_extract_worker", None)
                            and self.main._extract_worker.isRunning())
        self.btn_extract.setEnabled(
            bool(p) and bool(self.main.engine_module) and not extract_busy)
        self.btn_translate.setEnabled(n > 0 and not busy)
        self.btn_apply.setEnabled(translated > 0)

        if busy:
            active = 2
        elif n == 0:
            active = 1
        elif translated == 0:
            active = 2
        else:
            active = 3
        for btn, num in ((self.btn_extract, 1), (self.btn_translate, 2),
                         (self.btn_apply, 3)):
            on = num == active
            btn.setProperty("active", on)
            btn.setIcon(_step_icon(num, on))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ── extract ──

    def extract_text(self):
        p = self._project()
        if not p:
            QMessageBox.information(self, TR("err"), TR("tr_no_project"))
            return
        if not self.main.engine_module:
            QMessageBox.warning(self, TR("err"), TR("tr_no_engine"))
            return
        if translate_busy(self):  # иначе воркер мутирует orphan-объекты
            QMessageBox.warning(self, TR("err"), TR("tr_translating"))
            return
        self.flush_save()
        self.btn_extract.setEnabled(False)
        self.lbl_status.setText(TR("tr_extracting"))
        if not self.main.start_extraction(self._on_extracted):
            # воркер не стартовал (гонка с другим извлечением) —
            # _on_extracted не придёт, кнопку разблокируем сами.
            self.btn_extract.setEnabled(True)

    def _on_extracted(self, restored: int, error: str):
        self.btn_extract.setEnabled(True)
        if error:
            self.lbl_status.setText(error)
            # Дублируем в диалог: из QMessageBox текст копируется
            # выделением и Ctrl+C, из статус-строки фото не нужны.
            QMessageBox.critical(self, TR("err"), error)
            return
        p = self._project()
        self.main.refresh_all()
        extra = ""
        try:
            mod = getattr(self.main, "engine_module", None)
            if getattr(mod, "key", "") == "unity":
                from app.core.unity import parser as _uparser
                st = getattr(_uparser, "LAST_STATS", None) or {}
                if st.get("typetree", "ok") != "ok":
                    extra = "\n" + TR("tr_unity_typetree",
                                      status=st.get("typetree", "?"))
        except Exception:  # noqa: BLE001 — диагностика не роняет диалог
            extra = ""
        QMessageBox.information(
            self, TR("done"),
            TR("tr_extract_done", count=len(p.entries), restored=restored)
            + extra)

    # ── file list (left panel) ──

    def _on_search_text(self, text: str):
        if not text.strip():
            self._search_timer.stop()
            self._apply_search()
        else:
            self._search_timer.start()

    def _apply_search(self):
        self._rebuild_file_list()
        self.fill_table()

    def _rebuild_file_list(self):
        for item in self._file_items:
            item.setParent(None)
            item.deleteLater()
        self._file_items.clear()

        p = self._project()
        if not p or not p.entries:
            self._update_stats()
            return

        by_file: dict[str, list[TranslationEntry]] = {}
        for e in p.entries:
            by_file.setdefault(e.file, []).append(e)

        q = self.file_search.text().strip().lower()

        # «Все файлы» — агрегат, всегда виден
        all_total = len(p.entries)
        all_done = sum(1 for e in p.entries
                            if (e.translation or "").strip()
                            and e.status != "skip")
        all_item = _FileItem(TR("tr_all_files"), all_total, all_done,
                             all_item=True)
        all_item.clicked.connect(lambda _: self._select_file(""))
        self._file_list_lay.insertWidget(0, all_item)
        self._file_items.append(all_item)

        # файлы на целевом языке (не требуют перевода) — в конец списка
        tgt = p.target_lang
        groups = {"": [], "tl": []}
        for fname in sorted(by_file):
            if q:
                if q in fname.lower():
                    pass  # имя файла совпало
                elif not any(_entry_matches(q, e) for e in by_file[fname]):
                    continue  # ни имя, ни строки не совпали
            fe = by_file[fname]
            groups["tl" if _file_is_target_lang(fe, tgt) else ""].append(
                (fname, fe))
        for key in ("", "tl"):
            for fname, fe in groups[key]:
                total = len(fe)
                done = sum(1 for e in fe
                                if (e.translation or "").strip()
                            and e.status != "skip")
                item = _FileItem(fname, total, done,
                                 target_lang=(key == "tl"))
                item.clicked.connect(
                    lambda _, f=fname: self._select_file(f))
                self._file_list_lay.insertWidget(len(self._file_items), item)
                self._file_items.append(item)

        self._highlight_file()
        self._update_stats()

    def _select_file(self, fname: str):
        self._selected_file = fname
        self._highlight_file()
        self._refresh_crumbs()
        self.fill_table()

    def _highlight_file(self):
        for item in self._file_items:
            is_all = (item.fname == TR("tr_all_files"))
            active = (is_all and not self._selected_file) \
                or (item.fname == self._selected_file)
            item.set_active(active)

    # ── хлебные крошки ──

    def _refresh_crumbs(self):
        while self._crumb_holder.count():
            item = self._crumb_holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._selected_file:
            lbl = QLabel(TR("tr_all_files"))
            lbl.setStyleSheet(
                f"color: {C_TEXT}; background: transparent; font-weight: 600;"
                "font-size: 12.5px;")
            self._crumb_holder.addWidget(lbl)
            return
        parts = [x for x in self._selected_file.replace("\\", "/")
                 .split("/") if x]
        for i, seg in enumerate(parts):
            is_last = i == len(parts) - 1
            lbl = QLabel(seg)
            lbl.setStyleSheet((
                f"color: {C_TEXT}; background: transparent; font-weight: 600;"
                if is_last else
                f"color: {C_TEXT_SECONDARY}; background: transparent;")
                + "font-family: 'Cascadia Code', 'Consolas', monospace;"
                  "font-size: 12.5px;")
            lbl.setToolTip(self._selected_file)
            self._crumb_holder.addWidget(lbl)
            if not is_last:
                spl = QLabel("/")
                spl.setStyleSheet(
                    f"color: {C_PILL_EMPTY_FG}; background: transparent;")
                self._crumb_holder.addWidget(spl)

    # ── фильтр ──

    def _filtered(self) -> list[TranslationEntry]:
        p = self._project()
        if not p:
            return []
        mode = self.view_filter.currentIndex()
        q = self.file_search.text().strip().lower()
        out = []
        for e in p.entries:
            if self._selected_file and e.file != self._selected_file:
                continue
            if q and not _entry_matches(q, e):
                continue
            has = bool(e.translation.strip())
            done = has and e.status in ("translated", "corrected")
            draft = has and not done and e.status != "skip"
            # текстовый поиск перекрывает фильтр статуса:
            # ищем по всем строкам, а не только по «новым»
            if not q and mode == 0 and (has or e.status == "skip"):
                continue
            if not q and mode == 2 and has:
                continue
            if not q and mode == 3 and not draft:
                continue
            if not q and mode == 4 and not done:
                continue
            if not q and mode == 5 and e.status != "skip":
                continue
            out.append(e)
        return out

    # ── entries table / cards ──

    def fill_table(self):
        p = self._project()
        if p is None:
            return
        try:
            # новый проект/фильтр — старые подсказки памяти невалидны
            self._mem_cache.clear()
        except Exception:  # noqa: BLE001
            pass
        self._loading = True
        try:
            rows = self._filtered()
            capped = len(rows) > 10000
            if capped:
                rows = rows[:10000]
            self.table.setUpdatesEnabled(False)
            self.table.setRowCount(len(rows))
            for r, e in enumerate(rows):
                items = [
                    QTableWidgetItem(str(r + 1)),
                    QTableWidgetItem(_ctx_short(e.context)),
                    QTableWidgetItem(e.original),
                    QTableWidgetItem(e.translation),
                    QTableWidgetItem(""),
                ]
                items[COL_CTX].setToolTip(e.context)
                for c, it in enumerate(items):
                    if c != COL_TRANS:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    it.setData(Qt.UserRole, e.id)
                    self.table.setItem(r, c, it)
            self.table.setUpdatesEnabled(True)
            note = TR("tr_status_cap") if capped else ""
            self.lbl_status.setText(
                TR("tr_status", shown=len(rows),
                   total=len(p.entries), note=note))
        finally:
            self._loading = False
        self._update_steps()

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != COL_TRANS:
            return
        if not self._project():
            return
        entry_id = item.data(Qt.UserRole)
        e = self._entry_by_id(entry_id)
        if e is None:
            return
        e.translation = item.text()
        e.status = "manual"
        # На диск — дебаунсом: синхронная запись всего .ob.json
        # на каждую правку замораживала UI на больших проектах.
        self._schedule_save()
        self._update_stats()
        self._update_steps()
        self.table.viewport().update()

    # ── копирование текста из таблицы ──

    def _row_texts(self, row: int) -> tuple[str, str]:
        """(оригинал, перевод) для строки таблицы."""
        orig = self.table.item(row, COL_ORIG)
        trans = self.table.item(row, COL_TRANS)
        return (orig.text() if orig else "",
                trans.text() if trans else "")

    # ── глоссарий: совпадения для выбранной строки ──

    def _glossary_bar_update(self, row: int = -1, col: int = -1,
                             *args):
        """Показывает совпадения глоссария для выбранной строки."""
        self.gloss_title.show()
        bar = self.gloss_bar_lay
        while bar.count() > 2:  # title + stretch
            item = bar.takeAt(1)
            w = item.widget()
            if w:
                w.deleteLater()
        if row < 0:
            row = self.table.currentRow()
        if row < 0 or not self._project():
            self.gloss_bar.setVisible(False)
            return
        item = self.table.item(row, COL_ORIG)
        if not item:
            self.gloss_bar.setVisible(False)
            return
        orig = item.text()
        g = self.main.glossary
        if g is None:
            self.gloss_bar.setVisible(False)
            return
        src = self.main.settings.value("source_lang", "auto")
        src = "ja" if src == "auto" else src
        tgt = self.main.settings.value("target_lang", "ru")
        terms = g.terms(src, tgt)
        found = {t: v for t, v in terms.items()
                 if t and t in orig}
        if not found:
            self.gloss_bar.setVisible(False)
            return
        for t in sorted(found, key=len, reverse=True):
            chip = QPushButton(
                f"「{t}」 → {found[t]}")
            chip.setObjectName("chip_filter")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(
                lambda checked=False, tt=t, tv=found[t]:
                    self._glossary_apply(tt, tv))
            chip.setToolTip(TR("tr_gloss_chip_tip"))
            bar.insertWidget(bar.count() - 1, chip)
        self.gloss_bar.setVisible(True)

    def _glossary_apply(self, term: str, tr: str):
        """Вставляет перевод термина в ячейку перевода строки."""
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, COL_TRANS)
        if not item:
            return
        cur = item.text()
        new = (cur + " " + tr).strip() if cur else tr
        self.table.setCurrentCell(row, COL_TRANS)
        item.setText(new)
        self._on_item_changed(item)

    # ── память: похожие переводы для выбранной строки ──

    @staticmethod
    def _mem_short(text: str, limit: int = 40) -> str:
        t = " ".join((text or "").split())
        return t if len(t) <= limit else t[:limit - 1] + "…"

    def _memory_bar_update(self, row: int = -1, col: int = -1, *args):
        """Секция «Похожие из памяти» для выбранной строки.

        suggest_all быстрый (LIMIT 200 + difflib в памяти), вызывается
        прямо из GUI; результат кэшируется по entry id. Битая tm2
        панель просто прячет.
        """
        try:
            self.mem_title.show()
            bar = self.mem_bar_lay
            while bar.count() > 2:  # title + stretch
                item = bar.takeAt(1)
                w = item.widget()
                if w:
                    w.deleteLater()
            if row < 0:
                row = self.table.currentRow()
            if row < 0 or not self._project():
                self.mem_bar.setVisible(False)
                return
            orig_item = self.table.item(row, COL_ORIG)
            trans_item = self.table.item(row, COL_TRANS)
            if not orig_item:
                self.mem_bar.setVisible(False)
                return
            orig = orig_item.text()
            if not (orig or "").strip():
                self.mem_bar.setVisible(False)
                return
            entry_id = orig_item.data(Qt.UserRole)
            p = self._project()
            src = getattr(p, "source_lang", None) \
                or self.main.settings.value("source_lang", "auto")
            tgt = getattr(p, "target_lang", None) \
                or self.main.settings.value("target_lang", "ru")
            tm = getattr(self.main, "tm", None)
            if tm is None:
                self.mem_bar.setVisible(False)
                return
            # точный язык источника (auto -> detect), иначе suggest_all
            # по ключу 'auto' ничего не найдёт
            try:
                from app.core.translate.service import _resolve_src
                lang = _resolve_src(orig, src, tgt)
            except Exception:  # noqa: BLE001
                lang = None
            if not lang:
                # строка уже на целевом языке — подсказки не нужны
                self.mem_bar.setVisible(False)
                return
            try:
                cached = self._mem_cache.get(entry_id)
            except Exception:  # noqa: BLE001
                cached = None
            if cached is None:
                try:
                    sug = tm.suggest_all(orig, lang, tgt, limit=3)
                except Exception:  # noqa: BLE001 — битая tm2
                    self.mem_bar.setVisible(False)
                    return
                try:
                    self._mem_cache[entry_id] = sug
                except Exception:  # noqa: BLE001
                    pass
            else:
                sug = cached
            if not sug:
                self.mem_bar.setVisible(False)
                return
            cur_trans = trans_item.text().strip() if trans_item else ""
            shown = 0
            for s in sug[:3]:
                try:
                    target = s.get("target", "")
                    source = s.get("source", "")
                    score = float(s.get("score", 0.0))
                except Exception:  # noqa: BLE001
                    continue
                if not (target or "").strip():
                    continue
                if cur_trans and target.strip() == cur_trans and score >= 0.999:
                    continue  # точное уже стоит в ячейке
                pct = int(round(score * 100))
                lbl = QLabel(
                    f"{self._mem_short(source)} → "
                    f"{self._mem_short(target)} ({pct}%)")
                lbl.setStyleSheet(
                    f"color: {C_TEXT_SECONDARY}; font-size: 11px; "
                    "background: transparent;")
                lbl.setToolTip(source)
                bar.insertWidget(bar.count() - 1, lbl)
                btn = QPushButton(TR("tr_memory_take"))
                btn.setObjectName("chip_filter")
                btn.setCursor(Qt.PointingHandCursor)
                btn.setToolTip(TR("tr_memory_tip"))
                btn.clicked.connect(
                    lambda checked=False, tt=target, ss=score:
                        self._memory_apply(tt, ss))
                bar.insertWidget(bar.count() - 1, btn)
                shown += 1
            self.mem_bar.setVisible(shown > 0)
        except Exception:  # noqa: BLE001 — панель памяти никогда не роняет GUI
            try:
                self.mem_bar.setVisible(False)
            except Exception:  # noqa: BLE001
                pass

    def _memory_apply(self, target: str, score: float = 0.0):
        """Кнопка «Взять»: подставить перевод из памяти."""
        try:
            row = self.table.currentRow()
            if row < 0:
                return
            item = self.table.item(row, COL_TRANS)
            orig_item = self.table.item(row, COL_ORIG)
            if not item or not orig_item:
                return
            entry_id = orig_item.data(Qt.UserRole)
            p = self._project()
            if not p:
                return
            e = next((x for x in p.entries if x.id == entry_id), None)
            if e is None:
                return
            e.translation = target
            e.status = "translated" if score >= 0.999 else "manual"
            try:
                self.main.save_project()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._mem_cache.pop(entry_id, None)
            except Exception:  # noqa: BLE001
                pass
            self.fill_table()
            self._update_stats()
        except Exception:  # noqa: BLE001
            pass

    def _copy_text(self, text: str):
        if text:
            QApplication.clipboard().setText(text)

    def _copy_cell(self):
        item = self.table.currentItem()
        if item:
            self._copy_text(item.text())

    def _table_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        row = index.row()
        orig, trans = self._row_texts(row)
        menu = AnimatedMenu(self.table)
        act_orig = menu.addAction(TR("tr_copy_original"))
        act_orig.setEnabled(bool(orig))
        act_trans = menu.addAction(TR("tr_copy_translation"))
        act_trans.setEnabled(bool(trans))
        menu.addSeparator()
        act_row = menu.addAction(TR("tr_copy_row"))
        act_row.setEnabled(bool(orig) or bool(trans))
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is act_orig:
            self._copy_text(orig)
        elif chosen is act_trans:
            self._copy_text(trans)
        elif chosen is act_row:
            self._copy_text(f"{orig}\n\n{trans}" if trans else orig)

    # ── статус-пилюля: клик циклически меняет статус ──

    def _cycle_status(self, entry_id: int):
        if not self._project():
            return
        e = self._entry_by_id(entry_id)
        if not e:
            return
        state = _state_of(e)
        if state == STATE_SKIP:
            next_state = STATE_EMPTY
        else:
            next_state = (state + 1) % 3
        e.status = _STATE_TO_STATUS[next_state]
        self._schedule_save()
        self.table.viewport().update()
        self._update_stats()

    # ── сводки (сайдбар + статус-бар) ──

    def _project_stats(self) -> tuple[int, int, int, int]:
        p = self._project()
        if not p:
            return 0, 0, 0, 0
        done = draft = empty = 0
        for e in p.entries:
            if (e.translation or "").strip():
                if e.status == "skip":
                    draft += 1
                else:
                    done += 1
            else:
                empty += 1
        return done, draft, empty, len(p.entries)

    def _update_stats(self):
        p = self._project()
        done, _, _, total = self._project_stats()
        # файловые подсчёты
        by_file: dict[str, list[TranslationEntry]] = {}
        for e in (p.entries if p else []):
            by_file.setdefault(e.file, []).append(e)
        for item in self._file_items:
            is_all = item.fname == TR("tr_all_files")
            fe = list(p.entries) if (is_all and p) else by_file.get(item.fname)
            if fe is None:
                continue
            done_f = sum(1 for e in fe
                         if (e.translation or "").strip()
                         and e.status != "skip")
            item.update_counts(done_f, len(fe))
        # донут
        if total:
            pct = round(done / total * 100)
            self.donut.set_value(done / total)
        else:
            pct = 0
            self.donut.set_value(0)
        self.lbl_donut_n.setText(f"{_fmt(done)} / {_fmt(total)}")
        self.lbl_donut_l.setText(TR("tr_donut_caption", pct=pct))
        # сводка «Файлы · N завершено»
        n_files = len(by_file)
        done_files = sum(
            1 for fe in by_file.values()
            if fe and all((e.translation or "").strip()
                          and e.status != "skip"
                          for e in fe))
        self.lbl_files_sum.setText(
            "" if not p else TR("tr_files_summary",
                                files=n_files, done=done_files))
        # глобальный статус-бар
        self.main.refresh_project_stats()

    # ── translate ──

    def _lang_options(self) -> list[str]:
        return project_lang_options(self.main.engine_module, self._project())

    def _on_lang_extracted_then_translate(self, restored: int, error: str):
        self.btn_extract.setEnabled(True)
        if error:
            self.lbl_status.setText(error)
            return
        self.main.refresh_all()
        self.translate_all()

    def _translate_with_options(self):
        """Клик по «Перевести»: диалог — язык перевода (весь текст или
        один официальный) и режим (только непереведённое / всё заново),
        затем перевод."""
        p = self._project()
        if not p or not p.entries:
            QMessageBox.information(self, TR("err"), TR("tr_no_data"))
            return
        dlg = _TranslateDialog(self._lang_options(), p.extract_lang, self,
                                 group_entries_by_src_lang(p.entries))
        if not dlg.exec():
            return
        lang = dlg.lang()
        self._pending_overwrite = dlg.overwrite()
        self._pending_src_langs = dlg.selected_src_langs()
        prev = p.extract_lang
        p.extract_lang = lang
        p.lang_asked = True
        self.main.save_project()
        if prev != lang:
            self.btn_extract.setEnabled(False)
            self.lbl_status.setText(TR("tr_extracting"))
            self.main.start_extraction(self._on_lang_extracted_then_translate)
            return
        self.translate_all()

    def notify_pending_resume(self, pending: int):
        """Показать предложение дотянуть незаконченный перевод.

        Только строка статуса — БЕЗ старта воркера и БЕЗ оверлея:
        человек мог открыть игру ради читов, и молчаливый старт
        «перевожу» на весь экран — это баг с точки зрения пользователя.
        Продолжение — кнопка «Перевести», игнор — ничего не происходит.
        """
        self.lbl_status.setText(TR("tr_resume_offer", n=int(pending)))
        self._flash_saved(TR("tr_resume_offer", n=int(pending)))

    def translate_all(self):
        p = self._project()
        if not p or not p.entries:
            QMessageBox.information(self, TR("err"), TR("tr_no_data"))
            return
        if extract_busy(self):  # иначе воркер мутирует orphan-объекты
            QMessageBox.warning(self, TR("err"), TR("tr_extracting"))
            return
        if self.worker and self.worker.isRunning():
            # Явное действие важнее: прерываем текущий прогон и ставим
            # запрос в очередь — он выполнится сразу после остановки.
            self._queued_request = True
            self.cancel_translate()
            return
        engine = self.main.create_engine("files")
        if engine is None:
            QMessageBox.critical(self, TR("err"),
                                 TR("tr_engine_create_fail"))
            return
        s = self.main.settings
        # ping() — в воркере (в GUI морозил окно); текст ошибки — здесь.
        engine_name = getattr(engine, "name", "rotate")
        ping_hint = engine_hint(engine_name)
        translator = Translator(engine, tm=self.main.tm,
                                glossary=self.main.glossary)
        # Только выбранные в диалоге языки оригинала (остальные строки
        # остаются как есть — не жжём запросы). P0: воркеру — копию
        # списка (list), а не живой p.entries.
        src_langs = getattr(self, "_pending_src_langs", None)
        targets = filter_entries_by_src_lang(p.entries, src_langs)
        # Помечаем прогон как начавшийся: если приложение закроют (или
        # провайдеры сядут) посередине, tr_pending останется > 0 и
        # при следующем открытии предложим дотянуть (без автостарта).
        if p is not None and hasattr(p, "tr_pending"):
            p.tr_pending = len(targets)
            self.main.save_project()
        self.worker = TranslateWorker(
            translator, list(targets),
            s.value("source_lang", "auto"), s.value("target_lang", "ru"),
            overwrite=self._pending_overwrite, prefill=True,
            ping_hint=ping_hint)
        self.worker.progressed.connect(self._on_progress)
        self.worker.left.connect(self._on_left_over)
        self.worker.status.connect(self.lbl_status.setText)
        self.worker.status.connect(self.main.loading.set_text)
        self.worker.done.connect(self._on_translated)
        self.worker.failed.connect(self._on_translate_failed)
        self._cancelling = False
        self._last_progress = (0, 0)
        self._left_over = 0
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self.btn_translate.setEnabled(False)
        self.main.loading.show_loading(TR("tr_translating"), TR("tr_cancel"),
                                       self.cancel_translate)
        self.worker.start()

    def _on_left_over(self, n: int):
        """Сколько строк не осилил ни один провайдер. Показываем честно:
        они остались не переведёнными и повторятся при следующем запуске."""
        self._left_over = int(n or 0)
        if self._left_over:
            self.lbl_status.setText(
                TR("tr_waiting_providers").format(n=self._left_over))

    def cancel_translate(self):
        """Мягкая отмена: флаги остановки + ожидание фонового завершения
        через таймер (GUI не блокируется, полоса/текст доигрывают плавно)."""
        self._cancelling = True
        self._cancel_elapsed = 0
        w = self.worker
        if w is not None:
            translator = getattr(w, "translator", None)
            if translator is not None:
                translator.cancel()
            w.requestInterruption()
        self.btn_cancel.setEnabled(False)
        self.main.loading.set_text(TR("tr_cancelling"))
        busy = self.worker and self.worker.isRunning()
        if not busy:
            self._finish_cancelled()
            return
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self._poll_cancel)
        self._cancel_timer.start(120)

    def _poll_cancel(self):
        """Опрос завершения фонового потока после отмены.

        Никакого terminate(): движок теперь сам выходит по флагу отмены
        (проверки перед каждым сетевым запросом/ожиданием), поток
        завершается штатно. terminate() убивал QThread посреди C-кода
        (requests/SSL/sqlite) и ронял весь процесс — переведённое
        пропадало без сохранения.
        """
        self._cancel_elapsed += 120
        busy = self.worker and self.worker.isRunning()
        if busy:
            self._cancel_timer.start(120)
            return
        self._finish_cancelled()

    def _finish_cancelled(self):
        done, total = self._last_progress
        self._finish_translate(TR("tr_cancelled", done=done, total=total))
        # Отменил пользователь — авто-возобновление не должно потом
        # начинать то же самое без спроса.
        p = self._project()
        if p is not None and hasattr(p, "tr_pending"):
            p.tr_pending = 0
        self.main.save_project()
        self._rebuild_file_list()
        self.fill_table()
        self.main.refresh_project_stats()

    def _on_progress(self, done, total):
        self._last_progress = (done, total)
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)
        text = TR("tr_progress", done=done, total=total)
        self.lbl_status.setText(text)
        self.main.loading.set_text(text)
        # автосейв во время долгого перевода: при краше процесса
        # переведённая часть остаётся в проекте
        now = time.monotonic()
        if now - getattr(self, "_last_autosave", 0.0) >= 10.0:
            self._last_autosave = now
            try:
                self.main.save_project()
            except Exception:  # noqa: BLE001 — сейв не должен ломать перевод
                pass

    def _on_translated(self, n, skipped=0):
        if self._cancelling:
            return
        self._finish_translate()
        # что осталось не довести — по этому числу авто-возобновление
        # поймёт, что прошлый прогон не дошёл до конца
        p = self._project()
        if p is not None and hasattr(p, "tr_pending"):
            p.tr_pending = int(self._left_over or 0)
        self.main.save_project()
        self._rebuild_file_list()
        self.fill_table()
        skipped_note = TR("tr_translate_done_skipped", skipped=skipped) \
            if skipped else ""
        left_note = ""
        if self._left_over:
            # честно говорим, что часть строк не осилил ни один провайдер:
            # они остались не переведёнными, а не «готовыми»
            left_note = "\n\n" + TR("tr_left_over").format(n=self._left_over)
        QMessageBox.information(
            self, TR("done"),
            TR("tr_translate_done", n=n, skipped=skipped,
               skipped_note=skipped_note) + left_note)

    def _on_translate_failed(self, msg):
        if self._cancelling:
            return
        self._finish_translate()
        # Прогон завершён ошибкой — дотягивать нечего: без сброса
        # tr_pending следующее открытие проекта молча стартовало бы
        # перевод заново без нажатия кнопки.
        p = self._project()
        if p is not None and hasattr(p, "tr_pending"):
            p.tr_pending = 0
        self.main.save_project()
        self._rebuild_file_list()
        self.fill_table()
        QMessageBox.critical(self, TR("err"), msg)

    def _finish_translate(self, status_text: str = ""):
        self.main.loading.hide_loading()
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setEnabled(False)
        # P0: без wait() в слоте GUI — done/failed уже означают конец run(),
        # поток либо завершён, либо завершится сам; удаляем без блокировки.
        _w = self.worker
        self.worker = None
        if _w is not None:
            try:
                if _w.isRunning():
                    _w.requestInterruption()
                    _w.finished.connect(_w.deleteLater)
                else:
                    _w.deleteLater()
            except RuntimeError:
                pass
        if self._cancel_timer:
            self._cancel_timer.stop()
            self._cancel_timer = None
        if status_text:
            self.lbl_status.setText(status_text)
            self.progress.setVisible(True)
            self.progress.setMaximum(max(max(self._last_progress[1], 1),
                                         self.progress.value()))
            self.progress.setValue(self._last_progress[0])
            if self._status_timer:
                self._status_timer.stop()
            self._status_timer = QTimer(self)
            self._status_timer.setSingleShot(True)
            self._status_timer.timeout.connect(
                lambda: self.progress.setVisible(False))
            self._status_timer.start(4000)
        self._cancelling = False
        self._update_steps()
        # Пользователь нажал «Перевести» во время фонового прогона —
        # выполняем его выбор с выбранным режимом (см. translate_all).
        if self._queued_request:
            self._queued_request = False
            QTimer.singleShot(0, self.translate_all)

    # ── glossary ──

    def edit_glossary(self):
        GlossaryDialog(self.main.glossary, self.main.settings,
                       self).exec()

    # ── export / import ──

    def export_csv(self):
        p = self._project()
        if not p or not p.entries:
            return
        import csv
        path, _ = QFileDialog.getSaveFileName(
            self, TR("tr_export"), "translation.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["id", "file", "json_path", "context",
                        "original", "translation", "status"])
            for e in p.entries:
                w.writerow([e.id, e.file, e.json_path, e.context,
                            e.original, e.translation, e.status])
        QMessageBox.information(self, TR("done"), f"Exported: {path}")

    def import_csv(self):
        p = self._project()
        if not p or not p.entries:
            return
        import csv
        path, _ = QFileDialog.getOpenFileName(
            self, TR("tr_import"), "", "CSV (*.csv)")
        if not path:
            return
        by_id = {e.id: e for e in p.entries}
        updated = 0
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f, delimiter=";"):
                try:
                    e = by_id.get(int(row["id"]))
                except (ValueError, KeyError, TypeError):
                    continue
                # Короткая строка CSV даёт None вместо "" — гард обязателен.
                tr = row.get("translation") or ""
                if e and tr.strip():
                    e.translation = tr
                    e.status = "manual"
                    updated += 1
        self.main.save_project()
        self._rebuild_file_list()
        self.fill_table()
        QMessageBox.information(self, TR("done"), f"Updated: {updated}")

    # ── apply ──

    def apply_to_game(self):
        p = self._project()
        if not p or not p.entries:
            return
        translated = sum(1 for e in p.entries if (e.translation or "").strip())
        module = self.main.engine_module
        if not module:
            return
        if QMessageBox.question(
                self, TR("tr_apply_title"),
                TR("tr_apply_msg", n=translated)) != QMessageBox.Yes:
            return
        stats = module.apply(
            p.game_dir, p.entries,
            target_lang=self.main.settings.value("target_lang", "ru"))
        if stats.get("verify_failed"):
            msg = TR("tr_verify_failed",
                     problems="\n".join(stats["verify_failed"][:8]))
            if stats.get("verify_restored"):
                msg += "\n" + TR("tr_verify_restored")
            if stats.get("verify_remaining"):
                msg += "\n" + TR("tr_verify_broken",
                                 remaining="\n".join(stats["verify_remaining"][:8]))
            QMessageBox.critical(self, TR("err"), msg)
            self._update_steps()
            return
        parts = [TR("tr_apply_done", files=stats["files"],
                     strings=stats["strings"])]
        if stats.get("backups"):
            parts.append(TR("tr_apply_backup", n=len(stats["backups"])))
        if stats.get("out_file"):
            parts.append(TR("tr_apply_newfile", path=stats["out_file"]))
        if stats.get("out_dir"):
            parts.append(TR("tr_apply_folder", path=stats["out_dir"]))
        if stats.get("removed_orphans"):
            parts.append(TR("tr_apply_orphans", n=stats["removed_orphans"]))
        if stats.get("skipped_total"):
            details = ", ".join(
                f"{k}×{v}" for k, v in (stats.get("skipped_by") or {}).items())
            parts.append(TR("tr_apply_skipped", n=stats["skipped_total"],
                            details=details or "—"))
        if stats.get("long_lines_total"):
            parts.append(TR(
                "tr_apply_longlines", n=stats["long_lines_total"],
                problems="\n".join((stats.get("long_lines") or [])[:8])))
        # гибрид: если игра запущена — внедряем перевод live-хуком (MV/MZ),
        # это покрывает и зашифрованные/asar-сборки
        ch = self.main.channel()
        if ch is not None and hasattr(ch, "apply_translation"):
            try:
                pushed = ch.apply_translation(p.entries)
            except Exception:  # noqa: BLE001
                pushed = False
            if pushed:
                parts.append(TR("tr_apply_live"))
        QMessageBox.information(self, TR("done"), "\n".join(parts))
        self._update_steps()

    def restore_original(self):
        p = self._project()
        module = self.main.engine_module
        if not p or not module or not hasattr(module, "restore_original"):
            return
        if QMessageBox.question(
                self, TR("tr_restore_title"),
                TR("tr_restore_msg")) != QMessageBox.Yes:
            return
        try:
            stats = module.restore_original(p.game_dir)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, TR("err"), str(exc))
            return
        QMessageBox.information(
            self, TR("done"),
            TR("tr_restore_done", n=stats.get("restored", 0)))
        self._update_steps()

# ── конец TranslateTab: диалоги/воркеры/таблица/глоссарий живут в
#    app/ui/translate/* и импортируются в шапке файла ──