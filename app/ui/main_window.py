# -*- coding: utf-8 -*-
"""Главное окно OctopusBridge — ядро + движковые модули.

До загрузки игры: приветственный экран (drag & drop).
После загрузки: дашборд на вкладке «Домой» + рабочие вкладки.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading

from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtGui import QIcon, QCloseEvent
from PySide6.QtWidgets import (QMainWindow, QTabWidget, QSystemTrayIcon,
                               QMenu)

import app as app_paths
from app.core.session import GameSession
from app.core.tentacles import create_tentacle
from app.core.models import Project
from app.core.translate.engines import get_engine
from app.core.translate.glossary import Glossary
from app.core.translate.memory import TranslationMemory
from app.core.translate.service import Translator
from app.engines.registry import detect_engine
from app.ui.i18n import TR, provider_short_name, set_language
from app.ui.welcome_tab import WelcomeTab
from app.ui.projects_tab import ProjectsTab
from app.ui.translate_tab import TranslateTab

PROJECTS_DIR = app_paths.projects_dir()

_MAX_RECENT = 8

_TAB_ICON_COLOR = "#0000ff"

_TAB_ROLE_ICONS = {
    "MapTab": "map-trifold",
    "ResourceTab": "image",
    "SaveEditorTab": "floppy-disk",
    "VariablesTab": "list-bullets",
    "TriggersTab": "target",
    "translate": "translate",
    "cheats": "sword",
    "triggers": "target",
    "module": "gear",
}


def _migrate_qsettings(new: QSettings):
    """Одноразовый перенос настроек со старого бренда WrGameBridge."""
    if new.allKeys():
        return
    old = QSettings("WrGameBridge", "WrGameBridge")
    for key in old.allKeys():
        new.setValue(key, old.value(key))
    new.sync()


def _cleanup_nllb_settings(s: QSettings):
    """Удаляет остатки удалённых движков (NLLB, Argos) из настроек."""
    for key in s.allKeys():
        if key.startswith("nllb_gpu_") or key == "engine_nllb":
            s.remove(key)
    if s.value("engine_realtime") == "nllb":
        s.setValue("engine_realtime", "honyaku")
    if s.value("engine_files") == "nllb":
        s.setValue("engine_files", "honyaku")
    if s.value("engine_corrector") == "nllb":
        s.setValue("engine_corrector", "ai")
    for key in ("engine_realtime", "engine_files", "engine_corrector"):
        if s.value(key) == "argos":
            s.setValue(key, "honyaku")


def _migrate_project_files():
    """Переименовывает проекты старого бренда *.wgb.json -> *.ob.json."""
    if not os.path.isdir(PROJECTS_DIR):
        return
    for name in os.listdir(PROJECTS_DIR):
        if name.endswith(".wgb.json"):
            try:
                os.replace(os.path.join(PROJECTS_DIR, name),
                           os.path.join(PROJECTS_DIR,
                                        name[:-len(".wgb.json")] + ".ob.json"))
            except OSError:
                pass


class _ModelPrefetch(QThread):
    """Фоновая загрузка офлайн-моделей honyaku (fast+best).

    progress: (сделано, всего, метка) для прогресс-диалога;
    status: текстовые сообщения для лога.
    """

    progress = Signal(int, int, str)
    status = Signal(str)

    def __init__(self, pairs, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelPrefetch")
        self.pairs = pairs
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        from app.core.translate.engines import honyaku_download, honyaku_warm
        try:
            honyaku_download(
                self.pairs,
                progress=lambda i, n, lbl: self.progress.emit(i, n, lbl),
                cancel=self.cancel_event)
            if not self.cancel_event.is_set():
                # прогреваем модели: первый перевод живой сессии не должен
                # платить загрузку модели прямо в серверном/CDP-потоке
                honyaku_warm(self.pairs)
                self.status.emit("Офлайн-модели готовы к работе.")
        except Exception as e:  # noqa: BLE001
            if not self.cancel_event.is_set():
                self.status.emit(
                    f"Автозагрузка моделей не удалась ({e}) — "
                    f"перевод включится после повторной попытки.")


class MainWindow(QMainWindow):
    bridge_client = Signal(bool)
    bridge_translated = Signal(str, str)
    bridge_log = Signal(str)
    bridge_state = Signal(str)
    bridge_vars = Signal(str)
    bridge_cheat_ack = Signal(str, bool, str, str)

    def __init__(self):
        super().__init__()
        self.settings = QSettings("OctopusBridge", "OctopusBridge")
        _migrate_qsettings(self.settings)
        _cleanup_nllb_settings(self.settings)
        set_language(self.settings.value("ui_lang", "en"))
        self.setWindowTitle(f"{TR('app_title')}  v{app_paths.__version__}")
        self.resize(1100, 750)
        icon_path = app_paths.icon_path()
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._really_quit = False
        self._setup_tray()

        os.makedirs(PROJECTS_DIR, exist_ok=True)
        _migrate_project_files()
        self._dedup_recent()
        self.tm = TranslationMemory(os.path.join(PROJECTS_DIR, "tm.sqlite"))
        self.glossary = Glossary(os.path.join(PROJECTS_DIR, "glossary.json"))
        self.project: Project | None = None
        self.session = GameSession(self)
        # ретрансляция сигналов щупальца в сигналы главного окна
        self.session.attached.connect(
            lambda: self.bridge_client.emit(True))
        self.session.detached.connect(
            lambda _reason="": self.bridge_client.emit(False))
        self.session.text_seen.connect(self.bridge_translated)
        self.session.log.connect(self.bridge_log)
        self.session.state_received.connect(
            lambda d: self.bridge_state.emit(
                json.dumps(d, ensure_ascii=False)))
        self.session.vars_received.connect(
            lambda v: self.bridge_vars.emit(
                json.dumps(v, ensure_ascii=False)))
        self.session.cheat_ack.connect(self.bridge_cheat_ack)
        self.session.error.connect(self.bridge_log)   # ошибки — в лог

        self.engine_module = None
        self.cheat_tab = None
        self._engine_tabs: list[tuple] = []   # [(widget, role)]

        # ── tabs ──
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.welcome_tab = WelcomeTab(self)
        self.translate_tab = TranslateTab(self)

        from app.ui.icons import icon
        self.tabs.addTab(self.welcome_tab,
                         icon("house", 18, _TAB_ICON_COLOR), TR("tab_home"))
        self.projects_tab = ProjectsTab(self)
        self.tabs.addTab(self.projects_tab,
                         icon("folder", 18, _TAB_ICON_COLOR),
                         TR("tab_projects"))

        from PySide6.QtWidgets import QWidget, QVBoxLayout
        from app.ui.status_bar import StatusBar
        central = QWidget()
        central_lay = QVBoxLayout(central)
        central_lay.setContentsMargins(0, 0, 0, 0)
        central_lay.setSpacing(0)
        self.status_bar = StatusBar()
        central_lay.addWidget(self.tabs, 1)
        central_lay.addWidget(self.status_bar)
        self.setCentralWidget(central)
        self.translate_tab_visible = False

        self.bridge_client.connect(self._on_sb_client)
        self.refresh_status_bar()

        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self._check_models_on_start)
        from app.ui.app_info import maybe_show_changelog
        QTimer.singleShot(900, lambda: maybe_show_changelog(self))

    # ---------- трей ----------
    def _setup_tray(self):
        icon = QIcon(app_paths.icon_path())
        if icon.isNull():
            return
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(TR("app_title"))
        menu = QMenu()
        act_open = menu.addAction(TR("tray_open"))
        act_open.triggered.connect(self._tray_open)
        menu.addSeparator()
        act_quit = menu.addAction(TR("tray_quit"))
        act_quit.triggered.connect(self._tray_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._tray_open()

    def _tray_open(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_quit(self):
        self._really_quit = True
        self.close()

    # ---------- показать/скрыть рабочие вкладки ----------
    def _show_work_tabs(self):
        self.translate_tab_visible = True

    def _hide_work_tabs(self):
        self.translate_tab_visible = False

    # вкладка «Проекты» видна только пока не открыта игра
    def _set_projects_tab_visible(self, visible: bool):
        idx = self.tabs.indexOf(self.projects_tab)
        if idx >= 0:
            self.tabs.setTabVisible(idx, visible)

    # ---------- движковой модуль ----------
    def _set_engine_module(self, module):
        self.stop_session()
        for widget, _role in self._engine_tabs:
            idx = self.tabs.indexOf(widget)
            if idx >= 0:
                self.tabs.removeTab(idx)
            if widget is self.translate_tab:
                continue
            cleanup = getattr(widget, "cleanup", None)
            if cleanup:      # останавливаем фоновые QThread вкладки
                try:
                    cleanup()
                except Exception:  # noqa: BLE001
                    pass
            widget.setParent(None)
            widget.deleteLater()
        self._engine_tabs = []
        self.cheat_tab = None
        self.engine_module = module
        if module:
            from app.ui.icons import icon
            for widget, title, role in module.ui_tabs(self):
                ic = (_TAB_ROLE_ICONS.get(type(widget).__name__)
                      or _TAB_ROLE_ICONS.get(role))
                self.tabs.addTab(widget,
                                 icon(ic or "file-text", 18, _TAB_ICON_COLOR),
                                 title)
                self._engine_tabs.append((widget, role))
        self._show_work_tabs()

    # ---------- проект ----------
    def _project_file(self, game_dir: str) -> str:
        name = hashlib.md5(os.path.abspath(game_dir).encode()).hexdigest()[:12]
        base = os.path.basename(os.path.normpath(game_dir)) or "game"
        safe = "".join(c if c.isalnum() else "_" for c in base)[:40]
        return os.path.join(PROJECTS_DIR, f"{safe}_{name}.ob.json")

    def open_project(self, game_dir: str) -> str:
        # Если это .html файл — для проекта берём родительскую папку
        if os.path.isfile(game_dir) and game_dir.lower().endswith(".html"):
            game_dir = os.path.dirname(game_dir)
        module = detect_engine(game_dir)
        self._set_engine_module(module)
        engine = (module.variant or module.key) if module else "unknown"

        pf = self._project_file(game_dir)
        if os.path.exists(pf):
            try:
                with open(pf, encoding="utf-8") as f:
                    self.project = Project.from_dict(json.load(f))
                self.project.engine = engine
            except (json.JSONDecodeError, OSError, KeyError):
                self.project = Project(game_dir=game_dir, engine=engine)
        else:
            self.project = Project(game_dir=game_dir, engine=engine)
        self.refresh_all()

        self._add_recent(game_dir, engine)

        self._set_projects_tab_visible(False)
        self.tabs.setCurrentWidget(self.welcome_tab)

        if self.settings.value("auto_launch", False, type=bool) \
                and module and "live" in module.features:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, self.welcome_tab._action_live_toggle)

        return engine

    def save_project(self):
        if not self.project:
            return
        with open(self._project_file(self.project.game_dir), "w",
                  encoding="utf-8") as f:
            json.dump(self.project.to_dict(), f, ensure_ascii=False)

    def refresh_all(self):
        self.welcome_tab.refresh_dashboard()
        self.translate_tab._selected_file = ""
        self.translate_tab._rebuild_file_list()
        self.translate_tab.fill_table()
        for widget, _role in self._engine_tabs:
            hook = getattr(widget, "on_project_opened", None)
            if hook:
                hook()

    # ---------- recent projects ----------
    def _dedup_recent(self):
        recent = self._recent_list()
        self.settings.setValue("recent_projects",
                               json.dumps(recent, ensure_ascii=False))

    def _recent_list(self) -> list[dict]:
        raw = self.settings.value("recent_projects", [])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raw = []
        if not isinstance(raw, list):
            raw = []
        for r in raw:
            if "path" in r:
                r["path"] = os.path.normpath(r["path"])
        seen = set()
        deduped = []
        for r in raw:
            p = r.get("path", "")
            if p and p not in seen:
                seen.add(p)
                deduped.append(r)
        return deduped

    def _add_recent(self, game_dir: str, engine: str):
        import time
        game_dir = os.path.normpath(game_dir)
        recent = self._recent_list()
        recent = [r for r in recent if r.get("path") != game_dir]
        recent.insert(0, {
            "path": game_dir,
            "name": os.path.basename(os.path.normpath(game_dir)),
            "engine": engine,
            "ts": int(time.time()),
        })
        recent = recent[:_MAX_RECENT]
        self.settings.setValue("recent_projects", json.dumps(recent,
                                                              ensure_ascii=False))

    def remove_recent(self, path: str):
        path = os.path.normpath(path)
        recent = self._recent_list()
        recent = [r for r in recent if r.get("path") != path]
        self.settings.setValue("recent_projects", json.dumps(recent,
                                                              ensure_ascii=False))

    def _clear_recent(self):
        self.settings.setValue("recent_projects", json.dumps([],
                                                              ensure_ascii=False))

    def _rename_recent(self, path: str, new_name: str):
        path = os.path.normpath(path)
        recent = self._recent_list()
        for r in recent:
            if r.get("path") == path:
                r["name"] = new_name
                break
        self.settings.setValue("recent_projects", json.dumps(recent,
                                                              ensure_ascii=False))

    # ---------- движок перевода ----------
    def create_engine(self, engine_type: str = "files"):
        s = self.settings
        if engine_type == "realtime":
            name = s.value("engine_realtime", "honyaku")
        elif engine_type == "corrector":
            name = s.value("engine_corrector",
                           s.value("engine_files", s.value("engine", "honyaku")))
        else:
            name = s.value("engine_files", s.value("engine", "honyaku"))
        model = s.value("model", s.value("ollama_model", "qwen2.5:7b"))
        pfx = engine_type
        try:
            if name == "ai":
                return get_engine("ai",
                                  base_url=s.value(
                                      f"base_url_{pfx}",
                                      "https://openrouter.ai/api/v1"),
                                  api_key=s.value(f"api_key_{pfx}", ""),
                                  model=model)
            if name in ("google_free", "bing", "rotate"):
                return get_engine(name)
            if name in ("honyaku", "argos"):
                return get_engine(name)
            raise ValueError(f"Unknown engine: {name}")
        except Exception:  # noqa: BLE001
            return None

    def build_translate_fn(self, engine):
        s = self.settings
        src = s.value("source_lang", "auto")
        tgt = s.value("target_lang", "ru")
        state = {"error_reported": False}
        translator = Translator(engine, tm=self.tm, glossary=self.glossary)

        def translate(text: str) -> str:
            try:
                return translator.translate_text(text, src, tgt)
            except Exception as e:  # noqa: BLE001
                if not state["error_reported"]:
                    state["error_reported"] = True
                    self.bridge_log.emit(
                        f"Translation engine unavailable ({e}). "
                        f"Returning original text.")
                return text

        return translate

    # ---------- фоновое извлечение текста ----------
    def start_extraction(self, on_done) -> bool:
        """Извлечение в фоне (GUI не морозит).
        on_done(restored: int, error: str)."""
        from app.ui.translate_tab import ExtractWorker
        p = self.project
        module = self.engine_module
        if not p or not module:
            return False
        old = getattr(self, "_extract_worker", None)
        if old and old.isRunning():
            return False
        self._extract_worker = ExtractWorker(module, p.game_dir)
        self._extract_worker.done.connect(
            lambda entries: on_done(self._merge_extracted(entries), ""))
        self._extract_worker.failed.connect(lambda e: on_done(0, e))
        self._extract_worker.start()
        return True

    def _merge_extracted(self, new_entries) -> int:
        """Сливает свежее извлечение с переводами проекта (восстановление
        по ключу и по тексту). Возвращает число восстановленных."""
        p = self.project
        old_by_key = {(e.file, e.json_path): (e.translation, e.status)
                      for e in p.entries if e.translation.strip()}
        old_by_text = {e.original: (e.translation, e.status)
                       for e in p.entries if e.translation.strip()}
        restored = 0
        for e in new_entries:
            hit = old_by_key.get((e.file, e.json_path)) \
                or old_by_text.get(e.original)
            if hit:
                e.translation, e.status = hit
                restored += 1
        p.entries = new_entries
        self.save_project()
        return restored

    # ---------- живая сессия (щупальце) ----------
    def channel(self):
        """Активное щупальце или None — точка доступа чит-вкладок."""
        t = self.session.tentacle
        return t if (t and t.is_attached()) else None

    def start_session(self, target: str, translate_fn,
                      attach_pid: int | None = None,
                      port_hint: int = 0) -> bool:
        """Создаёт щупальце для текущего движка и подключает его к игре."""
        key = self.engine_module.key if self.engine_module else ""
        tentacle = create_tentacle(key)
        if tentacle is None:
            self.bridge_log.emit(TR("live_unsupported"))
            return False
        tentacle.set_translate_fn(translate_fn)
        self._live_translate_fn = translate_fn
        tentacle.setParent(self)
        if port_hint and hasattr(tentacle, "set_port_hint"):
            tentacle.set_port_hint(port_hint)
        if attach_pid is not None:
            ok = self.session.attach(tentacle, attach_pid)
        else:
            ok = self.session.launch(tentacle, target)
        if not ok:
            self.status_bar.set_connected(False)
        return ok

    def stop_session(self, kill_game: bool = True):
        self.session.stop(kill_game=kill_game)
        if hasattr(self, "status_bar"):
            self.status_bar.set_connected(False)

    def set_live_translation(self, enabled: bool):
        """Вкл/выкл перевод в живой сессии на лету.

        Щупальце остаётся подключённым — читы, переменные и состояние
        продолжают работать, текст показывается без перевода.
        """
        self.session.set_translation_enabled(enabled)

    # ---------- статус-бар ----------
    def refresh_status_bar(self):
        """Обновляет провайдера и соединение в нижнем статус-баре."""
        if not hasattr(self, "status_bar"):
            return
        name = self.settings.value(
            "engine_realtime", self.settings.value("engine", "honyaku"))
        self.status_bar.set_provider(provider_short_name(str(name)))
        self.status_bar.set_connected(self.session.is_active(),
                                      backend=self._backend_name())

    def _backend_name(self) -> str:
        t = self.session.tentacle
        if not t:
            return ""
        return {"rpgmaker": "CDP", "renpy": "Frida", "twine": "HTTP+WS",
                "tyrano": "CDP"}.get(t.key, t.key)

    def _on_sb_client(self, connected: bool):
        self.status_bar.set_connected(connected,
                                      backend=self._backend_name())

    # ---------- офлайн-модели: проверка и загрузка ----------
    def _check_models_on_start(self):
        """Всплывающее окно: офлайн-модели не скачаны — предложить
        загрузку. Показывается при каждом старте, пока модели не будут
        установлены (иначе офлайн-перевод работать не будет)."""
        if not self.isVisible():   # модальный попап — только в реальном UI
            return
        engine = self.settings.value("engine", "honyaku")
        realtime = self.settings.value("engine_realtime", "honyaku")
        files = self.settings.value("engine_files", "honyaku")
        if not any(e in ("honyaku", "argos", "")
                   for e in (engine, realtime, files)):
            self.settings.setValue("setup_done", True)
            return
        try:
            from app.core.translate.engines import honyaku_missing_pairs_all
            missing = honyaku_missing_pairs_all()
        except Exception:  # noqa: BLE001
            self.settings.setValue("setup_done", True)
            return
        if not missing:
            self.settings.setValue("setup_done", True)
            return
        self._ask_download_models(missing)

    def _ask_download_models(self, missing):
        """Диалог «модели не скачаны»: Скачать / Позже."""
        pairs_text = ", ".join(f"{a}→{b}" for a, b in missing)
        from PySide6.QtWidgets import QMessageBox
        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Icon.Information)
        mb.setWindowTitle(TR("models_title"))
        mb.setText(TR("models_prompt", pairs=pairs_text))
        mb.setInformativeText(TR("models_prompt_size"))
        btn_yes = mb.addButton(TR("models_download"),
                               QMessageBox.ButtonRole.AcceptRole)
        mb.addButton(TR("models_later"),
                     QMessageBox.ButtonRole.RejectRole)
        mb.setDefaultButton(btn_yes)
        mb.exec()
        if mb.clickedButton() is btn_yes:
            self._download_models(missing)

    def _download_models(self, pairs):
        """Загрузка моделей с прогресс-диалогом (общая точка: стартовое
        окно и кнопка в настройках)."""
        if getattr(self, "_prefetch_thread", None) \
                and self._prefetch_thread.isRunning():
            return
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QProgressDialog
        dlg = QProgressDialog(TR("models_downloading"),
                              TR("models_cancel"), 0, len(pairs), self)
        dlg.setWindowTitle(TR("models_title"))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setMinimumWidth(420)
        worker = _ModelPrefetch(pairs)
        worker.setObjectName("HonyakuDownload")
        worker.progress.connect(
            lambda done, total, label: (
                dlg.setMaximum(max(total, 1)),
                dlg.setValue(done),
                dlg.setLabelText(
                    f"{TR('models_downloading')}\n{label} ({done}/{total})")))
        worker.status.connect(self.bridge_log)
        worker.finished.connect(self._on_models_finished)
        worker.finished.connect(worker.deleteLater)
        dlg.canceled.connect(worker.cancel)
        self._prefetch_thread = worker
        worker.start()
        dlg.exec()
        if dlg.wasCanceled():
            worker.cancel()

    def _on_models_progress(self, done: int, total: int, label: str):
        self.bridge_log.emit(f"[{done}/{total}] {label}")

    def _on_models_finished(self):
        from PySide6.QtWidgets import QMessageBox
        worker = self._prefetch_thread
        self._prefetch_thread = None
        if worker is None or worker.cancel_event.is_set():
            return
        try:
            from app.core.translate.engines import honyaku_missing_pairs_all
            if not honyaku_missing_pairs_all():
                self.settings.setValue("setup_done", True)
        except Exception:  # noqa: BLE001
            pass
        QMessageBox.information(self, TR("models_title"),
                                TR("models_done"))

    def _stop_workers(self):
        """Мягко останавливает фоновые QThread перед выходом —
        иначе QThread.destroy во время run() роняет процесс."""
        tt = self.translate_tab
        for worker, cancel in (
                (tt.worker, getattr(tt.worker.translator, "cancel", None)
                 if tt.worker else None),
                (tt.worker_correct,
                 getattr(tt.worker_correct.corrector, "cancel", None)
                 if tt.worker_correct else None),
                (getattr(self, "_extract_worker", None), None),
                (getattr(self, "_prefetch_thread", None), None),
                (getattr(self.cheat_tab, "_names_worker", None)
                 if self.cheat_tab else None, None)):
            if not worker:
                continue
            if cancel:
                cancel()
            worker.requestInterruption()
            if not worker.wait(3000):
                worker.terminate()
                worker.wait(1000)
        # вкладки движка: останавливаем их фоновые потоки
        for widget, _role in self._engine_tabs:
            cleanup = getattr(widget, "cleanup", None)
            if cleanup:
                try:
                    cleanup()
                except Exception:  # noqa: BLE001
                    pass

    def closeEvent(self, event):
        # крестик либо сворачивает в трей (настройка по умолчанию),
        # либо закрывает приложение — реальный выход всегда через трей
        close_to_tray = self.settings.value("close_to_tray", True, type=bool)
        if (not self._really_quit and close_to_tray
                and getattr(self, "tray", None)
                and self.tray.isVisible()):
            event.ignore()
            self.hide()
            self.tray.showMessage(TR("app_title"), TR("tray_minimized"),
                                  QSystemTrayIcon.MessageIcon.Information, 2000)
            return
        self._stop_workers()
        self.stop_session(kill_game=True)
        self.save_project()
        self.tm.close()
        super().closeEvent(event)
