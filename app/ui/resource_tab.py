# -*- coding: utf-8 -*-
"""Вкладка «Ресурсы»: файловый браузер фото, GIF, аудио и видео."""
from __future__ import annotations

import os
import uuid

from PySide6.QtCore import (QBuffer, QByteArray, QEvent, QThread, QTimer,
                            Qt, QUrl, Signal)
from PySide6.QtGui import QImage, QImageReader, QMovie, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QSlider, QSplitter,
                               QStackedWidget, QVBoxLayout, QWidget)

from app import temp_dir
from app.core.media import (ResourceEntry, ResourceKind, classify,
                            export_name, is_encrypted, plain_extension)
from app.core.renpy.rpa import RpaArchive, find_rpa_archives
from app.core.rpgmaker import crypto
from app.ui.i18n import TR
from app.ui.icons import icon
from app.ui.theme import C_BG, C_TEXT_SECONDARY, AnimatedComboBox, AnimatedMenu

TAG_ROLE = Qt.UserRole + 1
STACK_IMAGE = 0
STACK_AUDIO = 1
STACK_VIDEO = 2
SKIP_DIRS = {"__pycache__", "ob_fonts", "ob_fonts_orig"}


def _ms_to_str(ms: int) -> str:
    seconds = max(0, int(ms or 0)) // 1000
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _size_text(size: int) -> str:
    return TR("res_size_kb", size=f"{max(0, int(size or 0)) / 1024:.0f}")


def _entry_icon(kind: ResourceKind):
    if kind == ResourceKind.AUDIO:
        return icon("audio")
    if kind == ResourceKind.VIDEO:
        return icon("video")
    return icon("image")


def _classify_entry(path: str, folder: str = "") -> ResourceKind | None:
    return classify(path, folder)


def _read_entry(entry: ResourceEntry, game_dir: str, view) -> bytes:
    if entry.source == "archive":
        body = RpaArchive(entry.archive).read(entry.path)
    elif os.path.isabs(entry.path):
        with open(entry.path, "rb") as f:
            body = f.read()
    else:
        if view is None:
            raise OSError(TR("res_read_fail"))
        body = view.read_bytes(entry.path)
    if body is None:
        raise OSError(TR("res_read_fail"))
    if is_encrypted(entry.path):
        key = crypto.get_key(game_dir, view=view)
        if not key:
            raise ValueError(TR("res_no_key"))
        body = crypto.decrypt_bytes(body, key)
    if not body:
        raise ValueError(TR("res_empty"))
    return body


