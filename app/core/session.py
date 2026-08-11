# -*- coding: utf-8 -*-
"""GameSession — сессия работы с живой игрой: одно щупальце + watchdog.

Сессия — стабильная точка подписки для UI: щупальца могут пересоздаваться
(перезапуск игры, смена движка), сессия остаётся. Ретранслирует сигналы
текущего щупальца и следит, не умер ли процесс игры.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from app.core import process as proc
from app.core.tentacles.base import Tentacle


class GameSession(QObject):
    # ретрансляция сигналов щупальца
    attached = Signal()
    detached = Signal(str)
    log = Signal(str)
    vars_received = Signal(object)
    state_received = Signal(object)
    cheat_ack = Signal(str, bool, str, str)
    error = Signal(str)
    game_exited = Signal()           # процесс игры завершился

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tentacle: Tentacle | None = None
        self._pid: int | None = None
        self._owns_game = False      # игру запустили мы (можно закрыть)
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(2000)
        self._watchdog.timeout.connect(self._check_alive)

    # ── текущее щупальце ──
    @property
    def tentacle(self) -> Tentacle | None:
        return self._tentacle

    def is_active(self) -> bool:
        return self._tentacle is not None and self._tentacle.is_attached()

    def is_connecting(self) -> bool:
        """Щупальце создано, но подключение ещё идёт (гонка автопоимки)."""
        return self._tentacle is not None

    def owns_game(self) -> bool:
        return self._owns_game

    def send_key(self, key: str, code: str = "", keyCode: int = 0,
                 windowsKeyCode: int = 0) -> bool:
        if self._tentacle:
            return self._tentacle.send_key(key, code, keyCode, windowsKeyCode)
        return False

    # ── запуск/подключение ──
    def launch(self, tentacle: Tentacle, target: str) -> bool:
        """Запускает игру через щупальце и берёт процесс под наблюдение."""
        self._bind(tentacle)
        if not tentacle.launch(target):
            self._unbind()
            return False
        self._pid = tentacle.game_pid()
        self._owns_game = True
        self._watchdog.start()
        return True

    def attach(self, tentacle: Tentacle, pid: int) -> bool:
        """Подключается к уже запущенному процессу (не наш — не трогаем)."""
        self._bind(tentacle)
        if not tentacle.attach(pid):
            self._unbind()
            return False
        self._pid = pid
        self._owns_game = False
        self._watchdog.start()
        return True

    # ── остановка ──
    def stop(self, kill_game: bool = False):
        self._watchdog.stop()
        if kill_game and self._owns_game and self._pid:
            proc.terminate(self._pid)
        self._unbind()
        self._pid = None
        self._owns_game = False

    # ── внутреннее ──
    def _bind(self, tentacle: Tentacle):
        self._unbind()
        self._tentacle = tentacle
        tentacle.attached.connect(self.attached)
        tentacle.detached.connect(self.detached)
        tentacle.log.connect(self.log)
        tentacle.vars_received.connect(self.vars_received)
        tentacle.state_received.connect(self.state_received)
        tentacle.cheat_ack.connect(self.cheat_ack)
        tentacle.error.connect(self.error)

    def _unbind(self):
        t = self._tentacle
        if t:
            try:
                t.detach()
            except Exception:  # noqa: BLE001
                pass
            t.setParent(None)
            t.deleteLater()
        self._tentacle = None

    def _check_alive(self):
        if self._pid and not proc.pid_exists(self._pid):
            pid = self._pid
            self.stop(kill_game=False)
            self._pid = pid  # stop() сбросил; восстановим для сообщения
            self.log.emit(f"Процесс игры завершился (pid {pid}).")
            self.game_exited.emit()
            self._pid = None
