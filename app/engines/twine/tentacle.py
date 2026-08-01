# -*- coding: utf-8 -*-
"""TwineTentacle — живой мост для Twine (HTML5) игр.

Запускает игру в браузере ПО УМОЛЧАНИЮ (Firefox, Chrome, Edge — любой).

Архитектура:
  HTTP-сервер → раздаёт .html с инжекцией JS-пэйлоада
  WebSocket   → двусторонняя связь: игра ⟷ OctopusBridge

Поддерживаемые форматы:
  - SugarCube  (State.variables, :passagedisplay)
  - Harlowe    (story.state, tw-passage)
  - Любой      (MutationObserver + DOM-обход)
"""
from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import mimetypes
import os
import socketserver
import threading
import time
import webbrowser
import zlib
from http import server as http_server
from queue import Queue
from urllib.parse import quote

from app.core.tentacles.base import Tentacle

# ── JS-пэйлоад ────────────────────────────────────────────────────────
#  {WS_URL} — подставляется HTTP-сервером при инжекции
PAYLOAD_SCRIPT = r"""
<script>
if (!window.__octopus || !window.__octopus.twineInjected) {
(function(){
var __OT = window.__octopus = window.__octopus || {};
__OT.twineInjected = true;
__OT._cache = {};
__OT._pending = new Map();
__OT._nextId = 1;

// ── WebSocket ──
var _ws = null;
function _connectWS() {
  _ws = new WebSocket("{WS_URL}");
  _ws.onopen = function() { __OT._sendState(); };
  _ws.onmessage = function(e) {
    try { var m = JSON.parse(e.data); } catch(x) { return; }
    if (m.type === "translation") {
      var r = __OT._pending.get(m.id);
      if (r) { __OT._pending.delete(m.id); r(m.text || m.value); }
    } else if (m.type === "cache") {
      for (var k in m.pairs) { __OT._cache[k] = m.pairs[k]; }
      __OT._translateDOM();
    } else if (m.type === "save_restore") {
      var tries = 0;
      (function retryRestore() {
        if (_restoreSaves(m.data)) return;
        if (++tries < 20) setTimeout(retryRestore, 500);
      })();
    }
  };
  _ws.onclose = function() { setTimeout(_connectWS, 1500); };
}
_connectWS();

__OT.send = function(obj) {
  if (_ws && _ws.readyState === 1) {
    _ws.send(JSON.stringify(obj));
  }
};

// ── Очередь переводов ──
// Одновременно в полёте не больше _maxInFlight; один и тот же текст
// не запрашивается дважды (_inflight); таймаут НЕ кэширует оригинал,
// поэтому позже текст перезапросится сам (см. retry-интервал).
__OT._maxInFlight = 6;
__OT._inflight = {};
__OT._queue = [];

function _sendNext() {
  while (__OT._pending.size < __OT._maxInFlight && __OT._queue.length) {
    var it = __OT._queue.shift();
    __OT._pending.set(it.id, it.resolve);
    __OT.send({ type: "translate", id: it.id, text: it.text });
  }
}

function _reqTr(text) {
  if (__OT._cache[text] !== undefined) return Promise.resolve(__OT._cache[text]);
  if (__OT._inflight[text]) return __OT._inflight[text];
  var item, resolveP;
  var p = new Promise(function(res) { resolveP = res; });
  __OT._inflight[text] = p;
  item = {
    id: __OT._nextId++,
    text: text,
    resolve: function(tr) {
      delete __OT._inflight[text];
      if (tr !== text) __OT._cache[text] = tr;
      resolveP(tr);
    },
    drop: function() {
      var i = __OT._queue.indexOf(item);
      if (i !== -1) __OT._queue.splice(i, 1);
      else __OT._pending.delete(item.id);
    }
  };
  __OT._queue.push(item);
  setTimeout(function() {
    if (__OT._inflight[text] === p) {
      item.drop();
      delete __OT._inflight[text];
      resolveP(text);
    }
  }, 120000);
  _sendNext();
  return p;
}

// ── Формат ──
__OT._fmt = (function(){
  if (typeof State !== 'undefined' && State.variables) return 'sugarcube';
  if (typeof Harlowe !== 'undefined') return 'harlowe';
  if (typeof window.story !== 'undefined' && window.story.state) return 'harlowe';
  if (document.querySelector('tw-storydata')) return 'twine-raw';
  return 'unknown';
})();

__OT.addToCache = function(pairs) {
  for (var k in pairs) { __OT._cache[k] = pairs[k]; }
};

function _tr(text) {
  if (typeof text !== 'string') return false;
  var s = text.trim();
  return s.length >= 2 && /[a-zA-Zа-яА-Я\u4e00-\u9fff]/.test(s);
}

// Разбивка длинного текста на предложения, чтобы перевод не
// уходил одним гигантским куском и заполнялся прогрессивно.
function _splitSentences(t) {
  return t.split(/(?<=[.!?…])\s+(?=[«"'A-ZА-Я0-9$\[])/)
    .filter(function(s) { return _tr(s); });
}

function _applyCache(n, s, tr) {
  if (tr !== undefined && tr !== s && n.isConnected) {
    n.textContent = n.textContent.replace(s, tr);
  }
}

function _walkText(root) {
  var nodes = [];
  var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: function(n) {
      var pe = n.parentElement;
      if (!pe) return NodeFilter.FILTER_REJECT;
      var tag = pe.tagName;
      if (tag === 'STYLE' || tag === 'SCRIPT' ||
          tag === 'TW-PASSAGEDATA' || tag === 'TW-STORYDATA') {
        return NodeFilter.FILTER_REJECT;
      }
      if (n.textContent.trim() && _tr(n.textContent)) {
        return NodeFilter.FILTER_ACCEPT;
      }
      return NodeFilter.FILTER_REJECT;
    }
  }, false);
  while (w.nextNode()) { nodes.push(w.currentNode); }
  return nodes;
}

__OT._translateDOM = function() {
  var c = document.querySelector(
    '#passages .passage, tw-passage, .passage, #passages');
  if (!c) return;
  _walkText(c).forEach(function(n) {
    var t = n.textContent, s = t.trim();
    if (!_tr(s)) return;
    // Быстрый путь: весь узел целиком уже в кэше (в т.ч. bulk-кэш)
    if (__OT._cache[s] !== undefined) {
      _applyCache(n, s, __OT._cache[s]);
      return;
    }
    var segs = _splitSentences(t);
    if (segs.length === 1) {
      if (!__OT._inflight[s]) {
        _reqTr(s).then(function(tr) { _applyCache(n, s, tr); });
      }
      return;
    }
    segs.forEach(function(seg) {
      if (__OT._cache[seg] !== undefined) {
        _applyCache(n, seg, __OT._cache[seg]);
        return;
      }
      if (__OT._inflight[seg]) return;
      _reqTr(seg).then(function(tr) { _applyCache(n, seg, tr); });
    });
  });
};

__OT._observer = null;
__OT._startObserver = function() {
  var t = document.querySelector('#passages, #story, tw-story, body') || document.body;
  if (!t) return;
  __OT._observer = new MutationObserver(function() { clearTimeout(__OT._obTimer); __OT._obTimer = setTimeout(__OT._translateDOM, 150); });
  __OT._observer.observe(t, { childList: true, subtree: true, characterData: true });
};

// ── Состояние ──
__OT.collectState = function() {
  var s = { type: "state", format: __OT._fmt, variables: {}, variablesFlat: {}, story: {} };
  if (__OT._fmt === 'sugarcube' && typeof State !== 'undefined') {
    try {
      s.variables = JSON.parse(JSON.stringify(State.variables || {}));
      s.story = { passage: State.passage || '', turns: State.turns || 0 };
      if (typeof Story !== 'undefined') { var c = Story.get(); s.story.title = (c && c.title) || ''; }
      (function fl(o, p) { for (var k in o) { var n = p ? p+'.'+k : k, v = o[k]; if (v && typeof v === 'object' && !Array.isArray(v)) fl(v, n); else s.variablesFlat[n] = v; } })(s.variables, '');
    } catch(e) {}
  } else if (__OT._fmt === 'harlowe') {
    try {
      if (window.Harlowe && window.Harlowe.state) {
        s.variables = JSON.parse(JSON.stringify(window.Harlowe.state.variables || {}));
        (function fl(o, p) { for (var k in o) { var n = p ? p+'.'+k : k, v = o[k]; if (v && typeof v === 'object' && !Array.isArray(v)) fl(v, n); else s.variablesFlat[n] = v; } })(s.variables, '');
      }
    } catch(e) {}
  }
  return s;
};

__OT._sendState = function() { try { __OT.send(__OT.collectState()); } catch(e) {} };

// ── Сейвы: бэкап в OctopusBridge + восстановление ──
__OT._restoreDone = null;
function _backupSaves() {
  if (typeof Save === 'undefined' || !Save.serialize) return;
  try {
    var s = Save.serialize();
    if (s) __OT.send({ type: "save_backup", data: s });
  } catch(e) {}
}
function _restoreSaves(data) {
  if (!data || data === __OT._restoreDone) return true;
  if (typeof Save === 'undefined' || !Save.deserialize) return false;
  try {
    Save.deserialize(data);
    __OT._restoreDone = data;
    // автосейв SugarCube сам не перечитается после restore — пробуем
    // загрузить его как при обычном старте
    if (typeof Save.get === 'function' && Save.get('autosave')) {
      setTimeout(function() {
        try { Save.load('autosave'); } catch(e) {}
      }, 200);
    }
    return true;
  } catch(e) { return false; }
}

// ── Инициализация ──
function _init() {
  if (__OT._fmt === 'sugarcube' && typeof $ !== 'undefined') {
    try { $(document).on(':passagedisplay', function() { setTimeout(__OT._translateDOM, 50); setTimeout(__OT._sendState, 100); }); } catch(e) {}
  } else { __OT._startObserver(); }
  setTimeout(__OT._translateDOM, 300); setTimeout(__OT._sendState, 500);
  // Сейвы: на каждый сейв в игре + периодически + при закрытии
  try {
    if (typeof $ !== 'undefined' && typeof $.fn !== 'undefined') {
      $(document).on(':save', function() { setTimeout(_backupSaves, 50); });
    }
  } catch(e) {}
  if (typeof window.addEventListener === 'function') {
    window.addEventListener('beforeunload', _backupSaves);
  }
  setInterval(_backupSaves, 30000);
  // retry: пока есть необработанные запросы — периодически проходимся
  // по DOM, чтобы подставить поздние ответы и перезапросить таймауты
  setInterval(function() {
    if (__OT._pending.size || __OT._queue.length) { __OT._translateDOM(); }
  }, 3000);
}
if (document.readyState === 'complete' || document.readyState === 'interactive') { _init(); }
else { document.addEventListener('DOMContentLoaded', _init); }

// ── API ──
__OT.getVars = function() {
  var s = __OT.collectState(); var a = [];
  for (var n in s.variablesFlat) a.push({ name: n, value: s.variablesFlat[n] });
  return JSON.stringify(a);
};

__OT.setVar = function(name, value) {
  if (__OT._fmt === 'sugarcube' && typeof State !== 'undefined') {
    try {
      var p = name.split('.'), o = State.variables;
      for (var i = 0; i < p.length - 1; i++) { if (o[p[i]] === undefined || o[p[i]] === null) o[p[i]] = {}; o = o[p[i]]; }
      o[p[p.length - 1]] = value; __OT._sendState(); return true;
    } catch(e) { return false; }
  }
  if (__OT._fmt === 'harlowe' && window.Harlowe) {
    try {
      var p = name.split('.'), o = window.Harlowe.state.variables;
      for (var i = 0; i < p.length - 1; i++) { if (o[p[i]] === undefined) o[p[i]] = {}; o = o[p[i]]; }
      o[p[p.length - 1]] = value; __OT._sendState(); return true;
    } catch(e) { return false; }
  }
  return false;
};

__OT.exec = function(code) { try { return { ok: true, value: eval(code) }; } catch(e) { return { ok: false, error: e.message || String(e) }; } };

})();
}
</script>
"""

