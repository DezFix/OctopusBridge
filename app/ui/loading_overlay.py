# -*- coding: utf-8 -*-
"""Overlay загрузки поверх главного окна: полупрозрачная подложка,
вращающийся спиннер, текст статуса и опциональная кнопка «Отмена».

Используется для длительных операций: запуск игры, извлечение текста,
«Перевести всё», ИИ-коррекция, открытие проекта.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from app.ui.theme import (C_BORDER, C_CARD, C_PRIMARY, C_TEXT,
                          C_TEXT_SECONDARY, RADIUS_MD)


class _Spinner(QWidget):
    """Спиннер: вращающаяся дуга (QPainter, ~60 FPS)."""

    def __init__(self, parent=None, size: int = 44):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _tick(self):
        self._angle = (self._angle + 7) % 360
        self.update()

    def paintEvent(self, event):  # noqa: N802 — переопределение Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        pen = self._pen(rect)
        p.setPen(pen)
        p.drawArc(rect, -self._angle * 16, 240 * 16)
        p.end()

    def _pen(self, rect):
        from PySide6.QtGui import QPen
        pen = QPen(QColor(C_PRIMARY))
        pen.setWidth(max(3, rect.width() // 9))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen


class LoadingOverlay(QWidget):
    """Полнооконный оверлей: спиннер + текст + (опц.) кнопка «Отмена».

    Родитель — центральный виджет главного окна; геометрия обновляется
    из MainWindow.resizeEvent (setGeometry). Поверх всех вкладок.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("loading_overlay")
        self._on_cancel = None
        self.hide()

        # подложка: лёгкое затемнение всего окна
        self._bg = QFrame(self)
        self._bg.setStyleSheet("background-color: rgba(15, 15, 20, 190);")

        # карточка по центру
        card = QFrame(self._bg)
        card.setStyleSheet(
            f"background-color: {C_CARD};"
            f"border: 1px solid {C_BORDER};"
            f"border-radius: {RADIUS_MD}px;")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(36, 28, 36, 28)
        card_lay.setSpacing(16)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(_Spinner(card, 40))
        self.lbl_text = QLabel("")
        self.lbl_text.setWordWrap(True)
        self.lbl_text.setStyleSheet(
            f"color: {C_TEXT}; font-size: 13px; background: transparent;")
        row.addWidget(self.lbl_text, 1)
        card_lay.addLayout(row)

        self.btn_cancel = QPushButton("")
        self.btn_cancel.setObjectName("loading_cancel")
        self.btn_cancel.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; background: transparent;"
            "border: none; font-size: 12px; padding: 2px;")
        self.btn_cancel.clicked.connect(self._cancel_clicked)
        card_lay.addWidget(self.btn_cancel, 0, Qt.AlignmentFlag.AlignRight)

        # карточка по центру подложки
        bg_lay = QVBoxLayout(self._bg)
        bg_lay.setContentsMargins(0, 0, 0, 0)
        bg_lay.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._bg)

    def show_loading(self, text: str = "", cancel_text: str = "",
                     on_cancel=None):
        """Показать оверлей. cancel_text пуст — без кнопки «Отмена»."""
        self.lbl_text.setText(text)
        self._on_cancel = on_cancel
        if cancel_text and on_cancel:
            self.btn_cancel.setText(cancel_text)
            self.btn_cancel.setVisible(True)
        else:
            self.btn_cancel.setVisible(False)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

    def set_text(self, text: str):
        self.lbl_text.setText(text)

    def hide_loading(self):
        self._on_cancel = None
        self.hide()

    def is_loading(self) -> bool:
        return self.isVisible()

    def _cancel_clicked(self):
        cb, self._on_cancel = self._on_cancel, None
        if cb:
            self.hide()
            cb()
