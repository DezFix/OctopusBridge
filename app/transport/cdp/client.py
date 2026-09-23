# -*- coding: utf-8 -*-
"""Минимальный клиент Chrome DevTools Protocol.

Один WebSocket на цель (page target). Читает фреймы в фоновом потоке,
команды выполняются синхронно с таймаутом. События доменов вылетают
Qt-сигналом (потокобезопасно для GUI через queued connection).
"""
from __future__ import annotations

import json
import threading

from PySide6.QtCore import QObject, Signal

from websockets.sync.client import connect as _ws_connect

try:
    from websockets.exceptions import ConnectionClosed
except ImportError:  # очень старые websockets — падаем на общий Exception
    ConnectionClosed = Exception  # type: ignore[assignment,misc]


class CDPError(Exception):
    pass


def _ws_connect_compat(ws_url: str):
    """connect() с учётом разных версий websockets (13..16+):
    новые kwargs пробуем первыми, при TypeError — урезаем."""
    attempts = [
        {"open_timeout": 10, "max_size": 64 * 1024 * 1024,
         "ping_interval": 20, "close_timeout": 5, "compression": None},
        {"open_timeout": 10, "max_size": 64 * 1024 * 1024},
        {"open_timeout": 10},
        {},
    ]
    last: Exception | None = None
    for kw in attempts:
        try:
            return _ws_connect(ws_url, **kw)
        except TypeError as e:
            last = e
            if "unexpected keyword" not in str(e):
                raise
    raise last or CDPError("ws connect failed")


class CDPClient(QObject):
    #: событие домена: (method, params)
    event = Signal(str, dict)
    #: соединение закрыто (кем угодно)
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ws = None
        self._reader: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, dict] = {}
        self._pend_lock = threading.Lock()
        self.last_error = ""

    # ── соединение ──
    def connect(self, ws_url: str) -> bool:
        if self._ws:
            return True
        self.last_error = ""
        try:
            self._ws = _ws_connect_compat(ws_url)
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            self._ws = None
            return False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def close(self):
        # was_connected — только такой close роняет живое соединение:
        # именно он обязан крикнуть closed, иначе сессия навсегда
        # остаётся «Connected», а читы мертвы (таймаут call() гасил
        # _ws без сигнала — классика MZ-жалоб).
        ws, self._ws = self._ws, None
        reader, self._reader = self._reader, None
        was_connected = ws is not None
        if ws:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        with self._pend_lock:
            pend = list(self._pending.values())
            self._pending.clear()
        for p in pend:
            p["error"] = CDPError("connection closed")
            p["done"].set()
        # reader — daemon; долго GUI не блокируем, join только не из
        # самого reader-потока, с таймаутом 2с.
        if reader is not None and reader.is_alive():
            try:
                if threading.current_thread() is not reader:
                    reader.join(timeout=2.0)
            except Exception:  # noqa: BLE001
                pass
        if was_connected:
            try:
                self.closed.emit()
            except RuntimeError:
                pass

    def is_connected(self) -> bool:
        return self._ws is not None

    # ── команды ──
    def call(self, method: str, params: dict | None = None,
             timeout: float = 15.0) -> dict:
        ws = self._ws
        if not ws:
            raise CDPError("not connected")
        with self._pend_lock:
            mid = self._next_id
            self._next_id += 1
            slot = {"done": threading.Event(), "result": None, "error": None}
            self._pending[mid] = slot
        msg = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        try:
            with self._send_lock:
                ws.send(json.dumps(msg))
        except Exception as e:  # noqa: BLE001
            with self._pend_lock:
                self._pending.pop(mid, None)
            self.last_error = f"send failed: {e}"
            try:
                self.close()
            except Exception:  # noqa: BLE001
                pass
            raise CDPError(f"send failed: {e}") from e
        if not slot["done"].wait(timeout):
            with self._pend_lock:
                self._pending.pop(mid, None)
            self.last_error = f"timeout calling {method}"
            try:
                self.close()
            except Exception:  # noqa: BLE001
                pass
            raise CDPError(f"timeout calling {method}")
        if slot["error"]:
            raise slot["error"]
        return slot["result"] or {}

    # ── читатель ──
    def _read_loop(self):
        ws = self._ws
        try:
            for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if "id" in msg:
                    with self._pend_lock:
                        slot = self._pending.pop(msg["id"], None)
                    if slot:
                        if "error" in msg:
                            e = msg["error"]
                            slot["error"] = CDPError(
                                f"{e.get('message', e)} "
                                f"(code {e.get('code')})")
                        else:
                            slot["result"] = msg.get("result") or {}
                        slot["done"].set()
                else:
                    method = msg.get("method", "")
                    params = msg.get("params") or {}
                    try:
                        self.event.emit(method, params)
                    except RuntimeError:
                        pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            with self._pend_lock:
                pend = list(self._pending.values())
                self._pending.clear()
            for p in pend:
                p["error"] = CDPError("connection lost")
                p["done"].set()
            # closed — ровно один раз: только если обрыв обнаружил
            # reader (close() уже крикнул — не дублируем).
            lost = self._ws is ws
            if lost:
                self._ws = None
            try:
                if lost:
                    self.closed.emit()
            except RuntimeError:
                pass

    # ── удобства поверх Runtime ──
    def evaluate(self, expression: str, await_promise: bool = False,
                 timeout: float = 15.0):
        """Runtime.evaluate с returnByValue. Возвращает (ok, value)."""
        res = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        }, timeout=timeout)
        if "exceptionDetails" in res:
            ex = res["exceptionDetails"]
            text = ex.get("text", "JS exception")
            exc = ex.get("exception") or {}
            desc = exc.get("description") or exc.get("value") or ""
            return False, f"{text} {desc}".strip()
        remote = res.get("result") or {}
        return True, remote.get("value")
