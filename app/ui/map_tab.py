# -*- coding: utf-8 -*-
"""Вкладка «Карты»: интерактивная карта с контекстным меню.

Левая колонка: список карт + текущая карта игрока.
Правая колонка: полная отрисовка карты (тайлсеты) + зум.
Клик по карте: пустой клетка → телепорт; событие → меню редактирования.

Отрисовка тяжёлых слоёв (тайлы+тени) вынесена в фоновый поток —
интерфейс не замирает на больших картах; зум лишь перекомпоновывает
кэшированные слои без повторного рендера.
"""
from __future__ import annotations

import copy
import os

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout,
                                QHBoxLayout, QLabel, QLineEdit, QListWidget,
                                QListWidgetItem, QMenu, QMessageBox,
                                QPushButton, QScrollArea, QSpinBox,
                                QSplitter, QVBoxLayout, QWidget)

from app.core.rpgmaker import crypto, maprender
from app.core.rpgmaker.varnames import extract_maps
from app.ui.i18n import TR
from app.ui.icons import icon
from app.ui.theme import C_BG

ZOOM_LEVELS = [25, 50, 75, 100, 150, 200]

# капы разрешения: базовый слой (тайлы+тени) и итоговая картинка
# не дают QImage раздуться до гигабайтов на больших картах/зуме
MAX_BASE = 4096
MAX_VIEW = 8192

_DIR_ROW = {2: 0, 4: 1, 6: 2, 8: 3}


def _layer_scale(w: int, h: int) -> float:
    return min(1.0, MAX_BASE / max(w, h, 1) / maprender.TILE)


class _LayerPainter:
    """Рисование слоёв карты: работает и в фоновом потоке, и в GUI.

    QPainter на QImage безопасен вне GUI-потока; файловые чтения идут
    через кэшируемый file_view (asar/диск).
    """

    def __init__(self, game_dir: str | None, view, tileset_names: list[str],
                 pages: dict[int, QImage | None],
                 chars: dict[str, QImage | None]):
        self._game_dir = game_dir
        self._view = view
        self._names = tileset_names
        self.pages = pages
        self.chars = chars

    def page_image(self, page: int) -> QImage | None:
        if page in self.pages:
            return self.pages[page]
        if page >= len(self._names) or not self._names[page]:
            self.pages[page] = None
            return None
        raw = crypto.read_image(
            self._game_dir or "", f"img/tilesets/{self._names[page]}",
            view=self._view) if self._game_dir else None
        if not raw:
            self.pages[page] = None
            return None
        img = QImage.fromData(raw, "PNG")
        self.pages[page] = img if not img.isNull() else None
        return self.pages[page]

    def draw_tile(self, painter: QPainter, tile_id: int, dx: int, dy: int,
                  up_wall: bool = False, up_earth: bool = False):
        src = maprender.tile_source(tile_id)
        if not src:
            return
        page, sx, sy = src
        img = self.page_image(page)
        t = maprender.TILE
        if img is None:
            painter.fillRect(dx, dy, t, t, QColor(70, 40, 40, 160))
            return
        if sx + t > img.width() or sy + t > img.height():
            return
        if page in (maprender.PAGE_A4, maprender.PAGE_A3) \
                and sx + 2 * t <= img.width() \
                and sy + 2 * t <= img.height():
            # стены A4 (2x3) и A3 (2x2): левая колонка блока — «бок»
            # (тёмная грань к соседу), правая — фасад. У A4 стены под
            # соседом-стеной рисуются телом без козырька — стены
            # соединяются в сплошную вертикаль.
            if page == maprender.PAGE_A4:
                if up_wall:
                    painter.drawImage(dx, dy, img, sx + t, sy + t, t, t)
                else:
                    cap = 18
                    painter.drawImage(dx, dy, img, sx + t, sy, t, cap)
                    painter.drawImage(dx, dy + cap, img, sx + t, sy + t,
                                      t, t - cap)
            else:
                painter.drawImage(dx, dy, img, sx + t, sy, t, t)
                painter.drawImage(dx, dy + t, img, sx + t, sy + t, t, t)
            return
        if page == maprender.PAGE_A2 \
                and sy + 3 * t <= img.height() \
                and sx + 2 * t <= img.width():
            # земля A2 (2x3): с соседом-землёй сверху — сплошной паттерн
            # (нижний ряд блока), иначе — верхняя грань участка (ряд 0).
            row = 2 * t if up_earth else 0
            painter.drawImage(dx, dy, img, sx, sy + row, t, t)
            return
        painter.drawImage(dx, dy, img, sx, sy, t, t)

    def char_image(self, name: str) -> QImage | None:
        if name in self.chars:
            return self.chars[name]
        raw = crypto.read_image(
            self._game_dir or "", f"img/characters/{name}",
            view=self._view) if self._game_dir else None
        img = QImage.fromData(raw, "PNG") if raw else QImage()
        self.chars[name] = img if not img.isNull() else None
        return self.chars[name]

    def draw_char(self, painter, name, img_ev, ex, ey):
        ch = self.char_image(name)
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
            sy = row * 4 * ch_h + _DIR_ROW.get(
                img_ev.get("direction", 2), 0) * ch_h
        scale = t / cw
        painter.drawImage(
            int(ex), int(ey + t - ch_h * scale), ch,
            int(sx), int(sy), int(cw), int(ch_h))

    def draw_events(self, painter, events: list):
        t = maprender.TILE
        painter.setPen(Qt.NoPen)
        for evd in events:
            if not isinstance(evd, dict):
                continue
            ex, ey = evd.get("x", 0) * t, evd.get("y", 0) * t
            pages = evd.get("pages") or []
            img_ev = (pages[0].get("image") or {}) if pages else {}
            ch_name = img_ev.get("characterName", "")
            if ch_name:
                self.draw_char(painter, ch_name, img_ev, ex, ey)
            elif img_ev.get("tileId"):
                self.draw_tile(painter, img_ev["tileId"], ex, ey)
            else:
                painter.fillRect(ex + 8, ey + 8, t - 16, t - 16,
                                 QColor(220, 160, 40, 110))
            painter.setPen(QColor(255, 200, 60, 180))
            painter.drawRect(ex + 1, ey + 1, t - 2, t - 2)
            painter.setPen(Qt.NoPen)


