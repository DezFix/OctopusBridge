# -*- coding: utf-8 -*-
"""Щупальце Ren'Py: внедрение Python-агента через RPY-файл.

Агент: ob_agent.rpy в game/ — Ren'Py сам его загружает и выполняет.
Запуск через subprocess (без Frida). Frida — только fallback attach.
Шрифт с кириллицей опционально копируется в game/ob_fonts/.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import socket
import threading
import time
from typing import Callable

from app.transport.frida_rpc.injector import PythonInjector
from app.core.tentacles.base import Tentacle
from app.engines.renpy.agent import agent_rpy_source
from app.engines.renpy.offsets import RenpyOffsetDB, detect_version

FONT_NAME = "NotoSans-Regular.ttf"
FONT_REL = "ob_fonts/" + FONT_NAME
AGENT_RPY = "ob_agent.rpy"

# ── Защита Ren'Py-интерполяции от переводчика ────────────────────────
# Плейсхолдер "OB{i}": чистый ASCII. Проверено на Argos/opus-mt:
# PUA-символы (\uE000) и скобки (⟦⟧, {{}}, «») токенизатор выбрасывает,
# а цифро-буквенные токены (OB0) сохраняет слово-в-слово.
_PLACEHOLDER = "OB{i}"


def _protect_interp(text: str) -> tuple[str, list[str]]:
    """Заменяет Ren'Py-коды ([...], {...}) и переводы строк на плейсхолдеры.

    Коды — это интерполяция и текстовые теги игры; они не переводимы и
    должны вернуться в перевод слово-в-слово. Переводы строк защищаем,
    чтобы движок не склеивал многострочные строки интерфейса.
    Возвращает (текст без кодов, список кодов в порядке появления).
    """
    codes: list[str] = []
    result: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "[" and i + 1 < n and text[i + 1] == "[":
            # Ren'Py-escape [[ — литеральная скобка, не интерполяция
            codes.append("[[")
            result.append(_PLACEHOLDER.format(i=len(codes) - 1))
            i += 2
        elif c in "[{":
            start = i
            depth = 1
            i += 1
            while i < n and depth > 0:
                if text[i] in "[{":
                    depth += 1
                elif text[i] in "]}":
                    depth -= 1
                i += 1
            codes.append(text[start:i])
            result.append(_PLACEHOLDER.format(i=len(codes) - 1))
        elif c == "\n":
            codes.append(c)
            result.append(_PLACEHOLDER.format(i=len(codes) - 1))
            i += 1
        else:
            result.append(c)
            i += 1
    return "".join(result), codes


def _restore_interp(text: str, codes: list[str]) -> str | None:
    for i, code in enumerate(codes):
        marker = _PLACEHOLDER.format(i=i)
        if marker not in text:
            return None
        text = text.replace(marker, code, 1)
    return text


def _translate_segments(translate: Callable[[str], str],
                        text: str, codes: list[str]) -> str | None:
    """Аварийный перевод: переводим только текстовые куски, коды вставляем
    обратно как есть. Гарантирует сохранность [..]/{..}/\n даже если
    движок перевода выбросил плейсхолдеры из перевода."""
    pieces: list[str] = []
    rest = text
    for code in codes:
        idx = rest.find(code)
        if idx < 0:
            return None
        pieces.append(rest[:idx])
        rest = rest[idx + len(code):]
    pieces.append(rest)
    targets = [p for p in pieces if p.strip()]
    if targets:
        translated = [translate(t) for t in targets]
        it = iter(translated)
        for i, p in enumerate(pieces):
            if p.strip():
                pieces[i] = next(it)
    result = pieces[0]
    for i, code in enumerate(codes):
        result += code + pieces[i + 1]
    return result


def find_launcher(game_dir: str) -> str | None:
    """Исполняемый файл Ren'Py-игры."""
    for name in ("Game.exe", "game.exe", "renpy.exe", "renpy.sh"):
        exe = os.path.join(game_dir, name)
        if os.path.isfile(exe):
            return exe
    sdk = os.path.join(game_dir, "renpy")
    if os.path.isdir(sdk):
        for name in ("renpy.exe", "renpy.sh"):
            exe = os.path.join(sdk, name)
            if os.path.isfile(exe):
                return exe
    for exe in glob.glob(os.path.join(game_dir, "*.exe")):
        base = os.path.splitext(os.path.basename(exe))[0].lower()
        if base not in ("uninstall", "setup", "unins000"):
            return exe
    return None


