# -*- coding: utf-8 -*-
"""Вкладка «Перевод файлов»: левая панель — файлы (поиск, прогресс, донут),
правая — хлебные крошки, фильтр, таблица/карточки, инлайн-редактирование,
статус-пилюли, степпер шагов в топбаре."""
from __future__ import annotations

from PySide6.QtCore import (QEvent, QPointF, QRectF, QSize, Qt, QThread,
                            QTimer, Signal)
from PySide6.QtGui import (QActionGroup, QColor, QFont, QIcon, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView,
                               QComboBox, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea,
                               QSplitter, QStackedWidget, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem, QToolButton,
                               QVBoxLayout, QWidget)

from app.core.models import TranslationEntry
from app.core.translate.service import Translator
from app.ui.i18n import TR, engine_hint
from app.ui.icons import icon
from app.ui.theme import (C_ACCENT, C_BG, C_GROUP_BORDER,
                          C_PILL_DONE, C_PILL_DRAFT, C_PILL_EMPTY_FG,
                          C_PRIMARY, C_TEXT, C_TEXT_SECONDARY,
                          C_TRACK)

# ── columns ──
COL_IDX, COL_CTX, COL_ORIG, COL_TRANS, COL_STATUS = range(5)

# ── status pill states ──
STATE_EMPTY, STATE_DRAFT, STATE_DONE, STATE_SKIP = range(4)

_STATE_LABEL = {
    STATE_EMPTY: "tr_status_empty",
    STATE_DRAFT: "tr_status_draft",
    STATE_DONE: "tr_status_done",
    STATE_SKIP: "tr_status_skip",
}
_STATE_TO_STATUS = {
    STATE_EMPTY: "new",
    STATE_DRAFT: "manual",
    STATE_DONE: "translated",
}


def _step_icon(n: int, active: bool = False) -> QIcon:
    """Кружок-номер для кнопок степпера."""
    size = 16
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if active:
        bg, fg = QColor(255, 255, 255, 64), QColor("#ffffff")
    else:
        bg, fg = QColor(C_BG), QColor(C_PILL_EMPTY_FG)
    p.setBrush(bg)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
    f = QFont("Segoe UI", 7)
    f.setBold(True)
    p.setFont(f)
    p.setPen(fg)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, str(n))
    p.end()
    return QIcon(pm)


class ExtractWorker(QThread):
    """Фоновое извлечение текста из игры (не морозит GUI)."""

    done = Signal(object)       # list[TranslationEntry]
    failed = Signal(str)

    def __init__(self, module, game_dir: str, extract_lang: str | None = None):
        super().__init__()
        self.setObjectName("ExtractWorker")
        self._module = module
        self._game_dir = game_dir
        self._extract_lang = extract_lang

    def run(self):
        try:
            if self._extract_lang and hasattr(self._module, "list_languages"):
                entries = self._module.extract(self._game_dir, self._extract_lang)
            else:
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
            self.corrector.correct_all(self.entries, self.tgt,
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
            btn_r.setIcon(icon("x"))
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
#  Donut (кольцевой индикатор общего прогресса)
# ────────────────────────────────────────────────────────
class _Donut(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pct = 0.0
        self.setFixedSize(34, 34)

    def set_value(self, pct: float):
        self._pct = max(0.0, min(1.0, pct))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 2
        off = (self.width() - side) / 2
        rect = QRectF(off, off, side, side)
        track = QPen(QColor(C_TRACK), 3.5, Qt.SolidLine, Qt.RoundCap)
        p.setPen(track)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect)

        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor(C_PRIMARY))
        grad.setColorAt(1.0, QColor(C_ACCENT))
        fg = QPen(QColor(C_PRIMARY), 3.5, Qt.SolidLine, Qt.RoundCap)
        fg.setBrush(grad)
        p.setPen(fg)
        p.drawArc(rect, 90 * 16, int(-self._pct * 360 * 16))
        p.end()


