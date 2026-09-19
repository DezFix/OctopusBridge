# -*- coding: utf-8 -*-
"""CDP-транспорт: heartbeat/reconnect/close (скрипт-стиль).

Проверяет минимальные правки без смены API:
1) CDPClient: close на неподключенном, join reader с timeout 2с,
   _reader=None после; call при send fail/timeout -> close+last_error;
   heartbeat ping_interval=20 в _ws_connect_compat.
2) cdp_base._connect_page: retry-пауза 5x0.2 (не сплошной sleep 1.0).
3) cdp_base detach: идемпотентный, disconnect сигналов, guard _detaching,
   _inject_payload сохраняет scriptId, detach зовёт removeScript.
4) browser.scan_ports: висящий probe не вешает скан (timeout 0.5с).
"""
import io
import os
import sys
import threading
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.transport.cdp.client import CDPClient, CDPError
from app.transport.cdp import browser
from app.core.tentacles.cdp_base import CDPTentacle


print("1) close на неподключенном + double close...")
c = CDPClient()
c.close()
c.close()
assert not c.is_connected()
assert c._reader is None
print("   OK")

print("2) call без подключения -> CDPError...")
try:
    CDPClient().call("Runtime.enable", timeout=0.1)
    raise AssertionError("ожидался CDPError")
except CDPError:
    pass
print("   OK")

print("3) pending будится при close...")
c = CDPClient()
slot = {"done": threading.Event(), "result": None, "error": None}
with c._pend_lock:
    c._pending[999] = slot
c.close()
assert slot["done"].is_set(), "pending не разбужен"
assert isinstance(slot["error"], CDPError), slot["error"]
with c._pend_lock:
    assert not c._pending
print("   OK")

print("4) send fail -> last_error + close...")
c = CDPClient()


class _FailWS:
    def send(self, msg):
        raise OSError("boom-send")

    def close(self):
        pass


c._ws = _FailWS()
try:
    c.call("Runtime.enable", timeout=1.0)
    raise AssertionError("ожидался CDPError send failed")
except CDPError as e:
    assert "send failed" in str(e), e
assert "send failed" in (c.last_error or ""), c.last_error
assert not c.is_connected(), "после send fail должен быть close()"
print("   OK:", c.last_error)

print("5) timeout -> last_error + close...")


class _HangWS:
    def send(self, msg):
        pass

    def close(self):
        pass


c = CDPClient()
c._ws = _HangWS()
t0 = time.monotonic()
try:
    c.call("Runtime.enable", timeout=0.3)
    raise AssertionError("ожидался CDPError timeout")
except CDPError as e:
    assert "timeout" in str(e), e
dt = time.monotonic() - t0
assert dt < 2.0, f"timeout должен сработать быстро, было {dt:.2f}с"
assert "timeout" in (c.last_error or ""), c.last_error
assert not c.is_connected(), "после timeout должен быть close()"
print(f"   OK: {c.last_error} за {dt:.2f}с")

print("6) close ждёт reader не дольше ~2с, _reader=None после...")
c = CDPClient()
stop = threading.Event()


def _slow_reader():
    stop.wait(timeout=30)


tr = threading.Thread(target=_slow_reader, daemon=True)
tr.start()
c._reader = tr
t0 = time.monotonic()
c.close()
dt = time.monotonic() - t0
assert c._reader is None, "_reader должен стать None"
assert dt < 3.0, f"join должен отпустить за ~2с, было {dt:.2f}с"
stop.set()
print(f"   OK за {dt:.2f}с")

print("7) heartbeat ping_interval=20 в _ws_connect_compat...")
import app.transport.cdp.client as cli_mod

seen = {}
_real_connect = cli_mod._ws_connect


def _fake_connect(url, **kw):
    seen.update(kw)
    raise TypeError("unexpected keyword argument 'ping_interval'")


cli_mod._ws_connect = _fake_connect
try:
    try:
        cli_mod._ws_connect_compat("ws://127.0.0.1:1/x")
    except TypeError:
        pass
    assert seen.get("ping_interval") == 20, f"первая попытка: {seen}"
finally:
    cli_mod._ws_connect = _real_connect
print("   OK: первая попытка", seen)