def install_font(game_dir: str) -> bool:
    """Копирует кириллический NotoSans в game/ob_fonts/."""
    game_sub = os.path.join(game_dir, "game")
    if not os.path.isdir(game_sub):
        return False
    font_src = os.path.join(os.path.dirname(__file__), "..", "..", "core",
                            "assets", "fonts", FONT_NAME)
    if not os.path.isfile(font_src):
        return False
    dst_dir = os.path.join(game_sub, "ob_fonts")
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, FONT_NAME)
    if not os.path.exists(dst):
        try:
            shutil.copy2(font_src, dst)
        except OSError:
            pass
    return os.path.isfile(dst)


def _fallback_font_path() -> str:
    """Абсолютный путь к NotoSans вне игры (для read-only каталогов).

    Гарантирует, что шрифт доступен агенту ВСЕГДА: если каталог игры
    не даёт записать ob_fonts/, агент возьмёт эту копию напрямую.
    """
    base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                        "OctopusBridge", "fonts")
    try:
        os.makedirs(base, exist_ok=True)
        dst = os.path.join(base, FONT_NAME)
        if not os.path.isfile(dst):
            font_src = os.path.join(os.path.dirname(__file__), "..", "..",
                                    "core", "assets", "fonts", FONT_NAME)
            if os.path.isfile(font_src):
                shutil.copy2(font_src, dst)
        if os.path.isfile(dst):
            return dst
    except OSError:
        pass
    return ""


def install_agent_rpy(game_dir: str, port: int) -> bool:
    """Записывает ob_agent.rpy в game/ — Ren'Py загрузит его при старте."""
    game_sub = os.path.join(game_dir, "game")
    if not os.path.isdir(game_sub):
        return False
    # Удаляем старый кэш, чтобы Ren'Py перекомпилировал .rpy
    cleanup_agent_rpy(game_dir)
    dst = os.path.join(game_sub, AGENT_RPY)
    code = agent_rpy_source(port, FONT_REL, _fallback_font_path())
    try:
        with open(dst, "w", encoding="utf-8") as f:
            f.write(code)
        return True
    except OSError:
        return False


CACHE_BACKUP_SUFFIX = ".ob_backup"


def _cache_backup_path(game_dir: str) -> str:
    return os.path.join(game_dir, "game", "cache") + CACHE_BACKUP_SUFFIX


def backup_cache(game_dir: str):
    """Сохраняет оригинальный game/cache/ до первого изменения."""
    cache_dir = os.path.join(game_dir, "game", "cache")
    backup_dir = _cache_backup_path(game_dir)
    if os.path.isdir(cache_dir) and not os.path.isdir(backup_dir):
        try:
            shutil.copytree(cache_dir, backup_dir)
        except OSError:
            pass


def restore_cache(game_dir: str):
    """Восстанавливает game/cache/ из бекапа (удаляет изменённый)."""
    cache_dir = os.path.join(game_dir, "game", "cache")
    backup_dir = _cache_backup_path(game_dir)
    if not os.path.isdir(backup_dir):
        return
    if os.path.isdir(cache_dir):
        try:
            shutil.rmtree(cache_dir, ignore_errors=True)
        except OSError:
            pass
    try:
        shutil.copytree(backup_dir, cache_dir)
    except OSError:
        pass


def _wipe_bytecode_cache(game_dir: str):
    """Удаляет общий байткод-кэш Ren'Py — форсирует чистую пересборку."""
    cache_dir = os.path.join(game_dir, "game", "cache")
    if not os.path.isdir(cache_dir):
        return
    for pattern in ("bytecode*.rpyb", "*.rpymc"):
        for p in glob.glob(os.path.join(cache_dir, pattern)):
            try:
                os.remove(p)
            except OSError:
                pass


