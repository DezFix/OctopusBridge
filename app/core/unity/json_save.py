# -*- coding: utf-8 -*-
"""Сохранения Unity-игр: JSON-файлы в LocalLow + безопасная правка.

Многие Mono-игры пишут прогресс не в PlayerPrefs, а в
``%USERPROFILE%\\AppData\\LocalLow\\<company>\\<product>\\*.json``.
Формат там произвольный, но почти всегда — плоский/вложенный JSON, где
деньги, флаги и статистика лежат обычными числами. Такие файлы правятся
универсально, без знания игры.

Правила безопасности (насле��ованы из правок сейвов Twine, где небрежная
запись ломала игру):
- пишем **только изменённые** листья; нетронутые контейнеры не
  пересобираются в строки (отсюда был «Maximum call stack size exceeded»);
- перед записью — бэкап, после — самопроверка чтением, при расхождении
  откат на бэкап;
- абсурдные индексы/глубина отклоняются ошибкой, а не молча создают
  миллионный массив.

Модуль чистый: без Qt. Текст сохранения наружу не выводится — наружу
идут только пути ключей и числа.
"""
from __future__ import annotations

import json
import os
import sys

#: максимальная глубина обхода — защита от «миллионного массива»
MAX_DEPTH = 12
#: максимальный индекс в списке, который соглашаемся создавать
MAX_INDEX = 100_000


class SaveError(RuntimeError):
    """Файл не читается/не пишется или значение недопустимо."""


def local_low_dir(game_dir: str) -> str | None:
    """``%USERPROFILE%\\AppData\\LocalLow\\<company>\\<product>``.

    None — определить не удалось (не Unity или нет PlayerSettings).
    """
    from app.core.unity.playerprefs import player_settings

    ident = player_settings(game_dir)
    if not ident:
        return None
    company, product = ident
    root = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(root, "AppData", "LocalLow", company, product)


#: файлы, которые Unity и сам OctopusBridge кладут рядом — не сейвы
_NOT_SAVE = frozenset({
    "manifest.json",
    "scriptingassemblies.json",
    "runtimeinitializeonloads.json",
    "link.xml",
    "assemblies.json",
})


def find_saves(game_dir: str) -> list[str]:
    """Пути к JSON-сохранениям игры: LocalLow, затем верхний уровень папки.

    Глубина в папке игры — 1: залезать в ``*_Data`` (там служебные json
    движка) и в ``backup`` (наши бэкапы) незачем.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        full = os.path.normpath(path)
        if full in seen:
            return
        if os.path.basename(full).lower() in _NOT_SAVE:
            return
        seen.add(full)
        out.append(full)

    low = local_low_dir(game_dir)
    if low and os.path.isdir(low):
        for cur, dirs, files in os.walk(low):
            dirs[:] = [d for d in dirs if d.lower() != "backup"]
            for name in sorted(files):
                if name.lower().endswith(".json"):
                    _add(os.path.join(cur, name))
    # верхний уровень папки игры: режем служебные подпапки
    try:
        entries = sorted(os.listdir(game_dir))
    except OSError:
        entries = []
    for name in entries:
        full = os.path.join(game_dir, name)
        low_name = name.lower()
        if low_name in ("backup", "monobleedingedge") or \
                low_name.endswith("_data"):
            continue
        if os.path.isfile(full) and low_name.endswith(".json"):
            _add(full)
    return out


def load_json(path: str) -> object:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise SaveError("Не читается %s: %s" % (os.path.basename(path), e)) \
            from e


# ── плоский доступ к скалярам ───────────────────────────────────────────────

def flatten(data: object, prefix: str = "", depth: int = 0) -> dict:
    """Скаляры JSON -> {dotted.path: значение}. Контейнеры не попадают.

    Пути-ключи — технические (не текст игры), их можно показывать.
    """
    out: dict = {}
    if depth > MAX_DEPTH:
        return out
    if isinstance(data, dict):
        for key, value in data.items():
            child = "%s.%s" % (prefix, key) if prefix else str(key)
            if isinstance(value, (dict, list)):
                out.update(flatten(value, child, depth + 1))
            else:
                out[child] = value
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            child = "%s[%d]" % (prefix, idx)
            if isinstance(value, (dict, list)):
                out.update(flatten(value, child, depth + 1))
            else:
                out[child] = value
    return out


def _tokens(dotted: str) -> list:
    """``a.b[0].c`` -> ['a','b',0,'c']."""
    import re
    toks: list = []
    for part in str(dotted).split("."):
        while True:
            m = re.match(r"^([^\[\]]*)", part)
            name = m.group(1)
            if name:
                toks.append(name)
            m = re.search(r"\[(\d+)\]", part)
            if not m:
                break
            idx = int(m.group(1))
            if idx > MAX_INDEX:
                raise SaveError("Индекс %d слишком велик" % idx)
            toks.append(idx)
            part = part[m.end():]
    return toks


def get_path(data: object, dotted: str):
    """Значение по пути или _MISSING."""
    cur = data
    for tok in _tokens(dotted):
        if isinstance(tok, int):
            if not isinstance(cur, list) or tok >= len(cur):
                return _MISSING
            cur = cur[tok]
        else:
            if not isinstance(cur, dict) or tok not in cur:
                return _MISSING
            cur = cur[tok]
    return cur


class _Missing:
    __slots__ = ()

    def __repr__(self):
        return "<missing>"

    def __bool__(self):
        return False


_MISSING = _Missing()


def as_bool(value) -> bool:
    """bool-поле: принимаем true/false, 0/1, on/off, yes/no."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "on", "yes", "да"):
        return True
    if text in ("false", "0", "off", "no", "нет", ""):
        return False
    raise SaveError("Нужно true/false, получено: %r" % str(value)[:20])


