# -*- coding: utf-8 -*-
"""Мастер первоначальной настройки (первый запуск приложения).

Шаги: приветствие → языки → переводчик → поведение. Пишет те же ключи
QSettings, что и диалог настроек (ui_lang, source_lang, target_lang,
engine_files, base_url_files, api_key_files, model, auto_launch,
auto_backup). По завершении ставит setup_done=true.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from app.core.translate.engines import PROVIDERS, SOURCE_LANGS, TARGET_LANGS
from app.ui.i18n import TR, provider_name, set_language
from app.ui.theme import (C_TEXT, C_TEXT_SECONDARY,
                          AnimatedComboBox)

PRESET_OPENROUTER = "https://openrouter.ai/api/v1"

_STEPS = 4  # приветствие, языки, переводчик, поведение

_AI_FIELDS = ("ed_base_url", "ed_api_key", "ed_model")


class SetupWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("OctopusBridge", "OctopusBridge")
        self.setWindowTitle(TR("wizard_title"))
        self.setModal(True)
        self.setMinimumSize(580, 480)
        self._step = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        self._stack = QStackedWidget()
        self._pages: list[QWidget] = []
        self._rebuild_pages()
        root.addWidget(self._stack, 1)

        # ── step label + nav ──
        nav = QHBoxLayout()
        nav.setSpacing(8)
        self.lbl_step = QLabel("")
        self.lbl_step.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; background: transparent;")
        nav.addWidget(self.lbl_step)
        nav.addStretch(1)

        self.btn_skip = QPushButton(TR("wizard_skip"))
        self.btn_skip.setObjectName("danger")
        self.btn_skip.clicked.connect(self._on_skip)
        nav.addWidget(self.btn_skip)

        self.btn_back = QPushButton(TR("wizard_back"))
        self.btn_back.clicked.connect(self._on_back)
        nav.addWidget(self.btn_back)

        self.btn_next = QPushButton(TR("wizard_next"))
        self.btn_next.setObjectName("accent")
        self.btn_next.clicked.connect(self._on_next)
        nav.addWidget(self.btn_next)

        root.addLayout(nav)
        self._update_nav()

    # ══════════════════════════════════════════════════════════
    #  Страницы (пересобираются при смене языка интерфейса)
    # ══════════════════════════════════════════════════════════

    def _snapshot(self) -> dict:
        """Текущие значения полей — пересборка страниц их не потеряет."""
        snap: dict = {}
        for name in ("cb_ui_lang", "cb_source", "cb_target",
                     "cb_provider", "ed_base_url", "ed_api_key",
                     "ed_model", "cb_auto_launch",
                     "cb_auto_backup"):
            w = getattr(self, name, None)
            if w is None:
                continue
            if isinstance(w, AnimatedComboBox):
                if name == "cb_ui_lang":
                    snap["cb_ui_lang_idx"] = w.currentIndex()
                elif name == "cb_provider":
                    snap["cb_provider_data"] = w.currentData()
                else:
                    snap[name + "_saved"] = w.currentData()
            elif isinstance(w, QCheckBox):
                snap[name] = w.isChecked()
            else:
                snap[name] = w.text()
        return snap

    def _rebuild_pages(self, snapshot: dict | None = None):
        snap = snapshot if snapshot is not None else self._snapshot()
        old = self._pages
        pages = [
            self._build_welcome(),
            self._build_langs(snap),
            self._build_provider(snap),
            self._build_behavior(snap),
        ]
        for p in pages:
            self._stack.addWidget(p)
        self._stack.setCurrentIndex(min(self._step, len(pages) - 1))
        for p in old:
            self._stack.removeWidget(p)
            p.deleteLater()
        self._pages = pages

    # ── шаг 1: приветствие ──
    def _build_welcome(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(12)

        title = QLabel(TR("wizard_welcome_title"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {C_TEXT}; "
            f"background: transparent;")
        lay.addWidget(title)

        text = QLabel(TR("wizard_welcome_text"))
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignCenter)
        text.setStyleSheet(
            f"font-size: 13px; color: {C_TEXT_SECONDARY}; "
            f"background: transparent;")
        lay.addWidget(text)
        lay.addStretch(1)
        return w

    # ── шаг 2: языки ──
    def _build_langs(self, snap: dict) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 8, 24, 8)
        lay.setSpacing(10)

        title = QLabel(TR("wizard_langs_title"))
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {C_TEXT}; "
            f"background: transparent;")
        lay.addWidget(title)
        text = QLabel(TR("wizard_langs_text"))
        text.setWordWrap(True)
        text.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; background: transparent;")
        lay.addWidget(text)
        lay.addSpacing(6)

        box = QGroupBox(TR("settings_languages"))
        form = QFormLayout(box)

        self.cb_ui_lang = AnimatedComboBox()
        self.cb_ui_lang.addItems([TR("settings_ui_ru"), TR("settings_ui_en")])
        default_idx = 0 if self.settings.value("ui_lang", "ru") == "ru" else 1
        self.cb_ui_lang.setCurrentIndex(snap.get("cb_ui_lang_idx", default_idx))
        self.cb_ui_lang.currentIndexChanged.connect(self._on_ui_lang_changed)
        form.addRow(TR("settings_ui_lang"), self.cb_ui_lang)

        self.cb_source = AnimatedComboBox()
        for code in SOURCE_LANGS:
            self.cb_source.addItem(TR("lang_" + code), code)
        saved = snap.get("cb_source_saved",
                         self.settings.value("source_lang", "auto"))
        self.cb_source.setCurrentIndex(max(
            self.cb_source.findData(saved), 0))
        form.addRow(TR("settings_src_lang"), self.cb_source)

        self.cb_target = AnimatedComboBox()
        for code in TARGET_LANGS:
            self.cb_target.addItem(TR("lang_" + code), code)
        saved_t = snap.get("cb_target_saved",
                           self.settings.value("target_lang", "ru"))
        self.cb_target.setCurrentIndex(max(
            self.cb_target.findData(saved_t), 0))
        form.addRow(TR("settings_tgt_lang"), self.cb_target)
        lay.addWidget(box)
        lay.addStretch(1)
        return w

    def _on_ui_lang_changed(self, idx: int):
        lang = "ru" if idx == 0 else "en"
        self.settings.setValue("ui_lang", lang)
        set_language(lang)
        self._rebuild_pages()
        self._update_nav()

    # ── шаг 3: переводчик ──
    def _build_provider(self, snap: dict) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 8, 24, 8)
        lay.setSpacing(10)

        title = QLabel(TR("wizard_provider_title"))
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {C_TEXT}; "
            f"background: transparent;")
        lay.addWidget(title)
        text = QLabel(TR("wizard_provider_text"))
        text.setWordWrap(True)
        text.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; background: transparent;")
        lay.addWidget(text)
        lay.addSpacing(6)

        box = QGroupBox(TR("settings_provider"))
        form = QFormLayout(box)

        self.cb_provider = AnimatedComboBox()
        for key in PROVIDERS:
            self.cb_provider.addItem(provider_name(key), key)
        saved_p = self.settings.value("engine_files", "rotate")
        idx = self.cb_provider.findData(
            snap.get("cb_provider_data", saved_p))
        self.cb_provider.setCurrentIndex(max(idx, 0))
        self.cb_provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow(TR("settings_provider_lbl"), self.cb_provider)

        self.ed_base_url = QLineEdit(
            snap.get("ed_base_url",
                     self.settings.value("base_url_files",
                                         PRESET_OPENROUTER)))
        form.addRow(TR("settings_base_url"), self.ed_base_url)

        self.ed_api_key = QLineEdit(
            snap.get("ed_api_key", self.settings.value("api_key_files", "")))
        self.ed_api_key.setEchoMode(QLineEdit.Password)
        self.ed_api_key.setPlaceholderText(TR("settings_api_key_ph"))
        form.addRow(TR("settings_api_key"), self.ed_api_key)

        self.ed_model = QLineEdit(
            snap.get("ed_model",
                     self.settings.value("model", "qwen2.5:7b")))
        self.ed_model.setPlaceholderText("gpt-4o-mini, qwen2.5:7b, …")
        form.addRow(TR("settings_model"), self.ed_model)

        self._ai_fields: list[tuple[QLabel, QLineEdit]] = [
            (lbl, ed) for lbl, ed in zip(
                (form.labelForField(self.ed_base_url),
                 form.labelForField(self.ed_api_key),
                 form.labelForField(self.ed_model)),
                (self.ed_base_url, self.ed_api_key, self.ed_model))]
        lay.addWidget(box)
        lay.addStretch(1)
        self._on_provider_changed()
        return w

    def _on_provider_changed(self, *_):
        is_ai = self.cb_provider.currentData() == "ai"
        for lbl, ed in getattr(self, "_ai_fields", []):
            if lbl is not None:
                lbl.setVisible(is_ai)
            ed.setVisible(is_ai)

    # ── шаг 4: поведение ──
    def _build_behavior(self, snap: dict) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(24, 8, 24, 8)
        lay.setSpacing(10)

        title = QLabel(TR("wizard_behavior_title"))
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {C_TEXT}; "
            f"background: transparent;")
        lay.addWidget(title)
        text = QLabel(TR("wizard_behavior_text"))
        text.setWordWrap(True)
        text.setStyleSheet(
            f"color: {C_TEXT_SECONDARY}; background: transparent;")
        lay.addWidget(text)
        lay.addSpacing(6)

        box = QGroupBox(TR("settings_game"))
        b_lay = QVBoxLayout(box)

        self.cb_auto_launch = QCheckBox(TR("settings_auto_launch"))
        self.cb_auto_launch.setChecked(snap.get(
            "cb_auto_launch",
            self.settings.value("auto_launch", False, type=bool)))
        b_lay.addWidget(self.cb_auto_launch)

        self.cb_auto_backup = QCheckBox(TR("settings_backup"))
        self.cb_auto_backup.setChecked(snap.get(
            "cb_auto_backup",
            self.settings.value("auto_backup", True, type=bool)))
        b_lay.addWidget(self.cb_auto_backup)
        lay.addWidget(box)
        lay.addStretch(1)
        return w

    # ── навигация ──
    def _update_nav(self):
        self.btn_back.setVisible(self._step > 0)
        self.btn_next.setText(TR("wizard_finish")
                              if self._step == _STEPS - 1
                              else TR("wizard_next"))
        self.lbl_step.setText(TR("wizard_step", n=self._step + 1,
                                 total=_STEPS))
        self._stack.setCurrentIndex(self._step)

    def _on_next(self):
        if self._step < _STEPS - 1:
            self._step += 1
            self._update_nav()
        else:
            self._finish()

    def _on_back(self):
        if self._step > 0:
            self._step -= 1
            self._update_nav()

    def _on_skip(self):
        # ничего не сохраняем — остаются настройки по умолчанию
        self.settings.setValue("setup_done", True)
        self.accept()

    def _finish(self):
        s = self.settings
        s.setValue("ui_lang", "ru" if self.cb_ui_lang.currentIndex() == 0
                   else "en")
        s.setValue("source_lang", self.cb_source.currentData())
        s.setValue("target_lang", self.cb_target.currentData())
        s.setValue("engine_files", self.cb_provider.currentData())
        s.setValue("base_url_files", self.ed_base_url.text().strip())
        s.setValue("api_key_files", self.ed_api_key.text().strip())
        s.setValue("model", self.ed_model.text().strip())
        s.setValue("auto_launch", self.cb_auto_launch.isChecked())
        s.setValue("auto_backup", self.cb_auto_backup.isChecked())
        s.setValue("setup_done", True)
        self.accept()