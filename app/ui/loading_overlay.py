# -*- coding: utf-8 -*-
"""Overlay загрузки поверх главного окна: полупрозрачная подложка,
вращающийся спиннер, текст статуса и опциональная кнопка «Отмена».

Используется для длительных операций: запуск игры, извлечение текста,
«Перевести всё», ИИ-коррекция, открытие проекта.

Появление/скрытие — плавное (fade 150 мс); спиннер крутится только
пока оверлей виден (таймер останавливается в hideEvent).
"""
from __future__ import annotations

from PySide6.QtCore import (QAbstractAnimation, QPropertyAnimation, QTimer,
                            Qt)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from app.ui.theme import (C_BORDER, C_CARD, C_PRIMARY, C_TEXT,
                          C_TEXT_SECONDARY, RADIUS_MD)

_FADE_MS = 150


class Spinner(QWidget):
    """Спиннер: вращающаяся дуга (QPainter, ~60 FPS только пока виден)."""

    def __init__(self, parent=None, size: int = 44):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(16)

    def showEvent(self, event):  # noqa: N802 — переопределение Qt
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):  # noqa: N802 — переопределение Qt
        super().hideEvent(event)
        self._timer.stop()

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


class BusyLabel(QWidget):
    """Компактный индикатор «спиннер + текст» для встраивания в диалоги
    и вкладки (глоссарий, чит-имена, ping в настройках и т.п.).

    show(text) — запустить, hide()/stop() — скрыть. Скрыт по умолчанию.
    """

    def __init__(self, parent=None, size: int = 14):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.spinner = Spinner(self, size)
        self.spinner.setVisible(False)
        lay.addWidget(self.spinner)
        self.lbl = QLabel("")
        self.lbl.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 12px; background: transparent;")
        lay.addWidget(self.lbl)
        self.hide()

    def start(self, text: str = ""):
        self.lbl.setText(text)
        self.spinner.setVisible(True)
        self.show()

    def stop(self):
        self.hide()
        self.spinner.setVisible(False)


_Spinner = Spinner  # обратная совместимость


class LoadingOverlay(QWidget):
    """Полнооконный оверлей: спиннер + текст + (опц.) кнопка «Отмена».

    Родитель — центральный виджет главного окна; геометрия обновляется
    из MainWindow.resizeEvent (setGeometry). Поверх всех вкладок.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("loading_overlay")
        self._on_cancel = None
        self._anim: QPropertyAnimation | None = None
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
        row.addWidget(Spinner(card, 40))
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

    # ── fade-анимация ──
    def _fade_to(self, target: float, then=None):
        if self._anim is not None \
                and self._anim.state() != QAbstractAnimation.State.Stopped:
            self._anim.stop()
            try:
                self._anim.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(_FADE_MS)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(target)
        if then is not None:
            self._anim.finished.connect(then)
        self._anim.start()

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
        if self.isVisible():
            return  # уже показан — только обновили текст/кнопки
        self.setWindowOpacity(0.0)
        self.raise_()
        self.show()
        self._fade_to(1.0)

    def set_text(self, text: str):
        self.lbl_text.setText(text)

    def hide_loading(self):
        self._on_cancel = None
        if not self.isVisible():
            return
        self._fade_to(0.0, then=self.hide)

    def _cancel_clicked(self):
        cb, self._on_cancel = self._on_cancel, None
        if cb:
            self.hide()
            cb()
