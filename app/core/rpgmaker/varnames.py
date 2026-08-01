# -*- coding: utf-8 -*-
"""Имена переменных и переключателей RPG Maker.

Источники (по приоритету):
1. data/System.json — массивы switches/variables (имена из редактора,
   доезжают и в деплое — их же читает mTool через $dataSystem)
2. параметры плагинов в js/plugins.js — маппинги вида
   {"VariableID": "2", "Label": "..."} для пропущенных имён
3. ручные имена пользователя — хранятся в проекте, применяются поверх
"""
from __future__ import annotations

import json
import os

VAR_ID_KEYS = {"variableid", "varid", "variable", "var", "variable_id"}
SWITCH_ID_KEYS = {"switchid", "swid", "switch", "switch_id"}
NAME_KEYS = {"label", "name", "title", "text", "displayname"}


def _walk(node, out: dict, id_keys: set[str]):
    if isinstance(node, dict):
        lowered = {str(k).lower(): v for k, v in node.items()}
        id_val = next((lowered[k] for k in id_keys if k in lowered), None)
        name_val = next((lowered[k] for k in NAME_KEYS
                         if k in lowered and isinstance(lowered[k], str)), None)
        if id_val is not None and name_val:
            try:
                out[int(id_val)] = name_val
            except (TypeError, ValueError):
                pass
        for v in node.values():
            _walk(v, out, id_keys)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out, id_keys)
    elif isinstance(node, str):
        s = node.strip()
        if s[:1] in ("[", "{") and len(s) > 2:
            try:
                _walk(json.loads(s), out, id_keys)
            except (json.JSONDecodeError, ValueError):
                pass


def _read_plugins_js(game_dir: str) -> list:
    path = os.path.join(game_dir, "js", "plugins.js")
    if not os.path.exists(path):
        path = os.path.join(game_dir, "www", "js", "plugins.js")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        return json.loads(text[text.index("["):text.rindex("]") + 1])
    except (ValueError, json.JSONDecodeError):
        return []


def _system_names(game_dir: str) -> tuple[dict[int, str], dict[int, str]]:
    """Имена из data/System.json (индекс 0 пустой, пропускаем)."""
    path = os.path.join(game_dir, "data", "System.json")
    if not os.path.exists(path):
        path = os.path.join(game_dir, "www", "data", "System.json")
    var_names: dict[int, str] = {}
    switch_names: dict[int, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return var_names, switch_names
    for i, name in enumerate(data.get("variables") or []):
        if name:
            var_names[i] = name
    for i, name in enumerate(data.get("switches") or []):
        if name:
            switch_names[i] = name
    return var_names, switch_names


def extract_names(game_dir: str) -> tuple[dict[int, str], dict[int, str]]:
    """Возвращает (имена переменных, имена переключателей)."""
    var_names, switch_names = _system_names(game_dir)
    # плагины заполняют пробелы, не затирая System.json
    plugin_vars: dict[int, str] = {}
    plugin_switches: dict[int, str] = {}
    for plugin in _read_plugins_js(game_dir):
        params = plugin.get("parameters") if isinstance(plugin, dict) else None
        if not isinstance(params, dict):
            continue
        _walk(params, plugin_vars, VAR_ID_KEYS)
        _walk(params, plugin_switches, SWITCH_ID_KEYS)
    for k, v in plugin_vars.items():
        var_names.setdefault(k, v)
    for k, v in plugin_switches.items():
        switch_names.setdefault(k, v)
    return var_names, switch_names


def extract_maps(game_dir: str) -> list[tuple[int, str]]:
    """Список карт (id, имя) из MapInfos.json для телепорта."""
    path = os.path.join(game_dir, "data", "MapInfos.json")
    if not os.path.exists(path):
        path = os.path.join(game_dir, "www", "data", "MapInfos.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    maps = []
    for obj in data:
        if isinstance(obj, dict) and obj.get("id") and obj.get("name"):
            maps.append((obj["id"], obj["name"]))
    return maps


def _read_data_file(game_dir: str, filename: str) -> list:
    path = os.path.join(game_dir, "data", filename)
    if not os.path.exists(path):
        path = os.path.join(game_dir, "www", "data", filename)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def extract_item_names(game_dir: str) -> dict[tuple[str, int], str]:
    """Имена предметов/оружия/брони: {(kind, id): name}."""
    result: dict[tuple[str, int], str] = {}
    for kind, fname in [("item", "Items.json"),
                        ("weapon", "Weapons.json"),
                        ("armor", "Armors.json")]:
        for obj in _read_data_file(game_dir, fname):
            if isinstance(obj, dict) and obj.get("id") and obj.get("name"):
                result[(kind, obj["id"])] = obj["name"]
    return result


def extract_state_names(game_dir: str) -> dict[int, str]:
    """Имена состояний (отравление, баффы и т.д.)."""
    result: dict[int, str] = {}
    for obj in _read_data_file(game_dir, "States.json"):
        if isinstance(obj, dict) and obj.get("id") and obj.get("name"):
            result[obj["id"]] = obj["name"]
    return result