class _MapRenderThread(QThread):
    """Фоновый рендер слоёв карты (тайлы+тени, маркеры событий)."""

    result_ready = Signal(int, object, object, object, object, bool)
    # (token, base_img, ev_img, pages_cache, chars_cache, base_capped)

    def __init__(self, token, game_dir, view, tileset_names, w, h,
                 ground, overlay, shadow, events, pages, chars):
        super().__init__()
        self._token = token
        self._w, self._h = w, h
        self._ground, self._overlay, self._shadow = ground, overlay, shadow
        self._events = events
        self._lp = _LayerPainter(game_dir, view, tileset_names, pages, chars)

    def run(self):
        t = maprender.TILE
        w, h = self._w, self._h
        scale = _layer_scale(w, h)
        bw, bh = max(1, int(w * t * scale)), max(1, int(h * t * scale))
        img = QImage(bw, bh, QImage.Format_ARGB32)
        img.fill(QColor(24, 24, 24))
        painter = QPainter(img)
        if scale != 1.0:
            painter.scale(scale, scale)
        gl, ol = len(self._ground), len(self._overlay)
        # индексы автотайлов стен/земли — для соединения по соседям
        a4_ids = {i for i, tid in enumerate(self._ground)
                  if maprender.TILE_ID_A4 <= tid < 4352 + 48 * 80}
        a4_ids.update(i for i, tid in enumerate(self._overlay)
                      if maprender.TILE_ID_A4 <= tid < 4352 + 48 * 80)
        a2_ids = {i for i, tid in enumerate(self._ground)
                  if maprender.TILE_ID_A2 <= tid < 3072}
        a2_ids.update(i for i, tid in enumerate(self._overlay)
                      if maprender.TILE_ID_A2 <= tid < 3072)
        for cy in range(h):
            if self.isInterruptionRequested():
                painter.end()
                return
            row = cy * w
            for cx in range(w):
                i = row + cx
                if i < gl:
                    self._lp.draw_tile(painter, self._ground[i], cx * t,
                                       cy * t, up_wall=(i - w) in a4_ids,
                                       up_earth=(i - w) in a2_ids)
                if i < ol:
                    self._lp.draw_tile(painter, self._overlay[i], cx * t,
                                       cy * t, up_wall=(i - w) in a4_ids,
                                       up_earth=(i - w) in a2_ids)
        painter.setPen(Qt.NoPen)
        sl = len(self._shadow)
        if sl:
            half = t // 2
            for cy in range(h):
                if self.isInterruptionRequested():
                    painter.end()
                    return
                for cx in range(w):
                    i = cy * w + cx
                    if i >= sl or not self._shadow[i]:
                        continue
                    v = self._shadow[i]
                    for bit, (qx, qy) in ((1, (0, 0)), (2, (half, 0)),
                                          (4, (0, half)), (8, (half, half))):
                        if v & bit:
                            painter.fillRect(cx * t + qx, cy * t + qy,
                                             half, half, QColor(0, 0, 40, 90))
        painter.end()
        if self.isInterruptionRequested():
            return
        ev = QImage(bw, bh, QImage.Format_ARGB32_Premultiplied)
        ev.fill(Qt.transparent)
        painter = QPainter(ev)
        if scale != 1.0:
            painter.scale(scale, scale)
        self._lp.draw_events(painter, self._events)
        painter.end()
        self.result_ready.emit(self._token, img, ev,
                               self._lp.pages, self._lp.chars,
                               scale != 1.0)


