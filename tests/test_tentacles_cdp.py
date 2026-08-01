# -*- coding: utf-8 -*-
"""Живые тесты CDP-ядра OctopusBridge: клиент + RPGM-щупальце.

Запускает Edge (Chromium) с отладочным портом на стабе движка RPG Maker.
ПРОПУСК, если Chromium в системе не найден.
"""
import io
import os
import subprocess
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from app.transport.cdp import browser
from app.transport.cdp.chromium import find_chromium

CHROME = find_chromium()
if not CHROME:
    print("ПРОПУСК: Chromium (Edge/Chrome) не найден в системе")
    sys.exit(0)

app = QApplication([])

RPGM_STUB = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>RPGM Stub</title></head>
<body><script>
function Game_Message() { this._texts = []; this._numVisibleRows = 4; }
Game_Message.prototype.add = function(t) { this._texts.push(t); };
var $gameMessage = new Game_Message();
function Window_Base() {}
Window_Base.prototype.drawTextEx = function(text) {
  window.__lastDrawn = text; return text; };
Window_Base.prototype.drawText = function(text) {
  window.__lastDrawn = text; return text; };
Window_Base.prototype.textWidth = function(s) { return ("" + s).length * 10; };
Window_Base.prototype.refresh = function() {};
function Window_Message() {}
Window_Message.prototype = Object.create(Window_Base.prototype);
Window_Message.prototype.constructor = Window_Message;
Window_Message.prototype.startMessage = function() {
  window.__lastDrawn = $gameMessage._texts.join("\n"); };
Window_Message.prototype.terminateMessage = function() {};
Window_Message.prototype.isOpen = function() { return true; };
var SceneManager = { _scene: { _messageWindow: new Window_Message() } };
function Scene_Map() {}
Scene_Map.prototype.update = function() {};
function Game_Variables() { this._data = [null, 0, 0, 0]; }
Game_Variables.prototype.setValue = function(id, v) { this._data[id] = v; };
Game_Variables.prototype.value = function(id) { return this._data[id]; };
var $gameVariables = new Game_Variables();
function Game_Switches() { this._data = [null, false, false]; }
Game_Switches.prototype.setValue = function(id, v) { this._data[id] = !!v; };
Game_Switches.prototype.value = function(id) { return this._data[id]; };
var $gameSwitches = new Game_Switches();
function Game_Party() { this._gold = 100; }
Game_Party.prototype.gold = function() { return this._gold; };
Game_Party.prototype.gainGold = function(n) { this._gold += n; };
Game_Party.prototype.loseGold = function(n) { this._gold -= n; };
Game_Party.prototype.gainItem = function(it, n, eq) {
  window.__lastItem = it.name + "x" + n; };
Game_Party.prototype.inBattle = function() { return false; };
Game_Party.prototype.members = function() { return []; };
Game_Party.prototype.numItems = function() { return 0; };
var $gameParty = new Game_Party();
function Game_Map() {}
Game_Map.prototype.mapId = function() { return 1; };
Game_Map.prototype.canvasToMapX = function(x) { return x; };
Game_Map.prototype.canvasToMapY = function(y) { return y; };
Game_Map.prototype.isValid = function() { return true; };
var $gameMap = new Game_Map();
var $gameActors = { _data: [], actor: function() { return null; } };
var $dataItems = [null, { id: 1, name: "Potion" }];
var $dataWeapons = [null];
var $dataArmors = [null];
var $gamePlayer = { reserveTransfer: function() {},
                    setMoveSpeed: function() {},
                    setThrough: function() {}, locate: function() {} };
