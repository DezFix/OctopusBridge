# -*- coding: utf-8 -*-
"""Live-читы Unity через Mono-рантайм: реестр запусков.

Правило проекта (AGENTS.md §1): доступ в процесс игры — **только к тем
играм, которые запустило само приложение**. Контроль двойной:

1. реестр запусков `unity_launches.json` в `%APPDATA%\\OctopusBridge` —
   pid, путь к exe, папка игры, время запуска;
2. сверка с живым процессом — exe-путь обязан совпадать с записанным
   (защита от переиспользования pid, см. `terminate(pid, expected_dir)`).

`attach()` без записи в реестре откажет **до** любого прикосновения к
процессу. Re-attach после перезапуска приложения возможен, потому что
реестр переживает перезапуск; чужая игра в него не попадает никогда.
"""
from __future__ import annotations

import json
import os
import time

_LAUNCHES = "unity_launches.json"
#: запись старше этого — считаем мусором (приложение не вечно)
MAX_AGE_S = 14 * 24 * 3600


def launches_path() -> str:
    from app import user_data_dir

    return os.path.join(user_data_dir(), _LAUNCHES)


def record_launch(pid: int, exe_path: str, game_dir: str) -> None:
    """Запомнить: этот pid — наша игра. Вызывать сразу после Popen."""
    path = launches_path()
    rows = _load(path)
    rows[str(pid)] = {
        "pid": int(pid),
        "exe": os.path.abspath(exe_path or ""),
        "game_dir": os.path.abspath(game_dir or ""),
        "at": int(time.time()),
    }
    _save(path, rows)


def forget_launch(pid: int) -> None:
    """Убрать запись (игра закрыта штатно или мы отвязались)."""
    path = launches_path()
    rows = _load(path)
    if rows.pop(str(pid), None) is not None:
        _save(path, rows)


def clean_stale() -> None:
    """Выкинуть записи о процессах, которых уже нет."""
    try:
        import psutil
    except Exception:
        return
    path = launches_path()
    rows = _load(path)
    alive = {p.pid for p in psutil.process_iter(["pid"])}
    keep = {k: v for k, v in rows.items()
            if int(v.get("pid", -1)) in alive
            and time.time() - float(v.get("at", 0)) < MAX_AGE_S}
    if len(keep) != len(rows):
        _save(path, keep)


def our_launches() -> list[dict]:
    """Наши живые запуски (без очистки мусора показа)."""
    clean_stale()
    return list(_load(launches_path()).values())


def verify_launch(pid: int, game_dir: str | None = None) -> str | None:
    """Путь к exe НАШЕГО процесса или None (это не наша игра).

    Проверяем и запись, и живой процесс: exe-путь обязан совпадать с
    записанным. Не совпал — pid занят другой программой.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    rows = _load(launches_path())
    row = rows.get(str(pid))
    if not row:
        return None
    if game_dir and os.path.abspath(game_dir) != row.get("game_dir"):
        return None
    try:
        import psutil

        proc = psutil.Process(pid)
        live = proc.exe()
    except Exception:
        return None
    if not live:
        return None
    if os.path.normcase(os.path.normpath(live)) != os.path.normcase(
            os.path.normpath(row.get("exe", ""))):
        return None
    return live


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(obj, dict):
        return {}
    out = {}
    for key, val in obj.items():
        if isinstance(val, dict) and isinstance(val.get("pid"), int):
            out[str(key)] = val
    return out


def _save(path: str, rows: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass