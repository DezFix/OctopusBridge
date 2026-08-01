# -*- coding: utf-8 -*-
"""Design system: palette, spacing, radius, typography, QSS."""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication,
                                QComboBox, QHeaderView, QLineEdit,
                                QPushButton, QSpinBox, QTabBar,
                                QTableWidget, QTextEdit, QToolTip,
                                QWidget)

# ======================================================================
#  Design tokens
# ======================================================================

FONT_FAMILY = '"Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'
FONT_SIZE_SM = "11px"
FONT_SIZE_MD = "13px"
FONT_SIZE_LG = "16px"
FONT_SIZE_XL = "20px"
FONT_SIZE_XXL = "28px"

RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 10
RADIUS_XL = 14

SPACING_XS = 2
SPACING_SM = 4
SPACING_MD = 8
SPACING_LG = 12
SPACING_XL = 16
SPACING_XXL = 24

# Colors
C_BG = "#1a1a22"
C_SURFACE = "#22222c"
C_CARD = "#2a2a36"
C_CARD_HOVER = "#303040"
C_BORDER = "#3a3a48"
C_BORDER_LIGHT = "#2e2e3c"
C_PRIMARY = "#5b8def"
C_PRIMARY_HOVER = "#4a7de0"
C_PRIMARY_PRESSED = "#3a6dd0"
C_ACCENT = "#a78bfa"
C_SUCCESS = "#34d399"
C_WARNING = "#fbbf24"
C_ERROR = "#f87171"
C_TEXT = "#e4e4ec"
C_TEXT_SECONDARY = "#8b8ba0"
C_TEXT_DIM = "#606070"
C_SIDEBAR_BG = "#16161e"
C_SIDEBAR_ACTIVE = "rgba(91, 141, 239, 0.15)"
C_SIDEBAR_HOVER = "rgba(91, 141, 239, 0.08)"
C_INPUT_BG = "#2a2a36"
C_INPUT_BORDER = "#3a3a48"
C_INPUT_FOCUS = "#5b8def"

# ======================================================================
#  QSS
# ======================================================================

_QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE_MD};
}}

QWidget {{
    color: {C_TEXT};
    background-color: {C_BG};
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px 14px;
    min-height: 20px;
    color: {C_TEXT};
}}
QPushButton:hover {{
    background-color: {C_CARD_HOVER};
    border-color: {C_PRIMARY};
}}
QPushButton:pressed {{
    background-color: {C_PRIMARY_PRESSED};
    border-color: {C_PRIMARY};
}}
QPushButton:disabled {{
    color: {C_TEXT_DIM};
    border-color: {C_BORDER_LIGHT};
    background-color: {C_SURFACE};
}}
QPushButton#accent {{
    background-color: {C_PRIMARY};
    border: none;
    color: #ffffff;
    font-weight: bold;
}}
QPushButton#accent:hover {{
    background-color: {C_PRIMARY_HOVER};
}}
QPushButton#accent:pressed {{
    background-color: {C_PRIMARY_PRESSED};
}}
QPushButton#danger {{
    background-color: {C_ERROR};
    border: none;
    color: #ffffff;
}}

/* ── Inputs ── */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {C_INPUT_BG};
    border: 1px solid {C_INPUT_BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 5px 8px;
    color: {C_TEXT};
    selection-background-color: {C_PRIMARY};
}}
QLineEdit:focus, QSpinBox:focus {{
    border-color: {C_INPUT_FOCUS};
}}
QComboBox::drop-down {{
    border: none;
    padding-right: 8px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C_TEXT_SECONDARY};
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 4px;
    selection-background-color: {C_SIDEBAR_ACTIVE};
    color: {C_TEXT};
}}

/* ── Tables ── */
QTableWidget {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER_LIGHT};
    border-radius: {RADIUS_MD}px;
    gridline-color: {C_BORDER_LIGHT};
    selection-background-color: {C_SIDEBAR_ACTIVE};
    selection-color: {C_TEXT};
    outline: none;
}}
QTableWidget::item {{
    padding: 4px 6px;
    border-bottom: 1px solid {C_BORDER_LIGHT};
}}
QTableWidget::item:selected {{
    background-color: {C_SIDEBAR_ACTIVE};
}}
QTableWidget::item:hover {{
    background-color: {C_CARD_HOVER};
}}
QHeaderView::section {{
    background-color: {C_CARD};
    color: {C_TEXT_SECONDARY};
    border: none;
    border-bottom: 2px solid {C_BORDER};
    border-right: 1px solid {C_BORDER_LIGHT};
    padding: 6px 8px;
    font-weight: bold;
    font-size: {FONT_SIZE_SM};
    text-transform: uppercase;
}}

