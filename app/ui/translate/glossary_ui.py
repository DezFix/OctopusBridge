# -*- coding: utf-8 -*-
"""Диалоги глоссария: кандидаты терминов, редактор строк, сам глоссарий.

Раньше жили в app/ui/translate_tab.py.
"""
from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from app.ui.i18n import TR
from app.ui.icons import icon
from app.ui.theme import AnimatedComboBox, C_TEXT, C_TEXT_SECONDARY


class _TermEditDialog(QDialog):
    """Диалог строки глоссария: термин / перевод / категория."""

    def __init__(self, parent=None, term: str = "", tr: str = "",
                 group: str = "", groups: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(TR("glossary_edit_title"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.ed_term = QLineEdit(term)
        form.addRow(TR("glossary_term"), self.ed_term)

        self.ed_tr = QLineEdit(tr)
        form.addRow(TR("glossary_term_tr"), self.ed_tr)

        self.cb_group = AnimatedComboBox()
        self.cb_group.setEditable(True)
        self.cb_group.setInsertPolicy(AnimatedComboBox.NoInsert)
        self.cb_group.addItem(TR("glossary_group_none"))
        for g in (groups or []):
            if g:
                self.cb_group.addItem(g)
        if group:
            self.cb_group.setCurrentText(group)
        form.addRow(TR("glossary_term_group"), self.cb_group)

        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Save
                                | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self) -> tuple[str, str, str]:
        g = self.cb_group.currentText().strip()
        return (self.ed_term.text().strip(), self.ed_tr.text().strip(),
                "" if g == TR("glossary_group_none") else g)


class GlossaryDialog(QDialog):
    """Глоссарий: понятные пары языков, категории, явное редактирование."""

    _LANG_CODES = ["ja", "zh", "en", "ru"]
    _LANG_KEYS = {
        "ja": "glossary_lang_ja", "zh": "glossary_lang_zh",
        "en": "glossary_lang_en", "ru": "glossary_lang_ru",
    }

    def __init__(self, glossary, settings, parent=None):
        super().__init__(parent)
        self.glossary = glossary
        self.setWindowTitle(TR("glossary_title"))
        self.setWindowIcon(icon("book-bookmark", 18, C_TEXT_SECONDARY))
        self.resize(760, 560)
        self.setMinimumSize(600, 400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 10)
        lay.setSpacing(8)

        # ── верх: источник → целевой язык ──
        top = QHBoxLayout()
        top.addWidget(QLabel(TR("glossary_src")))
        self.cb_src = AnimatedComboBox()
        for code in self._LANG_CODES:
            self.cb_src.addItem(TR(self._LANG_KEYS[code]), userData=code)
        top.addWidget(self.cb_src)
        top.addWidget(QLabel("→"))
        top.addWidget(QLabel(TR("glossary_tgt")))
        self.cb_tgt = AnimatedComboBox()
        for code in self._LANG_CODES:
            self.cb_tgt.addItem(TR(self._LANG_KEYS[code]), userData=code)
        top.addWidget(self.cb_tgt)
        src = settings.value("source_lang", "auto")
        src = "ja" if src == "auto" else src
        tgt = settings.value("target_lang", "ru")
        for i in range(self.cb_src.count()):
            if self.cb_src.itemData(i) == src:
                self.cb_src.setCurrentIndex(i)
                break
        for i in range(self.cb_tgt.count()):
            if self.cb_tgt.itemData(i) == tgt:
                self.cb_tgt.setCurrentIndex(i)
                break
        self.cb_src.currentIndexChanged.connect(self._on_pair_changed)
        self.cb_tgt.currentIndexChanged.connect(self._on_pair_changed)
        top.addStretch(1)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color: {C_TEXT_SECONDARY};")
        top.addWidget(self.count_label)
        lay.addLayout(top)

        # ── поиск + фильтр категории ──
        filt = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(TR("glossary_search"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("magnifying-glass", 15, C_TEXT_SECONDARY),
                              QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._fill)
        filt.addWidget(self.search, 1)
        self.cb_group = AnimatedComboBox()
        self.cb_group.currentIndexChanged.connect(self._fill)
        filt.addWidget(self.cb_group)
        lay.addLayout(filt)

        # ── таблица: термин / перевод / категория ──
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [TR("glossary_col_orig"), TR("glossary_col_tr"),
             TR("glossary_col_group")])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.setSortingEnabled(True)
        self.table.itemDoubleClicked.connect(self._edit)
        lay.addWidget(self.table, 1)

        # ── кнопки ──
        row = QHBoxLayout()
        self.btn_add = QPushButton(TR("glossary_add"))
        self.btn_add.setIcon(icon("plus", 15, C_TEXT))
        self.btn_add.clicked.connect(self._add)
        self.btn_edit = QPushButton(TR("glossary_edit"))
        self.btn_edit.setIcon(icon("pencil", 15, C_TEXT))
        self.btn_edit.clicked.connect(self._edit)
        self.btn_del = QPushButton(TR("glossary_del"))
        self.btn_del.setIcon(icon("trash", 15, C_TEXT))
        self.btn_del.clicked.connect(self._del)
        self.btn_save = QPushButton(TR("glossary_save"))
        self.btn_save.setIcon(icon("floppy-disk", 15, C_TEXT))
        self.btn_save.clicked.connect(self._save)
        self.btn_save.setDefault(True)
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_save)
        lay.addLayout(row)

        hint = QLabel(TR("glossary_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {C_TEXT_SECONDARY};")
        lay.addWidget(hint)
        self._fill()

    def _current_pair(self) -> tuple[str, str]:
        return (str(self.cb_src.currentData()),
                str(self.cb_tgt.currentData()))

    def _on_pair_changed(self, *args):
        self._fill()

    def _fill(self):
        src, tgt = self._current_pair()
        entries = self.glossary.entries(src, tgt)
        groups = self.glossary.groups(src, tgt)

        # перестроить фильтр категорий, не теряя выбор
        cur = self.cb_group.currentText()
        self.cb_group.blockSignals(True)
        self.cb_group.clear()
        self.cb_group.addItem(TR("glossary_group_all"))
        for g in groups:
            self.cb_group.addItem(g)
        if cur:
            idx = self.cb_group.findText(cur)
            if idx >= 0:
                self.cb_group.setCurrentIndex(idx)
        self.cb_group.blockSignals(False)
        sel_group = self.cb_group.currentText()

        query = self.search.text().strip().lower()
        rows = []
        for k, e in entries.items():
            if sel_group != TR("glossary_group_all") \
                    and e["group"] != sel_group:
                continue
            if query and query not in k.lower() \
                    and query not in e["tr"].lower() \
                    and query not in e["group"].lower():
                continue
            rows.append((k, e["tr"], e["group"]))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, (k, v, g) in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(k))
            self.table.setItem(r, 1, QTableWidgetItem(v))
            self.table.setItem(r, 2, QTableWidgetItem(g))
        self.table.setSortingEnabled(True)
        # Какие ключи показаны: _save() должен мёржить видимые строки в
        # полный словарь, а не заменять его — иначе закрытие диалога с
        # активным поиском/фильтром молча удаляет все скрытые термины.
        self._fill_keys = {k for k, _, _ in rows}

        self.count_label.setText(
            TR("glossary_count", shown=len(rows),
               total=len(entries)))

    def _selected_row(self) -> int:
        items = self.table.selectedItems()
        return items[0].row() if items else -1

    def _add(self):
        dlg = _TermEditDialog(self, groups=self.glossary.groups(
            *self._current_pair()))
        if dlg.exec() != QDialog.Accepted:
            return
        term, tr, group = dlg.values()
        if not term:
            return
        src, tgt = self._current_pair()
        entries = self.glossary.entries(src, tgt)
        entries[term] = {"tr": tr, "group": group}
        self.glossary.set_entries(src, tgt, entries)
        self._fill()

    def _edit(self, *args):
        row = self._selected_row()
        if row < 0:
            return
        term = self.table.item(row, 0).text()
        tr = self.table.item(row, 1).text()
        group = self.table.item(row, 2).text()
        dlg = _TermEditDialog(self, term, tr, group,
                              groups=self.glossary.groups(
                                  *self._current_pair()))
        if dlg.exec() != QDialog.Accepted:
            return
        n_term, n_tr, n_group = dlg.values()
        if not n_term:
            return
        src, tgt = self._current_pair()
        entries = self.glossary.entries(src, tgt)
        if n_term != term:
            entries.pop(term, None)
        entries[n_term] = {"tr": n_tr, "group": n_group}
        self.glossary.set_entries(src, tgt, entries)
        self._fill()

    def _del(self):
        row = self._selected_row()
        if row < 0:
            return
        term = self.table.item(row, 0).text()
        src, tgt = self._current_pair()
        entries = self.glossary.entries(src, tgt)
        entries.pop(term, None)
        self.glossary.set_entries(src, tgt, entries)
        self._fill()

    def _save(self):
        src, tgt = self._current_pair()
        # Мёрж в полный словарь пары, а не замена: таблица может показывать
        # подмножество (поиск/фильтр категории) — скрытые термины обязаны
        # уцелеть. Удаления через _del уже применены к глоссарию напрямую,
        # здесь лишь добиваем ключи, пропавшие из видимых строк.
        try:
            full = dict(self.glossary.entries(src, tgt) or {})
        except Exception:  # noqa: BLE001 — битый глоссарий: сохраняем видимое
            full = {}
        shown: dict[str, dict] = {}
        for r in range(self.table.rowCount()):
            t = self.table.item(r, 0)
            v = self.table.item(r, 1)
            g = self.table.item(r, 2)
            if t and t.text().strip():
                shown[t.text().strip()] = {
                    "tr": v.text().strip() if v else "",
                    "group": g.text().strip() if g else "",
                }
        for k in (getattr(self, "_fill_keys", set()) - set(shown)):
            full.pop(k, None)
        full.update(shown)
        self.glossary.set_entries(src, tgt, full)

    def closeEvent(self, event):
        self._save()  # автосохранение при закрытии
        super().closeEvent(event)
