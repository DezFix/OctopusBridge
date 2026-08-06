# -*- coding: utf-8 -*-
"""Вкладка «Проекты»: список последних проектов.

Видна только в welcome-режиме (нет открытой игры): при открытии
проекта main_window скрывает вкладку, при возврате на главную —
показывает снова.

Карточка проекта: иконка игры, название, путь, бейдж движка,
дата последнего открытия и кнопка «открыть».
"""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                                QMessageBox, QPushButton, QVBoxLayout,
                                QWidget)

import app as app_paths
from app.ui.i18n import TR
from app.ui.icons import icon
from app.ui.theme import (C_BORDER, C_CARD, C_CARD_HOVER, C_PRIMARY,
                          C_SURFACE, C_TEXT, C_TEXT_DIM, C_TEXT_SECONDARY,
                          RADIUS_LG, RADIUS_MD)

_ENGINE_COLORS = {
    "mz": "#43a047",
    "mv": "#43a047",
    "renpy": "#8e24aa",
    "twine": "#fb8c00",
    "tyrano": "#e53935",
    "ai": "#e53935",
}

_ENGINE_LOGOS = {
    "mz": "rpgmaker-mv.svg",
    "mv": "rpgmaker-mv.svg",
    "renpy": "renpy.svg",
    "twine": "twine.svg",
    "tyrano": "tyrano.svg",
}


def _engine_pixmap(engine: str, size: int = 44):
    fname = _ENGINE_LOGOS.get(engine)
    if not fname:
        return None
    path = os.path.join(app_paths.bundle_dir(), "app", "assets", fname)
    if not os.path.isfile(path):
        return None
    from PySide6.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(path)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    return pm


class ProjectsTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setAcceptDrops(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 20, 28, 20)
        lay.setSpacing(6)

        # ── header: title + add game ──
        top = QHBoxLayout()
        title = QLabel(TR("tab_projects"))
        title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {C_TEXT}; "
            f"background: transparent;")
        top.addWidget(title)
        top.addStretch(1)
        self.btn_clear = QPushButton(TR("projects_clear"))
        self.btn_clear.setIcon(icon("trash", 16))
        self.btn_clear.setMinimumHeight(34)
        self.btn_clear.setToolTip(TR("projects_clear"))
        self.btn_clear.clicked.connect(self._clear_all)
        top.addWidget(self.btn_clear)
        btn_add = QPushButton(TR("projects_add"))
        btn_add.setObjectName("accent")
        btn_add.setIcon(icon("plus", 16))
        btn_add.setMinimumHeight(34)
        btn_add.clicked.connect(self._browse)
        top.addWidget(btn_add)
        lay.addLayout(top)

        subtitle = QLabel(TR("projects_subtitle"))
        subtitle.setStyleSheet(
            f"font-size: 12px; color: {C_TEXT_SECONDARY}; "
            f"background: transparent;")
        lay.addWidget(subtitle)

        lay.addSpacing(8)

        self._recent_lay = QVBoxLayout()
        self._recent_lay.setSpacing(8)
        lay.addLayout(self._recent_lay)
        lay.addStretch(1)

        self._rebuild()

    # ── список проектов ──
    def _rebuild(self):
        self._clear_layout(self._recent_lay)

        recent = self.main._recent_list()
        self.btn_clear.setEnabled(bool(recent))
        if not recent:
            empty = QWidget()
            empty.setStyleSheet("background: transparent;")
            elay = QVBoxLayout(empty)
            elay.setContentsMargins(24, 24, 24, 24)
            elay.addStretch(1)
            lbl_t = QLabel(TR("projects_empty_title"))
            lbl_t.setAlignment(Qt.AlignCenter)
            lbl_t.setStyleSheet(
                f"font-size: 16px; font-weight: bold; color: {C_TEXT}; "
                f"background: transparent;")
            elay.addWidget(lbl_t)
            elay.addStretch(1)
            self._recent_lay.addWidget(empty)
            return

        for proj in recent:
            card = self._make_project_card(proj)
            self._recent_lay.addWidget(card)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            sub = item.layout()
            if sub:
                self._clear_layout(sub)

    # ── карточка проекта ──
    def _make_project_card(self, proj: dict) -> QFrame:
        path = proj.get("path", "")
        card = QFrame()
        card.setCursor(Qt.PointingHandCursor)
        card.setMinimumHeight(64)
        card.setMaximumHeight(72)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {C_CARD};
                border: 1px solid transparent;
                border-radius: {RADIUS_LG}px;
            }}
            QFrame:hover {{
                background-color: {C_CARD_HOVER};
                border-color: {C_PRIMARY};
            }}
        """)
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, p=path: self._show_project_menu(p, pos, card))

        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)

        # иконка игры (лого движка, если есть)
        ic = QLabel()
        ic.setFixedSize(44, 44)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(
            f"background: {C_SURFACE}; border-radius: {RADIUS_MD}px;")
        logo = _engine_pixmap(proj.get("engine", ""))
        if logo is not None:
            ic.setPixmap(logo)
        else:
            ic.setPixmap(icon("gamepad", 24, "#5b8def").pixmap(24, 24))
        lay.addWidget(ic)

        # имя + путь
        info = QVBoxLayout()
        info.setSpacing(2)
        name = QLabel(proj.get("name", "?"))
        name.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {C_TEXT}; "
            f"background: transparent; border: none;")
        info.addWidget(name)
        path_label = QLabel(path)
        path_label.setStyleSheet(
            f"font-size: 11px; color: {C_TEXT_SECONDARY}; "
            f"background: transparent; border: none;")
        path_label.setToolTip(path)
        info.addWidget(path_label)
        lay.addLayout(info, 1)

        # бейдж движка
        eng = proj.get("engine", "")
        eng_color = _ENGINE_COLORS.get(eng, C_PRIMARY)
        engine = QLabel(eng.upper() if eng else "?")
        engine.setStyleSheet(
            f"font-size: 10px; color: {eng_color}; "
            f"background: transparent; border: none; padding: 2px 8px; "
            f"border: 1px solid {eng_color}; border-radius: 4px;")
        lay.addWidget(engine)

        # дата
        ts = proj.get("ts", 0)
        if ts:
            date = QLabel(time.strftime("%d.%m.%Y", time.localtime(ts)))
            date.setStyleSheet(
                f"font-size: 11px; color: {C_TEXT_DIM}; "
                f"background: transparent; border: none;")
            lay.addWidget(date)

        # кнопка: открыть папку в проводнике
        btn_dir = QPushButton("")
        btn_dir.setIcon(icon("folder-open", 16, "#8899aa"))
        btn_dir.setFixedSize(34, 34)
        btn_dir.setCursor(Qt.PointingHandCursor)
        btn_dir.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid "
            f"{C_TEXT_DIM}; border-radius: {RADIUS_MD}px; }}"
            f"QPushButton:hover {{ border-color: {C_PRIMARY}; "
            f"background: {C_SURFACE}; }}")
        btn_dir.setToolTip(TR("projects_open_folder"))
        btn_dir.clicked.connect(lambda _=False, p=path: self._open_folder(p))
        lay.addWidget(btn_dir)

        # кнопка открыть
        btn_open = QPushButton("")
        btn_open.setIcon(icon("arrow-right", 16, "#8899aa"))
        btn_open.setFixedSize(34, 34)
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid "
            f"{C_TEXT_DIM}; border-radius: {RADIUS_MD}px; }}"
            f"QPushButton:hover {{ border-color: {C_PRIMARY}; "
            f"background: {C_SURFACE}; }}")
        btn_open.setToolTip(TR("welcome_open"))
        btn_open.clicked.connect(lambda _=False, p=path: self._open_recent(p))
        lay.addWidget(btn_open)

        card.mousePressEvent = \
            lambda e, p=path: self._open_recent(p) \
            if e.button() == Qt.LeftButton else None
        return card

    # ── контекстное меню ──
    def _show_project_menu(self, path: str, pos, card: QFrame):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {C_CARD}; border: 1px solid {C_PRIMARY}; "
            f"border-radius: 6px; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 20px; color: {C_TEXT}; }}"
            f"QMenu::item:selected {{ background: {C_PRIMARY}; color: #fff; }}")
        act_open = menu.addAction(TR("welcome_open"))
        act_folder = menu.addAction(TR("projects_open_folder"))
        act_rename = menu.addAction(TR("welcome_edit_name"))
        act_del = menu.addAction(TR("welcome_remove"))
        action = menu.exec(card.mapToGlobal(pos))
        if action == act_open:
            self._open_recent(path)
        elif action == act_folder:
            self._open_folder(path)
        elif action == act_rename:
            self._rename_project(path)
        elif action == act_del:
            self._remove_project(path)

    # ── drag & drop: открыть игру, не переключаясь на главную ──
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        event.accept()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.main.welcome_tab.open_path(urls[0].toLocalFile())

    # ── действия ──
    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, TR("side_home"),
                                             os.getcwd())
        if d:
            self.main.welcome_tab.open_path(d)

    def _open_folder(self, path: str):
        if not os.path.isdir(path):
            QMessageBox.warning(self, TR("err"),
                                f"Folder not found:\n{path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except OSError:
            QMessageBox.warning(self, TR("err"),
                                f"Can't open folder:\n{path}")

    def _open_recent(self, path: str):
        if not os.path.isdir(path):
            QMessageBox.warning(self, TR("err"),
                                f"Folder not found:\n{path}")
            self.main.remove_recent(path)
            self._rebuild()
            return
        self.main.welcome_tab.open_path(path)

    def _rename_project(self, path: str):
        from PySide6.QtWidgets import QInputDialog
        recent = self.main._recent_list()
        old = next((r.get("name", "") for r in recent
                    if r.get("path") == path), "")
        new, ok = QInputDialog.getText(
            self, TR("welcome_edit_name"),
            TR("welcome_new_name"), text=old)
        if ok and new.strip() and new.strip() != old:
            self.main._rename_recent(path, new.strip())
            self._rebuild()

    def _remove_project(self, path: str):
        if QMessageBox.question(
                self, TR("welcome_remove"),
                TR("welcome_remove_confirm")) == QMessageBox.Yes:
            self.main.remove_recent(path)
            self._rebuild()

    def _clear_all(self):
        if QMessageBox.question(
                self, TR("projects_clear"),
                TR("projects_clear_confirm")) == QMessageBox.Yes:
            self.main._clear_recent()
            self._rebuild()
