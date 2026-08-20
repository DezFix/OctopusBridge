# -*- coding: utf-8 -*-
"""Читы для Ren'Py и Twine: «Переменные» и «Триггеры» (две вкладки).

Живой режим: плагин в игре шлёт список переменных (store+persistent /
SugarCube State.variables, вложенные — dot-path), правки применяются
мгновенно: числа/строки — по вводу, триггеры (bool) — по галочке.

Режим сейва (Twine): переменные читаются из .save-файла SugarCube и
правятся прямо в нём — когда игра не запущена или live недоступен.

Таблица — QTableView с виртуальной моделью: при десятках тысяч
переменных Qt рендерит только видимые строки, прокрутка не лагает;
повторный сброс модели делается только при реальном изменении данных.

Вкладка «Переменные» дополнительно имеет консоль (exec/eval в игре).
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableView,
                               QVBoxLayout, QWidget)

from app.ui.i18n import TR
from app.ui.icons import icon

AUTOREFRESH_MS = 1000

# режимы поиска по значению (как Cheat Engine: первый скан — «равно»,
# уточнение — по изменению)
SCAN_EQ = "eq"
SCAN_CHANGED = "changed"
SCAN_UNCHANGED = "unchanged"
SCAN_INCREASED = "increased"
SCAN_DECREASED = "decreased"

_SCAN_MODES = [
    (SCAN_EQ, "rpy_scan_eq"),
    (SCAN_CHANGED, "rpy_scan_changed"),
    (SCAN_UNCHANGED, "rpy_scan_unchanged"),
    (SCAN_INCREASED, "rpy_scan_increased"),
    (SCAN_DECREASED, "rpy_scan_decreased"),
]


class _VarsTableModel(QAbstractTableModel):
    """Виртуальная модель списка переменных (2 колонки: имя, значение).

    Данные хранятся как list[dict] с ключами name/value; setData
    принимает правку и уведомляет вкладку (dataChanged) — применение
    к игре делает вкладка, при неудаче вызывается revert().
    """

    COL_NAME, COL_VALUE = 0, 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 2

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return TR("rpy_var_name") if section == self.COL_NAME \
                else TR("rpy_var_value")
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        if index.column() == self.COL_VALUE:
            value = self.rows[index.row()].get("value")
            if isinstance(value, bool):
                return Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
            return Qt.ItemIsEnabled | Qt.ItemIsEditable
        return Qt.ItemIsEnabled

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.rows)):
            return None
        v = self.rows[index.row()]
        if index.column() == self.COL_NAME:
            if role in (Qt.DisplayRole, Qt.EditRole, Qt.UserRole):
                return str(v["name"])
            if role == Qt.ToolTipRole:
                return repr(v.get("value"))
            return None
        # колонка значения
        value = v.get("value")
        if role == Qt.DisplayRole or role == Qt.EditRole:
            return "" if isinstance(value, bool) else str(value)
        if role == Qt.ToolTipRole:
            return type(value).__name__
        if role == Qt.UserRole:
            return str(v["name"])
        if role == Qt.CheckStateRole and isinstance(value, bool):
            return Qt.Checked if value else Qt.Unchecked
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or index.column() != self.COL_VALUE:
            return False
        row = index.row()
        if not (0 <= row < len(self.rows)):
            return False
        old = self.rows[row].get("value")
        if isinstance(old, bool) and role == Qt.CheckStateRole:
            self.rows[row]["value"] = (value == Qt.Checked)
        elif not isinstance(old, bool) and role == Qt.EditRole:
            self.rows[row]["value"] = value
        else:
            return False
        self.dataChanged.emit(index, index)
        return True

    def revert(self, row: int, old):
        if 0 <= row < len(self.rows):
            self.rows[row]["value"] = old
            idx = self.index(row, self.COL_VALUE)
            self.dataChanged.emit(idx, idx)

    def apply_edit(self, row: int, value):
        """Правка без сигнала (после успешного применения к игре)."""
        if 0 <= row < len(self.rows):
            self.rows[row]["value"] = value


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
        self._scan_mode: str | None = None      # активный поиск по значению
        self._scan_value = None
        self._scan_prev: dict[str, object] = {}  # снимок на момент скана
        self._scan_hits: set[str] | None = None  # имена после «Уточнить»

        lay = QVBoxLayout(self)
        self.lbl_status = QLabel(TR("cheat_hint"))
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        # ── поиск по имени + управление ──
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

        # ── поиск по значению (как Cheat Engine) ──
        scan_bar = QHBoxLayout()
        scan_bar.addWidget(QLabel(TR("rpy_scan_value")))
        self.scan_value_edit = QLineEdit()
        self.scan_value_edit.setPlaceholderText("10000")
        self.scan_value_edit.returnPressed.connect(self._scan_start)
        scan_bar.addWidget(self.scan_value_edit, 1)
        self.scan_mode_combo = QComboBox()
        for _key, _label in _SCAN_MODES:
            self.scan_mode_combo.addItem(TR(_label), _key)
        scan_bar.addWidget(self.scan_mode_combo)
        btn_scan = QPushButton(TR("rpy_scan_go"))
        btn_scan.clicked.connect(self._scan_start)
        scan_bar.addWidget(btn_scan)
        btn_next = QPushButton(TR("rpy_scan_next"))
        btn_next.clicked.connect(self._scan_next)
        scan_bar.addWidget(btn_next)
        btn_reset = QPushButton(TR("rpy_scan_reset"))
        btn_reset.clicked.connect(self._scan_reset)
        scan_bar.addWidget(btn_reset)
        lay.addLayout(scan_bar)

        # ── таблица (виртуальная модель — 20k+ строк без лагов) ──
        self._model = _VarsTableModel(self)
        self._model.dataChanged.connect(self._on_model_edit)
        self.vars_table = QTableView()
        self.vars_table.setModel(self._model)
        self.vars_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.vars_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
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
        self._scan_reset()
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

    # ── фильтр + заполнение ──
    def _passes(self, v: dict) -> bool:
        if self.want_bool is None:
            pass  # no filter on bool/non-bool
        elif isinstance(v.get("value"), bool) != self.want_bool:
            return False
        if self._hide_text and isinstance(v.get("value"), str):
            return False
        if self._scan_mode is not None and not self._scan_match(v):
            return False
        return True

    @staticmethod
    def _row_key(v: dict):
        value = v.get("value")
        return (str(v["name"]), value if not isinstance(value, bool)
                else ("__b__" if value else "__b0__"))

    def _fill_vars(self):
        self._loading = True
        try:
            q = self.var_search.text().strip().lower() \
                if hasattr(self, "var_search") else ""
            rows = [v for v in self._vars if self._passes(v)
                    and (not q or q in str(v["name"]).lower()
                         or q in str(v.get("value")).lower())]
            keys = [self._row_key(v) for v in rows]
            old_keys = [self._row_key(v) for v in self._model.rows]
            # сброс модели только при реальном изменении — прокрутка и
            # авторефреш не пересоздают таблицу без необходимости
            if keys != old_keys:
                self._model.set_rows(rows)
            if self._scan_mode is not None:
                self.lbl_status.setText(TR("rpy_scan_found", n=len(rows)))
        finally:
            self._loading = False

    # ── применение правок ──
    def _on_model_edit(self, top_left, bottom_right):
        if self._loading:
            return
        index = top_left
        if index.column() != _VarsTableModel.COL_VALUE:
            return
        row = index.row()
        if not (0 <= row < len(self._model.rows)):
            return
        name = str(self._model.rows[row]["name"])
        value = self._model.rows[row]["value"]
        var = next((v for v in self._vars if str(v["name"]) == name), None)
        old = var.get("value") if var else None
        if isinstance(old, bool):
            # галочка: bool значение уже проставлено моделью
            pass
        else:
            value = self._coerce(value, old)
            if value is _INVALID:
                self.lbl_status.setText(TR("rpy_bad_value", name=name))
                self._model.revert(row, old)
                return
        if self._is_save_mode():
            self._apply_to_save(name, value, row, var, old)
        else:
            self._apply_to_game(name, value, row, var, old)

    def _apply_to_game(self, name, value, row, var, old):
        if self._cheat("var_set", name=name, value=value):
            self._model.apply_edit(row, value)
            if var is not None:
                var["value"] = value
            self.lbl_status.setText(TR("rpy_applied", name=name, value=value))
        else:
            self.lbl_status.setText(TR("cheat_no_bridge"))
            self._model.revert(row, old)

    def _apply_to_save(self, name, value, row, var, old):
        from app.core.twine import savefile
        try:
            savefile.set_variables(self._save_data, {name: value})
            savefile.write_save(self._save_path, self._save_data)
        except (ValueError, OSError) as e:
            self.lbl_status.setText(str(e))
            self._model.revert(row, old)
            return
        self._model.apply_edit(row, value)
        if var is not None:
            var["value"] = value
        self.lbl_status.setText(
            TR("vars_saved", name=name, value=value))

    @staticmethod
    def _coerce(text, old):
        if not isinstance(text, str):
            return text
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

    # ── поиск по значению (как Cheat Engine) ──
    def _scan_start(self):
        text = self.scan_value_edit.text().strip()
        if not text:
            self.lbl_status.setText(TR("rpy_scan_need_value"))
            return
        self._scan_value = self._coerce_scan(text)
        self._scan_prev = {str(v["name"]): v.get("value")
                           for v in self._vars}
        self._scan_hits = None
        self._scan_mode = SCAN_EQ
        self._fill_vars()

    def _scan_next(self):
        if self._scan_mode is None:
            self.lbl_status.setText(TR("rpy_scan_no_active"))
            return
        mode = self.scan_mode_combo.currentData() or SCAN_CHANGED
        # сравниваем текущий снимок с базой прошлого скана
        hits: set[str] = set()
        for v in self._vars:
            name = str(v["name"])
            if self._match_change(name, v.get("value"), mode):
                hits.add(name)
        self._scan_mode = mode
        self._scan_hits = hits
        self._scan_prev = {str(v["name"]): v.get("value")
                           for v in self._vars}
        self._fill_vars()

    def _scan_reset(self):
        self._scan_mode = None
        self._scan_value = None
        self._scan_prev = {}
        self._scan_hits = None

    @staticmethod
    def _coerce_scan(text: str):
        """1000 → int, 3.14 → float, иначе строка (как в Cheat Engine)."""
        text = text.strip()
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return text

    def _match_change(self, name: str, cur, mode: str) -> bool:
        old = self._scan_prev.get(name)
        if name not in self._scan_prev:
            return False
        if mode == SCAN_CHANGED:
            return old != cur
        if mode == SCAN_UNCHANGED:
            return old == cur
        if mode in (SCAN_INCREASED, SCAN_DECREASED):
            if isinstance(old, bool) or not isinstance(old, (int, float)):
                return False
            if isinstance(cur, bool) or not isinstance(cur, (int, float)):
                return False
            return (cur > old) if mode == SCAN_INCREASED else (cur < old)
        return True

    def _scan_match(self, v: dict) -> bool:
        if self._scan_mode == SCAN_EQ:
            return v.get("value") == self._scan_value
        return str(v["name"]) in (self._scan_hits or set())


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