# ── HTTP-сервер с инжекцией ──────────────────────────────────────────


class _InjectingHTTPHandler(http_server.SimpleHTTPRequestHandler):
    """Раздаёт файлы игры, в .html — инжектирует JS-пэйлоад."""

    _ws_url: str = ""
    _game_html_rel: str = ""  # относительный путь к .html файлу игры
    directory: str = ""       # устанавливается перед созданием сервера

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=self.__class__.directory, **kwargs)

    def do_GET(self):
        # Только голый корень редиректим на файл игры.
        # /index.html отдаём как есть, иначе при игре-в-index.html
        # получалась бы бесконечная редирект-петля.
        if self.path == "/":
            rel = self._game_html_rel or "index.html"
            self.send_response(302)
            self.send_header("Location", "/" + quote(rel, safe="/"))
            self.end_headers()
            return
        # Инжектируем только .html
        if self.path.endswith(".html") or self.path.endswith(".htm"):
            local = self.translate_path(self.path)
            if os.path.isfile(local):
                try:
                    with open(local, "rb") as f:
                        content = f.read()
                except OSError:
                    self.send_error(404)
                    return
                script = PAYLOAD_SCRIPT.replace("{WS_URL}", self._ws_url)
                content = content.replace(b"</body>",
                                          script.encode() + b"</body>")
                if b"</body>" not in content:
                    content = content + script.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
                return
        # Остальные файлы — как есть
        super().do_GET()

    def log_message(self, fmt, *args):
        pass  # не шумим в консоль


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, http_server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


