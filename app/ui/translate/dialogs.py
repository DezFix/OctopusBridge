# -*- coding: utf-8 -*-
"""Диалоги вкладки перевода: выбор режима перевода.

Раньше жили в app/ui/translate_tab.py.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout)

from app.ui.i18n import TR
from app.ui.theme import AnimatedComboBox


class _ModeOption(QFrame):
    """Кликабельная плитка выбора режима: заголовок + описание.
    Подсвечивается рамкой/фоном при выборе (QSS #mode_option)."""

    clicked = Signal()

    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent)
        self.setObjectName("mode_option")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(58)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(3)
        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(
            "background: transparent; color: #e8eaf1; font-weight: 600;")
        lbl_d = QLabel(desc)
        lbl_d.setStyleSheet(
            "background: transparent; color: #aab1c4; font-size: 11px;")
        lbl_d.setWordWrap(True)
        lay.addWidget(lbl_t)
        lay.addWidget(lbl_d)

    def set_selected(self, on: bool):
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def is_selected(self) -> bool:
        return self.property("selected") is True

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _TranslateDialog(QDialog):
    """Выбор параметров перевода: язык (весь текст или один официальный),
    языки оригинала (какие гнать в движок, остальные не трогаем)
    и режим (только непереведённое / всё заново). Открывается по клику
    на кнопку «Перевести» вместо выпадающего меню."""

    def __init__(self, langs: list[str], current: str | None, parent=None,
                 src_groups: list[tuple[str | None, int]] | None = None):
        super().__init__(parent)
        self.setWindowTitle(TR("tr_translate"))
        self.setModal(True)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # Старый дропдаун «Язык игры» — только для Ren'Py (официальные
        # tl-языки). У остальных движков там один пункт «Весь текст» —
        # прячем, чтобы не занимал место.
        real_langs = [lang for lang in (langs or [])
                      if lang and lang != "None"]
        self.cb_lang = AnimatedComboBox()
        if real_langs:
            lay.addWidget(QLabel(TR("tr_translate_lang")))
            self.cb_lang.addItem(TR("tr_lang_all"), None)
            for lang in real_langs:
                self.cb_lang.addItem(lang, lang)
            idx = self.cb_lang.findData(current)
            if idx < 0:
                idx = 0
            self.cb_lang.setCurrentIndex(idx)
            lay.addWidget(self.cb_lang)
        else:
            self.cb_lang.addItem(TR("tr_lang_all"), None)
            self.cb_lang.setVisible(False)

        # ── языки оригинала: какие строки гнать в движок ──
        # (остальные остаются как есть — не тратим запросы Google/AI).
        self._src_checks: dict[str | None, QCheckBox] = {}
        self._src_counts: dict[str | None, int] = {}
        self._lbl_src_sum: QLabel | None = None
        if src_groups:
            lay.addWidget(QLabel(TR("tr_src_filter")))
            for lang, count in src_groups:
                name = TR("lang_" + lang) if lang else TR("tr_lang_unknown")
                cb = QCheckBox(f"{name} — {count}")
                cb.setChecked(True)
                cb.toggled.connect(self._refresh_src_sum)
                lay.addWidget(cb)
                self._src_checks[lang] = cb
                self._src_counts[lang] = count
            quick = QHBoxLayout()
            quick.setSpacing(8)
            b_all = QPushButton(TR("tr_src_all"))
            b_none = QPushButton(TR("tr_src_none"))
            b_all.setObjectName("tool_btn")
            b_none.setObjectName("tool_btn")
            b_all.clicked.connect(lambda: self._set_all_src(True))
            b_none.clicked.connect(lambda: self._set_all_src(False))
            quick.addWidget(b_all)
            quick.addWidget(b_none)
            quick.addStretch(1)
            self._lbl_src_sum = QLabel("")
            quick.addWidget(self._lbl_src_sum)
            lay.addLayout(quick)
            self._refresh_src_sum()

        lbl_mode = QLabel(TR("tr_mode"))
        lay.addWidget(lbl_mode)
        self._opt_new = _ModeOption(TR("tr_mode_new"), TR("tr_mode_new_desc"))
        self._opt_all = _ModeOption(TR("tr_mode_all"), TR("tr_mode_all_desc"))
        self._opt_new.clicked.connect(lambda: self._select_mode(self._opt_new))
        self._opt_all.clicked.connect(lambda: self._select_mode(self._opt_all))
        self._select_mode(self._opt_new)
        lay.addWidget(self._opt_new)
        lay.addWidget(self._opt_all)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        b_ok = QPushButton(TR("btn_ok"))
        b_cancel = QPushButton(TR("btn_cancel"))
        b_ok.clicked.connect(self.accept)
        b_cancel.clicked.connect(self.reject)
        btn_row.addWidget(b_ok)
        btn_row.addWidget(b_cancel)
        lay.addLayout(btn_row)

    def _set_all_src(self, on: bool) -> None:
        for cb in self._src_checks.values():
            cb.setChecked(on)
        self._refresh_src_sum()

    def _refresh_src_sum(self) -> None:
        if self._lbl_src_sum is None:
            return
        total = sum(self._src_counts.get(lang, 0)
                    for lang, cb in self._src_checks.items()
                    if cb.isChecked())
        self._lbl_src_sum.setText(TR("tr_src_selected", n=total))

    def _select_mode(self, opt: _ModeOption):
        self._opt_new.set_selected(opt is self._opt_new)
        self._opt_all.set_selected(opt is self._opt_all)

    def lang(self) -> str | None:
        return self.cb_lang.currentData()

    def selected_src_langs(self) -> set | None:
        """Выбранные языки оригинала. None — все (чекбоксов не было)."""
        if not self._src_checks:
            return None
        return {lang for lang, cb in self._src_checks.items()
                if cb.isChecked()}

    def overwrite(self) -> bool:
        return self._opt_all.is_selected()
