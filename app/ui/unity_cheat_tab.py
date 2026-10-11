# -*- coding: utf-8 -*-
"""Вкладки читов Unity: живые переменные отдельно, файлы отдельно.

Структура как у Twine (текст/перевод + редактор сейвов), а не свалка
всё-в-одном: пустой источник не занимает целую страницу.

* ``UnityCheatsTab`` — только живая игра: статические поля запущенного
  процесса через Mono-рантайм. Канал — лишь к игре, которую запустило
  приложение. Без канала — честная пустая страница, а не таблица ни о чём.
* ``UnitySavesTab`` — всё, что игра пишет сама: JSON-сейвы (LocalLow и
  папка игры) и PlayerPrefs (реестр). Правка по Enter, бэкап до записи,
  откат из автобэкапов.

Наружу идут только технические имена и числа — не текст игры.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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

from app.core.unity import json_save
from app.core.unity import playerprefs as pp
from app.ui.i18n import TR


def _empty(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        "color:#757c94; border:2px dashed #3a3d4f; border-radius:10px;"
        "padding:24px;")
    return lbl


def _parse(kind: str, text: str):
    """Строка из ячейки -> значение нужного типа. Мусор — отказ."""
    text = (text or "").strip()
    if kind == "bool":
        return json_save.as_bool(text)
    return pp.parse_input(text, kind if kind in
                          ("int", "float", "bytes") else "auto")


class UnityScanTab(QWidget):
    """Поиск по памяти игры — как в Cheat Engine.

    Один инструмент вместо двух: ни списка полей, ни правки сейвов. И то и
    другое ломало игру — потому что приложение угадывало, что значит то или
    иное поле. Здесь угадывать нечего: игрок сам называет значение
    («у меня 2 уровня»), находит его среди мусора и сужает список повторным
    поиском, пока не останется нужный адрес.

    Правка значения делается только по адресу, который игрок выбрал сам.
    """

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._rows: list[dict] = []
        self._loading = False
        self._touched: dict[str, object] = {}
        self._kind = "i32"

        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.inp_value = QLineEdit()
        self.inp_value.setPlaceholderText(TR("unity_scan_value_ph"))
        self.inp_value.returnPressed.connect(self.scan)
        bar.addWidget(self.inp_value, 1)

        self.cmb_kind = QComboBox()
        for kind, label in self._kinds():
            self.cmb_kind.addItem(label, kind)
        self.cmb_kind.currentIndexChanged.connect(
            lambda _i: self._on_kind_changed())
        bar.addWidget(self.cmb_kind)

        self.btn_scan = QPushButton(TR("unity_scan_find"))
        self.btn_scan.clicked.connect(self.scan)
        bar.addWidget(self.btn_scan)

        self.cmb_filter = QComboBox()
        # ключи пишем явно: проверка «все TR() есть в i18n» не умеет
        # собирать имя из кусков и рапортовала бы ложной пропажей
        for key, mode in (("unity_scan_f_changed", "changed"),
                          ("unity_scan_f_same", "same"),
                          ("unity_scan_f_inc", "inc"),
                          ("unity_scan_f_dec", "dec")):
            self.cmb_filter.addItem(TR(key), mode)
        bar.addWidget(self.cmb_filter)

        self.btn_next = QPushButton(TR("unity_scan_next"))
        self.btn_next.clicked.connect(self.next_scan)
        self.btn_next.setEnabled(False)
        bar.addWidget(self.btn_next)

        self.btn_reset = QPushButton(TR("unity_scan_reset"))
        self.btn_reset.clicked.connect(self.reset)
        self.btn_reset.setEnabled(False)
        bar.addWidget(self.btn_reset)

        self.btn_undo = QPushButton(TR("unity_scan_restore"))
        self.btn_undo.clicked.connect(self.undo)
        self.btn_undo.setEnabled(False)
        bar.addWidget(self.btn_undo)
        lay.addLayout(bar)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.lbl_hint = QLabel(TR("unity_scan_hint"))
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color:#757c94;")
        lay.addWidget(self.lbl_hint)

        self.stack = QStackedWidget()
        self.stack.addWidget(_empty(TR("unity_scan_empty")))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(
            [TR("unity_scan_addr"), TR("unity_scan_val")])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_edit)
        self.stack.addWidget(self.table)
        lay.addWidget(self.stack, 1)

    @staticmethod
    def _kinds() -> list:
        return [
            ("i32", TR("unity_scan_kind", t=TR("unity_scan_k_int"), n=4)),
            ("u32", TR("unity_scan_kind", t=TR("unity_scan_k_uint"), n=4)),
            ("i64", TR("unity_scan_kind", t=TR("unity_scan_k_int"), n=8)),
            ("f32", TR("unity_scan_kind", t=TR("unity_scan_k_float"), n=4)),
            ("f64", TR("unity_scan_kind", t=TR("unity_scan_k_float"), n=8)),
            ("i16", TR("unity_scan_kind", t=TR("unity_scan_k_int"), n=2)),
            ("i8", TR("unity_scan_kind", t=TR("unity_scan_k_int"), n=1)),
        ]

    # ── канал ───────────────────────────────────────────────────────────────

    def _tentacle(self):
        try:
            tent = self.main.session.tentacle
        except Exception:
            tent = None
        if tent is None or not getattr(tent, "is_attached", lambda: False)():
            return None
        return tent

    def _why_empty(self) -> str:
        try:
            tent = self.main.session.tentacle
        except Exception:
            tent = None
        reason = ""
        if tent is not None:
            reason = str(getattr(tent, "rpc_error", "") or "").strip()
        return reason or TR("unity_live_empty")

    def on_project_opened(self):
        self._rows = []
        self._touched = {}
        self.btn_undo.setEnabled(False)
        self.btn_next.setEnabled(False)
        self.btn_reset.setEnabled(False)
        self.lbl_status.setText("")
        self._fill()

    # ── поиск ───────────────────────────────────────────────────────────────

    def _on_kind_changed(self) -> None:
        self._kind = self.cmb_kind.currentData() or "i32"
        self.reset()

    def reset(self) -> None:
        self._rows = []
        self.btn_next.setEnabled(False)
        self.btn_reset.setEnabled(False)
        self._fill()
        self.lbl_status.setText("")

    def _parse(self, text: str):
        text = (text or "").strip().replace(",", ".")
        if not text:
            raise ValueError(TR("unity_scan_no_value"))
        try:
            if self._kind in ("f32", "f64"):
                return float(text)
            return int(text, 0)
        except ValueError as e:
            raise ValueError(TR("unity_scan_bad_number", s=text[:20])) from e

    def scan(self) -> None:
        tent = self._tentacle()
        if tent is None:
            self.lbl_status.setText(self._why_empty())
            return
        try:
            value = self._parse(self.inp_value.text())
        except ValueError as e:
            self.lbl_status.setText(str(e))
            return
        self.btn_scan.setEnabled(False)
        self.lbl_status.setText(TR("unity_scan_working"))
        QApplication.processEvents()
        try:
            res = tent.scan_memory(value, self._kind)
        finally:
            self.btn_scan.setEnabled(True)
        if res.get("error"):
            self.lbl_status.setText(str(res["error"]))
            return
        self._rows = [{"addr": r["addr"], "value": _as_num(r["value"])}
                      for r in res.get("data") or []]
        self.btn_next.setEnabled(bool(self._rows))
        self.btn_reset.setEnabled(bool(self._rows))
        self._fill()
        if not self._rows:
            self.lbl_status.setText(TR("unity_scan_none"))
            return
        # честно показываем и отброшенное: иначе игрок видит «0 найдено»
        # и думает, что инструмент сломан, хотя это были текстуры
        note = ""
        if res.get("skipped"):
            note = " " + TR("unity_scan_skipped", n=res["skipped"])
        key = "unity_scan_truncated" if res.get("truncated") \
            else "unity_scan_found"
        self.lbl_status.setText(TR(
            key, n=len(self._rows), ms=res.get("ms", 0),
            mb=round((res.get("bytes") or 0) / 1048576)) + note)

    def next_scan(self) -> None:
        tent = self._tentacle()
        if tent is None or not self._rows:
            self.lbl_status.setText(self._why_empty())
            return
        mode = self.cmb_filter.currentData() or "changed"
        addrs = [r["addr"] for r in self._rows]
        fresh = tent.read_memory(addrs, self._kind)
        if not fresh:
            self.lbl_status.setText(TR("unity_scan_all_gone"))
            self._rows = []
            self.btn_next.setEnabled(False)
            self._fill()
            return
        out = []
        for item in fresh:
            addr = item["addr"]
            now = _as_num(item["value"])
            old_row = next((r for r in self._rows if r["addr"] == addr), None)
            if old_row is None:
                continue
            before = old_row["value"]
            keep = ((mode == "changed" and now != before)
                    or (mode == "same" and now == before)
                    or (mode == "inc" and now > before)
                    or (mode == "dec" and now < before))
            if keep:
                out.append({"addr": addr, "value": now})
        self._rows = out
        self.btn_next.setEnabled(bool(out))
        self.btn_reset.setEnabled(True)
        self._fill()
        self.lbl_status.setText(
            TR("unity_scan_left", n=len(out)) if out
            else TR("unity_scan_none"))

    # ── таблица ─────────────────────────────────────────────────────────────

    def _fill(self) -> None:
        self._loading = True
        try:
            self.table.setRowCount(len(self._rows))
            for i, row in enumerate(self._rows):
                self.table.setItem(i, 0, QTableWidgetItem(row["addr"]))
                cell = QTableWidgetItem(_fmt(self._kind, row["value"]))
                cell.setData(Qt.UserRole, row)
                cell.setFlags(cell.flags() | Qt.ItemIsEditable)
                self.table.setItem(i, 1, cell)
        finally:
            self._loading = False
        self.stack.setCurrentIndex(1 if self._rows else 0)

    def _on_edit(self, item) -> None:
        if item is None or self._loading or item.column() != 1:
            return
        row = item.data(Qt.UserRole)
        tent = self._tentacle()
        if not row or tent is None:
            return
        try:
            value = self._parse(item.text())
        except ValueError as e:
            QMessageBox.warning(self, TR("err"), str(e))
            self._reset_cell(item, row)
            return
        ok, res = tent.write_memory(row["addr"], value, self._kind)
        if not ok:
            QMessageBox.warning(self, TR("err"),
                                TR("unity_scan_write_err", e=res))
            self._reset_cell(item, row)
            return
        # запоминаем былое — «Вернуть» должно работать всегда
        self._touched.setdefault(row["addr"], row["value"])
        self.btn_undo.setEnabled(True)
        row["value"] = _as_num(res)
        self._reset_cell(item, row)
        self.lbl_status.setText(TR(
            "unity_scan_written", addr=row["addr"],
            v=_fmt(self._kind, _as_num(res))))

    def _reset_cell(self, item, row) -> None:
        self.table.blockSignals(True)
        try:
            item.setText(_fmt(self._kind, row["value"]))
        finally:
            self.table.blockSignals(False)

    def undo(self) -> None:
        tent = self._tentacle()
        if tent is None or not self._touched:
            return
        back = 0
        for addr, old in list(self._touched.items()):
            ok, _res = tent.write_memory(addr, old, self._kind)
            if ok:
                back += 1
        self._touched = {}
        self.btn_undo.setEnabled(False)
        self.next_scan()
        self.lbl_status.setText(TR("unity_scan_restored", n=back))

    def reload_live(self):
        """Совместимость с вызовом движка: пересканировать."""
        self.next_scan() if self._rows else self.scan()


def _as_num(value):
    """Привести значение из агента к числу (i64 приходит строкой)."""
    if isinstance(value, (int, float)):
        return value
    try:
        text = str(value).strip()
        return float(text) if ("." in text or "e" in text.lower()) \
            else int(text)
    except (TypeError, ValueError):
        return 0


def _fmt(kind: str, value) -> str:
    if kind in ("f32", "f64"):
        try:
            f = float(value)
        except (TypeError, ValueError):
            return str(value)
        return ("%.6f" % f).rstrip("0").rstrip(".") or "0"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


class UnitySavesTab(QWidget):
    """Файлы игры: JSON-сейвы и PlayerPrefs. Без запусков и каналов."""

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._rows: list[dict] = []
        self._loading = False
        self._prefs_backed_up = False
        self._edited_saves: set[str] = set()
        self._save_files: list[str] = []
        self._file = ""

        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.btn_reload = QPushButton(TR("unity_prefs_reload"))
        self.btn_reload.clicked.connect(self.reload_all)
        bar.addWidget(self.btn_reload)

        # Выбор ФАЙЛА: у игры бывает много сейвов (слоты), и без выбора
        # строки разных файлов слипаются в одну таблицу — править не
        # понятно что. Список файлов, а не папок.
        self.cmb_file = QComboBox()
        self.cmb_file.currentIndexChanged.connect(self._on_file_changed)
        bar.addWidget(self.cmb_file, 1)

        self.search = QLineEdit()
        self.search.setPlaceholderText(TR("cheat_item_search"))
        self.search.textChanged.connect(self._fill)
        bar.addWidget(self.search, 1)

        self.chk_system = QCheckBox(TR("unity_prefs_show_system"))
        self.chk_system.toggled.connect(lambda _v: self._fill())
        bar.addWidget(self.chk_system)
        lay.addLayout(bar)

        # Правка сейвов убрана: игрок сообщил, что после неё игра ломалась.
        # Вкладка остаётся посмотреть, что вообще записано, — читать
        # безопасно. Кнопок записи/бэкапа/отката больше нет.
        self.lbl_ro = QLabel(TR("unity_saves_readonly"))
        self.lbl_ro.setWordWrap(True)
        self.lbl_ro.setStyleSheet("color:#757c94;")
        lay.addWidget(self.lbl_ro)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.stack = QStackedWidget()
        self.stack.addWidget(_empty(TR("unity_saves_empty2")))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            TR("unity_col_src"), TR("unity_prefs_name"),
            TR("unity_prefs_kind"), TR("unity_prefs_value")])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_edit)
        self.stack.addWidget(self.table)
        lay.addWidget(self.stack, 1)

    # ── загрузка ────────────────────────────────────────────────────────────

    def on_project_opened(self):
        self._prefs_backed_up = False
        self._edited_saves = set()
        # новый проект — показываем ВСЕ файлы; выбор игрока запоминается
        # только между перезагрузками внутри одного проекта
        self._file = ""
        self.reload_all()

    def reload_all(self):
        self._rows = []
        self._reload_files()
        self._rows.extend(self._load_saves())
        self._rows.extend(self._load_prefs())
        self._rows.sort(key=lambda r: (r["source"] != "сейв",
                                       r["name"].lower()))
        n_save = sum(1 for r in self._rows if r["source"] == "сейв")
        n_prefs = sum(1 for r in self._rows if r["source"] == "реестр")
        if self._rows:
            hint = TR("unity_saves_search_hint")
            # правка при запущенной игре бессмысленна: она перезапишет
            # файл при выходе и затрёт всё, что мы записали
            if self._game_running():
                hint = TR("unity_saves_game_running") + " " + hint
            self.lbl_status.setText(
                TR("unity_saves_count", save=n_save, prefs=n_prefs)
                + "  " + hint)
        else:
            self.lbl_status.setText(TR("unity_saves_empty2"))
        self._fill()

    def _game_running(self) -> bool:
        try:
            tent = self.main.session.tentacle
        except Exception:
            return False
        if tent is None:
            return False
        try:
            return bool(getattr(tent, "is_attached", lambda: False)())
        except Exception:
            return False

    # ── выбор файла сейва ───────────────────────────────────────────────────

    def _reload_files(self) -> None:
        p = self.main.project
        try:
            paths = json_save.find_saves(p.game_dir) if p else []
        except OSError:
            paths = []
        self._save_files = list(paths)
        prev = self._file
        self.cmb_file.blockSignals(True)
        try:
            self.cmb_file.clear()
            # один файл — выбор не нужен, показывать незачем
            self.cmb_file.setVisible(len(paths) > 1)
            if not paths:
                self._file = ""
            elif len(paths) == 1:
                self._file = paths[0]
                self.cmb_file.addItem(_file_label(paths[0]), paths[0])
            else:
                self._file = prev if prev in paths else ""
                self.cmb_file.addItem(
                    TR("unity_saves_all_files", n=len(paths)), "")
                for path in paths:
                    self.cmb_file.addItem(_file_label(path), path)
                idx = self.cmb_file.findData(self._file)
                self.cmb_file.setCurrentIndex(max(idx, 0))
        finally:
            self.cmb_file.blockSignals(False)

    def _on_file_changed(self, _index: int) -> None:
        self._file = self.cmb_file.currentData() or ""
        self.reload_all()

    def _load_saves(self) -> list[dict]:
        # выбран конкретный файл — грузим только его; «все файлы» — все
        chosen = [self._file] if self._file else list(self._save_files)
        if not chosen:
            return []
        multi = len(chosen) > 1
        rows = []
        for path in chosen:
            try:
                flat = json_save.flatten(json_save.load_json(path))
            except json_save.SaveError:
                continue
            base = _file_label(path)
            for dotted, value in sorted(flat.items()):
                if isinstance(value, (dict, list)) or value is None:
                    continue
                rows.append({
                    "source": "сейв",
                    # в общем списке файлы не путаются: в имени видно,
                    # из какого сейва строка
                    "name": ("%s: %s" % (base, dotted)) if multi else dotted,
                    "type": type(value).__name__,
                    "kind": ("bool" if isinstance(value, bool)
                             else "float" if isinstance(value, float)
                             else "int" if isinstance(value, int)
                             else "str"),
                    "value": value,
                    "ref": {"path": path, "dotted": dotted},
                })
        return rows

    def _load_prefs(self) -> list[dict]:
        p = self.main.project
        if not p:
            return []
        try:
            prefs = pp.read_prefs(p.game_dir)
        except (pp.PrefError, OSError):
            return []
        return [{
            "source": "реестр",
            "name": item["name"],
            "type": item["kind"],
            "kind": item["kind"],
            "value": item["value"],
            "system": bool(item.get("system")),
            "ref": {"name": item["name"]},
        } for item in prefs]

    # ── таблица ─────────────────────────────────────────────────────────────

    def _visible(self) -> list[dict]:
        q = self.search.text().strip().lower()
        show_system = self.chk_system.isChecked()
        out = []
        for row in self._rows:
            if row["source"] == "реестр" and row.get("system") \
                    and not show_system:
                continue
            if q and q not in row["name"].lower():
                continue
            out.append(row)
        return out

    def _fill(self):
        rows = self._visible()
        self._loading = True
        try:
            self.table.setRowCount(len(rows))
            for i, row in enumerate(rows):
                self.table.setItem(i, 0, QTableWidgetItem(row["source"]))
                self.table.setItem(i, 1, QTableWidgetItem(row["name"]))
                self.table.setItem(i, 2, QTableWidgetItem(row["type"]))
                cell = QTableWidgetItem(_render_file(row))
                cell.setData(Qt.UserRole, row)
                # только чтение: правка сейвов ломала игру
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                cell.setToolTip(TR("unity_saves_readonly"))
                self.table.setItem(i, 3, cell)
        finally:
            self._loading = False
        self.stack.setCurrentIndex(1 if rows else 0)

    def _on_edit(self, item):
        if item is None:
            return
        if self._loading or item.column() != 3:
            return
        row = item.data(Qt.UserRole)
        if not row:
            return
        try:
            value = _parse(row.get("kind") or "auto", item.text())
        except (pp.PrefError, json_save.SaveError, ValueError) as e:
            QMessageBox.warning(self, TR("err"), str(e))
            self._reset_cell(item, row)
            return
        ok, why = self._write(row, value)
        if ok:
            row["value"] = value
            self._reset_cell(item, row)
            self.lbl_status.setText(TR("unity_cheats_written",
                                       name=row["name"]))
        else:
            QMessageBox.warning(self, TR("err"), why or TR("err"))
            self._reset_cell(item, row)

    def _reset_cell(self, item, row):
        self.table.blockSignals(True)
        try:
            item.setText(_render_file(row))
        finally:
            self.table.blockSignals(False)

    # ── запись ──────────────────────────────────────────────────────────────

    def _write(self, row: dict, value) -> tuple[bool, str]:
        p = self.main.project
        if not p:
            return False, TR("err")
        try:
            if row.get("source") == "сейв":
                return self._write_save(row, value)
            return self._write_prefs(p.game_dir, row, value)
        except (pp.PrefError, json_save.SaveError, OSError) as e:
            return False, str(e)

    def _write_save(self, row: dict, value) -> tuple[bool, str]:
        ref = row.get("ref", {})
        path, dotted = ref.get("path", ""), ref.get("dotted", "")
        if not path or not dotted:
            return False, TR("err")
        try:
            data = json_save.load_json(path)
        except json_save.SaveError as e:
            return False, str(e)
        new, skipped = json_save.set_paths(data, {dotted: value})
        if skipped:
            return False, "%s — %s" % (skipped[0][0], skipped[0][1])
        try:
            json_save.save_json(path, new)
        except json_save.SaveError as e:
            return False, str(e)
        self._edited_saves.add(path)
        return True, ""

    def _write_prefs(self, game_dir: str, row: dict, value) -> tuple[bool, str]:
        if not self._prefs_backed_up:
            try:
                pp.export_prefs(game_dir, self._prefs_backup_path())
            except (pp.PrefError, OSError) as e:
                return False, str(e)
            self._prefs_backed_up = True
        try:
            pp.set_pref(game_dir, row.get("ref", {}).get("name", ""), value)
        except (pp.PrefError, OSError) as e:
            return False, str(e)
        return True, ""

    # ── бэкап / откат ───────────────────────────────────────────────────────

    def _prefs_backup_path(self) -> str:
        p = self.main.project
        base = os.path.join(p.game_dir, "backup", "unity") if p \
            else os.path.join(".", "backup", "unity")
        return os.path.join(base, "playerprefs.json")

    def _backup_all(self):
        p = self.main.project
        if not p:
            return
        try:
            dest = pp.export_prefs(p.game_dir, self._prefs_backup_path())
        except (pp.PrefError, OSError) as e:
            QMessageBox.critical(self, TR("err"), str(e))
            return
        self._prefs_backed_up = True
        QMessageBox.information(
            self, TR("done"), TR("unity_prefs_backup_done", path=dest,
                                 n=sum(1 for r in self._rows
                                       if r["source"] == "реестр")))

    def _restore_all(self):
        p = self.main.project
        if not p:
            return
        if QMessageBox.question(
                self, TR("unity_prefs_restore"),
                TR("unity_cheats_restore_q")) != QMessageBox.Yes:
            return
        restored, errors = 0, []
        dest = self._prefs_backup_path()
        if os.path.isfile(dest):
            try:
                res = pp.import_prefs(p.game_dir, dest)
                restored += int(res.get("restored", 0))
                errors.extend(res.get("errors", []))
            except (pp.PrefError, OSError, ValueError) as e:
                errors.append(str(e))
        for path in sorted(self._edited_saves):
            try:
                if json_save.restore_backup(path):
                    restored += 1
            except OSError as e:
                errors.append("%s: %s" % (os.path.basename(path), e))
        self.reload_all()
        if errors:
            QMessageBox.warning(
                self, TR("done"),
                TR("unity_cheats_restored_errors",
                   n=restored, problems="\n".join(errors[:8])))
        else:
            QMessageBox.information(
                self, TR("done"), TR("unity_prefs_restored", n=restored))


def _render_file(row: dict) -> str:
    value = row.get("value")
    if row.get("kind") == "bytes":
        return pp.format_value({"kind": "bytes", "value": value or b""})
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _file_label(path: str) -> str:
    """Имя файла сейва; одинаковые имена различаем папкой.

    Без этого пять слотов `save.json` в разных каталогах выглядят в
    списке как пять одинаковых строк — выбрать нужный невозможно.
    """
    base = os.path.basename(path) or path
    parent = os.path.basename(os.path.dirname(path) or "")
    return "%s / %s" % (parent, base) if parent else base
