# -*- coding: utf-8 -*-
"""Чтение .rpa-архивов Ren'Py (v1, v2, v3.0).

Форматы (сверены с renpy/loader.py 8.2.3 и 7.7.3):
- RPA-3.0 (Ren'Py 7.4+/8.x): 'RPA-3.0 ' + offset(16 hex) + ' ' + key(8 hex)
  + '\\n'. Индекс — zlib(pickle), поля XOR'ены с key.
- RPA-2.0 (Ren'Py 6.99-7.3): 'RPA-2.0 ' + offset(16 hex). Индекс —
  zlib(pickle), без XOR.
- RPA-1 (Ren'Py 6.x, .rpi): весь файл — zlib(pickle) индекса, без шапки.
"""
from __future__ import annotations

import os
import zlib


class RpaArchive:
    """Читатель .rpa-архива Ren'Py (v1, v2, v3.0)."""

    def __init__(self, path: str):
        self.path = path
        self.version = 0
        self._index: dict[str, tuple[int, int]] = {}
        self._load()

    def _load(self):
        with open(self.path, "rb") as f:
            head = f.read(64)

        if head[:8] == b"RPA-3.0 " or head[:7] == b"RPA-3.0":
            self._load_v3_0(head)
        elif head[:8] == b"RPA-2.0 " or head[:7] == b"RPA-2.0":
            self._load_v2(head)
        elif head[:2] == b"\x78\x9c":
            # RPA-1: весь файл — zlib(pickle) индекса (шапки нет)
            self._load_v1(head)
        else:
            raise ValueError(f"Not an RPA archive: {self.path}")

    def _load_v3_0(self, head: bytes):
        self.version = 30

        # Parse hex offset and key from human-readable header
        try:
            off_str = head[8:24].decode("ascii").strip()
            index_offset = int(off_str, 16)
            key_str = head[25:33].decode("ascii").strip()
            key = int(key_str, 16)
        except (ValueError, IndexError):
            raise ValueError(f"Invalid RPA-3.0 header in {self.path}")

        with open(self.path, "rb") as f:
            f.seek(index_offset)
            data = f.read()
        self._parse_index_pickle(data, key)

    def _load_v2(self, head: bytes):
        self.version = 2

        # 'RPA-2.0 ' + offset(16 hex) — ключа нет (Ren'Py 6.99-7.3)
        try:
            index_offset = int(head[8:24].decode("ascii").strip(), 16)
        except (ValueError, IndexError):
            raise ValueError(f"Invalid RPA-2.0 header in {self.path}")

        with open(self.path, "rb") as f:
            f.seek(index_offset)
            data = f.read()
        self._parse_index_pickle(data, 0)

    def _load_v1(self, head: bytes):
        self.version = 1

        with open(self.path, "rb") as f:
            data = f.read()
        self._parse_index_pickle(data, 0)

    def _parse_index_pickle(self, data: bytes, key: int):
        """Индекс RPA-2.0/3.0: zlib(pickle) словаря
        {name: [(offset, dlen) | (offset, dlen, start)]}, поля (кроме
        RPA-2.0) XOR'ены с key."""
        import pickle
        try:
            index = pickle.loads(zlib.decompress(data))
        except Exception as e:
            raise ValueError(f"Broken RPA index in {self.path}: {e}")
        for name, entries in index.items():
            if not entries:
                continue
            first = entries[0]
            if len(first) < 2:
                continue
            offset, length = first[0] ^ key, first[1] ^ key
            self._index[name] = (offset, length)

    @property
    def files(self) -> list[str]:
        return sorted(self._index.keys())

    def read(self, path: str) -> bytes:
        if path not in self._index:
            raise KeyError(f"File not found in archive: {path}")
        offset, length = self._index[path]
        with open(self.path, "rb") as f:
            f.seek(offset)
            return f.read(length)

    def extract_to(self, path: str, dest: str):
        data = self.read(path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)

    def __repr__(self):
        return f"RpaArchive({self.path!r}, v{self.version}, {len(self.files)} files)"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def find_rpa_archives(game_dir: str) -> list[str]:
    """Находит все .rpa-архивы в game/."""
    result = []
    game_sub = os.path.join(game_dir, "game")
    if not os.path.isdir(game_sub):
        return result
    for root, _dirs, files in os.walk(game_sub):
        for f in files:
            if f.lower().endswith(".rpa"):
                result.append(os.path.join(root, f))
    return result
