# -*- coding: utf-8 -*-
"""GameSession — сессия работы с живой игрой: одно щупальце + watchdog.

Новый дом live-слоя (модульный монолит): раньше жила в
app.core.session и тянула Qt в ядро. Теперь живет здесь,
в app/live, рядом со щупальцами.

Сессия — стабильная точка подписки для UI: щупальца могут пересоздаваться
(перезапуск игры, смена движка), сессия остаётся. Ретранслирует сигналы
текущего щупальца и следит, не умер ли процесс игры.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QTimer, Qt, Signal

from app.core import process as proc
from app.live.tentacle import Tentacle


class _SessionRelay(QObject):
    def __init__(self, session, tentacle):
        super().__init__(session)
        self._session = session
        self._tentacle = tentacle

    def attached(self):
        self._session._forward(self._tentacle, self._session.attached)

    def detached(self, reason):
        self._session._forward(
            self._tentacle, self._session.detached, reason)

    def log(self, text):
        self._session._forward(self._tentacle, self._session.log, text)

    def vars_received(self, value):
        self._session._forward(
            self._tentacle, self._session.vars_received, value)

    def state_received(self, value):
        self._session._forward(
            self._tentacle, self._session.state_received, value)

    def cheat_ack(self, cmd, ok, error, value):
        self._session._forward(
            self._tentacle, self._session.cheat_ack, cmd, ok, error, value)

    def error(self, text):
        self._session._forward(self._tentacle, self._session.error, text)


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
        self._game_dir = ""          # папка нашей игры для terminate-защиты
        self._connect_owner: Tentacle | None = None
        self._relay: _SessionRelay | None = None
        self._relay_slots: list[tuple] = []
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(2000)
        self._watchdog.timeout.connect(self._check_alive)

    # ── текущее щупальце ──
    @property
    def tentacle(self) -> Tentacle | None:
        return self._tentacle

    def is_active(self) -> bool:
        if self._tentacle is None:
            return False
        try:
            return bool(self._tentacle.is_attached())
        except Exception:  # noqa: BLE001
            return False

    def is_game_running(self) -> bool:
        """Процесс игры жив (даже без CDP-подключения — перевод идёт
        через ob_runtime.js, читы недоступны)."""
        pid = None
        if self._tentacle is not None:
            try:
                pid = self._tentacle.game_pid()
            except Exception:  # noqa: BLE001
                pid = None
        pid = pid or self._pid
        return bool(pid and proc.pid_exists(pid))

    def send_key(self, key: str, code: str = "", keyCode: int = 0,
                 windowsKeyCode: int = 0) -> bool:
        if self._tentacle:
            return self._tentacle.send_key(key, code, keyCode, windowsKeyCode)
        return False

    def begin_pending(self, tentacle: Tentacle):
        self._bind(tentacle)
        self._connect_owner = tentacle
        return tentacle

    def finish_launch(self, tentacle: Tentacle, ok: bool) -> bool:
        if self._tentacle is not tentacle:
            self._discard(tentacle)
            return False
        self._connect_owner = None
        try:
            pid = tentacle.game_pid()
        except Exception:  # noqa: BLE001
            pid = None
        if pid:
            self._pid = pid
            self._owns_game = True
            self._watchdog.start()
        if not ok and not pid:
            self._unbind(expected=tentacle)
            return False
        return bool(ok)

    def finish_attach(self, tentacle: Tentacle, pid: int, ok: bool) -> bool:
        if self._tentacle is not tentacle:
            self._discard(tentacle)
            return False
        self._connect_owner = None
        if not ok:
            self._unbind(expected=tentacle)
            return False
        self._pid = pid
        self._owns_game = False
        self._watchdog.start()
        return True

    def launch(self, tentacle: Tentacle, target: str, guard=None) -> bool:
        """Запускает игру через щупальце и берёт процесс под наблюдение."""
        if guard is not None and not guard():
            self._discard(tentacle)
            return False
        # target — папка игры: запоминаем для terminate-защиты в stop()
        # (PID мог переиспользоваться ОС под чужой процесс).
        try:
            self._game_dir = target if target and os.path.isdir(target) else ""
        except (ValueError, OSError):
            self._game_dir = ""
        self.begin_pending(tentacle)
        ok = bool(tentacle.launch(target))
        if guard is not None and not guard():
            self._unbind(expected=tentacle)
            self._discard(tentacle)
            return False
        return self.finish_launch(tentacle, ok)

    def attach(self, tentacle: Tentacle, pid: int, guard=None) -> bool:
        """Подключается к уже запущенному процессу (не наш — не трогаем)."""
        if guard is not None and not guard():
            self._discard(tentacle)
            return False
        self.begin_pending(tentacle)
        ok = bool(tentacle.attach(pid))
        if guard is not None and not guard():
            self._unbind(expected=tentacle)
            self._discard(tentacle)
            return False
        return self.finish_attach(tentacle, pid, ok)

    def reconnect(self, start_watchdog: bool = True) -> bool:
        tentacle = self._tentacle
        pid = self._pid
        if tentacle is None or not pid or self._connect_owner is not None:
            return False
        try:
            if tentacle.is_attached():
                return True
        except Exception:  # noqa: BLE001
            pass
        self._connect_owner = tentacle
        try:
            ok = bool(tentacle.attach(pid))
        except Exception:  # noqa: BLE001
            ok = False
        finally:
            if self._connect_owner is tentacle:
                self._connect_owner = None
        if ok and start_watchdog:
            self._watchdog.start()
        return ok

    def start_watchdog(self):
        self._watchdog.start()

    # ── остановка ──
    def stop(self, kill_game: bool = False):
        self._watchdog.stop()
        self._connect_owner = None
        # Папку не запомнили (target был файлом) — сверить exe не с
        # чем: убивать по голому PID запрещено, чужой процесс не трогаем.
        if kill_game and self._owns_game and self._pid and self._game_dir:
            # Защита от убийства чужого процесса: если игра вышла и ОС
            # переиспользовала PID, живой exe не совпадёт с папкой нашей
            # игры — terminate вернёт False и ничего не тронет.
            try:
                proc.terminate(self._pid, expected_dir=self._game_dir)
            except TypeError:
                # мок в старых тестах без expected_dir — старый вызов
                proc.terminate(self._pid)
        self._unbind()
        self._pid = None
        self._owns_game = False
        self._game_dir = ""

    # ── внутреннее ──
    def _bind(self, tentacle: Tentacle):
        self._unbind()
        self._tentacle = tentacle
        self._relay = _SessionRelay(self, tentacle)
        self._relay_slots = [
            (tentacle.attached, self._relay.attached),
            (tentacle.detached, self._relay.detached),
            (tentacle.log, self._relay.log),
            (tentacle.vars_received, self._relay.vars_received),
            (tentacle.state_received, self._relay.state_received),
            (tentacle.cheat_ack, self._relay.cheat_ack),
            (tentacle.error, self._relay.error),
        ]
        for signal, slot in self._relay_slots:
            signal.connect(slot, Qt.QueuedConnection)

    def _forward(self, tentacle: Tentacle, signal, *args):
        if self._tentacle is tentacle:
            signal.emit(*args)

    def _unbind(self, expected: Tentacle | None = None,
                notify: bool = True):
        t = self._tentacle
        if expected is not None and t is not expected:
            return
        slots = self._relay_slots
        relay = self._relay
        self._relay_slots = []
        self._relay = None
        self._tentacle = None
        if t:
            try:
                t.detach()
            except Exception:  # noqa: BLE001
                pass
            for signal, slot in slots:
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            if relay is not None:
                try:
                    relay.deleteLater()
                except RuntimeError:
                    pass
            self._dispose(t)
            if notify:
                self.detached.emit("")

    def _discard(self, tentacle: Tentacle):
        try:
            tentacle.detach()
        except Exception:  # noqa: BLE001
            pass
        self._dispose(tentacle)

    def discard(self, tentacle: Tentacle):
        if self._tentacle is tentacle:
            self._unbind(expected=tentacle)
        else:
            self._discard(tentacle)

    @staticmethod
    def _dispose(tentacle: Tentacle):
        try:
            tentacle.setParent(None)
        except RuntimeError:
            pass
        try:
            tentacle.deleteLater()
        except RuntimeError:
            pass

    def _check_alive(self):
        if self._pid and not proc.pid_exists(self._pid):
            pid = self._pid
            self.stop(kill_game=False)
            self._pid = pid  # stop() сбросил; восстановим для сообщения
            self.log.emit(f"Процесс игры завершился (pid {pid}).")
            self.game_exited.emit()
            self._pid = None
