# -*- coding: utf-8 -*-
"""Диалог настроек: три вкладки — Основные, Файлы, AI-корректор."""
from __future__ import annotations

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout,
                                QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                                QPushButton, QSpinBox,
                                QVBoxLayout, QWidget)

from app.core import cache as app_cache
from app.core.translate.engines import PROVIDERS, AI_PROVIDERS
from app.ui.i18n import TR, provider_name
from app.ui.icons import icon
from app.ui.loading_overlay import BusyLabel
from app.ui.theme import AnimatedComboBox, AnimatedTabWidget

PRESETS = {
    "OpenRouter": "https://openrouter.ai/api/v1",
    "OpenAI": "https://api.openai.com/v1",
    "NanoGPT": "https://nano-gpt.com/api/v1",
    "LM Studio": "http://localhost:1234/v1",
    "Ollama": "http://localhost:11434/v1",
}


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
        tabs.addTab(self._build_ai_tab(s), TR("settings_corr_tab"))
        tabs.addTab(self._build_system_tab(s), TR("settings_system_tab"))
        lay.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_save = QPushButton(TR("settings_save"))
        btn_save.setObjectName("accent")
        btn_save.clicked.connect(self._save_and_close)
        bottom.addWidget(btn_save)
        lay.addLayout(bottom)

        self._on_files_provider_changed()
        self._on_corrector_provider_changed()

    # ── Helper: build engine settings group ──
    def _build_engine_group(self, s, engine_key, prefix,
                            title: str | None = None,
                            providers: dict | None = None) -> QGroupBox:
        box = QGroupBox(title or TR("settings_provider"))
        form = QFormLayout(box)

        combo = AnimatedComboBox()
        provs = providers or PROVIDERS
        for key in provs:
            combo.addItem(provider_name(key), key)
        idx = combo.findData(s.value(engine_key, "rotate"))
        combo.setCurrentIndex(max(idx, 0))
        form.addRow(TR("settings_provider_lbl"), combo)

        # ── AI preset row ──
        preset_row = QWidget()
        preset_lay = QHBoxLayout(preset_row)
        preset_lay.setContentsMargins(0, 0, 0, 0)
        preset_lay.addWidget(QLabel(TR("settings_preset")))
        preset_buttons: dict[str, QPushButton] = {}
        for name in PRESETS:
            btn = QPushButton(name)
            btn.setCheckable(True)
            preset_lay.addWidget(btn)
            preset_buttons[name] = btn
        preset_lay.addStretch(1)
        form.addRow(preset_row)

        base_url = QLineEdit(s.value(f"base_url_{prefix}",
                                     PRESETS["OpenRouter"]))
        form.addRow(TR("settings_base_url"), base_url)

        api_key = QLineEdit()
        api_key.setEchoMode(QLineEdit.Password)
        api_key.setPlaceholderText(TR("settings_api_key_ph"))
        form.addRow(TR("settings_api_key"), api_key)

        model = QLineEdit(s.value("model", "qwen2.5:7b"))
        model.setPlaceholderText("gpt-4o-mini, qwen2.5:7b, …")
        form.addRow(TR("settings_model"), model)

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
            "engine": combo, "base_url": base_url, "api_key": api_key, "model": model,
            "preset_row": preset_row, "preset_buttons": preset_buttons,
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

        self.source_lang = AnimatedComboBox()
        self.source_lang.addItems(["auto", "ja", "zh", "en"])
        self.source_lang.setCurrentText(s.value("source_lang", "auto"))
        form.addRow(TR("settings_src_lang"), self.source_lang)

        self.target_lang = AnimatedComboBox()
        self.target_lang.addItems(["ru", "en"])
        self.target_lang.setCurrentText(s.value("target_lang", "ru"))
        form.addRow(TR("settings_tgt_lang"), self.target_lang)

        lay.addWidget(box)

        ui_box = QGroupBox(TR("settings_ui_lang"))
        ui_form = QFormLayout(ui_box)
        self.ui_lang = AnimatedComboBox()
        self.ui_lang.addItems([TR("settings_ui_ru"), TR("settings_ui_en")])
        self.ui_lang.setCurrentIndex(0 if s.value("ui_lang", "ru") == "ru" else 1)
        ui_form.addRow(TR("settings_ui_lang"), self.ui_lang)
        lay.addWidget(ui_box)

        close_box = QGroupBox(TR("settings_close_behavior"))
        close_form = QFormLayout(close_box)
        self.close_behavior = AnimatedComboBox()
        self.close_behavior.addItems([
            TR("settings_close_tray"),
            TR("settings_close_quit"),
        ])
        self.close_behavior.setCurrentIndex(
            0 if s.value("close_to_tray", True, type=bool) else 1)
        close_form.addRow(TR("settings_close_behavior"), self.close_behavior)
        lay.addWidget(close_box)

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
            s, "engine_files", "files", TR("settings_files_provider"))
        self.files_eng = self.files_engine_box._eng
        self.files_eng["engine"].currentIndexChanged.connect(
            self._on_files_provider_changed)
        self.files_eng["btn_ping"].clicked.connect(
            lambda: self._ping("files"))
        lay.addWidget(self.files_engine_box)

        self.corrector_engine_box = self._build_engine_group(
            s, "engine_corrector", "corrector", TR("settings_corr_provider"),
            providers=AI_PROVIDERS)
        self.corr_eng = self.corrector_engine_box._eng
        self.corr_eng["engine"].currentIndexChanged.connect(
            self._on_corrector_provider_changed)
        self.corr_eng["btn_ping"].clicked.connect(
            lambda: self._ping("corrector"))

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

    # ── Tab 4: AI Corrector (corrector + AI glossary) ──
    def _build_ai_tab(self, s) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(self.corrector_engine_box)

        gloss_box = QGroupBox(TR("settings_glossary_box"))
        gloss_form = QFormLayout(gloss_box)
        self.glossary_use_ai = QCheckBox(TR("settings_glossary_ai"))
        self.glossary_use_ai.setChecked(
            s.value("glossary_use_ai", True, type=bool))
        gloss_form.addRow(self.glossary_use_ai)
        info = QLabel(TR("settings_glossary_info"))
        info.setWordWrap(True)
        gloss_form.addRow(info)
        lay.addWidget(gloss_box)

        lay.addStretch(1)
        return w

    # ── Tab 5: System (cache size + auto-clean) ──
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

    # ── Provider visibility ──
    def _update_provider_visibility(self, eng: dict):
        key = eng["engine"].currentData()
        is_ai = key == "ai"

        eng["base_url"].setVisible(is_ai)
        eng["api_key"].setVisible(is_ai)
        eng["model"].setVisible(is_ai)
        eng["preset_row"].setVisible(is_ai)

        form = eng["form"]
        for w in (eng["base_url"], eng["api_key"],
                  eng["model"], eng["preset_row"]):
            label = form.labelForField(w)
            if label:
                label.setVisible(w.isVisible())

        if is_ai:
            eng["api_key"].setPlaceholderText(TR("settings_api_key_ph"))
        if self.isVisible():
            self.adjustSize()

    # ── Tab 3: AI Corrector (corrector + AI glossary) ──

    def _on_files_provider_changed(self):
        self._update_provider_visibility(self.files_eng)
        self._select_preset_for(self.files_eng, "files")

    def _on_corrector_provider_changed(self):
        self._update_provider_visibility(self.corr_eng)
        self._select_preset_for(self.corr_eng, "corrector")

    def _select_preset_for(self, eng: dict, prefix: str):
        s = self.main.settings
        saved_url = s.value(f"base_url_{prefix}", "")
        saved_key = s.value(f"api_key_{prefix}", "")
        if saved_url:
            eng["base_url"].setText(saved_url)
        if saved_key:
            eng["api_key"].setText(saved_key)
        for name, btn in eng["preset_buttons"].items():
            btn.setChecked(PRESETS.get(name, "") == eng["base_url"].text())
            btn.clicked.connect(
                lambda _=False, n=name, e=eng, p=prefix:
                    self._apply_preset(e, p, n))

    def _apply_preset(self, eng: dict, prefix: str, preset_name: str):
        s = self.main.settings
        url = PRESETS.get(preset_name, "")
        eng["base_url"].setText(s.value(f"base_url_{prefix}_{preset_name}",
                                        url))
        eng["api_key"].setText(s.value(f"api_key_{prefix}_{preset_name}", ""))
        for n, btn in eng["preset_buttons"].items():
            btn.setChecked(n == preset_name)

    # ── Ping ──
    def _ping(self, prefix: str):
        eng = {"files": self.files_eng,
               "corrector": self.corr_eng}.get(prefix, self.files_eng)
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

    # ── Save & close ──
    def _save_engine(self, eng: dict, engine_key: str, prefix: str):
        s = self.main.settings
        name = eng["engine"].currentData()
        s.setValue(engine_key, name)
        s.setValue(f"base_url_{prefix}", eng["base_url"].text())
        s.setValue(f"api_key_{prefix}", eng["api_key"].text())
        s.setValue("model", eng["model"].text())

    def _save_and_close(self):
        s = self.main.settings
        self._save_engine(self.files_eng, "engine_files", "files")
        self._save_engine(self.corr_eng, "engine_corrector", "corrector")
        s.setValue("source_lang", self.source_lang.currentText())
        s.setValue("target_lang", self.target_lang.currentText())
        s.setValue("auto_launch", self.auto_launch.isChecked())
        s.setValue("close_to_tray", self.close_behavior.currentIndex() == 0)
        s.setValue("file_overwrite_mode", self.overwrite_mode.currentIndex())
        s.setValue("auto_backup", self.auto_backup.isChecked())
        s.setValue("glossary_use_ai", self.glossary_use_ai.isChecked())
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
        for w in self._ping_workers.values():
            if w.isRunning():
                w.wait(5000)
        super().closeEvent(event)
