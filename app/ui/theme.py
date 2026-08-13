# -*- coding: utf-8 -*-
"""Design system: palette, spacing, radius, typography, QSS.

Тёмная палитра из актуального дизайн-концепта (deep-blue night):
глубокий фон, сине-стальные панели, акцент 5b7fff, статусные пилюли.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QUrl
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (QApplication,
                                QLabel,
                                QWidget)

from app import bundle_dir

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
RADIUS_BTN = 8
RADIUS_LG = 10
RADIUS_XL = 14

SPACING_XS = 2
SPACING_SM = 4
SPACING_MD = 8
SPACING_LG = 12
SPACING_XL = 16
SPACING_XXL = 24

# Colors (dark, deep-blue night)
C_BG = "#17181f"
C_SURFACE = "#1f212b"
C_CARD = "#262834"
C_CARD_HOVER = "#2e3140"
C_BORDER = "#3a3d4f"
C_BORDER_LIGHT = "#2a2d3a"
C_PRIMARY = "#5b7fff"
C_PRIMARY_HOVER = "#6f8dff"
C_PRIMARY_PRESSED = "#4a6df2"
C_ACCENT = "#9d7bff"
C_SUCCESS = "#3fcf96"
C_WARNING = "#f0a93e"
C_ERROR = "#f0707d"
C_TEXT = "#e8eaf1"
C_TEXT_SECONDARY = "#aab1c4"
C_TEXT_DIM = "#757c94"
C_SIDEBAR_BG = "#14151c"
C_SIDEBAR_ACTIVE = "rgba(91, 127, 255, 0.18)"
C_SIDEBAR_HOVER = "rgba(91, 127, 255, 0.10)"
C_INPUT_BG = "#262834"
C_INPUT_BORDER = "#3a3d4f"
C_INPUT_FOCUS = "#5b7fff"

# Pill / status colors
C_TRACK = "#2a2d3a"
C_PILL_EMPTY_FG = "#757c94"
C_PILL_DRAFT = "#f0a93e"
C_PILL_DONE = "#39c98f"
C_PILL_BG_SOFT = "rgba(255,255,255,0.05)"

# Stepper / toolbar groups
C_GROUP_BG = "#262834"
C_GROUP_BORDER = "#2e3243"

# ======================================================================
#  QSS
# ======================================================================


def _asset_url(name: str) -> str:
    """file:// URL иконки из assets/ (рядом с exe/репозиторием)."""
    path = os.path.join(bundle_dir(), "assets", name)
    return QUrl.fromLocalFile(path).toString()


_COMBO_ARROW = _asset_url("chevron-down.png")
_SPIN_UP = _asset_url("chevron-up.png")
_SPIN_DOWN = _asset_url("chevron-down.png")

_QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE_MD};
}}

QWidget {{
    color: {C_TEXT};
    background-color: {C_BG};
}}

QWidget#page {{ background-color: {C_BG}; }}

