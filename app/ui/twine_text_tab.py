"""Вкладка «Текст игры» (Twine): человекочитаемый текст пассажей.

Перевод игры делается в приложении (извлечение -> перевод -> новая
html-копия рядом с игрой). Здесь — просмотр текста, который реально
читает игрок: пассажи по порядку, код игры (макросы, переменные,
ссылки, картинки, скрипты) свёрнут в маркеры ⟦…⟧. Файлы игры
не меняются.
"""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.twine import parser
from app.ui.i18n import TR
from app.ui.icons import icon
from app.ui.theme import C_TEXT_SECONDARY


class TwineTextTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        bar = QHBoxLayout()
        self.lbl_title = QLabel(TR("twine_text_title"))
        bar.addWidget(self.lbl_title)
        bar.addStretch(1)
        self.lbl_info = QLabel("")
        bar.addWidget(self.lbl_info)
        self.btn_copy = QPushButton(TR("twine_text_copy"))
        self.btn_copy.setIcon(icon("document-text"))
        self.btn_copy.clicked.connect(self._copy)
        bar.addWidget(self.btn_copy)
        self.btn_json = QPushButton(TR("twine_text_json"))
        self.btn_json.setObjectName("tool_btn")
        self.btn_json.setIcon(icon("file-text", 14, C_TEXT_SECONDARY))
        self.btn_json.clicked.connect(self._save_json)
        bar.addWidget(self.btn_json)
        self.btn_refresh = QPushButton(TR("twine_text_refresh"))
        self.btn_refresh.setIcon(icon("arrows-clockwise"))
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.btn_refresh)
        lay.addLayout(bar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 10))
        lay.addWidget(self.view, 1)

    def refresh(self):
        p = self.main.project
        if not p:
            self.view.setPlainText(TR("twine_text_no_project"))
            self.lbl_info.setText("")
            return
        passages = parser.read_passages(p.game_dir)
        if not passages:
            self.view.setPlainText(TR("twine_text_empty"))
            self.lbl_info.setText("")
            return
        self.view.setPlainText(parser.format_passages(passages))
        self.lbl_info.setText(TR("twine_text_info", n=len(passages)))

    def _copy(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.view.toPlainText())

    def _save_json(self):
        from PySide6.QtWidgets import QMessageBox
        p = self.main.project
        if not p:
            QMessageBox.information(self, TR("err"),
                                    TR("twine_text_no_project"))
            return
        path = parser.write_story_json(p.game_dir)
        QMessageBox.information(
            self, TR("done"),
            TR("twine_text_json_saved", path=path))

    def on_project_opened(self):
        self.refresh()