print("8) double detach без клиента...")
t = CDPTentacle()
got = []
t.detached.connect(lambda s: got.append(s))
t.detach()
t.detach()
assert t._client is None and t._pid is None
assert t._detaching is False, "guard должен сброситься"
print(f"   OK: detached emit x{len(got)} без падений")

print("9) detach guard от рекурсии (_detaching)...")
t = CDPTentacle()
got2 = []
t.detached.connect(lambda s: got2.append(s))
t._detaching = True
t.detach()
assert got2 == [], "рекурсивный detach не должен эмитить"
t._detaching = False
t.detach()
print("   OK")

print("10) detach отключает сигналы и зовёт removeScript...")


class _FakeSig:
    def __init__(self):
        self.disconnected = []

    def disconnect(self, slot):
        self.disconnected.append(slot)


class _FakeClient:
    def __init__(self):
        self.event = _FakeSig()
        self.closed = _FakeSig()
        self.calls = []
        self.closed_flag = False

    def call(self, method, params=None, timeout=15.0):
        self.calls.append((method, params))
        return {}

    def close(self):
        self.closed_flag = True

    def is_connected(self):
        return True


t = CDPTentacle()
fc = _FakeClient()
t._client = fc
t._script_id = "abc-123"
t._pid = 4242
emitted = []
t.detached.connect(lambda s: emitted.append(s))
t.detach()
assert emitted, "detached должен эмититься"
assert fc.closed_flag, "client.close() должен вызваться"
assert fc.event.disconnected and fc.closed.disconnected, \
    "сигналы должны быть отключены"
rm = [x for x in fc.calls if x[0] == "Page.removeScriptToEvaluateOnNewDocument"]
assert rm and rm[0][1] == {"identifier": "abc-123"}, fc.calls
assert t._client is None and t._script_id is None and t._pid is None
# повторный detach безопасен
t.detach()
print("   OK: removeScript + disconnect + close")

print("11) _inject_payload сохраняет scriptId...")


class _InjClient:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None, timeout=15.0):
        self.calls.append(method)
        if method == "Page.addScriptToEvaluateOnNewDocument":
            return {"identifier": "sid-1"}
        return {}

    def evaluate(self, src, await_promise=False, timeout=15.0):
        return True, None


t = CDPTentacle()
t._client = _InjClient()
t.PAYLOAD = "1;"
t.log.connect(lambda s: None)
t.error.connect(lambda s: None)
t._inject_payload()
assert t._script_id == "sid-1", t._script_id
print("   OK: scriptId =", t._script_id)

print("12) _connect_page: retry-пауза кусочками 0.2...")
import app.core.tentacles.cdp_base as cdp_mod

sleeps = []
_real_sleep = cdp_mod.time.sleep
cdp_mod.time.sleep = lambda s: sleeps.append(s)
_real_wait = browser.wait_for_debugger
_real_pick = browser.pick_page_target
browser.wait_for_debugger = lambda port, timeout=20.0: True
browser.pick_page_target = lambda port, hint="": None
t = CDPTentacle()
t.log.connect(lambda s: None)
t.error.connect(lambda s: None)
try:
    ok = t._connect_page(19222, wait=0.1)
finally:
    cdp_mod.time.sleep = _real_sleep
    browser.wait_for_debugger = _real_wait
    browser.pick_page_target = _real_pick
assert ok is False
assert sleeps, "должны быть паузы между попытками"
assert all(abs(s - 0.2) < 1e-9 for s in sleeps), sleeps[:8]
assert len(sleeps) >= 4, sleeps
print(f"   OK: {len(sleeps)} пауз по 0.2с")

print("13) scan_ports: висящий probe пропускается (timeout 0.5с)...")
_real_ready = browser.debugger_ready


def _flaky(p, timeout=0.35):
    if p == 19991:
        time.sleep(1.5)
        return True
    return p == 19990


browser.debugger_ready = _flaky
try:
    t0 = time.monotonic()
    res = browser.scan_ports([19990, 19991, 19992], timeout=0.1)
    dt = time.monotonic() - t0
finally:
    browser.debugger_ready = _real_ready
assert res == [19990], res
print(f"   OK: {res} за {dt:.2f}с")
import inspect as _insp

_src = _insp.getsource(browser.scan_ports)
assert "0.5" in _src, "в scan_ports должен быть timeout 0.5 на probe"

print()
print("ВСЕ ТЕСТЫ CDP FIX ПРОШЛИ")