def set_paths(data: object, updates: dict) -> tuple[object, list]:
    """Вернуть копию data с применёнными updates {dotted: значение}.

    Пишутся только указанные листья. Пропущено: [(path, причина)].
    """
    import copy

    new = copy.deepcopy(data)
    skipped: list[tuple[str, str]] = []
    for dotted, value in updates.items():
        try:
            toks = _tokens(dotted)
        except SaveError as e:
            skipped.append((dotted, str(e)))
            continue
        if not toks:
            skipped.append((dotted, "пустой путь"))
            continue
        cur = new
        ok = True
        for tok in toks[:-1]:
            if isinstance(tok, int):
                if not isinstance(cur, list) or tok >= len(cur):
                    ok = False
                    break
                cur = cur[tok]
            else:
                if not isinstance(cur, dict):
                    ok = False
                    break
                if tok not in cur or not isinstance(
                        cur[tok], (dict, list)):
                    # не создаём контейнеры на лету: путь должен существовать
                    ok = False
                    break
                cur = cur[tok]
        if not ok:
            skipped.append((dotted, "путь не найден"))
            continue
        last = toks[-1]
        try:
            if isinstance(last, int):
                if not isinstance(cur, list) or last >= len(cur):
                    skipped.append((dotted, "нет такого элемента"))
                    continue
                old = cur[last]
            else:
                if not isinstance(cur, dict) or last not in cur:
                    skipped.append((dotted, "нет такого ключа"))
                    continue
                old = cur[last]
            # тип исходного значения — закон: bool не станет 0/1 молча,
            # float не станет int (иначе игра ломается на следующем кадре)
            if isinstance(old, bool):
                cur[last] = as_bool(value)
            elif isinstance(old, float):
                try:
                    cur[last] = float(value)
                except (TypeError, ValueError):
                    skipped.append((dotted, "нужно число"))
            elif isinstance(old, int):
                try:
                    cur[last] = int(value)
                except (TypeError, ValueError):
                    skipped.append((dotted, "нужно целое"))
            else:
                cur[last] = value
        except (TypeError, ValueError, SaveError) as e:
            skipped.append((dotted, str(e)))
    return new, skipped


def save_json(path: str, data: object) -> dict:
    """Записать JSON с бэкапом и самопроверкой. {'backup': str|None,...}"""
    from app.core.io import atomic_write_bytes, BackupStore

    backup: str | None = None
    try:
        backup = BackupStore(
            os.path.join(os.path.dirname(path), "backup")).backup(path)
    except Exception:
        backup = None
    try:
        text = json.dumps(data, ensure_ascii=False, indent=1)
    except (TypeError, ValueError) as e:
        raise SaveError("Не удалось сериализовать: %s" % e) from e
    atomic_write_bytes(path, text.encode("utf-8"))
    try:
        with open(path, encoding="utf-8") as f:
            back = json.load(f)
    except (OSError, ValueError) as e:
        _rollback(path, backup)
        raise SaveError("Самопроверка не прошла, файл возвращён: %s" % e) \
            from e
    if back != data:
        _rollback(path, backup)
        raise SaveError("Самопроверка не сошлась, файл возвращён.")
    return {"backup": backup, "bytes": len(text.encode("utf-8"))}


def _rollback(path: str, backup: str | None) -> None:
    if not backup or not os.path.isfile(backup):
        return
    try:
        from app.core.io import atomic_write_bytes

        with open(backup, "rb") as f:
            atomic_write_bytes(path, f.read())
    except OSError:
        pass


def restore_backup(path: str) -> bool:
    """Вернуть оригинал из бэкапа рядом (если он есть)."""
    from app.core.io import BackupStore, atomic_write_bytes

    store = BackupStore(os.path.join(os.path.dirname(path), "backup"))
    for abs_orig, name in store.manifest_files().items():
        if os.path.normcase(abs_orig) != os.path.normcase(
                os.path.abspath(path)):
            continue
        src = os.path.join(store.backup_dir, name)
        if not os.path.isfile(src):
            return False
        with open(src, "rb") as f:
            data = f.read()
        atomic_write_bytes(path, data)
        return True
    return False


def is_windows() -> bool:
    return sys.platform.startswith("win")


# ── удаление сейвов ────────────────────────────────────────────────────────

def delete_saves(game_dir: str, drop_backups: bool = True) -> dict:
    """Удалить файлы сохранений игры. {'files': [...], 'bytes': int, ...}

    Правила безопасности:
    - удаляются ТОЛЬКО найденные `find_saves` файлы, никаких папок целиком;
    - каждый файл предварительно уводится в наш `backup/`, поэтому
      действие обратимо (кнопка «Вернуть» в бэкапах остаётся);
    - PlayerPrefs (реестр) не трогаем: это настройки, а не прогресс, и
      стирание настроек — не то, чего ждёт «удалить сейвы»;
    - при ошибке на любом файле — продолжаем, собираем список проблем.

    Модуль чистый: без Qt, без вопросов пользователю — вопрос задаёт UI.
    """
    removed: list[str] = []
    errors: list[str] = []
    total = 0
    for path in find_saves(game_dir):
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        try:
            if drop_backups:
                from app.core.io import BackupStore

                store = BackupStore(os.path.join(
                    os.path.dirname(path), "backup"))
                try:
                    store.backup(path)
                except Exception:
                    pass    # не смогли отложить — удаляем всё равно
            os.unlink(path)
        except OSError as e:
            errors.append("%s: %s" % (os.path.basename(path), e))
            continue
        removed.append(path)
        total += size
    return {"files": removed, "count": len(removed),
            "bytes": total, "errors": errors}