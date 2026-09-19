# -*- coding: utf-8 -*-
"""Щупальце Wolf RPG Editor: запуск/останов нативного процесса.

Живого канала в процесс нет (движок — закрытый нативный exe, не
Chromium и не Ren'Py): is_attached() всегда False, читы недоступны.
Щупальце нужно сессии для запуска игры из приложения и watchdog'а
(корректная кнопка «Стоп», статус в дашборде). Перевод — файловый
(loose-Data/), шрифт — заменой TTF (после перезапуска).
"""
from __future__ import annotations

import glob
import os
import subprocess

from app.core.tentacles.base import Tentacle


def find_launcher(game_dir: str) -> str | None:
    """Исполняемый файл игры (Game.exe либо первый не-хелпер exe)."""
    for name in ("Game.exe", "game.exe"):
        exe = os.path.join(game_dir, name)
        if os.path.isfile(exe):
            return exe
    helpers = {"config", "setup", "uninstall", "unins000", "dxsetup"}
    cands = sorted(glob.glob(os.path.join(game_dir, "*.exe")))
    for exe in cands:
        base = os.path.splitext(os.path.basename(exe))[0].lower()
        if base not in helpers:
            return exe
    return cands[0] if cands else None


class WolfTentacle(Tentacle):
    key = "wolf"
    title = "Wolf RPG"

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
                      f"Живые читы для Wolf RPG недоступны — "
                      f"перевод файловый, шрифт после перезапуска.")
        return True

    def attach(self, pid: int) -> bool:
        self.error.emit("Wolf RPG: подключение к запущенной игре "
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
