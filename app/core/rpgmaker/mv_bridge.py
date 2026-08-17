# -*- coding: utf-8 -*-
"""MV-профиль: мост для официального рантайма RPG Maker MV.

Официальный рантайм MV — non-SDK сборка NW.js, где remote debugging
вырезан: --remote-debugging-port игнорируется (проверено: CLI,
chromium-args в package.json и оба сразу — порт не открывается).
CDP для MV-игр недоступен в принципе, поэтому MV получает отдельный
канал: в игру вшивается плагин octopus_ob.js (NW.js Node API в странице
— require('http')), поднимающий HTTP-сервер на 127.0.0.1. Все команды
(probe/eval/tr) ходят через него.

MZ (десктопные и Electron-сборки) этот модуль не трогает — там CDP.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

BRIDGE_PLUGIN_NAME = "octopus_ob"
BRIDGE_PLUGIN_VERSION = 2
BRIDGE_PORT_START = 38900
BRIDGE_PORT_COUNT = 12
_BRIDGE_PROBE_TIMEOUT = 0.8

# ── сбор ошибок страницы: переживает краш (localStorage) ──
_ERROR_CATCHER_JS = r"""
// ── OctopusBridge: сбор ошибок игры (переживает краш страницы) ──
(function () {
  function obErr(kind, msg, extra) {
    try {
      var prev = {};
      try {
        prev = JSON.parse(localStorage.getItem("__octopus_last_err") || "{}");
      } catch (e) {}
      prev[kind] = { msg: String(msg), extra: String(extra || ""),
                     t: Date.now() };
      localStorage.setItem("__octopus_last_err", JSON.stringify(prev));
    } catch (e) {}
  }
  window.addEventListener("error", function (ev) {
    obErr("error", ev.message || "",
          (ev.filename || "") + ":" + (ev.lineno || 0));
  });
  window.addEventListener("unhandledrejection", function (ev) {
    obErr("rejection", String(ev.reason || ""));
  });
  if (typeof SceneManager !== "undefined" && SceneManager.catchException) {
    try {
      var obCatch = SceneManager.catchException;
      SceneManager.catchException = function (e) {
        obErr("catch", e && e.message || e, e && e.stack || "");
        return obCatch.apply(this, arguments);
      };
    } catch (e) {}
  }
})();
"""

# ── HTTP-сервер внутри игры (вставляется в конец плагина) ──
_BRIDGE_SERVER_JS = r"""
// ── мост OctopusBridge: HTTP-сервер (NW.js Node API) ──
(function () {
  if (window.__octopusBridgeReady) return;
  window.__octopusBridgeReady = true;
  try {
    var http = require("http");
    var PORT0 = 38900;
    function start(port) {
      var server = http.createServer(function (req, res) {
        var body = "";
        req.on("data", function (chunk) { body += chunk; });
        req.on("end", function () {
          var out = { ok: true };
          try {
            var path = req.url.split("?")[0];
            if (path === "/probe") {
              out.name = "octopus_ob";
            } else if (path === "/eval") {
              var reqData = JSON.parse(body || "{}");
              var fn;
              try {
                fn = new Function("return (" + reqData.expr + ");");
              } catch (e) {
                fn = new Function(reqData.expr);
              }
              var value = fn.call(window);
              out.value = (value === undefined || value === null)
                ? null : JSON.stringify(value);
            } else if (path === "/tr") {
              var tr = JSON.parse(body || "{}");
              var n = 0;
              for (var k in tr) {
                if (Object.prototype.hasOwnProperty.call(tr, k)) {
                  window.__octopus_tr[k] = tr[k];
                  n++;
                }
              }
              out.count = n;
            } else if (path === "/errlog") {
              try {
                out.err = JSON.parse(
                  localStorage.getItem("__octopus_last_err") || "null");
              } catch (e) {
                out.err = null;
              }
            } else {
              out.ok = false;
              out.error = "unknown path";
            }
          } catch (e) {
            out.ok = false;
            out.error = String(e && e.message || e);
          }
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end(JSON.stringify(out));
        });
      });
      server.on("error", function () {
        if (port < PORT0 + 11) start(port + 1);
      });
      server.listen(port, "127.0.0.1", function () {
        window.__octopusBridgePort = port;
      });
    }
    start(PORT0);
  } catch (e) {
    console.warn("[octopus] bridge start failed: " + e);
  }
})();
"""


def build_plugin_source(cheats_payload: str, tr_payload: str,
                        tr_dict_json: str = "{}") -> str:
    """Полный исходник плагина-моста.

    Порядок: шим (send — заглушка) → пейлоад читов → пейлоад перевода
    (маркер __TR_DICT__ заменяется на JSON словаря — иначе ReferenceError
    оборвёт скрипт до старта HTTP-сервера) → сбор ошибок → сервер.
    Пейлоады идут из щупальца, чтобы не плодить дубликаты и не создавать
    циклических импортов.
    """
    return (
        "// OctopusBridge: чит-мост для RPG Maker MV (не редактируйте)\n"
        f"window.__octopusBridgeVersion = {BRIDGE_PLUGIN_VERSION};\n"
        "window.__octopus = window.__octopus || {};\n"
        "if (!window.__octopus.send) {\n"
        "  window.__octopus.send = function () {};\n"
        "}\n"
        "// eslint-disable-next-line\n"
        + cheats_payload + "\n"
        + tr_payload.replace("__TR_DICT__", tr_dict_json) + "\n"
        + _ERROR_CATCHER_JS + "\n"
        + _BRIDGE_SERVER_JS + "\n")


def _existing_dict(src: str) -> str:
    """JSON словаря из уже развёрнутого плагина (для регенерации)."""
    m = re.search(r"__octopus_trInstall\((.*?)\);", src, re.S)
    if m:
        blob = m.group(1).strip()
        try:
            json.loads(blob)
            return blob
        except ValueError:
            pass
    return "{}"


def _js_dir(game_dir: str) -> str:
    """js/ или www/js/ (игра, развёрнутая в подпапку www)."""
    if os.path.isfile(os.path.join(game_dir, "www", "index.html")):
        return "www/js"
    return "js"


def plugin_rel(game_dir: str) -> str:
    return f"{_js_dir(game_dir)}/plugins/{BRIDGE_PLUGIN_NAME}.js"


def plugins_js_rel(game_dir: str) -> str:
    return f"{_js_dir(game_dir)}/plugins.js"


# ── внедрение плагина в игру (при apply и перед запуском) ──

def ensure_bridge_registered(game_dir: str, cheats_payload: str,
                             tr_payload: str) -> bool:
    """Пишет плагин (если отсутствует или устарел) и регистрирует в
    plugins.js.

    Идемпотентно: актуальный плагин и запись не перезаписываются.
    Устаревший (другая версия пейлоадов/моста, маркер __TR_DICT__)
    перегенерируется с сохранением уже развёрнутого словаря.
    """
    ok = True
    plugin_path = os.path.join(game_dir, *plugin_rel(game_dir).split("/"))
    need_write = not os.path.isfile(plugin_path)
    old_dict = "{}"
    if not need_write:
        try:
            with open(plugin_path, encoding="utf-8") as f:
                src = f.read()
        except OSError:
            src = ""
        need_write = ("__TR_DICT__" in src or
                      f"__octopusBridgeVersion = {BRIDGE_PLUGIN_VERSION}"
                      not in src)
        old_dict = _existing_dict(src)
    if need_write:
        try:
            os.makedirs(os.path.dirname(plugin_path), exist_ok=True)
            with open(plugin_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(build_plugin_source(
                    cheats_payload, tr_payload, old_dict))
        except OSError:
            ok = False
    return _ensure_plugins_entry(game_dir) and ok


def _ensure_plugins_entry(game_dir: str) -> bool:
    path = os.path.join(game_dir, *plugins_js_rel(game_dir).split("/"))
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    if f'"{BRIDGE_PLUGIN_NAME}"' in text:
        return True
    entry = ('{"name":"octopus_ob","status":true,"description":'
             '"OctopusBridge bridge (cheats/translation)","parameters":{}}')
    if text.lstrip().startswith("["):
        # JSON-формат (data/plugins.js в MZ) — страховка
        try:
            data = json.loads(text)
        except ValueError:
            return False
        data.append(json.loads(entry))
        new_text = json.dumps(data, ensure_ascii=False, indent=1)
    else:
        # JS-формат MV: var $plugins = [ ... ];
        idx = text.rfind("]")
        if idx < 0:
            return False
        head = text[:idx].rstrip()
        if head.endswith(","):
            head = head[:-1]
        new_text = head + ",\n" + entry + "\n" + text[idx:]
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_text)
        return True
    except OSError:
        return False


def update_tr_dict(game_dir: str, entries: list) -> int:
    """Обновляет статический словарь перевода в плагине-мосте.

    Словарь собирается из записей (original -> translation, пустые и
    skip пропущены). Возвращает число записей словаря (0 — плагин
    отсутствует или нечего обновлять).
    """
    tr: dict = {}
    for e in entries:
        if isinstance(e, dict):
            orig = e.get("original", "")
            text = e.get("translation", "") or ""
            status = e.get("status", "")
        else:
            orig = getattr(e, "original", "")
            text = getattr(e, "translation", "") or ""
            status = getattr(e, "status", "")
        if orig and text.strip() and status != "skip":
            tr[orig] = text
    if not tr:
        return 0
    path = os.path.join(game_dir, *plugin_rel(game_dir).split("/"))
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return 0
    tr_json = json.dumps(tr, ensure_ascii=False)
    if "__TR_DICT__" in src:
        new_src = src.replace("__TR_DICT__", tr_json)
    else:
        m = re.search(r"__octopus_trInstall\((.*?)\);", src, re.S)
        if not m:
            return 0
        new_src = (src[:m.start(1)] + tr_json + src[m.end(1):])
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_src)
        return len(tr)
    except OSError:
        return 0


def unregister_bridge(game_dir: str) -> bool:
    """Снимает мост: убирает запись из plugins.js и удаляет плагин."""
    changed = False
    path = os.path.join(game_dir, *plugins_js_rel(game_dir).split("/"))
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        new_text = _remove_entry_by_name(text, BRIDGE_PLUGIN_NAME)
        if new_text != text:
            try:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_text)
                changed = True
            except OSError:
                pass
    plugin_path = os.path.join(
        game_dir, *plugin_rel(game_dir).split("/"))
    if os.path.isfile(plugin_path):
        try:
            os.remove(plugin_path)
            changed = True
        except OSError:
            pass
    return changed


def _remove_entry_by_name(text: str, name: str) -> str:
    """Вырезает объект {"name": ...} из JS/JSON-массива целиком.

    Регекс не подходит: у записи есть вложенная пара скобок
    ("parameters": {}). Идём от "name" назад до открывающей скобки
    объекта, затем вперёд до парной закрывающей — и удаляем объект
    вместе с окружающими запятыми/пробелами.
    """
    m = re.search(r'"name"\s*:\s*"' + re.escape(name) + r'"', text)
    if not m:
        return text
    idx = m.start()
    start = idx
    depth = 0
    while start >= 0:
        ch = text[start]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth < 0:
                break
        start -= 1
    if start < 0:
        return text
    end = start + 1
    depth = 0
    while end < len(text):
        ch = text[end]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                break
        end += 1
    if end >= len(text):
        return text
    head = text[:start]
    tail = re.sub(r"^\s*,?\s*", "", text[end + 1:])
    head = re.sub(r"\s*,\s*$", "", head)
    return head + tail


# ── клиент моста (app -> игра) ──

def bridge_probe(port: int) -> bool:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/probe",
            data=b"{}",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(
                req, timeout=_BRIDGE_PROBE_TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return data.get("name") == BRIDGE_PLUGIN_NAME
    except Exception:  # noqa: BLE001
        return False


def find_bridge_port(wait: float = 40.0) -> int:
    """Ждёт появления моста игры (все порты диапазона, пока не найден)."""
    deadline = time.time() + wait
    while time.time() < deadline:
        for port in range(BRIDGE_PORT_START,
                          BRIDGE_PORT_START + BRIDGE_PORT_COUNT):
            if bridge_probe(port):
                return port
        time.sleep(1.0)
    return 0


def bridge_eval(port: int, expr: str, timeout: float = 15.0):
    """Выполняет JS в игре. Возвращает (ok, value) — value как в CDP:
    json-декодированное значение выражения (None для undefined)."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/eval",
            data=json.dumps({"expr": expr}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if not out.get("ok"):
        return False, str(out.get("error") or "?")
    value = out.get("value")
    if value is None:
        return True, None
    try:
        return True, json.loads(value)
    except ValueError:
        return True, value


def bridge_install_tr(port: int, tr: dict, timeout: float = 15.0) -> bool:
    """Пуш живого словаря в игру (эквивалент apply_translation)."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/tr",
            data=json.dumps(tr, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8", "replace"))
        return bool(out.get("ok"))
    except Exception:  # noqa: BLE001
        return False


def bridge_errlog(port: int, timeout: float = 5.0) -> dict | None:
    """Последние ошибки страницы игры (catch/error/rejection) или None."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/errlog",
            data=b"{}",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8", "replace"))
        return out.get("err")
    except Exception:  # noqa: BLE001
        return None
