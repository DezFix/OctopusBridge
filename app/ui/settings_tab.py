# -*- coding: utf-8 -*-
"""Диалог настроек: три вкладки — Основные, Реалтайм, Файлы."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                                QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                                QMessageBox, QPushButton, QSpinBox,
                                QTabWidget, QVBoxLayout, QWidget)

from app.core.translate.engines import (PROVIDERS, AI_PROVIDERS,
                                        argos_download,
                                        argos_missing_pairs_all)
from app.ui.i18n import TR, provider_name

PRESETS = {
    "OpenRouter": "https://openrouter.ai/api/v1",
    "OpenAI": "https://api.openai.com/v1",
    "NanoGPT": "https://nano-gpt.com/api/v1",
    "LM Studio": "http://localhost:1234/v1",
    "Ollama": "http://localhost:11434/v1",
}


class DownloadWorker(QThread):
    progressed = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, pairs):
        super().__init__()
        self.setObjectName("DownloadWorker")
        self.pairs = pairs

    def run(self):
        try:
            installed = argos_download(
                self.pairs,
                progress=lambda i, n, name: self.progressed.emit(
                    f"Package {i}/{n}: {name}"))
            self.done.emit(installed)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class SettingsDialog(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main = main_window
        s = main_window.settings
        self.worker: DownloadWorker | None = None

        self.setWindowTitle(TR("settings_title"))
        self.setMinimumWidth(650)
        self.setMinimumHeight(520)
        lay = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(s), TR("settings_general"))
        tabs.addTab(self._build_live_tab(s), TR("settings_live"))
        tabs.addTab(self._build_files_tab(s), TR("settings_files"))
        lay.addWidget(tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_save = QPushButton(TR("settings_save"))
        btn_save.setObjectName("accent")
        btn_save.clicked.connect(self._save_and_close)
        bottom.addWidget(btn_save)
        lay.addLayout(bottom)

        self._on_live_provider_changed()
        self._on_files_provider_changed()
        self._on_corrector_provider_changed()

    # ── Helper: build engine settings group ──
    def _build_engine_group(self, s, engine_key, prefix,
                            title: str | None = None,
                            providers: dict | None = None) -> QGroupBox:
        box = QGroupBox(title or TR("settings_provider"))
        form = QFormLayout(box)

        combo = QComboBox()
        provs = providers or PROVIDERS
        for key in provs:
            combo.addItem(provider_name(key), key)
        idx = combo.findData(s.value(engine_key, "argos"))
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
        btn_dl = QPushButton(TR("settings_argos"))
        btn_row.addWidget(btn_ping)
        btn_row.addWidget(btn_dl)
        btn_row.addStretch(1)
        form.addRow(btn_row)

        lbl_status = QLabel("—")
        lbl_status.setWordWrap(True)
        form.addRow(TR("settings_status"), lbl_status)

        box._eng = {
            "engine": combo, "base_url": base_url, "api_key": api_key, "model": model,
            "preset_row": preset_row, "preset_buttons": preset_buttons,
            "btn_ping": btn_ping, "btn_dl": btn_dl,
            "lbl_status": lbl_status, "form": form,
        }
        return box

    # ── Tab 1: General (languages + UI lang) ──
    def _build_general_tab(self, s) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        box = QGroupBox(TR("settings_languages"))
        form = QFormLayout(box)

        self.source_lang = QComboBox()
        self.source_lang.addItems(["auto", "ja", "zh", "en"])
        self.source_lang.setCurrentText(s.value("source_lang", "auto"))
        form.addRow(TR("settings_src_lang"), self.source_lang)

        self.target_lang = QComboBox()
        self.target_lang.addItems(["ru", "en"])
        self.target_lang.setCurrentText(s.value("target_lang", "ru"))
        form.addRow(TR("settings_tgt_lang"), self.target_lang)

        lay.addWidget(box)

        ui_box = QGroupBox(TR("settings_ui_lang"))
        ui_form = QFormLayout(ui_box)
        self.ui_lang = QComboBox()
        self.ui_lang.addItems(["Русский", "English"])
        self.ui_lang.setCurrentIndex(0 if s.value("ui_lang", "ru") == "ru" else 1)
        ui_form.addRow(TR("settings_ui_lang"), self.ui_lang)
        lay.addWidget(ui_box)

        close_box = QGroupBox(TR("settings_close_behavior"))
        close_form = QFormLayout(close_box)
        self.close_behavior = QComboBox()
        self.close_behavior.addItems([
            TR("settings_close_tray"),
            TR("settings_close_quit"),
        ])
        self.close_behavior.setCurrentIndex(
            0 if s.value("close_to_tray", True, type=bool) else 1)
        close_form.addRow(TR("settings_close_behavior"), self.close_behavior)
        lay.addWidget(close_box)

        lay.addStretch(1)
        return w

    # ── Tab 2: Realtime (engine + port + auto_launch) ──
    def _build_live_tab(self, s) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.live_engine_box = self._build_engine_group(
            s, "engine_realtime", "realtime", TR("settings_live_provider"))
        self.live_eng = self.live_engine_box._eng
        self.live_eng["engine"].currentIndexChanged.connect(
            self._on_live_provider_changed)
        self.live_eng["btn_ping"].clicked.connect(
            lambda: self._ping("realtime"))
        self.live_eng["btn_dl"].clicked.connect(self.download_packages)
        lay.addWidget(self.live_engine_box)

        live_box = QGroupBox(TR("live_title"))
        live_form = QFormLayout(live_box)
        self.auto_launch = QCheckBox(TR("settings_auto_launch"))
        self.auto_launch.setChecked(s.value("auto_launch", False, type=bool))
        live_form.addRow(self.auto_launch)
        lay.addWidget(live_box)

        info = QLabel(TR("settings_ws_info"))
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addStretch(1)
        return w

    # ── Tab 3: Files (engines + overwrite + backup) ──
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
        self.files_eng["btn_dl"].clicked.connect(self.download_packages)
        lay.addWidget(self.files_engine_box)

        self.corrector_engine_box = self._build_engine_group(
            s, "engine_corrector", "corrector", TR("settings_corr_provider"),
            providers=AI_PROVIDERS)
        self.corr_eng = self.corrector_engine_box._eng
        self.corr_eng["engine"].currentIndexChanged.connect(
            self._on_corrector_provider_changed)
        self.corr_eng["btn_ping"].clicked.connect(
            lambda: self._ping("corrector"))
        self.corr_eng["btn_dl"].clicked.connect(self.download_packages)
        lay.addWidget(self.corrector_engine_box)

        opt_box = QGroupBox(TR("settings_files"))
        opt_form = QFormLayout(opt_box)
        self.overwrite_mode = QComboBox()
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

    def _on_live_provider_changed(self):
        self._update_provider_visibility(self.live_eng)
        self._select_preset_for(self.live_eng, "realtime")

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
        eng = {"realtime": self.live_eng, "files": self.files_eng,
               "corrector": self.corr_eng}.get(prefix, self.files_eng)
        engine = self.main.create_engine(prefix)
        if engine is None:
            eng["lbl_status"].setText(TR("settings_status_fail"))
            return
        ok = engine.ping()
        eng["lbl_status"].setText(
            TR("settings_status_ready") if ok else TR("settings_status_fail"))

    # ── Download Argos packages ──
    def download_packages(self):
        try:
            missing = argos_missing_pairs_all()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Argos", str(e))
            return
        if not missing:
            QMessageBox.information(self, "Argos", "All packages installed")
            return
        pairs_text = ", ".join(f"{a}→{b}" for a, b in missing)
        if QMessageBox.question(
                self, "Download",
                f"Packages: {pairs_text}?\n(~100-300 MB each)"
        ) != QMessageBox.Yes:
            return
        self.live_eng["btn_dl"].setEnabled(False)
        self.files_eng["btn_dl"].setEnabled(False)
        self.worker = DownloadWorker(missing)
        self.worker.progressed.connect(
            lambda t: self.live_eng["lbl_status"].setText(t))
        self.worker.done.connect(self._on_downloaded)
        self.worker.failed.connect(self._on_download_failed)
        self.worker.start()

    def _on_downloaded(self, installed: list):
        self.live_eng["btn_dl"].setEnabled(True)
        self.files_eng["btn_dl"].setEnabled(True)
        self.worker = None
        msg = "Installed: " + ", ".join(installed)
        self.live_eng["lbl_status"].setText(msg)
        self.files_eng["lbl_status"].setText(msg)

    def _on_download_failed(self, msg: str):
        self.live_eng["btn_dl"].setEnabled(True)
        self.files_eng["btn_dl"].setEnabled(True)
        self.worker = None
        QMessageBox.critical(self, "Argos", msg)

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
        self._save_engine(self.live_eng, "engine_realtime", "realtime")
        self._save_engine(self.files_eng, "engine_files", "files")
        self._save_engine(self.corr_eng, "engine_corrector", "corrector")
        s.setValue("source_lang", self.source_lang.currentText())
        s.setValue("target_lang", self.target_lang.currentText())
        s.setValue("auto_launch", self.auto_launch.isChecked())
        s.setValue("close_to_tray", self.close_behavior.currentIndex() == 0)
        s.setValue("file_overwrite_mode", self.overwrite_mode.currentIndex())
        s.setValue("auto_backup", self.auto_backup.isChecked())
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
        if self.worker and self.worker.isRunning():
            self.worker.wait(5000)
        super().closeEvent(event)
