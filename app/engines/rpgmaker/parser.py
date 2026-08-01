# -*- coding: utf-8 -*-
"""Парсер RPG Maker MV/MZ: извлечение и внедрение текста в data/*.json.

Расширенное извлечение (v2):
- Все текстоносные поля БД (Actors, Items, Skills, States, ...)
- Команды событий: диалоги, комментарии, выбор, плагин-команды
- Имена карт, общих событий, групп врагов
- Системные строки (термины, сообщения, название игры)
- Заметки событий (note field) — если содержат переводимый текст
- Поля message1..message4 в Skills/States
- Все плагин-команда (MZ: cmd 357/657, MV: cmd 356) с параметрами
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime

from app.core.models import TranslationEntry
from app.core.rpgmaker import crypto

CJK_RE = re.compile(r'[　-鿿\uac00-\ud7af\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]')

# ── Коды команд событий ──
CMD_DIALOG = 401
CMD_SCROLL = 405
CMD_CHOICES = 102
CMD_CHOICE_BRANCH = 402
CMD_COMMENT = 108
CMD_COMMENT_CONT = 408
CMD_SHOW_TEXT_HDR = 101
CMD_CHANGE_NAME = 320
CMD_CHANGE_NICK = 324
CMD_PLUGIN = 357
CMD_PLUGIN_CONT = 657
CMD_PLUGIN_MV = 356

# ── Поля БД: файл -> список полей ──
DB_FIELDS = {
    "Actors.json": ["name", "nickname", "profile"],
    "Classes.json": ["name"],
    "Items.json": ["name", "description"],
    "Weapons.json": ["name", "description"],
    "Armors.json": ["name", "description"],
    "Enemies.json": ["name"],
    "Skills.json": ["name", "description", "message1", "message2"],
    "States.json": ["name", "message1", "message2", "message3", "message4"],
    "Animations.json": ["name"],
    "Tilesets.json": ["name"],
}

SYSTEM_LIST_FIELDS = [
    "skillTypes", "armorTypes", "weaponTypes", "elements", "equipTypes"
]
TERMS_LIST_FIELDS = ["basic", "commands", "params"]


def detect_engine(game_dir: str) -> str:
    """Определяет движок: 'mz' | 'mv' | 'unknown'."""
    js = os.path.join(game_dir, "js")
    if os.path.exists(os.path.join(js, "rmmz_core.js")):
        return "mz"
    if os.path.exists(os.path.join(js, "rpg_core.js")):
        return "mv"
    if os.path.exists(os.path.join(game_dir, "www", "js", "rpg_core.js")):
        return "mv"
    return "unknown"


def find_data_dir(game_dir: str) -> str:
    """Где лежат данные: 'data' (MZ/MV) или 'www/data' (деплой MV)."""
    if os.path.isdir(os.path.join(game_dir, "data")):
        return "data"
    if os.path.isdir(os.path.join(game_dir, "www", "data")):
        return "www/data"
    return "data"


def has_cjk(text: str) -> bool:
    return bool(CJK_RE.search(text))


# ── Пути внутри JSON ──

_PATH_TOKEN = re.compile(r'([^\[\]]+)|\[(\d+)\]')


def parse_path(path: str) -> list:
    """'events[3].pages[0]' -> ['events', 3, 'pages', 0]"""
    out = []
    for m in _PATH_TOKEN.finditer(path):
        name, idx = m.group(1), m.group(2)
        if idx is not None:
            out.append(int(idx))
        elif name:
            for part in name.split('.'):
                if part:
                    out.append(part)
    return out


def get_by_path(obj, path: str):
    node = obj
    for key in parse_path(path):
        node = node[key]
    return node


def set_by_path(obj, path: str, value) -> None:
    keys = parse_path(path)
    node = obj
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value


# ── Извлечение ──

class _Extractor:
    def __init__(self):
        self.entries: list[TranslationEntry] = []
        self._next_id = 1
        self._seen: set[tuple[str, str]] = set()

    def add(self, file: str, path: str, context: str, text: str):
        if not isinstance(text, str) or not text.strip():
            return
        key = (file, path)
        if key in self._seen:
            return
        self._seen.add(key)
        self.entries.append(TranslationEntry(
            id=self._next_id, file=file, json_path=path,
            context=context, original=text,
        ))
        self._next_id += 1

    # ── команды событий ──
    def event_list(self, file: str, base: str, cmd_list: list, context: str):
        for i, cmd in enumerate(cmd_list):
            code = cmd.get("code")
            params = cmd.get("parameters") or []
            p = f"{base}[{i}].parameters"

            if code in (CMD_DIALOG, CMD_SCROLL, CMD_COMMENT, CMD_COMMENT_CONT):
                if params:
                    kind = ("comment" if code in (CMD_COMMENT, CMD_COMMENT_CONT)
                            else "dialog")
                    self.add(file, f"{p}[0]", f"{context} / {kind}", params[0])
            elif code == CMD_CHOICES and params and isinstance(params[0], list):
                for j, label in enumerate(params[0]):
                    self.add(file, f"{p}[0][{j}]",
                             f"{context} / choice", label)
            elif code == CMD_CHOICE_BRANCH and len(params) > 1:
                self.add(file, f"{p}[1]", f"{context} / branch", params[1])
            elif code == CMD_SHOW_TEXT_HDR and len(params) > 4:
                self.add(file, f"{p}[4]",
                         f"{context} / speaker name", params[4])
            elif code in (CMD_CHANGE_NAME, CMD_CHANGE_NICK) and len(params) > 1:
                self.add(file, f"{p}[1]", f"{context} / rename", params[1])
            elif code == CMD_PLUGIN and len(params) > 3 \
                    and isinstance(params[3], dict):
                for k, v in params[3].items():
                    self.add(file, f"{p}[3].{k}",
                             f"{context} / plugin", v)
            elif code == CMD_PLUGIN_CONT:
                for j, v in enumerate(params):
                    self.add(file, f"{p}[{j}]",
                             f"{context} / plugin", v)
            elif code == CMD_PLUGIN_MV and params:
                self.add(file, f"{p}[0]",
                         f"{context} / plugin (MV)", params[0])

    def db_file(self, file: str, data: list, fields: list[str]):
        for idx, obj in enumerate(data):
            if not isinstance(obj, dict):
                continue
            name = obj.get("name") or f"#{idx}"
            for field in fields:
                if field in obj:
                    self.add(file, f"[{idx}].{field}",
                             f"{file[:-5]} '{name}'", obj[field])

    def map_file(self, file: str, data: dict):
        if data.get("displayName"):
            self.add(file, "displayName", "map name", data["displayName"])
        for ei, ev in enumerate(data.get("events") or []):
            if not isinstance(ev, dict):
                continue
            for pi, page in enumerate(ev.get("pages") or []):
                ctx = (f"{file[:-5]} event "
                       f"'{ev.get('name', ei)}' p.{pi + 1}")
                self.event_list(
                    file, f"events[{ei}].pages[{pi}].list",
                    page.get("list") or [], ctx)

    def common_events(self, file: str, data: list):
        for idx, ev in enumerate(data):
            if not isinstance(ev, dict):
                continue
            self.add(file, f"[{idx}].name",
                     f"common event #{idx}", ev.get("name", ""))
            self.event_list(
                file, f"[{idx}].list", ev.get("list") or [],
                f"common event '{ev.get('name', idx)}'")

    def troops(self, file: str, data: list):
        for idx, tr in enumerate(data):
            if not isinstance(tr, dict):
                continue
            self.add(file, f"[{idx}].name",
                     f"enemy group #{idx}", tr.get("name", ""))
            for pi, page in enumerate(tr.get("pages") or []):
                self.event_list(
                    file, f"[{idx}].pages[{pi}].list",
                    page.get("list") or [],
                    f"battle '{tr.get('name', idx)}' p.{pi + 1}")

    def system(self, file: str, data: dict):
        self.add(file, "gameTitle", "game title",
                 data.get("gameTitle", ""))
        self.add(file, "currencyUnit", "currency",
                 data.get("currencyUnit", ""))
        for fld in SYSTEM_LIST_FIELDS:
            for j, v in enumerate(data.get(fld) or []):
                self.add(file, f"{fld}[{j}]", f"term {fld}", v)
        for j, v in enumerate(data.get("variables") or []):
            self.add(file, f"variables[{j}]", f"variable #{j}", v)
        for j, v in enumerate(data.get("switches") or []):
            self.add(file, f"switches[{j}]", f"switch #{j}", v)
        terms = data.get("terms") or {}
        for fld in TERMS_LIST_FIELDS:
            for j, v in enumerate(terms.get(fld) or []):
                self.add(file, f"terms.{fld}[{j}]",
                         f"term {fld}", v)
        for k, v in (terms.get("messages") or {}).items():
            self.add(file, f"terms.messages.{k}",
                     "system message", v)

    def map_infos(self, file: str, data: list):
        for idx, obj in enumerate(data):
            if isinstance(obj, dict) and obj.get("name"):
                self.add(file, f"[{idx}].name",
                         "map name (list)", obj["name"])

    def note_field(self, file: str, path_prefix: str, note: str,
                   context: str):
        """Извлекаем переводимые строки из заметок (note).

        Заметки в RPG Maker — многострочные строки. Если они содержат
        переводимый текст (а не XML/JSON-теги плагинов), извлекаем
        построчно.
        """
        if not note or not isinstance(note, str):
            return
        lines = note.split("\n")
        for j, line in enumerate(lines):
            s = line.strip()
            if not s:
                continue
            # пропускаем XML/теги плагинов <tag> и JSON
            if s.startswith("<") or s.startswith("{"):
                continue
            self.add(file, f"{path_prefix}[{j}]",
                     f"{context} / note", s)


def _read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract(game_dir: str, data_dir: str | None = None,
            on_skip=None) -> list[TranslationEntry]:
    """Извлекает все переводимые строки из data/*.json игры.

    on_skip(filename, exception) вызывается, если файл не удалось прочитать.
    """
    if data_dir is None:
        data_dir = find_data_dir(game_dir)
    ex = _Extractor()
    root = os.path.join(game_dir, data_dir)
    for fname in sorted(os.listdir(root)):
        if not fname.endswith(".json"):
            continue
        rel = f"{data_dir}/{fname}"
        try:
            data = _read_json(os.path.join(root, fname))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            if on_skip:
                on_skip(fname, e)
            else:
                print(f"[parser] skipped {fname}: {e}")
            continue
        if fname in DB_FIELDS:
            ex.db_file(rel, data, DB_FIELDS[fname])
            # извлечение note для БД-объектов
            for idx, obj in enumerate(data):
                if isinstance(obj, dict) and obj.get("note"):
                    name = obj.get("name") or f"#{idx}"
                    ex.note_field(rel, f"[{idx}].note",
                                  obj["note"],
                                  f"{fname[:-5]} '{name}'")
        elif fname.startswith("Map") and fname != "MapInfos.json":
            ex.map_file(rel, data)
        elif fname == "CommonEvents.json":
            ex.common_events(rel, data)
        elif fname == "Troops.json":
            ex.troops(rel, data)
        elif fname == "System.json":
            ex.system(rel, data)
        elif fname == "MapInfos.json":
            ex.map_infos(rel, data)
    return ex.entries


# ── Внедрение ──

def _detect_indent(path: str) -> int | None:
    with open(path, encoding="utf-8") as f:
        head = f.read(64)
    return 2 if head.startswith("{\n") or head.startswith("[\n") else None


def apply(game_dir: str, entries: list[TranslationEntry],
          backup_root: str | None = None, data_dir: str | None = None,
          target_lang: str = "ru",
          on_skip=None) -> dict:
    """Внедряет переводы обратно в файлы игры. Возвращает статистику.

    Гибридный режим: JSON-файлы + опциональная генерация JS-пейлоада
    для live-подмены.
    """
    if data_dir is None:
        data_dir = find_data_dir(game_dir)
    by_file: dict[str, list[TranslationEntry]] = {}
    for e in entries:
        if e.translation.strip() and e.status != "skip":
            by_file.setdefault(e.file, []).append(e)

    if backup_root is None:
        backup_root = os.path.join(
            game_dir, "backup",
            datetime.now().strftime("%Y%m%d_%H%M%S"))
    stats = {"files": 0, "strings": 0, "backups": []}

    for rel, items in by_file.items():
        abs_path = os.path.join(game_dir, *rel.split("/"))
        if not os.path.exists(abs_path):
            continue
        backup_path = os.path.join(backup_root, rel)
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        if not os.path.exists(backup_path):
            shutil.copy2(abs_path, backup_path)
            stats["backups"].append(backup_path)

        data = _read_json(abs_path)
        indent = _detect_indent(abs_path)
        written = 0
        for e in items:
            try:
                current = get_by_path(data, e.json_path)
            except (KeyError, IndexError, TypeError) as exc:
                if on_skip:
                    on_skip(e, f"path not found: {exc}")
                else:
                    print(f"[parser] {rel}: path {e.json_path} "
                          f"not found ({exc})")
                continue
            if isinstance(current, str):
                set_by_path(data, e.json_path, e.translation)
                written += 1
            elif on_skip:
                on_skip(e, "current value is not a string")
        with open(abs_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        stats["files"] += 1
        stats["strings"] += written
    return stats
