# -*- coding: utf-8 -*-
"""Вкладка «Карты»: интерактивная карта с контекстным меню.

Левая колонка: список карт + текущая карта игрока.
Правая колонка: полная отрисовка карты (тайлсеты) + зум.
Клик по карте: пустой клетка → телепорт; событие → меню редактирования.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox,
                                QHBoxLayout, QLabel, QLineEdit, QListWidget,
                                QListWidgetItem, QMenu, QMessageBox,
                                QPushButton, QScrollArea, QSpinBox,
                                QSplitter, QVBoxLayout, QWidget)

from app.core.rpgmaker import crypto, maprender
from app.core.rpgmaker.varnames import extract_maps
from app.ui.i18n import TR
from app.ui.icons import icon

ZOOM_LEVELS = [25, 50, 75, 100, 150, 200]

_DIR_ROW = {2: 0, 4: 1, 6: 2, 8: 3}


class MapCanvas(QLabel):
    """QLabel с интерактивной картой: левый клик — выбор, правый — меню."""

    def __init__(self, tab):
        super().__init__()
        self._tab = tab
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setStyleSheet("background: #1a1a1a;")
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            x, y = self._tile_at(event)
            self._tab.select_event_at(x, y)
        super().mousePressEvent(event)

    def _tile_at(self, event_or_pos) -> tuple[int, int]:
        zoom = self._tab.zoom_factor()
        if hasattr(event_or_pos, "position"):
            px = event_or_pos.position().x()
            py = event_or_pos.position().y()
        else:
            px = event_or_pos.x()
            py = event_or_pos.y()
        x = int(px / (maprender.TILE * zoom))
        y = int(py / (maprender.TILE * zoom))
        return x, y

    def _show_menu(self, pos):
        x, y = self._tile_at(pos)
        self._tab.show_tile_menu(x, y, self.mapToGlobal(pos))


class MapTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._maps: list[tuple[int, str]] = []
        self._map_data: dict | None = None
        self._map_id: int = 0
        self._pages_img: dict[int, QImage] = {}
        self._char_img: dict[str, QImage] = {}
        self._tilesets_loaded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # ── левая панель: только карты ──
        left = QWidget()
        left.setMinimumWidth(200)
        left.setMaximumWidth(320)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(4, 4, 4, 4)

        self.lbl_player_map = QLabel("")
        self.lbl_player_map.setStyleSheet(
            "font-size: 11px; color: #8cf; padding: 2px 4px;")
        ll.addWidget(self.lbl_player_map)

        self.map_search = QLineEdit()
        self.map_search.setPlaceholderText(TR("map_search_ph"))
        self.map_search.textChanged.connect(self._fill_maps)
        ll.addWidget(self.map_search)

        self.map_list = QListWidget()
        self.map_list.currentRowChanged.connect(self._on_map_selected)
        ll.addWidget(self.map_list, 1)

        split.addWidget(left)

        # ── правая панель: канвас ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 4, 4, 4)
        rl.setSpacing(4)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(TR("map_zoom")))
        self.zoom_combo = QComboBox()
        self.zoom_combo.addItems([f"{z}%" for z in ZOOM_LEVELS])
        self.zoom_combo.setCurrentIndex(1)
        self.zoom_combo.currentIndexChanged.connect(self._refresh_canvas)
        bar.addWidget(self.zoom_combo)
        self.lbl_map_info = QLabel("")
        bar.addWidget(self.lbl_map_info, 1)
        bar.addStretch(1)
        self.btn_save = QPushButton(TR("map_save"))
        self.btn_save.setIcon(icon("save"))
        self.btn_save.setObjectName("accent")
        self.btn_save.clicked.connect(self._save_map)
        bar.addWidget(self.btn_save)
        rl.addLayout(bar)

        self.canvas = MapCanvas(self)
        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(False)
        rl.addWidget(scroll, 1)

        split.addWidget(right)
        split.setSizes([240, 960])

        self.main.bridge_state.connect(self._on_state)

    # ── helpers ──
    def zoom_factor(self) -> float:
        return ZOOM_LEVELS[self.zoom_combo.currentIndex()] / 100.0

    def _game_dir(self) -> str | None:
        p = self.main.project
        return p.game_dir if p else None

    # ── загрузка ──
    def showEvent(self, event):
        super().showEvent(event)
        self.reload()

    def reload(self):
        game_dir = self._game_dir()
        self._maps = extract_maps(game_dir) if game_dir else []
        self._fill_maps()

    def _fill_maps(self):
        q = self.map_search.text().strip().lower()
        self.map_list.clear()
        for mid, name in self._maps:
            if q and q not in name.lower() and q != str(mid):
                continue
            it = QListWidgetItem(f"{mid:03d}  {name}")
            it.setData(Qt.UserRole, mid)
            self.map_list.addItem(it)

    def _on_map_selected(self, row: int):
        if row < 0:
            return
        it = self.map_list.item(row)
        self._load_map(it.data(Qt.UserRole))

    def _load_map(self, map_id: int):
        game_dir = self._game_dir()
        self._map_data = maprender.load_map(game_dir, map_id) \
            if game_dir else None
        self._map_id = map_id
        self._pages_img.clear()
        self._char_img.clear()
        self._tilesets_loaded = False
        self._render_canvas()

    # ── рендер: полный (с тайлсетами, кеш) ──
    def _page_image(self, page: int) -> QImage | None:
        if page in self._pages_img:
            return self._pages_img[page]
        game_dir = self._game_dir()
        tileset = maprender.tileset_for_map(
            maprender.load_tilesets(game_dir),
            (self._map_data or {}).get("tilesetId", 1)) if game_dir else None
        if not tileset:
            return None
        names = tileset.get("tilesetNames") or []
        if page >= len(names) or not names[page]:
            return None
        raw = crypto.read_image(game_dir, f"img/tilesets/{names[page]}")
        if not raw:
            self._pages_img[page] = None
            return None
        img = QImage.fromData(raw, "PNG")
        self._pages_img[page] = img if not img.isNull() else None
        return self._pages_img[page]

    def _draw_tile(self, painter: QPainter, tile_id: int, dx: int, dy: int):
        src = maprender.tile_source(tile_id)
        if not src:
            return
        page, sx, sy = src
        img = self._page_image(page)
        t = maprender.TILE
        if img is None:
            painter.fillRect(dx, dy, t, t, QColor(70, 40, 40, 160))
            return
        if sx + t > img.width() or sy + t > img.height():
            return
        painter.drawImage(dx, dy, img, sx, sy, t, t)

    def _render_canvas(self):
        if not self._map_data:
            self.canvas.setText(TR("map_none"))
            self.canvas.setPixmap(QPixmap())
            return
        w, h, ground, overlay, shadow = maprender.map_layers(self._map_data)
        t = maprender.TILE
        img = QImage(w * t, h * t, QImage.Format_ARGB32)
        img.fill(QColor(24, 24, 24))
        painter = QPainter(img)
        for cy in range(h):
            for cx in range(w):
                i = cy * w + cx
                if i < len(ground):
                    self._draw_tile(painter, ground[i], cx * t, cy * t)
                if i < len(overlay):
                    self._draw_tile(painter, overlay[i], cx * t, cy * t)
        painter.setPen(Qt.NoPen)
        for cy in range(h):
            for cx in range(w):
                i = cy * w + cx
                if i >= len(shadow) or not shadow[i]:
                    continue
                v = shadow[i]
                half = t // 2
                for bit, (qx, qy) in ((1, (0, 0)), (2, (half, 0)),
                                      (4, (0, half)), (8, (half, half))):
                    if v & bit:
                        painter.fillRect(cx * t + qx, cy * t + qy,
                                         half, half, QColor(0, 0, 40, 90))
        # события — маркеры
        for ev in self._map_data.get("events") or []:
            if not isinstance(ev, dict):
                continue
            ex, ey = ev.get("x", 0) * t, ev.get("y", 0) * t
            pages = ev.get("pages") or []
            img_ev = (pages[0].get("image") or {}) if pages else {}
            ch_name = img_ev.get("characterName", "")
            if ch_name:
                self._draw_char(painter, ch_name, img_ev, ex, ey)
            elif img_ev.get("tileId"):
                self._draw_tile(painter, img_ev["tileId"], ex, ey)
            else:
                painter.fillRect(ex + 8, ey + 8, t - 16, t - 16,
                                 QColor(220, 160, 40, 110))
            painter.setPen(QColor(255, 200, 60, 180))
            painter.drawRect(ex + 1, ey + 1, t - 2, t - 2)
            painter.setPen(Qt.NoPen)
        painter.end()

        zoom = self.zoom_factor()
        pm = QPixmap.fromImage(img).scaled(
            int(w * t * zoom), int(h * t * zoom),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.canvas.setPixmap(pm)
        self.canvas.resize(pm.size())
        name = self._map_data.get("displayName") or ""
        self.lbl_map_info.setText(
            TR("map_info", id=self._map_id, w=w, h=h, name=name))

    def _draw_char(self, painter, name, img_ev, ex, ey):
        ch = self._char_image(name)
        if ch is None:
            painter.fillRect(ex + 8, ey + 8, maprender.TILE - 16,
                             maprender.TILE - 16, QColor(220, 160, 40, 110))
            return
        t = maprender.TILE
        idx = img_ev.get("characterIndex", 0)
        big = name.startswith("$")
        if big:
            cw, ch_h = ch.width() / 3, ch.height() / 4
            sx = (img_ev.get("pattern", 1) % 3) * cw
            sy = _DIR_ROW.get(img_ev.get("direction", 2), 0) * ch_h
        else:
            cw, ch_h = ch.width() / 12, ch.height() / 8
            col, row = idx % 4, idx // 4
            sx = col * 3 * cw + (img_ev.get("pattern", 1) % 3) * cw
            sy = row * 4 * ch_h + _DIR_ROW.get(img_ev.get("direction", 2), 0) * ch_h
        scale = t / cw
        painter.drawImage(
            int(ex), int(ey + t - ch_h * scale), ch,
            int(sx), int(sy), int(cw), int(ch_h))

    def _char_image(self, name: str) -> QImage | None:
        if name in self._char_img:
            return self._char_img[name]
        game_dir = self._game_dir()
        raw = crypto.read_image(game_dir, f"img/characters/{name}") \
            if game_dir else None
        img = QImage.fromData(raw, "PNG") if raw else QImage()
        self._char_img[name] = img if not img.isNull() else None
        return self._char_img[name]

    def _refresh_canvas(self):
        if self._map_data:
            self._render_canvas()

    # ── контекстное меню по клику на тайле ──
    def show_tile_menu(self, x: int, y: int, global_pos):
        if not self._map_data:
            return
        w, h, *_ = maprender.map_layers(self._map_data)
        if x < 0 or x >= w or y < 0 or y >= h:
            return
        ev = self._event_at(x, y)
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: #2a2a2a; border: 1px solid #555; "
            f"border-radius: 4px; padding: 2px; }}"
            f"QMenu::item {{ padding: 5px 16px; color: #ddd; }}"
            f"QMenu::item:selected {{ background: #0078d4; color: #fff; }}")

        if ev:
            s = maprender.event_summary(ev)
            title = menu.addAction(f"EV{s['id']}  {s['name']}")
            title.setEnabled(False)
            menu.addSeparator()

            act_tp = menu.addAction(TR("map_ctx_teleport"))
            act_tp.triggered.connect(
                lambda: self._send_teleport(self._map_id, x, y))

            menu.addSeparator()
            act_edit = menu.addAction(TR("map_ctx_edit"))
            act_edit.triggered.connect(lambda: self._edit_event_dialog(ev))

            pages = ev.get("pages") or []
            page = pages[0] if pages else {}
            cond = maprender.page_conditions(page)
            if cond["switch1_valid"]:
                sw_id = cond["switch1_id"]
                act_sw = menu.addAction(
                    TR("map_ctx_toggle_sw").format(id=sw_id))
                act_sw.triggered.connect(
                    lambda sid=sw_id: self._toggle_switch_live(sid))
        else:
            act_tp = menu.addAction(TR("map_ctx_teleport_here"))
            act_tp.triggered.connect(
                lambda: self._send_teleport(self._map_id, x, y))

        menu.exec(global_pos)

    def _event_at(self, x: int, y: int) -> dict | None:
        if not self._map_data:
            return None
        for ev in self._map_data.get("events") or []:
            if isinstance(ev, dict) and ev.get("x") == x and ev.get("y") == y:
                return ev
        return None

    def select_event_at(self, x: int, y: int):
        ev = self._event_at(x, y)
        if ev:
            self._edit_event_dialog(ev)

    # ── диалог редактирования события ──
    def _edit_event_dialog(self, ev: dict):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        s = maprender.event_summary(ev)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"EV{s['id']} — {s['name']}")
        dlg.setMinimumWidth(380)
        lay = QVBoxLayout(dlg)
        form = QFormLayout()

        ed_name = QLineEdit(s["name"])
        form.addRow(TR("map_name"), ed_name)

        pos_row = QWidget()
        pl = QHBoxLayout(pos_row)
        pl.setContentsMargins(0, 0, 0, 0)
        sp_x = QSpinBox()
        sp_x.setRange(0, 999)
        sp_x.setValue(s["x"])
        sp_y = QSpinBox()
        sp_y.setRange(0, 999)
        sp_y.setValue(s["y"])
        pl.addWidget(QLabel("X:"))
        pl.addWidget(sp_x)
        pl.addWidget(QLabel("Y:"))
        pl.addWidget(sp_y)
        pl.addStretch(1)
        form.addRow(TR("map_pos"), pos_row)

        page_combo = QComboBox()
        for i in range(s["pages"]):
            page_combo.addItem(f"{i + 1}")
        pages = ev.get("pages") or []
        page = pages[0] if pages else {}
        form.addRow(TR("map_page"), page_combo)

        lbl_trigger = QLabel(
            maprender.TRIGGER_NAMES.get(page.get("trigger", 0), "?"))
        form.addRow(TR("map_trigger"), lbl_trigger)

        c = maprender.page_conditions(page)
        cb_sw1 = QCheckBox(TR("map_sw1"))
        cb_sw1.setChecked(c["switch1_valid"])
        sp_sw1 = QSpinBox()
        sp_sw1.setRange(1, 9999)
        sp_sw1.setValue(c["switch1_id"])
        sw1_row = QWidget()
        sw1_l = QHBoxLayout(sw1_row)
        sw1_l.setContentsMargins(0, 0, 0, 0)
        sw1_l.addWidget(cb_sw1)
        sw1_l.addWidget(sp_sw1)
        sw1_l.addStretch(1)
        form.addRow(TR("map_visibility"), sw1_row)

        cb_sw2 = QCheckBox(TR("map_sw2"))
        cb_sw2.setChecked(c["switch2_valid"])
        sp_sw2 = QSpinBox()
        sp_sw2.setRange(1, 9999)
        sp_sw2.setValue(c["switch2_id"])
        sw2_row = QWidget()
        sw2_l = QHBoxLayout(sw2_row)
        sw2_l.setContentsMargins(0, 0, 0, 0)
        sw2_l.addWidget(cb_sw2)
        sw2_l.addWidget(sp_sw2)
        sw2_l.addStretch(1)
        form.addRow("", sw2_row)

        lbl_vis = QLabel(maprender.visibility_text(page))
        lbl_vis.setWordWrap(True)
        form.addRow(lbl_vis)

        lay.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)

        if dlg.exec() != QDialog.Accepted:
            return

        ev["name"] = ed_name.text()
        ev["x"] = sp_x.value()
        ev["y"] = sp_y.value()
        if pages:
            c2 = pages[page_combo.currentIndex()].setdefault("conditions", {})
            c2["switch1Valid"] = cb_sw1.isChecked()
            c2["switch1Id"] = sp_sw1.value()
            c2["switch2Valid"] = cb_sw2.isChecked()
            c2["switch2Id"] = sp_sw2.value()
        self._render_canvas()

    # ── live: телепорт / переключатель ──
    def _send_teleport(self, map_id: int, x: int, y: int):
        ch = self.main.channel()
        if not ch:
            QMessageBox.information(self, TR("cheat_no_bridge"),
                                    TR("cheat_no_bridge"))
            return
        ch.send_cheat("teleport", mapId=map_id, x=x, y=y)

    def _toggle_switch_live(self, switch_id: int):
        ch = self.main.channel()
        if ch:
            ch.send_cheat("switch_set", index=switch_id, value=True)

    # ── сохранение ──
    def _save_map(self):
        game_dir = self._game_dir()
        if not game_dir or not self._map_data:
            return
        try:
            path = maprender.save_map(game_dir, self._map_id, self._map_data)
        except OSError as e:
            QMessageBox.critical(self, TR("err"), str(e))
            return
        self._render_canvas()
        QMessageBox.information(self, TR("done"),
                                TR("map_saved", path=os.path.basename(path)))

    # ── текущая карта игрока ──
    def _on_state(self, state):
        if isinstance(state, str):
            try:
                import json
                state = json.loads(state)
            except (json.JSONDecodeError, ValueError):
                return
        if not isinstance(state, dict):
            return
        current = state.get("mapId")
        if current is None:
            return
        self.lbl_player_map.setText(
            TR("map_player_map").format(map_id=current))
        for r in range(self.map_list.count()):
            it = self.map_list.item(r)
            if it.data(Qt.UserRole) == current:
                self.map_list.scrollToItem(it)
                break
