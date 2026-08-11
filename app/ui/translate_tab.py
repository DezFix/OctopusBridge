# -*- coding: utf-8 -*-
"""Вкладка «Перевод файлов»: левая панель — файлы, правая — записи."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog,
                                QFrame, QHBoxLayout, QHeaderView,
                                QLabel, QLineEdit, QMessageBox,
                                QProgressBar, QPushButton, QSplitter,
                                QTableWidget, QTableWidgetItem,
                                QVBoxLayout, QWidget)

from app.core.models import TranslationEntry
from app.core.translate.service import Translator
from app.ui.i18n import TR, engine_hint
from app.ui.icons import icon
from app.ui.theme import C_CARD, C_PRIMARY, C_TEXT, C_TEXT_SECONDARY, RADIUS_MD

ENTRY_COLS = ["Context", "Original", "Translation", "Status"]

STATUS_ICON = {
    "new": "circle",
    "translated": "check",
    "manual": "pencil",
    "corrected": "star",
    "skip": "dots-h",
}


class ExtractWorker(QThread):
    """Фоновое извлечение текста из игры (не морозит GUI)."""

    done = Signal(object)       # list[TranslationEntry]
    failed = Signal(str)

    def __init__(self, module, game_dir: str):
        super().__init__()
        self.setObjectName("ExtractWorker")
        self._module = module
        self._game_dir = game_dir

    def run(self):
        try:
            entries = self._module.extract(self._game_dir)
            if not self.isInterruptionRequested():
                self.done.emit(entries)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class TranslateWorker(QThread):
    progressed = Signal(int, int)
    done = Signal(int)
    failed = Signal(str)

    def __init__(self, translator: Translator, entries, src, tgt,
                 overwrite=False):
        super().__init__()
        self.setObjectName("TranslateWorker")
        self.translator = translator
        self.entries = entries
        self.src = src
        self.tgt = tgt
        self.overwrite = overwrite

    def run(self):
        try:
            def progress_check(d, t):
                if self.isInterruptionRequested():
                    raise InterruptedError("cancelled")
                self.progressed.emit(d, t)
            n = self.translator.translate_entries(
                self.entries, self.src, self.tgt,
                progress=progress_check,
                overwrite=self.overwrite)
            if not self.isInterruptionRequested():
                self.done.emit(n)
        except InterruptedError:
            pass
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class CorrectWorker(QThread):
    progressed = Signal(int, int)
    corrections_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, corrector, entries, tgt):
        super().__init__()
        self.setObjectName("CorrectWorker")
        self.corrector = corrector
        self.entries = entries
        self.tgt = tgt

    def run(self):
        try:
            def progress_check(d, t):
                if self.isInterruptionRequested():
                    raise InterruptedError("cancelled")
                self.progressed.emit(d, t)
            n = self.corrector.correct_all(self.entries, self.tgt,
                                           progress=progress_check)
            if not self.isInterruptionRequested():
                self.corrections_ready.emit(self.corrector.diffs)
        except InterruptedError:
            pass
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class AnalyzeWorker(QThread):
    """Автоглоссарий: LLM выделяет имена и термины из текстов проекта."""

    done = Signal(object)      # dict[str, str]
    failed = Signal(str)

    def __init__(self, engine, texts, src, tgt):
        super().__init__()
        self.setObjectName("AnalyzeWorker")
        self._engine = engine
        self._texts = texts
        self._src = src
        self._tgt = tgt

    def run(self):
        from app.core.translate.analysis import analyze_terms
        try:
            terms = analyze_terms(self._engine, self._texts,
                                  self._src, self._tgt)
            if not self.isInterruptionRequested():
                self.done.emit(terms)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class DiffReviewDialog(QDialog):
    def __init__(self, diffs: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TR("diff_title"))
        self.resize(850, 520)
        self.diffs = diffs
        lay = QVBoxLayout(self)

        lbl = QLabel(TR("diff_hint", n=len(diffs)))
        lbl.setWordWrap(True)
        lay.addWidget(lbl)

        self.table = QTableWidget(len(diffs), 4)
        self.table.setHorizontalHeaderLabels([
            TR("diff_col_orig"), TR("diff_col_was"),
            TR("diff_col_became"), TR("diff_col_action")])
        for c in range(3):
            self.table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.Stretch)
        self.table.setColumnWidth(3, 100)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        for r, d in enumerate(diffs):
            self.table.setItem(r, 0, QTableWidgetItem(d.entry.original))
            self.table.setItem(r, 1, QTableWidgetItem(d.old_text))
            self.table.setItem(r, 2, QTableWidgetItem(d.new_text))
            btn_a = QPushButton(TR("diff_accept"))
            btn_r = QPushButton(TR("diff_reject"))
            btn_a.setIcon(icon("check"))
            btn_r.setIcon(icon("cross"))
            btn_a.clicked.connect(lambda _, row=r: self._accept(row))
            btn_r.clicked.connect(lambda _, row=r: self._reject(row))
            w = QWidget()
            hb = QHBoxLayout(w)
            hb.setContentsMargins(0, 0, 0, 0)
            hb.addWidget(btn_a)
            hb.addWidget(btn_r)
            self.table.setCellWidget(r, 3, w)
            d.accepted = False

        lay.addWidget(self.table, 1)

        bar = QHBoxLayout()
        ba = QPushButton(TR("diff_accept_all"))
        ba.clicked.connect(self._accept_all)
        br = QPushButton(TR("diff_reject_all"))
        br.clicked.connect(self._reject_all)
        bp = QPushButton(TR("diff_apply"))
        bp.setObjectName("accent")
        bp.clicked.connect(self._apply)
        bar.addWidget(ba)
        bar.addWidget(br)
        bar.addStretch(1)
        bar.addWidget(bp)
        lay.addLayout(bar)

        self.lbl_count = QLabel()
        lay.addWidget(self.lbl_count)
        self._update_count()

    def _accept(self, row):
        self.diffs[row].accepted = True
        self._style(row, True)
        self._update_count()

    def _reject(self, row):
        self.diffs[row].accepted = False
        self._style(row, False)
        self._update_count()

    def _accept_all(self):
        for r in range(len(self.diffs)):
            self.diffs[r].accepted = True
            self._style(r, True)
        self._update_count()

    def _reject_all(self):
        for r in range(len(self.diffs)):
            self.diffs[r].accepted = False
            self._style(r, False)
        self._update_count()

    def _style(self, row, accepted):
        from PySide6.QtGui import QColor
        c = QColor(46, 125, 50, 40) if accepted else QColor(198, 40, 40, 40)
        for col in range(3):
            self.table.item(row, col).setBackground(c)

    def _update_count(self):
        acc = sum(1 for d in self.diffs if d.accepted)
        self.lbl_count.setText(
            TR("diff_count", acc=acc, total=len(self.diffs)))

    def _apply(self):
        self.accept()


# ────────────────────────────────────────────────────────
#  File list item widget (left panel)
# ────────────────────────────────────────────────────────
class _FileItem(QFrame):
    clicked = Signal(str)

    def __init__(self, fname: str, total: int, done: int, parent=None):
        super().__init__(parent)
        self.fname = fname
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(52)
        self.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: none;
                border-bottom: 1px solid #333;
            }}
            QFrame:hover {{
                background: {C_CARD};
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(2)

        top = QHBoxLayout()
        name = QLabel(fname)
        name.setStyleSheet(
            f"color: {C_TEXT}; font-size: 11px; background: transparent;")
        name.setMaximumWidth(200)
        top.addWidget(name, 1)
        pct = round(done / total * 100) if total else 0
        lbl = QLabel(f"{done}/{total} ({pct}%)")
        lbl.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 10px; background: transparent;")
        top.addWidget(lbl)
        lay.addLayout(top)

        bar = QProgressBar()
        bar.setMaximum(total)
        bar.setValue(done)
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background: #333;
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {C_PRIMARY};
                border-radius: 2px;
            }}
        """)
        lay.addWidget(bar)

    def mousePressEvent(self, event):
        self.clicked.emit(self.fname)
        super().mousePressEvent(event)

    def set_active(self, active: bool):
        if active:
            self.setStyleSheet(f"""
                QFrame {{
                    background: {C_CARD};
                    border-left: 3px solid {C_PRIMARY};
                    border-bottom: 1px solid #333;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame {{
                    background: transparent;
                    border: none;
                    border-bottom: 1px solid #333;
                }}
                QFrame:hover {{
                    background: {C_CARD};
                }}
            """)


