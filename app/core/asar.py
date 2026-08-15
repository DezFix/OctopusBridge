# -*- coding: utf-8 -*-
"""Чтение и правка ASAR-архивов Electron без распаковки всего архива.

Формат (по спецификации @electron/asar):
    [4: 4][4: размер pickle заголовка][4: payload_size][4: длина JSON]
    [JSON-дерево][выравнивание до 4][данные файлов подряд]

Заголовок — JSON-дерево: у каждого файла `offset` (строка, смещение от
начала данных), `size`, возможно `link`/`unpacked`/`integrity`.

Правка — «на месте»: если новый блоб не длиннее старого, дописываем
пробелы до исходной длины (JSON это переваривает) и перезаписываем байты —
заголовок и все смещения не меняются. Если файл вырос — архив пересобирается
целиком потоково: оригинал сохраняется рядом как <имя>.ob.bak.
"""
from __future__ import annotations

import json
import os
import struct

# константы заголовка (см. Pickle в @electron/asar)
_ALIGN = 4


class AsarError(Exception):
    """Архив не похож на asar или повреждён."""


class AsarArchive:
    """Открытый asar: заголовок в памяти, доступ к данным по смещению."""

    def __init__(self, path: str):
        self.path = path
        self.tree, self.data_offset = read_header(path)

    # ── дерево ──

    def find(self, rel: str) -> dict | None:
        """Узел дерева для rel-пути ('a/b.txt') или None."""
        node = self.tree
        for part in rel.split("/"):
            if part in ("", "."):
                continue
            files = node.get("files") if isinstance(node, dict) else None
            if not files or part not in files:
                return None
            node = files[part]
        return node

    def iter_files(self, prefix: str = ""):
        """Генератор (rel, node) для всех файлов под prefix (в порядке данных)."""
        def walk(node: dict, base: str):
            for name, sub in (node.get("files") or {}).items():
                rel = f"{base}/{name}" if base else name
                if "files" in sub:
                    yield from walk(sub, rel)
                else:
                    yield rel, sub
        root = self.find(prefix) if prefix else self.tree
        if root is None:
            return
        yield from walk(root, prefix)

    # ── навигация ──

    def exists(self, rel: str) -> bool:
        return self.find(rel) is not None

    def is_dir(self, rel: str) -> bool:
        node = self.find(rel)
        return isinstance(node, dict) and "files" in node

    def list_dir(self, rel: str) -> list[str]:
        """Имена записей (файлов и каталогов) внутри rel."""
        node = self.find(rel)
        if node is None or "files" not in node:
            return []
        return list(node["files"].keys())

    def stat_size(self, rel: str) -> int | None:
        """Размер файла в архиве (None — нет такого файла)."""
        node = self.find(rel)
        if node is None or "files" in node or "link" in node:
            return None
        try:
            return int(node.get("size", 0))
        except (TypeError, ValueError):
            return None

    # ── чтение ──

    def read_file(self, rel: str) -> bytes | None:
        """Содержимое файла (None — нет такого). Следует link, уважает unpacked."""
        node = self.find(rel)
        if node is None or "files" in node:
            return None
        if "link" in node:
            return self.read_file(node["link"])
        if node.get("unpacked"):
            unpacked = os.path.join(
                os.path.dirname(self.path) or ".",
                os.path.basename(self.path) + ".unpacked", rel)
            try:
                with open(unpacked, "rb") as f:
                    return f.read()
            except OSError:
                return None
        with open(self.path, "rb") as f:
            f.seek(self.data_offset + int(node["offset"]))
            return f.read(node["size"])

    def extract_prefix(self, prefix: str, dest_dir: str) -> int:
        """Распаковывает все файлы под prefix в dest_dir. Возвращает число файлов."""
        n = 0
        for rel, node in self.iter_files(prefix):
            rel_short = rel[len(prefix):].lstrip("/")
            out = os.path.join(dest_dir, *rel_short.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            data = self.read_file(rel)
            if data is None:
                continue
            with open(out, "wb") as f:
                f.write(data)
            n += 1
        return n


def read_header(path: str) -> tuple[dict, int]:
    """(дерево файлов, смещение начала данных)."""
    with open(path, "rb") as f:
        first = struct.unpack("<I", f.read(4))[0]
        if first != 4:
            raise AsarError(f"{path}: не похоже на asar (magic {first})")
        f.seek(12)
        json_size = struct.unpack("<I", f.read(4))[0]
        f.seek(16)
        raw = f.read(json_size)
    try:
        tree = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise AsarError(f"{path}: битый заголовок asar: {e}") from e
    pad = (-json_size) % _ALIGN
    return tree, 16 + json_size + pad


# ── запись ──

def _write_header(f: object, tree: dict) -> int:
    """Пишет pickle-заголовок. Возвращает смещение начала данных."""
    blob = json.dumps(tree, ensure_ascii=False,
                      separators=(",", ":"), default=str).encode("utf-8")
    pad = (-len(blob)) % _ALIGN
    f.write(struct.pack("<I", 4))                          # payload_size первого pickle
    f.write(struct.pack("<I", 8 + len(blob) + pad))        # размер pickle заголовка
    f.write(struct.pack("<I", 4 + len(blob) + pad))        # payload_size заголовка
    f.write(struct.pack("<I", len(blob)))                  # длина JSON
    f.write(blob)
    f.write(b"\x00" * pad)
    return 16 + len(blob) + pad


def apply_patches(path: str, patches: dict[str, bytes],
                  backup_dir: str | None = None) -> dict:
    """Заменяет файлы в asar. Возвращает статистику.

    Патч, влезающий в старый размер блоба, пишется на месте (дополняется
    пробелами — JSON их игнорирует; заголовок не трогаем). Если хоть один
    не влез — архив пересобирается целиком (оригинал -> <имя>.ob.bak).
    """
    ar = AsarArchive(path)
    stats = {"files": 0, "in_place": 0, "repacked": False, "backups": []}

    prepared: list[tuple[dict, str, bytes]] = []
    need_repack = False
    for rel, new in patches.items():
        node = ar.find(rel)
        if node is None or "files" in node or "link" in node \
                or node.get("unpacked"):
            continue
        if len(new) > node["size"]:
            need_repack = True
        prepared.append((node, rel, new))
    if not prepared:
        return stats

    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        for _node, rel, _new in prepared:
            old = ar.read_file(rel)
            if old is None:
                continue
            # бэкап по полному rel-пути — единый формат с parser.apply
            bp = os.path.join(backup_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(bp), exist_ok=True)
            with open(bp, "wb") as f:
                f.write(old)
            stats["backups"].append(bp)

    if not need_repack:
        with open(path, "r+b") as f:
            for node, _rel, new in prepared:
                padded = new + b" " * (node["size"] - len(new))
                f.seek(ar.data_offset + int(node["offset"]))
                f.write(padded)
        stats["in_place"] = len(prepared)
    else:
        _repack(path, {rel: new for _node, rel, new in prepared})
        stats["repacked"] = True
    stats["files"] = len(prepared)
    return stats


def _iter_tree(tree: dict, prefix: str = ""):
    """(rel, node) по дереву заголовка (порядок данных)."""
    for name, sub in (tree.get("files") or {}).items():
        rel = f"{prefix}/{name}" if prefix else name
        if "files" in sub:
            yield from _iter_tree(sub, rel)
        else:
            yield rel, sub


def _repack(path: str, patches: dict[str, bytes]) -> None:
    """Пересобирает asar: оригинал уходит в <path>.ob.bak, новый — на место."""
    ar = AsarArchive(path)

    bak = path + ".ob.bak"
    src_path = path
    if not os.path.exists(bak):
        # на Windows нельзя переименовать файл с открытым хэндлом —
        # сначала переименовываем, потом открываем бак для чтения
        os.replace(path, bak)
        src_path = bak

    # обновляем дерево: sizes для патчей, offsets для всех
    new_tree = json.loads(json.dumps(ar.tree))  # глубокая копия
    offset = 0
    for rel, node in _iter_tree(new_tree):
        if rel in patches:
            node["size"] = len(patches[rel])
        node["offset"] = str(offset)
        offset += node["size"]

    # чтение исходника идёт по СТАРЫМ смещениям (порядок данных не меняется)
    old_nodes = dict(ar.iter_files())

    tmp = path + ".ob.new"
    src = open(src_path, "rb")
    try:
        with open(tmp, "wb") as out:
            _write_header(out, new_tree)
            for rel, _node in _iter_tree(new_tree):
                if rel in patches:
                    out.write(patches[rel])
                else:
                    old = old_nodes[rel]
                    src.seek(ar.data_offset + int(old["offset"]))
                    out.write(src.read(old["size"]))
            out.flush()
            os.fsync(out.fileno())
    finally:
        src.close()
    os.replace(tmp, path)
