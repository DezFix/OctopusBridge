# -*- coding: utf-8 -*-
"""Save Editor для Twine (SugarCube .save) — минимальный редактор.

Перетащите .save на вкладку (или «Загрузить…»), правьте переменные и
нажмите «Применить» — файл перезаписывается на месте (оригинал —
рядом, как *.ob_backup). Извлекаются ВСЕ параметры сейва: словари по
точкам, списки по индексам ('flags[0]').
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from app.ui.i18n import TR
from app.ui.icons import icon


def _save_urls(mime):
    urls = mime.urls() if mime.hasUrls() else []
    out = []
    for u in urls:
        p = u.toLocalFile()
        if p and p.lower().endswith((".save", ".json")):
            out.append(p)
    return out


class SaveEditorTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._save_data: dict | None = None
        self._save_path: str | None = None
        self._vars: list[dict] = []
        self._loading = False
        self.setAcceptDrops(True)

        lay = QVBoxLayout(self)

        # ── верхняя панель ──
        bar = QHBoxLayout()
        self.btn_browse = QPushButton(TR("save_load"))
        self.btn_browse.setIcon(icon("folder-open"))
        self.btn_browse.setToolTip(TR("save_browse_tip"))
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

        # ── страницы: drop-зона / таблица переменных ──
        self.stack = QStackedWidget()

        drop = QWidget()
        drop_lay = QVBoxLayout(drop)
        drop_lay.setContentsMargins(24, 24, 24, 24)
        lbl_icon = QLabel()
        lbl_icon.setPixmap(icon("file-text", 56, "#445").pixmap(56, 56))
        lbl_icon.setAlignment(Qt.AlignCenter)
        drop_lay.addWidget(lbl_icon)
        self.lbl_drop = QLabel(TR("save_drop_ph"))
        self.lbl_drop.setAlignment(Qt.AlignCenter)
        self.lbl_drop.setWordWrap(True)
        self.lbl_drop.setStyleSheet(
            "color:#667; border:2px dashed #445; border-radius:10px;"
            "background:#14161a; font-size:16px;")
        drop_lay.addWidget(self.lbl_drop, 1)
        self.stack.addWidget(drop)

        table_page = QWidget()
        t_lay = QVBoxLayout(table_page)
        t_lay.setContentsMargins(0, 0, 0, 0)

        search_bar = QHBoxLayout()
        search_bar.addWidget(QLabel(TR("cheat_item_search")))
        self.var_search = QLineEdit()
        self.var_search.setPlaceholderText("имя или значение…")
        self.var_search.textChanged.connect(self._fill_vars)
        search_bar.addWidget(self.var_search, 1)
        t_lay.addLayout(search_bar)

        self.vars_table = QTableWidget(0, 3)
        self.vars_table.setHorizontalHeaderLabels(["#", "Переменная", "Значение"])
        self.vars_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.vars_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.vars_table.itemChanged.connect(self._on_var_edit)
        t_lay.addWidget(self.vars_table, 1)

        hint = QLabel(TR("save_apply_hint"))
        hint.setWordWrap(True)
        t_lay.addWidget(hint)
        self.stack.addWidget(table_page)

        self.stack.setCurrentIndex(0)
        lay.addWidget(self.stack, 1)

    # ── drag&drop ──
    def dragEnterEvent(self, e):
        if _save_urls(e.mimeData()):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        paths = _save_urls(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self._load_save(paths[0])
        else:
            super().dropEvent(e)

    # ── проект ──
    def on_project_opened(self):
        if not self._save_data:
            self.lbl_status.setText(TR("save_wait_drop"))

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
        self.stack.setCurrentIndex(1)
        self.lbl_status.setText(
            f"{os.path.basename(path)} — {len(self._vars)} параметров")

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

    # ── сохранение: перезаписывает тот же файл ──
    def _save_current(self):
        from app.core.twine import savefile
        if not self._save_data or not self._save_path:
            return
        updates = {v["name"]: v["value"] for v in self._vars}
        try:
            savefile.set_variables(self._save_data, updates)
            savefile.write_save(self._save_path, self._save_data)
            self.lbl_status.setText(
                TR("save_saved", name=os.path.basename(self._save_path),
                   n=len(updates)))
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Ошибка сохранения", str(e))