/* ── Scroll bars ── */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {C_BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {C_TEXT_SECONDARY};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {C_BORDER};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {C_TEXT_SECONDARY};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Group boxes ── */
QGroupBox {{
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_MD}px;
    margin-top: 14px;
    padding: 14px 10px 10px 10px;
    font-weight: bold;
    color: {C_TEXT_SECONDARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {C_TEXT_SECONDARY};
}}

/* ── Progress bars ── */
QProgressBar {{
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_SM}px;
    text-align: center;
    background: {C_SURFACE};
    max-height: 18px;
    color: {C_TEXT};
    font-size: {FONT_SIZE_SM};
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {C_PRIMARY}, stop:1 {C_ACCENT});
    border-radius: {RADIUS_SM}px;
}}

/* ── Tool tips ── */
QToolTip {{
    background-color: {C_CARD};
    color: {C_TEXT};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 6px 10px;
    font-size: {FONT_SIZE_SM};
}}

/* ── Labels ── */
QLabel {{
    background: transparent;
    border: none;
}}

/* ── Check boxes ── */
QCheckBox {{
    spacing: 6px;
    color: {C_TEXT};
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {C_BORDER};
    border-radius: 3px;
    background: {C_INPUT_BG};
}}
QCheckBox::indicator:checked {{
    background: {C_PRIMARY};
    border-color: {C_PRIMARY};
}}
QCheckBox::indicator:hover {{
    border-color: {C_PRIMARY};
}}

/* ── Tab widgets (used inside tabs) ── */
QTabWidget::pane {{
    border: 1px solid {C_BORDER_LIGHT};
    border-radius: {RADIUS_MD}px;
    background: {C_SURFACE};
}}
QTabBar::tab {{
    background: {C_CARD};
    color: {C_TEXT_SECONDARY};
    padding: 6px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 1px;
}}
QTabBar::tab:selected {{
    color: {C_PRIMARY};
    border-bottom-color: {C_PRIMARY};
    background: {C_SURFACE};
}}
QTabBar::tab:hover:!selected {{
    color: {C_TEXT};
    background: {C_CARD_HOVER};
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {C_BORDER_LIGHT};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}

/* ── Plain text edit (log views) ── */
QPlainTextEdit {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER_LIGHT};
    border-radius: {RADIUS_MD}px;
    padding: 6px;
    color: {C_TEXT};
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: {FONT_SIZE_SM};
}}
"""


def apply_dark_theme(app: QApplication):
    app.setStyle("Fusion")

    p = QPalette()
    p.setColor(QPalette.Window, QColor(C_BG))
    p.setColor(QPalette.WindowText, QColor(C_TEXT))
    p.setColor(QPalette.Base, QColor(C_SURFACE))
    p.setColor(QPalette.AlternateBase, QColor(C_CARD))
    p.setColor(QPalette.ToolTipBase, QColor(C_CARD))
    p.setColor(QPalette.ToolTipText, QColor(C_TEXT))
    p.setColor(QPalette.Text, QColor(C_TEXT))
    p.setColor(QPalette.Button, QColor(C_CARD))
    p.setColor(QPalette.ButtonText, QColor(C_TEXT))
    p.setColor(QPalette.BrightText, QColor(C_ERROR))
    p.setColor(QPalette.Link, QColor(C_PRIMARY))
    p.setColor(QPalette.Highlight, QColor(C_PRIMARY))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.PlaceholderText, QColor(C_TEXT_DIM))

    disabled = QColor(C_TEXT_DIM)
    p.setColor(QPalette.Disabled, QPalette.Text, disabled)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, disabled)
    p.setColor(QPalette.Disabled, QPalette.WindowText, disabled)

    app.setPalette(p)
    app.setStyleSheet(_QSS)

    # Global font
    font = QFont()
    font.setFamily("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)


def apply_light_theme(app: QApplication):
    app.setStyle("Fusion")
    app.setPalette(app.style().standardPalette())
    app.setStyleSheet("")


def apply_theme(app: QApplication, name: str):
    if name == "light":
        apply_light_theme(app)
    else:
        apply_dark_theme(app)


def make_font(size_px: int = 13, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamily("Segoe UI")
    f.setPixelSize(size_px)
    f.setBold(bold)
    return f


def fade_in(widget: QWidget, duration: int = 200):
    """Animate opacity fade-in on a widget (sets graphics effect)."""
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity")
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.start()
    # prevent GC
    widget._fade_anim = anim
    widget._fade_eff = eff


def slide_in(widget: QWidget, direction: str = "left", duration: int = 250):
    """Animate a widget sliding in from direction ('left'|'right')."""
    from PySide6.QtCore import QRect, QPoint
    end_pos = widget.pos()
    if direction == "left":
        start_pos = QPoint(end_pos.x() - 40, end_pos.y())
    else:
        start_pos = QPoint(end_pos.x() + 40, end_pos.y())

    anim = QPropertyAnimation(widget, b"pos")
    anim.setDuration(duration)
    anim.setStartValue(start_pos)
    anim.setEndValue(end_pos)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.start()
    widget._slide_anim = anim
