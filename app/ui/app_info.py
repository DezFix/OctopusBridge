# -*- coding: utf-8 -*-
"""Диалог «О программе»: описание, теги движков, поддержка, чейнджлог.

Чейнджлог (Markdown) берётся с GitHub (CHANGELOG.md), при отсутствии
сети — из локального файла. Теги движков подтягиваются из реестра
app.engines.registry.MODULES — новый движок появится сам.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtNetwork import (QNetworkAccessManager, QNetworkReply,
                                QNetworkRequest)
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                                QTextBrowser, QVBoxLayout)

import app
from app.engines.registry import MODULES
from app.ui.i18n import TR
from app.ui.theme import (C_BORDER, C_CARD, C_PRIMARY, C_TEXT,
                           C_TEXT_SECONDARY, RADIUS_MD)

# Где искать локальный CHANGELOG.md относительно каталога приложения.
_CHANGELOG_NAME = "CHANGELOG.md"

# Страница поддержки проекта.
KO_FI_URL = "https://ko-fi.com/k_k"

# URL чейнджлога на GitHub (сырой Markdown).
CHANGELOG_URL = ("https://raw.githubusercontent.com/DezFix/OctopusBridge/"
                 "main/CHANGELOG.md")

# Палитра тегов движков: (фон, текст). Цвета перебираются по кругу.
_TAG_COLORS = [
    ("rgba(91, 143, 239, 0.16)", "#5b8fef"),    # синий
    ("rgba(57, 201, 143, 0.16)", "#39c98f"),    # зелёный
    ("rgba(240, 163, 94, 0.16)", "#f0a35e"),    # оранжевый
    ("rgba(199, 139, 240, 0.16)", "#c78bf0"),   # фиолетовый
    ("rgba(239, 91, 143, 0.16)", "#ef5b8f"),    # розовый
    ("rgba(91, 214, 239, 0.16)", "#5bd6ef"),    # голубой
]

# CSS для Markdown: тёмные цвета под тему приложения.
_MD_CSS = """
h1 { color: #ffffff; font-size: 17px; margin: 0 0 8px 0; }
h2 { color: #ffffff; font-size: 15px; margin: 10px 0 6px 0; }
h3 { color: #ffffff; font-size: 13.5px; margin: 8px 0 4px 0; }
p { color: #cfd3dd; font-size: 12.5px; margin: 4px 0; }
li { color: #cfd3dd; font-size: 12.5px; }
code { background: #232837; border-radius: 3px; padding: 1px 4px;
       color: #8fb7ff; font-size: 11.5px; }
pre { background: #232837; border-radius: 6px; padding: 8px;
      color: #cfd3dd; font-size: 11.5px; }
a { color: #5b8fef; text-decoration: none; }
blockquote { color: #8a90a0; border-left: 3px solid #39405a;
             padding-left: 8px; }
hr { border: none; border-top: 1px solid #39405a; }
"""


def changelog_path() -> str:
    """Путь к локальному CHANGELOG.md (исходники или распакованная сборка)."""
    candidates = [
        os.path.join(os.path.dirname(app.__file__), "..", _CHANGELOG_NAME),
        os.path.join(app.bundle_dir(), _CHANGELOG_NAME),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]


def _latest_md_section(md: str) -> str:
    """Возвращает самую свежую секцию '## [vX.Y.Z]' (Что нового)."""
    sections = re.split(r"(?m)^## ", md)
    for s in sections[1:]:
        s = s.strip()
        if re.match(r"\[?v?\d+\.\d+", s):
            return "# " + s
    return sections[1].strip() if len(sections) > 1 else md.strip()


def local_changelog_text() -> str:
    """Локальный чейнджлог (свежая секция) или пустая строка."""
    try:
        with open(changelog_path(), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    return _latest_md_section(text)


class AboutDialog(QDialog):
    """«О программе» — верх: описание, теги движков, поддержка; низ: чейнджлог."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TR("about_title"))
        self.setMinimumSize(540, 640)
        self.resize(580, 700)

        body = QVBoxLayout(self)
        body.setContentsMargins(24, 24, 24, 24)
        body.setSpacing(12)

        # ── иконка, название, версия, описание ──
        head = QHBoxLayout()
        head.setSpacing(14)

        app_icon = QLabel()
        ico = QIcon(app.icon_path())
        if not ico.isNull():
            app_icon.setPixmap(ico.pixmap(64, 64))
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

        # ── теги движков (из реестра, цвета по кругу) ──
        eng_lbl = QLabel(TR("about_engines"))
        eng_lbl.setStyleSheet(
            f"font-size: 10.5px; font-weight: 700; color: {C_TEXT_SECONDARY};")
        body.addWidget(eng_lbl)

        tags = QHBoxLayout()
        tags.setSpacing(6)
        seen: set[str] = set()
        for i, cls in enumerate(MODULES):
            title = getattr(cls, "title", cls.__name__)
            if not title or title in seen:
                continue
            seen.add(title)
            bg, fg = _TAG_COLORS[i % len(_TAG_COLORS)]
            tag = QLabel(title)
            tag.setStyleSheet(
                f"background: {bg}; color: {fg}; font-size: 11px;"
                "font-weight: 600; border-radius: 9px; padding: 4px 12px;")
            tags.addWidget(tag)
        tags.addStretch(1)
        body.addLayout(tags)

        # ── бесплатно + кнопка Ko-fi ──
        free_lbl = QLabel(TR("about_free"))
        free_lbl.setStyleSheet(
            f"font-size: 11px; color: {C_TEXT_SECONDARY};")
        body.addWidget(free_lbl)

        from PySide6.QtCore import Qt
        btn_kofi = QPushButton(TR("about_kofi"))
        btn_kofi.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_kofi.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(KO_FI_URL)))
        btn_kofi.setStyleSheet(
            "QPushButton { background: #ff5e5b; color: #ffffff;"
            " border: none; border-radius: 6px; padding: 7px 18px;"
            " font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background: #ff7560; }"
            "QPushButton:pressed { background: #e8524f; }")
        btn_kofi.setFixedWidth(230)
        body.addWidget(btn_kofi, 0, Qt.AlignmentFlag.AlignLeft)

        body.addSpacing(2)

        # ── чейнджлог: Markdown с GitHub ──
        ch_title = QLabel(TR("about_changelog"))
        ch_title.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {C_TEXT};")
        body.addWidget(ch_title)

        self.ch = QTextBrowser()
        self.ch.setOpenExternalLinks(True)
        self.ch.setStyleSheet(
            f"QTextBrowser {{ background: {C_CARD}; color: {C_TEXT}; "
            f"border: 1px solid {C_BORDER}; border-radius: {RADIUS_MD}px; }}")
        self.ch.document().setDocumentMargin(10)
        self.ch.document().setDefaultStyleSheet(_MD_CSS)
        self.ch.setMarkdown(local_changelog_text())
        body.addWidget(self.ch, 1)

        # ── кнопка закрытия ──
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_close = QPushButton(TR("about_close"))
        btn_close.setFixedWidth(110)
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_close)
        body.addLayout(buttons)

        self._net = QNetworkAccessManager(self)
        req = QNetworkRequest(QUrl(CHANGELOG_URL))
        req.setRawHeader(b"User-Agent", b"OctopusBridge")
        reply = self._net.get(req)
        reply.finished.connect(lambda: self._on_changelog(reply))

    def _on_changelog(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return  # остаётся локальный текст
        data = bytes(reply.readAll()).decode("utf-8", "replace")
        text = _latest_md_section(data) if data.strip() else ""
        if text:
            self.ch.setMarkdown(text)


def show_about(parent=None) -> None:
    AboutDialog(parent).exec()