# -*- coding: utf-8 -*-
"""Приветственный экран / дашборд.

До загрузки игры: приветствие с drag&drop + последние проекты.
После загрузки: дашборд с инфой, быстрыми действиями, провайдером.
"""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, Qt, QTimer,
                             QTimeLine, QThread, Signal)
from PySide6.QtWidgets import (QFileDialog, QFormLayout, QFrame,
                                QGroupBox, QHBoxLayout,
                                QLabel, QMessageBox, QPushButton, QVBoxLayout,
                                QWidget)

from app.ui.i18n import TR
from app.ui.icons import icon
from app.ui.theme import (C_CARD, C_CARD_HOVER, C_PRIMARY, C_SUCCESS,
                            C_TEXT, C_TEXT_SECONDARY, RADIUS_LG, RADIUS_MD,
                            fade_in)


class _LaunchWorker(QThread):
    """Запуск игры в фоне: щупальце ждёт подключения до 60 с —
    GUI не должен замирать, оверлей с анимацией показывает статус."""

    done = Signal(bool)

    def __init__(self, main_window, game_dir: str, parent=None):
        super().__init__(parent)
        self._main = main_window
        self._game_dir = game_dir

    def run(self):
        ok = self._main.start_session(self._game_dir)
        self.done.emit(bool(ok))


class WelcomeTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setAcceptDrops(True)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWidgets import QStackedWidget
        self._stack = QStackedWidget()

        # page 0: welcome
        self._page_welcome = self._build_welcome_page()
        self._stack.addWidget(self._page_welcome)

        # page 1: dashboard
        self._page_dashboard = self._build_dashboard_page()
        self._stack.addWidget(self._page_dashboard)

        self._root.addWidget(self._stack)

        # session signals (для читов)
        main_window.bridge_client.connect(self._on_session_client)
        main_window.session.game_exited.connect(self._on_session_game_exited)
        main_window.session.error.connect(self._on_session_error)

        # animation timer
        self._pulse = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(120)
        self._dots = 0
        self._loading = False

    # ===================================================================
    #  Page 0: Welcome
    # ===================================================================
    def _build_welcome_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(40, 24, 40, 24)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(8)

        # контент — по центру окна (равные растяжки сверху и снизу)
        lay.addStretch(1)

        # title
        title = QLabel(TR("welcome_title"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 32px; font-weight: bold; color: {C_TEXT}; "
            f"background: transparent;")
        lay.addWidget(title)

        subtitle = QLabel(TR("welcome_subtitle"))
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(
            f"font-size: 14px; color: {C_TEXT_SECONDARY}; "
            f"background: transparent;")
        lay.addWidget(subtitle)

        lay.addSpacing(20)

        # drag & drop zone
        self.drop = QLabel(TR("welcome_drop"))
        self.drop.setAlignment(Qt.AlignCenter)
        self.drop.setMinimumHeight(160)
        self.drop.setMaximumHeight(200)
        self.drop.setWordWrap(True)
        lay.addWidget(self.drop, 0, Qt.AlignHCenter)

        lay.addSpacing(6)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("background: transparent;")
        lay.addWidget(self.lbl_status)

        # browse + settings row
        row_btns = QHBoxLayout()
        row_btns.addStretch(1)
        btn_browse = QPushButton(TR("welcome_browse"))
        btn_browse.setObjectName("accent")
        btn_browse.setFixedWidth(220)
        btn_browse.clicked.connect(self._browse)
        row_btns.addWidget(btn_browse)
        btn_settings = QPushButton("")
        btn_settings.setIcon(icon("cog", 20))
        btn_settings.setFixedWidth(44)
        btn_settings.setToolTip(TR("welcome_settings_tooltip"))
        btn_settings.clicked.connect(self._open_settings)
        row_btns.addWidget(btn_settings)
        btn_about = QPushButton("")
        btn_about.setIcon(icon("info", 20))
        btn_about.setFixedWidth(44)
        btn_about.setToolTip(TR("about_title"))
        btn_about.clicked.connect(self._open_about)
        row_btns.addWidget(btn_about)
        row_btns.addStretch(1)
        lay.addLayout(row_btns)

        lay.addStretch(1)

        # hint — прижат к низу
        hint = QLabel(TR("welcome_hint"))
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; font-size: 11px; "
            f"background: transparent;")
        lay.addWidget(hint, 0, Qt.AlignHCenter)
        lay.addSpacing(8)

        return w

    # ===================================================================
    #  Page 1: Dashboard
    # ===================================================================
    def _build_dashboard_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(12)

        # top row: title + buttons
        top = QHBoxLayout()
        top.setSpacing(8)
        self.lbl_title = QLabel("Game")
        self.lbl_title.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {C_TEXT}; "
            f"background: transparent;")
        top.addWidget(self.lbl_title, 1)

        btn_settings = QPushButton("")
        btn_settings.setIcon(icon("cog", 20))
        btn_settings.setMinimumSize(40, 34)
        btn_settings.setStyleSheet(
            "QPushButton { padding: 2px 8px; }")
        btn_settings.setToolTip(TR("welcome_settings_tooltip"))
        btn_settings.clicked.connect(self._open_settings)
        top.addWidget(btn_settings)

        btn_folder = QPushButton("")
        btn_folder.setIcon(icon("folder-open", 18))
        btn_folder.setMinimumSize(40, 34)
        btn_folder.setStyleSheet(
            "QPushButton { padding: 2px 8px; }")
        btn_folder.setToolTip(TR("welcome_open_folder"))
        btn_folder.clicked.connect(self._open_game_folder)
        top.addWidget(btn_folder)

        btn_change = QPushButton("")
        btn_change.setIcon(icon("arrow-left", 18))
        btn_change.setMinimumSize(40, 34)
        btn_change.setStyleSheet(
            "QPushButton { padding: 2px 8px; }")
        btn_change.setToolTip(TR("dash_change_game"))
        btn_change.clicked.connect(self._go_welcome)
        top.addWidget(btn_change)

        lay.addLayout(top)

        # game info
        info_box = QGroupBox(TR("dash_game_info"))
        info_form = QFormLayout(info_box)
        info_form.setSpacing(6)
        self.lbl_engine = QLabel("—")
        self.lbl_path = QLabel("—")
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_enc = QLabel("—")
        self.lbl_saves = QLabel("—")
        self.lbl_stats = QLabel("—")
        self.lbl_stats.setWordWrap(True)
        info_form.addRow(TR("dash_engine"), self.lbl_engine)
        info_form.addRow(TR("dash_folder"), self.lbl_path)
        info_form.addRow(TR("dash_encryption"), self.lbl_enc)
        info_form.addRow(TR("dash_saves"), self.lbl_saves)
        info_form.addRow(TR("dash_stats"), self.lbl_stats)
        lay.addWidget(info_box)

        # quick actions: извлечение, перевод, запуск игры для читов
        actions_box = QGroupBox(TR("dash_actions"))
        actions_lay = QVBoxLayout(actions_box)

        row1 = QHBoxLayout()
        self.btn_extract = QPushButton(TR("dash_extract"))
        self.btn_extract.clicked.connect(self._action_extract)
        row1.addWidget(self.btn_extract)
        self.btn_translate_files = QPushButton(TR("dash_translate"))
        self.btn_translate_files.clicked.connect(self._action_translate_files)
        row1.addWidget(self.btn_translate_files)
        actions_lay.addLayout(row1)

        row_launch = QHBoxLayout()
        self.btn_launch = QPushButton(TR("dash_launch"))
        self.btn_launch.setObjectName("accent")
        self.btn_launch.setMinimumHeight(42)
        self.btn_launch.setIcon(icon("play"))
        self.btn_launch.clicked.connect(self._action_launch_toggle)
        row_launch.addWidget(self.btn_launch, 1)  # stretch=1 fills width
        actions_lay.addLayout(row_launch)

        self.lbl_session_status = QLabel(TR("dash_session_idle"))
        self.lbl_session_status.setWordWrap(True)
        actions_lay.addWidget(self.lbl_session_status)

        lay.addWidget(actions_box)

        # font patch (Ren'Py): жёсткая замена шрифтов на кириллический
        self.font_box = QGroupBox(TR("dash_font"))
        font_lay = QHBoxLayout(self.font_box)
        self.btn_font_patch = QPushButton(TR("res_font"))
        self.btn_font_patch.clicked.connect(self._font_patch)
        font_lay.addWidget(self.btn_font_patch, 1)
        self.btn_font_restore = QPushButton(TR("res_font_restore"))
        self.btn_font_restore.clicked.connect(self._font_restore)
        font_lay.addWidget(self.btn_font_restore)
        self.font_box.setVisible(False)
        lay.addWidget(self.font_box)

        lay.addStretch(1)
        return w

    # ===================================================================
    #  Refresh dashboard
    # ===================================================================
    def refresh_dashboard(self):
        p = self.main.project
        if not p:
            return

        self._stack.setCurrentWidget(self._page_dashboard)

        game_name = os.path.basename(os.path.normpath(p.game_dir))
        self.lbl_title.setText(game_name)

        module = self.main.engine_module
        self.lbl_engine.setText(module.display if module else "—")
        self.lbl_path.setText(p.game_dir)

        renpy_mode = bool(module and module.key == "renpy")
        self.font_box.setVisible(renpy_mode)
        if renpy_mode:
            from app.core.renpy import fontpatch
            self.btn_font_restore.setVisible(
                fontpatch.is_patched(p.game_dir))

        self._refresh_stats()

    def _refresh_stats(self):
        p = self.main.project
        if not p:
            return
        game = p.game_dir
        mod = self.main.engine_module
        sysd = None
        if mod is not None:
            try:
                view = mod.file_view(game)
                text = view.read_text("data/System.json")
                if text is None:
                    text = view.read_text("www/data/System.json")
                if text:
                    import json as _json
                    sysd = _json.loads(text)
            except Exception:
                sysd = None
        if sysd is None:
            try:
                import json as _json
                sys_path = os.path.join(game, "data", "System.json")
                if not os.path.exists(sys_path):
                    sys_path = os.path.join(game, "www", "data", "System.json")
                with open(sys_path, encoding="utf-8") as f:
                    sysd = _json.load(f)
            except Exception:
                sysd = None
        if sysd:
            enc = sysd.get("hasEncryptedImages") or sysd.get("hasEncryptedAudio")
            self.lbl_enc.setText(TR("dash_enc_yes") if enc else TR("dash_enc_no"))
        else:
            self.lbl_enc.setText("—")
        save_dir = os.path.join(game, "save")
        n = len([f for f in os.listdir(save_dir)
                 if f.endswith("save")]) if os.path.isdir(save_dir) else 0
        self.lbl_saves.setText(str(n))

        from app.core.rpgmaker import parser
        total = len(p.entries)
        done = sum(1 for e in p.entries if e.translation.strip())
        if total:
            self.lbl_stats.setText(
                TR("dash_stats_fmt", total=total,
                   done=done, left=total - done))
        else:
            self.lbl_stats.setText(TR("dash_no_extract"))

    # ===================================================================
    #  Quick actions
    # ===================================================================
    def _action_extract(self):
        p = self.main.project
        if not p or not self.main.engine_module:
            return
        self.btn_extract.setEnabled(False)
        self.lbl_status.setText(TR("tr_extracting"))
        self.main.start_extraction(self._on_extracted)

    def _on_extracted(self, restored: int, error: str):
        self.btn_extract.setEnabled(True)
        if error:
            self.lbl_status.setText(error)
            return
        p = self.main.project
        self._refresh_stats()
        QMessageBox.information(
            self, TR("done"),
            TR("tr_extract_done", count=len(p.entries), restored=restored))

    def _action_translate_files(self):
        ti = self.main.tabs.indexOf(self.main.translate_tab)
        if ti >= 0:
            self.main.tabs.setCurrentIndex(ti)

    def _action_launch_toggle(self):
        if self.main.session.is_active():
            self._action_stop()
        else:
            self._action_launch()

    def _action_launch(self):
        game_dir = self.main.project.game_dir if self.main.project else ""
        if not game_dir:
            return
        if getattr(self, "_launch_worker", None) and \
                self._launch_worker.isRunning():
            return
        self.btn_launch.setEnabled(False)
        self.btn_launch.setText(TR("dash_launching"))
        self.lbl_session_status.setText(TR("dash_launching"))
        self.main.loading.show_loading(TR("dash_launching"))
        self._launch_worker = _LaunchWorker(self.main, game_dir, self)
        self._launch_worker.done.connect(self._on_launch_done)
        self._launch_worker.start()

    def _on_launch_done(self, ok: bool):
        self.main.loading.hide_loading()

    def _action_stop(self):
        self.main.stop_session()
        self.btn_launch.setEnabled(True)
        self.btn_launch.setText(TR("dash_launch"))
        self.btn_launch.setIcon(icon("play"))
        self.lbl_session_status.setText(TR("dash_session_idle"))

    def _on_session_client(self, connected: bool):
        if connected:
            self.lbl_session_status.setText(TR("dash_session_connected"))
            self.btn_launch.setText(TR("dash_stop"))
            self.btn_launch.setIcon(icon("stop"))
        else:
            self.lbl_session_status.setText(TR("dash_session_idle"))
            self.btn_launch.setText(TR("dash_launch"))
            self.btn_launch.setIcon(icon("play"))
        self.btn_launch.setEnabled(True)

    def _on_session_game_exited(self):
        self.btn_launch.setEnabled(True)
        self.btn_launch.setText(TR("dash_launch"))
        self.btn_launch.setIcon(icon("play"))
        self.lbl_session_status.setText(TR("dash_session_closed"))

    def _on_session_error(self, text: str):
        self.lbl_session_status.setText(text)
        self.btn_launch.setEnabled(True)
        self.btn_launch.setText(TR("dash_launch"))
        self.main.loading.hide_loading()
        self.btn_launch.setIcon(icon("play"))

    # ===================================================================
    #  Font patch (Ren'Py)
    # ===================================================================
    def _font_patch(self):
        p = self.main.project
        if not p:
            return
        from app.core.renpy import fontpatch
        try:
            report = fontpatch.patch_font(p.game_dir)
        except Exception as e:
            QMessageBox.critical(self, TR("dash_font"), str(e))
            return
        if report["replaced"]:
            QMessageBox.information(
                self, TR("done"),
                TR("res_font_done_renpy", n=report["replaced"]))
        else:
            QMessageBox.information(self, TR("done"), TR("res_font_already"))
        self.refresh_dashboard()

    def _font_restore(self):
        p = self.main.project
        if not p:
            return
        from app.core.renpy import fontpatch
        try:
            fontpatch.restore_font(p.game_dir)
        except Exception as e:
            QMessageBox.critical(self, TR("err"), str(e))
            return
        QMessageBox.information(self, TR("done"), TR("res_font_restored"))
        self.refresh_dashboard()

    # ===================================================================
    #  Navigation
    # ===================================================================
    def _go_welcome(self):
        self.main.stop_session()
        self.main.project = None
        self.main.engine_module = None
        self.main._hide_work_tabs()

        for widget, _role in self.main._engine_tabs:
            idx = self.main.tabs.indexOf(widget)
            if idx >= 0:
                self.main.tabs.removeTab(idx)
            if widget is self.main.translate_tab:
                continue
            cleanup = getattr(widget, "cleanup", None)
            if cleanup:
                try:
                    cleanup()
                except Exception:  # noqa: BLE001
                    pass
            widget.setParent(None)
            widget.deleteLater()
        self.main._engine_tabs = []
        self.main.cheat_tab = None

        self._stack.setCurrentWidget(self._page_welcome)
        self.lbl_status.setText("")
        self.main._set_projects_tab_visible(True)
        self.main.projects_tab._rebuild()

    def _open_settings(self):
        from app.ui.settings_tab import SettingsDialog
        SettingsDialog(self.main, self.main).exec()

    def _open_about(self):
        from app.ui.app_info import show_about
        show_about(self.main)

    def _open_game_folder(self):
        p = self.main.project
        if not p:
            return
        path = p.game_dir
        if not os.path.isdir(path):
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", path])
        except OSError:
            pass

    # ===================================================================
    #  Animation & drag-and-drop
    # ===================================================================
    def _animate(self):
        if self._stack.currentIndex() != 0:
            return
        self._pulse = (self._pulse + 1) % 20
        shade = 70 + int(60 * abs(10 - self._pulse) / 10)
        self.drop.setStyleSheet(
            f"QLabel {{ border: 3px dashed rgb({shade},{shade},{shade + 40});"
            f" border-radius: {RADIUS_LG}px; color: #bbb; font-size: 18px; "
            f" padding: 20px; background: transparent; }}")
        if self._loading:
            self._dots = (self._dots + 1) % 4
            self.lbl_status.setText(
                TR("welcome_loading") + "." * self._dots)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.open_path(urls[0].toLocalFile())

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, TR("side_home"),
                                             os.getcwd())
        if d:
            self.open_path(d)

    def open_path(self, path: str):
        # Если это .html — проверяем, не Twine ли это
        if os.path.isfile(path) and path.lower().endswith(".html"):
            try:
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    if "<tw-storydata" in fh.read(1024 * 1024):
                        pass  # оставляем path как есть
                    else:
                        path = os.path.dirname(path)  # не Twine — берём папку
            except OSError:
                path = os.path.dirname(path)
        elif os.path.isfile(path):
            path = os.path.dirname(path)
        self._loading = True
        self._dots = 0
        self.lbl_status.setText(TR("welcome_loading") + "…")
        QTimer.singleShot(150, lambda: self._do_open(path))

    def _do_open(self, path: str):
        self._loading = False
        engine = self.main.open_project(path)
        if self.main.engine_module is not None:
            self.lbl_status.setText("")
        else:
            self.lbl_status.setText(TR("welcome_unsupported"))
            self._stack.setCurrentWidget(self._page_welcome)
