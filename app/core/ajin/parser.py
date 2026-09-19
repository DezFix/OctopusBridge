# -*- coding: utf-8 -*-
"""AjinSyoujyo: детект, извлечение и внедрение .ks через слоёный доступ.

Формат строк — TyranoScript/KAG (как в app.core.tyrano.parser):
реплики — обычные строки, теги [l]/[bg]/[link]/[ruby] — служебные.
Извлекаются только текстовые сегменты и text="..." у link/button/ruby;
комментарии (;), метки (*), блоки [iscript]...[endscript] пропускаются.

Отличия от базового Tyrano:
- файлы читаются из override/ + app.asar (LayeredView), а не с диска;
- запись — только в override/ (asar не перепаковываем);
- бэкапы: override-оригиналы -> backup/override/<rel>;
  файлы, пришедшие только из asar -> asar-байты в backup/asar/<rel>
  + удаление override-файла при restore (возврат видимости asar).
"""
from __future__ import annotations

import os
import re
import shutil

from app.core.models import TranslationEntry
from app.core.tyrano import parser as _tyrano_parser
from app.core.tyrano.parser import (
    _SCRIPT_BLOCK_CLOSE,
    _SCRIPT_BLOCK_OPEN,
    _is_var_safe,
    _replace_seg,
    _replace_tag_attr,
    _split_tokens,
    _tag_name,
)

from . import layout as layout_mod
from .layered import LayeredView

_PATH_RE = re.compile(
    r"line\[(\d+)\](?:\.seg\[(\d+)\]|\.tag\[(\d+)\]\.text(?:#(\d+))?)?")


def _has_letters(text: str) -> bool:
    return any(ch.isalpha() for ch in text)


# ── детект ──

def detect(game_dir: str) -> int:
    """Вес уверенности: 0 — не Ajin-раскладка.

    Сигнатура (все условия структурные, текст игры не читается):
    - exe в корне + resources/app.asar + resources/app/override/;
    - package.json с main.js и перехватчиком file:// -> override;
    - в слоях есть data/scenario/*.ks (имена, не содержимое).
    Вес 120 — выше базового Tyrano (95), чтобы реестр выбрал Ajin.
    """
    info = layout_mod.layout(game_dir)
    if not (info["exe"] and info["asar"] and info["override"]):
        return 0
    if not info["has_interceptor"]:
        return 0
    pkg_main = (info["package_main"] or "").lower()
    if pkg_main and pkg_main != "main.js":
        return 0
    try:
        view = LayeredView(game_dir)
        if not view.list_scenario_files():
            return 0
    except Exception:  # noqa: BLE001 — битый asar/IO: не наш движок
        return 0
    # бонус за сейвы *_tyrano_*.sav / *.sav рядом с exe
    return 120 if info["has_saves"] else 110


def _iter_ks(game_dir: str):
    """(rel,) всех сценариев обоих слоёв."""
    view = LayeredView(game_dir)
    for rel in view.list_scenario_files():
        yield rel


# ── извлечение ──

class _Extractor:
    def __init__(self):
        self.entries: list[TranslationEntry] = []
        self._next_id = 1

    def add(self, file: str, path: str, context: str, original: str):
        original = original.strip()
        if not original or not _has_letters(original):
            return
        self.entries.append(TranslationEntry(
            id=self._next_id, file=file, json_path=path,
            context=context, original=original))
        self._next_id += 1

    def line(self, file: str, rel: str, n: int, line: str):
        if len(line) > 4000:
            return
        tokens = _split_tokens(line)
        text_tokens = [t for t in tokens if t[0] == "text"]
        if not text_tokens:
            self._tag_texts(file, rel, n,
                            [t for t in tokens if t[0] == "tag"])
            return
        seg_idx = 0
        for kind, value in tokens:
            if kind == "text":
                seg_idx += 1
                self.add(file, f"line[{n}].seg[{seg_idx}]",
                         f"{rel}:{n} text", value)
        self._tag_texts(file, rel, n,
                        [t for t in tokens if t[0] == "tag"])

    def _tag_texts(self, file: str, rel: str, n: int, tags: list):
        for k, (_kind, tag) in enumerate(tags):
            # набор берём через модуль (не from-импорт): базовый парсер
            # расширяет его (glink/ptext/...) — подхватываем живьём
            name = _tag_name(tag)
            if name not in _tyrano_parser._TEXT_ATTR_TAGS:
                continue
            text = _tyrano_parser._tag_attrs(tag).get("text")
            if not text:
                continue
            kind, parts = _tyrano_parser.split_text_attr(text)
            if kind == "skip":
                continue
            if kind == "plain":
                self.add(file, f"line[{n}].tag[{k}].text",
                         f"{rel}:{n} {name}", text)
            else:
                for li, lit in parts:
                    self.add(file, f"line[{n}].tag[{k}].text#{li}",
                             f"{rel}:{n} {name} str", lit)


