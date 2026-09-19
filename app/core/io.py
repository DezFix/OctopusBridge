# -*- coding: utf-8 -*-
"""Атомарные файловые операции — защита от потери данных при записи.

Проблема: прямая запись ``open(path, "w")`` усекает файл в начале,
и обрыв (крэш, выключение, нехватка места) оставляет на диске
половинчатый/пустой файл. Решение: пишем в уникальный tmp в той же
директории, затем ``flush + os.fsync + os.replace``.

- :func:`atomic_write_text` / :func:`atomic_write_bytes` — база;
- :func:`atomic_write_json` — JSON через ``atomic_write_text``;
- :func:`read_json_safe` — чтение без исключений;
- :class:`BackupStore` — версионированные бэкапы с ``manifest.json``.
"""
from __future__ import annotations

import json
import os
import tempfile


def atomic_write_bytes(path: str, data: bytes) -> None:
    """Атомарно записать байты: tmp в той же директории + fsync + replace."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".new")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync может не поддерживаться (некоторые FS) —
                # данные уже во временном файле, replace всё равно безопасен
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: str, text: str, encoding: str = "utf-8") -> None:
    """Атомарно записать текст (см. :func:`atomic_write_bytes`)."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".new")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: str,
    obj,
    indent: int | None = None,
    ensure_ascii: bool = False,
    **kwargs,
) -> None:
    """Атомарно записать JSON (``ensure_ascii=False`` по умолчанию)."""
    text = json.dumps(obj, ensure_ascii=ensure_ascii, indent=indent, **kwargs)
    atomic_write_text(path, text, encoding="utf-8")


def read_json_safe(path: str, encoding: str = "utf-8"):
    """Прочитать JSON без исключений.

    Возвращает ``(obj | None, error | None)``: при успехе ``(obj, None)``,
    при любой ошибке ``(None, exc)``. Исключений не бросает.
    """
    try:
        with open(path, encoding=encoding) as f:
            return json.load(f), None
    except Exception as e:  # noqa: BLE001 — контракт: не бросать
        return None, e


class BackupStore:
    """Версионированные бэкапы файлов с ``manifest.json``.

    - бэкапы лежат в ``backup_dir``;
    - ``manifest.json``: ``{"files": {abs_orig: backup_name}}``;
    - повторный :meth:`backup` уже забэкапленного файла — no-op
      (существующий бэкап не перезаписывается).
    """

    MANIFEST = "manifest.json"

    def __init__(self, backup_dir: str):
        self.backup_dir = os.path.abspath(backup_dir)
        self.manifest_path = os.path.join(self.backup_dir, self.MANIFEST)
        self._manifest: dict = {"files": {}}
        obj, _err = read_json_safe(self.manifest_path)
        if isinstance(obj, dict):
            files = obj.get("files")
            if isinstance(files, dict):
                # только строковые пары
                clean = {str(k): str(v) for k, v in files.items()}
                self._manifest = {"files": clean}
            elif not obj:
                self._manifest = {"files": {}}

    def _save_manifest(self) -> None:
        os.makedirs(self.backup_dir, exist_ok=True)
        atomic_write_json(self.manifest_path, self._manifest, indent=1)

    def backup(self, file_path: str) -> str | None:
        """Скопировать файл в хранилище. Вернуть путь бэкапа или None.

        Если бэкап для этого файла уже есть и цел — не трогать,
        вернуть существующий путь.
        """
        if not file_path or not os.path.isfile(file_path):
            return None
        os.makedirs(self.backup_dir, exist_ok=True)
        abs_orig = os.path.abspath(file_path)
        files: dict = self._manifest.setdefault("files", {})

        existing = files.get(abs_orig)
        if existing:
            existing_path = os.path.join(self.backup_dir, existing)
            if os.path.isfile(existing_path):
                return existing_path
            # запись в манифесте есть, а файла нет — пересоздадим
            # под тем же именем (без версионирования)
            try:
                with open(abs_orig, "rb") as f:
                    data = f.read()
                atomic_write_bytes(existing_path, data)
                try:
                    import shutil

                    shutil.copystat(abs_orig, existing_path)
                except OSError:
                    pass
                self._save_manifest()
                return existing_path
            except OSError:
                return None

        base = os.path.basename(abs_orig) or "file"
        candidate = base + ".bak"
        taken = set(files.values())
        name = candidate
        i = 1
        while name in taken or os.path.isfile(
            os.path.join(self.backup_dir, name)
        ):
            i += 1
            name = f"{candidate}.{i}"
            if i > 1000:  # pragma: no cover — защита от бесконечного цикла
                return None
        dst = os.path.join(self.backup_dir, name)
        try:
            with open(abs_orig, "rb") as f:
                data = f.read()
            atomic_write_bytes(dst, data)
            try:
                import shutil

                shutil.copystat(abs_orig, dst)
            except OSError:
                pass
        except OSError:
            return None
        files[abs_orig] = name
        try:
            self._save_manifest()
        except OSError:
            pass
        return dst

    def restore_all(self) -> dict:
        """Вернуть все бэкапы на место (атомарно). Возвращает статистику."""
        restored = 0
        errors: list[str] = []
        for abs_orig, name in list(
            self._manifest.get("files", {}).items()
        ):
            src = os.path.join(self.backup_dir, name)
            if not os.path.isfile(src):
                continue
            try:
                parent = os.path.dirname(abs_orig)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(src, "rb") as f:
                    data = f.read()
                atomic_write_bytes(abs_orig, data)
                restored += 1
            except OSError as e:
                errors.append(f"{abs_orig}: {e}")
        result: dict = {"restored": restored}
        if errors:
            result["errors"] = errors
        return result