def cleanup_agent_rpy(game_dir: str):
    game_sub = os.path.join(game_dir, "game")
    dst = os.path.join(game_sub, AGENT_RPY)
    try:
        if os.path.isfile(dst):
            os.remove(dst)
    except OSError:
        pass
    for ext in (".rpyc", ".rpy~"):
        try:
            p = dst + ext
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    pycache = os.path.join(game_sub, "__pycache__")
    if os.path.isdir(pycache):
        import fnmatch
        try:
            for fname in os.listdir(pycache):
                if fnmatch.fnmatch(fname, "ob_agent*"):
                    try:
                        os.remove(os.path.join(pycache, fname))
                    except OSError:
                        pass
        except OSError:
            pass
    # Общий байткод-кэш — чистим целиком, чтобы Ren'Py не опирался
    # на разъехавшийся архив при следующем запуске.
    _wipe_bytecode_cache(game_dir)


class _AgentServer:
    """TCP-сервер: принимает соединение от агента внутри игры."""

    def __init__(self, on_message, on_connect, on_disconnect):
        self._on_message = on_message
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._sock: socket.socket | None = None
        self._client: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.port = 0

    def start(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind(("127.0.0.1", 0))
            self._sock.listen(1)
            self.port = self._sock.getsockname()[1]
        except OSError:
            self._sock = None
            return False
        self._thread = threading.Thread(target=self._accept_loop,
                                        daemon=True)
        self._thread.start()
        return True

    def _accept_loop(self):
        while self._sock:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            old, self._client = self._client, conn
            if old:
                try:
                    old.close()
                except OSError:
                    pass
            self._on_connect()
            threading.Thread(target=self._read_loop, args=(conn,),
                             daemon=True).start()

    def _read_loop(self, conn: socket.socket):
        try:
            f = conn.makefile("rb")
            while self._client is conn:
                line = f.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                self._on_message(msg)
        except (OSError, ValueError):
            pass
        if self._client is conn:
            self._client = None
        try:
            conn.close()
        except OSError:
            pass
        self._on_disconnect()

    def send(self, obj: dict) -> bool:
        conn = self._client
        if not conn:
            return False
        try:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n"
            with self._send_lock:
                conn.sendall(data)
            return True
        except OSError:
            return False

    def has_client(self) -> bool:
        return self._client is not None

    def stop(self):
        sock, self._sock = self._sock, None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        client, self._client = self._client, None
        if client:
            try:
                client.close()
            except OSError:
                pass


class RenPyTentacle(Tentacle):
    key = "renpy"
    title = "Ren'Py"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._injector: PythonInjector | None = None
        self._server: _AgentServer | None = None
        self._pid: int | None = None
        self._game_dir: str = ""

    # ── жизненный цикл ──
    def launch(self, target: str) -> bool:
        exe = target
        if os.path.isdir(target):
            exe = find_launcher(target) or ""
        if not exe or not os.path.isfile(exe):
            self.error.emit(f"Не найден исполняемый файл Ren'Py: {target}")
            return False
        game_dir = os.path.dirname(exe)
        self._game_dir = game_dir

        # Бэкап девственного кэша ДО любых модификаций
        backup_cache(game_dir)

        install_font(game_dir)
        if not self._start_server():
            return False

        # RPY-агент: Ren'Py сам подхватит ob_agent.rpy из game/
        install_agent_rpy(game_dir, self._server.port)
        self.log.emit(f"RPY-агент записан в game/{AGENT_RPY}")

        # Запускаем игру обычным subprocess — БЕЗ Frida spawn/resume.
        # Тайминги инициализации Ren'Py не нарушаются.
        import subprocess
        try:
            proc = subprocess.Popen([exe], cwd=game_dir)
        except OSError as e:
            self.error.emit(f"Не удалось запустить игру: {e}")
            self._stop_server()
            return False
        self._pid = proc.pid
        self._injector = None
        self.log.emit(f"Игра запущена (pid {proc.pid}) обычным способом, "
                      f"ожидание подключения агента…")
        return self._inject_agent(wait=60.0)

    def attach(self, pid: int) -> bool:
        exe_path = self._exe_of(pid)
        exe_dir = os.path.dirname(exe_path or "")
        self._game_dir = exe_dir
        if exe_dir:
            install_font(exe_dir)
        if not self._start_server():
            return False

        # Для attach RPY уже должен быть от предыдущего launch.
        # Если нет — агент не подключится.
        injector = PythonInjector()
        if not injector.attach(pid):
            self.error.emit(f"Frida не смогла подключиться к pid {pid}.")
            self._stop_server()
            return False
        self._injector = injector
        self._pid = pid

        version, src = detect_version(exe_dir, exe_path)
        if version:
            db = RenpyOffsetDB()
            offsets = db.get_offsets(version)
            if offsets:
                injector.set_offsets(offsets)

        return self._inject_agent(wait=30.0)

    def _inject_agent(self, wait: float = 60.0) -> bool:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self._server and self._server.has_client():
                self.log.emit("Агент внедрён (RPY).")
                return True
            time.sleep(0.5)
        self.error.emit(
            f"Агент не подключился за {wait:.0f}с. "
            f"Проверьте, загружается ли game/{AGENT_RPY}.")
        self.detach()
        return False

    def detach(self):
        if self._server and self._server.has_client():
            self._server.send({"type": "shutdown"})
            time.sleep(0.2)
        self._stop_server()
        if self._injector:
            self._injector.detach()
            self._injector = None
        if self._game_dir:
            cleanup_agent_rpy(self._game_dir)
            restore_cache(self._game_dir)
        self._pid = None
        self.detached.emit("")

    def is_attached(self) -> bool:
        return self._server is not None and self._server.has_client()

    def game_pid(self) -> int | None:
        return self._pid

    # ── сервер ──
    def _start_server(self) -> bool:
        self._server = _AgentServer(self._on_message, self._on_agent_connect,
                                    self._on_agent_disconnect)
        if not self._server.start():
            self.error.emit("Не удалось поднять TCP-сервер для агента.")
            self._server = None
            return False
        return True

    def _stop_server(self):
        if self._server:
            self._server.stop()
            self._server = None

    @staticmethod
    def _exe_of(pid: int) -> str:
        try:
            from app.core import process as proc
            return proc.exe_of(pid)
        except Exception:  # noqa: BLE001
            return ""

    # ── сообщения агента ──
    def _on_agent_connect(self):
        self.log.emit("Агент игры подключился.")
        self.attached.emit()

    def _on_agent_disconnect(self):
        self.log.emit("Агент игры отключился.")

    def _on_message(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "translate":
            self._on_translate(msg)
        elif mtype == "state":
            self.state_received.emit(msg)
        elif mtype == "vars":
            self.vars_received.emit(msg.get("variables") or [])
        elif mtype == "cheat_ack":
            self.cheat_ack.emit(str(msg.get("cmd")), bool(msg.get("ok")),
                                str(msg.get("error", "")),
                                json.dumps(msg.get("value"),
                                           ensure_ascii=False))

    def _on_translate(self, msg: dict):
        original = msg.get("text", "")
        try:
            masked, codes = _protect_interp(original)
            translation = self.translate(masked)
            if codes:
                restored = _restore_interp(translation, codes)
                if restored is None:
                    # движок выбросил плейсхолдеры — переводим по кускам,
                    # коды вставляем как есть
                    restored = _translate_segments(self.translate,
                                                   original, codes)
                translation = restored if restored is not None else original
        except Exception:  # noqa: BLE001
            translation = original
        if self._server:
            self._server.send({"type": "translation", "id": msg.get("id"),
                               "text": translation})
        self.text_seen.emit(original, translation)

    # ── команды в игру ──
    def request_state(self) -> bool:
        return bool(self._server) and self._server.send({"type": "get_state"})

    def request_vars(self) -> bool:
        return self.send_cheat("get_vars")

    def set_variable(self, name: str, value) -> bool:
        return self.send_cheat("var_set", name=name, value=value)

    def send_cheat(self, cmd: str, **kwargs) -> bool:
        if not self._server or not self._server.has_client():
            self.log.emit("Нет подключения к игре.")
            return False
        return self._server.send({"type": "cheat", "cmd": cmd, **kwargs})
