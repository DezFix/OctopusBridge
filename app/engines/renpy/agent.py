# -*- coding: utf-8 -*-
"""Внутриигровой агент OctopusBridge для Ren'Py.

Внедряется в процесс игры через Frida (PyRun_SimpleString) — НИКАКИХ
файлов-плагинов в игре. Двухдиалектный: Ren'Py 7 (Python 2.7) и
Ren'Py 8 (Python 3.x) — поэтому никаких f-строк и daemon-кваргов.

Что делает агент: подмена шрифта (кириллица в японских/английских
играх), читы (золото/HP/переменные/exec/телепорт), состояние игры
и список переменных для панели приложения. Перевод — НЕ здесь:
он выполняется в отдельной вкладке перевода по файлам игры.
"""
from __future__ import annotations

import json
import re

AGENT_TEMPLATE = r'''
# OctopusBridge Ren'Py agent — bootstrap (init-time).
# ВАЖНО: не используем import renpy — в init python: контексте renpy
# уже есть в store как renpy.exports; import renpy перезапишет его
# на renpy-пакет, где нет register_shader/get_side_image/music и т.д.
import json
import os
import socket
import threading
import time
import types
import io

_OB_PORT = %PORT%
_OB_FONT = %FONT_PATH%
_OB_FONT_ABS = %FONT_ABS%
_OB_ABI = "%ABI%"
_OB_STRS = (type(u""), type(""))   # Py2: (unicode, str); Py3: (str, str)


# Глобальная подмена шрифта: font_replacement_map с "wildcard"-get().
# get_font (renpy/text/font.py) вызывает map.get(имя) ДО кэшей лиц —
# любой шрифт игры (диалоги, меню, gui.default_font и т.д.) рендерится
# нашим шрифтом. Файлы игры НЕ трогаем: нет блокировок Windows
# (WinError 32 при attach к запущенной игре), оригиналы остаются на
# диске, toggle восстанавливает карту как была.
#
# Шрифт NotoSans-Regular.ttf — универсальный (JP+RU+EN+латиница):
# и японский, и русский текст рендерятся без квадратиков. Поэтому
# подменять можно любой шрифт игры, включая японские (у которых есть
# только кана/кандзи) — наш шрифт покрывает все используемые скрипты.
class _OB_FontMap(dict):
    def get(self, _k, _d=None):
        try:
            return (_OB_FONT, _k[1], _k[2])
        except Exception:
            return _d


_OB_FONT_MAP_OLD = [None]


def _ob_bootstrap():
    if getattr(renpy, "_ob_agent", None) is not None:
        return
    A = {
        "sock": None, "connected": False, "connecting": False,
        "shutdown": False, "lock": threading.Lock(),
        "fontcache": {},
    }
    renpy._ob_agent = A

    # Чиним известные баги игр (свежий persistent без сохранений):
    # The Roommate — экран настроек читает persistent.fetish_level, а
    # default задан только в preferences → None + 0.5 крашит игру.
    try:
        if getattr(renpy.config, "name", "") == "The Roommate":
            if getattr(renpy.persistent, "fetish_level", None) is None:
                renpy.persistent.fetish_level = int(
                    getattr(renpy.preferences, "fetish_level", 2))
    except Exception:
        pass

    # Версионный сериализатор: Py2 json.dumps может вернуть str (байты)
    # или unicode; Py3 — всегда str. Превращаем в байты надёжно в обоих.
    #@@ABI:py2@@
    def _ob_json_bytes(obj):
        _d = json.dumps(obj, ensure_ascii=False)
        if isinstance(_d, type(u"")):
            return _d.encode("utf-8") + b"\n"
        return _d + b"\n"
    #@@ABI:end@@
    #@@ABI:py3@@
    def _ob_json_bytes(obj):
        return json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
    #@@ABI:end@@

    def _send(obj):
        try:
            if A["connected"] and A["sock"]:
                A["sock"].sendall(_ob_json_bytes(obj))
        except Exception:
            pass

    def _connect():
        with A["lock"]:
            if A["connecting"] or A["connected"] or A["shutdown"]:
                return
            A["connecting"] = True
        try:
            retry = 0
            while retry < 60 and not A["connected"] and not A["shutdown"]:
                try:
                    s = socket.create_connection(("127.0.0.1", _OB_PORT),
                                                 timeout=5)
                    s.settimeout(None)  # blocking — readline() ждёт вечно
                    A["sock"] = s
                    A["connected"] = True
                    t = threading.Thread(target=_recv_loop)
                    t.daemon = True
                    t.start()
                    _send_state()
                    return
                except Exception:
                    retry += 1
                    time.sleep(min(3 * retry, 30))
        finally:
            A["connecting"] = False

    def _recv_loop():
        try:
            f = A["sock"].makefile("rb")
            while A["connected"]:
                try:
                    line = f.readline()
                except Exception:
                    break
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8", "replace"))
                    _dispatch(msg)
                except Exception:
                    pass
        except Exception:
            pass
        A["connected"] = False
        try:
            if A["sock"]:
                A["sock"].close()
        except Exception:
            pass
        A["sock"] = None
        if not A["shutdown"]:
            t = threading.Thread(target=_connect)
            t.daemon = True
            t.start()

    def _dispatch(msg):
        mtype = msg.get("type")
        if mtype == "cheat":
            _run_cheat(msg)
        elif mtype == "get_state":
            _send_state()
        elif mtype == "shutdown":
            A["shutdown"] = True
            A["connected"] = False
            _font_restore()  # вернуть оригинальные шрифты игры

    # ---------- читы ----------
    def _get_gold():
        try:
            return renpy.store.gold
        except Exception:
            return 0

    def _set_gold(val):
        renpy.store.gold = int(val)

    def _heal_all():
        try:
            for attr in ("hp", "mp"):
                full = getattr(renpy.store, attr + "_max", None)
                if full is not None and hasattr(renpy.store, attr):
                    setattr(renpy.store, attr, full)
        except Exception:
            pass

    def _set_variable(name, value):
        if name.startswith("persistent."):
            setattr(renpy.persistent, name[11:], value)
            return
        if name.startswith("store."):
            name = name[6:]
        parts = name.split(".")
        node = renpy.store
        for p in parts[:-1]:
            if isinstance(node, dict):
                node = node.setdefault(p, {})
            else:
                node = getattr(node, p, None)
                if node is None:
                    return
        if isinstance(node, dict):
            node[parts[-1]] = value
        else:
            setattr(node, parts[-1], value)

    def _get_variable(name):
        if name.startswith("persistent."):
            return getattr(renpy.persistent, name[11:], None)
        if name.startswith("store."):
            name = name[6:]
        node = renpy.store
        for p in name.split("."):
            if isinstance(node, dict):
                node = node.get(p)
            else:
                node = getattr(node, p, None)
                if node is None:
                    return None
        return node

    def _teleport(label):
        try:
            renpy.call(label)
        except Exception:
            pass

    def _current_label():
        try:
            return renpy.current_context().current
        except Exception:
            return ""

    def _send_state():
        _send({"type": "state", "gold": _get_gold(),
               "label": _current_label()})

    _OB_VARS_MAX = 20000
    _OB_VARS_SKIP = ("config", "game", "interface", "style",
                     "translation", "persistent", "renpy", "store")

    def _flatten(node, prefix, depth, out):
        # store у реальной игры огромный (config, game, классы и т.п.) —
        # полный обход вешает канал. Не ходим в модули и служебные
        # объекты, обрезаем по лимиту (20k — вся игровая логика).
        if depth > 8 or len(out) >= _OB_VARS_MAX:
            return
        if isinstance(node, dict):
            items = node.items()
        elif isinstance(node, (list, tuple)):
            items = enumerate(node)
        else:
            if isinstance(node, types.ModuleType):
                return
            try:
                items = vars(node).items()
            except Exception:
                try:
                    items = [(k, getattr(node, k))
                             for k in dir(node) if not k.startswith("_")]
                except Exception:
                    return
        for k, v in items:
            if len(out) >= _OB_VARS_MAX:
                break
            # Py2: str(unicode-ключ с кириллицей) падает — используем
            # ключ как есть, если он строка
            #@@ABI:py2@@
            sk = k if isinstance(k, _OB_STRS) else str(k)
            #@@ABI:end@@
            #@@ABI:py3@@
            sk = str(k)
            #@@ABI:end@@
            if sk.startswith("_") or sk in _OB_VARS_SKIP:
                continue
            name = prefix + "." + sk if prefix else sk
            if isinstance(v, bool) or isinstance(v, (int, float) + _OB_STRS):
                out.append({"name": name, "value": v})
            else:
                _flatten(v, name, depth + 1, out)

    def _send_vars():
        names = []
        _flatten(renpy.store, "", 1, names)
        try:
            _flatten(vars(renpy.persistent), "persistent", 1, names)
        except Exception:
            pass
        _send({"type": "vars", "variables": names})

    def _run_cheat(msg):
        ok = True
        error = ""
        try:
            cmd = msg.get("cmd")
            if cmd == "gold_set":
                _set_gold(msg.get("value", 0))
            elif cmd == "gold_add":
                _set_gold(_get_gold() + msg.get("value", 0))
            elif cmd == "heal":
                _heal_all()
            elif cmd == "var_set":
                _set_variable(msg.get("name", ""), msg.get("value"))
            elif cmd == "var_get":
                val = _get_variable(msg.get("name", ""))
                _send({"type": "cheat_ack", "cmd": cmd, "ok": True,
                       "value": val})
                return
            elif cmd == "teleport":
                _teleport(msg.get("label", ""))
            elif cmd == "exec":
                result = renpy.python.py_eval(msg.get("code", "None"))
                #@@ABI:py2@@
                value = result if isinstance(result, _OB_STRS) else repr(result)
                #@@ABI:end@@
                #@@ABI:py3@@
                value = str(result)
                #@@ABI:end@@
                _send({"type": "cheat_ack", "cmd": cmd, "ok": True,
                       "value": value})
                return
            elif cmd == "get_vars":
                _send_vars()
                return
            else:
                ok = False
                error = "unknown cmd: " + str(cmd)
        except Exception as e:
            ok = False
            error = str(e)
        _send({"type": "cheat_ack", "cmd": msg.get("cmd"),
               "ok": ok, "error": error})

    # ---------- шрифт ----------

    # Доступность шрифта: копия в каталоге игры ИЛИ абсолютный фолбэк.
    # Сам шрифт в стили не кладём: рендер идёт через font_replacement_map
    # (см. _patch_font) — loader грузит ob_fonts/NotoSans-Regular.ttf как
    # обычный игровой файл, а оригиналы игры не трогаются вообще.
    _OB_FONT_FILE = [None]

    # Сброс кэша лиц шрифтов. Если игра уже отрендерила текст
    # оригинальными шрифтами (attach к запущенной игре), старые лица
    # остаются в renpy.text.font.face_cache — при смене карты шрифтов
    # чистим кэш, и следующий рендер использует наш шрифт.
    def _font_clear_faces():
        try:
            renpy.text.font.face_cache.clear()
        except Exception:
            pass

    def _font_available():
        if _OB_FONT_FILE[0] is not None:
            return _OB_FONT_FILE[0]
        _ok = False
        try:
            with open(renpy.config.gamedir + "/" + _OB_FONT, "rb") as _f:
                _ok = _f.read(4) == b"\x00\x01\x00\x00"  # TTF/OTF header
        except Exception:
            pass
        if not _ok and _OB_FONT_ABS:
            try:
                with open(_OB_FONT_ABS, "rb") as _f:
                    _ok = _f.read(4) == b"\x00\x01\x00\x00"
            except Exception:
                pass
        _OB_FONT_FILE[0] = _ok
        return _ok

    # Источник шрифта: каталог игры, иначе фолбэк-копия вне игры.
    # Собственный callback игры (если есть) сохраняем в цепочке.
    try:
        _prev_font_cb = getattr(renpy.config, "file_open_callback", None)

        def _font_file_open(name):
            if name.endswith(_OB_FONT):
                try:
                    return open(renpy.config.gamedir + "/" + _OB_FONT, "rb")
                except Exception:
                    try:
                        return open(_OB_FONT_ABS, "rb")
                    except Exception:
                        pass
            if _prev_font_cb is not None:
                return _prev_font_cb(name)
            return None

        renpy.config.file_open_callback = _font_file_open
    except Exception:
        pass

    def _patch_font():
        # Подмена шрифта через глобальную font_replacement_map (см.
        # _OB_FontMap выше). get_font() применяет карту к ЛЮБОМУ имени
        # шрифта ДО кэшей лиц — диалоги, меню, gui.default_font рендерятся
        # нашим NotoSans. Файлы игры не перезаписываются (нет WinError 32
        # на заблокированных attach-ом файлах), оригиналы не бэкапятся —
        # _font_restore просто возвращает старую карту.
        # Диагностика: файл game/.octopus_nofont полностью отключает патч,
        # успех пишется в game/ob_font_log.txt.
        try:
            if os.path.isfile(renpy.config.gamedir + "/.octopus_nofont"):
                return
        except Exception:
            pass
        if not _font_available():
            return
        try:
            _fm = getattr(renpy.config, "font_replacement_map", None)
            if not isinstance(_fm, _OB_FontMap):
                renpy.config.font_replacement_map = _OB_FontMap()
                # уже загруженные лица шрифтов очищаем — текущий экран
                # перерисуется нашим шрифтом при ближайшем restart
                _font_clear_faces()
                try:
                    with io.open(os.path.join(renpy.config.gamedir,
                                              "ob_font_log.txt"), "w",
                                 encoding="utf-8") as _f:
                        _f.write("OB-FONT-MAP installed font=" + _OB_FONT)
                except Exception:
                    pass
        except Exception:
            pass

    def _font_restore():
        # Возвращаем движковую карту шрифтов (toggle отключает подмену)
        try:
            renpy.config.font_replacement_map = _OB_FONT_MAP_OLD[0]
        except Exception:
            pass
        # Возвращаем оригиналы, подменённые файловым методом старых
        # сессий (game/ob_fonts_orig/manifest.json)
        _gamedir = renpy.config.gamedir
        _bdir = os.path.join(_gamedir, "ob_fonts_orig")
        try:
            with io.open(os.path.join(_bdir, "manifest.json"), "r",
                         encoding="utf-8") as _f:
                _manifest = json.loads(_f.read())
        except Exception:
            return
        for _flat, _rel in _manifest.items():
            try:
                _dst = os.path.join(_gamedir, _rel)
                _bpath = os.path.join(_bdir, _flat)
                if os.path.isfile(_bpath):
                    if os.path.isfile(_dst):
                        os.remove(_dst)
                    os.rename(_bpath, _dst)
            except Exception:
                pass
        try:
            os.remove(os.path.join(_bdir, "manifest.json"))
        except Exception:
            pass

    # запоминаем оригинальную карту — _font_restore вернёт её при shutdown
    _OB_FONT_MAP_OLD[0] = getattr(renpy.config, "font_replacement_map", None)
    _patch_font()
    try:
        renpy.config.start_callbacks.append(_patch_font)
        renpy.config.after_load_callbacks.append(_patch_font)
    except Exception:
        pass
    # periodic callback — font для новых стилей.
    # Полный обход стилей — не чаще раза в 2 секунды (не каждый кадр).
    _font_periodic_lock = [0.0]

    def _font_periodic():
        _now = time.time()
        if _now - _font_periodic_lock[0] >= 2.0:
            _font_periodic_lock[0] = _now
            _patch_font()

    try:
        if hasattr(renpy.config, "periodic_callbacks"):
            _cb = lambda: _font_periodic()
            renpy.config.periodic_callbacks.append(_cb)
    except Exception:
        pass
    try:
        renpy.restart_interaction()
    except Exception:
        pass
    t = threading.Thread(target=_connect)
    t.daemon = True
    t.start()


_ob_bootstrap()
'''


