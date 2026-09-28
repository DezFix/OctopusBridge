# -*- coding: utf-8 -*-
"""Виджеты таблицы перевода: колонки, пилюли статуса, делегаты, items.

Всё оформление таблицы/списка файлов в одном месте — TranslateTab
только раскладывает их по лэйаутам. Раньше жили в
app/ui/translate_tab.py.
"""
from __future__ import annotations

from PySide6.QtCore import (QEvent, QPointF, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QAbstractItemDelegate, QFrame, QHBoxLayout,
                               QLabel, QPlainTextEdit, QProgressBar,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from app.core.models import TranslationEntry
from app.core.translate.detect import detect_lang
from app.ui.i18n import TR
from app.ui.theme import (C_ACCENT, C_BG, C_GROUP_BORDER, C_PILL_DONE,
                          C_PILL_DRAFT, C_PILL_EMPTY_FG, C_PRIMARY, C_TEXT,
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
                 all_item: bool = False, target_lang: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("file_item")
        self.fname = fname
        self._tl = target_lang
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

        self.tag = QLabel("")
        self.tag.setStyleSheet(
            f"color: {C_PILL_DRAFT}; background: transparent;"
            "font-size: 10.5px;")
        self.tag.setVisible(False)
        lay.addWidget(self.tag)

        if target_lang:
            self.bar.setVisible(False)
            self.tag.setText(TR("tr_file_target_lang"))
            self.tag.setVisible(True)
            self.count.setText("")
            self.setToolTip(TR("tr_file_target_lang_hint"))
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
        if not self._tl:
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
        self.document().setDocumentMargin(3)
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background: #1e2230;
                border: 1.5px solid {C_PRIMARY};
                border-radius: 6px;
                color: {C_TEXT};
                padding: 2px;
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

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect
        h = max(r.height() * 3, 64)
        editor.setGeometry(r.x(), r.y(), r.width(), h)

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


def _file_is_target_lang(fe: list[TranslationEntry], tgt: str) -> bool:
    """Файл целиком на целевом языке — перевод ему не нужен.

    Проверяем выборку строк (до 40): если все распознанные языки
    совпадают с целевым — файл отделяется в конец списка с меткой.
    """
    texts = [e.original for e in fe if (e.original or "").strip()]
    if not texts:
        return False
    known = [l for l in (detect_lang(t) for t in texts[:40]) if l]
    if not known:
        return False
    return all(l == tgt for l in known)


def _ctx_short(ctx: str) -> str:
    parts = [x for x in ctx.replace("\\", "/").split("/") if x]
    return "/".join(parts[-2:]) if len(parts) > 2 else ctx


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")