# ────────────────────────────────────────────────────────
#  Main translate tab
# ────────────────────────────────────────────────────────
class TranslateTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.worker: TranslateWorker | None = None
        self.worker_correct: CorrectWorker | None = None
        self._loading = False
        self._selected_file = ""
        self._file_items: list[_FileItem] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # ── top toolbar ──
        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        self.btn_extract = QPushButton(TR("tr_extract"))
        self.btn_extract.clicked.connect(self.extract_text)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([TR("tr_mode_new"), TR("tr_mode_all")])
        self.btn_translate = QPushButton(TR("tr_translate"))
        self.btn_translate.setObjectName("accent")
        self.btn_translate.clicked.connect(self.translate_all)
        self.btn_cancel = QPushButton(TR("tr_cancel"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_translate)
        self.btn_apply = QPushButton(TR("tr_apply"))
        self.btn_apply.clicked.connect(self.apply_to_game)
        bar.addWidget(self.btn_extract)
        bar.addWidget(self.mode_combo)
        bar.addWidget(self.btn_translate)
        bar.addWidget(self.btn_cancel)
        bar.addWidget(self.btn_apply)
        bar.addStretch(1)
        self.btn_correct = QPushButton(TR("tr_correct"))
        self.btn_correct.clicked.connect(self.correct_all)
        btn_glossary = QPushButton(TR("tr_glossary"))
        btn_glossary.clicked.connect(self.edit_glossary)
        btn_export = QPushButton(TR("tr_export"))
        btn_export.clicked.connect(self.export_csv)
        btn_import = QPushButton(TR("tr_import"))
        btn_import.clicked.connect(self.import_csv)
        bar.addWidget(self.btn_correct)
        bar.addWidget(btn_glossary)
        bar.addWidget(btn_export)
        bar.addWidget(btn_import)
        root.addLayout(bar)

        # ── search + filter bar ──
        filt = QHBoxLayout()
        filt.setContentsMargins(8, 0, 8, 0)
        filt.addWidget(QLabel(TR("tr_search")))
        self.search = QLineEdit()
        self.search.setPlaceholderText(TR("tr_search_ph"))
        self.search.textChanged.connect(self.fill_table)
        filt.addWidget(self.search, 1)
        filt.addWidget(QLabel(TR("tr_filter")))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            TR("tr_filter_all"), TR("tr_filter_untranslated"),
            TR("tr_filter_translated"), TR("tr_filter_skipped"),
        ])
        self.filter_combo.currentIndexChanged.connect(self.fill_table)
        filt.addWidget(self.filter_combo)
        root.addLayout(filt)

        # ── splitter: file list | entries table ──
        splitter = QSplitter(Qt.Horizontal)

        # left: file list
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        lbl_files = QLabel(TR("tr_files"))
        lbl_files.setStyleSheet(
            f"font-weight: bold; padding: 6px 8px; color: {C_TEXT_SECONDARY};")
        left_lay.addWidget(lbl_files)
        from PySide6.QtWidgets import QScrollArea
        self._file_scroll = QScrollArea()
        self._file_scroll.setWidgetResizable(True)
        self._file_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._file_list_inner = QWidget()
        self._file_list_lay = QVBoxLayout(self._file_list_inner)
        self._file_list_lay.setContentsMargins(0, 0, 0, 0)
        self._file_list_lay.setSpacing(0)
        self._file_list_lay.addStretch()
        self._file_scroll.setWidget(self._file_list_inner)
        left_lay.addWidget(self._file_scroll, 1)
        splitter.addWidget(left)

        # right: entries table
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        self.lbl_entries_title = QLabel(TR("tr_select_file"))
        self.lbl_entries_title.setStyleSheet(
            f"font-weight: bold; padding: 6px 8px; color: {C_TEXT_SECONDARY};")
        right_lay.addWidget(self.lbl_entries_title)

        self.table = QTableWidget(0, len(ENTRY_COLS))
        self.table.setHorizontalHeaderLabels(ENTRY_COLS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.table.setColumnWidth(0, 160)  # Context
        self.table.setColumnWidth(1, 280)  # Original
        self.table.setColumnWidth(2, 280)  # Translation
        self.table.setColumnWidth(3, 50)   # Status
        self.table.itemChanged.connect(self._on_item_changed)
        right_lay.addWidget(self.table, 1)

        splitter.addWidget(right)
        splitter.setSizes([240, 760])
        root.addWidget(splitter, 1)

        # ── bottom bar ──
        bottom = QHBoxLayout()
        bottom.setContentsMargins(8, 0, 8, 0)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.lbl_status = QLabel("")
        bottom.addWidget(self.progress, 1)
        bottom.addWidget(self.lbl_status)
        root.addLayout(bottom)

    # ── helpers ──

    def _project(self):
        return self.main.project

    # ── extract ──

    def extract_text(self):
        p = self._project()
        if not p:
            QMessageBox.information(self, TR("err"), TR("tr_no_project"))
            return
        if not self.main.engine_module:
            QMessageBox.warning(self, TR("err"), TR("tr_no_engine"))
            return
        self.btn_extract.setEnabled(False)
        self.lbl_status.setText(TR("tr_extracting"))
        self.main.start_extraction(self._on_extracted)

    def _on_extracted(self, restored: int, error: str):
        self.btn_extract.setEnabled(True)
        if error:
            self.lbl_status.setText(error)
            return
        p = self._project()
        self.main.refresh_all()
        QMessageBox.information(
            self, TR("done"),
            TR("tr_extract_done", count=len(p.entries), restored=restored))

    # ── file list (left panel) ──

    def _rebuild_file_list(self):
        for item in self._file_items:
            item.setParent(None)
            item.deleteLater()
        self._file_items.clear()

        p = self._project()
        if not p or not p.entries:
            return

        by_file: dict[str, list[TranslationEntry]] = {}
        for e in p.entries:
            by_file.setdefault(e.file, []).append(e)

        # "all" item
        all_total = len(p.entries)
        all_done = sum(1 for e in p.entries
                       if e.translation.strip() and e.status != "skip")
        all_item = _FileItem(TR("tr_all_files"), all_total, all_done)
        all_item.clicked.connect(lambda _: self._select_file(""))
        self._file_list_lay.insertWidget(0, all_item)
        self._file_items.append(all_item)

        for fname in sorted(by_file):
            fe = by_file[fname]
            total = len(fe)
            done = sum(1 for e in fe
                       if e.translation.strip() and e.status != "skip")
            item = _FileItem(fname, total, done)
            item.clicked.connect(lambda _, f=fname: self._select_file(f))
            self._file_list_lay.insertWidget(
                len(self._file_items), item)
            self._file_items.append(item)

        self._highlight_file()

    def _select_file(self, fname: str):
        self._selected_file = fname
        self._highlight_file()
        self.fill_table()

    def _highlight_file(self):
        for item in self._file_items:
            is_all = (item.fname == TR("tr_all_files"))
            active = (is_all and not self._selected_file) \
                or (item.fname == self._selected_file)
            item.set_active(active)

    # ── entries table (right panel) ──

    def _filtered(self) -> list[TranslationEntry]:
        p = self._project()
        if not p:
            return []
        q = self.search.text().strip().lower()
        mode = self.filter_combo.currentIndex()
        out = []
        for e in p.entries:
            if self._selected_file and e.file != self._selected_file:
                continue
            if q and q not in e.original.lower() \
                    and q not in e.translation.lower():
                continue
            if mode == 1 and e.translation.strip():
                continue
            if mode == 2 and not e.translation.strip():
                continue
            if mode == 3 and e.status != "skip":
                continue
            out.append(e)
        return out

    def fill_table(self):
        p = self._project()
        self._loading = True
        try:
            rows = self._filtered()
            title = self._selected_file or TR("tr_all_files")
            total_in_file = sum(1 for e in p.entries
                                if not self._selected_file
                                or e.file == self._selected_file) if p else 0
            self.lbl_entries_title.setText(
                f"{title}  ({len(rows)}/{total_in_file})")

            capped = len(rows) > 10000
            if capped:
                rows = rows[:10000]
            self.table.setUpdatesEnabled(False)
            self.table.setRowCount(len(rows))
            for r, e in enumerate(rows):
                items = [
                    QTableWidgetItem(e.context),
                    QTableWidgetItem(e.original),
                    QTableWidgetItem(e.translation),
                    QTableWidgetItem(""),
                ]
                st_icon = STATUS_ICON.get(e.status)
                if st_icon:
                    items[3].setIcon(icon(st_icon))
                for c, it in enumerate(items):
                    if c != 2:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    it.setData(Qt.UserRole, e.id)
                    self.table.setItem(r, c, it)
            self.table.setUpdatesEnabled(True)
            note = TR("tr_status_cap") if capped else ""
            self.lbl_status.setText(
                TR("tr_status", shown=len(rows),
                   total=len(p.entries) if p else 0, note=note))
        finally:
            self._loading = False

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != 2:
            return
        p = self._project()
        if not p:
            return
        entry_id = item.data(Qt.UserRole)
        for e in p.entries:
            if e.id == entry_id:
                e.translation = item.text()
                e.status = "manual"
                status_item = self.table.item(item.row(), 3)
                if status_item:
                    status_item.setIcon(icon(STATUS_ICON["manual"]))
                break

    # ── translate ──

    def translate_all(self):
        p = self._project()
        if not p or not p.entries:
            QMessageBox.information(self, TR("err"), TR("tr_no_data"))
            return
        engine = self.main.create_engine("files")
        if engine is None:
            QMessageBox.critical(self, TR("err"),
                                 TR("tr_engine_create_fail"))
            return
        s = self.main.settings
        engine_name = s.value("engine_files", s.value("engine", "rotate"))
        if not engine.ping():
            QMessageBox.warning(self, TR("err"), engine_hint(engine_name))
            return
        translator = Translator(engine, tm=self.main.tm,
                                glossary=self.main.glossary)
        self.worker = TranslateWorker(
            translator, p.entries,
            s.value("source_lang", "auto"), s.value("target_lang", "ru"),
            overwrite=self.mode_combo.currentIndex() == 1)
        self.worker.progressed.connect(self._on_progress)
        self.worker.done.connect(self._on_translated)
        self.worker.failed.connect(self._on_translate_failed)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_cancel.setEnabled(True)
        self.btn_translate.setEnabled(False)
        self.main.loading.show_loading(TR("tr_translating"), TR("tr_cancel"),
                                       self.cancel_translate)
        self.worker.start()

    def cancel_translate(self):
        if self.worker:
            self.worker.translator.cancel()
            self.worker.requestInterruption()
            self.worker.wait(2000)
            if self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait(1000)
        if self.worker_correct:
            self.worker_correct.corrector.cancel()
            self.worker_correct.requestInterruption()
            self.worker_correct.wait(2000)
            if self.worker_correct.isRunning():
                self.worker_correct.terminate()
                self.worker_correct.wait(1000)
        self._finish_translate()

    def _on_progress(self, done, total):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        text = TR("tr_progress", done=done, total=total)
        self.lbl_status.setText(text)
        self.main.loading.set_text(text)

    def _on_translated(self, n):
        self._finish_translate()
        self.main.save_project()
        self._rebuild_file_list()
        self.fill_table()
        QMessageBox.information(self, TR("done"),
                                TR("tr_translate_done", n=n))

    def _on_translate_failed(self, msg):
        self._finish_translate()
        self.fill_table()
        QMessageBox.critical(self, TR("err"), msg)

    def _finish_translate(self):
        self.main.loading.hide_loading()
        self.progress.setVisible(False)
        self.btn_cancel.setEnabled(False)
        self.btn_translate.setEnabled(True)
        self.btn_correct.setEnabled(True)
        if self.worker:
            self.worker.wait(5000)
            self.worker = None
        if self.worker_correct:
            self.worker_correct.wait(5000)
            self.worker_correct = None

    # ── correct ──

    def correct_all(self):
        p = self._project()
        if not p or not p.entries:
            return
        from app.core.translate.corrector import Corrector
        engine = self.main.create_engine("corrector")
        if engine is None:
            QMessageBox.critical(self, TR("err"),
                                 TR("tr_engine_create_fail"))
            return
        try:
            corrector = Corrector(engine)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, TR("tr_correct"), str(e))
            return
        self.worker_correct = CorrectWorker(
            corrector, p.entries,
            self.main.settings.value("target_lang", "ru"))
        self.worker_correct.progressed.connect(self._on_progress)
        self.worker_correct.corrections_ready.connect(self._on_corrections)
        self.worker_correct.failed.connect(self._on_translate_failed)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_cancel.setEnabled(True)
        self.btn_correct.setEnabled(False)
        self.main.loading.show_loading(TR("tr_correcting"), TR("tr_cancel"),
                                       self.cancel_translate)
        self.worker_correct.start()

    def _on_corrections(self, diffs):
        self._finish_translate()
        if not diffs:
            QMessageBox.information(self, TR("done"),
                                    TR("tr_correct_done", n=0))
            return
        dlg = DiffReviewDialog(diffs, self)
        if dlg.exec() == QDialog.Accepted:
            accepted = [d for d in diffs if d.accepted]
            for d in accepted:
                d.entry.translation = d.new_text
                d.entry.status = "corrected"
            self.main.save_project()
            self._rebuild_file_list()
            self.fill_table()
            QMessageBox.information(
                self, TR("done"),
                TR("tr_correct_reviewed",
                    accepted=len(accepted), total=len(diffs)))

    # ── glossary ──

    def edit_glossary(self):
        p = self._project()
        texts = [e.original for e in p.entries] if p else []
        if self.main.settings.value("glossary_use_ai", True, type=bool):
            engine = self.main.create_engine("corrector")
        else:
            engine = None
        GlossaryDialog(self.main.glossary, self.main.settings, self,
                       texts=texts, engine=engine).exec()

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
                except (ValueError, KeyError):
                    continue
                if e and row.get("translation", "").strip():
                    e.translation = row["translation"]
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
        translated = sum(1 for e in p.entries if e.translation.strip())
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
        parts = [TR("tr_apply_done", files=stats["files"],
                     strings=stats["strings"])]
        if stats.get("backups"):
            parts.append(TR("tr_apply_backup", n=len(stats["backups"])))
        if stats.get("out_dir"):
            parts.append(TR("tr_apply_folder", path=stats["out_dir"]))
        QMessageBox.information(self, TR("done"), "\n".join(parts))


