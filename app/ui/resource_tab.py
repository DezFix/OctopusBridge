# -*- coding: utf-8 -*-
"""Вкладка «Ресурсы»: просмотр картинок, аудио и видео игры.

RPG Maker MV/MZ: папки img/ (+ audio/, movies/), превью с расшифровкой
.png_/.rpgmvp/.ogg_/.rpgmvo/.m4a_/.rpgmvm/.webm_ на лету,
кнопка установки кириллического шрифта.
Колёсико мыши — зум, зажатая ЛКМ — перемещение, ПКМ — сохранить.
Ren'Py: изображения, аудио и видео из game/ и из .rpa-архивов.
"""
from __future__ import annotations

import os
import tempfile
import uuid

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap, QImage, QMouseEvent, QWheelEvent
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSlider, QSplitter, QVBoxLayout, QWidget, QMenu,
)

from app.ui.i18n import TR
from app.ui.icons import icon

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
RPGM_ENC_IMG = (".png_", ".rpgmvp")
AUDIO_EXTS = (".ogg", ".m4a", ".wav", ".mp3")
RPGM_ENC_AUDIO = (".ogg_", ".m4a_", ".rpgmvo", ".rpgmvm")
VIDEO_EXTS = (".webm", ".mp4", ".m4v", ".avi")
RPGM_ENC_VIDEO = (".webm_", ".mp4_")
# теги типов — на элементах списка (Qt.UserRole + 1) для сортировки/фильтра
TAG_IMAGE = "image"
TAG_AUDIO = "audio"
TAG_VIDEO = "video"
TAG_ROLE = Qt.UserRole + 1
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".octopusbridge", "audio_cache")


def _find_ffmpeg() -> str | None:
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    for c in (r"C:\ffmpeg\bin\ffmpeg.exe",
              r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
              os.path.join(os.path.expanduser("~"), "ffmpeg", "bin", "ffmpeg.exe")):
        if os.path.isfile(c):
            return c
    return None


_FFMPEG = _find_ffmpeg()


def _to_wav(src_path: str) -> str | None:
    """Convert audio → WAV via ffmpeg subprocess."""
    if not _FFMPEG:
        return None
    os.makedirs(_CACHE_DIR, exist_ok=True)
    wav_path = os.path.join(_CACHE_DIR, f"_conv_{uuid.uuid4().hex[:12]}.wav")
    try:
        import subprocess
        r = subprocess.run(
            [_FFMPEG, "-y", "-i", src_path, "-vn",
             "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", wav_path],
            capture_output=True, timeout=30,
        )
        if r.returncode == 0 and os.path.isfile(wav_path):
            return wav_path
        try:
            os.remove(wav_path)
        except OSError:
            pass
    except Exception:
        pass
    return None


def _to_mp4(src_path: str) -> str | None:
    """Конвертация видео → H.264 MP4 через ffmpeg (надёжно играет везде)."""
    if not _FFMPEG:
        return None
    os.makedirs(_CACHE_DIR, exist_ok=True)
    mp4_path = os.path.join(_CACHE_DIR, f"_video_{uuid.uuid4().hex[:12]}.mp4")
    try:
        import subprocess
        r = subprocess.run(
            [_FFMPEG, "-y", "-i", src_path, "-c:v", "libx264",
             "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-movflags", "+faststart", mp4_path],
            capture_output=True, timeout=180,
        )
        if r.returncode == 0 and os.path.isfile(mp4_path):
            return mp4_path
        try:
            os.remove(mp4_path)
        except OSError:
            pass
    except Exception:
        pass
    return None


class ImageZoomLabel(QLabel):
    """QLabel с зумом колёсиком и перемещением зажатой ЛКМ."""

    def __init__(self):
        super().__init__()
        self._zoom = 1.0
        self._pixmap: QPixmap | None = None
        self._dragging = False
        self._drag_start = None
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_ctx_menu)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(200, 200)
        self._save_callback = None

    def setPixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._zoom = 1.0
        self._render()

    def _render(self):
        if self._pixmap is None or self._pixmap.isNull():
            super().setPixmap(QPixmap())
            self.adjustSize()
            return
        w = int(self._pixmap.width() * self._zoom)
        h = int(self._pixmap.height() * self._zoom)
        scaled = self._pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        super().setPixmap(scaled)
        self.adjustSize()

    def wheelEvent(self, event: QWheelEvent):
        if self._pixmap is None or self._pixmap.isNull():
            return
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom = max(0.05, min(self._zoom * factor, 20.0))
        self._render()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._pixmap:
            self._dragging = True
            self._drag_start = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and self._drag_start is not None:
            dx = event.position().toPoint().x() - self._drag_start.x()
            dy = event.position().toPoint().y() - self._drag_start.y()
            p = self.parent()
            if p and hasattr(p, "horizontalScrollBar"):
                p.horizontalScrollBar().setValue(p.horizontalScrollBar().value() - dx)
                p.verticalScrollBar().setValue(p.verticalScrollBar().value() - dy)
            self._drag_start = event.position().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self._drag_start = None
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _show_ctx_menu(self, pos):
        if self._pixmap is None or self._pixmap.isNull():
            return
        menu = QMenu(self)
        act = menu.addAction(TR("res_ctx_save"))
        act.triggered.connect(self._do_save)
        menu.exec(self.mapToGlobal(pos))

    def _do_save(self):
        if self._save_callback:
            self._save_callback()