def extract(game_dir: str) -> list[TranslationEntry]:
    """Все переводимые строки слоёв override+asar (файл = логический rel)."""
    view = LayeredView(game_dir)
    ex = _Extractor()
    for rel in view.list_scenario_files():
        try:
            lines = view.read_lines(rel)
        except (OSError, UnicodeDecodeError):
            continue
        in_script = False
        for n, raw_line in enumerate(lines, 1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            if in_script:
                if stripped == "[endscript]" \
                        or _tag_name(stripped) in _SCRIPT_BLOCK_CLOSE:
                    in_script = False
                continue
            if _tag_name(stripped) in _SCRIPT_BLOCK_OPEN:
                in_script = True
                continue
            if stripped.startswith(";") or stripped.startswith("*"):
                continue
            ex.line(file=rel, rel=rel, n=n, line=raw_line)
    return ex.entries


# ── внедрение (только override) ──

def apply(game_dir: str, entries: list[TranslationEntry],
          backup_root: str | None = None, on_skip=None,
          target_lang: str = "", **kwargs) -> dict:
    """Внедряет переводы в override/*.ks. Возвращает статистику.

    Позиция выводится из структуры строки заново
    (line[N].seg[M] / line[N].tag[K].text) и сверяется с оригиналом.
    Записи с потерянными переменными (%var/&var/tf./f./sf.) пропускаются.
    Переводы сильно длиннее оригинала попадают в stats["long_lines"]
    (первые 30, всего — long_lines_total): кандидаты на налезание.
    """
    if backup_root is None:
        backup_root = os.path.join(game_dir, "backup")
    view = LayeredView(game_dir)
    by_file: dict[str, list[TranslationEntry]] = {}
    for e in entries:
        if e.translation.strip() and e.status != "skip":
            by_file.setdefault(e.file, []).append(e)

    stats = {"files": 0, "strings": 0, "unsafe_skipped": 0,
             "backups": [], "out_dir": view.override_root,
             "skipped_total": 0, "skipped_by": {},
             "long_lines": [], "long_lines_total": 0}

    def _skip(reason: str):
        stats["skipped_total"] += 1
        stats["skipped_by"][reason] = \
            stats["skipped_by"].get(reason, 0) + 1

    def _note_length(rel: str, lineno: int, original: str,
                     translation: str):
        """Защита от налезания: перевод сильно длиннее оригинала —
        в фиксированном окне Tyrano он вылезет за края/соседей.
        Только отчёт (первые 30) — текст не правим, чтобы не ломать
        ключи повторного извлечения."""
        o_len, t_len = len(original.strip()), len(translation.strip())
        if t_len > 24 and t_len > int(o_len * 1.7):
            stats["long_lines_total"] += 1
            if len(stats["long_lines"]) < 30:
                stats["long_lines"].append(f"{rel}:{lineno} "
                                           f"({o_len}→{t_len})")

    for rel, items in by_file.items():
        if not view.exists(rel):
            continue
        try:
            lines = view.read_lines(rel)
        except (OSError, UnicodeDecodeError):
            continue
        # бэкап до первой записи в этот файл
        if view.has_override(rel):
            src_disk = view.override_path(rel)
            bp = os.path.join(backup_root, "override", *rel.split("/"))
            if not os.path.exists(bp):
                os.makedirs(os.path.dirname(bp), exist_ok=True)
                shutil.copy2(src_disk, bp)
                stats["backups"].append(bp)
        else:
            # файл только из asar: сохраняем asar-байты для restore
            bp = os.path.join(backup_root, "asar", *rel.split("/"))
            if not os.path.exists(bp):
                raw = view.read_bytes(rel)
                if raw is not None:
                    os.makedirs(os.path.dirname(bp), exist_ok=True)
                    with open(bp, "wb") as f:
                        f.write(raw)
                    stats["backups"].append(bp)
        written = 0
        for e in items:
            m = _PATH_RE.match(e.json_path)
            if not m:
                continue
            n = int(m.group(1)) - 1
            if n < 0 or n >= len(lines):
                continue
            if not _is_var_safe(e.original, e.translation):
                stats["unsafe_skipped"] += 1
                _skip("unsafe_var")
                continue
            line = lines[n]
            if m.group(2) is not None:
                new_line, ok = _replace_seg(line, int(m.group(2)),
                                            e.original, e.translation)
            elif m.group(3) is not None:
                if not _tyrano_parser.is_tag_translation_safe(
                        e.translation):
                    # скобки/кавычки в text="..." роняют кнопку в игре —
                    # пропускаем с явной причиной, меню остаётся целым
                    stats["unsafe_skipped"] += 1
                    _skip("tag_unsafe")
                    continue
                lit = int(m.group(4)) if m.group(4) is not None else None
                new_line, ok = _replace_tag_attr(line, int(m.group(3)),
                                                 e.original, e.translation,
                                                 lit=lit)
            else:
                ok = False
                if line.strip() == e.original:
                    lead = line[:len(line) - len(line.lstrip())]
                    new_line = lead + e.translation
                    ok = True
            if not ok:
                _skip("mismatch")
                if on_skip:
                    on_skip(e, f"{rel}: строка {n + 1}: оригинал не найден")
                continue
            lines[n] = new_line
            written += 1
            _note_length(rel, n + 1, e.original, e.translation)
        if written:
            view.write_lines(rel, lines)
        stats["files"] += 1 if written else 0
        stats["strings"] += written
    return stats


def restore_original(game_dir: str) -> dict:
    """Откат override-слоя к состоянию до переводов.

    - backup/override/<rel> -> resources/app/override/<rel>;
    - файлы, созданные переводом поверх asar (есть backup/asar/<rel>,
      но не было backup/override/<rel>), удаляются из override/,
      возвращая видимость asar-оригинала.
    """
    from . import layout as _layout
    root = os.path.join(game_dir, "backup")
    if not os.path.isdir(root):
        return {"restored": 0}
    restored = 0
    ovr_backup = os.path.join(root, "override")
    if os.path.isdir(ovr_backup):
        for cur, _dirs, files in os.walk(ovr_backup):
            for f in files:
                src = os.path.join(cur, f)
                rel = os.path.relpath(src, ovr_backup).replace(os.sep, "/")
                dst = os.path.join(game_dir,
                                   _layout.OVERRIDE_REL, *rel.split("/"))
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    restored += 1
                except OSError:
                    pass
    asar_backup = os.path.join(root, "asar")
    if os.path.isdir(asar_backup):
        for cur, _dirs, files in os.walk(asar_backup):
            for f in files:
                src = os.path.join(cur, f)
                rel = os.path.relpath(src, asar_backup).replace(os.sep, "/")
                ovr_backup_file = os.path.join(ovr_backup, *rel.split("/"))
                if os.path.exists(ovr_backup_file):
                    continue  # уже восстановлен из override-бэкапа
                dst = os.path.join(game_dir,
                                   _layout.OVERRIDE_REL, *rel.split("/"))
                try:
                    if os.path.isfile(dst):
                        os.remove(dst)
                        restored += 1
                except OSError:
                    pass
                # пустые каталоги override не чистим (безопаснее)
    return {"restored": restored}
