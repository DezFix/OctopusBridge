# -*- coding: utf-8 -*-
"""PlayerPrefs Unity — чтение/правка настроек игры в реестре Windows.

Читы Unity делаются ТОЛЬКО по файлам и реестру: канала в процесс игры нет
и не будет (см. AGENTS.md §1). PlayerPrefs — единственное универсальное
хранилище «переменных», которое Unity-игры пишут без своего формата:
```HKCU\\Software\\<companyName>\\<productName>```

company/product берём из `globalgamemanagers` (PlayerSettings), путь
собираем сами — тогда движок работает с чужой игрой, не гадая.

Формат значений (Unity, Windows):
    REG_DWORD   — int
    REG_SZ      — string
    REG_BINARY  — 4 байта float, иначе произвольные данные

К имени ключа Unity дописывает хеш `_h<число>`; для показа human-readable
имени хеш срезается, при записи добавляется обратно. Ключи игнорируемые
(``unity.*``, ``Screenmanager*``, ``Unity*``) помечаются, но не прячутся —
начинающий с них игрок может случайно сбить разрешение окна.

Модуль чистый: без Qt, без сети. Реестр трогаем только по явному вызову.
"""
from __future__ import annotations

import os
import re
import struct

# ── путь реестра ────────────────────────────────────────────────────────────

def prefs_subkey(company: str, product: str) -> str:
    """``Software\\<company>\\<product>`` — ветка PlayerPrefs."""
    return r"Software\%s\%s" % (company, product)


def player_settings(game_dir: str) -> tuple[str, str] | None:
    """(companyName, productName) из ``globalgamemanagers``.

    Метаданные сборки, не игровой текст. None — определить не удалось.
    """
    from app.core.unity.parser import _data_dirs

    for ddir in _data_dirs(game_dir):
        path = os.path.join(ddir, "globalgamemanagers")
        if not os.path.isfile(path):
            continue
        try:
            import UnityPy

            from app.core.unity.parser import _close_env, \
                _force_pure_python_reader
            _force_pure_python_reader()
            env = UnityPy.load(path)
        except Exception:
            continue
        try:
            for _ak, asset in list(getattr(env, "files", {}).items()):
                objects = getattr(asset, "objects", None) or {}
                vals = (objects.values() if isinstance(objects, dict)
                        else objects)
                for obj in list(vals):
                    try:
                        if str(getattr(obj.type, "name", "?")) \
                                != "PlayerSettings":
                            continue
                        tree = obj.parse_as_dict()
                    except Exception:
                        continue
                    company = str(tree.get("companyName") or "").strip()
                    product = str(tree.get("productName") or "").strip()
                    if company and product:
                        return (company, product)
        finally:
            try:
                _close_env(env)
            except Exception:
                pass
    return None


# ── разбор ключей ───────────────────────────────────────────────────────────

_HASH_RE = re.compile(r"_h\d+$")

#: префиксы служебных ключей Unity (менять их = ломать окно/графику)
_SYSTEM_PREFIXES = ("unity.", "Unity", "Screenmanager")


def split_hash(key: str) -> tuple[str, str]:
    """``Name_h123`` -> (``Name``, ``_h123``)."""
    m = _HASH_RE.search(key)
    if not m:
        return (key, "")
    return (key[: m.start()], m.group(0))


def is_system_key(name: str) -> bool:
    """Служебный ключ Unity (не игровая переменная)."""
    return name.startswith(_SYSTEM_PREFIXES)


# ── чтение ──────────────────────────────────────────────────────────────────

class PrefError(RuntimeError):
    """Реестр недоступен или значение неприменимо."""


def read_prefs(game_dir: str) -> list[dict]:
    """Все PlayerPrefs игры -> [{key, name, kind, value, system}].

    kind: ``int`` | ``float`` | ``str`` | ``bytes``.
    Игры, у которых PlayerPrefs ещё нет (не запускалась), дают [].
    """
    import winreg

    ident = player_settings(game_dir)
    if not ident:
        raise PrefError(
            "Не удалось прочитать companyName/productName из "
            "globalgamemanagers — не Unity Mono-сборка?")
    company, product = ident
    subkey = prefs_subkey(company, product)
    out: list[dict] = []
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey)
    except FileNotFoundError:
        return out
    except OSError as e:
        raise PrefError("Реестр недоступен: %s" % e) from e
    try:
        idx = 0
        while True:
            try:
                key, raw, typ = winreg.EnumValue(root, idx)
            except OSError:
                break
            idx += 1
            name, _h = split_hash(str(key))
            kind, value = _decode(raw, typ)
            out.append({
                "key": str(key),
                "name": name,
                "kind": kind,
                "value": value,
                "system": is_system_key(name),
                "company": company,
                "product": product,
            })
    finally:
        root.Close()
    out.sort(key=lambda d: (d["system"], d["name"].lower()))
    return out


