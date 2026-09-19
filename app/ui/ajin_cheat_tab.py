# -*- coding: utf-8 -*-
"""Читы AjinSyoujyo: «Переменные» и «Триггеры» в реальном времени.

Механика унаследована от app.ui.renpy_cheat_tab (та же шина):
вкладка слушает сигналы главного окна bridge_vars / bridge_cheat_ack /
bridge_client, раз в секунду тянет get_vars из игры и отправляет
var_set при правке. Здесь только Ajin-специфика:

- переменные Tyrano: f.* (stat.f), sf.* (variable.sf), tf.* (variable.tf);
- щупальце — AjinTentacle (CDP к Electron), команды get_vars/var_set/exec;
- консоль с примерами kag вместо renpy/sugarcube;
- save-режим скрыт (у Ajin сейвы бинарные, не SugarCube).

Как пользоваться: вкладка «Читы» → «Запустить игру» (или «Домой»):
список сам обновляется из игры раз в секунду; двойной клик по
значению, новое число, Enter — в игре меняется сразу. Галочки
триггеров — тоже сразу. Без запущенной игры список пуст.
"""
from __future__ import annotations

from PySide6.QtCore import Qt

from app.ui.i18n import TR
from app.ui.renpy_cheat_tab import (_VarsTableModel, TriggersTab,
                                    VariablesTab)

# примеры для консоли: живой kag игры (переменные + временные флаги)
_CONSOLE_PLACEHOLDER = "f.money = 99999  /  tf.flag = 1"


class _AjinVarsModel(_VarsTableModel):
    """Модель с типизированной правкой чисел.

    Базовая модель кладёт в строку сырой текст из редактора, и к моменту
    _on_model_edit исходный тип уже затёрт (строки модели — те же dict,
    что в _vars): _coerce видит строку и отправляет в игру строку "999"
    вместо числа 999. Здесь приводим к типу СТАРОГО значения до записи —
    в игру уходит JSON-число, арифметика скриптов Tyrano не ломается.
    """

    def setData(self, index, value, role=Qt.EditRole):
        if (index.isValid() and index.column() == self.COL_VALUE
                and role == Qt.EditRole and isinstance(value, str)
                and 0 <= index.row() < len(self.rows)):
            old = self.rows[index.row()].get("value")
            if isinstance(old, bool):
                pass
            elif isinstance(old, int):
                try:
                    value = int(value.strip())
                except ValueError:
                    pass
            elif isinstance(old, float):
                try:
                    value = float(value.strip())
                except ValueError:
                    pass
        return super().setData(index, value, role)


def _install_typed_model(tab) -> None:
    """Меняет модель вкладки на типизированную (сохраняет сигнал правок)."""
    old = tab._model
    tab._model = _AjinVarsModel(tab)
    tab._model.dataChanged.connect(tab._on_model_edit)
    tab.vars_table.setModel(tab._model)
    old.deleteLater()


class _AjinAckMixin:
    """Ошибки чтения переменных — в статус (база показывает только
    ошибки записи; молча пустой список иначе не отличить от обрыва)."""

    def _on_ack(self, cmd: str, ok: bool, error: str, value: str):
        super()._on_ack(cmd, ok, error, value)
        if not ok and cmd == "get_vars":
            self.lbl_status.setText(TR("cheat_error", cmd=cmd, err=error))


class AjinVariablesTab(_AjinAckMixin, VariablesTab):
    """«Переменные»: числа/строки Tyrano (не-bool) + консоль kag."""

    def __init__(self, main_window):
        super().__init__(main_window)
        _install_typed_model(self)
        self.console_edit.setPlaceholderText(_CONSOLE_PLACEHOLDER)


class AjinTriggersTab(_AjinAckMixin, TriggersTab):
    """«Триггеры»: bool-переменные Tyrano с мгновенными галочками."""

    def __init__(self, main_window):
        super().__init__(main_window)
        _install_typed_model(self)
