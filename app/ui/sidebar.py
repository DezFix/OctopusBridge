# -*- coding: utf-8 -*-
"""Sidebar navigation: collapsible rail with engine-aware items."""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, Signal,
                             QTimer)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                                QSizePolicy, QVBoxLayout, QWidget)

from app.ui.theme import (C_PRIMARY, C_SIDEBAR_ACTIVE, C_SIDEBAR_BG,
                           C_SIDEBAR_HOVER, C_TEXT, C_TEXT_SECONDARY,
                           C_BORDER_LIGHT, RADIUS_MD)

_SIDEBAR_W = 200
_SIDEBAR_W_COLLAPSED = 56

_QSS_SIDEBAR = f"""
QFrame#sidebar {{
    background-color: {C_SIDEBAR_BG};
    border-right: 1px solid {C_BORDER_LIGHT};
}}
QPushButton.nav-btn {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_MD}px;
    padding: 8px 12px;
    text-align: left;
    color: {C_TEXT_SECONDARY};
    font-size: 13px;
}}
QPushButton.nav-btn:hover {{
    background-color: {C_SIDEBAR_HOVER};
    color: {C_TEXT};
}}
QPushButton.nav-btn[active="true"] {{
    background-color: {C_SIDEBAR_ACTIVE};
    color: {C_PRIMARY};
    font-weight: bold;
}}
"""


class SideBar(QWidget):
    """Collapsible sidebar with navigation buttons."""
    tab_clicked = Signal(str)  # emits role string

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar_frame")
        self.setStyleSheet(_QSS_SIDEBAR)
        self.setFixedWidth(_SIDEBAR_W)
        self._collapsed = False

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 10, 6, 10)
        root.setSpacing(0)

        self._inner = QVBoxLayout()
        self._inner.setContentsMargins(0, 0, 0, 0)
        self._inner.setSpacing(2)
        root.addLayout(self._inner)

        # brand
        self._brand = QLabel("OB")
        self._brand.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {C_PRIMARY}; "
            f"padding: 4px 8px 10px 8px; background: transparent;")
        self._brand.setAlignment(Qt.AlignCenter)
        self._inner.addWidget(self._brand)

        # nav buttons
        self._buttons: dict[str, QPushButton] = {}
        self._inner.addStretch(1)

        # collapse toggle at bottom
        self._inner.addSpacing(8)
        self._collapse_btn = QPushButton("«")
        self._collapse_btn.setFixedHeight(32)
        self._collapse_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; "
            f"color: {C_TEXT_SECONDARY}; font-size: 14px; "
            f"border-radius: {RADIUS_MD}px; padding: 4px; }}"
            f"QPushButton:hover {{ color: {C_TEXT}; }}")
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        self._inner.addWidget(self._collapse_btn)

    def add_nav_button(self, role: str, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("class", "nav-btn")
        btn.setProperty("active", False)
        btn.setProperty("role", role)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.tab_clicked.emit(role))
        self._buttons[role] = btn
        # insert before the stretch
        idx = self._inner.count() - 2  # before stretch
        self._inner.insertWidget(idx, btn)
        return btn

    def add_separator(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(
            f"background: {C_BORDER_LIGHT}; max-height: 1px; "
            f"margin: 4px 8px;")
        idx = self._inner.count() - 2
        self._inner.insertWidget(idx, line)

    def set_active(self, role: str):
        for r, btn in self._buttons.items():
            active = (r == role)
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_visible_role(self, role: str, visible: bool):
        if role in self._buttons:
            self._buttons[role].setVisible(visible)

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        w = _SIDEBAR_W_COLLAPSED if self._collapsed else _SIDEBAR_W

        anim = QPropertyAnimation(self, b"maximumWidth")
        anim.setDuration(200)
        anim.setEndValue(w)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._anim_width = anim

        anim2 = QPropertyAnimation(self, b"minimumWidth")
        anim2.setDuration(200)
        anim2.setEndValue(w)
        anim2.setEasingCurve(QEasingCurve.OutCubic)
        anim2.start()
        self._anim_width2 = anim2

        self._brand.setText("" if self._collapsed else "OB")
        self._collapse_btn.setText("" if self._collapsed else "«")
        for btn in self._buttons.values():
            if self._collapsed:
                btn.setText("")
            else:
                btn.setText(btn.property("role").replace("_", " ").title()
                            if btn.property("role") else "")

    def refresh_labels(self, labels: dict[str, str]):
        """Update button labels from i18n dict."""
        if self._collapsed:
            return
        for role, text in labels.items():
            if role in self._buttons:
                self._buttons[role].setText(text)