# ── WebSocket-сервер ─────────────────────────────────────────────────


class _WSServer:
    """Принимает одно WS-соединение от игры, ретранслирует сообщения.

    send() можно вызывать из любого потока: доставка идёт через
    событийный цикл сервера (run_coroutine_threadsafe).
    """

    def __init__(self, on_message, on_connect, on_disconnect):
        self._on_message = on_message
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._ws = None
        self._loop = None
        self._stop_ev = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="twine-msg")
        self.port = 0
        self._ready = threading.Event()

    def start(self) -> bool:
        import asyncio
        import websockets.server as ws_server

        def _safe(fn):
            def _call(*a):
                try:
                    fn(*a)
                except Exception:  # noqa: BLE001 — сигнал мог быть удалён
                    pass
            return _call

        async def handler(websocket):
            with self._lock:
                self._ws = websocket
            _safe(self._on_connect)()
            try:
                async for raw in websocket:
                    try:
                        msg = json.loads(raw)
                    except (ValueError, TypeError):
                        continue
                    self._dispatch(msg)
            except Exception:  # noqa: BLE001
                pass
            finally:
                with self._lock:
                    self._ws = None
                _safe(self._on_disconnect)()

        async def run():
            self._loop = asyncio.get_running_loop()
            self._stop_ev = asyncio.Event()
            self.port = _find_free_port()
            self._ready.set()
            async with ws_server.serve(handler, "127.0.0.1", self.port):
                await self._stop_ev.wait()

        def _server():
            try:
                asyncio.run(run())
            except Exception:  # noqa: BLE001
                pass
            self._loop = None

        self._thread = threading.Thread(target=_server, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)
        return self.port > 0

    def _dispatch(self, msg: dict):
        # Перевод может быть медленным — не блокируем цикл событий WS.
        try:
            self._pool.submit(self._on_message, msg)
        except Exception:  # noqa: BLE001 — пул уже закрыт
            pass

    def send(self, obj: dict) -> bool:
        import asyncio
        with self._lock:
            ws, loop = self._ws, self._loop
        if not ws or not loop or loop.is_closed():
            return False
        data = json.dumps(obj, ensure_ascii=False)
        try:
            fut = asyncio.run_coroutine_threadsafe(ws.send(data), loop)
            if threading.current_thread() is not self._thread:
                fut.result(timeout=10)
            return True
        except Exception:  # noqa: BLE001
            return False

    def has_client(self) -> bool:
        with self._lock:
            return self._ws is not None

    def stop(self):
        import asyncio
        with self._lock:
            ws, loop, stop_ev = self._ws, self._loop, self._stop_ev
            self._ws = None
        if ws and loop and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.close(), loop).result(timeout=5)
            except Exception:  # noqa: BLE001
                pass
        if loop and not loop.is_closed() and stop_ev:
            try:
                loop.call_soon_threadsafe(stop_ev.set)
            except Exception:  # noqa: BLE001
                pass
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._pool.shutdown(wait=False)


