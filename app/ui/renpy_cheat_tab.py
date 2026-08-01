# -*- coding: utf-8 -*-
"""Читы для Ren'Py и Twine: «Переменные» и «Триггеры» (две вкладки).

Живой режим: плагин в игре шлёт список переменных (store+persistent /
SugarCube State.variables, вложенные — dot-path), правки применяются
мгновенно: числа/строки — по вводу, триггеры (bool) — по галочке.

Режим сейва (Twine): переменные читаются из .save-файла SugarCube и
правятся прямо в нём — когда игра не запущена или live недоступен.

Вкладка «Переменные» дополнительно имеет консоль (exec/eval в игре).
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from app.ui.i18n import TR
from app.ui.icons import icon

AUTOREFRESH_MS = 1000


class _VarsBaseTab(QWidget):
    """Общая логика списка переменных (живой + сейв режимы)."""

    want_bool: bool | None = None     # фильтр: True=только bool, False=не bool

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._vars: list[dict] = []
        self._loading = False
        self._save_path: str | None = None
        self._save_data: dict | None = None
        self._hide_text = True

        lay = QVBoxLayout(self)
        self.lbl_status = QLabel(TR("cheat_hint"))
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        # ── поиск + управление ──
        bar = QHBoxLayout()
        bar.addWidget(QLabel(TR("cheat_item_search")))
        self.var_search = QLineEdit()
        self.var_search.setPlaceholderText(TR("rpy_search_ph"))
        self.var_search.textChanged.connect(self._fill_vars)
        bar.addWidget(self.var_search, 1)
        self.cb_hide_text = QCheckBox(TR("rpy_hide_text"))
        self.cb_hide_text.setChecked(True)
        self.cb_hide_text.toggled.connect(self._on_hide_text_toggled)
        bar.addWidget(self.cb_hide_text)
        self.cb_autorefresh = QCheckBox(TR("rpy_autorefresh"))
        self.cb_autorefresh.setChecked(True)
        bar.addWidget(self.cb_autorefresh)
        self.btn_save_mode = QPushButton(TR("vars_from_save"))
        self.btn_save_mode.setIcon(icon("save"))
        self.btn_save_mode.clicked.connect(self._open_save)
        bar.addWidget(self.btn_save_mode)
        btn_refresh = QPushButton(TR("cheat_refresh"))
        btn_refresh.clicked.connect(self.reload_vars)
        bar.addWidget(btn_refresh)
        lay.addLayout(bar)

        # ── таблица ──
        self.vars_table = QTableWidget(0, 2)
        self.vars_table.setHorizontalHeaderLabels(
            [TR("rpy_var_name"), TR("rpy_var_value")])
        self.vars_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.vars_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.vars_table.itemChanged.connect(self._on_var_edit)
        lay.addWidget(self.vars_table, 1)

        self.lbl_hint = QLabel(TR("rpy_vars_hint"))
        self.lbl_hint.setWordWrap(True)
        lay.addWidget(self.lbl_hint)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(AUTOREFRESH_MS)

        self.main.bridge_vars.connect(self._on_vars)
        self.main.bridge_cheat_ack.connect(self._on_ack)
        self.main.bridge_client.connect(self._on_client)

    def _on_hide_text_toggled(self, checked: bool):
        self._hide_text = checked
        self._fill_vars()

    # ── режим ──
    def _engine_key(self) -> str:
        mod = self.main.engine_module
        return mod.key if mod else ""

    def _is_save_mode(self) -> bool:
        return self._save_path is not None

    # ── канал ──
    def _cheat(self, cmd: str, **kwargs) -> bool:
        ch = self.main.channel()
        if not ch:
            return False
        return ch.send_cheat(cmd, **kwargs)

    def reload_vars(self):
        if self._is_save_mode():
            self._load_save_file(self._save_path)
        else:
            self._load_live()

    def _load_live(self):
        if not self._cheat("get_vars"):
            self.lbl_status.setText(TR("cheat_no_bridge"))

    def _auto_refresh(self):
        if self._is_save_mode() or not self.isVisible() \
                or not self.cb_autorefresh.isChecked():
            return
        if self.vars_table.state() == QAbstractItemView.EditingState:
            return
        self._cheat("get_vars")

    def showEvent(self, event):
        super().showEvent(event)
        self.btn_save_mode.setVisible(self._engine_key() == "twine")
        self.reload_vars()

    def on_project_opened(self):
        self._vars = []
        self._save_path = None
        self._save_data = None
        self._fill_vars()

    # ── живой приём ──
    def _on_vars(self, variables: str):
        variables = json.loads(variables)
        if self._is_save_mode():
            return
        self._vars = sorted(
            (v for v in variables if isinstance(v, dict) and "name" in v),
            key=lambda v: str(v["name"]).lower())
        self._fill_vars()

    def _on_client(self, connected: bool):
        if not self._is_save_mode():
            self.lbl_status.setText(
                TR("cheat_connected") if connected else
                TR("cheat_disconnected"))
            if connected:
                self._load_live()

    # ── сейв режим (Twine) ──
    def _open_save(self):
        from app.core.twine import savefile
        start = ""
        p = self.main.project
        if p:
            saves = savefile.find_saves(p.game_dir)
            start = saves[0] if saves else p.game_dir
        path, _ = QFileDialog.getOpenFileName(
            self, TR("vars_from_save"), start,
            "SugarCube saves (*.save);;All files (*)")
        if path:
            self._load_save_file(path)

    def _load_save_file(self, path: str):
        from app.core.twine import savefile
        try:
            data = savefile.load_save(path)
        except (ValueError, OSError) as e:
            self.lbl_status.setText(str(e))
            return
        self._save_path = path
        self._save_data = data
        flat = savefile.flatten_variables(savefile.get_variables(data))
        self._vars = sorted(
            ({"name": k, "value": v} for k, v in flat.items()),
            key=lambda v: v["name"].lower())
        self._fill_vars()
        self.lbl_status.setText(
            TR("vars_save_loaded", path=os.path.basename(path),
               n=len(self._vars)))

    # ── таблица ──
    def _passes(self, v: dict) -> bool:
        if self.want_bool is None:
            pass  # no filter on bool/non-bool
        elif isinstance(v.get("value"), bool) != self.want_bool:
            return False
        if self._hide_text and isinstance(v.get("value"), str):
            return False
        return True

    def _fill_vars(self):
        self._loading = True
        try:
            q = self.var_search.text().strip().lower() \
                if hasattr(self, "var_search") else ""
            rows = [v for v in self._vars if self._passes(v)
                    and (not q or q in str(v["name"]).lower()
                         or q in str(v.get("value")).lower())]
            self.vars_table.setRowCount(len(rows))
            for r, v in enumerate(rows):
                name = str(v["name"])
                value = v.get("value")
                it_n = QTableWidgetItem(name)
                it_n.setFlags(it_n.flags() & ~Qt.ItemIsEditable)
                it_n.setData(Qt.UserRole, name)
                it_n.setToolTip(repr(value))
                self.vars_table.setItem(r, 0, it_n)
                if isinstance(value, bool):
                    it_v = QTableWidgetItem()
                    it_v.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    it_v.setCheckState(Qt.Checked if value else Qt.Unchecked)
                    it_v.setToolTip("bool")
                else:
                    it_v = QTableWidgetItem(str(value))
                    it_v.setToolTip(type(value).__name__)
                it_v.setData(Qt.UserRole, name)
                self.vars_table.setItem(r, 1, it_v)
        finally:
            self._loading = False

    # ── применение ──
    def _on_var_edit(self, item):
        if self._loading or item.column() != 1:
            return
        name = item.data(Qt.UserRole)
        var = next((v for v in self._vars if str(v["name"]) == name), None)
        old = var.get("value") if var else None
        if isinstance(old, bool):
            value = item.checkState() == Qt.Checked
        else:
            value = self._coerce(item.text(), old)
            if value is _INVALID:
                self.lbl_status.setText(TR("rpy_bad_value", name=name))
                self._revert_cell(item, old)
                return
        if self._is_save_mode():
            self._apply_to_save(name, value, item, var, old)
        else:
            self._apply_to_game(name, value, item, var, old)

    def _apply_to_game(self, name, value, item, var, old):
        if self._cheat("var_set", name=name, value=value):
            if var is not None:
                var["value"] = value
            self.lbl_status.setText(TR("rpy_applied", name=name, value=value))
        else:
            self.lbl_status.setText(TR("cheat_no_bridge"))
            self._revert_cell(item, old)

    def _apply_to_save(self, name, value, item, var, old):
        from app.core.twine import savefile
        try:
            savefile.set_variables(self._save_data, {name: value})
            savefile.write_save(self._save_path, self._save_data)
        except (ValueError, OSError) as e:
            self.lbl_status.setText(str(e))
            self._revert_cell(item, old)
            return
        if var is not None:
            var["value"] = value
        self.lbl_status.setText(
            TR("vars_saved", name=name, value=value))

    def _revert_cell(self, item, old):
        self._loading = True
        try:
            if isinstance(old, bool):
                item.setCheckState(Qt.Checked if old else Qt.Unchecked)
            else:
                item.setText(str(old))
        finally:
            self._loading = False

    @staticmethod
    def _coerce(text: str, old):
        text = text.strip()
        try:
            if isinstance(old, int) and not isinstance(old, bool):
                return int(text)
            if isinstance(old, float):
                return float(text)
            if old is None:
                return None if text.lower() in ("none", "") else text
            return text
        except ValueError:
            return _INVALID

    def _on_ack(self, cmd: str, ok: bool, error: str, value: str):
        if not ok and cmd == "var_set":
            self.lbl_status.setText(TR("cheat_error", cmd=cmd, err=error))


class _Invalid:
    pass


_INVALID = _Invalid()


class VariablesTab(_VarsBaseTab):
    """«Переменные»: не-bool значения + консоль (exec/eval в игре)."""

    want_bool = False

    def __init__(self, main_window):
        super().__init__(main_window)
        lay = self.layout()

        console_box = QLabel(TR("vars_console"))
        lay.addWidget(console_box)
        row = QHBoxLayout()
        self.console_edit = QLineEdit()
        self.console_edit.setPlaceholderText(
            "renpy.store.gold + 100  /  SugarCube.State.variables.player.money")
        self.console_edit.returnPressed.connect(self._run_console)
        row.addWidget(self.console_edit, 1)
        btn_run = QPushButton(TR("rpy_exec_go"))
        btn_run.setIcon(icon("run"))
        btn_run.clicked.connect(self._run_console)
        row.addWidget(btn_run)
        lay.addLayout(row)
        self.lbl_console = QLabel("—")
        self.lbl_console.setWordWrap(True)
        self.lbl_console.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_console)

    def _run_console(self):
        code = self.console_edit.text().strip()
        if not code:
            return
        if self._cheat("exec", code=code):
            self.lbl_console.setText("…")
        else:
            self.lbl_console.setText(TR("cheat_no_bridge"))

    def _on_ack(self, cmd: str, ok: bool, error: str, value: str):
        super()._on_ack(cmd, ok, error, value)
        if cmd == "exec":
            self.lbl_console.setText(
                f"= {value}" if ok else f"ERROR: {error}")


class TriggersTab(_VarsBaseTab):
    """«Триггеры»: bool-переменные с мгновенными галочками."""

    want_bool = True


# совместимость со старым именем
RenPyCheatTab = VariablesTab