def _raw_to_wav(raw_bytes: bytes, src_path: str) -> str | None:
    """Write raw bytes to temp file, then convert to WAV via ffmpeg."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    ext = ".ogg"
    low = src_path.lower()
    for e in (".ogg", ".m4a", ".wav", ".mp3"):
        if low.endswith(e) or low.endswith(e + "_"):
            ext = e
            break
    tmp = os.path.join(_CACHE_DIR, f"_raw_{uuid.uuid4().hex[:12]}{ext}")
    with open(tmp, "wb") as f:
        f.write(raw_bytes)
    wav = _to_wav(tmp)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return wav


class ResourceTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self._mode = ""
        self._archives: dict[str, object] = {}
        self._in_archive = False
        self._current_item_data = None
        self._current_item_name = ""

        # audio player (QMediaPlayer — native Qt)
        self._player = QMediaPlayer()
        self._audio_out = QAudioOutput()
        self._player.setAudioOutput(self._audio_out)
        self._audio_out.setVolume(1.0)
        self._player.positionChanged.connect(self._on_pos)
        self._player.durationChanged.connect(self._on_dur)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.errorOccurred.connect(self._on_error)
        self._current_wav: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # ── left panel ──
        left = QWidget()
        left.setMinimumWidth(280)
        left.setMaximumWidth(420)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 6, 6)

        top = QHBoxLayout()
        self.dir_combo = QComboBox()
        self.dir_combo.currentTextChanged.connect(self._fill_list)
        top.addWidget(self.dir_combo, 1)
        self.btn_back = QPushButton("")
        self.btn_back.setIcon(icon("arrow-left"))
        self.btn_back.setFixedWidth(34)
        self.btn_back.setToolTip(TR("res_back"))
        self.btn_back.clicked.connect(self._go_back)
        self.btn_back.setVisible(False)
        top.addWidget(self.btn_back)
        ll.addLayout(top)

        self.search = QLineEdit()
        self.search.setPlaceholderText(TR("res_search_ph"))
        self.search.textChanged.connect(self._fill_list)
        row2 = QHBoxLayout()
        row2.addWidget(self.search, 1)
        self.filter_combo = QComboBox()
        self.filter_combo.addItem(TR("res_filter_all"), "")
        self.filter_combo.addItem(TR("res_filter_img"), TAG_IMAGE)
        self.filter_combo.addItem(TR("res_filter_audio"), TAG_AUDIO)
        self.filter_combo.addItem(TR("res_filter_video"), TAG_VIDEO)
        self.filter_combo.setFixedWidth(118)
        self.filter_combo.currentIndexChanged.connect(self._fill_list)
        row2.addWidget(self.filter_combo)
        ll.addLayout(row2)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_item_selected)
        self.list.itemActivated.connect(self._open_item)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._list_ctx_menu)
        ll.addWidget(self.list, 1)

        self.btn_font = QPushButton(TR("res_font"))
        self.btn_font.clicked.connect(self._patch_font)
        ll.addWidget(self.btn_font)
        split.addWidget(left)

        # ── right panel ──
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)

        self.lbl_info = QLabel(TR("res_select"))
        self.lbl_info.setStyleSheet("color: #999; padding: 2px;")
        rl.addWidget(self.lbl_info)

        # image area
        self.image_label = ImageZoomLabel()
        self.image_label._save_callback = self._save_current_image
        self.image_label.setStyleSheet("background: #1a1a1a;")
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidget(self.image_label)
        self.image_scroll.setWidgetResizable(True)
        rl.addWidget(self.image_scroll, 1)

        # audio player area
        self._audio_widget = QWidget()
        aw = QVBoxLayout(self._audio_widget)
        aw.setContentsMargins(0, 0, 0, 0)
        self.audio_title = QLabel()
        self.audio_title.setStyleSheet("color: #ccc; padding: 2px; font-weight: bold;")
        aw.addWidget(self.audio_title)
        row = QHBoxLayout()
        self.btn_play = QPushButton("")
        self.btn_play.setIcon(icon("play"))
        self.btn_play.setFixedWidth(50)
        self.btn_play.clicked.connect(self._toggle_play)
        row.addWidget(self.btn_play)
        self.btn_stop = QPushButton("")
        self.btn_stop.setIcon(icon("stop"))
        self.btn_stop.setFixedWidth(46)
        self.btn_stop.clicked.connect(self._stop_audio)
        row.addWidget(self.btn_stop)
        self.audio_slider = QSlider(Qt.Horizontal)
        self.audio_slider.setRange(0, 0)
        self.audio_slider.sliderMoved.connect(self._seek)
        row.addWidget(self.audio_slider, 1)
        self.lbl_pos = QLabel("0:00")
        self.lbl_pos.setFixedWidth(50)
        row.addWidget(self.lbl_pos)
        self.lbl_dur = QLabel("0:00")
        self.lbl_dur.setFixedWidth(50)
        row.addWidget(self.lbl_dur)
        self.btn_download = QPushButton("")
        self.btn_download.setIcon(icon("download"))
        self.btn_download.setFixedWidth(46)
        self.btn_download.setToolTip(TR("res_ctx_save_audio"))
        self.btn_download.clicked.connect(self._download_current_audio)
        row.addWidget(self.btn_download)
        aw.addLayout(row)
        rl.addWidget(self._audio_widget)
        self._audio_widget.setVisible(False)

        # video player area
        self._video_widget = QWidget()
        vw = QVBoxLayout(self._video_widget)
        vw.setContentsMargins(0, 0, 0, 0)
        self.video_title = QLabel()
        self.video_title.setStyleSheet("color: #ccc; padding: 2px; font-weight: bold;")
        vw.addWidget(self.video_title)
        self.video_view = QVideoWidget()
        self.video_view.setMinimumHeight(220)
        self.video_view.setStyleSheet("background: #000;")
        vw.addWidget(self.video_view, 1)
        vrow = QHBoxLayout()
        self.btn_video_play = QPushButton("")
        self.btn_video_play.setIcon(icon("play"))
        self.btn_video_play.setFixedWidth(50)
        self.btn_video_play.clicked.connect(self._toggle_video_play)
        vrow.addWidget(self.btn_video_play)
        self.btn_video_stop = QPushButton("")
        self.btn_video_stop.setIcon(icon("stop"))
        self.btn_video_stop.setFixedWidth(46)
        self.btn_video_stop.clicked.connect(self._stop_video)
        vrow.addWidget(self.btn_video_stop)
        self.video_slider = QSlider(Qt.Horizontal)
        self.video_slider.setRange(0, 0)
        self.video_slider.sliderMoved.connect(self._seek_video)
        vrow.addWidget(self.video_slider, 1)
        self.lbl_video_pos = QLabel("0:00")
        self.lbl_video_pos.setFixedWidth(50)
        vrow.addWidget(self.lbl_video_pos)
        self.lbl_video_dur = QLabel("0:00")
        self.lbl_video_dur.setFixedWidth(50)
        vrow.addWidget(self.lbl_video_dur)
        self.btn_video_download = QPushButton("")
        self.btn_video_download.setIcon(icon("download"))
        self.btn_video_download.setFixedWidth(46)
        self.btn_video_download.setToolTip(TR("res_ctx_save_video"))
        self.btn_video_download.clicked.connect(self._download_current_video)
        vrow.addWidget(self.btn_video_download)
        vw.addLayout(vrow)
        rl.addWidget(self._video_widget, 1)
        self._video_widget.setVisible(False)

        # video player (separate instance — own video output)
        self._video_player = QMediaPlayer()
        self._video_player.setVideoOutput(self.video_view)
        self._video_player.positionChanged.connect(self._on_video_pos)
        self._video_player.durationChanged.connect(self._on_video_dur)
        self._video_player.playbackStateChanged.connect(self._on_video_state)
        self._video_player.errorOccurred.connect(self._on_video_error)
        self._current_video: str | None = None
        self._video_tmp_files: list[str] = []

        split.addWidget(right)
        split.setSizes([320, 760])

    def _game_dir(self) -> str | None:
        p = self.main.project
        return p.game_dir if p else None

    # ── helpers: тег типа + иконка (основа для сортировки) ──
    @staticmethod
    def _mk_item(text: str, tag: str) -> QListWidgetItem:
        it = QListWidgetItem(text)
        if tag == TAG_IMAGE:
            it.setIcon(icon("image"))
        elif tag == TAG_AUDIO:
            it.setIcon(icon("audio"))
        elif tag == TAG_VIDEO:
            it.setIcon(icon("video"))
        it.setData(TAG_ROLE, tag)
        return it

    def _filter_tag(self) -> str:
        return self.filter_combo.currentData() or ""

    def _tag_ok(self, tag: str) -> bool:
        ft = self._filter_tag()
        return not ft or ft == tag

    def showEvent(self, event):
        super().showEvent(event)
        self.reload()

    def reload(self):
        self._stop_audio()
        self._stop_video()
        game_dir = self._game_dir()
        mod = self.main.engine_module
        self._mode = mod.key if mod else ""
        self._archives.clear()
        self._in_archive = False
        self.btn_back.setVisible(False)
        self.btn_font.setVisible(
            bool(mod and "font" in mod.features)
            and os.path.isdir(os.path.join(game_dir or "", "img")))
        self.dir_combo.blockSignals(True)
        self.dir_combo.clear()
        if not game_dir:
            self.dir_combo.blockSignals(False)
            return
        if self._mode == "renpy":
            self._fill_dirs_renpy(game_dir)
        else:
            self._fill_dirs_rpgm(game_dir)
        self.dir_combo.blockSignals(False)
        self._fill_list()

    # ── RPG Maker dirs ──
    def _fill_dirs_rpgm(self, game_dir: str):
        roots = [game_dir]
        if os.path.isdir(os.path.join(game_dir, "www")):
            roots.append(os.path.join(game_dir, "www"))
        for root in roots:
            for base, prefix in (("img", "img"), ("audio", "audio"),
                                 ("movies", "movies")):
                base_path = os.path.join(root, base)
                if not os.path.isdir(base_path):
                    continue
                for d in sorted(os.listdir(base_path)):
                    if os.path.isdir(os.path.join(base_path, d)):
                        label = f"{prefix}/{d}"
                        if root.endswith("www"):
                            label = "www/" + label
                        self.dir_combo.addItem(label)

    def _rpgm_folder(self, game_dir: str) -> str:
        rel = self.dir_combo.currentText()
        return os.path.join(game_dir, *rel.split("/"))

    # ── Ren'Py dirs ──
    def _fill_dirs_renpy(self, game_dir: str):
        game_sub = os.path.join(game_dir, "game")
        if not os.path.isdir(game_sub):
            return
        self.dir_combo.addItem("game/")
        from app.core.renpy.rpa import find_rpa_archives
        for arch in find_rpa_archives(game_dir):
            rel = os.path.relpath(arch, game_dir).replace(os.sep, "/")
            self.dir_combo.addItem(icon("folder"), rel)

    def _fill_list(self):
        self.list.clear()
        self._in_archive = False
        self.btn_back.setVisible(False)
        self._stop_audio()
        self._current_item_data = None
        self._current_item_name = ""
        game_dir = self._game_dir()
        if not game_dir:
            return
        q = self.search.text().strip().lower()
        current = self.dir_combo.currentText()
        if self._mode == "renpy":
            self._fill_list_renpy(game_dir, current, q)
        else:
            self._fill_list_rpgm(game_dir, q)

    def _fill_list_rpgm(self, game_dir: str, q: str):
        folder = self._rpgm_folder(game_dir)
        if not os.path.isdir(folder):
            return
        for root, dirs, files in os.walk(folder):
            dirs[:] = sorted(dirs)
            for f in sorted(files):
                low = f.lower()
                rel = os.path.relpath(os.path.join(root, f), folder)
                if low.endswith(IMG_EXTS + RPGM_ENC_IMG):
                    if q and q not in low and q not in rel.lower():
                        continue
                    if not self._tag_ok(TAG_IMAGE):
                        continue
                    it = self._mk_item(rel.replace(os.sep, "/"), TAG_IMAGE)
                    it.setData(Qt.UserRole, ("img", os.path.join(root, f)))
                    self.list.addItem(it)
                elif low.endswith(AUDIO_EXTS + RPGM_ENC_AUDIO):
                    if q and q not in low and q not in rel.lower():
                        continue
                    if not self._tag_ok(TAG_AUDIO):
                        continue
                    it = self._mk_item(rel.replace(os.sep, "/"), TAG_AUDIO)
                    it.setData(Qt.UserRole, ("audio", os.path.join(root, f)))
                    self.list.addItem(it)
                elif low.endswith(VIDEO_EXTS + RPGM_ENC_VIDEO):
                    if q and q not in low and q not in rel.lower():
                        continue
                    if not self._tag_ok(TAG_VIDEO):
                        continue
                    it = self._mk_item(rel.replace(os.sep, "/"), TAG_VIDEO)
                    it.setData(Qt.UserRole, ("video", os.path.join(root, f)))
                    self.list.addItem(it)

    def _fill_list_renpy(self, game_dir: str, current: str, q: str):
        if self.dir_combo.currentIndex() > 0:
            arch_path = os.path.join(game_dir, *current.split("/"))
            try:
                from app.core.renpy.rpa import RpaArchive
                arch = self._archives.get(arch_path)
                if arch is None:
                    arch = RpaArchive(arch_path)
                    self._archives[arch_path] = arch
            except Exception as e:
                QMessageBox.warning(self, TR("err"), str(e))
                return
            self._in_archive = True
            self.btn_back.setVisible(True)
            for name in arch.files:
                low = name.lower()
                if low.endswith(IMG_EXTS):
                    if q and q not in low:
                        continue
                    if not self._tag_ok(TAG_IMAGE):
                        continue
                    it = self._mk_item(name, TAG_IMAGE)
                    it.setData(Qt.UserRole, ("archive_img", (arch_path, name)))
                    self.list.addItem(it)
                elif low.endswith(AUDIO_EXTS):
                    if q and q not in low:
                        continue
                    if not self._tag_ok(TAG_AUDIO):
                        continue
                    it = self._mk_item(name, TAG_AUDIO)
                    it.setData(Qt.UserRole, ("archive_audio", (arch_path, name)))
                    self.list.addItem(it)
                elif low.endswith(VIDEO_EXTS):
                    if q and q not in low:
                        continue
                    if not self._tag_ok(TAG_VIDEO):
                        continue
                    it = self._mk_item(name, TAG_VIDEO)
                    it.setData(Qt.UserRole, ("archive_video", (arch_path, name)))
                    self.list.addItem(it)
            return
        game_sub = os.path.join(game_dir, "game")
        for root, dirs, files in os.walk(game_sub):
            dirs[:] = [d for d in dirs
                       if d not in ("tl", "__pycache__", "ob_fonts",
                                    "ob_fonts_orig")]
            for f in sorted(files):
                low = f.lower()
                rel = os.path.relpath(os.path.join(root, f),
                                      game_dir).replace(os.sep, "/")
                if low.endswith(IMG_EXTS):
                    if q and q not in rel.lower():
                        continue
                    if not self._tag_ok(TAG_IMAGE):
                        continue
                    it = self._mk_item(rel, TAG_IMAGE)
                    it.setData(Qt.UserRole, ("img", os.path.join(root, f)))
                    self.list.addItem(it)
                elif low.endswith(AUDIO_EXTS):
                    if q and q not in rel.lower():
                        continue
                    if not self._tag_ok(TAG_AUDIO):
                        continue
                    it = self._mk_item(rel, TAG_AUDIO)
                    it.setData(Qt.UserRole, ("audio", os.path.join(root, f)))
                    self.list.addItem(it)
                elif low.endswith(VIDEO_EXTS):
                    if q and q not in rel.lower():
                        continue
                    if not self._tag_ok(TAG_VIDEO):
                        continue
                    it = self._mk_item(rel, TAG_VIDEO)
                    it.setData(Qt.UserRole, ("video", os.path.join(root, f)))
                    self.list.addItem(it)

    # ── actions ──
    def _go_back(self):
        self._in_archive = False
        self.btn_back.setVisible(False)
        idx = self.dir_combo.findText("game/")
        if idx >= 0:
            self.dir_combo.setCurrentIndex(idx)

    def _open_item(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if data and data[0] == "archive_img":
            self._on_item_selected(item, None)

    def _on_item_selected(self, item, _prev):
        if not item:
            return
        data = item.data(Qt.UserRole)
        if data is None:
            return
        self._current_item_data = data
        self._current_item_name = item.text()
        self._stop_audio()
        self._stop_video()
        if data[0] in ("img", "archive_img"):
            self._show_image(data)
        elif data[0] in ("audio", "archive_audio"):
            self._show_audio_info(data)
        elif data[0] in ("video", "archive_video"):
            self._show_video(data)

    # ── byte readers ──
    def _read_image_bytes(self, data) -> bytes | None:
        kind, payload = data
        if kind == "archive_img":
            arch = self._archives.get(payload[0])
            return arch.read(payload[1]) if arch else None
        with open(payload, "rb") as f:
            body = f.read()
        if payload.lower().endswith(RPGM_ENC_IMG):
            from app.core.rpgmaker import crypto
            key = crypto.get_key(self._game_dir() or "")
            if not key:
                raise ValueError(TR("res_no_key"))
            return crypto.decrypt_bytes(body, key)
        return body

    def _read_audio_bytes(self, data) -> bytes | None:
        kind, payload = data
        if kind == "archive_audio":
            arch = self._archives.get(payload[0])
            return arch.read(payload[1]) if arch else None
        if kind == "archive_img":
            return None
        with open(payload, "rb") as f:
            body = f.read()
        if payload.lower().endswith(RPGM_ENC_AUDIO):
            from app.core.rpgmaker import crypto
            key = crypto.get_key(self._game_dir() or "")
            if key:
                try:
                    return crypto.decrypt_bytes(body, key)
                except (ValueError, IndexError):
                    pass
        return body

    def _get_audio_ext(self, path: str) -> str:
        if isinstance(path, tuple):
            path = path[1]
        low = path.lower()
        for ext in (".ogg", ".m4a", ".wav", ".mp3"):
            if low.endswith(ext) or low.endswith(ext + "_"):
                return ext
        return ".ogg"

    def _read_video_bytes(self, data) -> bytes | None:
        kind, payload = data
        if kind == "archive_video":
            arch = self._archives.get(payload[0])
            return arch.read(payload[1]) if arch else None
        with open(payload, "rb") as f:
            body = f.read()
        if payload.lower().endswith(RPGM_ENC_VIDEO):
            from app.core.rpgmaker import crypto
            key = crypto.get_key(self._game_dir() or "")
            if key:
                try:
                    return crypto.decrypt_bytes(body, key)
                except (ValueError, IndexError):
                    pass
        return body

    def _get_video_ext(self, path) -> str:
        if isinstance(path, tuple):
            path = path[1]
        low = path.lower()
        for ext in (".webm", ".mp4", ".m4v", ".avi"):
            if low.endswith(ext) or low.endswith(ext + "_"):
                return ext
        return ".webm"

    def _item_size(self, path) -> int:
        if isinstance(path, tuple):
            arch = self._archives.get(path[0])
            return arch._index.get(path[1], (0, 0))[1] if arch else 0
        return os.path.getsize(path)

    # ── video player ──
    def _clear_video_tmp(self):
        for p in self._video_tmp_files:
            try:
                os.remove(p)
            except OSError:
                pass
        self._video_tmp_files = []
        self._current_video = None

    def _show_video(self, data):
        self.image_scroll.setVisible(False)
        self._audio_widget.setVisible(False)
        self._video_widget.setVisible(True)
        self.video_title.setText(f"{self._current_item_name} — "
                                 f"{self._item_size(data[1]) / 1024:.0f} KB")
        self.lbl_info.setText(self._current_item_name)
        self.video_slider.setRange(0, 0)
        self.video_slider.setValue(0)
        self.lbl_video_pos.setText("0:00")
        self.lbl_video_dur.setText("0:00")
        self.btn_video_play.setIcon(icon("play"))
        self._clear_video_tmp()
        try:
            body = self._read_video_bytes(data)
            if not body:
                raise ValueError(TR("res_empty"))
            ext = self._get_video_ext(data[1])
            os.makedirs(_CACHE_DIR, exist_ok=True)
            tmp = os.path.join(_CACHE_DIR, f"_video_{uuid.uuid4().hex[:12]}{ext}")
            with open(tmp, "wb") as f:
                f.write(body)
            self._video_tmp_files.append(tmp)
            play_path = tmp
            conv = _to_mp4(tmp)
            if conv:
                self._video_tmp_files.append(conv)
                play_path = conv
            self._current_video = play_path
            self._video_player.setSource(QUrl.fromLocalFile(play_path))
            self._video_player.play()
        except Exception as e:
            self.lbl_info.setText(str(e))

    def _stop_video(self):
        self._video_player.stop()
        self._video_player.setSource(QUrl())
        self.btn_video_play.setIcon(icon("play"))
        self.video_slider.setRange(0, 0)
        self.video_slider.setValue(0)
        self.lbl_video_pos.setText("0:00")
        self.lbl_video_dur.setText("0:00")
        self._clear_video_tmp()

    def _toggle_video_play(self):
        if self._video_player.playbackState() == QMediaPlayer.PlayingState:
            self._video_player.pause()
        else:
            self._video_player.play()

    def _seek_video(self, pos):
        self._video_player.setPosition(pos)

    def _on_video_pos(self, pos):
        if not self.video_slider.isSliderDown():
            self.video_slider.setValue(pos)
        self.lbl_video_pos.setText(_ms_to_str(pos))

    def _on_video_dur(self, dur):
        self.video_slider.setRange(0, dur)
        self.lbl_video_dur.setText(_ms_to_str(dur))

    def _on_video_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self.btn_video_play.setIcon(icon("pause"))
        elif state == QMediaPlayer.PausedState:
            self.btn_video_play.setIcon(icon("play"))
        elif state == QMediaPlayer.StoppedState:
            self.btn_video_play.setIcon(icon("play"))

    def _on_video_error(self, err, msg):
        self.lbl_info.setText(TR("res_video_fail") + ": " + msg)

    def _download_current_video(self):
        data = self._current_item_data
        if not data or data[0] not in ("video", "archive_video"):
            return
        body = self._read_video_bytes(data)
        if body is None:
            return
        name = os.path.basename(data[1]) if not isinstance(data[1], tuple) \
            else os.path.basename(data[1][1])
        path, _ = QFileDialog.getSaveFileName(
            self, TR("res_ctx_save_video"), name, "Video (*)")
        if not path:
            return
        with open(path, "wb") as f:
            f.write(body)

    # ── image preview ──
    def _show_image(self, data):
        self.image_scroll.setVisible(True)
        self._audio_widget.setVisible(False)
        self._video_widget.setVisible(False)
        try:
            body = self._read_image_bytes(data)
            if not body:
                raise ValueError(TR("res_empty"))
            qimg = QImage()
            qimg.loadFromData(body)
            if qimg.isNull():
                raise ValueError(TR("res_decode_fail"))
            pixmap = QPixmap.fromImage(qimg)
            self.image_label.setPixmap(pixmap)
            self.lbl_info.setText(
                f"{self._current_item_name} — "
                f"{pixmap.width()}×{pixmap.height()}, "
                + TR("res_size_kb", size=f"{len(body) / 1024:.0f}"))
        except Exception as e:
            self.image_label.setText(str(e))
            self.lbl_info.setText("")

    def _save_current_image(self):
        pixmap = self.image_label._pixmap
        if pixmap is None or pixmap.isNull():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, TR("res_ctx_save"), self._current_item_name,
            "PNG (*.png);;JPEG (*.jpg);;All (*)")
        if not path:
            return
        fmt = "JPEG" if path.lower().endswith((".jpg", ".jpeg")) else "PNG"
        pixmap.save(path, fmt)

    def _download_current_audio(self):
        data = self._current_item_data
        if not data or data[0] not in ("audio", "archive_audio"):
            return
        body = self._read_audio_bytes(data)
        if body is None:
            return
        name = os.path.basename(data[1]) if not isinstance(data[1], tuple) \
            else os.path.basename(data[1][1])
        path, _ = QFileDialog.getSaveFileName(
            self, TR("res_ctx_save_audio"), name, "Audio (*)")
        if not path:
            return
        with open(path, "wb") as f:
            f.write(body)

    # ── audio: convert to WAV ──
    def _prepare_wav(self, data) -> str | None:
        """Get a WAV file path for the given audio data."""
        raw = self._read_audio_bytes(data)
        if raw is None:
            return None
        ext = self._get_audio_ext(data[1])
        if ext == ".wav":
            os.makedirs(_CACHE_DIR, exist_ok=True)
            p = os.path.join(_CACHE_DIR, f"_play_{uuid.uuid4().hex[:10]}.wav")
            with open(p, "wb") as f:
                f.write(raw)
            return p
        return _raw_to_wav(raw, data[1])

    # ── audio player (QMediaPlayer) ──
    def _show_audio_info(self, data):
        self.image_scroll.setVisible(False)
        self._audio_widget.setVisible(True)
        self._video_widget.setVisible(False)
        path = data[1]
        if isinstance(path, tuple):
            arch = self._archives.get(path[0])
            size_bytes = (arch._index.get(path[1], (0, 0))[1]
                          if arch else 0)
        else:
            size_bytes = os.path.getsize(path)
        size_kb = size_bytes / 1024
        self.audio_title.setText(f"{self._current_item_name} — {size_kb:.0f} KB")
        self.lbl_info.setText(self._current_item_name)
        self.audio_slider.setRange(0, 0)
        self.audio_slider.setValue(0)
        self.lbl_pos.setText("0:00")
        self.lbl_dur.setText("0:00")
        self.btn_play.setIcon(icon("play"))

    def _toggle_play(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
        else:
            self._play_audio()

    def _play_audio(self):
        data = self._current_item_data
        if not data or data[0] != "audio":
            return
        if not _FFMPEG:
            QMessageBox.warning(self, TR("err"), TR("res_no_ffmpeg"))
            return
        wav = self._prepare_wav(data)
        if not wav:
            QMessageBox.warning(self, TR("err"), TR("res_audio_fail"))
            return
        self._current_wav = wav
        self._player.setSource(QUrl.fromLocalFile(wav))
        self._player.play()

    def _stop_audio(self):
        self._player.stop()
        self.btn_play.setIcon(icon("play"))
        self.audio_slider.setRange(0, 0)
        self.audio_slider.setValue(0)
        self.lbl_pos.setText("0:00")
        self.lbl_dur.setText("0:00")
        if self._current_wav:
            try:
                os.remove(self._current_wav)
            except OSError:
                pass
            self._current_wav = None

    def _seek(self, pos):
        self._player.setPosition(pos)

    def _on_pos(self, pos):
        if not self.audio_slider.isSliderDown():
            self.audio_slider.setValue(pos)
        self.lbl_pos.setText(_ms_to_str(pos))

    def _on_dur(self, dur):
        self.audio_slider.setRange(0, dur)
        self.lbl_dur.setText(_ms_to_str(dur))

    def _on_state(self, state):
        if state == QMediaPlayer.PlayingState:
            self.btn_play.setIcon(icon("pause"))
        elif state == QMediaPlayer.PausedState:
            self.btn_play.setIcon(icon("play"))
        elif state == QMediaPlayer.StoppedState:
            self.btn_play.setIcon(icon("play"))
            if self._current_wav and os.path.exists(self._current_wav):
                self.audio_slider.setValue(self.audio_slider.maximum())

    def _on_error(self, err, msg):
        QMessageBox.warning(self, TR("err"), msg)

    # ── list context menu ──
    def _list_ctx_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        menu = QMenu(self)
        kind = data[0]
        if kind in ("audio", "archive_audio"):
            act = menu.addAction(TR("res_ctx_save_audio"))
            act.triggered.connect(lambda: self._save_audio_file(data))
        elif kind in ("video", "archive_video"):
            act = menu.addAction(TR("res_ctx_save_video"))
            act.triggered.connect(lambda: self._save_video_file(data))
        elif kind in ("img", "archive_img"):
            act = menu.addAction(TR("res_ctx_save"))
            act.triggered.connect(lambda: self._save_image_file(data))
        if menu.actions():
            menu.exec(self.list.mapToGlobal(pos))

    def _save_audio_file(self, data):
        body = self._read_audio_bytes(data)
        if body is None:
            return
        name = os.path.basename(data[1]) if not isinstance(data[1], tuple) \
            else os.path.basename(data[1][1])
        path, _ = QFileDialog.getSaveFileName(
            self, TR("res_ctx_save_audio"), name, "Audio (*)")
        if not path:
            return
        with open(path, "wb") as f:
            f.write(body)

    def _save_image_file(self, data):
        body = self._read_image_bytes(data)
        if body is None:
            return
        name = os.path.basename(data[1]) if not isinstance(data[1], tuple) \
            else os.path.basename(data[1][1])
        path, _ = QFileDialog.getSaveFileName(
            self, TR("res_ctx_save"), name, "PNG (*.png);;All (*)")
        if not path:
            return
        with open(path, "wb") as f:
            f.write(body)

    def _save_video_file(self, data):
        body = self._read_video_bytes(data)
        if body is None:
            return
        name = os.path.basename(data[1]) if not isinstance(data[1], tuple) \
            else os.path.basename(data[1][1])
        path, _ = QFileDialog.getSaveFileName(
            self, TR("res_ctx_save_video"), name, "Video (*)")
        if not path:
            return
        with open(path, "wb") as f:
            f.write(body)

    # ── font (RPGM: выбор своего файла; Ren'Py — на главной странице) ──
    def _patch_font(self):
        p = self.main.project
        if not p:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, TR("res_font"), r"C:\Windows\Fonts",
            "Fonts (*.ttf *.otf *.woff)")
        if not path:
            return
        from app.core.rpgmaker.fontpatch import patch_font
        try:
            report = patch_font(p.game_dir, p.engine, path)
        except Exception as e:
            QMessageBox.critical(self, TR("res_font"), str(e))
            return
        QMessageBox.information(
            self, TR("done"),
            TR("res_font_done", font=report["font"]))


def _ms_to_str(ms: int) -> str:
    s = ms // 1000
    m, s = divmod(s, 60)
    return f"{m}:{s:02d}"