/* ── Buttons ── */
QPushButton {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_BTN}px;
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
QPushButton:checked {{
    background: rgba(91, 127, 255, 0.16);
    border-color: {C_PRIMARY};
    color: {C_TEXT};
}}
QPushButton:checked:hover {{
    background: rgba(91, 127, 255, 0.24);
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

/* ── Menu ── */
QMenu {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 5px;
}}
QMenu::item {{
    padding: 6px 26px 6px 14px;
    border-radius: {RADIUS_MD}px;
    color: {C_TEXT};
}}
QMenu::item:selected {{
    background-color: {C_SIDEBAR_ACTIVE};
}}
QMenu::item:disabled {{
    color: {C_TEXT_DIM};
}}
QMenu::separator {{
    height: 1px;
    background: {C_BORDER_LIGHT};
    margin: 5px 8px;
}}
QMenu::indicator {{
    width: 14px;
    height: 14px;
}}

/* ── Toolbar buttons ── */
QPushButton#tool_btn {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_BTN}px;
    padding: 7px 14px;
    color: {C_TEXT_SECONDARY};
    font-weight: 500;
}}
QPushButton#tool_btn:hover {{
    color: {C_TEXT};
    border-color: {C_PRIMARY};
    background: {C_CARD_HOVER};
}}
QPushButton#tool_btn:pressed {{
    background: {C_PRIMARY_PRESSED};
}}
QPushButton[step="true"] {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_BTN}px;
    padding: 7px 14px;
    color: {C_TEXT_SECONDARY};
    font-weight: 600;
    text-align: left;
}}
QPushButton[step="true"]:hover {{
    background: {C_CARD_HOVER};
    border-color: {C_PRIMARY};
    color: {C_TEXT};
}}
QPushButton[step="true"][active="true"] {{
    background: {C_PRIMARY};
    border-color: {C_PRIMARY};
    color: #ffffff;
}}
QPushButton[step="true"]:disabled {{
    color: {C_TEXT_DIM};
}}
QPushButton[step="true"]:disabled:hover {{
    background: {C_CARD};
    color: {C_TEXT_DIM};
}}
QPushButton#view_btn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 5px 9px;
    color: {C_TEXT_DIM};
    font-weight: 600;
    font-size: {FONT_SIZE_SM};
}}
QPushButton#view_btn:hover {{
    color: {C_TEXT};
}}
QPushButton#view_btn[on="true"] {{
    background: {C_SURFACE};
    color: {C_TEXT};
}}
QToolButton#step {{
    background: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_BTN}px;
    padding: 7px 6px 7px 12px;
    color: {C_TEXT_SECONDARY};
    font-weight: 600;
    text-align: left;
}}
QToolButton#step:hover {{
    background: {C_CARD_HOVER};
    border-color: {C_PRIMARY};
    color: {C_TEXT};
}}
QToolButton#step[active="true"] {{
    background: {C_PRIMARY};
    border-color: {C_PRIMARY};
    color: #ffffff;
}}
QToolButton#step:disabled {{
    color: {C_TEXT_DIM};
}}
QToolButton#step::menu-button {{
    width: 16px;
    border-left: none;
    border-top-right-radius: {RADIUS_BTN}px;
    border-bottom-right-radius: {RADIUS_BTN}px;
}}
QToolButton#step::menu-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 4px solid {C_TEXT_SECONDARY};
}}
QToolButton#step[active="true"]::menu-arrow {{
    border-top-color: #ffffff;
}}
QComboBox#chip_filter {{
    background: transparent;
    border: 1px solid {C_BORDER_LIGHT};
    border-radius: {RADIUS_MD}px;
    padding: 5px 10px;
    color: {C_TEXT_SECONDARY};
    font-size: 12px;
}}
QComboBox#chip_filter:hover {{
    border-color: {C_PRIMARY};
    color: {C_TEXT};
}}
QLineEdit#file_search {{
    background: transparent;
    border: 1px solid {C_BORDER_LIGHT};
    border-radius: {RADIUS_MD}px;
    padding: 7px 10px;
    color: {C_TEXT};
    font-size: {FONT_SIZE_MD};
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
/* Редакторы ячеек таблиц (QLineEdit внутри QTableView): padding
   из правила выше съедает всю высоту строки (~30px) — контентная
   область становится 8px, и набираемый текст не виден. Свой стиль
   с минимальным отступом и подчёркнутой рамкой. */
QAbstractItemView QLineEdit {{
    padding: 0px 2px;
    border: 1px solid {C_PRIMARY};
    border-radius: 4px;
    background-color: {C_INPUT_BG};
    color: {C_TEXT};
    selection-background-color: {C_PRIMARY};
    selection-color: #ffffff;
}}
QAbstractItemView QLineEdit:focus {{
    border-color: {C_INPUT_FOCUS};
}}
/* То же для textarea-редакторов (колонка перевода) и комбобоксов
   в ячейках — текст не должен обрезаться высотой строки. */
