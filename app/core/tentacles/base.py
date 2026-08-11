# -*- coding: utf-8 -*-
"""Щупальце (Tentacle) — канал управления живым процессом игры.

OctopusBridge не модифицирует файлы игры ради реалтайма: каждое
щупальце подключается к запущенному процессу снаружи
(CDP для Chromium-based движков, Frida для Ren'Py) и предоставляет
ядру единый API: переменные, читы, состояние игры.

Жизненный цикл:
    tentacle = SomeTentacle()
    tentacle.launch(target)            # запустить игру и подключиться
    # ...или...
    tentacle.attach(pid)               # подключиться к уже запущенной
    tentacle.detach()                  # отпустить (игра продолжает жить)
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class Tentacle(QObject):
    key: str = "base"                  # 'rpgmaker' | 'twine' | 'renpy'
    title: str = "Базовое щупальце"

    # ── сигналы для UI/ядра ──
    attached = Signal()
    detached = Signal(str)             # причина ('' = штатно)
    log = Signal(str)
    # object вместо dict/list: при межпоточной доставке Qt иначе пытается
    # копировать контейнер в C++ и ругается в консоль (Shiboken warning)
    vars_received = Signal(object)     # [{"name": str, "value": ..., "type": str}]
    state_received = Signal(object)    # полный снимок состояния игры
    cheat_ack = Signal(str, bool, str, str)  # cmd, ok, error, value(json)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    # ── жизненный цикл (реализуют наследники) ──
    def launch(self, target: str) -> bool:
        """Запустить игру (путь к exe / html) и подключиться к ней."""
        raise NotImplementedError

    def attach(self, pid: int) -> bool:
        """Подключиться к уже запущенному процессу."""
        raise NotImplementedError

    def detach(self):
        """Отключиться от процесса (игра НЕ завершается)."""
        raise NotImplementedError

    def is_attached(self) -> bool:
        raise NotImplementedError

    def game_pid(self) -> int | None:
        """PID процесса игры, если известен (для watchdog)."""
        return None

    # ── переменные и читы (реализуют наследники) ──
    def request_state(self) -> bool:
        """Запросить полный снимок состояния (ответ — state_received)."""
        return False

    def request_vars(self) -> bool:
        """Запросить список игровых переменных (ответ — vars_received)."""
        return False

    def set_variable(self, name: str, value) -> bool:
        """Установить переменную/переключатель внутри игры."""
        return False

    def send_cheat(self, cmd: str, **kwargs) -> bool:
        """Выполнить чит-команду (ответ — cheat_ack)."""
        return False

    def send_key(self, key: str, code: str = "", keyCode: int = 0,
                 windowsKeyCode: int = 0) -> bool:
        """Отправить нажатие клавиши в игру."""
        return False