var $gameTroop = { members: function() { return []; } };
function Game_Player() {}
Game_Player.prototype.reserveTransfer = function() {};
function Game_BattlerBase() {}
Game_BattlerBase.prototype.setHp = function() {};
Game_BattlerBase.prototype.setMp = function() {};
function Game_Actor() {}
Game_Actor.prototype.changeLevel = function() {};
Game_Actor.prototype.changeExp = function() {};
var TouchInput = { isTriggered: function() { return false; }, x: 0, y: 0 };
var Input = { isPressed: function() { return false; } };
</script></body></html>"""


def pump(seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


with tempfile.TemporaryDirectory() as td:
    page = os.path.join(td, "rpgm_stub.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(RPGM_STUB)
    profile = os.path.join(td, "profile")
    port = browser.free_port()
    url = "file:///" + page.replace("\\", "/")
    proc = subprocess.Popen([
        CHROME, f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}", "--no-first-run",
        "--no-default-browser-check", url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        print("1) Отладчик + page-цель...")
        assert browser.wait_for_debugger(port, timeout=25)
        target = None
        for _ in range(20):
            target = browser.pick_page_target(port, "rpgm_stub")
            if target:
                break
            time.sleep(0.5)
        assert target, "page-цель не найдена"
        print("   OK, port", port)

        print("2) CDPClient: evaluate sync/promise/error...")
        from app.transport.cdp.client import CDPClient
        client = CDPClient()
        assert client.connect(target["webSocketDebuggerUrl"])
        client.call("Runtime.enable")
        ok, val = client.evaluate("21 * 2")
        assert ok and val == 42, (ok, val)
        ok, val = client.evaluate(
            "new Promise(r => setTimeout(() => r('late'), 50))",
            await_promise=True)
        assert ok and val == "late", (ok, val)
        ok, val = client.evaluate("nonexistentFn()")
        assert not ok and "nonexistentFn" in str(val)
        client.close()
        print("   OK")

        print("3) RPGM-щупальце: инъекция, перевод, читы, состояние...")
        from app.engines.rpgmaker.tentacle import RpgMakerTentacle
        t = RpgMakerTentacle()
        states, seen, acks = [], [], []
        t.state_received.connect(states.append)
        t.text_seen.connect(lambda o, tr: seen.append((o, tr)))
        t.cheat_ack.connect(lambda c, ok, e, v: acks.append((c, ok, e, v)))
        t.set_translate_fn(lambda s: s.upper())
        t._pid = proc.pid
        assert t.connect_debugger(port, "rpgm_stub", wait=15)
        pump(0.5)
        ok, val = t.evaluate("!!window.__octopus && !!window.__octopus.rpgm")
        assert ok and val is True, (ok, val)
        pump(0.5)
        assert states and states[-1].get("gold") == 100, states

        # перевод: drawText -> запрос -> кэш
        t.evaluate("var w = new Window_Base(); w.drawText('hello bridge');")
        pump(1.0)
        t.evaluate("w.drawText('hello bridge');")
        pump(0.5)
        ok, val = t.evaluate("window.__lastDrawn")
        assert ok and val == "HELLO BRIDGE", (ok, val)
        # диалог: префетч + перепечатка переводом
        t.evaluate("$gameMessage.add('dialog line one');")
        pump(1.0)
        t.evaluate("SceneManager._scene._messageWindow.startMessage();")
        pump(0.3)
        ok, val = t.evaluate("window.__lastDrawn")
        assert ok and val == "DIALOG LINE ONE", (ok, val)
        print("   перевод: кэш, диалог — OK")

        # читы прямым eval
        assert t.send_cheat("gold_add", value=50)
        ok, val = t.evaluate("$gameParty.gold()")
        assert ok and val == 150, (ok, val)
        assert t.send_cheat("var_set", index=1, value=77)
        assert t.send_cheat("switch_set", index=2, value=True)
        ok, val = t.evaluate("$gameVariables.value(1)")
        assert ok and val == 77
        assert t.send_cheat("give_item", kind="item", id=1, count=3)
        ok, val = t.evaluate("window.__lastItem")
        # имя предмета зависит от того, успел ли bulk-перевод $data
        assert ok and val in ("Potionx3", "POTIONx3"), (ok, val)
        assert not t.send_cheat("win_battle")     # нет боя -> честный False
        print("   читы: gold/vars/switch/item/win_battle — OK")

        # снимок по запросу + автосинхронизация
        states.clear()
        assert t.request_state()
        pump(0.3)
        assert states and states[-1]["gold"] == 150
        states.clear()
        t.evaluate("$gameVariables.setValue(3, 555);")
        pump(1.2)
        assert states and states[-1]["variables"][2] == 555, states
        print("   состояние: запрос + автосинхронизация — OK")

        # bulk-перевод $data в памяти игры (приём mtool_proto)
        deadline = time.time() + 15
        injected = False
        while time.time() < deadline and not injected:
            pump(0.2)
            ok, val = t.evaluate("$dataItems[1] && $dataItems[1].name")
            injected = ok and val == "POTION"
        assert injected, "bulk-перевод $data не сработал"
        # и кэш drawText-хуков подпитан
        t.evaluate("w.drawText('Potion');")
        pump(0.3)
        ok, val = t.evaluate("window.__lastDrawn")
        assert ok and val == "POTION", (ok, val)
        print("   bulk-перевод $data + подпитка кэша — OK")

        t.detach()
        assert not t.is_attached()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

# ── сценарий «медленного движка»: классы появляются через 2.5 с ──
# Регрессия бага: пейлоад внедрялся до загрузки rmmz_*.js и умирал —
# на реальной игре это выглядело как «подключились и тишина».
print("4) Медленный движок: хуки ждут загрузку классов...")
_SLOW_EXPORTS = (";["
    "'Game_Message','Window_Base','Window_Message','Scene_Map',"
    "'Game_Variables','Game_Switches','Game_Party','Game_Player',"
    "'Game_BattlerBase','Game_Actor','SceneManager','TouchInput','Input'"
    "].forEach(function(n){window[n]=eval(n);});"
    "['$gameMessage','$gameVariables','$gameSwitches','$gameParty',"
    "'$gameMap','$gameActors','$dataItems','$dataWeapons','$dataArmors',"
    "'$gamePlayer','$gameTroop'"
    "].forEach(function(n){window[n]=eval(n);});")
SLOW_STUB = RPGM_STUB.replace(
    "<script>", "<script>setTimeout(function(){", 1).replace(
    "</script>", _SLOW_EXPORTS + "}, 2500);</script>", 1)
with tempfile.TemporaryDirectory() as td2:
    page2 = os.path.join(td2, "rpgm_slow.html")
    with open(page2, "w", encoding="utf-8") as f:
        f.write(SLOW_STUB)
    port2 = browser.free_port()
    url2 = "file:///" + page2.replace("\\", "/")
    proc2 = subprocess.Popen([
        CHROME, f"--remote-debugging-port={port2}",
        f"--user-data-dir={os.path.join(td2, 'profile')}",
        "--no-first-run", "--no-default-browser-check", url2,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t2 = RpgMakerTentacle()
        t2.set_translate_fn(lambda s: s.upper())
        t2._pid = proc2.pid
        assert t2.connect_debugger(port2, "rpgm_slow", wait=25)
        # сразу после подключения движка ещё нет
        deadline = time.time() + 15
        hooks_ready = False
        while time.time() < deadline and not hooks_ready:
            pump(0.3)
            hooks_ready = t2.evaluate(
                "!!window.__octopus_hooksReady")[1] is True
        assert hooks_ready, "хуки не дождались движка"
        t2.evaluate("var w = new Window_Base(); w.drawText('late');")
        pump(1.0)
        t2.evaluate("w.drawText('late');")
        pump(0.5)
        ok, val = t2.evaluate("window.__lastDrawn")
        assert ok and val == "LATE", (ok, val)
        assert t2.send_cheat("gold_add", value=5)
        ok, val = t2.evaluate("$gameParty.gold()")
        assert ok and val == 105, (ok, val)
        print("   OK: хуки, перевод и читы после позднего движка")
        t2.detach()
    finally:
        proc2.terminate()
        try:
            proc2.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc2.kill()

print()
print("ВСЕ ТЕСТЫ CDP-ЯДРА ПРОШЛИ")
sys.stdout.flush()
os._exit(0)
