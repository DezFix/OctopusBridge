# -*- coding: utf-8 -*-
"""Щупальце TyranoScript: CDP-внедрение в NW.js-процесс игры.

Запуск: Game.exe (NW.js-обёртка) с --remote-debugging-port — файлы игры
не трогаем. Переменные Tyrano (kag.variables / kag.tmp) доступны для
чит-вкладок.

Для браузерной игры без exe живого подключения нет: пользователю
предлагается запустить через Launch (см. error в launch).
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from app.core import process as proc
from app.transport.cdp import browser
from app.transport.cdp.client import CDPClient, CDPError
from app.core.tentacles.cdp_base import CDPTentacle

# Кандидаты портов для сканирования (как у RPG Maker)
SCAN_PORTS = [9222, 9229, 9333] + list(range(9000, 9101)) + \
    list(range(26000, 26051))

# признак страницы Tyrano
_TYRANO_PROBE = ("!!(window.kag && window.kag.variables) || "
                 "!!(document.querySelector('#tyrano_base'))")

# ── JS-пейлоад: переменные/состояние (для чит-вкладок) ──
PAYLOAD = r"""
if (!window.__octopus.tyrano) {
window.__octopus.tyrano = true;

// ── переменные Tyrano ──
// %user и &system лежат в kag.variables, временные tf. — в kag.tmp.
window.__octopus_collectState = function () {
  const s = { type: "state", engine: "tyrano", variables: {}, variablesFlat: {} };
  try {
    if (typeof kag !== "undefined") {
      const kv = kag.variables || {};
      const tmp = kag.tmp || {};
      const src = {};
      for (const k of Object.keys(kv)) src[k] = kv[k];
      for (const k of Object.keys(tmp)) src["tf." + k] = tmp[k];
      s.variables = JSON.parse(JSON.stringify(src));
    }
    const flat = {};
    (function fl(o, p) {
      for (const k in o) {
        const n = p ? p + "." + k : k;
        const v = o[k];
        if (v && typeof v === "object" && !Array.isArray(v)) fl(v, n);
        else flat[n] = v;
      }
    })(s.variables, "");
    s.variablesFlat = flat;
  } catch (e) {}
  return s;
};

function sendState() {
  try { window.__octopus.send(window.__octopus_collectState()); } catch (e) {}
}

// ── установка хуков после готовности движка ──
(function init() {
  const poll = setInterval(function () {
    if (typeof kag === "undefined" && !document.querySelector("#tyrano_base")) {
      return;
    }
    clearInterval(poll);
    try {
      sendState();
      console.log("[octopus] Tyrano hooks installed");
    } catch (e) {
      console.warn("[octopus] Tyrano hook install failed: " + e);
    }
  }, 400);
})();
}
"""


class TyranoTentacle(CDPTentacle):
    key = "tyrano"
    title = "TyranoScript (CDP)"
    PAYLOAD = PAYLOAD

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._game_dir: str = ""

    # ── запуск ──
    def launch(self, target: str) -> bool:
        exe = target
        game_dir = target
        if os.path.isdir(target):
            game_dir = target
            exe = os.path.join(target, "Game.exe")
            if not os.path.isfile(exe):
                # некоторые сборки TyranoBuilder: index.html в корне без exe
                for cand in ("TyranoPlayer.exe", "nw.exe", "nwjs.exe"):
                    p = os.path.join(target, cand)
                    if os.path.isfile(p):
                        exe = p
                        break
        if not os.path.isfile(exe):
            self.error.emit(
                f"Не найден исполняемый файл игры: {exe}\n"
                "Tyrano-игра без exe (браузерная) поддерживается только "
                "в файловом режиме перевода.")
            return False
        port = browser.free_port()
        try:
            self._proc = subprocess.Popen(
                [exe, f"--remote-debugging-port={port}"],
                cwd=game_dir)
        except OSError as e:
            self.error.emit(f"Не удалось запустить игру: {e}")
            return False
        self._pid = self._proc.pid
        self._game_dir = game_dir
        self.log.emit(f"Игра запущена (pid {self._pid}), отладка :{port}.")
        if not self._connect_page(port, url_hint=".html", wait=30.0):
            self.detach()
            return False
        return True

    def attach(self, pid: int) -> bool:
        port = getattr(self, "_port_hint", 0) or probe_game_port(pid)
        if not port:
            self.error.emit(
                "Отладочный порт не найден: игра запущена без "
                "--remote-debugging-port. Запустите её через OctopusBridge.")
            return False
        self._pid = pid
        exe = proc.exe_of(pid)
        self._game_dir = os.path.dirname(exe) if exe else ""
        return self._connect_page(port, url_hint=".html", wait=5.0)

    def set_port_hint(self, port: int):
        self._port_hint = port

    def detach(self):
        self._proc = None
        super().detach()

    # ── состояние/переменные ──
    def request_state(self) -> bool:
        ok, val = self.evaluate(
            "JSON.stringify(window.__octopus_collectState "
            "? window.__octopus_collectState() : null)")
        if ok and isinstance(val, str) and val:
            try:
                self.state_received.emit(json.loads(val))
                return True
            except ValueError:
                pass
        return False

    def request_vars(self) -> bool:
        return self.send_cheat("get_vars")

    def set_variable(self, name: str, value) -> bool:
        return self.send_cheat("var_set", name=name, value=value)

    def send_cheat(self, cmd: str, **kwargs) -> bool:
        expr = self._cheat_expr(cmd, **kwargs)
        if expr is None:
            self.cheat_ack.emit(cmd, False, "unknown cmd", "")
            return False
        ok, val = self.evaluate(expr)
        if not ok:
            time.sleep(0.5)
            ok, val = self.evaluate(expr)
        if cmd == "get_vars" and ok:
            try:
                raw = json.loads(val) if isinstance(val, str) else val
                items = raw.get("variablesFlat") or {}
                self.vars_received.emit(
                    [{"name": k, "value": v} for k, v in items.items()])
            except (ValueError, AttributeError):
                pass
        self.cheat_ack.emit(cmd, ok, "" if ok else str(val),
                            json.dumps(val, ensure_ascii=False) if ok else "")
        return ok

    @staticmethod
    def _cheat_expr(cmd: str, **kwargs) -> str | None:
        js = json.dumps
        if cmd == "get_vars":
            return ("JSON.stringify(window.__octopus_collectState "
                    "? window.__octopus_collectState() : null)")
        if cmd == "var_set":
            name = str(kwargs["name"])
            value = kwargs["value"]
            # tf.x живёт в kag.tmp, остальное — в kag.variables
            target = "kag.tmp" if name.startswith("tf.") else "kag.variables"
            key = name[3:] if name.startswith("tf.") else name
            return ("(() => { if (typeof kag === 'undefined') "
                    f"throw new Error('kag not ready'); "
                    f"{target}[{js(key)}] = {js(value)}; "
                    "return JSON.stringify({ok:true}); })()")
        if cmd == "exec":
            return ("(() => { try { return JSON.stringify({ok:true, "
                    "value:(function(){" + kwargs["code"] + "})()}); } "
                    "catch(e) { return JSON.stringify({ok:false, "
                    "error:String(e)}); } })()")
        return None

    def game_pid(self) -> int | None:
        if self._proc and self._proc.poll() is None:
            return self._proc.pid
        return self._pid if self._pid else None


# ── Поиск порта для attach ──

def probe_game_port(pid: int) -> int:
    exe = proc.exe_of(pid)
    game_dir = os.path.dirname(exe) if exe else ""
    port = proc.debug_port_from_cmdline(proc.cmdline_of(pid))
    if port:
        return port
    port = browser.port_from_devtools_file(exe, game_dir)
    if port:
        return port
    return _bruteforce_port(pid)


def _bruteforce_port(pid: int) -> int:
    candidates = browser.scan_ports(SCAN_PORTS)
    if not candidates:
        time.sleep(2.0)
        candidates = browser.scan_ports(SCAN_PORTS)
    for port in candidates:
        if _port_is_tyrano(port, pid):
            return port
    return 0


def _port_is_tyrano(port: int, pid: int) -> bool:
    target = browser.pick_page_target(port, ".html")
    if not target:
        return False
    client = CDPClient()
    if not client.connect(target["webSocketDebuggerUrl"]):
        return False
    try:
        client.call("Runtime.enable")
        ok, val = client.evaluate(_TYRANO_PROBE)
        if not (ok and val is True):
            return False
        try:
            info = client.call("SystemInfo.getProcessInfo", timeout=3)
            procs = info.get("processInfo") or []
            browser_pid = next((p.get("id") for p in procs
                                if p.get("type") == "browser"), None)
            if browser_pid is not None:
                return int(browser_pid) == int(pid)
        except CDPError:
            pass
        return True
    except CDPError:
        return False
    finally:
        client.close()
