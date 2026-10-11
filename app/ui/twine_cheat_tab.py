# -*- coding: utf-8 -*-
"""Живые читы Twine: переменные запущенной игры.

Почему именно живые, а не по файлу сейва:

* игра — это страница в браузере, а переменные лежат в `State.variables`
  (SugarCube) или `Harlowe.state.variables`. Это обычный JS-объект;
* правим мы его через уже работающий мост (`var_set`), и мост сразу
  перерисовывает игру — эффект виден немедленно, без «загрузи сейв»;
* если переменной нет в файле сейва (текущее состояние, флаги, счётчик
  дней), файловый чит её вообще не увидит, а живой — увидит;
* ошибка записи приходит подтверждением `cheat_ack`, а не ломает файл.

Мост написан давно (`get_vars`/`var_set` в tentacle.py), вкладки не было —
поэтому шеф и видел «читов нет».
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.i18n import TR

#: как часто перечитывать переменные у запущенной игры, мс
_POLL_MS = 2000
#: длиннее — игрок не заметит, что ввёл число
_LARGE_ROWS = 4000


def _empty(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        "color:#757c94; border:2px dashed #3a3d4f; border-radius:10px;"
        "padding:24px;")
    return lbl


def _kind(value) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list(%d)" % len(value)
    if isinstance(value, dict):
        return "object(%d)" % len(value)
    return type(value).__name__


def _render(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)[:180]
    except (TypeError, ValueError):
        return str(value)[:180]


def _parse(kind: str, text: str):
    """Ячейка -> значение того же типа, что был. Мусор — отказ."""
    text = (text or "").strip()
    if kind == "bool":
        low = text.lower()
        if low in ("true", "1", "да", "on", "yes"):
            return True
        if low in ("false", "0", "нет", "off", "no", ""):
            return False
        raise ValueError(TR("twine_cheat_bool"))
    if kind == "number":
        try:
            return int(text, 0) if "." not in text and "e" not in text.lower() \
                else float(text.replace(",", "."))
        except ValueError as e:
            raise ValueError(TR("twine_cheat_number", s=text[:20])) from e
    return text


class TwineCheatTab(QWidget):
    """Переменные запущенной игры Twine: чтение и правка на лету."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._rows: list[dict] = []
        self._loading = False
        self._pending: dict[str, tuple] = {}

        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_reload = QPushButton(TR("twine_cheat_reload"))
        self.btn_reload.clicked.connect(self.reload)
        bar.addWidget(self.btn_reload)

        self.search = QLineEdit()
        self.search.setPlaceholderText(TR("cheat_item_search"))
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search, 1)

        self.chk_auto = QCheckBox(TR("twine_cheat_auto"))
        self.chk_auto.setChecked(True)
        self.chk_auto.toggled.connect(lambda _v: self._sync_timer())
        bar.addWidget(self.chk_auto)
        lay.addLayout(bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#757c94;")
        lay.addWidget(self.lbl_hint)

        self.stack = QStackedWidget()
        self.stack.addWidget(_empty(TR("twine_cheat_empty")))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            TR("twine_cheat_var"), TR("twine_cheat_type"),
            TR("twine_cheat_val")])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_edit)
        self.stack.addWidget(self.table)
        lay.addWidget(self.stack, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self.reload)

        try:
            main_window.bridge_vars.connect(self._on_vars)
            main_window.bridge_cheat_ack.connect(self._on_ack)
        except Exception:  # noqa: BLE001 — нет моста (тесты, сборка без UI)
            pass

    # ── канал ───────────────────────────────────────────────────────────────

    def _channel(self):
        try:
            return self.main.channel()
        except Exception:  # noqa: BLE001
            return None

    def reload(self) -> None:
        ch = self._channel()
        if ch is None:
            self._rows = []
            self.lbl_status.setText(TR("twine_cheat_no_channel"))
            self._fill()
            return
        try:
            ok = ch.request_vars()
        except Exception as e:  # noqa: BLE001
            self.lbl_status.setText(str(e))
            return
        if not ok:
            self.lbl_status.setText(TR("twine_cheat_no_channel"))

    def _on_vars(self, payload: str) -> None:
        """Мост прислал плоский список переменных игры."""
        try:
            items = json.loads(payload) if payload else []
        except (TypeError, ValueError):
            return
        if not isinstance(items, list):
            return
        rows = []
        for it in items[:_LARGE_ROWS]:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name", ""))
            if not name:
                continue
            value = it.get("value")
            kind = _kind(value)
            rows.append({"name": name, "value": value, "kind": kind,
                         "editable": kind in ("bool", "number", "string")})
        # применённую правку показываем сразу: иначе до следующего
        # автообновления ячейка моргает старым значением
        for row in rows:
            want = self._pending.get(row["name"])
            if want is not None and want == row["value"]:
                self._pending.pop(row["name"], None)
        self._rows = sorted(rows, key=lambda r: r["name"].lower())
        ch = self._channel()
        if ch is not None:
            self.lbl_status.setText(TR("twine_cheat_count", n=len(rows)))
        # Ноль переменных у опознанного движка — это правда «переменных
        # нет»; у неопознанного (сырой Twine, нестандартная сборка)
        # список будет пустым, и молчать об этом нельзя: игрок решит,
        # что сломалась вкладка.
        self.lbl_hint.setText(
            "" if rows else TR("twine_cheat_none"))
        self._fill()

    def _on_ack(self, cmd: str, ok: bool, err: str, value: str) -> None:
        if cmd != "var_set":
            return
        if not ok:
            QMessageBox.warning(self, TR("err"), err or TR("err"))
        self.reload()

    # ── таблица ─────────────────────────────────────────────────────────────

    def _fill(self) -> None:
        q = self.search.text().strip().lower()
        rows = [r for r in self._rows
                if not q or q in r["name"].lower()]
        self._loading = True
        try:
            self.table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                self.table.setItem(i, 0, QTableWidgetItem(row["name"]))
                self.table.setItem(i, 1, QTableWidgetItem(row["kind"]))
                cell = QTableWidgetItem(_render(row["value"]))
                cell.setData(Qt.UserRole, row)
                flags = cell.flags()
                if row["editable"]:
                    flags |= Qt.ItemIsEditable
                else:
                    flags &= ~Qt.ItemIsEditable
                    cell.setToolTip(TR("twine_cheat_no_edit"))
                cell.setFlags(flags)
                self.table.setItem(i, 2, cell)
        finally:
            self._loading = False
        self.stack.setCurrentIndex(1 if rows else 0)

    def _on_edit(self, item) -> None:
        if item is None or self._loading or item.column() != 2:
            return
        row = item.data(Qt.UserRole)
        ch = self._channel()
        if not row or ch is None:
            return
        if not row.get("editable"):
            QMessageBox.warning(self, TR("err"), TR("twine_cheat_no_edit"))
            self._reset_cell(item, row)
            return
        try:
            value = _parse(row.get("kind", ""), item.text())
        except ValueError as e:
            QMessageBox.warning(self, TR("err"), str(e))
            self._reset_cell(item, row)
            return
        try:
            ok = ch.set_variable(row["name"], value)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, TR("err"), str(e))
            self._reset_cell(item, row)
            return
        if not ok:
            QMessageBox.warning(self, TR("err"), TR("twine_cheat_write_err"))
            self._reset_cell(item, row)
            return
        row["value"] = value
        self._pending[row["name"]] = value
        self._reset_cell(item, row)

    def _reset_cell(self, item, row) -> None:
        self.table.blockSignals(True)
        try:
            item.setText(_render(row.get("value")))
        finally:
            self.table.blockSignals(False)

    # ── жизненный цикл ──────────────────────────────────────────────────────

    def _sync_timer(self) -> None:
        """Опрос только когда вкладка видна: в фоне она бесцельна."""
        if self.chk_auto.isChecked() and self.isVisible() \
                and self._channel() is not None:
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_timer()
        self.reload()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def on_project_opened(self) -> None:
        self._rows = []
        self._pending = {}
        self.lbl_status.setText("")
        self._fill()
        self.reload()

    def cleanup(self) -> None:
        try:
            self._timer.stop()
        except Exception:  # noqa: BLE001, RuntimeError
            pass
        for sig, slot in ((getattr(self.main, "bridge_vars", None),
                           self._on_vars),
                          (getattr(self.main, "bridge_cheat_ack", None),
                           self._on_ack)):
            try:
                if sig is not None:
                    sig.disconnect(slot)
            except Exception:  # noqa: BLE001, RuntimeError
                pass
