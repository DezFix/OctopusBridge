# -*- coding: utf-8 -*-
"""Вкладка «Читы»: модификация запущенной игры через LiveBridge.

Авто-обновление: каждая подвкладка (пати, предметы, переменные,
переключатели) обновляется по таймеру и подсвечивает изменённые
значения жёлтым фоном. Текущее значение игрока (золото, HP/MP/Level/EXP)
обновляется мгновенно по сигналу состояния.
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                                QGroupBox, QHBoxLayout,
                                QHeaderView, QLabel, QLineEdit, QMessageBox,
                                QPushButton, QSpinBox, QTableWidget,
                                QTableWidgetItem, QTabWidget, QVBoxLayout,
                                QWidget)

from app.core.rpgmaker.varnames import (extract_names,
                                        extract_item_names,
                                        extract_state_names)
from app.core.translate.service import Translator
from app.ui.i18n import TR

CHANGED_COLOR = QColor(255, 255, 150)  # жёлтый фон для изменённых ячеек


class NamesWorker(QThread):
    done = Signal(object, object, object, object)

    def __init__(self, translator: Translator, tgt: str,
                 var_names: dict, switch_names: dict,
                 item_names: dict, state_names: dict):
        super().__init__()
        self.setObjectName("NamesWorker")
        self.translator = translator
        self.tgt = tgt
        self.var_names = var_names
        self.switch_names = switch_names
        self.item_names = item_names
        self.state_names = state_names

    def run(self):
        v, s, it, st = {}, {}, {}, {}
        try:
            for i, name in self.var_names.items():
                v[i] = self.translator.translate_text(name, "auto", self.tgt)
            for i, name in self.switch_names.items():
                s[i] = self.translator.translate_text(name, "auto", self.tgt)
            for key, name in self.item_names.items():
                it[key] = self.translator.translate_text(
                    name, "auto", self.tgt)
            for i, name in self.state_names.items():
                st[i] = self.translator.translate_text(
                    name, "auto", self.tgt)
        except Exception:  # noqa: BLE001
            pass
        self.done.emit(v, s, it, st)

PARAM_NAMES = ["MHP", "MMP", "ATK", "DEF", "MAT", "MDF", "AGI", "LUK"]
KIND_NAMES = {"item": "Item", "weapon": "Weapon", "armor": "Armor"}


class CheatTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.state: dict | None = None
        self._prev_state: dict | None = None  # предыдущее состояние для diff
        self.var_names: dict[int, str] = {}
        self.switch_names: dict[int, str] = {}
        self.var_names_tr: dict[int, str] = {}
        self.switch_names_tr: dict[int, str] = {}
        self.item_names: dict[tuple[str, int], str] = {}
        self.item_names_tr: dict[tuple[str, int], str] = {}
        self.state_names: dict[int, str] = {}
        self.state_names_tr: dict[int, str] = {}
        self._names_worker: NamesWorker | None = None
        self._loading = False
        self._actor_edits: dict[tuple[int, str], int] = {}

        lay = QVBoxLayout(self)
        self.lbl_status = QLabel(TR("cheat_hint"))
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        tabs = QTabWidget()
        tabs.addTab(self._build_main_tab(), TR("cheat_main"))
        tabs.addTab(self._build_party_tab(), TR("cheat_party"))
        tabs.addTab(self._build_items_tab(), TR("cheat_items"))
        tabs.addTab(self._build_vars_tab(), TR("cheat_vars"))
        tabs.addTab(self._build_switches_tab(), TR("cheat_switches"))
        lay.addWidget(tabs, 1)
        self._tabs = tabs

        self.main.bridge_state.connect(self._on_state)
        self.main.bridge_cheat_ack.connect(self._on_ack)
        self.main.bridge_client.connect(self._on_client)

        # автообновление состояния: 500мс — быстрее чем было (1с)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_state)
        self._timer.start(500)

    def _auto_state(self):
        if not self.isVisible() or not self.main.channel():
            return
        # не дергаем, пока пользователь редактирует ячейку
        for tbl in (self.vars_table, self.sw_table,
                    self.party_table, self.items_table):
            if tbl.state() == QAbstractItemView.EditingState:
                return
        self._request_state()

    def cleanup(self):
        """Останавливает NamesWorker перед удалением вкладки."""
        worker = self._names_worker
        if worker and worker.isRunning():
            worker.requestInterruption()
            worker.wait(3000)
        self._names_worker = None

    # ── diff-подсветка: сравнивает старое и новое значение ──
    def _cell_changed(self, table: QTableWidget, row: int, col: int,
                      new_val: str, key: str | int | tuple) -> bool:
        """Подсвечивает ячейку жёлтым, если значение изменилось.
        Возвращает True если было изменение."""
        prev = self._prev_state
        if prev is None:
            return False
        old_val = None
        if key == "gold":
            old_val = str(prev.get("gold", ""))
        elif isinstance(key, tuple) and key[0] == "party":
            idx = key[1]
            field = key[2]
            party = prev.get("party", [])
            if idx < len(party):
                old_val = str(party[idx].get(field, ""))
        elif isinstance(key, tuple) and key[0] == "item":
            kind, iid = key[1], key[2]
            for it in prev.get("items", []):
                if it["kind"] == kind and it["id"] == iid:
                    old_val = str(it.get("count", ""))
                    break
        elif isinstance(key, tuple) and key[0] == "var":
            idx = key[1]
            vals = prev.get("variables", [])
            if idx - 1 < len(vals):
                old_val = str(vals[idx - 1])
        elif isinstance(key, tuple) and key[0] == "switch":
            idx = key[1]
            vals = prev.get("switches", [])
            if idx - 1 < len(vals):
                old_val = "1" if vals[idx - 1] else "0"
        changed = old_val is not None and old_val != new_val
        item = table.item(row, col)
        if item and changed:
            item.setBackground(CHANGED_COLOR)
        elif item:
            item.setBackground(QColor())  # сброс
        return changed

    # ── построение UI ──
    def _build_main_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        gold_box = QGroupBox(TR("cheat_gold").rstrip(":"))
        row = QHBoxLayout(gold_box)
        self.gold_value = QSpinBox()
        self.gold_value.setRange(0, 999_999_999)
        self.gold_value.setValue(0)
        btn_apply = QPushButton(TR("cheat_apply"))
        btn_apply.setObjectName("accent")
        btn_apply.clicked.connect(
            lambda: self._cheat("gold_set", value=self.gold_value.value()))
        row.addWidget(self.gold_value, 1)
        row.addWidget(btn_apply)
        lay.addWidget(gold_box)

        menu_box = QGroupBox(TR("cheat_menu"))
        v = QVBoxLayout(menu_box)
        menu_row = QHBoxLayout()
        btn_menu = QPushButton(TR("cheat_menu_main"))
        btn_menu.clicked.connect(lambda: self._cheat("open_menu"))
        btn_items = QPushButton(TR("cheat_menu_items"))
        btn_items.clicked.connect(lambda: self._cheat("open_items"))
        btn_skills = QPushButton(TR("cheat_menu_skills"))
        btn_skills.clicked.connect(lambda: self._cheat("open_skills"))
        btn_equip = QPushButton(TR("cheat_menu_equip"))
        btn_equip.clicked.connect(lambda: self._cheat("open_equip"))
        btn_status = QPushButton(TR("cheat_menu_status"))
        btn_status.clicked.connect(lambda: self._cheat("open_status"))
        menu_row.addWidget(btn_menu)
        menu_row.addWidget(btn_items)
        menu_row.addWidget(btn_skills)
        menu_row.addWidget(btn_equip)
        menu_row.addWidget(btn_status)
        menu_row2 = QHBoxLayout()
        btn_save = QPushButton(TR("cheat_menu_save"))
        btn_save.clicked.connect(lambda: self._cheat("open_save"))
        btn_load = QPushButton(TR("cheat_menu_load"))
        btn_load.clicked.connect(lambda: self._cheat("open_load"))
        btn_options = QPushButton(TR("cheat_menu_options"))
        btn_options.clicked.connect(lambda: self._cheat("open_options"))
        btn_end = QPushButton(TR("cheat_menu_end"))
        btn_end.clicked.connect(lambda: self._cheat("open_gameend"))
        menu_row2.addWidget(btn_save)
        menu_row2.addWidget(btn_load)
        menu_row2.addWidget(btn_options)
        menu_row2.addWidget(btn_end)
        menu_row2.addStretch(1)
        v.addLayout(menu_row)
        v.addLayout(menu_row2)
        lay.addWidget(menu_box)

        battle_box = QGroupBox("Battle")
        row = QHBoxLayout(battle_box)
        btn_heal = QPushButton(TR("cheat_heal"))
        btn_heal.clicked.connect(lambda: self._cheat("heal"))
        btn_win = QPushButton(TR("cheat_win"))
        btn_win.clicked.connect(lambda: self._cheat("win_battle"))
        row.addWidget(btn_heal)
        row.addWidget(btn_win)
        lay.addWidget(battle_box)

        move_box = QGroupBox("Movement")
        row = QHBoxLayout(move_box)
        self.cb_noclip = QCheckBox(TR("cheat_noclip"))
        self.cb_noclip.toggled.connect(
            lambda on: self._cheat("through", value=on))
        self.cb_clicketp = QCheckBox(TR("cheat_clicktp"))
        self.cb_clicketp.toggled.connect(
            lambda on: self._cheat("click_tp", value=on))
        self.speed_value = QSpinBox()
        self.speed_value.setRange(1, 10)
        self.speed_value.setValue(4)
        btn_speed = QPushButton(TR("cheat_speed"))
        btn_speed.clicked.connect(
            lambda: self._cheat("speed", value=self.speed_value.value()))
        row.addWidget(self.cb_noclip)
        row.addWidget(self.cb_clicketp)
        row.addWidget(self.speed_value)
        row.addWidget(btn_speed)
        lay.addWidget(move_box)

        lay.addStretch(1)
        return w

    def _build_party_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.party_table = QTableWidget(0, 8)
        self.party_table.setHorizontalHeaderLabels(
            ["ID", "Name", "Class", "Level", "HP", "MP", "EXP", "In Party"])
        self.party_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.party_table.itemChanged.connect(self._on_party_edit)
        lay.addWidget(self.party_table, 1)
        row = QHBoxLayout()
        btn = QPushButton(TR("cheat_apply_party"))
        btn.clicked.connect(self._apply_party)
        row.addWidget(btn)
        lay.addLayout(row)
        return w

    def _build_items_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        filt = QHBoxLayout()
        filt.addWidget(QLabel(TR("cheat_item_search")))
        self.item_search = QLineEdit()
        self.item_search.textChanged.connect(self._fill_items)
        filt.addWidget(self.item_search, 1)
        self.item_kind = QComboBox()
        self.item_kind.addItems(["All", "Items", "Weapons", "Armor"])
        self.item_kind.currentIndexChanged.connect(self._fill_items)
        filt.addWidget(self.item_kind)
        lay.addLayout(filt)
        self.items_table = QTableWidget(0, 4)
        self.items_table.setHorizontalHeaderLabels(
            ["Type", "ID", "Name", "Count"])
        self.items_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.items_table.itemChanged.connect(self._on_item_edit)
        lay.addWidget(self.items_table, 1)
        hint = QLabel(TR("cheat_var_hint"))
        lay.addWidget(hint)
        return w

    def _build_vars_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        filt = QHBoxLayout()
        filt.addWidget(QLabel(TR("cheat_item_search")))
        self.var_search = QLineEdit()
        self.var_search.textChanged.connect(self._fill_vars)
        filt.addWidget(self.var_search, 1)
        lay.addLayout(filt)
        self.vars_table = QTableWidget(0, 3)
        self.vars_table.setHorizontalHeaderLabels(["#", "Name", "Value"])
        self.vars_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.vars_table.itemChanged.connect(self._on_var_edit)
        lay.addWidget(self.vars_table, 1)
        hint = QLabel(TR("cheat_var_hint"))
        lay.addWidget(hint)
        return w

    def _build_switches_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        filt = QHBoxLayout()
        filt.addWidget(QLabel(TR("cheat_item_search")))
        self.sw_search = QLineEdit()
        self.sw_search.textChanged.connect(self._fill_switches)
        filt.addWidget(self.sw_search, 1)
        lay.addLayout(filt)
        self.sw_table = QTableWidget(0, 3)
        self.sw_table.setHorizontalHeaderLabels(["#", "Name", "On"])
        self.sw_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.sw_table.itemChanged.connect(self._on_switch_toggle)
        lay.addWidget(self.sw_table, 1)
        hint = QLabel(TR("cheat_sw_hint"))
        lay.addWidget(hint)
        return w

    # ── отправка читов ──
    def _cheat(self, cmd: str, **kwargs):
        ch = self.main.channel()
        if not ch:
            QMessageBox.information(self, TR("cheat_no_bridge"),
                                    TR("cheat_no_bridge"))
            return
        ch.send_cheat(cmd, **kwargs)

    def _request_state(self):
        ch = self.main.channel()
        if ch:
            ch.request_state()

    def showEvent(self, event):
        super().showEvent(event)
        self._request_state()

    def on_project_opened(self):
        if not self.main.project:
            return
        mod = self.main.engine_module
        game_dir = self.main.project.game_dir
        view = mod.file_view(game_dir) if mod else None
        v, s = extract_names(game_dir, view)
        self.var_names = v
        self.switch_names = s
        self.item_names = extract_item_names(game_dir, view)
        self.state_names = extract_state_names(game_dir, view)
        self._fill_vars()
        self._fill_switches()
        self._fill_items()
        self._translate_names_async()

    def _translate_names_async(self):
        if not (self.var_names or self.switch_names
                or self.item_names or self.state_names):
            return
        if self._names_worker and self._names_worker.isRunning():
            self._names_worker.terminate()
            self._names_worker.wait(2000)
        engine = self.main.create_engine("realtime")
        if engine is None:
            return
        translator = Translator(engine, tm=self.main.tm,
                                glossary=self.main.glossary)
        tgt = self.main.settings.value("target_lang", "ru")
        self._names_worker = NamesWorker(
            translator, tgt,
            self.var_names, self.switch_names,
            self.item_names, self.state_names)
        self._names_worker.done.connect(self._on_names_translated)
        self._names_worker.start()

    def _on_names_translated(self, v: dict, s: dict, it: dict, st: dict):
        self.var_names_tr = v
        self.switch_names_tr = s
        self.item_names_tr = it
        self.state_names_tr = st
        self._fill_vars()
        self._fill_switches()
        self._fill_items()
        self._names_worker = None

    # ── обработка нового состояния ──
    def _on_state(self, state: str):
        state = json.loads(state)
        # сохраняем предыдущее для diff-подсветки
        self._prev_state = self.state
        self.state = state

        # золото: не трогаем, пока редактируется
        if not self.gold_value.hasFocus():
            self.gold_value.setValue(int(state.get("gold", 0) or 0))

        self._fill_party()
        self._fill_items()
        self._fill_vars()
        self._fill_switches()

    def _fill_party(self):
        self._loading = True
        try:
            party = (self.state or {}).get("party", [])
            self.party_table.setRowCount(len(party))
            for r, a in enumerate(party):
                cells = [str(a["id"]), a["name"], a["className"],
                         str(a["level"]), f'{a["hp"]}/{a["mhp"]}',
                         f'{a["mp"]}/{a["mmp"]}', str(a["exp"]),
                         "yes" if a["inParty"] else "—"]
                for c, val in enumerate(cells):
                    it = QTableWidgetItem(val)
                    if c not in (3, 4, 5, 6):
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if c == 1:
                        it.setToolTip(" / ".join(
                            f"{n}={v}" for n, v in
                            zip(PARAM_NAMES, a.get("params", []))))
                    it.setData(Qt.UserRole, a["id"])
                    self.party_table.setItem(r, c, it)

                    # diff-подсветка для Level, HP, MP, EXP
                    if c in (3, 4, 5, 6):
                        field = {3: "level", 4: "hp", 5: "mp",
                                 6: "exp"}[c]
                        self._cell_changed(
                            self.party_table, r, c, val,
                            ("party", r, field))
        finally:
            self._loading = False

    def _fill_items(self):
        self._loading = True
        try:
            items = (self.state or {}).get("items", [])
            q = self.item_search.text().strip().lower() \
                if hasattr(self, "item_search") else ""
            kind_idx = self.item_kind.currentIndex() \
                if hasattr(self, "item_kind") else 0
            kind_filter = {1: "item", 2: "weapon", 3: "armor"}.get(kind_idx)
            rows = [it for it in items
                    if (not kind_filter or it["kind"] == kind_filter)
                    and (not q or q in it["name"].lower()
                         or q in self.item_names_tr.get(
                             (it["kind"], it["id"]), "").lower())]
            self.items_table.setRowCount(len(rows))
            for r, it in enumerate(rows):
                key = (it["kind"], it["id"])
                tr_name = self.item_names_tr.get(key, "")
                display = f"{tr_name} · {it['name']}" \
                    if tr_name and tr_name != it["name"] else it["name"]
                cells = [KIND_NAMES[it["kind"]], str(it["id"]),
                         display, str(it["count"])]
                for c, val in enumerate(cells):
                    cell = QTableWidgetItem(val)
                    if c != 3:
                        cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                    cell.setData(Qt.UserRole, key)
                    cell.setToolTip(it["name"])
                    self.items_table.setItem(r, c, cell)

                    # diff-подсветка для Count
                    if c == 3:
                        self._cell_changed(
                            self.items_table, r, c, val,
                            ("item", it["kind"], it["id"]))
        finally:
            self._loading = False

    def _manual_names(self) -> tuple[dict[int, str], dict[int, str]]:
        p = self.main.project
        if not p:
            return {}, {}
        return ({int(k): v for k, v in p.var_names.items()},
                {int(k): v for k, v in p.switch_names.items()})

    def _display_name(self, idx: int, kind: str) -> str:
        manual_v, manual_s = self._manual_names()
        if kind == "var":
            original = self.var_names.get(idx) or f"Variable #{idx}"
            translated = self.var_names_tr.get(idx)
            manual = manual_v.get(idx)
        else:
            original = self.switch_names.get(idx) or f"Switch #{idx}"
            translated = self.switch_names_tr.get(idx)
            manual = manual_s.get(idx)
        if manual:
            return manual
        if translated and translated != original:
            return f"{translated} · {original}"
        return original

    def _known_indices(self, values: list, kind: str) -> list[int]:
        names = self.var_names if kind == "var" else self.switch_names
        manual_v, manual_s = self._manual_names()
        manual = manual_v if kind == "var" else manual_s
        indices = set(range(1, len(values) + 1)) | set(names) | set(manual)
        return sorted(i for i in indices if i > 0)

    def _fill_vars(self):
        self._loading = True
        try:
            values = (self.state or {}).get("variables", [])
            q = self.var_search.text().strip().lower() \
                if hasattr(self, "var_search") else ""
            rows = []
            for i in self._known_indices(values, "var"):
                name = self._display_name(i, "var")
                v = values[i - 1] if i - 1 < len(values) else 0
                if q and q not in name.lower() and q not in str(v).lower():
                    continue
                rows.append((i, name, v))
            self.vars_table.setRowCount(len(rows))
            for r, (i, name, v) in enumerate(rows):
                it_i = QTableWidgetItem(str(i))
                it_i.setFlags(it_i.flags() & ~Qt.ItemIsEditable)
                it_n = QTableWidgetItem(name)
                it_n.setFlags(it_n.flags() & ~Qt.ItemIsEditable)
                it_v = QTableWidgetItem(str(v))
                for it in (it_i, it_n, it_v):
                    it.setData(Qt.UserRole, i)
                self.vars_table.setItem(r, 0, it_i)
                self.vars_table.setItem(r, 1, it_n)
                self.vars_table.setItem(r, 2, it_v)

                # diff-подсветка
                self._cell_changed(
                    self.vars_table, r, 2, str(v), ("var", i))
        finally:
            self._loading = False

    def _fill_switches(self):
        self._loading = True
        try:
            values = (self.state or {}).get("switches", [])
            q = self.sw_search.text().strip().lower() \
                if hasattr(self, "sw_search") else ""
            rows = []
            for i in self._known_indices(values, "switch"):
                name = self._display_name(i, "switch")
                v = bool(values[i - 1]) if i - 1 < len(values) else False
                if q and q not in name.lower():
                    continue
                rows.append((i, name, v))
            self.sw_table.setRowCount(len(rows))
            for r, (i, name, on) in enumerate(rows):
                it_i = QTableWidgetItem(str(i))
                it_i.setFlags(it_i.flags() & ~Qt.ItemIsEditable)
                it_n = QTableWidgetItem(name)
                it_n.setFlags(it_n.flags() & ~Qt.ItemIsEditable)
                it_v = QTableWidgetItem()
                it_v.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                it_v.setCheckState(Qt.Checked if on else Qt.Unchecked)
                for it in (it_i, it_n, it_v):
                    it.setData(Qt.UserRole, i)
                self.sw_table.setItem(r, 0, it_i)
                self.sw_table.setItem(r, 1, it_n)
                self.sw_table.setItem(r, 2, it_v)

                # diff-подсветка
                self._cell_changed(
                    self.sw_table, r, 2, "1" if on else "0",
                    ("switch", i))
        finally:
            self._loading = False

    # ── редактирование ──
    def _on_party_edit(self, item):
        if self._loading:
            return
        actor_id = item.data(Qt.UserRole)
        field = {3: "level", 4: "hp", 5: "mp", 6: "exp"}.get(item.column())
        if not field:
            return
        try:
            value = int(item.text().split("/")[0])
        except ValueError:
            return
        self._actor_edits[(actor_id, field)] = value

    def _on_item_edit(self, item):
        if self._loading or item.column() != 3:
            return
        key = item.data(Qt.UserRole)
        try:
            target = int(item.text())
        except (ValueError, TypeError):
            self._fill_items()
            return
        have = next((it["count"] for it in (self.state or {}).get("items", [])
                     if (it["kind"], it["id"]) == key), 0)
        delta = target - have
        if delta:
            self._cheat("give_item", kind=key[0], id=key[1], count=delta)

    @staticmethod
    def _coerce_var(text: str):
        text = text.strip()
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return text

    def _on_var_edit(self, item):
        if self._loading:
            return
        idx = item.data(Qt.UserRole)
        if item.column() == 2:
            self._cheat("var_set", index=idx,
                        value=self._coerce_var(item.text()))
        elif item.column() == 1 and self.main.project:
            self.main.project.var_names[str(idx)] = item.text().strip()
            self.main.save_project()

    def _on_switch_toggle(self, item):
        if self._loading:
            return
        idx = item.data(Qt.UserRole)
        if item.column() == 2:
            self._cheat("switch_set", index=idx,
                        value=item.checkState() == Qt.Checked)
        elif item.column() == 1 and self.main.project:
            self.main.project.switch_names[str(idx)] = item.text().strip()
            self.main.save_project()

    def _apply_party(self):
        for (actor_id, field), value in self._actor_edits.items():
            self._cheat("actor_set", actorId=actor_id, field=field,
                        value=value)
        self._actor_edits.clear()

    def _on_ack(self, cmd: str, ok: bool, error: str, value: str):
        if ok:
            self.lbl_status.setText(TR("cheat_done", cmd=cmd))
        else:
            self.lbl_status.setText(TR("cheat_error", cmd=cmd, err=error))
        if ok:
            self._request_state()

    def _on_client(self, connected: bool):
        self.lbl_status.setText(
            TR("cheat_connected") if connected else
            TR("cheat_disconnected"))
        if connected:
            self._request_state()
