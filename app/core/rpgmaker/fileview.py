# -*- coding: utf-8 -*-
"""Файловый доступ к проекту RPG Maker: диск или asar (Electron).

Вкладки (карты, ресурсы, имена читов) читают файлы через абстракцию
FileView с относительными путями ("data/System.json", "img/tilesets/..."):
- DiskFileView — обычная игра: путь = os.path.join(game_dir, rel);
- AsarFileView — данные внутри resources/app.asar: читаются лениво прямо
  из архива; запись копится в патчи и применяется одним commit().

Оба вида прозрачно работают с префиксом "www/" (рельсы без него — тоже).
"""
from __future__ import annotations

import os

from app.core import asar


class FileView:
    """Базовый view: относительный путь rel -> байты/список.

    rel — как в обычной игре: "data/X.json", "www/data/X.json",
    "img/pics/a.png" и т.п.
    """

    def read_bytes(self, rel: str) -> bytes | None:
        raise NotImplementedError

    def read_text(self, rel: str) -> str | None:
        body = self.read_bytes(rel)
        if body is None:
            return None
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def exists(self, rel: str) -> bool:
        raise NotImplementedError

    def is_dir(self, rel: str) -> bool:
        raise NotImplementedError

    def list_dir(self, rel: str) -> list[str]:
        raise NotImplementedError

    def walk(self, rel: str) -> list[str]:
        """Все файлы под rel (рекурсивно), отсортированы."""
        raise NotImplementedError

    def size(self, rel: str) -> int | None:
        raise NotImplementedError

    def write_bytes(self, rel: str, data: bytes) -> None:
        raise NotImplementedError

    def write_text(self, rel: str, text: str) -> None:
        self.write_bytes(rel, text.encode("utf-8"))

    def commit(self) -> None:
        """Применить накопленные записи (для диска — no-op)."""


class DiskFileView(FileView):
    def __init__(self, game_dir: str):
        self.game_dir = game_dir

    def _path(self, rel: str) -> str:
        return os.path.join(self.game_dir, *rel.split("/"))

    def read_bytes(self, rel: str) -> bytes | None:
        path = self._path(rel)
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def exists(self, rel: str) -> bool:
        return os.path.isfile(self._path(rel))

    def is_dir(self, rel: str) -> bool:
        return os.path.isdir(self._path(rel))

    def list_dir(self, rel: str) -> list[str]:
        try:
            return sorted(os.listdir(self._path(rel)))
        except OSError:
            return []

    def walk(self, rel: str) -> list[str]:
        base = self._path(rel)
        out: list[str] = []
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(dirs)
            for f in sorted(files):
                p = os.path.join(root, f)
                out.append(os.path.relpath(p, self.game_dir).replace(os.sep, "/"))
        return sorted(out)

    def size(self, rel: str) -> int | None:
        try:
            return os.path.getsize(self._path(rel))
        except OSError:
            return None

    def write_bytes(self, rel: str, data: bytes) -> None:
        path = self._path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)


class AsarFileView(FileView):
    """Ленивое чтение из asar; записи копятся и применяются commit().

    Рельсы вида "data/X.json" / "www/data/X.json" разрешаются в архив:
    пробуем как есть, затем с топ-префиксами проекта ("project", "www").
    """

    def __init__(self, ar_path: str, backup_dir: str | None = None):
        self.ar_path = ar_path
        self.backup_dir = backup_dir
        self._ar = asar.AsarArchive(ar_path)
        self._patches: dict[str, bytes] = {}
        tops = self._ar.list_dir("")
        self._tops = [t for t in ("project", "www") if t in tops]

    def _resolve(self, rel: str) -> str | None:
        """Архивный rel для виртуального rel (первый существующий кандидат)."""
        if self._ar.exists(rel):
            return rel
        for top in self._tops:
            cand = f"{top}/{rel}"
            if self._ar.exists(cand):
                return cand
        return None

    def _rel_for_write(self, rel: str) -> str:
        resolved = self._resolve(rel)
        if resolved is not None:
            return resolved
        top = self._tops[0] if self._tops else ""
        return f"{top}/{rel}" if top else rel

    def read_bytes(self, rel: str) -> bytes | None:
        resolved = self._resolve(rel)
        if resolved is None:
            return None
        if resolved in self._patches:
            return self._patches[resolved]
        return self._ar.read_file(resolved)

    def exists(self, rel: str) -> bool:
        return self._resolve(rel) is not None

    def is_dir(self, rel: str) -> bool:
        resolved = self._resolve(rel)
        return self._ar.is_dir(resolved) if resolved else False

    def list_dir(self, rel: str) -> list[str]:
        resolved = self._resolve(rel)
        return self._ar.list_dir(resolved) if resolved else []

    def walk(self, rel: str) -> list[str]:
        resolved = self._resolve(rel)
        if resolved is None:
            return []
        top = next((t for t in self._tops if resolved.startswith(t + "/")), "")
        cut = len(top) + 1 if top else 0
        out = [r[cut:] for r, _ in self._ar.iter_files(resolved)]
        return sorted(out)

    def size(self, rel: str) -> int | None:
        resolved = self._resolve(rel)
        if resolved is None:
            return None
        if resolved in self._patches:
            return len(self._patches[resolved])
        return self._ar.stat_size(resolved)

    def write_bytes(self, rel: str, data: bytes) -> None:
        self._patches[self._rel_for_write(rel)] = data

    def commit(self) -> None:
        """Применяет накопленные патчи в asar (в месте или пересборкой)."""
        if not self._patches:
            return
        stats = asar.apply_patches(
            self.ar_path, dict(self._patches), backup_dir=self.backup_dir)
        self._patches = {}
        self._ar = asar.AsarArchive(self.ar_path)
        return stats
