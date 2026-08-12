# -*- coding: utf-8 -*-
"""Диалог выбора языка перевода для многоязычных игр (Ren'Py tl/<lang>).

Показывается при открытии проекта, если найдено несколько языков.
Пользователь выбирает ОДИН язык — переводим только его текст,
иначе одни и те же строки дублируются по числу языков.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox,
                               QLabel, QRadioButton, QVBoxLayout)

from app.ui.i18n import TR


class LangPickDialog(QDialog):
    """Выбор одного языка из списка (или «все языки» — старый режим).

    selected_lang: str | None — выбранный язык или None (все языки),
    если диалог принят; при отмене остаётся прежнее значение проекта.
    """

    def __init__(self, langs: list[str], current: str | None,
                 parent=None):
        super().__init__(parent)
        self.selected_lang = None
        self._langs = langs
        self.setWindowTitle(TR("lang_dialog_title"))
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)

        text = QLabel(TR("lang_dialog_text").format(
            langs=", ".join(langs)))
        text.setWordWrap(True)
        lay.addWidget(text)

        group = QButtonGroup(self)
        radios: list[QRadioButton] = []
        for lang in langs:
            rb = QRadioButton(lang.capitalize())
            group.addButton(rb)
            radios.append(rb)
            lay.addWidget(rb)
        rb_all = QRadioButton(TR("lang_dialog_all"))
        group.addButton(rb_all)
        lay.addWidget(rb_all)

        if current in langs:
            radios[langs.index(current)].setChecked(True)
        elif current is None:
            rb_all.setChecked(True)
        elif radios:
            radios[0].setChecked(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok
                                   | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._radios = radios
        self._rb_all = rb_all

    def _accept(self):
        for i, rb in enumerate(self._radios):
            if rb.isChecked():
                self.selected_lang = self._langs[i]
                break
        if self._rb_all.isChecked():
            self.selected_lang = None
        self.accept()