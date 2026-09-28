# -*- coding: utf-8 -*-
"""Диалог настроек: три вкладки — Основные, Файлы, Система."""
from __future__ import annotations

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from app.core import cache as app_cache
from app.core.translate.engines import TARGET_LANGS
from app.ui.i18n import TR
from app.ui.icons import icon
from app.ui.loading_overlay import BusyLabel
from app.ui.theme import AnimatedComboBox, AnimatedTabWidget


class PingWorker(QThread):
    done = Signal(bool)

    def __init__(self, engine):
        super().__init__()
        self.setObjectName("PingWorker")
        self.engine = engine

    def run(self):
        try:
            ok = self.engine.ping()
        except Exception:  # noqa: BLE001
            ok = False
        self.done.emit(ok)


class SettingsDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        s = main_window.settings

        self.setWindowTitle(TR("settings_title"))
        self.setMinimumWidth(650)
        self.setMinimumHeight(520)
        lay = QVBoxLayout(self)
        self._ping_workers: dict[str, PingWorker] = {}

        tabs = AnimatedTabWidget()
        self.tabs = tabs
        tabs.addTab(self._build_general_tab(s), TR("settings_general"))
        tabs.addTab(self._build_files_tab(s), TR("settings_files"))
        tabs.addTab(self._build_system_tab(s), TR("settings_system_tab"))
        lay.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_wizard = QPushButton(TR("settings_show_wizard"))
        btn_wizard.clicked.connect(self._show_wizard)
        bottom.addWidget(btn_wizard)
        btn_save = QPushButton(TR("settings_save"))
        btn_save.setObjectName("accent")
        btn_save.clicked.connect(self._save_and_close)
        bottom.addWidget(btn_save)
        lay.addLayout(bottom)

    # ── Helper: build engine settings group ──
    def _build_engine_group(self, s,
                            title: str | None = None) -> QGroupBox:
        # Движок один (rotate-пул), выбора нет — только подпись,
        # что крутится внутри, плюс опции резервных провайдеров.
        box = QGroupBox(title or TR("settings_provider"))
        form = QFormLayout(box)

        info = QLabel(TR("settings_provider_fixed"))
        info.setWordWrap(True)
        form.addRow(info)

        email = QLineEdit(s.value("mymemory_email", ""))
        email.setPlaceholderText(TR("settings_mymemory_email_ph"))
        form.addRow(TR("settings_mymemory_email"), email)

        btn_row = QHBoxLayout()
        btn_ping = QPushButton(TR("settings_check"))
        busy = BusyLabel(box, size=12)
        btn_row.addWidget(btn_ping)
        btn_row.addWidget(busy)
        btn_row.addStretch(1)
        form.addRow(btn_row)

        lbl_status = QLabel("—")
        lbl_status.setWordWrap(True)
        form.addRow(TR("settings_status"), lbl_status)

        box._eng = {
            "engine": "rotate", "email": email,
            "btn_ping": btn_ping, "busy": busy,
            "lbl_status": lbl_status, "form": form,
        }
        return box

    # ── Tab 1: General (languages + UI lang) ──
    def _build_general_tab(self, s) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        box = QGroupBox(TR("settings_languages"))
        form = QFormLayout(box)

        # Исходный язык не выбирается: он всегда определяется по каждой
        # строке автоматически (detect_lang). В смешанных играх часть
        # текста японская, часть английская — одна галочка тут только
        # мешала. Оставляем единственный целевой язык на выбор.
        self.source_lang = None
        form.addRow(TR("settings_src_lang_auto"),
                    QLabel(TR("settings_src_lang_auto_note")))

        self.target_lang = AnimatedComboBox()
        for code in TARGET_LANGS:
            self.target_lang.addItem(TR("lang_" + code), code)
        idx = self.target_lang.findData(s.value("target_lang", "ru"))
        self.target_lang.setCurrentIndex(max(idx, 0))
        form.addRow(TR("settings_tgt_lang"), self.target_lang)

        self.tr_autoresume = QCheckBox(TR("tr_autoresume"))
        self.tr_autoresume.setChecked(
            s.value("tr_autoresume", True, type=bool))
        form.addRow("", self.tr_autoresume)

        lay.addWidget(box)

        ui_box = QGroupBox(TR("settings_ui_lang"))
        ui_form = QFormLayout(ui_box)
        self.ui_lang = AnimatedComboBox()
        self.ui_lang.addItems([TR("settings_ui_ru"), TR("settings_ui_en")])
        self.ui_lang.setCurrentIndex(0 if s.value("ui_lang", "ru") == "ru" else 1)
        ui_form.addRow(TR("settings_ui_lang"), self.ui_lang)
        lay.addWidget(ui_box)

        launch_box = QGroupBox(TR("settings_game"))
        launch_form = QFormLayout(launch_box)
        self.auto_launch = QCheckBox(TR("settings_auto_launch"))
        self.auto_launch.setChecked(s.value("auto_launch", False, type=bool))
        launch_form.addRow(self.auto_launch)
        lay.addWidget(launch_box)

        lay.addStretch(1)
        return w

    # ── Tab 2: Files (engines + overwrite + backup) ──
    def _build_files_tab(self, s) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.files_engine_box = self._build_engine_group(
            s, TR("settings_files_provider"))
        self.files_eng = self.files_engine_box._eng
        self.files_eng["btn_ping"].clicked.connect(
            lambda: self._ping("files"))
        lay.addWidget(self.files_engine_box)

        opt_box = QGroupBox(TR("settings_files"))
        opt_form = QFormLayout(opt_box)
        self.overwrite_mode = AnimatedComboBox()
        self.overwrite_mode.addItems([
            TR("settings_overwrite_new"),
            TR("settings_overwrite_all"),
        ])
        idx = s.value("file_overwrite_mode", 0, type=int)
        self.overwrite_mode.setCurrentIndex(idx)
        opt_form.addRow(TR("settings_overwrite"), self.overwrite_mode)
        self.auto_backup = QCheckBox(TR("settings_backup"))
        self.auto_backup.setChecked(s.value("auto_backup", True, type=bool))
        opt_form.addRow(self.auto_backup)
        lay.addWidget(opt_box)

        info = QLabel(TR("settings_files_info"))
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addStretch(1)
        return w

    # ── Tab 3: System (cache size + auto-clean) ──
    def _build_system_tab(self, s) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        cache_box = QGroupBox(TR("settings_cache_box"))
        form = QFormLayout(cache_box)

        self.cache_size_label = QLabel()
        self.cache_size_label.setWordWrap(True)
        form.addRow(TR("settings_cache_size_lbl"), self.cache_size_label)

        btn_row = QHBoxLayout()
        self.btn_clean_cache = QPushButton(TR("settings_cache_clean"))
        self.btn_clean_cache.setIcon(icon("trash", 16))
        self.btn_clean_cache.clicked.connect(self._clean_cache)
        btn_row.addWidget(self.btn_clean_cache)
        self.btn_open_cache = QPushButton(TR("settings_cache_open"))
        self.btn_open_cache.setIcon(icon("folder-open", 16))
        self.btn_open_cache.clicked.connect(self._open_cache_dir)
        btn_row.addWidget(self.btn_open_cache)
        btn_row.addStretch(1)
        form.addRow(btn_row)

        self.auto_clean = QCheckBox(TR("settings_cache_auto"))
        self.auto_clean.setChecked(s.value("cache_auto_clean", False,
                                           type=bool))
        form.addRow(self.auto_clean)

        spin_row = QWidget()
        spin_lay = QHBoxLayout(spin_row)
        spin_lay.setContentsMargins(0, 0, 0, 0)
        self.cache_limit_spin = QSpinBox()
        self.cache_limit_spin.setRange(10, 2000)
        self.cache_limit_spin.setValue(
            s.value("cache_auto_clean_mb", 200, type=int))
        self.cache_limit_spin.setSuffix(" " + TR("settings_cache_mb"))
        spin_lay.addWidget(self.cache_limit_spin)
        spin_lay.addStretch(1)
        form.addRow(TR("settings_cache_limit"), spin_row)

        self.cache_status = QLabel("")
        self.cache_status.setWordWrap(True)
        form.addRow(self.cache_status)

        lay.addWidget(cache_box)

        info = QLabel(TR("settings_cache_info"))
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addStretch(1)
        self._refresh_cache_size()
        return w

    def _cache_lang(self) -> str:
        return "ru" if self.ui_lang.currentIndex() == 0 else "en"

    def _refresh_cache_size(self):
        total, files = app_cache.projects_size()
        tmp_total, tmp_files = app_cache.temp_size()
        self.cache_size_label.setText(
            TR("settings_cache_size",
               size=app_cache.format_size(total, self._cache_lang()),
               files=files,
               tmp=app_cache.format_size(tmp_total, self._cache_lang()),
               tmp_files=tmp_files))

    def _clean_cache(self):
        freed = app_cache.clean_cache()
        self._refresh_cache_size()
        if freed > 0:
            self.cache_status.setText(
                TR("settings_cache_cleaned",
                   size=app_cache.format_size(freed, self._cache_lang())))
        else:
            self.cache_status.setText(TR("settings_cache_nothing"))

    def _open_cache_dir(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(app_cache.temp_dir()))

    # ── Ping ──
    def _ping(self, prefix: str):
        eng = self.files_eng
        w = self._ping_workers.get(prefix)
        if w and w.isRunning():
            return
        engine = self.main.create_engine(prefix)
        if engine is None:
            eng["lbl_status"].setText(TR("settings_status_fail"))
            return
        eng["btn_ping"].setEnabled(False)
        eng["busy"].start(TR("settings_status_ping"))
        w = PingWorker(engine)
        self._ping_workers[prefix] = w
        w.done.connect(
            lambda ok, e=eng, p=prefix: self._ping_done(p, e, ok))
        w.start()

    def _ping_done(self, prefix: str, eng: dict, ok: bool):
        eng["btn_ping"].setEnabled(True)
        eng["busy"].stop()
        eng["lbl_status"].setText(
            TR("settings_status_ready") if ok else TR("settings_status_fail"))
        self._ping_workers.pop(prefix, None)

    # ── Show setup wizard again ──
    def _show_wizard(self):
        from app.ui.setup_wizard import SetupWizard

        s = self.main.settings
        old_lang = s.value("ui_lang", "ru")
        s.setValue("setup_done", False)
        wizard = SetupWizard(self)
        wizard.exec()
        new_lang = s.value("ui_lang", "ru")
        self.ui_lang.setCurrentIndex(0 if new_lang == "ru" else 1)
        if new_lang != old_lang:
            QMessageBox.information(self, TR("info"),
                                    TR("settings_restart_hint"))

    # ── Save & close ──
    def _save_engine(self, eng: dict):
        s = self.main.settings
        s.setValue("engine_files", "rotate")
        s.setValue("mymemory_email", eng["email"].text().strip())

    def _save_and_close(self):
        s = self.main.settings
        self._save_engine(self.files_eng)
        s.setValue("source_lang", "auto")
        s.setValue("target_lang", self.target_lang.currentData())
        s.setValue("tr_autoresume", self.tr_autoresume.isChecked())
        s.setValue("auto_launch", self.auto_launch.isChecked())
        s.setValue("file_overwrite_mode", self.overwrite_mode.currentIndex())
        s.setValue("auto_backup", self.auto_backup.isChecked())
        s.setValue("cache_auto_clean", self.auto_clean.isChecked())
        s.setValue("cache_auto_clean_mb", self.cache_limit_spin.value())
        old_lang = s.value("ui_lang", "ru")
        new_lang = "ru" if self.ui_lang.currentIndex() == 0 else "en"
        s.setValue("ui_lang", new_lang)
        if new_lang != old_lang:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, TR("info"), TR("settings_restart_hint"))
        self.main.welcome_tab.refresh_dashboard()
        if hasattr(self.main, "refresh_status_bar"):
            self.main.refresh_status_bar()
        self.accept()

    def closeEvent(self, event):
        # P0: не блокируем GUI дольше 200мс на воркер; незавершённые
        # PingWorker доудалятся сами по finished.
        for w in list(self._ping_workers.values()):
            try:
                if w.isRunning():
                    w.requestInterruption()
                    if w.wait(200):
                        w.deleteLater()
                    else:
                        w.finished.connect(w.deleteLater)
                else:
                    w.deleteLater()
            except RuntimeError:
                pass
        self._ping_workers.clear()
        super().closeEvent(event)
