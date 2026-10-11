# -*- coding: utf-8 -*-
"""Подключение к Mono-игре: Frida + реестр наших запусков.

Правило проекта: в процесс лезем **только** если игру запустили мы.
`attach()` без записи в реестре откажет до `frida.attach` — не попробует
и не откатится, а откажет сразу.
"""
from __future__ import annotations

import time

from app.transport.unity_rpc import registry

#: сколько ждать, пока игра поднимет Mono (холодный старт, большие игры)
MONO_WAIT_S = 60.0
MONO_POLL_S = 0.5


class UnityRPCError(RuntimeError):
    """Игра не готова, Mono не поднялся или поле недоступно."""


class UnityMonoRPC:
    """Живой канал к Mono-игре: диагностика, классы, статические поля."""

    def __init__(self):
        self._pid: int | None = None
        self._session = None
        self._script = None

    # ── подключение ─────────────────────────────────────────────────────────

    def attach(self, pid: int, game_dir: str | None = None) -> bool:
        """Присоединиться к НАШЕЙ игре. False — не наша/не получилось."""
        from app.transport.unity_rpc.agent import _HELPER_JS

        exe = registry.verify_launch(pid, game_dir)
        if exe is None:
            raise UnityRPCError(
                "Игра не запущена через OctopusBridge — подключаться "
                "к чужим процессам приложение не будет.")
        try:
            import frida
        except Exception as e:
            raise UnityRPCError("Frida недоступен: %s" % e) from e
        try:
            device = frida.get_local_device()
            session = device.attach(int(pid))
            try:
                script = session.create_script(_HELPER_JS)
                script.load()
            except Exception:
                # полуживая сессия не должна висеть для retry
                try:
                    session.detach()
                except Exception:
                    pass
                raise
        except UnityRPCError:
            raise
        except Exception as e:
            raise UnityRPCError("Не удалось подключиться: %s" % e) from e
        self._pid, self._session, self._script = int(pid), session, script
        if not self._wait_mono():
            # Mono ещё не поднялся (ранний старт) — сессию бросаем, но
            # запись в реестре НЕ трогаем: это наша игра, будет retry.
            self.detach(forget=False)
            raise UnityRPCError(
                "Mono-рантайм не поднялся за %.0f с — игра ещё "
                "загружается, попробуйте обновить чуть позже."
                % MONO_WAIT_S)
        return True

    def _wait_mono(self) -> bool:
        deadline = time.monotonic() + MONO_WAIT_S
        while time.monotonic() < deadline:
            try:
                if self.call("diagnose", {}).get("hasMono"):
                    return True
            except Exception:
                pass
            time.sleep(MONO_POLL_S)
        return False

    def detach(self, forget: bool = True):
        """Отвязаться. forget=False — бросить попытку, но запись
        в реестре наших запусков оставить (будет retry)."""
        for closer in (getattr(self._script, "unload", None),):
            try:
                if callable(closer):
                    closer()
            except Exception:
                pass
        try:
            if self._session is not None:
                self._session.detach()
        except Exception:
            pass
        if forget and self._pid is not None:
            registry.forget_launch(self._pid)
        self._pid = self._session = self._script = None

    def is_attached(self) -> bool:
        if self._script is None:
            return False
        try:
            return bool(self.call("alive", {}))
        except Exception:
            return False

    @property
    def pid(self) -> int | None:
        return self._pid

    # ── вызовы ──────────────────────────────────────────────────────────────

    def call(self, export: str, payload: dict):
        if self._script is None:
            raise UnityRPCError("Нет подключения к игре.")
        fn = getattr(self._script.exports_sync, export, None)
        if fn is None:
            raise UnityRPCError("Агент не умеет %s" % export)
        return fn(payload)

    #: тонкие обёртки — чтобы UI не знал про rpc.exports
    def diagnose(self) -> dict:
        return self.call("diagnose", {})

    def assemblies(self) -> list:
        return self.call("assemblies", {})
