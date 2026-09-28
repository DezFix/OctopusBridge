# -*- coding: utf-8 -*-
"""Главное окно OctopusBridge — ядро + движковые модули.

До загрузки игры: приветственный экран (drag & drop).
После загрузки: дашборд на вкладке «Домой» + рабочие вкладки.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QSettings, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow

import app as app_paths
from app.core import cache as app_cache
from app.live import create_tentacle
from app.live.session import GameSession
from app.core.models import Project
from app.core.translate.engines import GoogleFreeEngine
from app.core.translate.glossary import Glossary
from app.core.translate.memory import TranslationMemory
from app.engines.registry import detect_engine
from app.ui.i18n import TR, provider_short_name, set_language
from app.ui.welcome_tab import WelcomeTab
from app.ui.projects_tab import ProjectsTab
from app.ui.translate_tab import TranslateTab
from app.ui.theme import AnimatedTabWidget

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


class _ReconnectWorker(QThread):
    done = Signal(bool, object)

    def __init__(self, session, tentacle, parent=None):
        super().__init__(parent)
        self._session = session
        self.tentacle = tentacle
        self.wait_timeout = 5000

    def cancel(self):
        self.requestInterruption()
        if self.tentacle is not None:
            try:
                self.tentacle.detach()
            except Exception:  # noqa: BLE001
                pass

    def run(self):
        ok = False
        try:
            ok = bool(self._session.reconnect(start_watchdog=False))
        except Exception:  # noqa: BLE001
            ok = False
        self.done.emit(ok, self.tentacle)


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
    - ai / ollama / openai_compat / corrector / nllb / argos / honyaku /
      libretranslate (удалённые переводчики) -> rotate;
    - мусорные ключи удалённых эпох удаляются."""
    for key in s.allKeys():
        if key.startswith("nllb_gpu_") or key == "engine_nllb":
            s.remove(key)
    for key in ("engine_files", "engine_corrector", "engine"):
        if s.value(key) in ("ai", "ollama", "openai_compat", "corrector",
                            "nllb", "argos", "honyaku", "libretranslate"):
            s.setValue(key, "rotate")
    for key in ("engine_corrector", "base_url_corrector", "base_url_files",
                "api_key_corrector", "api_key_files", "model", "ollama_model",
                "glossary_use_ai"):
        s.remove(key)
    # системный трей убран из приложения — настройка больше не читается
    s.remove("close_to_tray")
    # светлая тема удалена (dark-only) — чистим остатки
    for _k in ("theme", "ui_theme", "theme_name", "color_theme"):
        s.remove(_k)


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
        set_language(self.settings.value("ui_lang", "ru"))
        self._base_title = f"{TR('app_title')}  v{app_paths.__version__}"
        self.setWindowTitle(self._base_title)
        self.resize(1390, 755)
        saved_geo = self.settings.value("window_geometry")
        if saved_geo:
            self.restoreGeometry(saved_geo)
        icon_path = app_paths.icon_path()
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        os.makedirs(PROJECTS_DIR, exist_ok=True)
        _migrate_project_files()
        app_paths.migrate_appdata()
        self._dedup_recent()
        self.tm = TranslationMemory(os.path.join(PROJECTS_DIR, "tm.sqlite"))
        self.glossary = Glossary(os.path.join(app_paths.glossary_dir(),
                                              "glossary.json"))
        self.project: Project | None = None
        self.session = GameSession(self)
        self._session_generation = 0
        self._session_operation = 0
        self._reconnect_worker: _ReconnectWorker | None = None
        # ретрансляция сигналов щупальца в сигналы главного окна
        self.session.attached.connect(
            lambda: self.bridge_client.emit(True))
        self.session.detached.connect(self._on_session_detached)
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
        self.tabs = AnimatedTabWidget()
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
        app_cache.maybe_auto_clean(self.settings)

    def resizeEvent(self, event):
        if getattr(self, "loading", None):
            self.loading.setGeometry(self.rect())
        super().resizeEvent(event)

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
            from app.ui.engine_tabs import build_tabs
            from app.ui.icons import icon
            try:
                tabs = build_tabs(module.key, self)
            except (KeyError, ValueError, ImportError):
                # неизвестный движок: legacy-фолбэк через модуль
                tabs = module.ui_tabs(self)
            for widget, title, role in tabs:
                ic = (_TAB_ROLE_ICONS.get(type(widget).__name__)
                      or _TAB_ROLE_ICONS.get(role))
                self.tabs.addTab(widget,
                                 icon(ic or "file-text", 18, _TAB_ICON_COLOR),
                                 title)
                self._engine_tabs.append((widget, role))
        self._show_work_tabs()

    # ---------- проект ----------
    def _project_file(self, game_dir: str) -> str:
        from app.core.models import project_file_for
        return project_file_for(game_dir)

    def open_project(self, game_dir: str) -> str:
        # Смена проекта во время фоновых работ теряет их результат
        # (воркер мутирует orphan-объекты старого p.entries).
        try:
            from app.ui.translate.helpers import (extract_busy,
                                                  translate_busy)
            tt = getattr(self, "translate_tab", None)
            if tt is not None and (translate_busy(tt)
                                   or extract_busy(tt)):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, TR("err"), TR("tr_translating"))
                p0 = getattr(self, "project", None)
                return getattr(p0, "engine", "unknown") if p0 else "unknown"
        except Exception:  # noqa: BLE001 — гард не должен мешать открытию
            pass
        # Сбрасываем отложенный автосейв вкладки перевода, иначе
        # ручные правки старого проекта потеряются вместе с объектом.
        try:
            tt = getattr(self, "translate_tab", None)
            flush = getattr(tt, "flush_save", None)
            if callable(flush):
                flush()
        except Exception:  # noqa: BLE001
            pass
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
        bak = pf + ".bak"
        if os.path.exists(pf):
            try:
                with open(pf, encoding="utf-8") as f:
                    self.project = Project.from_dict(json.load(f))
                self.project.engine = engine
            except json.JSONDecodeError:
                # Битая копия (обрыв записи): карантиним оригинал,
                # затем пробуем .bak и только потом пустой Project.
                try:
                    import time
                    ts = int(time.time())
                    corrupt = f"{pf}.corrupt-{ts}.json"
                    _i = 0
                    while os.path.exists(corrupt):
                        _i += 1
                        corrupt = f"{pf}.corrupt-{ts}-{_i}.json"
                    try:
                        os.replace(pf, corrupt)
                    except OSError:
                        try:
                            import shutil
                            shutil.copy2(pf, corrupt)
                            os.remove(pf)
                        except OSError:
                            pass
                except Exception:  # noqa: BLE001 — карантин best-effort
                    pass
                try:
                    with open(bak, encoding="utf-8") as f:
                        self.project = Project.from_dict(json.load(f))
                    self.project.engine = engine
                except (OSError, ValueError, KeyError, TypeError):
                    self.project = Project(game_dir=game_dir, engine=engine)
            except (OSError, KeyError, ValueError, TypeError,
                    UnicodeDecodeError):
                # Не JSON-обрыв (нет доступа/плохая схема): тоже пробуем
                # .bak для восстановления, иначе пустой Project.
                # Старые .ob.json читаются как раньше (from_dict
                # с defaults) — API не ломаем.
                try:
                    with open(bak, encoding="utf-8") as f:
                        self.project = Project.from_dict(json.load(f))
                    self.project.engine = engine
                except (OSError, ValueError, KeyError, TypeError):
                    self.project = Project(game_dir=game_dir, engine=engine)
        else:
            # pf нет — но .bak от прошлой установки мог уцелеть
            try:
                with open(bak, encoding="utf-8") as f:
                    self.project = Project.from_dict(json.load(f))
                self.project.engine = engine
            except (OSError, ValueError, KeyError, TypeError):
                self.project = Project(game_dir=game_dir, engine=engine)

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

        self._maybe_resume_translation()
        return engine

    def _maybe_resume_translation(self) -> None:
        """Предложить дотянуть незаконченный перевод (НЕ стартовать).

        Только если прошлый прогон реально не дошёл до конца
        (Project.tr_pending > 0 — провайдеры сели на лимите или сети не
        было). Не по факту «есть непереведённые строки»: они есть всегда.

        Автозапуск убран сознательно: человек, открывший игру ради
        читов, получал «перевожу» на весь экран без спроса, а оверлей
        висел без прогресса, пока шёл ping. Теперь — только строка
        в статусе вкладки «Перевод»: продолжение — одна кнопка,
        игнор — ничего не происходит.
        Отключается настройкой tr_autoresume.
        """
        if not self.settings.value("tr_autoresume", True, type=bool):
            return
        p = self.project
        if not p or not p.entries:
            return
        pending = getattr(p, "tr_pending", 0) or 0
        if pending <= 0:
            return
        tab = self.translate_tab
        if tab.worker and tab.worker.isRunning():
            return
        tab.notify_pending_resume(int(pending))

    def save_project(self):
        if not self.project:
            return
        pf = self._project_file(self.project.game_dir)
        bak = pf + ".bak"
        # Страховка: предыдущую целую копию — в .bak (битая поверх
        # хорошей никогда не пишется).
        try:
            if os.path.isfile(pf):
                try:
                    with open(pf, encoding="utf-8") as f:
                        json.load(f)  # проверка целостности
                except (OSError, ValueError):
                    pass  # pf битый — .bak не трогаем
                else:
                    try:
                        from app.core.io import atomic_write_bytes as _awb
                        with open(pf, "rb") as _src:
                            _awb(bak, _src.read())
                    except (OSError, ValueError):
                        pass
        except OSError:
            pass
        try:
            from app.core.io import atomic_write_json as _awj
            _awj(pf, self.project.to_dict())
        except (OSError, TypeError, ValueError):
            pass

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
                if (e.translation or "").strip():
                    if e.status == "skip":
                        draft += 1
                    else:
                        done += 1
                else:
                    empty += 1
        self.status_bar.update_project_stats(done, draft, empty, total)
        # Размер памяти переводов — рядом со сводкой («Память: {total}»).
        # Битая tm2 не роняет статистику.
        try:
            tm = getattr(self, "tm", None)
            if tm is not None:
                self.status_bar.set_memory(tm.stats().get("total", 0))
        except Exception:  # noqa: BLE001
            pass

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

    def _files_provider(self) -> str:
        # Движок один на всех (rotate-пул), выбора нет: старые значения
        # мигрируют при старте (см. _cleanup_legacy_settings).
        return "rotate"

    # ---------- движок перевода ----------
    def create_engine(self, engine_type: str = "files"):
        """Всегда единый rotate-пул: Google → Bing → MyMemory (с почтой).
        Параметр оставлен для совместимости вызовов."""
        s = self.settings
        try:
            from app.core.translate.engines import RotateEngine
            return RotateEngine(
                mymemory_email=s.value("mymemory_email", ""))
        except Exception:  # noqa: BLE001
            return None

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
        self._extract_worker = ExtractWorker(
            module, p.game_dir, getattr(p, "extract_lang", None))
        self.loading.show_loading(TR("tr_extracting"))

        def _finish(restored, error):
            self.loading.hide_loading()
            on_done(restored, error)

        self._extract_worker.done.connect(
            lambda entries: _finish(self._merge_extracted(entries), ""))
        self._extract_worker.failed.connect(lambda e: _finish(0, e))
        # Страховка от тихого прерывания: ExtractWorker при
        # requestInterruption выходит без done/failed (например, на
        # выходе из приложения) — оверлей иначе висит навсегда.
        # hide_loading идемпотентен: на штатном пути уже спрятан.
        self._extract_worker.finished.connect(
            lambda: self.loading.hide_loading())
        self._extract_worker.start()
        return True

    def _merge_extracted(self, new_entries) -> int:
        """Сливает свежее извлечение с переводами проекта (восстановление
        по ключу и по тексту). Возвращает число восстановленных."""
        p = self.project
        old_by_key = {(e.file, e.json_path): (e.translation, e.status)
                      for e in p.entries if (e.translation or "").strip()}
        old_by_text = {e.original: (e.translation, e.status)
                       for e in p.entries if (e.translation or "").strip()}
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
        if t is None:
            return None
        try:
            return t if t.is_attached() else None
        except Exception:  # noqa: BLE001
            return None

    def ensure_channel(self):
        t = self.channel()
        if t is not None:
            return t
        if not self.session.is_game_running():
            return None
        worker = self._reconnect_worker
        if worker is not None:
            try:
                if worker.isRunning():
                    return None
            except RuntimeError:
                self._reconnect_worker = None
        tentacle = self.session.tentacle
        if tentacle is None:
            return None
        self._reconnect_worker = _ReconnectWorker(
            self.session, tentacle, self)
        self._reconnect_worker.done.connect(self._on_reconnect_done)
        self._reconnect_worker.finished.connect(
            self._reconnect_worker.deleteLater)
        self._reconnect_worker.start()
        return None

    def _on_session_detached(self, _reason: str = ""):
        self.bridge_client.emit(False)
        if self.session.tentacle is None:
            return
        if not self.session.is_game_running() or self.is_reconnecting():
            return
        QTimer.singleShot(250, self.ensure_channel)

    def is_reconnecting(self) -> bool:
        worker = self._reconnect_worker
        if worker is None:
            return False
        try:
            return bool(worker.isRunning())
        except RuntimeError:
            return False

    def _on_reconnect_done(self, ok: bool, tentacle):
        if tentacle is not self.session.tentacle:
            return
        if ok:
            self.session.start_watchdog()
            self.refresh_status_bar()
        elif not self.session.is_game_running():
            self.bridge_client.emit(False)

    def channel_diag(self) -> str:
        """Одна строка диагностики «почему нет канала» для диалогов.

        Статус-бар мог остаться «Connected», а канал уже мёртв
        (тихий разрыв) — тут видно расхождение сразу.
        """
        try:
            t = self.session.tentacle
            has = t is not None
            att = bool(t and t.is_attached())
            pid = None
            try:
                pid = t.game_pid() if t else None
            except Exception:  # noqa: BLE001
                pid = None
            alive = None
            if pid:
                try:
                    from app.core import process as _proc
                    alive = bool(_proc.pid_exists(pid))
                except Exception:  # noqa: BLE001
                    alive = None
            return (f"tentacle={type(t).__name__ if has else None} "
                    f"attached={att} pid={pid} alive={alive}")
        except Exception as e:  # noqa: BLE001
            return f"diag-error: {e}"

    def _live_translate(self, texts: list, lang_from: str,
                        lang_to: str) -> list:
        """Live-перевод текстов игры (простой бесплатный плагин).

        Вызывается из потоков WS-сервера щупальца Twine. Переводим
        встроенным бесплатным Google Translate (без ключа, без настроек
        пользователя — движки для файлов тут не участвуют). Кешируем
        движок/переводчика на время сессии; при любой ошибке щупальце
        покажет причину в панели игры через tr_status, текст останется
        оригиналом.
        """
        translator = getattr(self, "_live_translator", None)
        if translator is None \
                or getattr(translator, "engine", None).__class__ \
                is not GoogleFreeEngine:
            from app.core.translate.service import Translator
            translator = Translator(GoogleFreeEngine(), tm=self.tm,
                                    glossary=self.glossary)
            self._live_translator = translator
        return translator.translate_texts(list(texts),
                                          lang_from, lang_to)

    def _new_tentacle(self, port_hint: int = 0):
        key = self.engine_module.key if self.engine_module else ""
        tentacle = create_tentacle(key)
        if tentacle is None:
            self.session.error.emit(TR("dash_session_unsupported"))
            return None
        tentacle.setParent(self)
        if port_hint and hasattr(tentacle, "set_port_hint"):
            tentacle.set_port_hint(port_hint)
        if key == "twine":
            tentacle.set_tr_callback(self._live_translate)
        return tentacle

    def prepare_session(self, target: str, port_hint: int = 0,
                        generation: int | None = None):
        if generation is not None and generation != self._session_generation:
            return None
        self._session_operation += 1
        operation = self._session_operation
        tentacle = self._new_tentacle(port_hint)
        if tentacle is None:
            return None
        self.session.begin_pending(tentacle)
        return tentacle, operation

    def finish_session(self, tentacle, ok: bool, operation: int,
                       generation: int, attach_pid: int | None = None):
        current = (generation == self._session_generation
                   and operation == self._session_operation)
        if not current:
            self.session.discard(tentacle)
            return False
        if attach_pid is not None:
            ok = self.session.finish_attach(tentacle, attach_pid, ok)
        else:
            ok = self.session.finish_launch(tentacle, ok)
        if not ok:
            self.status_bar.set_connected(False)
        return ok

    def start_session(self, target: str,
                      attach_pid: int | None = None,
                      port_hint: int = 0,
                      generation: int | None = None) -> bool:
        """Создаёт щупальце для текущего движка и подключает его к игре."""
        current_generation = self._session_generation
        if generation is not None and generation != current_generation:
            return False
        self._session_operation += 1
        operation = self._session_operation

        def current() -> bool:
            return (generation is None
                    or generation == self._session_generation) and \
                operation == self._session_operation

        tentacle = self._new_tentacle(port_hint)
        if tentacle is None:
            return False
        if attach_pid is not None:
            ok = self.session.attach(tentacle, attach_pid, guard=current)
        else:
            ok = self.session.launch(tentacle, target, guard=current)
        if not ok and current():
            self.status_bar.set_connected(False)
        return ok

    def stop_session(self, kill_game: bool = True):
        self._session_generation += 1
        self._session_operation += 1
        worker = self._reconnect_worker
        if worker is not None:
            try:
                worker.cancel()
            except RuntimeError:
                pass
        self.session.stop(kill_game=kill_game)
        if hasattr(self, "status_bar"):
            self.status_bar.set_connected(False)

    # ---------- статус-бар ----------
    def refresh_status_bar(self):
        """Обновляет провайдера и соединение в нижнем статус-баре."""
        if not hasattr(self, "status_bar"):
            return
        name = self._files_provider()
        self.status_bar.set_provider(provider_short_name(name))
        self.status_bar.set_connected(self.session.is_active(),
                                      backend=self._backend_name())

    def _backend_name(self) -> str:
        t = self.session.tentacle
        if not t:
            return ""
        return {"rpgmaker": "CDP", "renpy": "Frida", "twine": "HTTP+WS",
                "tyrano": "CDP", "wolf": "EXE"}.get(t.key, t.key)

    def _on_sb_client(self, connected: bool):
        self.status_bar.set_connected(connected,
                                      backend=self._backend_name())

    def _stop_workers(self):
        """Мягко останавливает фоновые QThread перед выходом.

        Только cooperative отмена: translator.cancel() +
        worker.cancel()/requestInterruption() + wait(800) max.
        Никакого terminate(): он убивает поток посреди C-кода
        (requests/SSL/sqlite) и роняет весь процесс с AV до сохранения.
        Не дождавшийся поток завершится сам и удалится по
        finished->deleteLater."""
        tt = self.translate_tab
        for worker, cancel in (
                (tt.worker, getattr(tt.worker.translator, "cancel", None)
                 if tt.worker else None),
                (getattr(self, "_extract_worker", None), None),
                (getattr(getattr(self, "welcome_tab", None),
                         "_launch_worker", None), None),
                (getattr(self, "_reconnect_worker", None), None),
                (getattr(self.cheat_tab, "_names_worker", None)
                 if self.cheat_tab else None, None)):
            if not worker:
                continue
            try:
                if cancel:
                    try:
                        cancel()
                    except Exception:  # noqa: BLE001
                        pass
                worker_cancel = getattr(worker, "cancel", None)
                if callable(worker_cancel):
                    try:
                        worker_cancel()
                    except Exception:  # noqa: BLE001
                        pass
                worker.requestInterruption()
                try:
                    worker.finished.connect(worker.deleteLater)
                except Exception:  # noqa: BLE001, RuntimeError
                    pass
                worker.wait(getattr(worker, "wait_timeout", 800))
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
        # закрытие окна = выход из приложения
        self.settings.setValue("window_geometry", self.saveGeometry())
        # сохраняем проект ДО остановки воркеров: даже если при выходе
        # что-то упадёт, переведённое останется на диске
        self.save_project()
        self.stop_session(kill_game=True)
        self._stop_workers()
        self.save_project()
        self.tm.close()
        super().closeEvent(event)
