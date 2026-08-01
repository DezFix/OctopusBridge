# -*- coding: utf-8 -*-
"""Поддержка Twine (HTML5): детект, извлечение текста, внедрение перевода.

Twine-игра — это .html с элементом <tw-storydata>, внутри которого
пассажи <tw-passagedata pid="N" name="...">текст</tw-passagedata>.

Извлечение построчное: строки-макросы (<<...>> SugarCube, (...): Harlowe),
чистые ссылки [[target]] и служебные строки пропускаются — переводятся
только строки с «живым» текстом. HTML-сущности раскрываются при извлечении
и экранируются обратно при внедрении.
"""
from __future__ import annotations

import html as html_mod
import os
import re
import shutil
from datetime import datetime

from app.core.models import TranslationEntry

STORY_TAG = "<tw-storydata"
_MAX_HTML_SIZE = 64 * 1024 * 1024   # безопасный предел чтения

RE_PASSAGE = re.compile(
    r"<tw-passagedata\b([^>]*)>(.*?)</tw-passagedata>", re.DOTALL)
RE_ATTR = re.compile(r'(\w[\w-]*)="([^"]*)"')

# служебные строки (не переводим)
RE_MACRO_SUGARCUBE = re.compile(r"^\s*<<.*>>\s*$", re.DOTALL)
RE_MACRO_HARLOWE = re.compile(r"^\s*\(.*\)\s*$", re.DOTALL)
RE_COMMENT = re.compile(r"^\s*(/%%|%%/|<!--)")
RE_PURE_LINK = re.compile(r"^\s*\[\[[^\]]*\]\]\s*$")
RE_PURE_TAG = re.compile(r"^\s*<[^>]*>\s*$")


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


def find_story(game_dir: str) -> str | None:
    """Путь к .html с <tw-storydata> (корень папки или 1 уровень вглубь)."""
    candidates = []
    for root, dirs, files in os.walk(game_dir):
        depth = os.path.relpath(root, game_dir).count(os.sep)
        if depth > 0:
            dirs[:] = []
        for f in sorted(files):
            if f.lower().endswith((".html", ".htm")):
                candidates.append(os.path.join(root, f))
    for path in candidates:
        try:
            if os.path.getsize(path) > _MAX_HTML_SIZE:
                continue
            with open(path, encoding="utf-8", errors="ignore") as f:
                head = f.read(2 * 1024 * 1024)
            if STORY_TAG in head:
                return path
        except OSError:
            continue
    return None


def detect(game_dir: str) -> bool:
    return find_story(game_dir) is not None


def _attrs(attr_text: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in RE_ATTR.finditer(attr_text)}


def is_translatable_line(line: str) -> bool:
    """Строка пассажа — «живой» текст, а не макрос/ссылка/тег."""
    s = line.strip()
    if not s or not _has_letters(s):
        return False
    if RE_MACRO_SUGARCUBE.match(line) or RE_MACRO_HARLOWE.match(line):
        return False
    if RE_COMMENT.match(line):
        return False
    if RE_PURE_LINK.match(line) or RE_PURE_TAG.match(line):
        return False
    return True


def extract(game_dir: str) -> list[TranslationEntry]:
    """Извлекает переводимые строки из пассажей истории."""
    story = find_story(game_dir)
    if not story:
        return []
    rel = os.path.basename(story)
    with open(story, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    entries: list[TranslationEntry] = []
    next_id = 1
    for m in RE_PASSAGE.finditer(text):
        attrs = _attrs(m.group(1))
        pid = attrs.get("pid", "?")
        name = html_mod.unescape(attrs.get("name", ""))
        for n, line in enumerate(m.group(2).split("\n")):
            if not is_translatable_line(line):
                continue
            original = html_mod.unescape(line.strip())
            entries.append(TranslationEntry(
                id=next_id, file=rel,
                json_path=f"passage[{pid}].line[{n}]",
                context=f"{name} (pid {pid})",
                original=original))
            next_id += 1
    return entries


def apply(game_dir: str, entries: list[TranslationEntry],
          backup_root: str | None = None, on_skip=None) -> dict:
    """Внедряет переводы построчно обратно в .html истории (с бэкапом)."""
    story = find_story(game_dir)
    if not story:
        return {"files": 0, "strings": 0, "backups": []}
    by_pid: dict[str, dict[int, str]] = {}
    for e in entries:
        if not e.translation.strip() or e.status == "skip":
            continue
        m = re.match(r"passage\[(\d+)\]\.line\[(\d+)\]", e.json_path)
        if m:
            by_pid.setdefault(m.group(1), {})[int(m.group(2))] = e.translation

    with open(story, encoding="utf-8", errors="ignore") as f:
        text = f.read()

    if backup_root is None:
        backup_root = os.path.join(
            game_dir, "backup", datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(backup_root, exist_ok=True)
    backup_path = os.path.join(backup_root, os.path.basename(story))
    if not os.path.exists(backup_path):
        shutil.copy2(story, backup_path)

    written = 0

    def replace_passage(m: re.Match) -> str:
        nonlocal written
        attrs = _attrs(m.group(1))
        pid = attrs.get("pid")
        lines_map = by_pid.get(pid)
        if not lines_map:
            return m.group(0)
        lines = m.group(2).split("\n")
        for idx, translation in lines_map.items():
            if 0 <= idx < len(lines):
                lead = lines[idx][:len(lines[idx])
                                     - len(lines[idx].lstrip())]
                lines[idx] = lead + html_mod.escape(translation, quote=False)
                written += 1
        return f"<tw-passagedata{m.group(1)}>" + "\n".join(lines) + \
            "</tw-passagedata>"

    new_text = RE_PASSAGE.sub(replace_passage, text)
    with open(story, "w", encoding="utf-8") as f:
        f.write(new_text)
    return {"files": 1 if written else 0, "strings": written,
            "backups": [backup_path]}