# ────────────────────────────────────────────────────────
#  File list item (left panel)
# ────────────────────────────────────────────────────────
class _FileItem(QFrame):
    clicked = Signal(str)

    _QSS = f"""
        QFrame#file_item {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px;
        }}
        QFrame#file_item:hover {{
            background: #1e2230;
        }}
        QFrame#file_item[active="true"] {{
            background: rgba(91, 143, 239, 0.15);
            border-color: rgba(91, 127, 255, 0.35);
        }}
        QFrame#file_item[all="true"] {{
            border-bottom: 1px solid {C_GROUP_BORDER};
            margin-bottom: 9px;
        }}
        QProgressBar {{
            background: {C_TRACK};
            border: none;
            border-radius: 2px;
        }}
        QProgressBar::chunk {{
            border-radius: 2px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {C_PRIMARY}, stop:1 {C_ACCENT});
        }}
        QProgressBar[fillstate="zero"]::chunk {{
            background: transparent;
        }}
        QProgressBar[fillstate="done"]::chunk {{
            background: {C_PILL_DONE};
        }}
    """

    def __init__(self, fname: str, total: int, done: int,
                 all_item: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("file_item")
        self.fname = fname
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(52)
        self.setMinimumWidth(0)
        self.setStyleSheet(self._QSS)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(9, 8, 9, 8)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.name = QLabel(fname)
        self.name.setMinimumWidth(0)
        bold = "font-weight: bold;" if all_item else ""
        self.name.setStyleSheet(
            f"color: {C_TEXT}; background: transparent; {bold}"
            "font-size: 12px;"
            "font-family: 'Cascadia Code', 'Consolas', monospace;")
        top.addWidget(self.name, 1)
        self.count = QLabel("")
        self.count.setStyleSheet(
            f"color: {C_PILL_EMPTY_FG}; background: transparent;"
            "font-size: 10.5px;")
        top.addWidget(self.count)
        lay.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setMinimumWidth(0)
        lay.addWidget(self.bar)

        self.update_counts(done, total)

    def update_counts(self, done: int, total: int):
        pct = round(done / total * 100) if total else 0
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        if done == 0:
            state = "zero"
        elif done >= total:
            state = "done"
        else:
            state = "part"
        self.bar.setProperty("fillstate", state)
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.count.setText(f"{done}/{total}")
        self.count.setStyleSheet(
            ("color: #39c98f;" if pct == 100 else
             f"color: {C_PILL_EMPTY_FG};")
            + " background: transparent; font-size: 10.5px;")
        self.setToolTip(f"{done}/{total} ({pct}%)")

    def set_active(self, active: bool):
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.name.setStyleSheet(
            ("color: #ffffff;" if active else f"color: {C_TEXT};")
            + " background: transparent; font-size: 12px;"
              "font-family: 'Cascadia Code', 'Consolas', monospace;")

    def mousePressEvent(self, event):
        self.clicked.emit(self.fname)
        super().mousePressEvent(event)


# ────────────────────────────────────────────────────────
#  Inline translation editor (textarea в таблице/карточках)
# ────────────────────────────────────────────────────────
class _TransEditor(QPlainTextEdit):
    commit_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background: #1e2230;
                border: 1.5px solid {C_PRIMARY};
                border-radius: 6px;
                color: {C_TEXT};
                padding: 4px;
                font-size: 12.5px;
            }}
        """)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) \
                and not (event.modifiers() & Qt.ShiftModifier):
            event.accept()
            self.commit_requested.emit()
            return
        if event.key() == Qt.Key_Escape:
            event.accept()
            self.cancel_requested.emit()
            return
        super().keyPressEvent(event)


class _TransDelegate(QStyledItemDelegate):
    """Клик по ячейке перевода → textarea прямо в таблице.
    Enter — сохранить, Esc — отмена, потеря фокуса — автосохранение."""

    def createEditor(self, parent, option, index):
        ed = _TransEditor(parent)
        ed.commit_requested.connect(
            lambda: (self.commitData.emit(ed),
                     self.closeEditor.emit(
                         ed, QAbstractItemDelegate.EndEditHint.EditFinished)))
        ed.cancel_requested.connect(
            lambda: self.closeEditor.emit(
                ed, QAbstractItemDelegate.EndEditHint.NoHint))
        return ed

    def setEditorData(self, editor, index):
        editor.setPlainText(index.data(Qt.ItemDataRole.DisplayRole) or "")

    def setModelData(self, editor, model, index):
        model.setData(index,
                      editor.toPlainText(), Qt.ItemDataRole.EditRole)


# ────────────────────────────────────────────────────────
#  Status pill delegate (клик — циклическая смена статуса)
# ────────────────────────────────────────────────────────
def _pill_colors(state: int) -> tuple[QColor, QColor, QColor]:
    """(bg, fg, dot) для состояния пилюли."""
    if state == STATE_DRAFT:
        return (QColor(240, 169, 62, 33), QColor(C_PILL_DRAFT),
                QColor(240, 169, 62))
    if state == STATE_DONE:
        return (QColor(57, 201, 143, 33), QColor(C_PILL_DONE),
                QColor(57, 201, 143))
    if state == STATE_SKIP:
        return (QColor(93, 99, 119, 38), QColor("#5d6377"),
                QColor(93, 99, 119))
    return (QColor(255, 255, 255, 13), QColor(C_PILL_EMPTY_FG),
            QColor(C_PILL_EMPTY_FG))


class _StatusDelegate(QStyledItemDelegate):
    cycled = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._meta = None   # fn(entry_id) -> (state, label)

    def set_meta_lookup(self, fn):
        self._meta = fn

    def paint(self, painter, option, index):
        state, label = STATE_EMPTY, ""
        if self._meta:
            eid = index.data(Qt.ItemDataRole.UserRole)
            if eid is not None:
                state, label = self._meta(int(eid))
        bg, fg, dot = _pill_colors(state)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect.adjusted(6, 6, -6, -6)
        if rect.height() > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect), rect.height() / 2,
                                rect.height() / 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawPath(path)
            c = QPointF(rect.left() + 11, rect.top() + rect.height() / 2)
            painter.setBrush(dot)
            painter.drawEllipse(c, 3, 3)
            if label:
                painter.setPen(fg)
                f = painter.font()
                f.setPixelSize(11)
                f.setBold(True)
                painter.setFont(f)
                painter.drawText(
                    QRectF(rect.left() + 19, rect.top(),
                           max(rect.width() - 25, 0), rect.height()),
                    Qt.AlignVCenter | Qt.AlignLeft, label)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(118, 30)

    def editorEvent(self, event, model, option, index):
        if (event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and index.isValid()):
            eid = index.data(Qt.ItemDataRole.UserRole)
            if eid is not None:
                self.cycled.emit(int(eid))
                return True
        return super().editorEvent(event, model, option, index)



# ────────────────────────────────────────────────────────
#  Main translate tab
# ────────────────────────────────────────────────────────
def _state_of(e: TranslationEntry) -> int:
    if e.status == "skip":
        return STATE_SKIP
    if e.status in ("translated", "corrected"):
        return STATE_DONE
    if e.status == "manual":
        return STATE_DRAFT
    return STATE_EMPTY


def _entry_matches(q: str, e: TranslationEntry) -> bool:
    """Поиск по строке: имя/оригинал/перевод (без учёта регистра)."""
    return (q in (e.original or "").lower()
            or q in (e.translation or "").lower())


def _ctx_short(ctx: str) -> str:
    parts = [x for x in ctx.replace("\\", "/").split("/") if x]
    return "/".join(parts[-2:]) if len(parts) > 2 else ctx


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


class TranslateTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.worker: TranslateWorker | None = None
        self.worker_correct: CorrectWorker | None = None
        self._loading = False
        self._cancelling = False
        self._cancel_elapsed = 0
        self._cancel_timer: QTimer | None = None
        self._status_timer: QTimer | None = None
        self._last_progress = (0, 0)
        self._selected_file = ""
        self._file_items: list[_FileItem] = []
        self._toast_timer: QTimer | None = None

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

        self.btn_translate = QToolButton()
        self.btn_translate.setObjectName("step")
        self.btn_translate.setIcon(_step_icon(2))
        self.btn_translate.setIconSize(QSize(16, 16))
        self.btn_translate.setText(" " + TR("tr_translate"))
        self.btn_translate.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_translate.setToolButtonStyle(
            Qt.ToolButtonTextBesideIcon)
        self._mode_group = QActionGroup(self)
        self._act_new = self._mode_group.addAction(TR("tr_mode_new"))
        self._act_all = self._mode_group.addAction(TR("tr_mode_all"))
        self._act_new.setCheckable(True)
        self._act_all.setCheckable(True)
        self._act_new.setChecked(True)
        menu = QMenu(self.btn_translate)
        menu.addAction(self._act_new)
        menu.addAction(self._act_all)
        self.btn_translate.setMenu(menu)
        self.btn_translate.setCursor(Qt.PointingHandCursor)
        self.btn_translate.clicked.connect(self.translate_all)
        bar.addWidget(self.btn_translate)

        self.btn_apply = QPushButton(TR("tr_apply"))
        self.btn_apply.setProperty("step", True)
        self.btn_apply.setIcon(_step_icon(3))
        self.btn_apply.setIconSize(QSize(16, 16))
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        self.btn_apply.clicked.connect(self.apply_to_game)
        bar.addWidget(self.btn_apply)

        self.btn_correct = QPushButton(TR("tr_correct"))
        self.btn_correct.setObjectName("tool_btn")
        self.btn_correct.setIcon(icon("ai", 14, C_TEXT_SECONDARY))
        self.btn_correct.clicked.connect(self.correct_all)
        bar.addWidget(self.btn_correct)

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
        left.setMinimumWidth(260)
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(10, 10, 8, 0)
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
        self.view_filter = QComboBox()
        self.view_filter.setObjectName("chip_filter")
        self.view_filter.addItems([
            TR("tr_mode_new"), TR("tr_filter_all_lines"),
            TR("tr_filter_untranslated"), TR("tr_filter_drafts"),
            TR("tr_filter_finished"), TR("tr_filter_skipped")])
        self.view_filter.currentIndexChanged.connect(self.fill_table)
        hdr.addWidget(self.view_filter)
        right_lay.addLayout(hdr)

        self.stack = QStackedWidget()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            TR("tr_col_idx"), TR("tr_col_context"), TR("tr_col_original"),
            TR("tr_col_translation"), TR("tr_col_status")])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.table.setColumnWidth(COL_IDX, 44)
        self.table.setColumnWidth(COL_CTX, 190)
        self.table.setColumnWidth(COL_ORIG, 320)
        self.table.setColumnWidth(COL_TRANS, 340)
        self.table.setColumnWidth(COL_STATUS, 118)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked)
        self.table.itemChanged.connect(self._on_item_changed)
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
        splitter.setSizes([270, 760])
        root.addWidget(splitter, 1)

        # ── bottom bar: прогресс перевода + статус ──
        bottom = QHBoxLayout()
        bottom.setContentsMargins(12, 4, 12, 8)
        bottom.setSpacing(8)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
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

    def _flash_saved(self):
        self.toast.show()
        self.toast.raise_()
        self._place_toast()
        if self._toast_timer:
            self._toast_timer.stop()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self.toast.hide)
        self._toast_timer.start(1000)

    # ── шаги (степпер) ──

    def _update_steps(self):
        p = self._project()
        n = len(p.entries) if p else 0
        translated = sum(1 for e in p.entries if e.translation.strip()) \
            if p else 0
        busy = bool((self.worker and self.worker.isRunning())
                    or (self.worker_correct
                        and self.worker_correct.isRunning()))
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
                       if e.translation.strip() and e.status != "skip")
        all_item = _FileItem(TR("tr_all_files"), all_total, all_done,
                             all_item=True)
        all_item.clicked.connect(lambda _: self._select_file(""))
        self._file_list_lay.insertWidget(0, all_item)
        self._file_items.append(all_item)

        for fname in sorted(by_file):
            if q:
                if q in fname.lower():
                    pass  # имя файла совпало
                elif not any(_entry_matches(q, e) for e in by_file[fname]):
                    continue  # ни имя, ни строки не совпали
            fe = by_file[fname]
            total = len(fe)
            done = sum(1 for e in fe
                       if e.translation.strip() and e.status != "skip")
            item = _FileItem(fname, total, done)
            item.clicked.connect(lambda _, f=fname: self._select_file(f))
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
        p = self._project()
        if not p:
            return
        entry_id = item.data(Qt.UserRole)
        for e in p.entries:
            if e.id == entry_id:
                e.translation = item.text()
                e.status = "manual"
                break
        self._update_stats()
        self._update_steps()
        self.table.viewport().update()
        self._flash_saved()

    # ── статус-пилюля: клик циклически меняет статус ──

    def _cycle_status(self, entry_id: int):
        p = self._project()
        if not p:
            return
        e = next((x for x in p.entries if x.id == entry_id), None)
        if not e:
            return
        state = _state_of(e)
        if state == STATE_SKIP:
            next_state = STATE_EMPTY
        else:
            next_state = (state + 1) % 3
        e.status = _STATE_TO_STATUS[next_state]
        self.table.viewport().update()
        self._update_stats()

    # ── сводки (сайдбар + статус-бар) ──

    def _project_stats(self) -> tuple[int, int, int, int]:
        p = self._project()
        if not p:
            return 0, 0, 0, 0
        done = draft = empty = 0
        for e in p.entries:
            if e.translation.strip():
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
                         if e.translation.strip() and e.status != "skip")
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
            if fe and all(e.translation.strip() and e.status != "skip"
                          for e in fe))
        self.lbl_files_sum.setText(
            "" if not p else TR("tr_files_summary",
                                files=n_files, done=done_files))
        # глобальный статус-бар
        self.main.refresh_project_stats()

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
            overwrite=self._act_all.isChecked())
        self.worker.progressed.connect(self._on_progress)
        self.worker.done.connect(self._on_translated)
        self.worker.failed.connect(self._on_translate_failed)
        self._cancelling = False
        self._last_progress = (0, 0)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self.btn_translate.setEnabled(False)
        self.btn_correct.setEnabled(False)
        self.main.loading.show_loading(TR("tr_translating"), TR("tr_cancel"),
                                       self.cancel_translate)
        self.worker.start()

    def cancel_translate(self):
        """Мягкая отмена: флаги остановки + ожидание фонового завершения
        через таймер (GUI не блокируется, полоса/текст доигрывают плавно)."""
        self._cancelling = True
        self._cancel_elapsed = 0
        for w in (self.worker, self.worker_correct):
            if not w:
                continue
            translator = getattr(w, "translator", None)
            if translator is not None:
                translator.cancel()
            corrector = getattr(w, "corrector", None)
            if corrector is not None:
                corrector.cancel()
            w.requestInterruption()
        self.btn_cancel.setEnabled(False)
        self.main.loading.set_text(TR("tr_cancelling"))
        busy = (self.worker and self.worker.isRunning()) or (
            self.worker_correct and self.worker_correct.isRunning())
        if not busy:
            self._finish_cancelled()
            return
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self._poll_cancel)
        self._cancel_timer.start(120)

    def _poll_cancel(self):
        self._cancel_elapsed += 120
        busy = (self.worker and self.worker.isRunning()) or (
            self.worker_correct and self.worker_correct.isRunning())
        if busy and self._cancel_elapsed < 8000:
            self._cancel_timer.start(120)
            return
        if busy:  # зависший поток — принудительно, но без GUI-блокировки
            for w in (self.worker, self.worker_correct):
                if w and w.isRunning():
                    w.terminate()
            self._cancel_timer.start(120)
            return
        self._finish_cancelled()

    def _finish_cancelled(self):
        done, total = self._last_progress
        self._finish_translate(TR("tr_cancelled", done=done, total=total))
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

    def _on_translated(self, n):
        if self._cancelling:
            return
        self._finish_translate()
        self.main.save_project()
        self._rebuild_file_list()
        self.fill_table()
        QMessageBox.information(self, TR("done"),
                                TR("tr_translate_done", n=n))

    def _on_translate_failed(self, msg):
        if self._cancelling:
            return
        self._finish_translate()
        self.main.save_project()
        self._rebuild_file_list()
        self.fill_table()
        QMessageBox.critical(self, TR("err"), msg)

    def _finish_translate(self, status_text: str = ""):
        self.main.loading.hide_loading()
        self.progress.setVisible(False)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setEnabled(False)
        self.btn_correct.setEnabled(True)
        if self.worker:
            self.worker.wait(5000)
            self.worker = None
        if self.worker_correct:
            self.worker_correct.wait(5000)
            self.worker_correct = None
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
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self.btn_correct.setEnabled(False)
        self.main.loading.show_loading(TR("tr_correcting"), TR("tr_cancel"),
                                       self.cancel_translate)
        self.worker_correct.start()

    def _on_corrections(self, diffs):
        if self._cancelling:
            return
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
        self._update_steps()


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

    def closeEvent(self, event):
        # Даём воркеру-анализатору штатно завершиться, иначе Qt упадёт
        # с «QThread: Destroyed while thread ... is still running».
        if self.analyze_worker and self.analyze_worker.isRunning():
            self.analyze_worker.requestInterruption()
            self.analyze_worker.wait(15000)
        super().closeEvent(event)

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