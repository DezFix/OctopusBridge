# -*- coding: utf-8 -*-
"""Проверка файлов игры после перевода: игра обязана стартовать.

Мотивация: SyntaxError вида ``Expected ',' or ']' after array element
in JSON at position N`` при старте игры означает, что какой-то файл,
который движок читает через JSON.parse (data/*.json, список плагинов,
словарь вшитого плагина), стал невалидным после нашей записи. Внешние
проверки отдельных записей это не ловят (например, порванный внутренний
JSON-в-строке параметра плагина при валидном внешнем plugins.js).

V8 JSON.parse строже, чем Python json: отвергает NaN/Infinity,
висячие запятые и комментарии — проверяем теми же глазами, что игра.
Возвращает список проблем (пустой = всё чисто).
"""
from __future__ import annotations

import json
import os
import re

__all__ = ["strict_loads", "verify_boot_files"]


def _reject_constant(value: str):
    raise ValueError(f"non-JSON constant: {value}")


def strict_loads(text: str):
    """json.loads глазами V8: NaN/Infinity/-Infinity запрещены."""
    return json.loads(text, parse_constant=_reject_constant)


def _strip_js_comments(text: str) -> str:
    """Вырезает // и /* */ вне строковых литералов (JS-формат plugins.js)."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str: str | None = None
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in "\"'":
            in_str = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _js_array_span(text: str) -> str | None:
    """Тело JS-массива plugins.js: от первой [ до последней ]."""
    try:
        return text[text.index("["):text.rindex("]") + 1]
    except ValueError:
        return None


def _check_plugins_list(path: str) -> str | None:
    """Проверяет список плагинов (JSON-массив или JS var $plugins)."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return f"{path}: cannot read ({e})"
    if text.lstrip().startswith("["):
        try:
            data = strict_loads(text)
        except ValueError as e:
            return f"{path}: invalid JSON ({e})"
        if not isinstance(data, list):
            return f"{path}: top level is not an array"
        return None
    span = _js_array_span(text)
    if span is None:
        return f"{path}: no [...] array found"
    span = _strip_js_comments(span)
    span = re.sub(r",(\s*[\]}])", r"\1", span)
    try:
        data = strict_loads(span)
    except ValueError as e:
        return f"{path}: invalid plugins array ({e})"
    if not isinstance(data, list):
        return f"{path}: top level is not an array"
    return None


