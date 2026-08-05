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

from .fileview import DiskFileView, FileView

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


def _read_plugins_js(game_dir: str, view: FileView | None = None) -> list:
    view = view or DiskFileView(game_dir)
    for rel in ("js/plugins.js", "www/js/plugins.js"):
        text = view.read_text(rel)
        if text is None:
            continue
        try:
            return json.loads(text[text.index("["):text.rindex("]") + 1])
        except (ValueError, json.JSONDecodeError):
            return []
    return []


def _system_names(game_dir: str,
                  view: FileView | None = None) -> tuple[dict[int, str], dict[int, str]]:
    """Имена из data/System.json (индекс 0 пустой, пропускаем)."""
    view = view or DiskFileView(game_dir)
    var_names: dict[int, str] = {}
    switch_names: dict[int, str] = {}
    text = None
    for rel in ("data/System.json", "www/data/System.json"):
        text = view.read_text(rel)
        if text is not None:
            break
    if text is None:
        return var_names, switch_names
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return var_names, switch_names
    for i, name in enumerate(data.get("variables") or []):
        if name:
            var_names[i] = name
    for i, name in enumerate(data.get("switches") or []):
        if name:
            switch_names[i] = name
    return var_names, switch_names


def extract_names(game_dir: str,
                  view: FileView | None = None) -> tuple[dict[int, str], dict[int, str]]:
    """Возвращает (имена переменных, имена переключателей)."""
    var_names, switch_names = _system_names(game_dir, view)
    # плагины заполняют пробелы, не затирая System.json
    plugin_vars: dict[int, str] = {}
    plugin_switches: dict[int, str] = {}
    for plugin in _read_plugins_js(game_dir, view):
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


def extract_maps(game_dir: str,
                 view: FileView | None = None) -> list[tuple[int, str]]:
    """Список карт (id, имя) из MapInfos.json для телепорта."""
    view = view or DiskFileView(game_dir)
    text = None
    for rel in ("data/MapInfos.json", "www/data/MapInfos.json"):
        text = view.read_text(rel)
        if text is not None:
            break
    if text is None:
        return []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    maps = []
    for obj in data:
        if isinstance(obj, dict) and obj.get("id") and obj.get("name"):
            maps.append((obj["id"], obj["name"]))
    return maps


def _read_data_file(game_dir: str, filename: str,
                    view: FileView | None = None) -> list:
    view = view or DiskFileView(game_dir)
    for rel in (f"data/{filename}", f"www/data/{filename}"):
        text = view.read_text(rel)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return []
        return data if isinstance(data, list) else []
    return []


def extract_item_names(game_dir: str,
                       view: FileView | None = None) -> dict[tuple[str, int], str]:
    """Имена предметов/оружия/брони: {(kind, id): name}."""
    result: dict[tuple[str, int], str] = {}
    for kind, fname in [("item", "Items.json"),
                        ("weapon", "Weapons.json"),
                        ("armor", "Armors.json")]:
        for obj in _read_data_file(game_dir, fname, view):
            if isinstance(obj, dict) and obj.get("id") and obj.get("name"):
                result[(kind, obj["id"])] = obj["name"]
    return result


def extract_state_names(game_dir: str,
                        view: FileView | None = None) -> dict[int, str]:
    """Имена состояний (отравление, баффы и т.д.)."""
    result: dict[int, str] = {}
    for obj in _read_data_file(game_dir, "States.json", view):
        if isinstance(obj, dict) and obj.get("id") and obj.get("name"):
            result[obj["id"]] = obj["name"]
    return result