def _decode_image(body: bytes) -> QImage:
    buffer = QBuffer()
    buffer.setData(QByteArray(body))
    buffer.open(QBuffer.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > 4096:
        scale = 4096 / max(size.width(), size.height())
        reader.setScaledSize(size.scaled(int(size.width() * scale),
                                         int(size.height() * scale),
                                         Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        raise ValueError(TR("res_decode_fail"))
    return image


def _scan_rpgm(view, folder: str) -> list[ResourceEntry]:
    entries: list[ResourceEntry] = []
    if view is None or not folder:
        return entries
    for rel in view.walk(folder):
        kind = _classify_entry(rel, folder)
        if kind is None:
            continue
        display = rel
        prefix = folder.rstrip("/") + "/"
        if display.startswith(prefix):
            display = display[len(prefix):]
        try:
            size = int(view.size(rel) or 0)
        except (OSError, TypeError, ValueError):
            size = 0
        entries.append(ResourceEntry(kind, rel, display, size))
    return entries


def _scan_renpy(game_dir: str, folder: str, archive: str) -> list[ResourceEntry]:
    entries: list[ResourceEntry] = []
    if archive:
        arch = RpaArchive(archive)
        for name in arch.files:
            kind = _classify_entry(name)
            if kind is None:
                continue
            try:
                size = arch.size(name)
            except (KeyError, OSError):
                size = 0
            entries.append(ResourceEntry(kind, name, name, size,
                                         source="archive", archive=archive))
        return entries
    base = os.path.join(game_dir, folder)
    if not os.path.isdir(base):
        return entries
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, game_dir).replace(os.sep, "/")
            kind = _classify_entry(rel)
            if kind is None:
                continue
            display = os.path.relpath(path, base).replace(os.sep, "/")
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            entries.append(ResourceEntry(kind, path, display, size))
    return entries


class ScanWorker(QThread):
    ready = Signal(object, str)

    def __init__(self, mode: str, game_dir: str, view, folder: str,
                 archive: str = "", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.game_dir = game_dir
        self.view = view
        self.folder = folder
        self.archive = archive

    def run(self):
        try:
            if self.mode == "renpy":
                entries = _scan_renpy(self.game_dir, self.folder, self.archive)
            else:
                entries = _scan_rpgm(self.view, self.folder)
            if not self.isInterruptionRequested():
                self.ready.emit(entries, "")
        except Exception as e:  # noqa: BLE001
            if not self.isInterruptionRequested():
                self.ready.emit([], str(e))


class ReadWorker(QThread):
    ready = Signal(object, str)

    def __init__(self, entry: ResourceEntry, game_dir: str, view, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.game_dir = game_dir
        self.view = view

    def run(self):
        try:
            body = _read_entry(self.entry, self.game_dir, self.view)
            if self.entry.kind == ResourceKind.ANIMATED:
                result = {"kind": "bytes", "data": body}
            elif self.entry.kind == ResourceKind.IMAGE:
                result = {"kind": "image", "image": _decode_image(body)}
            else:
                media_dir = os.path.join(temp_dir(), "media_preview")
                os.makedirs(media_dir, exist_ok=True)
                path = os.path.join(
                    media_dir, f"preview_{uuid.uuid4().hex}"
                    + plain_extension(self.entry.path))
                with open(path, "wb") as f:
                    f.write(body)
                result = {"kind": "path", "path": path, "size": len(body)}
            if not self.isInterruptionRequested():
                self.ready.emit(result, "")
        except Exception as e:  # noqa: BLE001
            if not self.isInterruptionRequested():
                self.ready.emit({}, str(e))


class SaveWorker(QThread):
    ready = Signal(str, str)

    def __init__(self, entry: ResourceEntry, game_dir: str, view,
                 destination: str, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.game_dir = game_dir
        self.view = view
        self.destination = destination

    def run(self):
        try:
            body = _read_entry(self.entry, self.game_dir, self.view)
            with open(self.destination, "wb") as f:
                f.write(body)
            self.ready.emit(self.destination, "")
        except Exception as e:  # noqa: BLE001
            self.ready.emit("", str(e))


class ImageViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._movie: QMovie | None = None
        self._buffer: QBuffer | None = None
        self._zoom = 1.0
        self._save_callback = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.btn_out = QPushButton("−")
        self.btn_fit = QPushButton(TR("res_fit"))
        self.btn_in = QPushButton("+")
        for button in (self.btn_out, self.btn_fit, self.btn_in):
            button.setFixedWidth(46)
            tools.addWidget(button)
        tools.addStretch(1)
        root.addLayout(tools)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(f"background: {C_BG};")
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(200, 200)
        self.label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.label.customContextMenuRequested.connect(self._context_menu)
        self.label.installEventFilter(self)
        self.scroll.setWidget(self.label)
        root.addWidget(self.scroll, 1)
        self.btn_out.clicked.connect(lambda: self._zoom_by(1 / 1.2))
        self.btn_in.clicked.connect(lambda: self._zoom_by(1.2))
        self.btn_fit.clicked.connect(self.fit)

    def _zoom_by(self, factor: float):
        self._zoom = max(0.05, min(20.0, self._zoom * factor))
        self._render()

    def fit(self):
        self._zoom = 1.0
        self._render()

    def set_pixmap(self, pixmap: QPixmap):
        self._stop_movie()
        self._pixmap = pixmap
        self._zoom = 1.0
        self._render()

    def set_gif(self, body: bytes):
        self._stop_movie()
        self._pixmap = None
        self._buffer = QBuffer(self)
        self._buffer.setData(QByteArray(body))
        self._buffer.open(QBuffer.ReadOnly)
        movie = QMovie(self)
        movie.setDevice(self._buffer)
        if not movie.jumpToFrame(0) or movie.currentImage().isNull():
            raise ValueError(TR("res_decode_fail"))
        self._movie = movie
        self._zoom = 1.0
        self.label.setMovie(movie)
        movie.start()
        self._render()

    def _stop_movie(self):
        if self._movie is not None:
            self._movie.stop()
            self.label.setMovie(None)
            self._movie.deleteLater()
            self._movie = None
        if self._buffer is not None:
            self._buffer.close()
            self._buffer.deleteLater()
            self._buffer = None

    def clear(self):
        self._stop_movie()
        self._pixmap = None
        self.label.clear()
        self.label.setText("")

    def _render(self):
        if self._movie is not None:
            size = self._movie.currentImage().size()
            if size.isValid() and self._zoom != 1.0:
                self._movie.setScaledSize(size.scaled(
                    int(size.width() * self._zoom),
                    int(size.height() * self._zoom),
                    Qt.KeepAspectRatio))
            self.label.adjustSize()
            return
        if self._pixmap is None or self._pixmap.isNull():
            self.label.clear()
            return
        size = self._pixmap.size() * self._zoom
        scaled = self._pixmap.scaled(size, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
        self.label.setPixmap(scaled)
        self.label.adjustSize()

    def eventFilter(self, obj, event):
        if obj is self.label and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            self._zoom_by(1.15 if delta > 0 else 1 / 1.15)
            return True
        return super().eventFilter(obj, event)

    def _context_menu(self, pos):
        if self._save_callback is None:
            return
        menu = AnimatedMenu(self)
        action = menu.addAction(TR("res_ctx_save"))
        action.triggered.connect(self._save_callback)
        menu.exec(self.label.mapToGlobal(pos))

    def cleanup(self):
        self._stop_movie()
        self._pixmap = None


class ResourceTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._mode = ""
        self._view = None
        self._game_dir = ""
        self._loaded_signature = None
        self._entries: list[ResourceEntry] = []
        self._current_entry: ResourceEntry | None = None
        self._scan_worker: ScanWorker | None = None
        self._read_worker: ReadWorker | None = None
        self._save_worker: SaveWorker | None = None
        self._workers: set[QThread] = set()
        self._temp_files: set[str] = set()
        self._selection_generation = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        left = QWidget()
        left.setMinimumWidth(280)
        left.setMaximumWidth(440)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        folder_row = QHBoxLayout()
        self.dir_combo = AnimatedComboBox()
        self.dir_combo.currentIndexChanged.connect(self._folder_changed)
        folder_row.addWidget(self.dir_combo, 1)
        self.btn_refresh = QPushButton("")
        self.btn_refresh.setIcon(icon("refresh", 16))
        self.btn_refresh.setToolTip(TR("res_refresh"))
        self.btn_refresh.setFixedWidth(38)
        self.btn_refresh.clicked.connect(lambda: self.reload(force=True))
        folder_row.addWidget(self.btn_refresh)
        left_layout.addLayout(folder_row)

        filter_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(TR("res_search_ph"))
        self.search.textChanged.connect(self._search_changed)
        filter_row.addWidget(self.search, 1)
        self.filter_combo = AnimatedComboBox()
        self.filter_combo.addItem(TR("res_filter_all"), "")
        self.filter_combo.addItem(TR("res_filter_img"), "image")
        self.filter_combo.addItem(TR("res_filter_animated"), "animated")
        self.filter_combo.addItem(TR("res_filter_audio"), "audio")
        self.filter_combo.addItem(TR("res_filter_video"), "video")
        self.filter_combo.setFixedWidth(132)
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_combo)
        left_layout.addLayout(filter_row)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._item_selected)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_menu)
        left_layout.addWidget(self.list, 1)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 11px;")
        left_layout.addWidget(self.count_label)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 6, 6, 6)
        self.lbl_info = QLabel(TR("res_select"))
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; padding: 2px;")
        right_layout.addWidget(self.lbl_info)
        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        self.image_viewer = ImageViewer()
        self.image_viewer._save_callback = self._export_current
        self.stack.addWidget(self.image_viewer)

        self._audio_widget, self._audio_controls = self._build_audio()
        self.stack.addWidget(self._audio_widget)
        self._video_widget, self._video_controls = self._build_video()
        self.stack.addWidget(self._video_widget)
        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._player.positionChanged.connect(self._audio_position)
        self._player.durationChanged.connect(self._audio_duration)
        self._player.playbackStateChanged.connect(self._audio_state)
        self._player.errorOccurred.connect(
            lambda _e, msg: self.lbl_info.setText(
                TR("res_audio_fail") + ": " + msg))
        self._video_player = QMediaPlayer(self)
        self._video_out = QAudioOutput(self)
        self._video_player.setAudioOutput(self._video_out)
        self._video_player.setVideoOutput(self._video_controls["view"])
        self._video_player.positionChanged.connect(self._video_position)
        self._video_player.durationChanged.connect(self._video_duration)
        self._video_player.playbackStateChanged.connect(self._video_state)
        self._video_player.errorOccurred.connect(
            lambda _e, msg: self.lbl_info.setText(
                TR("res_video_fail") + ": " + msg))
        split.addWidget(right)
        split.setSizes([330, 900])
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_filter)
        self._audio_controls["play"].clicked.connect(self._toggle_audio)
        self._audio_controls["stop"].clicked.connect(self._stop_audio)
        self._audio_controls["slider"].sliderMoved.connect(
            self._player.setPosition)
        self._audio_controls["volume"].valueChanged.connect(
            lambda value: self._audio_out.setVolume(value / 100))
        self._video_controls["play"].clicked.connect(self._toggle_video)
        self._video_controls["stop"].clicked.connect(self._stop_video)
        self._video_controls["slider"].sliderMoved.connect(
            self._video_player.setPosition)
        self._video_controls["volume"].valueChanged.connect(
            lambda value: self._video_out.setVolume(value / 100))

    def _build_audio(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        title = QLabel()
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        row = QHBoxLayout()
        play = QPushButton("")
        play.setIcon(icon("play"))
        play.setFixedWidth(50)
        stop = QPushButton("")
        stop.setIcon(icon("stop"))
        stop.setFixedWidth(46)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 0)
        pos = QLabel("0:00")
        dur = QLabel("0:00")
        volume = QSlider(Qt.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(80)
        volume.setFixedWidth(110)
        for widget_item in (play, stop, slider, pos, dur, volume):
            row.addWidget(widget_item)
        slider.setRange(0, 0)
        layout.addLayout(row)
        return widget, {"title": title, "play": play, "stop": stop,
                        "slider": slider, "pos": pos, "dur": dur,
                        "volume": volume}

    def _build_video(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        title = QLabel()
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        view = QVideoWidget()
        view.setMinimumHeight(260)
        view.setStyleSheet("background: #000;")
        layout.addWidget(view, 1)
        row = QHBoxLayout()
        play = QPushButton("")
        play.setIcon(icon("play"))
        play.setFixedWidth(50)
        stop = QPushButton("")
        stop.setIcon(icon("stop"))
        stop.setFixedWidth(46)
        slider = QSlider(Qt.Horizontal)
        pos = QLabel("0:00")
        dur = QLabel("0:00")
        volume = QSlider(Qt.Horizontal)
        volume.setRange(0, 100)
        volume.setValue(80)
        volume.setFixedWidth(110)
        for widget_item in (play, stop, slider, pos, dur, volume):
            row.addWidget(widget_item)
        layout.addLayout(row)
        return widget, {"title": title, "view": view, "play": play,
                        "stop": stop, "slider": slider, "pos": pos,
                        "dur": dur, "volume": volume}

    def _track_worker(self, worker):
        self._workers.add(worker)
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        worker.finished.connect(worker.deleteLater)

    def _game_dir_value(self) -> str:
        return self.main.project.game_dir if self.main.project else ""

    def _engine_module(self):
        return self.main.engine_module

    def _stop_media(self):
        self._player.stop()
        self._player.setSource(QUrl())
        self._video_player.stop()
        self._video_player.setSource(QUrl())
        self.image_viewer.cleanup()
        for path in list(self._temp_files):
            try:
                os.remove(path)
            except OSError:
                pass
        self._temp_files.clear()

    def cleanup(self):
        self._selection_generation += 1
        self._stop_media()
        for worker in list(self._workers):
            try:
                worker.requestInterruption()
                worker.wait(500)
            except RuntimeError:
                pass
        self._workers.clear()

    def on_project_opened(self):
        self.reload(force=True)

    def showEvent(self, event):
        super().showEvent(event)
        if self._loaded_signature is None:
            self.reload()

    def reload(self, force: bool = False):
        game_dir = self._game_dir_value()
        module = self._engine_module()
        mode = module.key if module else ""
        signature = (game_dir, mode)
        if not force and signature == self._loaded_signature:
            return
        self._loaded_signature = signature
        self._selection_generation += 1
        self._stop_media()
        self.list.clear()
        self._entries = []
        self._current_entry = None
        self._game_dir = game_dir
        self._mode = mode
        self._view = module.file_view(game_dir) if module and game_dir else None
        self.dir_combo.blockSignals(True)
        self.dir_combo.clear()
        if mode == "renpy":
            self._fill_renpy_dirs(game_dir)
        elif mode and game_dir:
            self._fill_rpgm_dirs(self._view)
        self.dir_combo.blockSignals(False)
        if self.dir_combo.count():
            self.dir_combo.setCurrentIndex(0)
            self._start_scan()
        else:
            self.lbl_info.setText(TR("res_select"))

    def _fill_rpgm_dirs(self, view):
        if view is None:
            return
        for root in ("", "www"):
            for base in ("img", "audio", "movies"):
                rel = f"{root}/{base}" if root else base
                if not view.is_dir(rel):
                    continue
                label = ("www/" if root else "") + base
                self.dir_combo.addItem(label, ("view", rel))
                for name in view.list_dir(rel):
                    child = f"{rel}/{name}"
                    if view.is_dir(child):
                        self.dir_combo.addItem(label + "/" + name,
                                               ("view", child))

    def _fill_renpy_dirs(self, game_dir: str):
        if not os.path.isdir(os.path.join(game_dir, "game")):
            return
        self.dir_combo.addItem("game/", ("view", "game"))
        for archive in find_rpa_archives(game_dir):
            rel = os.path.relpath(archive, game_dir).replace(os.sep, "/")
            self.dir_combo.addItem(rel, ("archive", archive))

    def _folder_changed(self, *_):
        self._start_scan()

    def _start_scan(self):
        if not self._game_dir:
            return
        data = self.dir_combo.currentData()
        if not data:
            return
        source, value = data
        archive = value if source == "archive" else ""
        folder = value if source == "view" else "game"
        self._selection_generation += 1
        self._stop_media()
        self.list.clear()
        self._entries = []
        worker = ScanWorker(self._mode, self._game_dir, self._view,
                            folder, archive, self)
        worker.ready.connect(lambda entries, error, w=worker:
                             self._scan_ready(entries, error, w))
        self._track_worker(worker)
        self._scan_worker = worker
        self.lbl_info.setText(TR("res_loading"))
        worker.start()

    def _scan_ready(self, entries, error, worker):
        if worker is not self._scan_worker:
            return
        self._scan_worker = None
        if error:
            self.lbl_info.setText(TR("res_scan_fail") + ": " + error)
            return
        self._entries = entries
        self._apply_filter()

    def _search_changed(self, *_):
        self._search_timer.start(180)

    def _apply_filter(self, *_):
        query = self.search.text().strip().lower()
        wanted = self.filter_combo.currentData() or ""
        self.list.clear()
        for entry in self._entries:
            if wanted and entry.tag != wanted:
                continue
            if query and query not in entry.display.lower():
                continue
            item = QListWidgetItem(entry.display)
            item.setIcon(_entry_icon(entry.kind))
            item.setData(Qt.UserRole, entry)
            item.setToolTip(f"{entry.display}\n{_size_text(entry.size)}")
            self.list.addItem(item)
        self.count_label.setText(
            TR("res_found", count=self.list.count(),
               total=len(self._entries)))

    def _item_selected(self, item, _previous):
        if item is None:
            self._current_entry = None
            self._stop_media()
            return
        entry = item.data(Qt.UserRole)
        if not isinstance(entry, ResourceEntry):
            return
        self._current_entry = entry
        self._selection_generation += 1
        generation = self._selection_generation
        self._stop_media()
        self.lbl_info.setText(f"{entry.display} — {TR('res_loading')}")
        worker = ReadWorker(entry, self._game_dir, self._view, self)
        worker.ready.connect(lambda result, error, w=worker:
                             self._read_ready(result, error, entry, generation,
                                              w))
        self._track_worker(worker)
        self._read_worker = worker
        worker.start()

    def _read_ready(self, result, error, entry, generation, worker):
        if worker is not self._read_worker or generation != self._selection_generation:
            return
        self._read_worker = None
        if error:
            self.lbl_info.setText(error)
            return
        if result.get("kind") == "image":
            pixmap = QPixmap.fromImage(result["image"])
            self.image_viewer.set_pixmap(pixmap)
            self.stack.setCurrentIndex(STACK_IMAGE)
            self.lbl_info.setText(
                f"{entry.display} — {pixmap.width()}×{pixmap.height()}, "
                f"{_size_text(entry.size)}")
        elif result.get("kind") == "bytes":
            try:
                self.image_viewer.set_gif(result["data"])
            except Exception as e:  # noqa: BLE001
                self.lbl_info.setText(str(e))
                return
            self.stack.setCurrentIndex(STACK_IMAGE)
            self.lbl_info.setText(f"{entry.display} — GIF, "
                                  f"{_size_text(entry.size)}")
        elif result.get("kind") == "path":
            path = result["path"]
            self._temp_files.add(path)
            source_url = QUrl.fromLocalFile(path)
            if entry.kind == ResourceKind.AUDIO:
                self._show_audio(entry, source_url)
            else:
                self._show_video(entry, source_url)
            self.lbl_info.setText(
                f"{entry.display} — {_size_text(entry.size)}")

    def _show_audio(self, entry, url):
        controls = self._audio_controls
        controls["title"].setText(entry.display)
        controls["slider"].setRange(0, 0)
        controls["pos"].setText("0:00")
        controls["dur"].setText("0:00")
        controls["play"].setIcon(icon("play"))
        self._player.setSource(url)
        self._audio_out.setVolume(controls["volume"].value() / 100)
        self.stack.setCurrentIndex(STACK_AUDIO)

    def _show_video(self, entry, url):
        controls = self._video_controls
        controls["title"].setText(entry.display)
        controls["slider"].setRange(0, 0)
        controls["pos"].setText("0:00")
        controls["dur"].setText("0:00")
        controls["play"].setIcon(icon("play"))
        self._video_player.setSource(url)
        self._video_out.setVolume(controls["volume"].value() / 100)
        self.stack.setCurrentIndex(STACK_VIDEO)
        self._video_player.play()

    def _toggle_audio(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _toggle_video(self):
        if self._video_player.playbackState() == QMediaPlayer.PlayingState:
            self._video_player.pause()
        else:
            self._video_player.play()

    def _stop_audio(self):
        self._player.stop()
        self._audio_controls["play"].setIcon(icon("play"))

    def _stop_video(self):
        self._video_player.stop()
        self._video_controls["play"].setIcon(icon("play"))

    def _audio_position(self, value):
        controls = self._audio_controls
        if not controls["slider"].isSliderDown():
            controls["slider"].setValue(value)
        controls["pos"].setText(_ms_to_str(value))

    def _audio_duration(self, value):
        self._audio_controls["slider"].setRange(0, value)
        self._audio_controls["dur"].setText(_ms_to_str(value))

    def _audio_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self._audio_controls["play"].setIcon(icon("pause"))
        else:
            self._audio_controls["play"].setIcon(icon("play"))

    def _video_position(self, value):
        controls = self._video_controls
        if not controls["slider"].isSliderDown():
            controls["slider"].setValue(value)
        controls["pos"].setText(_ms_to_str(value))

    def _video_duration(self, value):
        self._video_controls["slider"].setRange(0, value)
        self._video_controls["dur"].setText(_ms_to_str(value))

    def _video_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self._video_controls["play"].setIcon(icon("pause"))
        else:
            self._video_controls["play"].setIcon(icon("play"))

    def _list_menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None:
            return
        entry = item.data(Qt.UserRole)
        if not isinstance(entry, ResourceEntry):
            return
        menu = AnimatedMenu(self)
        action = menu.addAction(TR("res_ctx_save_resource"))
        action.triggered.connect(lambda: self._export_entry(entry))
        menu.exec(self.list.mapToGlobal(pos))

    def _export_current(self):
        if self._current_entry is not None:
            self._export_entry(self._current_entry)

    def _export_entry(self, entry: ResourceEntry):
        if entry.kind == ResourceKind.IMAGE:
            filt = "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All (*)"
        elif entry.kind == ResourceKind.ANIMATED:
            filt = "GIF (*.gif);;All (*)"
        elif entry.kind == ResourceKind.AUDIO:
            filt = "Audio (*.ogg *.mp3 *.wav *.m4a *.flac);;All (*)"
        else:
            filt = "Video (*.webm *.mp4 *.avi *.mov);;All (*)"
        path, _ = QFileDialog.getSaveFileName(
            self, TR("res_ctx_save_resource"), export_name(entry.display), filt)
        if not path:
            return
        worker = SaveWorker(entry, self._game_dir, self._view, path, self)
        worker.ready.connect(self._save_ready)
        self._track_worker(worker)
        self._save_worker = worker
        worker.start()

    def _save_ready(self, path, error):
        if error:
            QMessageBox.warning(self, TR("err"), error)
        else:
            self.lbl_info.setText(TR("res_saved", path=path))
