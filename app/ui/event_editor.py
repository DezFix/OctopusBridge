# -*- coding: utf-8 -*-
"""Редактор событий RPG Maker: всё, что можно менять у события.

Диалог `EventEditorDialog` редактирует словарь события на месте:
- общие свойства (имя, позиция, страницы: добавить/дублировать/удалить);
- страница: изображение (персонаж/тайл с предпросмотром), триггер,
  приоритет, движение (тип/скорость/частота), опции, условия видимости
  (переключатели/переменная/self-switch), список команд.

Команды: добавление из полного каталога (по группам), редактирование
параметров (числа/строки/выборы), спец-редакторы для текста (401),
выборов (102), ветвлений (111), маршрутов (205/505), текстовых команд.
Поддерживаются форматы MZ (dict {code, indent, parameters}) и MV (list).
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPushButton, QScrollArea,
                               QSpinBox, QTabWidget, QTextEdit, QVBoxLayout,
                               QWidget)

from app.core.rpgmaker import commands as C
from app.core.rpgmaker import maprender
from app.ui.i18n import TR, current_lang


def _CL() -> str:
    """Текущий язык для каталога команд."""
    return current_lang()


def _triggers() -> list[str]:
    return [TR("map_trigger_0"), TR("map_trigger_1"), TR("map_trigger_2"),
            TR("map_trigger_3"), TR("map_trigger_4")]


def _priorities() -> list[str]:
    return [TR("ev_priority_0"), TR("ev_priority_1"), TR("ev_priority_2")]


def _moves() -> list[str]:
    return [TR("ev_move_0"), TR("ev_move_1"), TR("ev_move_2"), TR("ev_move_3")]


def _dirs() -> dict[int, str]:
    return {2: TR("ev_dir_down"), 4: TR("ev_dir_left"),
            6: TR("ev_dir_right"), 8: TR("ev_dir_up")}


DIR_ORDER = [2, 4, 6, 8]  # вниз, влево, вправо, вверх — стабильный порядок

_MV = object()  # маркер: команды в формате списка (MV)

# ─────────────────────────────────────────────────────────
# команды: универсальные помощники
# ─────────────────────────────────────────────────────────

def is_dict_cmd(cmd) -> bool:
    return isinstance(cmd, dict) and "code" in cmd


def cmd_code(cmd) -> int:
    return cmd["code"] if is_dict_cmd(cmd) else (cmd[0] if cmd else 0)


def cmd_indent(cmd) -> int:
    return cmd.get("indent", 0) if is_dict_cmd(cmd) else (cmd[1] if len(cmd) > 1 else 0)


def cmd_params(cmd) -> list:
    return cmd.get("parameters", []) if is_dict_cmd(cmd) else cmd[2:]


def make_cmd(code: int, indent: int = 0, params: list | None = None,
             fmt: dict | None = None) -> dict | list:
    params = list(params or [])
    if fmt is _MV:
        return [code, indent] + params
    return {"code": code, "indent": indent, "parameters": params}


def make_default_cmd(code: int, indent: int = 0,
                     fmt: dict | None = None) -> dict | list:
    """Команда с параметрами по умолчанию для спец-команд."""
    if code == 102:
        return make_cmd(code, indent, [[TR("ev_choice", n=1),
                                        TR("ev_choice", n=2)], 0, 0, 0], fmt)
    if code == 111:
        return make_cmd(code, indent, [0, 1, True], fmt)
    if code == 205:
        return make_cmd(code, indent, [0], fmt)
    if code == 505:
        return make_cmd(code, indent, [1], fmt)
    if code == 201:
        return make_cmd(code, indent, [0, 1, 0, 0, 2, 0], fmt)
    if code == 121:
        return make_cmd(code, indent, [1, 1, 0], fmt)
    if code == 122:
        # [startId, endId, operationType, operand, operandId, value]
        return make_cmd(code, indent, [1, 1, 0, 0, 0, 0], fmt)
    if code in (117, 230, 212, 213, 231, 232, 233, 234, 235, 236,
                241, 242, 243, 244, 245, 246, 250, 301, 302, 303,
                311, 312, 313, 314, 315, 316, 317, 318, 319, 320,
                321, 322, 323, 324, 341, 342):
        return make_cmd(code, indent, [], fmt)
    return make_cmd(code, indent, [], fmt)


def cmd_summary(cmd) -> str:
    """Короткое описание команды для списка."""
    code = cmd_code(cmd)
    name = C.command_name(code, _CL())
    params = cmd_params(cmd)
    if code == 401 and params and isinstance(params[0], str):
        return f"{name}: {params[0]}"
    if code == 101 and len(params) >= 2 and isinstance(params[0], str):
        return f"{name} ({params[0]} {params[1]})"
    if code == 108:
        return f"{name}: {params[0] if params else ''}"
    if code == 102:
        choices = params[0] if params and isinstance(params[0], list) else []
        return f"{name} [{', '.join(str(c) for c in choices[:3])}]"
    if code == 111:
        return f"{name}: {_cond_brief(params)}"
    if code == 117 and params:
        return f"{name} #{params[0]}"
    if code in (121, 123) and params:
        return f"{name}: {params[0]}..{params[1] if len(params) > 1 else params[0]}"
    if code == 201 and len(params) >= 2:
        return TR("ev_cmd_map", name=name, mid=params[1], x=params[2],
                  y=params[3])
    if code == 230 and params:
        return f"{name}: {params[0]}"
    if code == 241 and params:
        return f"{name}: {params[0]}"
    if code == 505:
        return C.route_command_name(params[0] if params else 0, _CL())
    if code in (355, 356) and params and isinstance(params[0], str):
        return f"{name}: {params[0]}"
    if code == 357 and len(params) > 1 and isinstance(params[1], str):
        return f"{name}: {params[1]}"
    if code == 655 and params and isinstance(params[0], str):
        return f"{name}: {params[0]}"
    if code in (402, 403, 404, 411, 412, 113, 115, 221, 222, 249,
                214, 206):
        return name
    return name


def _cond_brief(params: list) -> str:
    if not params:
        return ""
    t = params[0]
    if t == 0 and len(params) >= 2:
        return TR("ev_cond_switch", id=params[1])
    if t == 1 and len(params) >= 4:
        op = (["==", ">=", "<=", ">", "<", "!="][params[2]]
              if params[2] < 6 else "?")
        return TR("ev_cond_var", id=params[1], op=op, v=params[3])
    if t == 2 and len(params) >= 2:
        return TR("ev_cond_self", id=params[1])
    if t == 3 and len(params) >= 2:
        return TR("ev_cond_timer", s=params[1])
    if t == 4 and len(params) >= 4:
        return TR("ev_cond_actor", id=params[1])
    if t == 6 and len(params) >= 4:
        return TR("ev_cond_char", id=params[1])
    if t == 7 and len(params) >= 3:
        return TR("ev_cond_gold", v=params[2])
    if t == 8 and len(params) >= 3:
        return TR("ev_cond_item", v=params[2])
    if t == 11 and len(params) >= 2:
        return TR("ev_cond_button", id=params[1])
    if t == 12 and len(params) >= 2:
        return TR("ev_cond_script", s=params[1])
    return TR("ev_cond_type", t=t)


# ─────────────────────────────────────────────────────────
# редактор параметров (generic)
# ─────────────────────────────────────────────────────────

class _ParamRow(QWidget):
    """Один параметр: подпись + поле (число/строка/выбор)."""

    def __init__(self, spec, value):
        super().__init__()
        typ, label = spec[0], spec[1]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(label))
        if typ == "e":
            options = spec[2]
            self.widget = QComboBox()
            self.widget.addItems(options)
            if isinstance(value, int) and 0 <= value < len(options):
                self.widget.setCurrentIndex(value)
        elif typ == "b":
            self.widget = QCheckBox(label)
            lay.addWidget(self.widget)
            self.widget.setChecked(bool(value))
            lay.addStretch(1)
            return
        elif typ == "n":
            self.widget = QSpinBox()
            self.widget.setRange(-2_000_000_000, 2_000_000_000)
            try:
                self.widget.setValue(int(value))
            except (ValueError, TypeError):
                self.widget.setValue(0)
        else:  # s / any
            self.widget = QLineEdit(str(value) if value is not None else "")
        lay.addWidget(self.widget, 1)

    def value(self):
        w = self.widget
        if isinstance(w, QComboBox):
            return w.currentIndex()
        if isinstance(w, QCheckBox):
            return w.isChecked()
        if isinstance(w, QSpinBox):
            return w.value()
        text = w.text()
        if text.lstrip("-").isdigit():
            return int(text)
        return text


class _GenericParamsDialog(QDialog):
    """Редактор параметров команды по схеме каталога."""

    def __init__(self, parent, code: int, params: list, extra: bool = True):
        super().__init__(parent)
        self.setWindowTitle(C.command_name(code, _CL()))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.rows: list[_ParamRow] = []
        specs = C.command_params(code, _CL())
        # параметры, которых нет в схеме, показываем как «дополнительные»
        shown = 0
        for i, spec in enumerate(specs):
            value = params[i] if i < len(params) else _default_for(spec)
            row = _ParamRow(spec, value)
            self.rows.append(row)
            form.addRow("", row)
            shown = i + 1
        for j in range(shown, len(params)):
            row = _ParamRow(("any", TR("ev_param", n=j + 1)), params[j])
            self.rows.append(row)
            form.addRow("", row)
        if extra and len(params) > shown:
            pass
        lay.addLayout(form)
        if not specs and not params:
            lay.addWidget(QLabel(TR("cmd_no_params")))
        btns = QDialogButtonBox(QDialogButtonBox.Ok
                                | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def values(self) -> list:
        return [r.value() for r in self.rows]


def _default_for(spec: tuple) -> object:
    if spec[0] == "n":
        return 0
    if spec[0] == "b":
        return False
    if spec[0] == "e":
        return 0
    return ""


# ─────────────────────────────────────────────────────────
# спец-редакторы команд
# ─────────────────────────────────────────────────────────

class _TextCmdDialog(QDialog):
    """Текст 401: многострочный редактор."""

    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle(TR("cmd_text"))
        lay = QVBoxLayout(self)
        self.ed = QTextEdit()
        self.ed.setPlainText(text.replace("\\n", "\n"))
        lay.addWidget(self.ed)
        btns = QDialogButtonBox(QDialogButtonBox.Ok
                                | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def text(self) -> str:
        return self.ed.toPlainText().replace("\n", "\\n")


class _ChoicesDialog(QDialog):
    """Выборы 102: список вариантов + параметры."""

    def __init__(self, parent, params: list):
        super().__init__(parent)
        self.setWindowTitle(TR("cmd_choices"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        choices = params[0] if params and isinstance(params[0], list) \
            else [TR("ev_choice", n=1), TR("ev_choice", n=2)]
        self.list = QListWidget()
        self.list.addItems([str(c) for c in choices])
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        for label, fn in ((TR("cmd_add"), self._add),
                          (TR("cmd_edit"), self._edit),
                          (TR("cmd_del"), self._del)):
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        form = QFormLayout()
        self.sp_cancel = QSpinBox()
        self.sp_cancel.setRange(0, 4)
        self.sp_cancel.setValue(params[1] if len(params) > 1 else 0)
        form.addRow(TR("cmd_cancel"), self.sp_cancel)
        self.sp_position = QSpinBox()
        self.sp_position.setRange(0, 2)
        self.sp_position.setValue(params[3] if len(params) > 3 else 0)
        form.addRow(TR("cmd_position"), self.sp_position)
        self.sp_default = QSpinBox()
        self.sp_default.setRange(0, 4)
        self.sp_default.setValue(params[2] if len(params) > 2 else 0)
        form.addRow(TR("cmd_default"), self.sp_default)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok
                                | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _add(self):
        self.list.addItem(TR("cmd_choice_new"))

    def _edit(self):
        it = self.list.currentItem()
        if not it:
            return
        dlg = _TextCmdDialog(self, it.text())
        if dlg.exec() == QDialog.Accepted:
            it.setText(dlg.text())

    def _del(self):
        it = self.list.currentItem()
        if it:
            self.list.takeItem(self.list.row(it))

    def values(self) -> list:
        return [[self.list.item(i).text()
                 for i in range(self.list.count())],
                self.sp_cancel.value(), self.sp_position.value(),
                self.sp_default.value()]


class _CondDialog(QDialog):
    """Условное ветвление 111."""

    @staticmethod
    def _types() -> list[str]:
        return [TR("ev_cond_t_switch"), TR("ev_cond_t_var"),
                TR("ev_cond_t_self"), TR("ev_cond_t_timer"),
                TR("ev_cond_t_actor"), TR("ev_cond_t_enemy"),
                TR("ev_cond_t_char"), TR("ev_cond_t_gold"),
                TR("ev_cond_t_item"), TR("ev_cond_t_weapon"),
                TR("ev_cond_t_armor"), TR("ev_cond_t_button"),
                TR("ev_cond_t_script")]

    def __init__(self, parent, params: list):
        super().__init__(parent)
        self.setWindowTitle(TR("cmd_cond"))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        t = params[0] if params else 0
        self.cb_type = QComboBox()
        self.cb_type.addItems(self._types())
        self.cb_type.setCurrentIndex(t)
        self.cb_type.currentIndexChanged.connect(self._sync)
        form.addRow(TR("cmd_cond_type"), self.cb_type)

        self.sp1 = QSpinBox()
        self.sp1.setRange(0, 2_000_000_000)
        self.sp2 = QSpinBox()
        self.sp2.setRange(-2_000_000_000, 2_000_000_000)
        self.ed_script = QLineEdit()
        self.cb_op = QComboBox()
        self.cb_op.addItems(["==", ">=", "<=", ">", "<", "!="])
        form.addRow(TR("cmd_cond_p1"), self.sp1)
        form.addRow(TR("cmd_cond_op"), self.cb_op)
        form.addRow(TR("cmd_cond_p2"), self.sp2)
        form.addRow(TR("cmd_cond_script"), self.ed_script)
        lay.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.Ok
                                | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        # текущие значения
        if len(params) >= 2 and isinstance(params[1], (int, str)):
            if isinstance(params[1], str) and not str(params[1]).isdigit():
                self.ed_script.setText(str(params[1]))
            else:
                try:
                    self.sp1.setValue(int(params[1]))
                except (ValueError, TypeError):
                    pass
        if len(params) >= 3:
            try:
                self.sp2.setValue(int(params[2]))
            except (ValueError, TypeError):
                pass
        self._sync()

    def _sync(self):
        t = self.cb_type.currentIndex()
        script = t == 12
        self.ed_script.setVisible(script)
        self.cb_op.setVisible(t == 1)
        self.sp2.setVisible(t in (1, 4, 5, 6, 7, 8, 9, 10))

    def values(self) -> list:
        t = self.cb_type.currentIndex()
        if t == 12:
            return [t, self.ed_script.text()]
        if t == 1:
            return [t, self.sp1.value(), self.cb_op.currentIndex(),
                    self.sp2.value(), self.sp2.value()]
        if t in (4, 5, 6, 7, 8, 9, 10):
            return [t, self.sp1.value(), 0, self.sp2.value(),
                    self.sp2.value()]
        return [t, self.sp1.value()]


class _RouteDialog(QDialog):
    """Маршрут движения 205: список команд 505."""

    def __init__(self, parent, page, fmt):
        super().__init__(parent)
        self.setWindowTitle(TR("cmd_route"))
        self.setMinimumSize(460, 360)
        self._fmt = fmt
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.sp_char = QSpinBox()
        self.sp_char.setRange(0, 999)
        params = cmd_params(page) if page else []
        try:
            self.sp_char.setValue(int(params[0]) if params else 0)
        except (ValueError, TypeError):
            self.sp_char.setValue(0)
        form.addRow(TR("cmd_route_char"), self.sp_char)
        lay.addLayout(form)
        self.list = QListWidget()
        self._routes = []
        for cmd in (params[1] if len(params) > 1 and isinstance(params[1], list)
                    else []):
            if not cmd:
                continue
            self._routes.append(cmd)
            code = cmd_code(cmd)
            self.list.addItem(C.route_command_name(code, _CL()))
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        btn_add = QPushButton(TR("cmd_add"))
        btn_add.clicked.connect(self._add)
        btn_edit = QPushButton(TR("cmd_edit"))
        btn_edit.clicked.connect(self._edit)
        btn_del = QPushButton(TR("cmd_del"))
        btn_del.clicked.connect(self._del)
        for b in (btn_add, btn_edit, btn_del):
            row.addWidget(b)
        lay.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.Ok
                                | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _add(self):
        menu = QMenu(self)
        for code in sorted(C.ROUTE_COMMANDS):
            name = C.route_command_name(code, _CL())
            act = menu.addAction(name)
            act.triggered.connect(
                lambda c=code: self._append(make_cmd(c, 0, [], self._fmt)))
        menu.exec(self.list.mapToGlobal(
            self.list.rect().topRight()))

    def _append(self, cmd):
        self._routes.append(cmd)
        self.list.addItem(C.route_command_name(cmd_code(cmd), _CL()))

    def _edit(self):
        row = self.list.currentRow()
        if row < 0:
            return
        cmd = self._routes[row]
        code = cmd_code(cmd)
        dlg = _GenericParamsDialog(self, code, cmd_params(cmd))
        if dlg.exec() == QDialog.Accepted:
            vals = dlg.values()
            if is_dict_cmd(cmd):
                cmd["parameters"] = vals
            else:
                self._routes[row] = make_cmd(code, 0, vals, self._fmt)
            self.list.item(row).setText(
                C.route_command_name(code, _CL()))

    def _del(self):
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            del self._routes[row]

    def values(self):
        return [self.sp_char.value(), self._routes]


# ─────────────────────────────────────────────────────────
# список команд страницы
# ─────────────────────────────────────────────────────────

class _CommandListEditor(QWidget):
    """Список команд страницы: добавить/изменить/удалить/сдвинуть."""

    def __init__(self, parent, fmt):
        super().__init__()
        self._dialog = parent
        self._fmt = fmt
        self._cmds: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SingleSelection)
        self.list.itemDoubleClicked.connect(lambda _: self._edit())
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        btn_add = QPushButton(TR("cmd_add"))
        btn_add.clicked.connect(self._add)
        btn_edit = QPushButton(TR("cmd_edit"))
        btn_edit.clicked.connect(self._edit)
        btn_del = QPushButton(TR("cmd_del"))
        btn_del.clicked.connect(self._del)
        btn_up = QPushButton(TR("cmd_up"))
        btn_up.clicked.connect(lambda: self._move(-1))
        btn_down = QPushButton(TR("cmd_down"))
        btn_down.clicked.connect(lambda: self._move(1))
        for b in (btn_add, btn_edit, btn_del, btn_up, btn_down):
            row.addWidget(b)
        lay.addLayout(row)

    def set_commands(self, cmds: list):
        self._cmds = cmds
        self.list.clear()
        for cmd in cmds:
            if not cmd:
                continue
            self.list.addItem(QListWidgetItem(cmd_summary(cmd)))

    def _indent(self, cmd) -> int:
        return cmd_indent(cmd)

    def _add(self):
        menu = QMenu(self)
        for group in C.groups(_CL()):
            sub = menu.addMenu(group)
            for code in sorted(C.COMMANDS):
                if C.command_group(code, _CL()) != group:
                    continue
                if code in (401, 402, 403, 404, 405, 408, 411, 412,
                            505, 601, 602, 603, 604, 605, 655, 657):
                    continue  # континуаторы — только автоматически
                act = sub.addAction(C.command_name(code, _CL()))
                act.triggered.connect(
                    lambda c=code: self._insert_cmd(make_default_cmd(
                        c, self._indent(self._cmds[-1]) if self._cmds
                        else 0, self._fmt)))
        menu.exec(self.list.mapToGlobal(self.list.rect().bottomLeft()))

    def _insert_cmd(self, cmd, after: int | None = None):
        row = after if after is not None else self.list.currentRow()
        if row is None or row < 0:
            row = len(self._cmds)
        self._cmds.insert(row, cmd)
        item = QListWidgetItem(cmd_summary(cmd))
        self.list.insertItem(row, item)
        self.list.setCurrentRow(row)
        self._after_insert(cmd)

    def _after_insert(self, cmd):
        """Спец-команды: сразу создать континуаторы."""
        code = cmd_code(cmd)
        row = self._cmds.index(cmd)
        indent = cmd_indent(cmd)
        if code == 101:
            self._insert_cmd(
                make_cmd(401, indent, [TR("cmd_text_ph")], self._fmt), after=row + 1)
        elif code == 102:
            self._insert_cmd(
                make_cmd(402, indent, [0, TR("cmd_choice_1")], self._fmt),
                after=row + 1)
            self._insert_cmd(
                make_cmd(404, indent, [], self._fmt), after=row + 1)
        elif code == 111:
            self._insert_cmd(
                make_cmd(411, indent, [], self._fmt), after=row + 1)
            self._insert_cmd(
                make_cmd(412, indent, [], self._fmt), after=row + 1)
        elif code == 205:
            self._insert_cmd(
                make_cmd(505, indent, [1], self._fmt), after=row + 1)

    def _edit(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self._cmds):
            return
        cmd = self._cmds[row]
        code = cmd_code(cmd)
        params = cmd_params(cmd)
        if code == 401:
            dlg = _TextCmdDialog(self, params[0] if params else "")
            if dlg.exec() != QDialog.Accepted:
                return
            if is_dict_cmd(cmd):
                cmd["parameters"] = [dlg.text()]
            else:
                self._cmds[row] = make_cmd(code, cmd_indent(cmd),
                                           [dlg.text()], self._fmt)
        elif code == 102:
            dlg = _ChoicesDialog(self, params)
            if dlg.exec() != QDialog.Accepted:
                return
            if is_dict_cmd(cmd):
                cmd["parameters"] = dlg.values()
            else:
                self._cmds[row] = make_cmd(code, cmd_indent(cmd),
                                           dlg.values(), self._fmt)
        elif code == 111:
            dlg = _CondDialog(self, params)
            if dlg.exec() != QDialog.Accepted:
                return
            if is_dict_cmd(cmd):
                cmd["parameters"] = dlg.values()
            else:
                self._cmds[row] = make_cmd(code, cmd_indent(cmd),
                                           dlg.values(), self._fmt)
        elif code == 205:
            dlg = _RouteDialog(self, cmd, self._fmt)
            if dlg.exec() != QDialog.Accepted:
                return
            if is_dict_cmd(cmd):
                cmd["parameters"] = dlg.values()
            else:
                self._cmds[row] = make_cmd(code, cmd_indent(cmd),
                                           dlg.values(), self._fmt)
        elif code == 505:
            dlg = _GenericParamsDialog(self, code, params, extra=False)
            if dlg.exec() != QDialog.Accepted:
                return
            if is_dict_cmd(cmd):
                cmd["parameters"] = dlg.values()
            else:
                self._cmds[row] = make_cmd(code, cmd_indent(cmd),
                                           dlg.values(), self._fmt)
        else:
            dlg = _GenericParamsDialog(self, code, params)
            if dlg.exec() != QDialog.Accepted:
                return
            if is_dict_cmd(cmd):
                cmd["parameters"] = dlg.values()
            else:
                self._cmds[row] = make_cmd(code, cmd_indent(cmd),
                                           dlg.values(), self._fmt)
        self.list.item(row).setText(cmd_summary(self._cmds[row]))

    def _del(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._cmds):
            del self._cmds[row]
            self.list.takeItem(row)

    def _move(self, delta: int):
        row = self.list.currentRow()
        new = row + delta
        if 0 <= row < len(self._cmds) and 0 <= new < len(self._cmds):
            self._cmds[row], self._cmds[new] = \
                self._cmds[new], self._cmds[row]
            self.list.takeItem(row)
            self.list.insertItem(new, QListWidgetItem(
                cmd_summary(self._cmds[new])))
            self.list.setCurrentRow(new)


# ─────────────────────────────────────────────────────────
# редактор страницы
# ─────────────────────────────────────────────────────────

class _PageEditor(QWidget):
    """Все свойства одной страницы события."""

    def __init__(self, game_dir, view, fmt):
        super().__init__()
        self._game_dir = game_dir
        self._view = view
        self._fmt = fmt
        lay = QVBoxLayout(self)
        split = QHBoxLayout()
        lay.addLayout(split, 1)

        props = QWidget()
        props.setFixedWidth(380)
        form = QFormLayout(props)

        self.cb_image = QComboBox()
        self._char_names = self._characters()
        self.cb_image.addItem(TR("ev_none"))
        self.cb_image.addItems(self._char_names)
        self.cb_image.currentIndexChanged.connect(self._preview)
        form.addRow(TR("ev_image"), self.cb_image)

        img_row = QHBoxLayout()
        self.sp_char_index = QSpinBox()
        self.sp_char_index.setRange(0, 7)
        self.sp_direction = QComboBox()
        self.sp_direction.addItems(list(_dirs().values()))
        self.sp_pattern = QSpinBox()
        self.sp_pattern.setRange(1, 3)
        self.lbl_preview = QLabel()
        self.lbl_preview.setFixedSize(48, 64)
        self.lbl_preview.setStyleSheet(
            "background: #222; border: 1px solid #555;")
        img_row.addWidget(self.sp_char_index)
        img_row.addWidget(self.sp_direction)
        img_row.addWidget(self.sp_pattern)
        img_row.addWidget(self.lbl_preview, 1)
        form.addRow(TR("ev_image_opt"), img_row)

        self.sp_tile = QSpinBox()
        self.sp_tile.setRange(0, 8191)
        form.addRow(TR("ev_tile"), self.sp_tile)

        self.cb_trigger = QComboBox()
        self.cb_trigger.addItems(_triggers())
        form.addRow(TR("ev_trigger"), self.cb_trigger)

        self.cb_priority = QComboBox()
        self.cb_priority.addItems(_priorities())
        form.addRow(TR("ev_priority"), self.cb_priority)

        self.cb_move = QComboBox()
        self.cb_move.addItems(_moves())
        form.addRow(TR("ev_move"), self.cb_move)

        speed_row = QHBoxLayout()
        self.sp_speed = QSpinBox()
        self.sp_speed.setRange(1, 6)
        self.sp_freq = QSpinBox()
        self.sp_freq.setRange(1, 6)
        speed_row.addWidget(QLabel(TR("ev_speed")))
        speed_row.addWidget(self.sp_speed)
        speed_row.addWidget(QLabel(TR("ev_freq")))
        speed_row.addWidget(self.sp_freq)
        speed_row.addStretch(1)
        form.addRow("", speed_row)

        self.cb_walk = QCheckBox(TR("ev_walk_anime"))
        self.cb_step = QCheckBox(TR("ev_step_anime"))
        self.cb_dfix = QCheckBox(TR("ev_dir_fix"))
        self.cb_through = QCheckBox(TR("ev_through"))
        opts = QHBoxLayout()
        for cb in (self.cb_walk, self.cb_step, self.cb_dfix,
                   self.cb_through):
            opts.addWidget(cb)
        opts.addStretch(1)
        form.addRow(TR("ev_options"), opts)

        # ── условия видимости ──
        cond = QWidget()
        cl = QVBoxLayout(cond)
        cl.setContentsMargins(0, 0, 0, 0)
        self.cb_sw1 = QCheckBox(TR("ev_sw1"))
        self.sp_sw1 = QSpinBox()
        self.sp_sw1.setRange(1, 9999)
        r1 = QHBoxLayout()
        r1.addWidget(self.cb_sw1)
        r1.addWidget(self.sp_sw1)
        r1.addStretch(1)
        cl.addLayout(r1)
        self.cb_sw2 = QCheckBox(TR("ev_sw2"))
        self.sp_sw2 = QSpinBox()
        self.sp_sw2.setRange(1, 9999)
        r2 = QHBoxLayout()
        r2.addWidget(self.cb_sw2)
        r2.addWidget(self.sp_sw2)
        r2.addStretch(1)
        cl.addLayout(r2)
        self.cb_var = QCheckBox(TR("ev_var"))
        self.sp_var = QSpinBox()
        self.sp_var.setRange(1, 9999)
        self.sp_var_val = QSpinBox()
        self.sp_var_val.setRange(-2_000_000_000, 2_000_000_000)
        r3 = QHBoxLayout()
        r3.addWidget(self.cb_var)
        r3.addWidget(self.sp_var)
        r3.addWidget(QLabel("≥"))
        r3.addWidget(self.sp_var_val)
        r3.addStretch(1)
        cl.addLayout(r3)
        self.cb_self = QCheckBox(TR("ev_self"))
        self.sp_self = QComboBox()
        self.sp_self.addItems(["A", "B", "C", "D"])
        r4 = QHBoxLayout()
        r4.addWidget(self.cb_self)
        r4.addWidget(self.sp_self)
        r4.addStretch(1)
        cl.addLayout(r4)
        form.addRow(TR("ev_conditions"), cond)

        self.cmd_editor = _CommandListEditor(self, fmt)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(props)
        split.addWidget(scroll, 0)
        split.addWidget(self.cmd_editor, 1)

    def _characters(self) -> list[str]:
        if not self._game_dir:
            return []
        try:
            base = os.path.join(self._game_dir, "img", "characters")
            names = []
            for root, dirs, files in os.walk(base):
                for f in sorted(files):
                    if f.endswith((".png", ".png_")):
                        rel = os.path.relpath(os.path.join(root, f), base)
                        names.append(os.path.splitext(rel)[0].replace("\\", "/"))
            return names
        except OSError:
            return []

    def _preview(self):
        name = self.cb_image.currentText()
        if not name or name == TR("ev_none"):
            self.lbl_preview.clear()
            return
        from app.core.rpgmaker import crypto
        raw = crypto.read_image(
            self._game_dir or "", f"img/characters/{name}",
            view=self._view)
        if not raw:
            self.lbl_preview.setText("?")
            return
        img = QPixmap()
        img.loadFromData(raw, "PNG")
        if img.isNull():
            self.lbl_preview.setText("?")
            return
        idx = self.sp_char_index.value()
        dir_idx = max(0, self.sp_direction.currentIndex())
        cw = img.width() / 12
        ch = img.height() / 8
        col, row = idx % 4, idx // 4
        sx = col * 3 * cw + 0 * cw
        sy = row * 4 * ch + dir_idx * ch
        crop = img.copy(int(sx), int(sy), int(cw), int(ch))
        self.lbl_preview.setPixmap(
            crop.scaled(48, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_page(self, page: dict):
        img = page.get("image") or {}
        name = img.get("characterName") or ""
        if name:
            idx = self.cb_image.findText(name)
            self.cb_image.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.cb_image.setCurrentIndex(0)
        self.sp_char_index.setValue(img.get("characterIndex", 0))
        dir_idx = DIR_ORDER.index(img.get("direction", 2)) \
            if img.get("direction") in DIR_ORDER else 0
        self.sp_direction.setCurrentIndex(dir_idx)
        self.sp_pattern.setValue(img.get("pattern", 1))
        self.sp_tile.setValue(img.get("tileId", 0))
        self.cb_trigger.setCurrentIndex(page.get("trigger", 0))
        self.cb_priority.setCurrentIndex(page.get("priorityType", 0))
        self.cb_move.setCurrentIndex(page.get("moveType", 0))
        self.sp_speed.setValue(page.get("moveSpeed", 3))
        self.sp_freq.setValue(page.get("moveFrequency", 3))
        self.cb_walk.setChecked(page.get("walkAnime", True))
        self.cb_step.setChecked(page.get("stepAnime", False))
        self.cb_dfix.setChecked(page.get("directionFix", False))
        self.cb_through.setChecked(page.get("through", False))
        c = page.get("conditions") or {}
        self.cb_sw1.setChecked(bool(c.get("switch1Valid")))
        self.sp_sw1.setValue(c.get("switch1Id", 1))
        self.cb_sw2.setChecked(bool(c.get("switch2Valid")))
        self.sp_sw2.setValue(c.get("switch2Id", 1))
        self.cb_var.setChecked(bool(c.get("variableValid")))
        self.sp_var.setValue(c.get("variableId", 1))
        self.sp_var_val.setValue(c.get("variableValue", 0))
        self.cb_self.setChecked(bool(c.get("selfSwitchValid")))
        si = "ABCD".find(str(c.get("selfSwitchCh", "A")))
        self.sp_self.setCurrentIndex(max(0, si))
        self.cmd_editor.set_commands(page.get("list") or [])
        self._preview()

    def apply_to(self, page: dict):
        name = self.cb_image.currentText()
        img = page.setdefault("image", {})
        if name and name != TR("ev_none"):
            img["characterName"] = name
            img["characterIndex"] = self.sp_char_index.value()
            img["direction"] = DIR_ORDER[
                self.sp_direction.currentIndex()]
            img["pattern"] = self.sp_pattern.value()
            if img.get("tileId"):
                img["tileId"] = 0
        else:
            for k in ("characterName", "characterIndex", "direction",
                      "pattern"):
                img.pop(k, None)
            tile = self.sp_tile.value()
            if tile:
                img["tileId"] = tile
            else:
                img.pop("tileId", None)
        page["trigger"] = self.cb_trigger.currentIndex()
        page["priorityType"] = self.cb_priority.currentIndex()
        page["moveType"] = self.cb_move.currentIndex()
        page["moveSpeed"] = self.sp_speed.value()
        page["moveFrequency"] = self.sp_freq.value()
        page["walkAnime"] = self.cb_walk.isChecked()
        page["stepAnime"] = self.cb_step.isChecked()
        page["directionFix"] = self.cb_dfix.isChecked()
        page["through"] = self.cb_through.isChecked()
        c = page.setdefault("conditions", {})
        c["switch1Valid"] = self.cb_sw1.isChecked()
        c["switch1Id"] = self.sp_sw1.value()
        c["switch2Valid"] = self.cb_sw2.isChecked()
        c["switch2Id"] = self.sp_sw2.value()
        c["variableValid"] = self.cb_var.isChecked()
        c["variableId"] = self.sp_var.value()
        c["variableValue"] = self.sp_var_val.value()
        c["selfSwitchValid"] = self.cb_self.isChecked()
        c["selfSwitchCh"] = "ABCD"[self.sp_self.currentIndex()]
        if not any(c.values()):
            page.pop("conditions", None)
        page["list"] = list(self.cmd_editor._cmds)
        if not page["list"]:
            page.pop("list", None)


# ─────────────────────────────────────────────────────────
# главный диалог
# ─────────────────────────────────────────────────────────

class EventEditorDialog(QDialog):
    """Полный редактор события: страницы, изображение, условия, команды."""

    def __init__(self, parent, game_dir, view, ev: dict):
        super().__init__(parent)
        self._ev = ev
        self._game_dir = game_dir
        self._view = view
        self._fmt = None
        pages = ev.get("pages") or []
        self._orig_pages = len(pages)
        s = maprender.event_summary(ev)
        self.setWindowTitle(f"EV{s['id']} — {s['name']}")
        self.setMinimumSize(1180, 640)

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_name = QLineEdit(s["name"])
        form.addRow(TR("map_name"), self.ed_name)
        pos = QHBoxLayout()
        self.sp_x = QSpinBox()
        self.sp_x.setRange(0, 9999)
        self.sp_x.setValue(s["x"])
        self.sp_y = QSpinBox()
        self.sp_y.setRange(0, 9999)
        self.sp_y.setValue(s["y"])
        pos.addWidget(QLabel("X:"))
        pos.addWidget(self.sp_x)
        pos.addWidget(QLabel("Y:"))
        pos.addWidget(self.sp_y)
        pos.addStretch(1)
        form.addRow(TR("map_pos"), pos)
        lay.addLayout(form)

        pages_row = QHBoxLayout()
        pages_row.addWidget(QLabel(TR("ev_pages")))
        self.cb_pages = QComboBox()
        self.cb_pages.currentIndexChanged.connect(self._page_changed)
        pages_row.addWidget(self.cb_pages, 1)
        btn_add_page = QPushButton(TR("ev_add_page"))
        btn_add_page.clicked.connect(self._add_page)
        btn_dup_page = QPushButton(TR("ev_dup_page"))
        btn_dup_page.clicked.connect(self._dup_page)
        btn_del_page = QPushButton(TR("ev_del_page"))
        btn_del_page.clicked.connect(self._del_page)
        for b in (btn_add_page, btn_dup_page, btn_del_page):
            pages_row.addWidget(b)
        lay.addLayout(pages_row)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Save
                                | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._rebuild_pages()

    def _page_index(self) -> int:
        return self.cb_pages.currentIndex()

    def _fmt_of(self, page: dict) -> dict | object | None:
        """Формат команд: MZ (dict) или MV (list)."""
        lst = page.get("list") or []
        for cmd in lst:
            if cmd:
                return _MV if isinstance(cmd, list) else None
        return None

    def _rebuild_pages(self):
        self.cb_pages.blockSignals(True)
        self.cb_pages.clear()
        pages = self._ev.get("pages") or []
        for i, pg in enumerate(pages):
            cond = maprender.visibility_text(pg)
            self.cb_pages.addItem(
                f"{i + 1}  [{_triggers()[pg.get('trigger', 0)]}]  {cond}")
        self.cb_pages.blockSignals(False)
        while self.tabs.count():
            w = self.tabs.widget(0)
            self.tabs.removeTab(0)
            w.deleteLater()
        for i, pg in enumerate(pages):
            fmt = self._fmt_of(pg) if self._fmt is None else self._fmt
            if self._fmt is None and fmt is not None:
                self._fmt = fmt
            ed = _PageEditor(self._game_dir, self._view, self._fmt)
            ed.set_page(pg)
            self.tabs.addTab(ed, f"{i + 1}")
        self.cb_pages.setCurrentIndex(0)

    def _page_changed(self, idx: int):
        if 0 <= idx < self.tabs.count():
            self.tabs.setCurrentIndex(idx)

    def _new_page(self) -> dict:
        return {
            "conditions": {},
            "directionFix": False,
            "image": {},
            "list": [make_cmd(108, 0, [TR("cmd_new_page_comment")],
                              self._fmt)],
            "moveFrequency": 3,
            "moveRoute": {"list": [], "repeat": True, "skippable": False,
                          "wait": False},
            "moveSpeed": 3,
            "moveType": 0,
            "priorityType": 0,
            "stepAnime": False,
            "through": False,
            "trigger": 0,
            "walkAnime": True,
        }

    def _add_page(self):
        pages = self._ev.setdefault("pages", [])
        pages.append(self._new_page())
        self._rebuild_pages()
        self.cb_pages.setCurrentIndex(len(pages) - 1)

    def _dup_page(self):
        import copy
        pages = self._ev.setdefault("pages", [])
        if not pages:
            return
        src = pages[self._page_index()]
        pages.insert(self._page_index() + 1, copy.deepcopy(src))
        self._rebuild_pages()
        self.cb_pages.setCurrentIndex(self._page_index() + 1)

    def _del_page(self):
        pages = self._ev.get("pages") or []
        if len(pages) <= 1:
            QMessageBox.information(
                self, TR("ev_no_del"), TR("ev_no_del"))
            return
        idx = self._page_index()
        del pages[idx]
        self._rebuild_pages()
        self.cb_pages.setCurrentIndex(min(idx, len(pages) - 1))

    def accept(self) -> None:
        ev = self._ev
        ev["name"] = self.ed_name.text()
        ev["x"] = self.sp_x.value()
        ev["y"] = self.sp_y.value()
        pages = ev.get("pages") or []
        for i, pg in enumerate(pages):
            if i < self.tabs.count():
                self.tabs.widget(i).apply_to(pg)
        super().accept()