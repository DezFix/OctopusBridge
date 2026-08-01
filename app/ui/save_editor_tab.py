# -*- coding: utf-8 -*-
"""Save Editor для Twine (SugarCube .save).

Вкладка показывает список .save-файлов, позволяет загрузить,
просматривать и редактировать переменные, а также сохранять изменения.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.ui.i18n import TR
from app.ui.icons import icon


class SaveEditorTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._save_data: dict | None = None
        self._save_path: str | None = None
        self._vars: list[dict] = []
        self._loading = False

        lay = QVBoxLayout(self)

        # ── верхняя панель ──
        bar = QHBoxLayout()
        self.btn_refresh = QPushButton(TR("cheat_refresh"))
        self.btn_refresh.clicked.connect(self._scan_saves)
        bar.addWidget(self.btn_refresh)

        self.btn_browse = QPushButton("…")
        self.btn_browse.setToolTip("Выбрать .save вручную")
        self.btn_browse.clicked.connect(self._browse_save)
        bar.addWidget(self.btn_browse)

        self.lbl_status = QLabel("")
        bar.addWidget(self.lbl_status, 1)

        self.btn_save = QPushButton(TR("cheat_apply"))
        self.btn_save.setIcon(icon("save"))
        self.btn_save.setObjectName("accent")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_current)
        bar.addWidget(self.btn_save)
        lay.addLayout(bar)

        # ── сплиттер: список сейвов + таблица ──
        splitter = QSplitter(Qt.Horizontal)

        # левая панель — список сейвов
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(QLabel("Сейвы:"))
        self.save_list = QListWidget()
        self.save_list.currentRowChanged.connect(self._on_save_selected)
        left_lay.addWidget(self.save_list, 1)
        splitter.addWidget(left)

        # правая панель — таблица переменных
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)

        search_bar = QHBoxLayout()
        search_bar.addWidget(QLabel(TR("cheat_item_search")))
        self.var_search = QLineEdit()
        self.var_search.setPlaceholderText("имя или значение…")
        self.var_search.textChanged.connect(self._fill_vars)
        search_bar.addWidget(self.var_search, 1)
        right_lay.addLayout(search_bar)

        self.vars_table = QTableWidget(0, 3)
        self.vars_table.setHorizontalHeaderLabels(["#", "Переменная", "Значение"])
        self.vars_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.vars_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.vars_table.itemChanged.connect(self._on_var_edit)
        right_lay.addWidget(self.vars_table, 1)

        hint = QLabel("Изменения применяются только после нажатия «Применить».")
        hint.setWordWrap(True)
        right_lay.addWidget(hint)

        splitter.addWidget(right)
        splitter.setSizes([200, 600])
        lay.addWidget(splitter, 1)

    # ── сканирование ──
    def on_project_opened(self):
        self._scan_saves()

    def _scan_saves(self):
        self.save_list.blockSignals(True)
        self.save_list.clear()
        self._save_data = None
        self._save_path = None
        self._vars = []
        self._fill_vars()
        self.btn_save.setEnabled(False)
        self.lbl_status.setText("Поиск сейвов…")

        p = self.main.project
        game_dir = p.game_dir if p else ""
        if not game_dir or not os.path.isdir(game_dir):
            self.lbl_status.setText("Проект не открыт")
            self.save_list.blockSignals(False)
            return

        from app.core.twine import savefile
        saves = savefile.find_saves(game_dir)
        if not saves:
            # поиск глубже: game/saves/ (Ren'Py-совместимость)
            for root, _dirs, files in os.walk(game_dir):
                for f in sorted(files):
                    if f.endswith(".save"):
                        saves.append(os.path.join(root, f))

        if not saves:
            self.lbl_status.setText("Сейвы не найдены")
            self.save_list.blockSignals(False)
            return

        for path in saves:
            name = os.path.basename(path)
            folder = os.path.basename(os.path.dirname(path))
            item = QListWidgetItem(f"{folder}/{name}" if folder != os.path.basename(game_dir) else name)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.save_list.addItem(item)

        self.lbl_status.setText(f"Найдено сейвов: {len(saves)}")
        self.save_list.blockSignals(False)

    # ── загрузка ──
    def _browse_save(self):
        start = ""
        if self.main.project:
            start = self.main.project.game_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите .save", start,
            "Save files (*.save);;All files (*)")
        if path:
            self._load_save(path)

    def _on_save_selected(self, row: int):
        if row < 0:
            return
        item = self.save_list.item(row)
        if not item:
            return
        path = item.data(Qt.UserRole)
        self._load_save(path)

    def _load_save(self, path: str):
        from app.core.twine import savefile
        try:
            data = savefile.load_save(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Ошибка", str(e))
            return

        self._save_path = path
        self._save_data = data

        flat = savefile.flatten_variables(savefile.get_variables(data))
        self._vars = sorted(
            ({"name": k, "value": v} for k, v in flat.items()),
            key=lambda v: v["name"].lower())

        self._fill_vars()
        self.btn_save.setEnabled(True)
        self.lbl_status.setText(
            f"{os.path.basename(path)} — {len(self._vars)} переменных")

    # ── таблица ──
    def _fill_vars(self):
        self._loading = True
        try:
            q = self.var_search.text().strip().lower()
            rows = [v for v in self._vars
                    if not q or q in v["name"].lower()
                    or q in str(v["value"]).lower()]
            self.vars_table.setRowCount(len(rows))
            for r, v in enumerate(rows):
                it_idx = QTableWidgetItem(str(r + 1))
                it_idx.setFlags(it_idx.flags() & ~Qt.ItemIsEditable)
                self.vars_table.setItem(r, 0, it_idx)

                it_name = QTableWidgetItem(v["name"])
                it_name.setFlags(it_name.flags() & ~Qt.ItemIsEditable)
                it_name.setData(Qt.UserRole, v["name"])
                self.vars_table.setItem(r, 1, it_name)

                value = v["value"]
                if isinstance(value, bool):
                    it_val = QTableWidgetItem()
                    it_val.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    it_val.setCheckState(Qt.Checked if value else Qt.Unchecked)
                else:
                    it_val = QTableWidgetItem(str(value))
                    it_val.setToolTip(type(value).__name__)
                it_val.setData(Qt.UserRole, v["name"])
                self.vars_table.setItem(r, 2, it_val)
        finally:
            self._loading = False

    # ── редактирование ──
    def _on_var_edit(self, item):
        if self._loading:
            return
        name = item.data(Qt.UserRole)
        if name is None:
            return
        var = next((v for v in self._vars if v["name"] == name), None)
        if var is None:
            return
        old = var["value"]
        if isinstance(old, bool):
            var["value"] = item.checkState() == Qt.Checked
        else:
            try:
                if isinstance(old, int) and not isinstance(old, bool):
                    var["value"] = int(item.text().strip())
                elif isinstance(old, float):
                    var["value"] = float(item.text().strip())
                else:
                    var["value"] = item.text().strip()
            except (ValueError, TypeError):
                self._revert_cell(item, old)
                return
        self.lbl_status.setText(f"{name} = {var['value']!r} (не сохранено)")

    def _revert_cell(self, item, old):
        self._loading = True
        try:
            if isinstance(old, bool):
                item.setCheckState(Qt.Checked if old else Qt.Unchecked)
            else:
                item.setText(str(old))
        finally:
            self._loading = False

    # ── сохранение ──
    def _save_current(self):
        from app.core.twine import savefile
        if not self._save_data or not self._save_path:
            return
        updates = {v["name"]: v["value"] for v in self._vars}
        try:
            savefile.set_variables(self._save_data, updates)
            savefile.write_save(self._save_path, self._save_data)
            self.lbl_status.setText(
                f"Сохранено: {os.path.basename(self._save_path)} "
                f"({len(updates)} переменных)")
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Ошибка сохранения", str(e))