class MapCanvas(QLabel):
    """QLabel с интерактивной картой: левый клик — выбор, правый — меню."""

    def __init__(self, tab):
        super().__init__()
        self._tab = tab
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setStyleSheet(f"background: {C_BG};")
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
        self._tileset_names: list[str] = []
        self._base_img: QImage | None = None
        self._ev_img: QImage | None = None
        self._base_capped: bool = False
        self._loaded_game: str | None = None
        self._render_seq: int = 0
        # живые ссылки на рендер-потоки: пока поток работает, держим
        # wrapper в Python, иначе C++-объект удалится во время run() и Qt
        # упадёт («QThread: Destroyed while thread is still running»)
        self._render_threads: set = set()

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

    def _view(self):
        mod = self.main.engine_module
        p = self.main.project
        if mod and p:
            return mod.file_view(p.game_dir)
        return None

    # ── загрузка ──
    def showEvent(self, event):
        super().showEvent(event)
        self.reload()

    def reload(self):
        game_dir = self._game_dir()
        if game_dir != self._loaded_game:
            # сменился проект — сбрасываем карту и слои предыдущей игры
            self._loaded_game = game_dir
            self._render_seq += 1
            self._map_data = None
            self._base_img = None
            self._ev_img = None
        self._maps = extract_maps(game_dir, self._view()) if game_dir else []
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
        self._map_data = maprender.load_map(game_dir, map_id, self._view()) \
            if game_dir else None
        self._map_id = map_id
        self._pages_img.clear()
        self._char_img.clear()
        # тайлсеты читаем один раз на карту (вкладки страниц кэшируются)
        view = self._view()
        tilesets = maprender.load_tilesets(game_dir, view) if game_dir else []
        tileset = maprender.tileset_for_map(
            tilesets, (self._map_data or {}).get("tilesetId", 1))
        self._tileset_names = list(tileset.get("tilesetNames") or []) \
            if tileset else []
        self._render_canvas()

    def _render_canvas(self):
        """Запускает фоновый рендер слоёв (интерфейс не замирает)."""
        if not self._map_data:
            self.canvas.setText(TR("map_none"))
            self.canvas.setPixmap(QPixmap())
            return
        w, h, ground, overlay, shadow = maprender.map_layers(self._map_data)
        events = copy.deepcopy(self._map_data.get("events") or [])
        self._render_seq += 1
        token = self._render_seq
        self._base_img = None
        self._ev_img = None
        self.canvas.setText(TR("map_rendering"))
        self.canvas.setPixmap(QPixmap())
        th = _MapRenderThread(
            token, self._game_dir(), self._view(),
            list(self._tileset_names), w, h, ground, overlay, shadow,
            events, dict(self._pages_img), dict(self._char_img))
        th.result_ready.connect(self._on_render_done)
        th.finished.connect(lambda: self._on_thread_finished(th))
        self._render_threads.add(th)
        th.start()

    def _on_thread_finished(self, th):
        self._render_threads.discard(th)
        th.deleteLater()

    def cleanup(self):
        """Останавливает фоновые рендер-потоки (вызов при смене проекта/выходе)."""
        for th in list(self._render_threads):
            th.requestInterruption()
        for th in list(self._render_threads):
            if th.isRunning():
                th.wait()   # run() выходит по isInterruptionRequested()
        self._render_threads.clear()

    def _on_render_done(self, token, base, ev, pages, chars, capped):
        if token != self._render_seq or base is None:
            return
        self._pages_img = pages
        self._char_img = chars
        self._base_img = base
        self._ev_img = ev
        self._base_capped = capped
        self._compose()

    def _redraw_events(self):
        """Перерисовывает только слой маркеров событий (дёшево)."""
        if self._map_data is None or self._base_img is None:
            return
        w, h, *_ = maprender.map_layers(self._map_data)
        scale = _layer_scale(w, h)
        bw, bh = self._base_img.width(), self._base_img.height()
        ev = QImage(bw, bh, QImage.Format_ARGB32_Premultiplied)
        ev.fill(Qt.transparent)
        painter = QPainter(ev)
        if scale != 1.0:
            painter.scale(scale, scale)
        lp = _LayerPainter(self._game_dir(), self._view(),
                           self._tileset_names, self._pages_img,
                           self._char_img)
        lp.draw_events(painter, self._map_data.get("events") or [])
        painter.end()
        self._ev_img = ev

    def _compose(self):
        """Собирает итоговую картинку: зум-масштаб двух слоёв + наложение."""
        if self._base_img is None:
            return
        zoom = self.zoom_factor()
        bw, bh = self._base_img.width(), self._base_img.height()
        dw, dh = max(1, int(bw * zoom)), max(1, int(bh * zoom))
        m = max(dw, dh)
        if m > MAX_VIEW:
            s = MAX_VIEW / m
            dw, dh = max(1, int(dw * s)), max(1, int(dh * s))
        # вниз — быстро (сетка тайлов); вверх — сглаживание, но если база
        # уже усечена (большая карта), апскейл без сглаживания
        transform = Qt.SmoothTransformation \
            if (zoom > 1.0 and not self._base_capped) \
            else Qt.FastTransformation
        if (dw, dh) == (bw, bh):
            pm = QPixmap.fromImage(self._base_img)
            if self._ev_img is not None:
                p = QPainter(pm)
                p.drawImage(0, 0, self._ev_img)
                p.end()
        else:
            pm = QPixmap.fromImage(self._base_img).scaled(
                dw, dh, Qt.KeepAspectRatio, transform)
            if self._ev_img is not None:
                evp = QPixmap.fromImage(self._ev_img).scaled(
                    dw, dh, Qt.KeepAspectRatio, transform)
                p = QPainter(pm)
                p.drawPixmap(0, 0, evp)
                p.end()
        self.canvas.setPixmap(pm)
        self.canvas.resize(pm.size())
        w, h, *_ = maprender.map_layers(self._map_data)
        name = self._map_data.get("displayName") or ""
        self.lbl_map_info.setText(
            TR("map_info", id=self._map_id, w=w, h=h, name=name))

    def _refresh_canvas(self):
        # зум — только перекомпоновка кэшированных слоёв (без ре-рендера)
        self._compose()

    # ── контекстное меню по клику на тайле ──
    def show_tile_menu(self, x: int, y: int, global_pos):
        if not self._map_data:
            return
        w, h, *_ = maprender.map_layers(self._map_data)
        if x < 0 or x >= w or y < 0 or y >= h:
            return
        ev = self._event_at(x, y)
        menu = QMenu(self)

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
        # изменились только события — перерисовываем лёгкий слой
        self._redraw_events()
        self._compose()

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
            rel = maprender.save_map(game_dir, self._map_id, self._map_data,
                                     view=self._view())
        except OSError as e:
            QMessageBox.critical(self, TR("err"), str(e))
            return
        self._render_canvas()
        QMessageBox.information(self, TR("done"),
                                TR("map_saved", path=os.path.basename(rel)))

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
