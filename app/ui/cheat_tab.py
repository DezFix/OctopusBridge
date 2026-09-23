# -*- coding: utf-8 -*-
"""Вкладка «Читы»: модификация запущенной игры через LiveBridge.

Авто-обновление: каждая подвкладка (пати, предметы, переменные,
переключатели) обновляется по таймеру и подсвечивает изменённые
значения жёлтым фоном. Текущее значение игрока (золото, HP/MP/Level/EXP)
обновляется мгновенно по сигналу состояния.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox,
                               QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QSpinBox,
                               QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from app.core.rpgmaker.varnames import (extract_names,
                                        extract_item_names,
                                        extract_state_names)
from app.core.translate.service import Translator
from app.ui.i18n import TR
from app.ui.loading_overlay import BusyLabel
from app.ui.theme import AnimatedComboBox

CHANGED_COLOR = QColor(255, 255, 150)  # жёлтый фон для изменённых ячеек


def _is_qthread_running(w) -> bool:
    """isRunning() без исключений: C++-объект мог уже уйти в deleteLater."""
    try:
        return bool(w.isRunning())
    except RuntimeError:
        return False


class NamesWorker(QThread):
    done = Signal(object, object, object, object)
    failed = Signal(str)

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
        self._cancelled = False

    def cancel(self):
        """Cooperative отмена: флаг движка + прерывание QThread.

        Движок проверяет cancelled перед каждым сетевым запросом
        и бросает InterruptedError — поток выходит штатно, без
        terminate() (тот роняет процесс посреди C-кода SSL/SQLite).
        """
        self._cancelled = True
        try:
            if self.translator is not None:
                self.translator.cancel()
        except Exception:  # noqa: BLE001 — отмена не должна падать
            pass
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        if self._cancelled or self.isInterruptionRequested():
            return True
        try:
            if getattr(self.translator, "cancelled", False):
                return True
        except Exception:  # noqa: BLE001
            pass
        return False

    def run(self):
        v, s, it, st = {}, {}, {}, {}
        try:
            if self._is_cancelled():
                return
            v = dict(zip(
                self.var_names.keys(),
                self.translator.translate_texts(
                    list(self.var_names.values()), "auto", self.tgt)))
            if self._is_cancelled():
                return
            s = dict(zip(
                self.switch_names.keys(),
                self.translator.translate_texts(
                    list(self.switch_names.values()), "auto", self.tgt)))
            if self._is_cancelled():
                return
            it = dict(zip(
                self.item_names.keys(),
                self.translator.translate_texts(
                    list(self.item_names.values()), "auto", self.tgt)))
            if self._is_cancelled():
                return
            st = dict(zip(
                self.state_names.keys(),
                self.translator.translate_texts(
                    list(self.state_names.values()), "auto", self.tgt)))
        except InterruptedError:
            return
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))
        if self._is_cancelled():
            return
        self.done.emit(v, s, it, st)

PARAM_NAMES = ["MHP", "MMP", "ATK", "DEF", "MAT", "MDF", "AGI", "LUK"]
KIND_NAMES = {"item": "Item", "weapon": "Weapon", "armor": "Armor"}


def frozen_corrections(state_vars: list, state_switches: list,
                       frozen_vars: dict, frozen_switches: dict) -> list:
    """Какие читы отправить, чтобы удержать замороженное.

    Игра (параллельные события) перезаписывает переменные каждый кадр —
    правка живёт секунду. Возвращает [(cmd, kwargs)] только для
    разошедшихся значений. Чистая, без Qt.
    """
    out = []
    try:
        for idx, val in (frozen_vars or {}).items():
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            cur = state_vars[i - 1] if isinstance(state_vars, list) \
                and 0 < i <= len(state_vars) else None
            if cur is None or cur != val:
                out.append(("var_set", {"index": i, "value": val}))
        for idx, val in (frozen_switches or {}).items():
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            cur = state_switches[i - 1] if isinstance(state_switches, list) \
                and 0 < i <= len(state_switches) else None
            cur = bool(cur) if cur is not None else None
            want = bool(val)
            if cur is None or cur != want:
                out.append(("switch_set", {"index": i, "value": want}))
    except Exception:  # noqa: BLE001
        pass
    return out


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
        self._names_worker: NamesWorker | None = None
        self._names_seq = 0
        # Отменённые, но ещё бегущие воркеры: держим Python-ссылку до
        # finished. Без этого последний ref исчезает при замене/очистке
        # и shiboken сносит C++ QThread посреди run() -> AV 0xC0000409.
        self._zombie_workers: list[NamesWorker] = []
        self._loading = False
        self._actor_edits: dict[tuple[int, str], int] = {}
        # Заморозка: {idx: value} — игра перезаписывает переменные
        # каждый кадр, без повтора правка живёт секунду.
        self._frozen_vars: dict[int, object] = {}
        self._frozen_switches: dict[int, bool] = {}

        lay = QVBoxLayout(self)
        self.lbl_status = QLabel(TR("cheat_hint"))
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        self.busy_names = BusyLabel(self, size=14)
        lay.addWidget(self.busy_names)

        tabs = QTabWidget()
        tabs.addTab(self._build_main_tab(), TR("cheat_main"))
        tabs.addTab(self._build_party_tab(), TR("cheat_party"))
        tabs.addTab(self._build_items_tab(), TR("cheat_items"))
        tabs.addTab(self._build_vars_tab(), TR("cheat_vars"))
        tabs.addTab(self._build_switches_tab(), TR("cheat_switches"))
        lay.addWidget(tabs, 1)

        self.main.bridge_state.connect(self._on_state)
        self.main.bridge_cheat_ack.connect(self._on_ack)
        self.main.bridge_client.connect(self._on_client)

        # автообновление состояния: 500мс — быстрее чем было (1с)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_state)
        self._timer.start(500)

    def _auto_state(self):
        if not self.isVisible():
            return
        # не слать запросы когда detached: channel() is None без
        # активного щупальца; перепроверяем перед отправкой
        try:
            ch = self.main.channel()
        except Exception:  # noqa: BLE001
            return
        if ch is None:
            return
        # не дергаем, пока пользователь редактирует ячейку
        for tbl in (self.vars_table, self.sw_table,
                    self.party_table, self.items_table):
            if tbl.state() == QAbstractItemView.EditingState:
                return
        self._request_state()

    def _hold_zombie(self, worker: NamesWorker) -> None:
        """Удерживает отменённый, но ещё бегущий поток до finished.

        finished (когда цикл событий доставит) убирает поток из списка;
        finished->deleteLater подключает вызывающий код. Завершённые
        потоки из списка выкидываем сразу — удалять finished QThread
        безопасно. Список ограничен 8 записями.
        """
        try:
            if not worker.isRunning():
                return
        except RuntimeError:  # C++-объект уже удалён
            return
        if worker not in self._zombie_workers:
            self._zombie_workers.append(worker)
        self._zombie_workers = [
            w for w in self._zombie_workers if w is worker
            or _is_qthread_running(w)][-8:]
        try:
            worker.finished.connect(
                lambda _w=worker: self._drop_zombie(_w))
        except Exception:  # noqa: BLE001, RuntimeError
            pass

    def _drop_zombie(self, worker: NamesWorker) -> None:
        try:
            self._zombie_workers.remove(worker)
        except ValueError:
            pass

    def cleanup(self):
        """Останавливает NamesWorker без блокировки GUI.

        Cooperative отмена (cancel + requestInterruption) + wait(200)
        max; если поток не успел — он сам завершится и удалится по
        finished->deleteLater, висящих запросов не шлём (поколение
        инвалидируется, поздние done игнорятся).
        """
        worker = self._names_worker
        self._names_worker = None
        self._names_seq += 1
        # чистим список зомби от уже завершённых (удалять finished
        # QThread безопасно) — обратного роста списка не будет
        for z in list(self._zombie_workers):
            if not _is_qthread_running(z):
                self._drop_zombie(z)
        if worker is None:
            return
        try:
            if worker.isRunning():
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    try:
                        cancel()
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    try:
                        worker.requestInterruption()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    worker.finished.connect(worker.deleteLater)
                except Exception:  # noqa: BLE001, RuntimeError
                    pass
                worker.wait(200)
                # поток мог не успеть (блокирующий POST в C-коде):
                # ссылку держим до finished, иначе shiboken снесёт
                # бегущий QThread -> AV 0xC0000409
                self._hold_zombie(worker)
            try:
                self.busy_names.stop()
            except Exception:  # noqa: BLE001
                pass
        except RuntimeError:  # C++-объект уже удалён (deleteLater)
            pass

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
        grid = QGridLayout(w)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # ── золото ──
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
        for delta in (1000, 10000, -1000):
            b = QPushButton(f"{delta:+d}")
            b.clicked.connect(
                lambda _, d=delta: self._cheat("gold_add", value=d))
            row.addWidget(b)
        grid.addWidget(gold_box, 0, 0)

        # ── турбо (скорость игры) ──
        turbo_box = QGroupBox(TR("cheat_turbo"))
        row = QHBoxLayout(turbo_box)
        self.turbo_value = QSpinBox()
        self.turbo_value.setRange(1, 20)
        self.turbo_value.setValue(1)
        btn_turbo = QPushButton(TR("cheat_apply"))
        btn_turbo.clicked.connect(
            lambda: self._cheat("game_speed",
                                value=self.turbo_value.value()))
        row.addWidget(self.turbo_value)
        row.addWidget(btn_turbo)
        for sp in (1, 2, 4, 8):
            b = QPushButton(f"{sp}x")
            b.clicked.connect(
                lambda _, s=sp: self._cheat("game_speed", value=s))
            row.addWidget(b)
        grid.addWidget(turbo_box, 0, 1)

        # ── бой (отряд + мгновенная победа) ──
        battle_box = QGroupBox(TR("cheat_box_battle"))
        row = QHBoxLayout(battle_box)
        btn_heal = QPushButton(TR("cheat_heal_full"))
        btn_heal.clicked.connect(lambda: self._cheat("heal_all"))
        btn_states = QPushButton(TR("cheat_clear_states"))
        btn_states.clicked.connect(lambda: self._cheat("clear_states"))
        btn_win = QPushButton(TR("cheat_win"))
        btn_win.clicked.connect(lambda: self._cheat("win_battle"))
        row.addWidget(btn_heal)
        row.addWidget(btn_states)
        row.addWidget(btn_win)
        row.addStretch(1)
        grid.addWidget(battle_box, 1, 0)

        # ── перемещение ──
        move_box = QGroupBox(TR("cheat_box_movement"))
        v = QVBoxLayout(move_box)
        row = QHBoxLayout()
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
        row.addStretch(1)
        v.addLayout(row)
        row2 = QHBoxLayout()
        btn_reload = QPushButton(TR("cheat_reload_map"))
        btn_reload.clicked.connect(lambda: self._cheat("reload_map"))
        row2.addWidget(btn_reload)
        row2.addStretch(1)
        v.addLayout(row2)
        grid.addWidget(move_box, 1, 1)

        # ── меню игры + скриншот ──
        menu_box = QGroupBox(TR("cheat_menu"))
        v = QVBoxLayout(menu_box)
        row = QHBoxLayout()
        row.setSpacing(4)
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
        btn_save = QPushButton(TR("cheat_menu_save"))
        btn_save.clicked.connect(lambda: self._cheat("open_save"))
        btn_load = QPushButton(TR("cheat_menu_load"))
        btn_load.clicked.connect(lambda: self._cheat("open_load"))
        btn_options = QPushButton(TR("cheat_menu_options"))
        btn_options.clicked.connect(lambda: self._cheat("open_options"))
        btn_end = QPushButton(TR("cheat_menu_end"))
        btn_end.clicked.connect(lambda: self._cheat("open_gameend"))
        btn_shot = QPushButton(TR("cheat_screenshot"))
        btn_shot.clicked.connect(self._screenshot)
        for b in (btn_menu, btn_items, btn_skills, btn_equip, btn_status,
                  btn_save, btn_load, btn_options, btn_end, btn_shot):
            row.addWidget(b, 1)
        v.addLayout(row)
        grid.addWidget(menu_box, 2, 0, 1, 2)

        return w

    def _build_party_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.party_table = QTableWidget(0, 8)
        self.party_table.setHorizontalHeaderLabels(
            [TR("tbl_col_id"), TR("tbl_col_name"), TR("party_col_class"),
             TR("party_col_level"), TR("party_col_hp"), TR("party_col_mp"),
             TR("party_col_exp"), TR("party_col_inparty")])
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
        self.item_kind = AnimatedComboBox()
        self.item_kind.addItems([TR("cheat_kind_all"), TR("cheat_kind_items"),
                                 TR("cheat_kind_weapons"), TR("cheat_kind_armor")])
        self.item_kind.currentIndexChanged.connect(self._fill_items)
        filt.addWidget(self.item_kind)
        lay.addLayout(filt)
        self.items_table = QTableWidget(0, 4)
        self.items_table.setHorizontalHeaderLabels(
            [TR("tbl_col_type"), TR("tbl_col_id"), TR("tbl_col_name"),
             TR("tbl_col_count")])
        self.items_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.items_table.itemChanged.connect(self._on_item_edit)
        lay.addWidget(self.items_table, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel(TR("cheat_sel_item")))
        for d in (1, 10, 99, -1):
            b = QPushButton(f"{d:+d}")
            b.clicked.connect(
                lambda _, delta=d: self._give_selected(delta))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
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
        self.vars_table.setHorizontalHeaderLabels(
            [TR("tbl_col_idx"), TR("tbl_col_name"), TR("tbl_col_value")])
        self.vars_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.vars_table.itemChanged.connect(self._on_var_edit)
        self.vars_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.vars_table.customContextMenuRequested.connect(
            lambda pos: self._freeze_menu(self.vars_table, pos, "var"))
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
        self.sw_table.setHorizontalHeaderLabels(
            [TR("tbl_col_idx"), TR("tbl_col_name"), TR("tbl_col_on")])
        self.sw_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.sw_table.itemChanged.connect(self._on_switch_toggle)
        self.sw_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.sw_table.customContextMenuRequested.connect(
            lambda pos: self._freeze_menu(self.sw_table, pos, "switch"))
        lay.addWidget(self.sw_table, 1)
        hint = QLabel(TR("cheat_sw_hint"))
        lay.addWidget(hint)
        return w

    def _give_selected(self, delta: int):
        """Быстрые кнопки на вкладке предметов: выдать/забрать выделенное."""
        row = self.items_table.currentRow()
        if row < 0:
            return
        item = self.items_table.item(row, 0)
        if item is None:
            return
        key = item.data(Qt.UserRole)
        if not key:
            return
        self._cheat("give_item", kind=key[0], id=key[1], count=delta)

    def _screenshot(self):
        ch = self.main.channel()
        if not ch:
            QMessageBox.information(self, TR("cheat_no_bridge"),
                                    TR("cheat_no_bridge"))
            return
        shot = ch.screenshot() if hasattr(ch, "screenshot") else None
        if not shot:
            self.lbl_status.setText(TR("cheat_screenshot_fail"))
            return
        p = self.main.project
        if not p:
            self.lbl_status.setText(TR("cheat_screenshot_fail"))
            return
        from datetime import datetime
        shot_dir = os.path.join(p.game_dir, "screenshots")
        os.makedirs(shot_dir, exist_ok=True)
        path = os.path.join(shot_dir, "ob_" +
                            datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
        try:
            with open(path, "wb") as f:
                f.write(shot)
        except OSError as e:
            self.lbl_status.setText(
                TR("cheat_screenshot_fail") + f" ({e})")
            return
        self.lbl_status.setText(TR("cheat_screenshot_ok", path=path))

    # ── отправка читов ──
    def _cheat(self, cmd: str, **kwargs):
        ch = self.main.channel()
        if not ch:
            QMessageBox.information(
                self, TR("cheat_no_bridge"),
                TR("cheat_no_bridge") + "\n" + self.main.channel_diag())
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
        self._names_seq += 1
        seq = self._names_seq
        old = self._names_worker
        if old is not None and old.isRunning():
            # никакого terminate()/wait(2000): cooperative отмена,
            # старый поток доработает отмену сам и удалится по finished
            try:
                cancel = getattr(old, "cancel", None)
                if callable(cancel):
                    cancel()
                else:
                    old.requestInterruption()
            except Exception:  # noqa: BLE001, RuntimeError
                pass
            try:
                old.finished.connect(old.deleteLater)
            except Exception:  # noqa: BLE001, RuntimeError
                pass
            # отцепляем сигналы старого, чтобы поздний done не трогал UI;
            # страховка — проверка поколения в _on_names_translated
            for sig_name in ("done", "failed"):
                try:
                    getattr(old, sig_name).disconnect()
                except Exception:  # noqa: BLE001, RuntimeError
                    pass
            # ссылку держим до finished, иначе shiboken снесёт бегущий
            # QThread при переназначении _names_worker -> AV 0xC0000409
            self._hold_zombie(old)
        engine = self.main.create_engine("files")
        if engine is None:
            return
        translator = Translator(engine, tm=self.main.tm,
                                glossary=self.main.glossary)
        tgt = self.main.settings.value("target_lang", "ru")
        self.busy_names.start(TR("cheat_names_translating"))
        worker = NamesWorker(
            translator, tgt,
            self.var_names, self.switch_names,
            self.item_names, self.state_names)
        worker.done.connect(
            lambda v, s, it, st, _seq=seq:
            self._on_names_translated(v, s, it, st, _seq))
        worker.failed.connect(self._on_names_failed)
        worker.finished.connect(worker.deleteLater)
        self._names_worker = worker
        worker.start()

    def _on_names_failed(self, err: str):
        self.busy_names.stop()

    def _on_names_translated(self, v: dict, s: dict, it: dict, st: dict,
                             seq: int | None = None):
        if seq is not None and seq != self._names_seq:
            return  # устаревший worker, результат игнорируем
        self.var_names_tr = v
        self.switch_names_tr = s
        self.item_names_tr = it
        self.busy_names.stop()
        self._fill_vars()
        self._fill_switches()
        self._fill_items()
        self._names_worker = None

    # ── заморозка значений ──
    def _freeze_menu(self, table: QTableWidget, pos, kind: str):
        """Контекстное меню строки: заморозить / снять заморозку."""
        item = table.itemAt(pos)
        if item is None:
            return
        idx = item.data(Qt.UserRole)
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return
        frozen = self._frozen_vars if kind == "var" else self._frozen_switches
        menu = QMenu(self)
        if idx in frozen:
            act = menu.addAction(TR("cheat_unfreeze", idx=idx))
            act.triggered.connect(lambda: self._set_frozen(kind, idx, None))
        else:
            act = menu.addAction(TR("cheat_freeze", idx=idx))
            act.triggered.connect(
                lambda: self._freeze_current(kind, idx))
        menu.exec(table.mapToGlobal(pos))

    def _freeze_current(self, kind: str, idx: int):
        """Заморозить текущее значение из state."""
        try:
            if kind == "var":
                vals = (self.state or {}).get("variables", [])
                cur = vals[idx - 1] if 0 < idx <= len(vals) else 0
                self._set_frozen(kind, idx, cur)
            else:
                vals = (self.state or {}).get("switches", [])
                cur = bool(vals[idx - 1]) if 0 < idx <= len(vals) else False
                self._set_frozen(kind, idx, cur)
        except Exception:  # noqa: BLE001
            pass

    def _set_frozen(self, kind: str, idx: int, value):
        if kind == "var":
            if value is None:
                self._frozen_vars.pop(idx, None)
            else:
                self._frozen_vars[idx] = value
        else:
            if value is None:
                self._frozen_switches.pop(idx, None)
            else:
                self._frozen_switches[idx] = bool(value)
        self._fill_vars()
        self._fill_switches()
        self._enforce_frozen()

    def _enforce_frozen(self):
        """Дожать замороженное в игру (только разошедшееся)."""
        if not self._frozen_vars and not self._frozen_switches:
            return
        try:
            ch = self.main.channel()
        except Exception:  # noqa: BLE001
            return
        if not ch:
            return
        try:
            cmds = frozen_corrections(
                (self.state or {}).get("variables", []),
                (self.state or {}).get("switches", []),
                self._frozen_vars, self._frozen_switches)
        except Exception:  # noqa: BLE001
            return
        for cmd, kw in cmds:
            try:
                ch.send_cheat(cmd, **kw)
            except Exception:  # noqa: BLE001
                continue

    # ── обработка нового состояния ──
    def _on_state(self, state):
        # bridge_state — str (json), но принимаем и готовый dict:
        # json.loads(dict) роняет вкладку с TypeError.
        if not isinstance(state, dict):
            try:
                state = json.loads(state)
            except (TypeError, ValueError):
                return
            if not isinstance(state, dict):
                return
        # сохраняем предыдущее для diff-подсветки
        self._prev_state = self.state
        self.state = state
        # заморозка дожимается сразу, а не следующим тиком (500мс): иначе
        # игра перезаписывает правку между тиками и «не применяется».
        self._enforce_frozen()

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
                if i in self._frozen_vars:
                    f = it_n.font()
                    f.setBold(True)
                    it_n.setFont(f)
                    it_n.setToolTip(TR("cheat_frozen"))
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
                if i in self._frozen_switches:
                    f = it_n.font()
                    f.setBold(True)
                    it_n.setFont(f)
                    it_n.setToolTip(TR("cheat_frozen"))
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
            value = self._coerce_var(item.text())
            self._cheat("var_set", index=idx, value=value)
            # замороженную правим вместе с ячейкой, иначе дожималка
            # вернёт старое значение и «не применяется»
            try:
                if int(idx) in self._frozen_vars:
                    self._frozen_vars[int(idx)] = value
            except (TypeError, ValueError):
                pass
        elif item.column() == 1 and self.main.project:
            self.main.project.var_names[str(idx)] = item.text().strip()
            self.main.save_project()

    def _on_switch_toggle(self, item):
        if self._loading:
            return
        idx = item.data(Qt.UserRole)
        if item.column() == 2:
            value = item.checkState() == Qt.Checked
            self._cheat("switch_set", index=idx, value=value)
            try:
                if int(idx) in self._frozen_switches:
                    self._frozen_switches[int(idx)] = value
            except (TypeError, ValueError):
                pass
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
