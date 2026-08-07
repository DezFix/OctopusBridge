# -*- coding: utf-8 -*-
"""Внутриигровой агент OctopusBridge для Ren'Py.

Внедряется в процесс игры через Frida (PyRun_SimpleString) — НИКАКИХ
файлов-плагинов в игре. Двухдиалектный: Ren'Py 7 (Python 2.7) и
Ren'Py 8 (Python 3.x) — поэтому никаких f-строк и daemon-кваргов.
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
import re
import types
import io

_OB_PORT = %PORT%
_OB_FONT = %FONT_PATH%
_OB_FONT_ABS = %FONT_ABS%
_OB_ABI = "%ABI%"
_OB_STRS = (type(u""), type(""))   # Py2: (unicode, str); Py3: (str, str)

# --- префильтры: что не отправляем на сервер перевода ---
_OB_LATIN_RE = re.compile(r"[A-Za-z]")
# японские символы (кана + кандзи): строки без латиницы, но с каной —
# это японский текст игры, его тоже отправляем на перевод
_OB_JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# трейсбеки, пути к файлам, код движка — не переводятся
_OB_JUNK_RE = re.compile(
    r"Traceback|Full traceback|uncaught exception|While running game code|"
    r"File [\"']|renpy[/\\]|\.rpy[\"']|_ob_agent"
)
# пути ассетов (картинки/звуки/шрифты, в т.ч. DynamicImage-шаблоны вида
# "gui/scrollbar/vertical_[prefix_]bar.png") — перевод имени файла
# ломает загрузку ассетов (краш "could not find image")
_OB_ASSET_RE = re.compile(r"/[^/]{1,120}\.[A-Za-z0-9]{1,4}$")
# строки форматирования (strftime/printf: "%A %B %d, %Y", "%.1f") — перевод
# добавляет кириллицу ("г."), и time.strftime падает (locale codec)
_OB_FMT_RE = re.compile(r"%[-+#0-9]*\.?[0-9]*[A-Za-z%]")
_OB_MAX_LEN = 500
# Лимит кэша: десятки тысяч пар при json.load/json.dump в главном
# потоке игры (старт + periodic callback) вызывают фризы — держим
# последние 20k пар, старые вытесняем.
_OB_CACHE_MAX = 20000


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
        "cache": {}, "translated": set(), "pending": {},
        "next_id": 1, "fontcache": {},
        "cache_dirty": False, "cache_path": None,
        "skip": set(), "skip_path": None, "skip_dirty": False,
        "paused": False,
        "response_events": {}, "response_events_lock": threading.Lock(),
    }
    renpy._ob_agent = A
    # загружаем кэш перевода из файла игры (единый формат octopus_cache.json)
    A["cache_path"] = renpy.config.gamedir + "/octopus_cache.json"

    def _ob_filter_pairs(_pairs):
        # отфильтровываем identity-записи, трейсбеки, пути кода и пути
        # ассетов (в т.ч. испорченные прежними сессиями переводы
        # DynamicImage-путей — они давали краш "could not find image")
        return {k: v for k, v in _pairs.items()
                if isinstance(v, _OB_STRS)
                and k != v and len(k) <= _OB_MAX_LEN
                and not _OB_JUNK_RE.search(k)
                and not _OB_FMT_RE.search(k)
                and not _OB_FMT_RE.search(v)
                and not _OB_ASSET_RE.search(k)
                and not _OB_ASSET_RE.search(v)}

    try:
        with io.open(A["cache_path"], "r", encoding="utf-8") as _f:
            _raw = json.load(_f)
        if isinstance(_raw, dict) and isinstance(_raw.get("pairs"), dict):
            A["cache"] = _ob_filter_pairs(_raw["pairs"])
            _ob_skip = _raw.get("skip")
            if isinstance(_ob_skip, list):
                A["skip"] = set(x for x in _ob_skip
                                if isinstance(x, _OB_STRS))
        elif isinstance(_raw, dict):
            A["cache"] = _ob_filter_pairs(_raw)
        A["translated"] = set(A["cache"].values())
    except Exception:
        # старый формат: плоский .octopus_cache.json
        try:
            _cp_old = renpy.config.gamedir + "/.octopus_cache.json"
            with io.open(_cp_old, "r", encoding="utf-8") as _f:
                _raw = json.load(_f)
            if isinstance(_raw, dict):
                A["cache"] = _ob_filter_pairs(_raw)
                A["translated"] = set(A["cache"].values())
        except Exception:
            pass
    # Лимит кэша после загрузки: обрезаем до последних 20k пар, чтобы
    # старт и периодическая запись не тормозили игру на большом кэше
    if len(A["cache"]) > _OB_CACHE_MAX:
        A["cache"] = dict(list(A["cache"].items())[-_OB_CACHE_MAX:])
        A["translated"] = set(A["cache"].values())
    # старый отдельный файл identity-строк
    try:
        _sp_old = renpy.config.gamedir + "/.octopus_skip.json"
        with io.open(_sp_old, "r", encoding="utf-8") as _f:
            _ob_skip = json.load(_f)
        if isinstance(_ob_skip, list):
            A["skip"] |= set(x for x in _ob_skip
                             if isinstance(x, _OB_STRS))
    except Exception:
        pass
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
    # identity-строки: не перезапрашиваем перевод, который вернулся
    # без изменений
    try:
        A["skip_path"] = renpy.config.gamedir + "/.octopus_skip.json"
        with io.open(A["skip_path"], "r", encoding="utf-8") as _f:
            A["skip"] = set(json.load(_f))
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

    def _is_skipping():
        """Идёт ли перемотка (skip): при ней нельзя блокировать и слать
        сотни строк на сервер — берём только кэш, остальное пропускаем."""
        try:
            _iface = getattr(renpy, "game", None)
            _iface = getattr(_iface, "interface", None)
            if _iface is None:
                return False
            return bool(getattr(_iface, "skipping", False))
        except Exception:
            return False

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
                    # догон: всё, что уже на экране, перерисуем —
                    # Text-виджеты пересоздадутся и уйдут на перевод
                    _restart_needed[0] = True
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
        with A["lock"]:
            # pending очищаем: при переподключении тексты уйдут заново,
            # иначе предзагрузка зависнет навсегда
            A["pending"].clear()
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

    # Флаг для restart в главном потоке (через periodic_callbacks)
    _restart_needed = [False]
    # Очередь замен текста — применяется из главного потока
    _pending_replace = []
    _restart_lock = [0.0]
    _restart_interval = 0.5

    def _do_restart():
        # во время перемотки не перерисовываем: Ren'Py сам пересоздаёт
        # виджеты каждую строку, лишний restart только лагает
        if _is_skipping():
            return
        now = time.time()
        if now - _restart_lock[0] >= _restart_interval:
            _restart_lock[0] = now
            _restart_needed[0] = False  # сброс: рестарт только по новым переводам
            try:
                # Применяем накопившиеся замены текста в виджетах
                for o, t in _pending_replace:
                    _replace_text_in_widgets(o, t)
                _pending_replace.clear()
                # Сбрасываем кэш виджетов интерфейса (для scene)
                if hasattr(renpy.game, "interface") and renpy.game.interface:
                    if hasattr(renpy.game.interface, "widget_cache"):
                        renpy.game.interface.widget_cache.clear()
                # Сбрасываем виджеты экранов — чтобы Text.__init__ вызвался заново
                try:
                    from renpy.display.screen import screens
                    for sc in list(screens.values()):
                        sc.widgets.clear()
                except Exception:
                    pass
                renpy.restart_interaction()
            except Exception:
                pass

    def _replace_text_in_widgets(orig, trans):
        """Прямая замена текста в уже существующих Text-виджетах."""
        def _walk(d):
            if isinstance(d, renpy.text.text.Text):
                cur = getattr(d, "text", None)
                if cur and cur.strip() == orig.strip():
                    d.text = trans
                    try:
                        d.redraw()
                    except Exception:
                        pass
            for ch in getattr(d, "children", ()):
                _walk(ch)
            child = getattr(d, "child", None)
            if child is not None:
                _walk(child)
        try:
            from renpy.display.screen import screens
            for sc in list(screens.values()):
                for wid, wdg in list(sc.widgets.items()):
                    _walk(wdg)
        except Exception:
            pass
        try:
            for d in renpy.game.interface.layers.values():
                _walk(d)
        except Exception:
            pass

    # Запись кэша — не чаще раза в 5 секунд: json.dump большого кэша
    # выполняется в главном потоке игры (periodic callback), и каждая
    # запись на кадре — источник фризов.
    _save_lock = [0.0]

    def _save_cache():
        if not (A["cache_dirty"] or A["skip_dirty"]) \
                or not A["cache_path"]:
            return
        if time.time() - _save_lock[0] < 5.0:
            return
        _save_lock[0] = time.time()
        try:
            # не сохраняем identity-записи; единый формат + skip
            _clean = {k: v for k, v in A["cache"].items() if k != v}
            _payload = {"format": 1, "engine": "renpy", "pairs": _clean}
            if A["skip"]:
                _payload["skip"] = sorted(A["skip"])
            _tmp = A["cache_path"] + ".tmp"
            with io.open(_tmp, "w", encoding="utf-8") as _f:
                json.dump(_payload, _f, ensure_ascii=False, indent=2)
            try:
                os.remove(A["cache_path"])
            except Exception:
                pass
            os.rename(_tmp, A["cache_path"])
        except Exception:
            return
        A["cache_dirty"] = False
        A["skip_dirty"] = False
        # старые файлы кэша больше не пишем — убираем (best effort)
        try:
            os.remove(renpy.config.gamedir + "/.octopus_cache.json")
        except Exception:
            pass
        try:
            os.remove(renpy.config.gamedir + "/.octopus_skip.json")
        except Exception:
            pass

    def _extract_brackets(text):
        """Extract balanced [...] and {...} groups from text (handles nesting).

        Both [variable] and {size=16}{/size} must be preserved in translations.
        Ren'Py escape [[ is a literal bracket, not interpolation.
        """
        result = []
        i, n = 0, len(text)
        while i < n:
            if text[i] in ("[", "{"):
                if text[i] == "[" and i + 1 < n and text[i + 1] == "[":
                    result.append("[[")
                    i += 2
                    continue
                start = i
                closer = "]" if text[i] == "[" else "}"
                depth = 1
                i += 1
                while i < n and depth > 0:
                    if text[i] == text[start]:
                        depth += 1
                    elif text[i] == closer:
                        depth -= 1
                    i += 1
                result.append(text[start:i])
            else:
                i += 1
        return result

    def _dispatch(msg):
        mtype = msg.get("type")
        if mtype == "translation":
            mid = msg.get("id")
            with A["lock"]:
                orig = A["pending"].pop(mid, None)
                _do_replace = False
                if orig is not None:
                    trans = msg.get("text", "")
                    # НЕ кэшируем identity-переводы (экстрактор возвращает то же самое).
                    # Если закэшировать identity, то _translate вернёт оригинал
                    # из кэша и НЕ отправит текст на реальный сервер перевода.
                    # paused: перевод приостановлен пользователем — строку
                    # не кэшируем и в skip не добавляем (после включения
                    # перевода она уйдёт на сервер заново).
                    if not msg.get("paused") and trans != orig:
                        # строки форматирования (strftime и т.п.) — не
                        # кэшируем даже если сервер их уже перевёл
                        if (_OB_FMT_RE.search(orig)
                                or _OB_FMT_RE.search(trans)):
                            A["skip"].add(orig)
                            A["skip_dirty"] = True
                            trans = orig
                        # проверяем что [interpolation]/[code] коды сохранены
                        _codes = _extract_brackets(orig)
                        _is_pure = False
                        if _codes:
                            # pure interpolation: текст состоит ТОЛЬКО из кодов
                            _rest = orig
                            for _c in _codes:
                                _rest = _rest.replace(_c, "", 1)
                            _is_pure = not _rest.strip()
                        _ok = True
                        if not _is_pure:
                            # mixed — коды должны быть сохранены в переводе
                            for _c in _codes:
                                if _c not in trans:
                                    _ok = False
                                    break
                        if _ok and trans != orig:
                            # кэш ограничен: вытесняем самую старую пару,
                            # чтобы json-файл и память не росли бесконечно
                            if len(A["cache"]) >= _OB_CACHE_MAX:
                                A["cache"].pop(
                                    next(iter(A["cache"]), None), None)
                            A["cache"][orig] = trans
                            A["translated"].add(trans)
                            if len(A["translated"]) > _OB_CACHE_MAX * 2:
                                A["translated"] = set(A["cache"].values())
                            A["cache_dirty"] = True
                            _do_replace = True
                    elif not msg.get("paused"):
                        # identity — больше не перезапрашиваем эту строку
                        A["skip"].add(orig)
                        A["skip_dirty"] = True
            if _do_replace:
                if len(_pending_replace) > 200:
                    _pending_replace.clear()  # защита от неограниченного роста
                _pending_replace.append((orig, trans))
                _restart_needed[0] = True
            # будим ждущий поток (даже для identity — чтобы blocking не завис)
            with A["response_events_lock"]:
                ev = A["response_events"].pop(mid, None)
                if ev is not None:
                    ev.set()
        elif mtype == "cheat":
            _run_cheat(msg)
        elif mtype == "get_state":
            _send_state()
        elif mtype == "shutdown":
            A["shutdown"] = True
            A["connected"] = False
            _font_restore()  # вернуть оригинальные шрифты игры
        elif mtype == "set_paused":
            A["paused"] = bool(msg.get("paused", False))

    def _translate(what, blocking=False, timeout=5):
        if not isinstance(what, _OB_STRS) or not what.strip():
            return what
        key = what.strip().replace("%%", "%")  # unescape для поиска/отправки
        # перевод приостановлен (переключатель в мосте выключен):
        # показываем оригинал, ничего не шлём и не блокируем игру —
        # раньше агент не знал о паузе и висел на round-trip к серверу
        if A["paused"]:
            return what
        # без латиницы и без японских символов — строка уже переведена
        # (кириллица, коды, имена): не тратим сервер и не создаём
        # identity-записи. Японский текст (кана/кандзи) переводим.
        if not _OB_LATIN_RE.search(key) and not _OB_JP_RE.search(key):
            return what
        # трейсбеки/пути/код движка и слишком длинные строки — не переводим
        if len(key) > _OB_MAX_LEN or _OB_JUNK_RE.search(key):
            return what
        # пути ассетов (gui/...png и т.п.) — перевод ломает загрузку
        if _OB_ASSET_RE.search(key):
            return what
        # строки форматирования времени/чисел — strftime не переживёт
        # кириллицу, которую добавит переводчик ("%Y" -> "%Y г.")
        if _OB_FMT_RE.search(key):
            return what
        with A["lock"]:
            cached = A["cache"].get(key)
            if cached is not None:
                return cached
            # identity-строка — сервер уже возвращал её без изменений
            if key in A["skip"]:
                return what
            # уже переведённая нами строка (перевод с латиницей внутри,
            # например "Версия v2.0") — повторно на сервер не отправляем
            if key in A["translated"]:
                return what
            if not A["connected"]:
                return what
            # перемотка (skip): не шлём на сервер и не блокируем —
            # перемотка гонит сотни строк за секунды, ждать нельзя
            if _is_skipping():
                return what
            if key in A["pending"].values():
                return what
            mid = A["next_id"]
            A["next_id"] += 1
            A["pending"][mid] = key
        _send({"type": "translate", "id": mid, "text": key})
        if blocking:
            ev = threading.Event()
            with A["response_events_lock"]:
                A["response_events"][mid] = ev
            # ждём с проверкой connected (timeout=None = макс 10s; сервер
            # сам отвечает не дольше ~12с — таймаут-страховка щупальца)
            _timeout = 10.0 if timeout is None else timeout
            _start_all = time.time()
            while _timeout > 0:
                _start = time.time()
                if not A["connected"]:
                    break
                if ev.wait(timeout=min(_timeout, 0.5)):
                    break
                _timeout -= time.time() - _start
            with A["response_events_lock"]:
                A["response_events"].pop(mid, None)
            with A["lock"]:
                cached = A["cache"].get(key)
                if cached is not None:
                    return cached
        return what

    def _text_filter(text):
        tr = _translate(text)
        if tr is not text and isinstance(tr, _OB_STRS):
            tr = tr.replace("%", "%%")
        return tr

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

    _OB_VARS_MAX = 2000
    _OB_VARS_SKIP = ("config", "game", "interface", "style",
                     "translation", "persistent", "renpy", "store")

    def _flatten(node, prefix, depth, out):
        # store у реальной игры огромный (config, game, классы и т.п.) —
        # полный обход вешает канал, читы/триггеры перестают работать.
        # Не ходим в модули и служебные объекты, обрезаем по лимиту.
        if depth > 6 or len(out) >= _OB_VARS_MAX:
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

    # ---------- универсальный перехват текста ----------

    def _patch_text():
        try:
            prev_say = getattr(renpy.config, "say_menu_text_filter", None)
            def _chained_say(what):
                if prev_say is not None:
                    what = prev_say(what)
                # при перемотке не блокируем (кэш-перевод внутри
                # _translate всё равно применится, отправки нет)
                tr = _translate(what, blocking=not _is_skipping(),
                                timeout=None)
                if tr is not what and isinstance(tr, _OB_STRS):
                    tr = tr.replace("%", "%%")
                return tr
            renpy.config.say_menu_text_filter = _chained_say
        except Exception:
            pass
        try:
            prev_menu = getattr(renpy.config, "menu_text_filter", None)
            def _chained_menu(what):
                if prev_menu is not None:
                    what = prev_menu(what)
                # неблокирующий — перевод меню асинхронный (через кэш)
                return _text_filter(what)
            renpy.config.menu_text_filter = _chained_menu
        except Exception:
            pass
        # Text.__init__ hook: применяет перевод из кэша при перерисовке
        # (say_menu_text_filter и menu_text_filter вызываются один раз;
        # когда перевод приходит асинхронно, renpy.restart_interaction()
        # пересоздаёт Text-виджет — тут подставляем кэшированный перевод).
        try:
            Text = renpy.text.text.Text
            if not getattr(Text, "_ob_patched", False):
                orig_init = Text.__init__

                def _patched_init(self, text, *args, **kwargs):
                    try:
                        if isinstance(text, _OB_STRS):
                            raw = text.strip().replace("%%", "%")
                            _translate(raw)
                            # применяем кэш только если текст ещё НЕ переведён
                            # (чтобы не сломать say_menu_text_filter)
                            with A["lock"]:
                                if raw not in A["translated"]:
                                    cached = A["cache"].get(raw)
                                    if cached is not None:
                                        text = cached.replace("%", "%%")
                    except Exception:
                        pass
                    return orig_init(self, text, *args, **kwargs)

                Text.__init__ = _patched_init
                Text._ob_patched = True
        except Exception:
            pass
        # Интерполированные строки (меню, списки действий, [var] в текстах)
        # НЕ проходят через translate_string целиком: Ren'Py переводит
        # шаблон ДО подстановки значений, а сами значения (например,
        # "Go somewhere else" из build_actions_list, подставляемое в
        # textbutton "[item.title!i]") остаются на языке оригинала.
        # Обёртка renpy.substitutions.substitute (единственная точка
        # интерполяции — text.py вызывает её в set_text) переводит
        # УЖЕ интерполированный результат (когда подстановка была).
        try:
            import sys as _sys2
            _sub = _sys2.modules.get("renpy.substitutions")
            if _sub is None:
                _sub = __import__("renpy.substitutions", fromlist=["x"])
            if _sub is not None and not getattr(_sub, "_ob_patched", False):
                _orig_sub = _sub.substitute

                def _ob_sub(s, scope=None, force=False, translate=True):
                    _rv, _did = _orig_sub(s, scope, force, translate)
                    try:
                        # translate=False — движок сам запретил перевод:
                        # DynamicImage (renpy/easy.py) так вызывает
                        # substitute для ПУТЕЙ КАРТИНОК — их нельзя трогать
                        if _did and translate:
                            _rv = _translate(_rv)
                    except Exception:
                        pass
                    return _rv, _did

                _sub.substitute = _ob_sub
                _sub._ob_patched = True
        except Exception:
            pass
        # Здесь:
        # renpy.substitutions.substitute(translate=True) вызывает
        # renpy.translation.translate_string ДО создания виджетов —
        # для реплик (what), имён (who), меню и интерфейса. Перевод
        # здесь синхронизирует виджет say-экрана с what_string, что
        # устраняет краш "displayable with id 'what'" и английский
        # флеш-мгновение в диалогах.
        try:
            import sys as _sys
            _trl = _sys.modules.get("renpy.translation")
            if _trl is None:
                _trl = __import__("renpy.translation", fromlist=["x"])
            if _trl is None or getattr(_trl, "_ob_patched", False):
                return
            _orig_tl = _trl.translate_string

            def _ob_tl(*args, **kwargs):
                _s = args[0] if args else kwargs.get("s")
                if isinstance(_s, _OB_STRS) and _s.strip():
                    _tr = _translate(_s)
                    if _tr is not _s and isinstance(_tr, _OB_STRS):
                        return _tr.replace("%", "%%")
                return _orig_tl(*args, **kwargs)

            _trl.translate_string = _ob_tl
            _trl._ob_patched = True
        except Exception:
            pass

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
                _restart_needed[0] = True
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

    _patch_text()
    # запоминаем оригинальную карту — _font_restore вернёт её при shutdown
    _OB_FONT_MAP_OLD[0] = getattr(renpy.config, "font_replacement_map", None)
    _patch_font()
    try:
        renpy.config.start_callbacks.append(_patch_font)
        renpy.config.after_load_callbacks.append(_patch_font)
    except Exception:
        pass
    # periodic callback — restart из главного потока + font для новых стилей.
    # Полный обход стилей — не чаще раза в 2 секунды (не каждый кадр).
    _font_periodic_lock = [0.0]

    def _font_periodic():
        _now = time.time()
        if _now - _font_periodic_lock[0] >= 2.0:
            _font_periodic_lock[0] = _now
            _patch_font()

    try:
        if hasattr(renpy.config, "periodic_callbacks"):
            _cb = lambda: (_save_cache(),
                           _font_periodic(),
                           _do_restart() if _restart_needed[0] else None)
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