# ────────────────────────────────────────────────────────
#  Term candidates dialog (автоглоссарий)
# ────────────────────────────────────────────────────────
class TermsDialog(QDialog):
    """Кандидаты терминов от LLM: чекбокс + термин + перевод."""

    def __init__(self, terms: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle(TR("glossary_terms_title"))
        self.resize(620, 420)
        self.terms = terms
        self.selected: dict[str, str] = {}
        lay = QVBoxLayout(self)
        hint = QLabel(TR("glossary_terms_hint"))
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.table = QTableWidget(len(terms), 3)
        self.table.setHorizontalHeaderLabels([
            TR("glossary_terms_col_use"), TR("glossary_terms_col_orig"),
            TR("glossary_terms_col_tr")])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 40)
        for r, (term, trans) in enumerate(sorted(terms.items())):
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.Checked)
            self.table.setItem(r, 0, chk)
            self.table.setItem(r, 1, QTableWidgetItem(term))
            self.table.setItem(r, 2, QTableWidgetItem(trans))
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        btn_apply = QPushButton(TR("glossary_terms_apply"))
        btn_apply.setObjectName("accent")
        btn_apply.clicked.connect(self._collect)
        btn_cancel = QPushButton(TR("cancel"))
        btn_cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_apply)
        lay.addLayout(row)

    def _collect(self):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                term = self.table.item(r, 1).text().strip()
                trans = self.table.item(r, 2).text().strip()
                if term and trans:
                    self.selected[term] = trans
        self.accept()


