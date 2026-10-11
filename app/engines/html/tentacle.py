# -*- coding: utf-8 -*-
"""HtmlTentacle — live-оверлей для обычных HTML-игр (без движкового API).

Транспорт переиспользует Twine (HTTP-инжекция + WebSocket), перевод —
тот же GENERIC DOM-механизм (TR_SCRIPT импортирован БЕЗ ИЗМЕНЕНИЙ:
TreeWalker + MutationObserver поверх text nodeValue). SugarCube-куски
TR_SCRIPT (ре-триггер :passagedisplay) на обычных страницах просто не
срабатывают: обёрнуты в try/except + typeof-гварды.

PAYLOAD_SCRIPT Twine переиспользован как есть (инжекция — в базовом
хендлере): все обращения к State/Harlowe/Save/$ закрыты typeof-гвардами
(проверено ассертами ниже), на страницах без SugarCube/jQuery/Save он
молча шлёт пустое состояние + live-перевод, исключений нет.

Отличия от TwineTentacle:
- нет синка сейвов (Save API может отсутствовать): _save_sync_cb
  не выставляется, /api/saves отвечает 404;
- нет читов (игрового API нет): set_variable/send_cheat не поддерживаем
  (базовые возвращают False), ветка cheat_ack из протокола убрана.
"""
from __future__ import annotations

import os
import threading
import time
import webbrowser
import zlib
from urllib.parse import quote

from app.live.tentacle import Tentacle
from app.core.translate.service import build_tr_dict  # noqa: F401 — реэкспорт
from app.engines.twine.tentacle import (
    PAYLOAD_SCRIPT,
    TR_SCRIPT,
    _InjectingHTTPHandler,
    _ThreadedHTTPServer,
    _WSServer,
    _find_free_port,
    load_tr_dict,
)

# PAYLOAD обязан быть exception-safe на страницах без SugarCube/jQuery:
# State/Harlowe/Save/$ — только через typeof. TR_SCRIPT — generic DOM
# (TreeWalker/MutationObserver) + опциональные SugarCube-триггеры.
for _needle in ("typeof State", "typeof Save", "typeof $"):
    assert _needle in PAYLOAD_SCRIPT, _needle
for _needle in ("tr_request", "tr_result", "MutationObserver"):
    assert _needle in TR_SCRIPT, _needle
del _needle


class _HtmlHTTPHandler(_InjectingHTTPHandler):
    """Тот же инжектор Twine (PAYLOAD+TR в .html), но без синка сейвов."""

    def do_POST(self):
        """Сейв-синка нет: любой POST — 404 (плагин окна сейвы не шлёт)."""
        self.send_error(404)


def find_html(target: str) -> str | None:
    """Стартовый .html: файл напрямую, иначе index.html корня, иначе
    первый .html корня, иначе то же на уровень вглубь (case-insensitive)."""
    if os.path.isfile(target) and target.lower().endswith((".html", ".htm")):
        return target
    if not os.path.isdir(target):
        return None
    try:
        entries = sorted(os.listdir(target))
    except OSError:
        return None
    for f in entries:
        if f.lower() in ("index.html", "index.htm"):
            p = os.path.join(target, f)
            if os.path.isfile(p):
                return p
    for f in entries:
        if f.lower().endswith((".html", ".htm")):
            p = os.path.join(target, f)
            if os.path.isfile(p):
                return p
    for f in entries:
        sub = os.path.join(target, f)
        if not os.path.isdir(sub):
            continue
        try:
            sub_entries = sorted(os.listdir(sub))
        except OSError:
            continue
        for sf in sub_entries:
            if sf.lower() in ("index.html", "index.htm"):
                p = os.path.join(sub, sf)
                if os.path.isfile(p):
                    return p
        for sf in sub_entries:
            if sf.lower().endswith((".html", ".htm")):
                p = os.path.join(sub, sf)
                if os.path.isfile(p):
                    return p
    return None


