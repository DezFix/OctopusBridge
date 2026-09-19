# -*- coding: utf-8 -*-
"""Слоёный доступ к файлам AjinSyoujyo: override/ поверх app.asar.

Логический путь rel — как внутри бандла игры: "data/scenario/x.ks",
"tyrano/lang.js", "index.html". Физически:
- чтение: resources/app/override/<rel>, иначе app.asar/<rel>;
- запись: всегда resources/app/override/<rel> (asar не меняем).

Кодировки .ks: utf-8-sig / utf-8 / cp932, перевод строк CRLF/LF
и финальный newline запоминаются по rel для побайтово-бережной записи.
"""
from __future__ import annotations

import os

from app.core import asar as asar_mod

from . import layout as layout_mod

# подкаталоги со сценариями внутри бандла (логические префиксы)
SCENARIO_PREFIXES = (
    "data/scenario",
    "data/system",
)

# файлы, которые никогда не считаем сценариями (движок/конфиг оболочки)
_NON_SCENARIO_BASENAMES = {
    "config.ks",  # системный конфиг сценариев — трогаем только явно
}


class LayeredView:
    """override/ + app.asar как единая файловая система (read + write)."""

    def __init__(self, game_dir: str):
        self.game_dir = game_dir
        self.asar_file = layout_mod.asar_path(game_dir)
        self.override_root = os.path.join(game_dir,
                                          layout_mod.OVERRIDE_REL)
        self._ar: asar_mod.AsarArchive | None = None
        if self.asar_file:
            try:
                self._ar = asar_mod.AsarArchive(self.asar_file)
            except Exception:  # noqa: BLE001 — пустой/битый asar: работаем с override
                self._ar = None
        # rel -> (enc, nl, trailing_nl) для бережной записи .ks
        self._meta: dict[str, tuple[str, str, bool]] = {}

    # ── пути ──

    def override_path(self, rel: str) -> str:
        return os.path.join(self.override_root, *rel.split("/"))

    def has_override(self, rel: str) -> bool:
        return os.path.isfile(self.override_path(rel))

    def has_asar(self, rel: str) -> bool:
        return bool(self._ar and self._ar.exists(rel))

    def exists(self, rel: str) -> bool:
        return self.has_override(rel) or self.has_asar(rel)

    # ── листинг (только имена, без чтения содержимого) ──

    def _list_override_ks(self, prefix: str) -> list[str]:
        # Рекурсивно: сценарии лежат и в подпапках (base/, event/,
        # home/, system/) — плоский os.listdir их не видел, и текст
        # из подпапок никогда не попадал в перевод.
        base = os.path.join(self.override_root, *prefix.split("/"))
        out: list[str] = []
        for cur, dirs, files in os.walk(base):
            dirs.sort()
            for n in sorted(files):
                if not n.lower().endswith(".ks"):
                    continue
                rel = os.path.relpath(os.path.join(cur, n),
                                      self.override_root)
                out.append(rel.replace(os.sep, "/"))
        return sorted(out)

    def _list_asar_ks(self, prefix: str) -> list[str]:
        # iter_files идёт по дереву рекурсивно (в отличие от list_dir).
        if not self._ar:
            return []
        try:
            return sorted(rel for rel, _node in self._ar.iter_files(prefix)
                          if rel.lower().endswith(".ks"))
        except OSError:
            return []

    def list_scenario_files(self) -> list[str]:
        """Все .ks обоих слоёв (override перекрывает asar), отсортированы."""
        seen: dict[str, None] = {}
        for prefix in SCENARIO_PREFIXES:
            for rel in self._list_asar_ks(prefix) \
                    + self._list_override_ks(prefix):
                if os.path.basename(rel) in _NON_SCENARIO_BASENAMES \
                        and prefix == "data/system":
                    # system/config.ks — служебный, по умолчанию пропускаем
                    continue
                seen.setdefault(rel)
        return sorted(seen)

    # ── чтение ──

    def read_bytes(self, rel: str) -> bytes | None:
        try:
            with open(self.override_path(rel), "rb") as f:
                return f.read()
        except OSError:
            pass
        if self._ar:
            try:
                return self._ar.read_file(rel)
            except OSError:
                return None
        return None

    def read_lines(self, rel: str) -> list[str]:
        """Строки .ks + запоминание enc/nl/trailing для записи."""
        raw = self.read_bytes(rel)
        if raw is None:
            raise OSError(f"not found: {rel}")
        for enc in ("utf-8-sig", "utf-8", "cp932"):
            try:
                text = raw.decode(enc)
            except (UnicodeDecodeError, ValueError):
                continue
            store_enc = "utf-8" if enc != "cp932" else "cp932"
            nl = "\r\n" if b"\r\n" in raw else "\n"
            self._meta[rel] = (store_enc, nl, text.endswith(("\n", "\r")))
            return text.splitlines()
        raise UnicodeDecodeError("ajin", raw, 0, 1, "no suitable encoding")

    # ── запись (только в override) ──

    def write_lines(self, rel: str, lines: list[str]) -> str:
        """Пишет .ks в override/, возвращает физический путь."""
        enc, nl, trailing = self._meta.get(rel, ("utf-8", "\n", True))
        body = nl.join(lines)
        if trailing and not body.endswith(nl):
            body += nl
        out = self.override_path(rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding=enc, newline="") as f:
            f.write(body)
        return out

    def write_bytes(self, rel: str, data: bytes) -> str:
        out = self.override_path(rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(data)
        return out
