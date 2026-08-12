# -*- coding: utf-8 -*-
"""Status bar at the bottom: provider, connection, project summary (done /
draft / empty + pct bar), tasks."""
from __future__ import annotations

from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar)

from app.ui.i18n import TR
from app.ui.theme import (C_BORDER_LIGHT, C_CARD, C_PILL_DONE,
                          C_PILL_DRAFT, C_PILL_EMPTY_FG, C_PRIMARY,
                          C_SUCCESS, C_TEXT, C_TEXT_SECONDARY, C_TRACK)

_QSS_SB = f"""
QFrame#status_bar {{
    background-color: {C_CARD};
    border-top: 1px solid {C_BORDER_LIGHT};
}}
QProgressBar#mini {{
    background: {C_TRACK};
    border: none;
    border-radius: 3px;
    min-height: 6px;
    max-height: 6px;
}}
QProgressBar#mini::chunk {{
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C_PRIMARY}, stop:1 {C_PILL_DONE});
}}
"""


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


class StatusBar(QFrame):
    """Compact bottom bar with provider, connection, and task info."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("status_bar")
        self.setStyleSheet(_QSS_SB)
        self.setFixedHeight(32)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 2, 12, 2)
        lay.setSpacing(12)

        # provider
        self.lbl_provider = QLabel("")
        self.lbl_provider.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        lay.addWidget(self.lbl_provider)

        # dot separator
        dot1 = QLabel("·")
        dot1.setStyleSheet(f"color: {C_TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        lay.addWidget(dot1)

        # connection
        self.lbl_connection = QLabel("")
        self.lbl_connection.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 11px; background: transparent;")
        lay.addWidget(self.lbl_connection)

        lay.addStretch(1)

        # ── project summary: готово / черновики / пусто + %% ──
        self.lbl_done = self._mk_stat(lay, C_PILL_DONE, "sb_done")
        self.lbl_draft = self._mk_stat(lay, C_PILL_DRAFT, "sb_draft")
        self.lbl_empty = self._mk_stat(lay, C_PILL_EMPTY_FG, "sb_empty")

        self.lbl_pct = QLabel("")
        self.lbl_pct.setStyleSheet(
            f"color: {C_TEXT}; font-size: 11px; font-weight: 700; "
            "background: transparent;")
        lay.addWidget(self.lbl_pct)

        self.mini = QProgressBar()
        self.mini.setObjectName("mini")
        self.mini.setTextVisible(False)
        self.mini.setFixedSize(160, 6)
        lay.addWidget(self.mini)

        # task indicator
        self.lbl_task = QLabel("")
        self.lbl_task.setStyleSheet(
            f"color: {C_PRIMARY}; font-size: 11px; background: transparent;")
        lay.addWidget(self.lbl_task)

    def _mk_stat(self, lay: QHBoxLayout, color: str, key: str):
        hv = QHBoxLayout()
        hv.setSpacing(5)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background: {color}; border-radius: 3px;")
        hv.addWidget(dot)
        lbl = QLabel("")
        lbl.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 11px;"
            " background: transparent;")
        hv.addWidget(lbl)
        lay.addLayout(hv)
        return lbl

    def _set_text(self, lbl: QLabel, key: str, n: int, hidden: bool):
        if hidden:
            lbl.setText("")
        else:
            lbl.setText(f"<b>{_fmt(n)}</b> {TR(key)}")

    def update_project_stats(self, done: int, draft: int, empty: int,
                             total: int):
        """Сводка по всему проекту: готово / черновики / пусто + общий %."""
        hidden = total <= 0
        self._set_text(self.lbl_done, "sb_done", done, hidden)
        self._set_text(self.lbl_draft, "sb_draft", draft, hidden)
        self._set_text(self.lbl_empty, "sb_empty", empty, hidden)
        self.mini.setVisible(not hidden)
        self.lbl_pct.setVisible(not hidden)
        if total:
            self.mini.setMaximum(total)
            self.mini.setValue(done)
            self.lbl_pct.setText(f"{round(done / total * 100)}%")

    def set_provider(self, name: str):
        self.lbl_provider.setText(TR("status_provider", name=name) if name else "")

    def set_connected(self, connected: bool, backend: str = ""):
        if connected:
            suffix = f" ({backend})" if backend else ""
            self.lbl_connection.setText(f"Connected{suffix}")
            self.lbl_connection.setStyleSheet(
                f"color: {C_SUCCESS}; font-size: 11px; background: transparent;")
        else:
            self.lbl_connection.setText("")
            self.lbl_connection.setStyleSheet(
                f"color: {C_TEXT_SECONDARY}; font-size: 11px; background: transparent;")

    def set_task(self, text: str):
        self.lbl_task.setText(text)

    def clear_task(self):
        self.lbl_task.setText("")