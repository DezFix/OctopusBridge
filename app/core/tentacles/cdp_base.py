# -*- coding: utf-8 -*-
"""CDP-щупальце — база для движков на Chromium (RPG Maker MV/MZ, Twine).

Транспорт «игра -> приложение»:
- основной: Runtime.addBinding -> Runtime.bindingCalled;
- запасной (древний NW.js RPG Maker MV, Chrome ~62): console.log с
  префиксом -> Runtime.consoleAPICalled.
Транспорт «приложение -> игра»: всегда Runtime.evaluate.

JS-пейлоад наследника может слать произвольные JSON-сообщения
(например, type: state / vars / cheat).
"""
from __future__ import annotations

import base64
import json
import time

from app.transport.cdp import browser
from app.transport.cdp.client import CDPClient, CDPError
from app.core.tentacles.base import Tentacle

BINDING_NAME = "__octopus_send"
CONSOLE_PREFIX = "__octopus__"

# Транспортная прослойка, встраиваемая в начало каждого пейлоада.
TRANSPORT_SHIM = r"""
// ── OctopusBridge transport shim ──
if (window.__octopus) { /* уже внедрено — повторную инъекцию игнорируем */ }
else {
window.__octopus = {};
const __ob_send = (window[""" + json.dumps(BINDING_NAME) + r"""])
  ? (o) => window[""" + json.dumps(BINDING_NAME) + r"""](JSON.stringify(o))
  : (o) => console.log(""" + json.dumps(CONSOLE_PREFIX) + r""" + JSON.stringify(o));
window.__octopus.send = __ob_send;
}
"""


class CDPTentacle(Tentacle):
    """Общая механика CDP: подключение к page-цели, инъекция, диспетчер."""

    PAYLOAD: str = ""          # JS наследника (после TRANSPORT_SHIM)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: CDPClient | None = None
        self._pid: int | None = None

    # ── подключение ──
    def connect_debugger(self, port: int, url_hint: str = "",
                         wait: float = 20.0) -> bool:
        """Публичная точка подключения к уже работающему отладчику
        (используется launch/attach наследников и тестами)."""
        return self._connect_page(port, url_hint, wait)

    def _connect_page(self, port: int, url_hint: str = "",
                      wait: float = 20.0) -> bool:
        self.log.emit(f"Жду отладчик на порту {port}…")
        if not browser.wait_for_debugger(port, timeout=wait):
            self.error.emit(f"Отладчик не отвечает на порту {port}.")
            return False
        # окно NW.js может пересоздаться при инициализации — цель из
        # первого снимка /json устаревает: несколько попыток со свежим
        # списком целей
        client = None
        last_err = "page-цель не найдена"
        for attempt in range(4):
            target = browser.pick_page_target(port, url_hint)
            if not target:
                last_err = "Не найдена page-цель отладчика."
                time.sleep(1.0)
                continue
            self.log.emit(f"Цель: {(target.get('url') or '')[:80]}")
            client = CDPClient()
            if client.connect(target["webSocketDebuggerUrl"]):
                break
            last_err = ("Не удалось подключиться к цели по WebSocket: "
                        + (client.last_error or "?"))
            self.log.emit(f"Попытка {attempt + 1}: {last_err}")
            client = None
            time.sleep(1.0)
        if client is None:
            self.error.emit(last_err)
            return False
        self._client = client
        client.event.connect(self._on_event)
        client.closed.connect(self._on_closed)
        try:
            client.call("Runtime.enable")
        except CDPError as e:
            self.log.emit(f"Runtime.enable: {e}")
        # binding — основной канал; на древних ядрах его нет, не страшно
        try:
            client.call("Runtime.addBinding", {"name": BINDING_NAME})
            self.log.emit("Канал: Runtime binding.")
        except CDPError:
            self.log.emit("addBinding недоступен — канал через console.")
        self._inject_payload()
        self.attached.emit()
        try:
            self._after_attach()
        except Exception:  # noqa: BLE001
            pass
        return True

    def _after_attach(self):
        """Хук для наследников: вызывается после успешной инъекции."""

    def _inject_payload(self):
        src = TRANSPORT_SHIM + "\n" + self.PAYLOAD
        # на будущие перезагрузки страницы (может не существовать на
        # старых ядрах — тогда просто инъекция в текущую страницу)
        try:
            self._client.call("Page.enable")
            self._client.call("Page.addScriptToEvaluateOnNewDocument",
                              {"source": src})
        except CDPError:
            pass
        ok, val = self._client.evaluate(src)
        if not ok:
            self.error.emit(f"Инъекция пейлоада не удалась: {val}")
        else:
            self.log.emit("Пейлоад внедрён в страницу игры.")

    # ── диспетчер событий CDP ──
    def _on_event(self, method: str, params: dict):
        if method == "Runtime.bindingCalled":
            if params.get("name") == BINDING_NAME:
                self._handle_raw_message(params.get("payload", ""))
        elif method == "Runtime.consoleAPICalled":
            for arg in params.get("args", []):
                val = arg.get("value")
                if isinstance(val, str) and val.startswith(CONSOLE_PREFIX):
                    self._handle_raw_message(val[len(CONSOLE_PREFIX):])
        elif method == "Inspector.targetCrashed":
            self.log.emit("Страница игры упала (targetCrashed).")
            self.detach()

    def _handle_raw_message(self, raw: str):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        mtype = msg.get("type")
        if mtype == "state":
            self.state_received.emit(msg)
        else:
            self._on_game_message(msg)

    def _on_game_message(self, msg: dict):
        """Точка расширения для наследников (свои типы сообщений)."""

    def _on_closed(self):
        self.log.emit("Соединение с отладчиком закрыто.")
        self.detach()

    # ── общий API ──
    def detach(self):
        client, self._client = self._client, None
        if client:
            client.close()
        self._pid = None
        self.detached.emit("")

    def is_attached(self) -> bool:
        return self._client is not None and self._client.is_connected()

    def game_pid(self) -> int | None:
        return self._pid

    def evaluate(self, expression: str, await_promise: bool = False,
                 timeout: float = 15.0):
        """Прямой eval в странице игры. (ok, value)"""
        if not self.is_attached():
            return False, "not attached"
        try:
            return self._client.evaluate(expression, await_promise,
                                         timeout=timeout)
        except CDPError as e:
            return False, str(e)

    def send_key(self, key: str, code: str = "", keyCode: int = 0,
                 windowsKeyCode: int = 0) -> bool:
        """Отправить нажатие клавиши в страницу игры через CDP Input."""
        if not self.is_attached():
            return False
        kc = keyCode or windowsKeyCode
        cmd_down = {"type": "keyDown", "key": key, "code": code,
                    "windowsVirtualKeyCode": kc, "nativeVirtualKeyCode": kc}
        cmd_up = {"type": "keyUp", "key": key, "code": code,
                  "windowsVirtualKeyCode": kc, "nativeVirtualKeyCode": kc}
        try:
            self._client.call("Input.dispatchKeyEvent", cmd_down)
            self._client.call("Input.dispatchKeyEvent", cmd_up)
            return True
        except CDPError:
            return False

    def screenshot(self) -> bytes | None:
        """PNG-скриншот страницы игры (Page.captureScreenshot) или None."""
        if not self.is_attached():
            return None
        try:
            res = self._client.call("Page.captureScreenshot",
                                    {"format": "png"})
        except CDPError:
            return None
        data = (res or {}).get("data")
        if not data:
            return None
        try:
            return base64.b64decode(data)
        except (ValueError, TypeError):
            return None
