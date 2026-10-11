# -*- coding: utf-8 -*-
"""Щупальце Unity: запуск игры + ЖИВОЙ канал через Mono-рантайм.

Отличие от прежней заглушки: `is_attached()` больше не врёт `False` —
для запущенных нами игр канал настоящий (Frida + Mono), читы работают.

Границы (решение шефа, AGENTS.md §1):

* `launch()` — свой процесс, регистрируем в реестре запусков, цепляемся;
* `attach(pid)` — только если pid есть в реестре **и** exe-процесса
  совпадает с записанным. Чужая игра не подключается вообще;
* `send_key` / `screenshot()` живым каналом не делаются (инъекция ввода
  в Unity — отдельная история). Честно `False` / `None`, как у MV-моста.
* Пока канала нет — UI показывает это прямо, без «зелёной» лапши.
"""
from __future__ import annotations

import glob
import os
import subprocess
import time

from app.live.tentacle import Tentacle
from app.transport.unity_rpc import registry

# Хелперы рядом с игрой — не она.
_HELPERS = {"unitycrashhandler", "unitycrashhandler64", "config", "setup",
            "uninstall", "unins000", "dxsetup"}

#: сколько ждём канал суммарно (ранний старт игры: Frida в первые
#: миллисекунды жизни процесса получает отказ VirtualAllocEx — лечится
#: повторными попытками, а не одной)
_ATTACH_TIMEOUT_S = 150.0
#: пауза перед первой попыткой: дать процессу выйти из ранней инициации
_SPAWN_SETTLE_S = 4.0


def find_launcher(game_dir: str) -> str | None:
    """Исполняемый файл Unity-игры.

    Приоритет: <Name>.exe, совпадающий с <Name>_Data (стандартная сборка
    Unity), затем первый не-хелпер exe.
    """
    try:
        names = os.listdir(game_dir)
    except OSError:
        return None
    data_names = {n[:-len("_Data")].lower() for n in names
                  if n.lower().endswith("_data")
                  and os.path.isdir(os.path.join(game_dir, n))}
    cands = sorted(glob.glob(os.path.join(game_dir, "*.exe")))
    cands = [c for c in cands
             if os.path.splitext(os.path.basename(c))[0].lower()
             not in _HELPERS]
    if not cands:
        return None
    for exe in cands:
        if os.path.splitext(os.path.basename(exe))[0].lower() in data_names:
            return exe
    return cands[0]


