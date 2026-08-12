# -*- coding: utf-8 -*-
"""Диалог «О программе»: описание, движки, поддержка проекта, чейнджлог."""
from __future__ import annotations

import os
import re

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel,
                                QPlainTextEdit, QPushButton, QVBoxLayout)

import app
from app.ui.i18n import TR
from app.ui.theme import (C_BORDER, C_CARD, C_PRIMARY, C_TEXT,
                           C_TEXT_SECONDARY, RADIUS_MD)

# Где искать CHANGELOG.md относительно каталога приложения.
_CHANGELOG_NAME = "CHANGELOG.md"

# Страница поддержки проекта.
KO_FI_URL = "https://ko-fi.com/k_k"


def changelog_path() -> str:
    return os.path.join(os.path.dirname(app.__file__), "..", _CHANGELOG_NAME)


def last_changelog_text() -> str:
    """Текст CHANGELOG.md (последняя секция) или пустая строка."""
    try:
        with open(changelog_path(), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    sections = re.split(r"(?m)^#+ ", text)
    if len(sections) > 1:
        return "# " + sections[1].strip()
    return text.strip()


class AboutDialog(QDialog):
    """«О программе» — верхний блок: описание и поддержка; нижний: чейнджлог."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TR("about_title"))
        self.setMinimumSize(520, 620)
        self.resize(560, 680)

        body = QVBoxLayout(self)
        body.setContentsMargins(24, 24, 24, 24)
        body.setSpacing(12)

        # ── верхний блок: иконка, название, версия, описание ──
        head = QHBoxLayout()
        head.setSpacing(14)

        app_icon = QLabel()
        ico = QIcon(app.icon_path())
        if not ico.isNull():
            app_icon.setPixmap(ico.pixmap(64, 64))
        else:
            app_icon.setPixmap(QPixmap(64, 64))
        app_icon.setFixedSize(64, 64)
        head.addWidget(app_icon)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        name = QLabel("OctopusBridge")
        name.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {C_TEXT};")
        version = QLabel(TR("about_version", v=app.__version__))
        version.setStyleSheet(
            f"font-size: 12px; color: {C_TEXT_SECONDARY};")
        desc = QLabel(TR("about_desc"))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {C_TEXT};")
        texts.addWidget(name)
        texts.addWidget(version)
        texts.addWidget(desc)
        head.addLayout(texts, 1)
        body.addLayout(head)

        support = QLabel(TR("about_support", url=KO_FI_URL))
        support.setWordWrap(True)
        support.setOpenExternalLinks(True)
        support.setStyleSheet(
            f"font-size: 12px; color: {C_TEXT};"
            "a { color: #5b8fef; text-decoration: none; }")
        body.addWidget(support)

        body.addSpacing(4)

        # ── нижний блок: чейнджлог ──
        ch_title = QLabel(TR("about_changelog"))
        ch_title.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {C_TEXT};")
        body.addWidget(ch_title)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(last_changelog_text())
        self.text.setStyleSheet(
            f"QPlainTextEdit {{ background: {C_CARD}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: {RADIUS_MD}px; "
            f"font-size: 12px; padding: 8px; }}")
        body.addWidget(self.text, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_close = QPushButton(TR("about_close"))
        btn_close.setFixedWidth(110)
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_close)
        body.addLayout(buttons)


def show_about(parent=None) -> None:
    AboutDialog(parent).exec()