_ABI_RE = re.compile(
    r"^[ \t]*#@@ABI:(\w+)@@\n?(.*?)^[ \t]*#@@ABI:end@@[ \t]*\n?",
    re.S | re.M)


def _trim_abi(template: str, abi: str) -> str:
    """Оставляет в шаблоне только секции нужной ветки Ren'Py.

    Секции в шаблоне помечаются строками #@@ABI:py2@@ ... #@@ABI:end@@
    и #@@ABI:py3@@ ... #@@ABI:end@@. Для выбранной ветки секция
    оставляется, чужая — вырезается целиком.
    """

    def _pick(m: re.Match) -> str:
        return m.group(2) if m.group(1) == abi else ""
    return _ABI_RE.sub(_pick, template)


def agent_source(port: int, font_path: str = "ob_fonts/NotoSans-Regular.ttf",
                 font_abs: str = "", abi: str = "py3") -> str:
    s = AGENT_TEMPLATE.replace("%PORT%", str(port))
    s = s.replace("%FONT_PATH%", json.dumps(font_path, ensure_ascii=False))
    s = s.replace("%FONT_ABS%", json.dumps(font_abs, ensure_ascii=False))
    s = s.replace("%ABI%", abi)
    return _trim_abi(s, abi)


def agent_rpy_source(port: int, font_path: str = "ob_fonts/NotoSans-Regular.ttf",
                     font_abs: str = "", abi: str = "py3") -> str:
    """Генерирует .rpy с init python: блоком (полный бутстрап агента)."""
    bootstrap_body = agent_source(port, font_path, font_abs, abi).strip()

    def _indent(text: str) -> str:
        lines = text.split("\n")
        return "\n".join(
            "    " + ln
            for ln in lines
        )

    parts = [
        "init python:",
        _indent(bootstrap_body),
    ]
    return "\n".join(parts)
