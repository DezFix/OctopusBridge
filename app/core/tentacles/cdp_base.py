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
import os
import time
from typing import Callable

from app.core import process as proc
from app.transport.cdp import browser
from app.transport.cdp.client import CDPClient, CDPError
from app.core.tentacles.base import Tentacle
from app.core.translate.service import build_tr_dict  # noqa: F401 — реэкспорт

BINDING_NAME = "__octopus_send"
CONSOLE_PREFIX = "__octopus__"

# Кандидаты портов для сканирования CDP (общие для NW.js/Electron-игр).
# Per-engine SCAN_PORTS-константы в наследниках — алиасы этого списка
# (оставлены для совместимости импортов).
DEFAULT_SCAN_PORTS = [9222, 9229, 9333] + list(range(9000, 9101)) + \
    list(range(26000, 26051))


def probe_game_port(pid: int, ports=None,
                    check: Callable[[int, int], bool] | None = None) -> int:
    """Порт CDP-отладчика процесса pid.

    Порядок: --remote-debugging-port из cmdline -> DevToolsActivePort
    -> брутфорс SCAN_PORTS с per-engine предикатом check(port, pid).
    Без check брутфорс не подтверждает принадлежность (возвращает 0,
    чтобы не подцепить чужой Chromium).
    """
    exe = proc.exe_of(pid)
    game_dir = os.path.dirname(exe) if exe else ""
    port = proc.debug_port_from_cmdline(proc.cmdline_of(pid))
    if port:
        return port
    port = browser.port_from_devtools_file(exe, game_dir)
    if port:
        return port
    return bruteforce_port(pid, ports=ports, check=check)


def bruteforce_port(pid: int | None = None, ports=None,
                    check: Callable[[int, int], bool] | None = None) -> int:
    """Перебор живых CDP-портов; первый прошедший check(port, pid).

    check is None — чужой порт подтвердить нечем, возвращаем 0.
    """
    if check is None:
        return 0
    candidates = browser.scan_ports(ports or DEFAULT_SCAN_PORTS)
    if not candidates:
        time.sleep(2.0)
        candidates = browser.scan_ports(ports or DEFAULT_SCAN_PORTS)
    for port in candidates:
        try:
            if check(port, pid):
                return port
        except Exception:  # noqa: BLE001 — битый порт, идём дальше
            continue
    return 0


def cdp_page_is_game(port: int, pid: int | None, probe_js: str,
                     engine_key: str = "") -> bool:
    """Общая проверка CDP-порта: page-цель + probe-JS + принадлежность pid.

    Per-engine предикаты (_port_is_rpgm_game, _port_is_tyrano) — тонкие
    обёртки над этой функцией: отличаются только probe_js и engine_key.
    SCAN_PORTS остаются per-engine (алиасы DEFAULT_SCAN_PORTS).
    """
    target = browser.pick_page_target(port, ".html")
    if not target:
        return False
    client = CDPClient()
    if not client.connect(target["webSocketDebuggerUrl"]):
        return False
    try:
        client.call("Runtime.enable")
        ok, val = client.evaluate(probe_js)
        if not (ok and val is True):
            return False
        try:
            info = client.call("SystemInfo.getProcessInfo", timeout=3)
            procs = info.get("processInfo") or []
            browser_pid = next((p.get("id") for p in procs
                                if p.get("type") == "browser"), None)
            if browser_pid is not None:
                return pid is not None and int(browser_pid) == int(pid)
        except CDPError:
            pass
        if engine_key:
            # Без точного browser-pid: не цепляем чужой Chromium, когда
            # рядом несколько игр одного движка.
            return len(proc.find_game_processes(engine_key)) <= 1
        return True
    except CDPError:
        return False
    finally:
        client.close()

# Транспортная прослойка, встраиваемая в начало каждого пейлоада.
# ES5-only: старые NW.js (RPG Maker MV, Chromium 41-49) не знают
# const/let/стрелки — SyntaxError здесь ронял бы всю инъекцию.
TRANSPORT_SHIM = r"""
// ── OctopusBridge transport shim (ES5) ──
(function () {
  var BINDING = """ + json.dumps(BINDING_NAME) + r""";
  var PREFIX = """ + json.dumps(CONSOLE_PREFIX) + r""";
  window.__octopus = window.__octopus || {};
  function obSend(o) {
    var s = null;
    try { s = JSON.stringify(o); } catch (e) { return; }
    try {
      if (window[BINDING]) { window[BINDING](s); return; }
    } catch (e) {}
    try { console.log(PREFIX + s); } catch (e2) {}
  }
  // CDP-канал всегда перекрывает заглушку моста (mv_bridge ставит
  // пустой send) — иначе state/cheat сообщения теряются, когда в игре
  // есть и мост, и CDP (SDK-сборки MV).
  window.__octopus.send = obSend;
})();
"""


class CDPTentacle(Tentacle):
    """Общая механика CDP: подключение к page-цели, инъекция, диспетчер."""

    PAYLOAD: str = ""          # JS наследника (после TRANSPORT_SHIM)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: CDPClient | None = None
        self._pid: int | None = None
        self._script_id: str | None = None
        self._detaching: bool = False

    def _sleep_retry(self) -> bool:
        """Пауза 1с кусочками 5x0.2; False если попросили detach."""
        for _ in range(5):
            if self._detaching:
                return False
            time.sleep(0.2)
        return True

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
                if not self._sleep_retry():
                    return False
                continue
            self.log.emit(f"Цель: {(target.get('url') or '')[:80]}")
            client = CDPClient()
            if client.connect(target["webSocketDebuggerUrl"]):
                break
            last_err = ("Не удалось подключиться к цели по WebSocket: "
                        + (client.last_error or "?"))
            self.log.emit(f"Попытка {attempt + 1}: {last_err}")
            client = None
            if not self._sleep_retry():
                return False
        if client is None:
            self.error.emit(last_err)
            return False
        self._client = client
        self._script_id = None
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
            res = self._client.call("Page.addScriptToEvaluateOnNewDocument",
                                    {"source": src})
            self._script_id = (res or {}).get("identifier")
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
        if self._detaching:
            return
        self._detaching = True
        try:
            client, self._client = self._client, None
            script_id, self._script_id = self._script_id, None
            if client is not None:
                if script_id:
                    try:
                        client.call(
                            "Page.removeScriptToEvaluateOnNewDocument",
                            {"identifier": script_id}, timeout=3.0)
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    client.event.disconnect(self._on_event)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    client.closed.disconnect(self._on_closed)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass
            self._pid = None
            try:
                self.detached.emit("")
            except RuntimeError:
                pass
        finally:
            self._detaching = False

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
