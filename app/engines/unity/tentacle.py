# -*- coding: utf-8 -*-
"""Щупальце Unity: запуск/останов нативного процесса (как у Wolf).

Живого канала в процесс нет (закрытый Unity-плеер): is_attached()
всегда False, читы недоступны. Щупальце нужно сессии для запуска игры
из приложения и watchdog'а (кнопка «Стоп», статус в дашборде).
Перевод — файловый (.assets/level), шрифт — будущий патч.
"""
from __future__ import annotations

import glob
import os
import subprocess

from app.core.tentacles.base import Tentacle

# Хелперы рядом с игрой — не игра.
_HELPERS = {"unitycrashhandler", "unitycrashhandler64", "config", "setup",
            "uninstall", "unins000", "dxsetup"}


def find_launcher(game_dir: str) -> str | None:
    """Исполняемый файл Unity-игры.

    Приоритет: <Name>.exe, совпадающий с <Name>_Data (стандартная
    сборка Unity), затем первый не-хелпер exe.
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
    key = "unity"
    title = "Unity"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._pid: int | None = None

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
        self._pid = self._proc.pid
        self.log.emit(f"Игра запущена (pid {self._pid}). "
                      f"Живые читы для Unity недоступны — "
                      f"перевод файловый.")
        return True

    def attach(self, pid: int) -> bool:
        self.error.emit("Unity: подключение к запущенной игре "
                        "не поддерживается (нет канала в процесс). "
                        "Запустите игру через OctopusBridge.")
        return False

    def detach(self):
        self._proc = None
        self._pid = None
        self.detached.emit("")

    def is_attached(self) -> bool:
        return False

    def game_pid(self) -> int | None:
        if self._proc is not None:
            try:
                if self._proc.poll() is None:
                    return self._proc.pid
            except OSError:
                pass
        return self._pid
