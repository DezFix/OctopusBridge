# -*- coding: utf-8 -*-
"""Щупальце AjinSyoujyo: CDP к Electron-процессу игры (читы на переменных).

Запуск: <game>.exe (Electron) с --remote-debugging-port — файлы игры
не трогаем, перевод живёт в override/. KAG здесь НЕ глобальный:
инстанс лежит в TYRANO.kag.kag (запасные: tyrano.plugin.kag,
классический window.kag). Игровые переменные: f.* — stat.f,
sf.* — variable.sf, tf.* — variable.tf (kag.tmp — служебный,
не игровой). Отличия от TyranoTentacle: поиск exe по маске *.exe
(не Game.exe), cwd = корень игры, подхват уже запущенной игры.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from app.core import process as proc
from app.core.ajin import layout as layout_mod
from app.core.tentacles.cdp_base import (
    CDPTentacle, DEFAULT_SCAN_PORTS, bruteforce_port,
    probe_game_port as _base_probe,
)
from app.transport.cdp import browser
from app.transport.cdp.client import CDPClient, CDPError

SCAN_PORTS = DEFAULT_SCAN_PORTS

# KAG-резолвер: классический window.kag либо инстанс TyranoBuilder
# (TYRANO.kag.kag, запасной tyrano.plugin.kag).
_KAG = ("(window.kag||(window.TYRANO&&TYRANO.kag&&TYRANO.kag.kag)||"
        "(window.tyrano&&tyrano.plugin&&tyrano.plugin.kag))")

_TYRANO_PROBE = ("(!!" + _KAG + "||"
                 "!!(document.querySelector('#tyrano_base'))")

PAYLOAD = r"""
if (!window.__octopus) window.__octopus = {};
if (!window.__octopus.ajin) {
window.__octopus.ajin = true;

window.__octopus_kag = function () {
  return (window.kag
    || (window.TYRANO && TYRANO.kag && TYRANO.kag.kag)
    || (window.tyrano && tyrano.plugin && tyrano.plugin.kag)
    || null);
};

window.__octopus_collectState = function () {
  const s = { type: "state", engine: "ajin", variables: {}, variablesFlat: {} };
  try {
    const KAGV = window.__octopus_kag();
    if (KAGV) {
      const f = (KAGV.stat && KAGV.stat.f) || {};
      const vv = KAGV.variable || {};
      const sf = vv.sf || {};
      const tf = vv.tf || {};
      const src = {};
      for (const k of Object.keys(f)) src["f." + k] = f[k];
      for (const k of Object.keys(sf)) src["sf." + k] = sf[k];
      for (const k of Object.keys(tf)) src["tf." + k] = tf[k];
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

(function init() {
  const poll = setInterval(function () {
    const hasKag = (typeof kag !== "undefined")
      || (window.TYRANO && TYRANO.kag && TYRANO.kag.kag);
    if (!hasKag && !document.querySelector("#tyrano_base")) {
      return;
    }
    clearInterval(poll);
    try {
      sendState();
      console.log("[octopus] Ajin hooks installed");
    } catch (e) {
      console.warn("[octopus] Ajin hook install failed: " + e);
    }
  }, 400);
})();
}
"""


class AjinTentacle(CDPTentacle):
    key = "ajin"
    title = "AjinSyoujyo (CDP)"
    PAYLOAD = PAYLOAD

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._game_dir: str = ""

    # ── запуск ──
    def launch(self, target: str) -> bool:
        game_dir = target if os.path.isdir(target) else \
            os.path.dirname(target)
        # игра уже запущена вручную: не плодим второй экземпляр —
        # подхватываем по отладочному порту, иначе честно говорим,
        # что нужен перезапуск через приложение (пустой список читов
        # как раз отсюда: сессия не подключена к чужому процессу).
        running = pick_running(game_dir)
        if running is not None:
            pid, port = running
            if port:
                self._pid = pid
                self._game_dir = game_dir
                self.log.emit(f"Подключаюсь к запущенной игре (pid {pid}).")
                if not self._connect_page(port, url_hint=".html", wait=5.0):
                    self.detach()
                    return False
                return True
            self.error.emit(
                "Игра уже запущена, но без флага отладки — читы "
                "к ней не подключить.\nЗакройте игру и нажмите "
                "«Запустить игру» в приложении.")
            return False
        exe = layout_mod.find_exe(game_dir)
        if not exe or not os.path.isfile(exe):
            self.error.emit(
                f"Не найден исполняемый файл игры в: {game_dir}\n"
                "Ожидается Electron exe рядом с resources/app.asar.")
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

    # ── состояние/переменные (читы) ──
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
            # f.* -> stat.f, sf.* -> variable.sf, tf.* -> variable.tf
            if name.startswith("tf."):
                target, key = "KAGV.variable.tf", name[3:]
            elif name.startswith("sf."):
                target, key = "KAGV.variable.sf", name[3:]
            elif name.startswith("f."):
                target, key = "KAGV.stat.f", name[2:]
            else:
                target, key = "KAGV.stat.f", name
            return ("(() => { var KAGV = " + _KAG + "; "
                    "if (!KAGV || !KAGV.stat) "
                    "throw new Error('kag not ready'); "
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


def pick_running(game_dir: str) -> tuple[int, int] | None:
    """(pid, port) запущенной игры этой папки или None.

    port == 0 — процесс есть, но отладочного флага нет (подключить
    CDP нельзя, нужен перезапуск через приложение).
    """
    hits = proc.find_game_processes("ajin", game_dir)
    if not hits:
        return None
    return hits[0]["pid"], hits[0].get("port", 0)


def probe_game_port(pid: int) -> int:
    """Тонкая обёртка над cdp_base.probe_game_port (логика одна)."""
    return _base_probe(pid, SCAN_PORTS, _port_is_ajin)


def _bruteforce_port(pid: int) -> int:
    return bruteforce_port(pid, SCAN_PORTS, _port_is_ajin)


def _port_is_ajin(port: int, pid: int) -> bool:
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
