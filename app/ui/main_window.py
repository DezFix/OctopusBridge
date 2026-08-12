# -*- coding: utf-8 -*-
"""Главное окно OctopusBridge — ядро + движковые модули.

До загрузки игры: приветственный экран (drag & drop).
После загрузки: дашборд на вкладке «Домой» + рабочие вкладки.
"""
from __future__ import annotations

import hashlib
import json
import os

from PySide6.QtCore import QSettings, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QMainWindow, QTabWidget, QSystemTrayIcon,
                               QMenu)

import app as app_paths
from app.core.session import GameSession
from app.core.tentacles import create_tentacle
from app.core.models import Project
from app.core.translate.engines import get_engine
from app.core.translate.glossary import Glossary
from app.core.translate.memory import TranslationMemory
from app.engines.registry import detect_engine
from app.ui.i18n import TR, provider_short_name, set_language
from app.ui.welcome_tab import WelcomeTab
from app.ui.projects_tab import ProjectsTab
from app.ui.translate_tab import TranslateTab

PROJECTS_DIR = app_paths.projects_dir()

_MAX_RECENT = 8

_TAB_ICON_COLOR = "#cdd6ff"

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


def _cleanup_legacy_settings(s: QSettings):
    """Чистит остатки удалённых движков и переводит старые настройки
    на актуальные провайдеры:
    - nllb / argos / honyaku (удалённый офлайн-переводчик) -> rotate;
    - engine_corrector 'nllb' -> 'ai'."""
    for key in s.allKeys():
        if key.startswith("nllb_gpu_") or key == "engine_nllb":
            s.remove(key)
    for key in ("engine_files", "engine_corrector"):
        if s.value(key) in ("nllb", "argos", "honyaku"):
            s.setValue(key, "ai" if key == "engine_corrector" else "rotate")


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


