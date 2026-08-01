# -*- coding: utf-8 -*-
"""Status bar at the bottom: provider, connection, tasks."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                                QSizePolicy, QWidget)

from app.ui.i18n import TR
from app.ui.theme import (C_BORDER_LIGHT, C_CARD, C_PRIMARY, C_SUCCESS,
                           C_TEXT, C_TEXT_SECONDARY, C_ERROR, RADIUS_MD)

_QSS_SB = f"""
QFrame#status_bar {{
    background-color: {C_CARD};
    border-top: 1px solid {C_BORDER_LIGHT};
}}
"""


class StatusBar(QFrame):
    """Compact bottom bar with provider, connection, and task info."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("status_bar")
        self.setStyleSheet(_QSS_SB)
        self.setFixedHeight(32)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 2, 12, 2)
        lay.setSpacing(20)

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

        # task indicator
        self.lbl_task = QLabel("")
        self.lbl_task.setStyleSheet(
            f"color: {C_PRIMARY}; font-size: 11px; background: transparent;")
        lay.addWidget(self.lbl_task)

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
