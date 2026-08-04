# -*- coding: utf-8 -*-
"""Диалоги «О программе» и «Что нового», проверка обновлений.

Проверка обновлений идёт через GitHub Releases API. Пока репозиторий
не указан (GITHUB_REPO пуст), проверка отключена — кнопка в диалоге
«О программе» не показывается. Заполнить константу перед релизом.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from PySide6.QtCore import QSettings, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                                QPlainTextEdit, QPushButton, QVBoxLayout)

import app
from app.ui.icons import icon
from app.ui.i18n import TR
from app.ui.theme import (C_CARD, C_PRIMARY, C_TEXT, C_TEXT_SECONDARY,
                           RADIUS_MD, RADIUS_LG)

# GitHub-репозиторий вида "owner/repo". Пусто — проверка обновлений отключена.
GITHUB_REPO = ""

# Ключ QSettings, где хранится последняя просмотренная версия «Что нового».
_LAST_SEEN_KEY = "last_seen_version"

# Где искать CHANGELOG.md относительно каталога приложения.
_CHANGELOG_NAME = "CHANGELOG.md"


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


def _parse_version(v: str) -> tuple:
    m = re.search(r"(\d+(?:\.\d+)*)", v or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


class ChangelogDialog(QDialog):
    """«Что нового» — последняя секция CHANGELOG.md."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TR("changelog_title"))
        self.setMinimumSize(560, 420)

        body = QVBoxLayout(self)
        body.setContentsMargins(20, 20, 20, 20)
        body.setSpacing(12)

        title = QLabel(TR("changelog_title"))
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {C_TEXT};")

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(last_changelog_text())
        self.text.setStyleSheet(
            f"QPlainTextEdit {{ background: {C_CARD}; color: {C_TEXT}; "
            f"border: 1px solid #3a3a48; border-radius: {RADIUS_MD}px; "
            f"font-size: 12px; padding: 8px; }}")

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_close = QPushButton(TR("about_close"))
        btn_close.setFixedWidth(110)
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_close)

        body.addWidget(title)
        body.addWidget(self.text, 1)
        body.addLayout(buttons)


class AboutDialog(QDialog):
    """«О программе» — версия, движки, обновления."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TR("about_title"))
        self.setFixedWidth(420)

        body = QVBoxLayout(self)
        body.setContentsMargins(24, 24, 24, 24)
        body.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(14)

        app_icon = QLabel()
        app_icon.setPixmap(icon("tray", 44, C_PRIMARY).pixmap(44, 44))
        head.addWidget(app_icon)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        name = QLabel("OctopusBridge")
        name.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {C_TEXT};")
        version = QLabel(TR("about_version", v=app.__version__))
        version.setStyleSheet(
            f"font-size: 12px; color: {C_TEXT_SECONDARY};")
        texts.addWidget(name)
        texts.addWidget(version)
        head.addLayout(texts)
        head.addStretch(1)
        body.addLayout(head)

        body.addSpacing(6)

        engines = QLabel(TR("about_engines"))
        engines.setStyleSheet(
            f"font-size: 12px; color: {C_TEXT_SECONDARY};")
        engines_list = QLabel(TR("about_engines_list"))
        engines_list.setWordWrap(True)
        engines_list.setStyleSheet(f"font-size: 13px; color: {C_TEXT};")
        body.addWidget(engines)
        body.addWidget(engines_list)

        body.addSpacing(10)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        if GITHUB_REPO:
            btn_updates = QPushButton(TR("about_check_updates"))
            btn_updates.setFixedWidth(160)
            btn_updates.clicked.connect(lambda: check_updates(self))
            buttons.addWidget(btn_updates)
        btn_close = QPushButton(TR("about_close"))
        btn_close.setFixedWidth(110)
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_close)
        body.addLayout(buttons)


class _UpdateChecker(QThread):
    """Проверка последнего релиза через GitHub Releases API."""

    found = Signal(str, str)  # tag_name, html_url

    def __init__(self, repo: str, parent=None):
        super().__init__(parent)
        self.repo = repo

    def run(self):
        try:
            url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            req = urllib.request.Request(
                url, headers={"User-Agent": "OctopusBridge"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.load(r)
            tag = data.get("tag_name", "") if isinstance(data, dict) else ""
            html = data.get("html_url", "") if isinstance(data, dict) else ""
            if tag:
                self.found.emit(tag, html)
        except Exception:
            pass


def check_updates(parent=None, silent: bool = True):
    """Проверка обновлений. Без GITHUB_REPO — тихо выходит."""
    if not GITHUB_REPO:
        return
    dialog = parent if parent is not None else None
    worker = _UpdateChecker(GITHUB_REPO, dialog)
    timer = QTimer()
    timer.setSingleShot(True)

    def on_found(tag: str, url: str):
        timer.stop()
        if _parse_version(tag) > _parse_version(app.__version__):
            ret = QMessageBox.question(
                dialog,
                TR("updates_title"),
                TR("updates_msg", v=tag.lstrip("v")),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if ret == QMessageBox.StandardButton.Yes and url:
                QDesktopServices.openUrl(QUrl(url))
        elif not silent:
            QMessageBox.information(dialog, TR("updates_title"),
                                    TR("updates_none"))

    def on_timeout():
        worker.quit()
        worker.wait(2000)
        if not silent:
            QMessageBox.information(dialog, TR("updates_title"),
                                    TR("updates_check_failed"))

    worker.found.connect(on_found)
    worker.finished.connect(worker.deleteLater)
    timer.timeout.connect(on_timeout)
    timer.start(15000)
    worker.start()


def maybe_show_changelog(main) -> None:
    """Показывает «Что нового», если версия отличается от просмотренной.

    Вызывать при старте приложения (после построения окна).
    """
    if not os.path.isfile(changelog_path()):
        return
    settings = QSettings("OctopusBridge", "OctopusBridge")
    if settings.value(_LAST_SEEN_KEY, "") == app.__version__:
        return
    settings.setValue(_LAST_SEEN_KEY, app.__version__)
    dialog = ChangelogDialog(main)
    QTimer.singleShot(120, dialog.show)


def show_about(parent=None) -> None:
    AboutDialog(parent).exec()