class HtmlTentacle(Tentacle):
    key = "html"
    title = "HTML (HTTP+WS)"

    def __init__(self, parent=None, use_webapp_window: bool = True):
        super().__init__(parent)
        self._use_webapp_window = use_webapp_window
        if os.environ.get("OCTOPUS_BROWSER_MODE"):
            self._use_webapp_window = False
        self._game_path: str = ""
        self._game_dir: str = ""
        self._httpd: _ThreadedHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._ws_server: _WSServer | None = None
        self._http_port = 0
        self._port_hint = 0               # фиксированный порт (опционально)
        self._webapp_proc = None          # процесс окна WebView2 (webapp-режим)
        self._tr_dict: dict = {}          # словарь live-перевода (проект)
        self._tr_state: dict = {          # состояние live-перевода
            "from": "auto", "to": "ru", "enabled": True}
        self._tr_cb = self._default_tr_cb   # переводчик: бесплатный Google
        self._tr_lock = threading.Lock()  # один перевод в момент времени
        self._tr_last_status: str | None = None  # последний статус провайдера
        self._tr_default_translator = None  # Translator (лентяй-создание)

    def set_port_hint(self, port: int):
        """Зафиксировать порт HTTP-сервера (стабильный origin браузера)."""
        self._port_hint = int(port or 0)

    def _game_port(self) -> int:
        """Детерминированный порт по пути игры (как у Twine).

        localStorage привязан к origin (host:port): один и тот же порт
        для одной игры между запусками = те же данные. Разные игры —
        разные порты.
        """
        if self._port_hint:
            return self._port_hint
        crc = zlib.crc32(self._game_path.encode("utf-8", "replace"))
        return 6000 + (crc % 1000)

    # ── Запуск ──
    def launch(self, target: str) -> bool:
        if os.path.isdir(target):
            story = find_html(target)
            if not story:
                self.error.emit("HTML-игра не найдена (нет .html).")
                return False
            self._game_path = story
            self._game_dir = target
        else:
            self._game_path = target
            self._game_dir = os.path.dirname(target)

        if not os.path.isfile(self._game_path):
            self.error.emit(f"Файл игры не найден: {self._game_path}")
            return False

        # Live-перевод: словарь из проекта .ob.json уходит в игру
        # по WebSocket (tr_dict) при подключении страницы.
        self._tr_dict = load_tr_dict(self._game_dir)
        if self._tr_dict:
            self.log.emit(
                f"Live-перевод: {len(self._tr_dict)} строк из проекта.")

        rel = os.path.relpath(self._game_path, self._game_dir)
        rel = rel.replace("\\", "/")

        if not self._start_http(rel):
            return False

        if not self._start_ws():
            return False
        ws_url = f"ws://127.0.0.1:{self._ws_server.port}"
        _HtmlHTTPHandler._ws_url = ws_url
        _HtmlHTTPHandler._game_html_rel = rel

        if self._use_webapp_window:
            return self._launch_webapp(rel)

        _HtmlHTTPHandler._inject_html = True
        _HtmlHTTPHandler._shield_html = False

        url = f"http://127.0.0.1:{self._http_port}/{quote(rel, safe='/')}"
        self.log.emit(f"Игра: {url}")
        self.log.emit(f"WebSocket: {ws_url}")

        try:
            webbrowser.open(url)
            self.log.emit("Браузер по умолчанию открыт.")
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"webbrowser.open: {e}")
            self.log.emit(f"Откройте вручную: {url}")

        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if self._ws_server and self._ws_server.has_client():
                self.log.emit("Игра подключена по WebSocket.")
                self.attached.emit()
                return True
            time.sleep(0.3)

        self.error.emit("Игра не подключилась по WebSocket за 60с.")
        self.detach()
        return False

    def _launch_webapp(self, rel: str) -> bool:
        """WebView2-режим: обёртка ставится в папку игры
        (octopus_htmlapp/) и раздаётся этим же HTTP-сервером, игра
        открывается в окне приложения. Мост (состояние, live-перевод)
        работает через WebSocket — как в браузере."""
        from app.engines.html import webapp as _webapp

        _HtmlHTTPHandler._inject_html = False
        _HtmlHTTPHandler._shield_html = True
        _HtmlHTTPHandler._game_html_rel = rel
        self._close_webapp_window()
        title = _webapp.game_title(self._game_path)
        wrapper_rel = _webapp.install_webapp(self._game_dir, rel, title)
        url = f"http://127.0.0.1:{self._http_port}/{wrapper_rel}"
        profile = _webapp.profile_dir_for(self._game_path)
        self.log.emit(f"Веб-приложение: {url}")
        proc = _webapp.open_game_window(_webapp.APP_TITLE, url, profile)
        if proc is not None:
            self._webapp_proc = proc
            self.log.emit("Окно приложения открыто (WebView2).")
        else:
            self.log.emit(f"Откройте вручную: {url}")
        self.attached.emit()
        return True

    def _close_webapp_window(self):
        """Закрывает окно WebView2, если оно запущено."""
        if self._webapp_proc is not None:
            proc = self._webapp_proc
            self._webapp_proc = None
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:  # noqa: BLE001 — уже умерло
                    pass

    def attach(self, pid: int) -> bool:
        self.error.emit("attach через PID не поддерживается — "
                        "запускайте игру через Launch.")
        return False

    def detach(self):
        self._close_webapp_window()
        self._stop_ws()
        self._stop_http()
        self._pid = None
        self.detached.emit("")

    def is_attached(self) -> bool:
        if self._use_webapp_window:
            # webapp-режим: прикреплены, пока живо окно приложения
            return (self._webapp_proc is not None
                    and self._webapp_proc.poll() is None)
        return self._ws_server is not None and self._ws_server.has_client()

    def game_pid(self) -> int | None:
        return None  # браузер не наш процесс

    # ── HTTP ──
    def _start_http(self, game_html_rel: str) -> bool:
        handler = _HtmlHTTPHandler
        handler._game_html_rel = game_html_rel
        handler.directory = self._game_dir
        port = self._game_port()
        try:
            self._httpd = _ThreadedHTTPServer(("127.0.0.1", port), handler)
        except OSError:
            port = _find_free_port()
            try:
                self._httpd = _ThreadedHTTPServer(
                    ("127.0.0.1", port), handler)
            except OSError as e:
                self.error.emit(f"HTTP-сервер не запустился: {e}")
                return False
            self.log.emit(
                f"Порт {self._game_port()} занят — используется {port}.")
        self._http_port = port
        self._http_thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True)
        self._http_thread.start()
        self.log.emit(f"HTTP-сервер: 127.0.0.1:{port}")
        return True

    def _stop_http(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self._http_thread = None

    # ── WebSocket ──
    def _ws_port_hint(self) -> int:
        """Детерминированный порт моста: 7000 + crc(путь игры) % 1000.

        Диапазон 7000-7999 не пересекается с HTTP-портами (6000-6999).
        """
        if self._game_path:
            crc = zlib.crc32(self._game_path.encode("utf-8", "replace"))
            return 7000 + (crc % 1000)
        return 0

    def _start_ws(self) -> bool:
        self._ws_server = _WSServer(
            self._on_ws_message,
            self._on_ws_connect,
            lambda: self.log.emit("WebSocket: клиент отключился"),
            port_hint=self._ws_port_hint())
        if not self._ws_server.start():
            self.error.emit("WebSocket-сервер не запустился.")
            self._ws_server = None
            return False
        if self._ws_server.port != self._ws_port_hint():
            self.log.emit(
                f"WebSocket: порт {self._ws_server.port} (детерминированный "
                f"{self._ws_port_hint()} занят)")
        return True

    def _stop_ws(self):
        if self._ws_server:
            self._ws_server.stop()
            self._ws_server = None

    # ── Обработка сообщений из игры ──
    def _on_ws_connect(self):
        self.log.emit("WebSocket: клиент подключился")
        # Состояние live-перевода и словарь проекта передаём при каждом
        # подключении — перезагрузка страницы их сбрасывает.
        if not self._ws_server:
            return
        st = self._tr_state
        self._ws_server.send({"type": "tr_set", "enabled": st["enabled"],
                              "from": st["from"], "to": st["to"]})
        if self._tr_dict:
            self._ws_server.send({"type": "tr_dict", "data": self._tr_dict})

    def _on_ws_message(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "state":
            self.state_received.emit(msg)
        elif mtype == "vars":
            self.vars_received.emit(msg.get("variables") or [])
        elif mtype == "tr_state":
            # Пользователь поменял языки/вкл-выкл прямо в игре — запоминаем,
            # чтобы при переподключении страницы tr_set вернул тот же выбор.
            st = self._tr_state
            st["enabled"] = bool(msg.get("enabled", st["enabled"]))
            st["from"] = str(msg.get("from") or st["from"])
            st["to"] = str(msg.get("to") or st["to"])
        elif mtype == "tr_request":
            self._on_tr_request(msg)

    # ── Live-перевод ──
    def _on_tr_request(self, msg: dict):
        """Батч видимого текста игры → провайдер приложения → tr_result.

        Вызывается из потоков WS-пула; колбэк сериализуется локом.
        Сбой провайдера — отвечаем оригиналами и один раз сообщаем
        странице причину (tr_status).
        """
        texts = msg.get("texts") or []
        if not isinstance(texts, list):
            texts = []
        results = list(texts)
        cb = self._tr_cb
        if cb and texts:
            try:
                with self._tr_lock:
                    results = cb(list(texts),
                                 str(msg.get("lang_from", "auto")),
                                 str(msg.get("lang_to", "ru")))
                if len(results) != len(texts):
                    results = list(texts)
                self._send_tr_status(None)
            except Exception as e:  # noqa: BLE001 — провайдер упал
                results = list(texts)
                self._send_tr_status(f"Провайдер перевода недоступен: {e}")
        else:
            self._send_tr_status("Движок перевода не настроен (настройки)")
        if self._ws_server:
            self._ws_server.send({
                "type": "tr_result",
                "id": msg.get("id"),
                "results": results})

    def _send_tr_status(self, msg: str | None) -> None:
        """Шлёт странице статус провайдера (однажды на изменение)."""
        if msg == self._tr_last_status:
            return
        self._tr_last_status = msg
        if self._ws_server:
            self._ws_server.send({"type": "tr_status", "msg": msg})

    def _default_tr_cb(self, texts: list, lang_from: str,
                       lang_to: str) -> list:
        """Переводчик по умолчанию: встроенный бесплатный Google Translate."""
        translator = self._tr_default_translator
        if translator is None:
            from app.core.translate.engines import GoogleFreeEngine
            from app.core.translate.service import Translator
            translator = Translator(GoogleFreeEngine())
            self._tr_default_translator = translator
        return translator.translate_texts(list(texts), lang_from, lang_to)

    def set_tr_callback(self, cb) -> None:
        """Колбэк автоперевода текстов игры (вызывается из потоков WS):
        cb(texts: list[str], lang_from: str, lang_to: str) -> list[str].
        Возвращает ровно столько же строк; None — вернуть переводчик
        по умолчанию (бесплатный Google)."""
        self._tr_cb = cb or self._default_tr_cb

    def set_tr_state(self, lang_from: str, lang_to: str,
                     enabled: bool) -> None:
        """Языки и вкл/выкл live-перевода из панели приложения."""
        st = self._tr_state
        st["from"] = lang_from or "auto"
        st["to"] = lang_to or "ru"
        st["enabled"] = bool(enabled)
        if self._ws_server and self._ws_server.has_client():
            self._ws_server.send({"type": "tr_set",
                                  "enabled": st["enabled"],
                                  "from": st["from"], "to": st["to"]})

    def tr_state(self) -> dict:
        """Текущее состояние live-перевода (для панели приложения)."""
        return dict(self._tr_state)

    # ── Состояние ──
    def request_state(self) -> bool:
        if not self._ws_server:
            return False
        return self._ws_server.send({"type": "get_state"})

    def request_vars(self) -> bool:
        if not self._ws_server:
            return False
        return self._ws_server.send({"type": "get_vars"})

    def push_tr_dict(self, entries) -> bool:
        """Обновить словарь live-перевода (новые переводы в проекте)."""
        self._tr_dict = build_tr_dict(entries)
        if self._ws_server and self._ws_server.has_client():
            return self._ws_server.send({
                "type": "tr_dict", "data": self._tr_dict})
        return False