# ────────────────────────────────────────────────────────
#  Glossary dialog
# ────────────────────────────────────────────────────────
class GlossaryDialog(QDialog):
    PAIRS = ["ja->ru", "zh->ru", "en->ru", "ja->en", "zh->en", "ru->en"]

    def __init__(self, glossary, settings, parent=None,
                 texts: list[str] | None = None, engine=None):
        super().__init__(parent)
        self.glossary = glossary
        self.texts = texts or []
        self.engine = engine
        self.analyze_worker: AnalyzeWorker | None = None
        self.setWindowTitle(TR("glossary_title"))
        self.resize(600, 450)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel(TR("glossary_pair")))
        self.pair = QComboBox()
        self.pair.setEditable(True)
        self.pair.addItems(self.PAIRS)
        src = settings.value("source_lang", "auto")
        src = "ja" if src == "auto" else src
        self.pair.setCurrentText(
            f"{src}->{settings.value('target_lang', 'ru')}")
        self.pair.currentTextChanged.connect(self._fill)
        top.addWidget(self.pair, 1)
        lay.addLayout(top)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(
            [TR("glossary_col_orig"), TR("glossary_col_tr")])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        btn_add = QPushButton(TR("glossary_add"))
        btn_add.clicked.connect(
            lambda: self.table.insertRow(self.table.rowCount()))
        btn_del = QPushButton(TR("glossary_del"))
        btn_del.clicked.connect(self._del)
        btn_analyze = QPushButton(TR("glossary_analyze"))
        btn_analyze.clicked.connect(self._analyze)
        btn_save = QPushButton(TR("glossary_save"))
        btn_save.clicked.connect(self._save)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addStretch(1)
        row.addWidget(btn_analyze)
        row.addWidget(btn_save)
        lay.addLayout(row)

        hint = QLabel(TR("glossary_hint"))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._fill()

    def _current_pair(self) -> tuple[str, str]:
        parts = self.pair.currentText().split("->")
        return (parts[0].strip(), parts[1].strip()) \
            if len(parts) == 2 else ("ja", "ru")

    def _fill(self):
        src, tgt = self._current_pair()
        terms = self.glossary.terms(src, tgt)
        self.table.setRowCount(len(terms))
        for r, (k, v) in enumerate(sorted(terms.items())):
            self.table.setItem(r, 0, QTableWidgetItem(k))
            self.table.setItem(r, 1, QTableWidgetItem(v))

    def _del(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()},
                      reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def _analyze(self):
        if not self.texts:
            QMessageBox.information(
                self, TR("err"), TR("tr_no_data"))
            return
        if self.engine is None or not self.engine.ping():
            QMessageBox.warning(
                self, TR("err"), TR("glossary_analyze_need_ai"))
            return
        src, tgt = self._current_pair()
        self.analyze_worker = AnalyzeWorker(self.engine, self.texts, src, tgt)
        self.analyze_worker.done.connect(self._analyze_done)
        self.analyze_worker.failed.connect(self._analyze_failed)
        self.setWindowTitle(TR("glossary_analyze_running"))
        self.analyze_worker.start()

    def _analyze_done(self, terms: dict):
        self.setWindowTitle(TR("glossary_title"))
        if not terms:
            QMessageBox.information(
                self, TR("done"), TR("glossary_analyze_none"))
            return
        dlg = TermsDialog(terms, self)
        if dlg.exec() == QDialog.Accepted:
            src, tgt = self._current_pair()
            merged = dict(self.glossary.terms(src, tgt))
            merged.update(dlg.selected)
            self.glossary.set_terms(src, tgt, merged)
            self._fill()
            QMessageBox.information(
                self, TR("done"),
                TR("glossary_analyze_added", accepted=len(dlg.selected),
                   total=len(terms)))

    def _analyze_failed(self, err: str):
        self.setWindowTitle(TR("glossary_title"))
        QMessageBox.critical(
            self, TR("err"), TR("glossary_analyze_fail", msg=err))

    def _save(self):
        src, tgt = self._current_pair()
        terms = {}
        for r in range(self.table.rowCount()):
            k = self.table.item(r, 0)
            v = self.table.item(r, 1)
            if k and k.text().strip():
                terms[k.text().strip()] = v.text().strip() if v else ""
        self.glossary.set_terms(src, tgt, terms)
        self.accept()