def _find_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Щупальце ─────────────────────────────────────────────────────────


class TwineTentacle(Tentacle):
    key = "twine"
    title = "Twine (HTTP+WS)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._game_path: str = ""
        self._game_dir: str = ""
        self._httpd: _ThreadedHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._ws_server: _WSServer | None = None
        self._http_port = 0
        self._pending_translations: dict[int, dict] = {}
        self._last_state: dict | None = None
        self._translating: set = set()      # тексты, уже в работе
        self._translate_waiters: dict[str, list] = {}
        self._tr_lock = threading.Lock()
        self._live_cache: dict[str, str] = {}  # кэш переводов (сессия + файл)
        self._cache_path: str = ""             # octopus_cache.json в папке игры
        self._cache_lock = threading.Lock()
        self._cache_timer_alive = False
        self._port_hint = 0               # фиксированный порт (опционально)
        self._restore_sent = False
        self._last_save_backup = ""

    # ── перевод с кэшем ──
    def translate(self, text: str) -> str:
        """Переводит текст; реальные переводы кэшируются в папке игры."""
        cached = self._live_cache.get(text)
        if cached is not None:
            return cached
        result = super().translate(text)
        if result and result != text:
            with self._cache_lock:
                if len(self._live_cache) > 20000:
                    self._live_cache = dict(
                        list(self._live_cache.items())[-15000:])
                self._live_cache[text] = result
            self._schedule_cache_save()
        return result

    # ── кэш в папке игры ──
    def _load_live_cache(self):
        try:
            with open(self._cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pairs = data.get("pairs", {})
            if isinstance(pairs, dict):
                self._live_cache = {
                    k: v for k, v in pairs.items()
                    if isinstance(k, str) and isinstance(v, str) and v != k}
        except Exception:  # noqa: BLE001 — файла нет или битый
            self._live_cache = {}

    def _save_live_cache(self):
        if not self._cache_path:
            return
        try:
            with self._cache_lock:
                with open(self._cache_path, "w", encoding="utf-8") as f:
                    json.dump({"pairs": self._live_cache}, f,
                              ensure_ascii=False)
        except Exception:  # noqa: BLE001
            pass

    def _schedule_cache_save(self):
        with self._cache_lock:
            if self._cache_timer_alive:
                return
            self._cache_timer_alive = True

        def _timer():
            time.sleep(3)
            with self._cache_lock:
                self._cache_timer_alive = False
            self._save_live_cache()

        threading.Thread(target=_timer, daemon=True).start()

    def set_port_hint(self, port: int):
        """Зафиксировать порт HTTP-сервера (стабильный origin браузера)."""
        self._port_hint = int(port or 0)

    def _game_port(self) -> int:
        """Детерминированный порт по пути игры.

        SugarCube хранит сейвы в localStorage, а localStorage привязан
        к origin (host:port). Один и тот же порт для одной игры между
        запусками = те же сейвы. Разные игры — разные порты (иначе их
        сейвы конфликтовали бы в одном origin).
        """
        if self._port_hint:
            return self._port_hint
        crc = zlib.crc32(self._game_path.encode("utf-8", "replace"))
        return 6000 + (crc % 1000)

    # ── Запуск ──
    def launch(self, target: str) -> bool:
        from app.core.twine.parser import find_story
        if os.path.isdir(target):
            story = find_story(target)
            if not story:
                self.error.emit("Twine-игра не найдена (нет <tw-storydata>).")
                return False
            self._game_path = story
            self._game_dir = target
        else:
            self._game_path = target
            self._game_dir = os.path.dirname(target)

        if not os.path.isfile(self._game_path):
            self.error.emit(f"Файл игры не найден: {self._game_path}")
            return False

        # HTTP-сервер
        rel = os.path.relpath(self._game_path, self._game_dir)
        rel = rel.replace("\\", "/")

        # Кэш переводов из папки игры (переживает перезапуски)
        self._cache_path = os.path.join(self._game_dir, "octopus_cache.json")
        self._load_live_cache()
        if self._live_cache:
            self.log.emit(
                f"Кэш переводов: {len(self._live_cache)} строк из папки игры.")

        if not self._start_http(rel):
            return False
        if not self._start_ws():
            return False

        # Настраиваем URL в пэйлоаде
        ws_url = f"ws://127.0.0.1:{self._ws_server.port}"
        _InjectingHTTPHandler._ws_url = ws_url
        _InjectingHTTPHandler._game_html_rel = rel

        url = f"http://127.0.0.1:{self._http_port}/{quote(rel, safe='/')}"
        self.log.emit(f"Игра: {url}")
        self.log.emit(f"WebSocket: {ws_url}")

        # Открываем в браузере по умолчанию
        try:
            webbrowser.open(url)
            self.log.emit("Браузер по умолчанию открыт.")
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"webbrowser.open: {e}")
            self.log.emit(f"Откройте вручную: {url}")

        # Ждём WS-подключения (таймаут 60с)
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if self._ws_server and self._ws_server.has_client():
                self.log.emit("Игра подключена по WebSocket.")
                self.attached.emit()
                import threading as _t
                _t.Thread(target=self._pretranslate_worker,
                          daemon=True).start()
                return True
            time.sleep(0.3)

        self.error.emit("Игра не подключилась по WebSocket за 60с.")
        self.detach()
        return False

    def attach(self, pid: int) -> bool:
        self.error.emit("attach через PID не поддерживается — "
                        "запускайте игру через Launch.")
        return False

    def detach(self):
        self._save_live_cache()
        self._restore_sent = False
        self._live_cache.clear()
        self._stop_ws()
        self._stop_http()
        self._pid = None
        self.detached.emit("")

    def is_attached(self) -> bool:
        return self._ws_server is not None and self._ws_server.has_client()

    def game_pid(self) -> int | None:
        return None  # браузер не наш процесс

    # ── HTTP ──
    def _start_http(self, game_html_rel: str) -> bool:
        handler = _InjectingHTTPHandler
        handler._game_html_rel = game_html_rel
        handler.directory = self._game_dir
        port = self._game_port()
        try:
            self._httpd = _ThreadedHTTPServer(("127.0.0.1", port), handler)
        except OSError:
            # Порт занят — берём свободный (сейвы браузера при этом
            # не переживут перезапуск: другой origin)
            port = _find_free_port()
            try:
                self._httpd = _ThreadedHTTPServer(
                    ("127.0.0.1", port), handler)
            except OSError as e:
                self.error.emit(f"HTTP-сервер не запустился: {e}")
                return False
            self.log.emit(
                f"Порт {self._game_port()} занят — сейвы браузера могут "
                f"не пережить перезапуск, используется {port}.")
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
    def _start_ws(self) -> bool:
        self._ws_server = _WSServer(
            self._on_ws_message,
            lambda: self.log.emit("WebSocket: клиент подключился"),
            lambda: self.log.emit("WebSocket: клиент отключился"))
        if not self._ws_server.start():
            self.error.emit("WebSocket-сервер не запустился.")
            self._ws_server = None
            return False
        return True

    def _stop_ws(self):
        if self._ws_server:
            self._ws_server.stop()
            self._ws_server = None

    # ── Обработка сообщений из игры ──
    def _on_ws_message(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "translate":
            self._on_translate_request(msg)
        elif mtype == "state":
            self._last_state = msg
            self.state_received.emit(msg)
            # Первое сообщение игры после подключения — отдаём бэкап
            # сейва и кэш переводов (покрывает и переподключения)
            if not self._restore_sent:
                self._restore_sent = True
                self._send_save_restore()
                self._send_live_cache()
        elif mtype == "save_backup":
            self._on_save_backup(msg)
        elif mtype == "cheat_ack":
            self.cheat_ack.emit(str(msg.get("cmd")), bool(msg.get("ok")),
                                str(msg.get("error", "")),
                                json.dumps(msg.get("value", ""),
                                           ensure_ascii=False))

    def _on_translate_request(self, msg: dict):
        original = msg.get("text", "")
        mid = msg.get("id")
        with self._tr_lock:
            if original in self._translating:
                # Уже переводится — отдадим результат по второму id
                self._translate_waiters.setdefault(original, []).append(mid)
                return
            self._translating.add(original)
        try:
            translation = self.translate(original)
        finally:
            with self._tr_lock:
                self._translating.discard(original)
                waiters = self._translate_waiters.pop(original, [])
        self._reply_translation(mid, translation)
        for wid in waiters:
            self._reply_translation(wid, translation)
        self.text_seen.emit(original, translation)

    def _reply_translation(self, mid, text):
        if mid is None:
            return
        if self._ws_server:
            self._ws_server.send({
                "type": "translation",
                "id": mid,
                "text": text,
            })

    # ── Сейвы: бэкап/восстановление ──
    def _send_save_restore(self):
        if not self._game_dir or not self._ws_server:
            return
        path = os.path.join(self._game_dir, "saves", "save.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f).get("data")
        except Exception:  # noqa: BLE001 — нет бэкапа
            return
        if data:
            self._ws_server.send({"type": "save_restore", "data": data})
            self.log.emit("Сейв игры восстановлен из saves/save.json.")

    def _send_live_cache(self):
        if self._live_cache and self._ws_server:
            self._ws_server.send({
                "type": "cache", "pairs": dict(self._live_cache)})

    def _on_save_backup(self, msg: dict):
        data = msg.get("data", "")
        if not data or not self._game_dir or data == self._last_save_backup:
            return
        self._last_save_backup = data
        try:
            saves_dir = os.path.join(self._game_dir, "saves")
            os.makedirs(saves_dir, exist_ok=True)
            tmp = os.path.join(saves_dir, "save.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "game": os.path.basename(self._game_path),
                    "data": data,
                }, f, ensure_ascii=False)
            os.replace(tmp, os.path.join(saves_dir, "save.json"))
        except Exception:  # noqa: BLE001
            pass

    # ── Состояние ──
    def request_state(self) -> bool:
        if not self._ws_server:
            return False
        return self._ws_server.send({"type": "get_state"})

    def request_vars(self) -> bool:
        if not self._ws_server:
            return False
        return self._ws_server.send({"type": "get_vars"})

    def set_variable(self, name: str, value) -> bool:
        if not self._ws_server:
            return False
        return self._ws_server.send({
            "type": "cheat", "cmd": "var_set",
            "name": name, "value": value})

    def send_cheat(self, cmd: str, **kwargs) -> bool:
        if not self._ws_server:
            self.cheat_ack.emit(cmd, False, "no connection", "")
            return False
        payload = {"type": "cheat", "cmd": cmd, **kwargs}
        ok = self._ws_server.send(payload)
        if ok:
            self.cheat_ack.emit(cmd, True, "", "")
        else:
            self.cheat_ack.emit(cmd, False, "send failed", "")
        return ok

    # ── Bulk-перевод ──
    def _pretranslate_worker(self):
        try:
            self._pretranslate()
        except Exception as e:  # noqa: BLE001
            self.log.emit(f"Bulk-перевод: {e}")

    def _pretranslate(self):
        from app.core.twine import parser
        try:
            entries = parser.extract(self._game_dir)
        except Exception:  # noqa: BLE001
            return
        import re as _re
        cyr = _re.compile("[А-яЁё]")
        pairs = {}
        for e in entries:
            t = e.original.strip()
            if len(t) <= 2 or cyr.search(t) or not any(
                    c.isalpha() for c in t):
                continue
            tr = self.translate(e.original)
            if tr and tr != e.original:
                pairs[e.original] = tr
        if pairs and self._ws_server:
            self._ws_server.send({
                "type": "cache", "pairs": pairs})
            self.log.emit(
                f"Bulk-перевод: {len(pairs)} строк в кэше.")