def _decode(raw: object, typ: int) -> tuple[str, object]:
    """Значение реестра -> (kind, python-value) по правилам Unity."""
    if typ == 4:                      # REG_DWORD -> int
        return ("int", int(raw))
    if typ == 1 or isinstance(raw, str):   # REG_SZ -> string
        return ("str", str(raw))
    data = raw if isinstance(raw, bytes) else bytes(raw or b"")
    if len(data) == 4:
        try:
            return ("float", struct.unpack("<f", data)[0])
        except Exception:
            pass
    return ("bytes", data)


def format_value(row: dict) -> str:
    """Человекочитаемое значение для таблицы."""
    kind, value = row.get("kind"), row.get("value")
    if kind == "bytes":
        data = value or b""
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if text and all(ch == "\n" or ch >= " " for ch in text):
            return "%s (%d Б, текст)" % (_clip(text, 60), len(data))
        return "%d Б: %s" % (len(data), data[:16].hex(" "))
    if kind == "float":
        return "%.6g" % float(value)
    return str(value)


def _clip(text: str, limit: int) -> str:
    text = text.replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ── запись ──────────────────────────────────────────────────────────────────

def set_pref(game_dir: str, name: str, value) -> str:
    """Записать PlayerPrefs по ЧИСТОМУ имени (без ``_h``).

    Хеш-суффикс подставляется по образцу существующих ключей с тем же
    именем; если таких нет — ключ создаётся без хеша (Unity его прочитает).
    Возвращает полное имя записанного ключа.
    """
    import winreg

    ident = player_settings(game_dir)
    if not ident:
        raise PrefError("Не удалось определить ветку PlayerPrefs игры.")
    company, product = ident
    subkey = prefs_subkey(company, product)
    rows = read_prefs(game_dir)
    full = name
    for row in rows:
        if row["name"] == name and row["key"] != name:
            full = row["key"]
            break
    if full == name:
        full = name
    typ, data = _encode(value)
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, full, 0, typ, data)
    except OSError as e:
        raise PrefError("Запись в реестр не удалась: %s" % e) from e
    return full


def _encode(value) -> tuple[int, object]:
    """python-value -> (тип реестра, данные) по правилам Unity."""
    if isinstance(value, bool):
        return (4, int(value))
    if isinstance(value, int):
        return (4, value)
    if isinstance(value, float):
        return (3, struct.pack("<f", value))
    if isinstance(value, (bytes, bytearray)):
        return (3, bytes(value))
    return (1, str(value))


def parse_input(text: str, kind: str):
    """Строка из поля ввода -> значение нужного типа.

    ``kind='auto'`` — угадать по содержимому (int -> float -> str).
    Ошибка -> PrefError с понятным текстом.
    """
    text = (text or "").strip()
    if kind == "auto":
        if re.fullmatch(r"[+-]?\d+", text):
            return int(text)
        try:
            return float(text)
        except ValueError:
            return text
    if kind == "int":
        if not re.fullmatch(r"[+-]?\d+", text):
            raise PrefError("Нужно целое число, получено: %r" % text[:20])
        return int(text)
    if kind == "float":
        try:
            return float(text)
        except ValueError:
            raise PrefError("Нужно число, получено: %r" % text[:20])
    if kind == "bytes":
        try:
            return bytes.fromhex(text.replace(" ", ""))
        except ValueError:
            raise PrefError("Нужны hex-байты, получено: %r" % text[:20])
    return text


# ── бэкап / откат ───────────────────────────────────────────────────────────

def export_prefs(game_dir: str, dest_path: str) -> str:
    """Выгрузить PlayerPrefs в JSON (бэкап перед правками)."""
    import json

    rows = read_prefs(game_dir)
    ident = player_settings(game_dir) or ("", "")
    payload = {
        "company": ident[0],
        "product": ident[1],
        "prefs": [{k: r[k] for k in
                   ("key", "name", "kind", "value", "system")}
                  for r in rows],
    }
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return dest_path


def import_prefs(game_dir: str, src_path: str) -> dict:
    """Вернуть PlayerPrefs из JSON-бэкапа. {'restored': n, 'errors': [...]}"""
    import json

    import winreg

    with open(src_path, encoding="utf-8") as f:
        payload = json.load(f)
    company = str(payload.get("company") or "")
    product = str(payload.get("product") or "")
    if not company or not product:
        raise PrefError("В бэкапе нет company/product.")
    subkey = prefs_subkey(company, product)
    restored = 0
    errors: list[str] = []
    for row in payload.get("prefs") or []:
        key = str(row.get("key") or row.get("name") or "")
        if not key:
            continue
        kind = str(row.get("kind") or "str")
        raw = row.get("value")
        if kind == "bytes":
            value = bytes.fromhex(str(raw)) if isinstance(raw, str) \
                else bytes(raw or b"")
        elif kind == "float":
            value = float(raw)
        elif kind == "int":
            value = int(raw)
        else:
            value = "" if raw is None else str(raw)
        typ, data = _encode(value)
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, key, 0, typ, data)
            restored += 1
        except OSError as e:
            errors.append("%s: %s" % (key, e))
    result: dict = {"restored": restored}
    if errors:
        result["errors"] = errors[:10]
    return result