class UnityTentacle(Tentacle):
    """Живой канал к Mono-игре, которую запустили мы."""

    key = "unity"
    title = "Unity"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._pid: int | None = None
        self._rpc = None
        self._rpc_error = ""
        self._owns_game = False

    # ── запуск ──────────────────────────────────────────────────────────────

    def launch(self, target: str) -> bool:
        exe = target
        if os.path.isdir(target):
            exe = find_launcher(target) or ""
        if not exe or not os.path.isfile(exe):
            self.error.emit(f"Не найден исполняемый файл игры: {target}")
            return False
        game_dir = os.path.dirname(exe)
        try:
            self._proc = subprocess.Popen([exe], cwd=game_dir)
        except OSError as e:
            self.error.emit(f"Не удалось запустить игру: {e}")
            return False
        self._pid, self._owns_game = self._proc.pid, True
        # Popen вернул pid сразу: процесс уже есть, ждать нечего
        try:
            alive = self._proc.poll() is None
        except OSError:
            alive = False
        if not alive:
            self.error.emit("Игра закрылась сразу после запуска.")
            self._proc = None
            self._pid = None
            self._owns_game = False
            return False
        registry.record_launch(self._pid, exe, game_dir)
        self.log.emit(f"Игра запущена (pid {self._pid}), подключаюсь "
                      f"к Mono-рантайму — это может занять до минуты.")
        ok = self._attach_rpc(self._pid, game_dir)
        if ok:
            self.attached.emit()
            self.log.emit("Канал к игре есть: читы работают.")
        else:
            # игра идёт, канала нет — не врать игроку; конкретная причина
            # уже в _rpc_error и уйдёт в статус дашборда
            self.log.emit("Игра запущена без живых читов: канал к процессу "
                          "не поднялся.")
        return True

    def _attach_rpc(self, pid: int, game_dir: str) -> bool:
        """Подключение с повторами: старт игры — гонка, первая попытка
        почти всегда падает (VirtualAllocEx в ранней инициации).

        Не-наша игра — отказ сразу, без повторов. Процесс умер —
        тоже сразу. Остальное — retry с нарастающей паузой.
        """
        from app.transport.unity_rpc.injector import UnityMonoRPC

        self._rpc_error = ""
        time.sleep(_SPAWN_SETTLE_S)
        start = time.monotonic()
        attempt = 0
        last_err = "канал не поднялся"
        while time.monotonic() - start < _ATTACH_TIMEOUT_S:
            attempt += 1
            # `launch()` даёт живой Popen. При переподключении к уже
            # запущенной игре Popen'а нет — тогда alive смотрим по
            # реестру, иначе цикл выходил бы с первой попытки, ни разу
            # не попробовав подключиться.
            if self._proc is not None:
                try:
                    alive = self._proc.poll() is None
                except OSError:
                    alive = False
            else:
                alive = registry.verify_launch(pid) is not None
            if not alive:
                last_err = "Игра закрылась до подключения."
                break
            rpc = UnityMonoRPC()
            try:
                rpc.attach(pid, game_dir)
            except Exception as e:  # noqa: BLE001
                last_err = str(e) or type(e).__name__
                if "не запущена через" in last_err:
                    break  # чужая — повторы бессмысленны
                self.log.emit(f"Попытка {attempt}: {last_err[:120]}")
                time.sleep(min(2.0 * attempt, 10.0))
                continue
            self._rpc = rpc
            self._rpc_error = ""
            return True
        self._rpc_error = f"Живой канал недоступен ({attempt} попыток): {last_err}"
        self.error.emit(self._rpc_error)
        return False

    def attach(self, pid: int) -> bool:
        """Подключиться к уже запущенной НАШЕЙ игре."""
        exe = registry.verify_launch(pid)
        if exe is None:
            self.error.emit("Подключение возможно только к игре, запущенной "
                            "через OctopusBridge — чужие процессы не "
                            "трогаем.")
            return False
        self._owns_game = False
        if not self._attach_rpc(pid, os.path.dirname(exe)):
            return False
        self._pid = int(pid)
        self.attached.emit()
        return True

    def detach(self):
        rpc, self._rpc = self._rpc, None
        if rpc is not None:
            try:
                rpc.detach()
            except Exception:
                pass
        self._owns_game = False
        self.detached.emit("")

    def is_attached(self) -> bool:
        return self._rpc is not None and self._rpc.is_attached()

    @property
    def rpc_error(self) -> str:
        """Почему канала нет — для честного статуса во вкладке читов.

        Раньше причина жила в приватном `_rpc_error`, и UI её не видел:
        вкладка писала «запустите игру» даже при обрушенном attach, и
        игрок бесконечно жал «Обновить».
        """
        return self._rpc_error

    def game_pid(self) -> int | None:
        if self._proc is not None:
            try:
                if self._proc.poll() is None:
                    return self._proc.pid
            except OSError:
                pass
        if self._rpc is not None:
            return self._rpc.pid
        return self._pid

    # ── читы ────────────────────────────────────────────────────────────────

    def request_state(self) -> bool:
        if not self.is_attached():
            return False
        try:
            self.state_received.emit(self._rpc.call("diagnose", {}))
        except Exception as e:
            self.error.emit(f"Состояние игры прочитать не удалось: {e}")
            return False
        return True

    def request_vars(self) -> bool:
        """Статические поля игровых классов (имена и значения).

        Только классы сборок игры (Assembly-CSharp и «наши» — не UnityEngine),
        иначе список превращается в простыню из 100 тысяч полей движка.
        """
        if not self.is_attached():
            return False
        try:
            rows = self.game_variables()
        except Exception as e:
            self.error.emit(f"Переменные игры прочитать не удалось: {e}")
            return False
        self.vars_received.emit(rows)
        return True

    def game_variables(self) -> list:
        """Статика игровых сборок — только чтение.

        Списки статик-полей больше не читятся как таковые: игрок ищет
        нужное значение сканером памяти (`scan_memory`), потому что
        адрес он определяет сам по поведению игры. Метод оставлен как
        диагностика (что вообще есть в сборках) и в UI не торчит.
        """
        asms = self._rpc.assemblies()
        game = [a for a in asms if not a.startswith(("Unity", "System",
                                                      "mscorlib", "Mono."))]
        rows: list = []
        for asm in game[:12]:
            try:
                res = self._rpc.call("statics", {"assembly": asm})
            except Exception:
                continue
            if not isinstance(res, dict) or res.get("error"):
                continue
            for entry in res.get("data") or []:
                cls = entry.get("class", "")
                ns = entry.get("ns", "")
                full = ("%s.%s" % (ns, cls)) if ns else cls
                for field in entry.get("fields") or []:
                    if field.get("value") is None:
                        continue
                    rows.append({
                        "assembly": asm,
                        "class": full,
                        "name": field.get("name", ""),
                        "type": field.get("type", ""),
                        "value": field.get("value"),
                    })
        return rows

    # ── сканер памяти ───────────────────────────────────────────────────────
    #
    # Единственный способ работать с игрой, который не ломает её: не
    # угадывать, что значит поле, а искать значение, которое игрок сам
    # называет, и сужать список повторным поиском.

    def scan_memory(self, value, kind: str = "i32") -> dict:
        """Найти все адреса, где лежит значение. {'data': [...], ...}"""
        if not self.is_attached():
            return {"error": "Нет канала к игре — запустите её здесь."}
        try:
            return self._rpc.call("scan", {"kind": kind, "value": value})
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def read_memory(self, addrs: list, kind: str = "i32") -> list:
        """Текущие значения по списку адресов (для сужения)."""
        if not self.is_attached() or not addrs:
            return []
        try:
            res = self._rpc.call("readMany", {"kind": kind,
                                              "addrs": list(addrs)})
        except Exception:  # noqa: BLE001
            return []
        return (res or {}).get("data") or []

    def write_memory(self, addr: str, value, kind: str = "i32") -> tuple:
        """Записать значение по адресу. (ok, сообщение)."""
        if not self.is_attached():
            return False, "нет канала к игре"
        try:
            res = self._rpc.call("writeMem", {
                "addr": addr, "kind": kind, "value": value})
        except Exception as e:  # noqa: BLE001
            return False, str(e)
        if not (res or {}).get("ok"):
            return False, str((res or {}).get("error", "запись не удалась"))
        return True, res.get("value")

    def set_variable(self, name: str, value) -> bool:
        """Записать статическое поле. name — 'Сборка|Класс|поле'."""
        if not self.is_attached():
            return False
        parts = str(name).split("|")
        if len(parts) != 3:
            self.error.emit("Ожидается 'Сборка|Класс|поле'.")
            return False
        asm, cls, field = parts
        ns = ""
        if "." in cls:
            ns, cls = cls.split(".", 1)
        try:
            res = self._rpc.call("writeStatic", {
                "assembly": asm, "ns": ns, "name": cls,
                "field": field, "value": value})
        except Exception as e:
            self.error.emit(f"Запись в игру не удалась: {e}")
            return False
        ok = bool(res and res.get("ok"))
        self.cheat_ack.emit("var_set", ok,
                            "" if ok else (res or {}).get("error", "?"), "")
        return ok

    def send_cheat(self, cmd: str, **kwargs) -> bool:
        if not self.is_attached():
            return False
        if cmd == "var_set":
            return self.set_variable(kwargs.get("name", ""),
                                     kwargs.get("value"))
        if cmd == "reload":
            return self.request_vars()
        self.cheat_ack.emit(cmd, False, "unknown cmd", "")
        return False

    def send_key(self, key, code, keyCode, windowsKeyCode) -> bool:
        # инъекция ввода в Unity — отдельная задача; не делаем вид
        return False

    def screenshot(self):
        return None