QAbstractItemView QPlainTextEdit {{
    padding: 0px 2px;
    border: 1px solid {C_PRIMARY};
    border-radius: 4px;
    background-color: {C_INPUT_BG};
    color: {C_TEXT};
    selection-background-color: {C_PRIMARY};
    selection-color: #ffffff;
}}
QAbstractItemView QComboBox {{
    padding: 0px 2px;
    background-color: {C_INPUT_BG};
    color: {C_TEXT};
    border: 1px solid {C_PRIMARY};
    border-radius: 4px;
}}
QComboBox:hover {{
    border-color: {C_PRIMARY};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: url("{_COMBO_ARROW}");
    width: 12px;
    height: 12px;
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {C_CARD};
    border: 1px solid {C_BORDER};
    border-radius: {RADIUS_MD}px;
    padding: 4px;
    outline: none;
    selection-background-color: {C_SIDEBAR_ACTIVE};
    selection-color: {C_TEXT};
    color: {C_TEXT};
}}
QComboBox QAbstractItemView::item {{
    padding: 5px 8px;
    border-radius: {RADIUS_SM}px;
    min-height: 18px;
}}
QComboBox QAbstractItemView::item:hover {{
    background: {C_SIDEBAR_HOVER};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    border: none;
    background: transparent;
    width: 18px;
}}
QSpinBox::up-arrow {{
    image: url("{_SPIN_UP}");
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow {{
    image: url("{_SPIN_DOWN}");
    width: 10px;
    height: 10px;
}}

/* ── Lists / trees ── */
QListView, QTreeView {{
    background: transparent;
    border: none;
    outline: none;
}}
QListView::item, QTreeView::item {{
    border-radius: {RADIUS_MD}px;
    padding: 5px 10px;
    color: {C_TEXT_SECONDARY};
}}
QListView::item:hover, QTreeView::item:hover {{
    background: {C_SIDEBAR_HOVER};
    color: {C_TEXT};
}}
QListView::item:selected, QTreeView::item:selected {{
    background: {C_SIDEBAR_ACTIVE};
    color: {C_TEXT};
}}

/* ── Tables ── */
QTableWidget {{
    background-color: {C_SURFACE};
    border: 1px solid {C_BORDER_LIGHT};
    border-radius: {RADIUS_LG}px;
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
    border: 1px solid {C_BORDER_LIGHT};
    border-radius: {RADIUS_LG}px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: bold;
    color: {C_TEXT_SECONDARY};
    background: transparent;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {C_TEXT_SECONDARY};
    background: transparent;
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
    border-radius: 4px;
    background: {C_INPUT_BG};
}}
QCheckBox::indicator:hover {{
    border-color: {C_PRIMARY};
}}
QCheckBox::indicator:checked {{
    background: {C_PRIMARY};
    border-color: {C_PRIMARY};
}}
QCheckBox::indicator:disabled {{
    border-color: {C_BORDER_LIGHT};
    background: {C_SURFACE};
}}

/* ── Tab widgets: underline, VS Code style ── */
QTabWidget::pane {{
    border: none;
    background: {C_SURFACE};
}}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: {C_CARD};
    color: {C_TEXT_SECONDARY};
    padding: 7px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    margin: 8px 2px 0 2px;
    font-weight: 600;
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
QSplitter::handle:hover {{
    background: {C_PRIMARY};
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


# ======================================================================
#  Shared widgets / helpers
# ======================================================================

def section_label(text: str, color: str | None = None,
                  font_size: int = 11) -> QLabel:
    """Заголовок секции в стиле концепта (капс, приглушённый, полужирный)."""
    lbl = QLabel(text.upper())
    c = color or C_TEXT_DIM
    lbl.setStyleSheet(
        f"color: {c}; background: transparent; font-size: {font_size}px;"
        "font-weight: 700;")
    return lbl


def slide_in(widget: QWidget, direction: str = "left", duration: int = 250):
    """Animate a widget sliding in from direction ('left'|'right')."""
    from PySide6.QtCore import QPoint
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