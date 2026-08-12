# -*- coding: utf-8 -*-
"""Чтение .rpa-архивов Ren'Py (v1, v2, v3, v3.0).

Форматы:
- RPA-3.0 (Ren'Py 8+): 'RPA-3.0 ' + offset(16 hex) + ' ' + key(8 hex)
  + '\\nMade with Ren'Py.\\n'. Индекс — XOR с key, затем zlib.
- RPA-3 / RPA-2 (Ren'Py 7):  'RPA-3' + offset(8 LE) + index_size(8 LE)
  + version(4 LE). Индекс — zlib.
- RPA-1: 'RPA' + offset(8 LE) + index_size(8 LE). Индекс без сжатия.
"""
from __future__ import annotations

import os
import struct
import zlib


class RpaArchive:
    """Читатель .rpa-архива Ren'Py (v1, v2, v3, v3.0)."""

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
        elif head[:5] == b"RPA-3":
            self._load_v3(head)
        elif head[:5] == b"RPA-2":
            self._load_v2(head)
        elif head[:3] == b"RPA":
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

        # Ren'Py 8: индекс — zlib(pickle) со словарём
        # {name: [(offset, dlen) | (offset, dlen, start)]}, поля XOR'ены с key.
        try:
            import pickle
            index = pickle.loads(zlib.decompress(data))
        except Exception as e:
            raise ValueError(f"Broken RPA-3.0 index in {self.path}: {e}")
        self._index_offset = index_offset
        for name, entries in index.items():
            if not entries:
                continue
            first = entries[0]
            if len(first) < 2:
                continue
            offset, length = first[0] ^ key, first[1] ^ key
            self._index[name] = (offset, length)

    def _load_v3(self, head: bytes):
        with open(self.path, "rb") as f:
            f.seek(5)
            offset = struct.unpack("<Q", f.read(8))[0]
            index_size = struct.unpack("<Q", f.read(8))[0]
            f.read(4)
            self.version = 3
            f.seek(offset)
            data = f.read(index_size)
            if data:
                data = zlib.decompress(data)
            if data:
                self._parse_index(data)

    def _load_v2(self, head: bytes):
        with open(self.path, "rb") as f:
            f.seek(5)
            offset = struct.unpack("<Q", f.read(8))[0]
            index_size = struct.unpack("<Q", f.read(8))[0]
            self.version = 2
            f.seek(offset)
            data = f.read(index_size)
            if data:
                data = zlib.decompress(data)
            if data:
                self._parse_index(data)

    def _load_v1(self, head: bytes):
        with open(self.path, "rb") as f:
            f.seek(3)
            offset = struct.unpack("<Q", f.read(8))[0]
            index_size = struct.unpack("<Q", f.read(8))[0]
            self.version = 1
            f.seek(offset)
            data = f.read(index_size)
            if data:
                self._parse_index(data)

    def _parse_index(self, data: bytes):
        i = 0
        while i + 4 <= len(data):
            path_len = struct.unpack("<H", data[i:i + 2])[0]
            i += 2
            if i + path_len > len(data):
                break
            path = data[i:i + path_len].decode("utf-8", errors="replace")
            i += path_len
            start = struct.unpack("<Q", data[i:i + 8])[0]
            i += 8
            length = struct.unpack("<Q", data[i:i + 8])[0]
            i += 8
            if self.version == 3:
                i += 4
            self._index[path] = (start, length)

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