def _check_generated_dict(path: str) -> str | None:
    """Проверяет вшитый словарь ob_runtime.js / octopus_ob.js."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            src = f.read()
    except (OSError, UnicodeDecodeError) as e:
        return f"{path}: cannot read ({e})"
    try:
        from app.core.rpgmaker.mv_bridge import _tr_dict_span
    except Exception as e:  # noqa: BLE001
        return f"{path}: cannot import span scanner ({e})"
    span = _tr_dict_span(src)
    if not span:
        return f"{path}: __octopus_trInstall dict not found"
    try:
        strict_loads(src[span[0]:span[1]].strip())
    except ValueError as e:
        return f"{path}: embedded dict invalid ({e})"
    return None


def _tolerant_plugins_array(text: str):
    """Список плагинов из JSON-массива или JS var $plugins (или None)."""
    try:
        if text.lstrip().startswith("["):
            data = json.loads(text)
        else:
            span = _js_array_span(text)
            if span is None:
                return None
            span = _strip_js_comments(span)
            span = re.sub(r",(\s*[\]}])", r"\1", span)
            data = json.loads(span)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _param_leaves(params) -> list[tuple[str, str]]:
    """(key, leaf) листьев параметров в порядке извлечения парсера."""
    from app.core.rpgmaker import parser as _p
    out: list[tuple[str, str]] = []
    if not isinstance(params, dict):
        return out
    for key, val in params.items():
        found: list[str] = []
        _p._walk_param_value(val, found.append)
        for s in found:
            out.append((key, s))
    return out


def verify_resource_refs(game_dir: str) -> list[str]:
    """Ловит перевод имён файлов в параметрах плагинов.

    Сравнивает backup/plugins.js (оригинал) с текущим: если значение,
    совпадавшее с файлом ресурса (BGM/SE/картинка), заменено на строку,
    которая файлом не является, — игра упадёт с "Failed to load".
    Внешний plugins.js при этом валиден, обычный verify это не видит.
    """
    from app.core.rpgmaker import resrefs
    problems: list[str] = []
    idx = resrefs.build_index(game_dir)
    if not idx:
        return []
    for rel in ("js/plugins.js", "www/js/plugins.js",
                "data/plugins.js", "www/data/plugins.js"):
        cur_p = os.path.join(game_dir, rel.replace("/", os.sep))
        bak_p = os.path.join(game_dir, "backup", *rel.split("/"))
        if not (os.path.isfile(cur_p) and os.path.isfile(bak_p)):
            continue
        try:
            with open(bak_p, encoding="utf-8-sig") as f:
                old_list = _tolerant_plugins_array(f.read())
            with open(cur_p, encoding="utf-8-sig") as f:
                new_list = _tolerant_plugins_array(f.read())
        except (OSError, UnicodeDecodeError):
            continue
        if not old_list or not new_list:
            continue
        old_by_name = {p["name"]: p for p in old_list
                       if isinstance(p, dict) and isinstance(p.get("name"), str)}
        new_by_name = {p["name"]: p for p in new_list
                       if isinstance(p, dict) and isinstance(p.get("name"), str)}
        for name, old_pl in old_by_name.items():
            new_pl = new_by_name.get(name)
            if not new_pl:
                continue
            old_leaves = _param_leaves(old_pl.get("parameters"))
            new_leaves = _param_leaves(new_pl.get("parameters"))
            if len(old_leaves) != len(new_leaves):
                continue  # структура уехала — не наш случай, молчим
            for (key, old_v), (_, new_v) in zip(old_leaves, new_leaves):
                if old_v == new_v:
                    continue
                if resrefs.is_resource_name(idx, old_v) \
                        and not resrefs.is_resource_name(idx, new_v):
                    problems.append(
                        f"{rel}: параметр {name}/{key}: файл «{old_v}» "
                        f"переведён в «{new_v}» — игра не найдёт ресурс "
                        f"(поставь строке skip и примени заново)")
    return problems


def verify_boot_files(game_dir: str) -> list[str]:
    """Проверяет всё, что RPG Maker читает при старте. [] = чисто."""
    problems: list[str] = []
    # 1) data/*.json (+ www-деплой): строгий парсинг глазами V8
    data_dirs = []
    for cand in ("data", os.path.join("www", "data")):
        full = os.path.join(game_dir, cand)
        if os.path.isdir(full):
            data_dirs.append((cand, full))
    for rel_dir, full_dir in data_dirs:
        try:
            names = sorted(os.listdir(full_dir))
        except OSError:
            continue
        for fn in names:
            if not fn.lower().endswith(".json"):
                continue
            p = os.path.join(full_dir, fn)
            rel = f"{rel_dir}/{fn}"
            try:
                with open(p, encoding="utf-8-sig") as f:
                    strict_loads(f.read())
            except (OSError, UnicodeDecodeError) as e:
                problems.append(f"{rel}: cannot read ({e})")
            except ValueError as e:
                problems.append(f"{rel}: invalid JSON, game will not boot ({e})")
        # шифрованные карты MV: обязаны расшифровываться и парситься
        for fn in names:
            if not fn.lower().endswith(".rpgmvm"):
                continue
            p = os.path.join(full_dir, fn)
            rel = f"{rel_dir}/{fn}"
            try:
                from app.core.rpgmaker import crypto
                key = crypto.get_key_mv(game_dir)
            except Exception:  # noqa: BLE001
                key = None
            if not key:
                continue
            try:
                with open(p, "rb") as f:
                    body = f.read()
                strict_loads(crypto.decrypt_bytes(body, key).decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                problems.append(f"{rel}: cannot decrypt/parse ({e})")
    # 2) списки плагинов во всех известных местах
    for rel in ("js/plugins.js", "www/js/plugins.js",
                "data/plugins.js", "www/data/plugins.js"):
        p = os.path.join(game_dir, rel.replace("/", os.sep))
        if os.path.isfile(p):
            err = _check_plugins_list(p)
            if err:
                problems.append(err)
    # 3) вшитые словари наших плагинов
    for rel in ("js/plugins/ob_runtime.js", "www/js/plugins/ob_runtime.js",
                "js/plugins/octopus_ob.js", "www/js/plugins/octopus_ob.js"):
        p = os.path.join(game_dir, rel.replace("/", os.sep))
        if os.path.isfile(p):
            err = _check_generated_dict(p)
            if err:
                problems.append(err)
    # 4) ссылки на ресурсы в параметрах плагинов (backup vs текущий)
    problems.extend(verify_resource_refs(game_dir))
    # 5) манифест NW.js: битый package.json = игра не стартует вообще
    _pkg = os.path.join(game_dir, "package.json")
    if os.path.isfile(_pkg):
        try:
            with open(_pkg, encoding="utf-8-sig") as f:
                strict_loads(f.read())
        except (OSError, UnicodeDecodeError) as e:
            problems.append(f"package.json: cannot read ({e})")
        except ValueError as e:
            problems.append(
                f"package.json: invalid JSON, game will not boot ({e})")
    return problems