class MainWindow(QMainWindow):
    bridge_client = Signal(bool)
    bridge_state = Signal(str)
    bridge_vars = Signal(str)
    bridge_cheat_ack = Signal(str, bool, str, str)

    def __init__(self):
        super().__init__()
        self.settings = QSettings("OctopusBridge", "OctopusBridge")
        _migrate_qsettings(self.settings)
        _cleanup_legacy_settings(self.settings)
        set_language(self.settings.value("ui_lang", "en"))
        self._base_title = f"{TR('app_title')}  v{app_paths.__version__}"
        self.setWindowTitle(self._base_title)
        self.resize(1390, 755)
        saved_geo = self.settings.value("window_geometry")
        if saved_geo:
            self.restoreGeometry(saved_geo)
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
        self.session.state_received.connect(
            lambda d: self.bridge_state.emit(
                json.dumps(d, ensure_ascii=False)))
        self.session.vars_received.connect(
            lambda v: self.bridge_vars.emit(
                json.dumps(v, ensure_ascii=False)))
        self.session.cheat_ack.connect(self.bridge_cheat_ack)

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

        from app.ui.loading_overlay import LoadingOverlay
        self.loading = LoadingOverlay(central)

        self.bridge_client.connect(self._on_sb_client)
        self.refresh_status_bar()
        self.refresh_project_stats()

        from PySide6.QtCore import QTimer
        from app.ui.app_info import maybe_show_changelog
        QTimer.singleShot(900, lambda: maybe_show_changelog(self))

    def resizeEvent(self, event):
        if getattr(self, "loading", None):
            self.loading.setGeometry(self.rect())
        base = getattr(self, "_base_title", None)
        if base:
            self.setWindowTitle(f"{base} — {self.width()}×{self.height()}")
        super().resizeEvent(event)

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
        pass

    def _hide_work_tabs(self):
        pass

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
        # Оверлей появляется, только если открытие затянулось
        # (de-bounce 250 мс) — на быстрых проектах не мигает.
        from PySide6.QtCore import QTimer
        if getattr(self, "_open_proj_timer", None) is None:
            self._open_proj_timer = QTimer(self)
            self._open_proj_timer.setSingleShot(True)
            self._open_proj_timer.timeout.connect(
                lambda: self.loading.show_loading(TR("project_opening")))
        self._open_proj_timer.start(250)
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

        self._ask_extract_lang(module)
        self.refresh_all()

        self._add_recent(game_dir, engine)

        self._set_projects_tab_visible(False)
        self.tabs.setCurrentWidget(self.welcome_tab)

        self._open_proj_timer.stop()
        self.loading.hide_loading()

        if self.settings.value("auto_launch", False, type=bool) \
                and module and "cheats" in module.features:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, self.welcome_tab._action_launch_toggle)

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
        self.refresh_project_stats()
        for widget, _role in self._engine_tabs:
            hook = getattr(widget, "on_project_opened", None)
            if hook:
                hook()

    def refresh_project_stats(self):
        """Сводка проекта для нижнего статус-бара: done / draft / empty."""
        if not hasattr(self, "status_bar"):
            return
        done = draft = empty = total = 0
        if self.project:
            total = len(self.project.entries)
            for e in self.project.entries:
                if e.translation.strip():
                    if e.status == "skip":
                        draft += 1
                    else:
                        done += 1
                else:
                    empty += 1
        self.status_bar.update_project_stats(done, draft, empty, total)

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
        if engine_type == "corrector":
            name = s.value("engine_corrector",
                           s.value("engine_files", s.value("engine", "rotate")))
        else:
            name = s.value("engine_files", s.value("engine", "rotate"))
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
            return get_engine(name)
        except Exception:  # noqa: BLE001
            return None

    # ---------- фоновое извлечение текста ----------
    def _ask_extract_lang(self, module) -> None:
        """Многоязычная игра (Ren'Py tl/<lang>): предупредить и дать
        выбрать ОДИН язык, чтобы не переводить дубли по всем языкам."""
        p = self.project
        getter = getattr(module, "list_languages", None)
        if not getter or not p:
            return
        try:
            langs = getter(p.game_dir)
        except Exception:  # noqa: BLE001
            return
        if len(langs) < 2:
            return
        from app.ui.lang_dialog import LangPickDialog
        dlg = LangPickDialog(langs, p.extract_lang, self)
        if dlg.exec() == dlg.Accepted:
            p.extract_lang = dlg.selected_lang
            self.save_project()

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
        self._extract_worker = ExtractWorker(
            module, p.game_dir, getattr(p, "extract_lang", None))
        self.loading.show_loading(TR("tr_extracting"))

        def _finish(restored, error):
            self.loading.hide_loading()
            on_done(restored, error)

        self._extract_worker.done.connect(
            lambda entries: _finish(self._merge_extracted(entries), ""))
        self._extract_worker.failed.connect(lambda e: _finish(0, e))
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

    def start_session(self, target: str,
                      attach_pid: int | None = None,
                      port_hint: int = 0) -> bool:
        """Создаёт щупальце для текущего движка и подключает его к игре."""
        key = self.engine_module.key if self.engine_module else ""
        tentacle = create_tentacle(key)
        if tentacle is None:
            self.session.error.emit(TR("dash_session_unsupported"))
            return False
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
        return ok

    def stop_session(self, kill_game: bool = True):
        self.session.stop(kill_game=kill_game)
        if hasattr(self, "status_bar"):
            self.status_bar.set_connected(False)

    # ---------- статус-бар ----------
    def refresh_status_bar(self):
        """Обновляет провайдера и соединение в нижнем статус-баре."""
        if not hasattr(self, "status_bar"):
            return
        name = self.settings.value(
            "engine_files", self.settings.value("engine", "rotate"))
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
                (getattr(self.cheat_tab, "_names_worker", None)
                 if self.cheat_tab else None, None)):
            if not worker:
                continue
            try:
                if cancel:
                    cancel()
                worker.requestInterruption()
                if not worker.wait(3000):
                    worker.terminate()
                    worker.wait(1000)
            except RuntimeError:   # C++-объект уже удалён (deleteLater)
                pass
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
        self.settings.setValue("window_geometry", self.saveGeometry())
        self._stop_workers()
        self.stop_session(kill_game=True)
        self.save_project()
        self.tm.close()
        super().closeEvent(event)
