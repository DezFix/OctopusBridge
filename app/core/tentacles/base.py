# -*- coding: utf-8 -*-
"""Щупальце (Tentacle) — канал управления живым процессом игры.

OctopusBridge не модифицирует файлы игры ради реалтайма: каждое
щупальце подключается к запущенному процессу снаружи
(CDP для Chromium-based движков, Frida для Ren'Py) и предоставляет
ядру единый API: перехват текста для перевода, переменные, читы.

Жизненный цикл:
    tentacle = SomeTentacle()
    tentacle.set_translate_fn(fn)      # fn(text) -> str, None — выкл
    tentacle.launch(target)            # запустить игру и подключиться
    # ...или...
    tentacle.attach(pid)               # подключиться к уже запущенной
    tentacle.detach()                  # отпустить (игра продолжает жить)
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal

TranslateFn = Callable[[str], str]


class Tentacle(QObject):
    key: str = "base"                  # 'rpgmaker' | 'twine' | 'renpy'
    title: str = "Базовое щупальце"

    # ── сигналы для UI/ядра ──
    attached = Signal()
    detached = Signal(str)             # причина ('' = штатно)
    log = Signal(str)
    text_seen = Signal(str, str)       # оригинал, перевод (для лога GUI)
    # object вместо dict/list: при межпоточной доставке Qt иначе пытается
    # копировать контейнер в C++ и ругается в консоль (Shiboken warning)
    vars_received = Signal(object)     # [{"name": str, "value": ..., "type": str}]
    state_received = Signal(object)    # полный снимок состояния игры
    cheat_ack = Signal(str, bool, str, str)  # cmd, ok, error, value(json)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._translate_fn: TranslateFn | None = None
        self._translation_enabled = True

    # ── перевод ──
    def set_translate_fn(self, fn: TranslateFn | None):
        """Устанавливает функцию перевода. None — возвращать оригинал."""
        self._translate_fn = fn

    def set_translation_enabled(self, enabled: bool):
        """Вкл/выкл перевод на лету, не отключая щупальце: читы и
        переменные продолжают работать, текст возвращается как есть."""
        self._translation_enabled = bool(enabled)

    def translate(self, text: str) -> str:
        """Переводит текст текущей функцией; при любой ошибке — оригинал."""
        if (not self._translation_enabled or not self._translate_fn
                or not text):
            return text
        try:
            return self._translate_fn(text)
        except Exception:  # noqa: BLE001
            return text

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
