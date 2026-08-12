# -*- coding: utf-8 -*-
"""Расшифровка ресурсов RPG Maker MV/MZ (.png_, .ogg_, .m4a_).

Формат: 16-байтный заголовок 'RPGMV\\0\\0\\0\\3\\0\\1\\0\\0\\0\\0\\0',
затем первые 16 байт исходного файла, XOR-енные ключом из
System.json:encryptionKey (MZ) или rpg_core.js (MV).
"""
from __future__ import annotations

import json
import re

from app.core.rpgmaker.fileview import DiskFileView

SIGNATURE = b"RPGMV\x00\x00\x00\x00\x03\x01\x00\x00\x00\x00\x00"
HEADER_LEN = 16


def _view(game_dir: str, view=None):
    return view or DiskFileView(game_dir)


def get_key_mz(game_dir: str, view=None) -> str | None:
    view = _view(game_dir, view)
    for rel in ("data/System.json", "www/data/System.json"):
        text = view.read_text(rel)
        if text is None:
            continue
        try:
            key = json.loads(text).get("encryptionKey")
        except ValueError:
            continue
        if key:
            return key
    return None


def get_key_mv(game_dir: str, view=None) -> str | None:
    view = _view(game_dir, view)
    text = view.read_text("js/rpg_core.js")
    if text is None:
        text = view.read_text("www/js/rpg_core.js")
    if text is None:
        return None
    m = re.search(r'encryptionKey["\s:]+([0-9a-f]{32})', text)
    return m.group(1) if m else None


def decrypt_bytes(body: bytes, key_hex: str) -> bytes:
    """Расшифровывает содержимое .png_/.rpgmvp и т.п. из памяти."""
    if body[:HEADER_LEN] != SIGNATURE:
        raise ValueError("Not an encrypted RPGM file (signature mismatch)")
    key = bytes.fromhex(key_hex)
    head = bytes(b ^ key[i] for i, b in enumerate(body[HEADER_LEN:HEADER_LEN * 2]))
    return head + body[HEADER_LEN * 2:]


# MZ: .png_ / .ogg_ / .m4a_;  MV: .rpgmvp / .rpgmvo / .rpgmvm
ENCRYPTED_SUFFIXES = (".png_", ".ogg_", ".m4a_",
                      ".rpgmvp", ".rpgmvo", ".rpgmvm")


def is_encrypted_name(filename: str) -> bool:
    return filename.lower().endswith(ENCRYPTED_SUFFIXES)


def get_key(game_dir: str, view=None) -> str | None:
    """Ключ шифрования: MZ (System.json) или MV (rpg_core.js), и в www/."""
    view = _view(game_dir, view)
    return get_key_mz(game_dir, view) or get_key_mv(game_dir, view)


# варианты имени для незашифрованного ext: (MZ-суффикс, MV-замена ext)
_MV_ENC_EXT = {".png": ".rpgmvp", ".ogg": ".rpgmvo", ".m4a": ".rpgmvm"}


def _resource_rels(rel_no_ext: str, exts: tuple[str, ...]) -> list[str]:
    """Кандидаты путей ресурса: www/, MZ-суффиксы, MV-замены ext."""
    out: list[str] = []
    for base in (rel_no_ext, "www/" + rel_no_ext):
        for ext in exts:
            out.append(base + ext)
            out.append(base + ext + "_")
            mv_ext = _MV_ENC_EXT.get(ext)
            if mv_ext:
                out.append(base + mv_ext)
    return out


def find_resource(game_dir: str, rel_no_ext: str,
                  exts: tuple[str, ...] = (".png",), view=None) -> str | None:
    """Ищет ресурс с учётом деплоя в www/ и шифрованных вариантов имени.

    find_resource(game, "img/tilesets/Outside") найдёт
    img/tilesets/Outside.png, Outside.png_ (MZ) или Outside.rpgmvp (MV),
    в том числе в www/. Возвращает относительный путь (rel) или None.
    """
    view = _view(game_dir, view)
    for rel in _resource_rels(rel_no_ext, exts):
        if view.exists(rel):
            return rel
    return None


def read_image(game_dir: str, rel_no_ext: str,
               key: str | None = None, view=None) -> bytes | None:
    """Возвращает байты PNG (расшифровывая при необходимости) или None."""
    view = _view(game_dir, view)
    rel = find_resource(game_dir, rel_no_ext, (".png",), view=view)
    if not rel:
        return None
    body = view.read_bytes(rel)
    if body is None:
        return None
    if is_encrypted_name(rel):
        if key is None:
            key = get_key(game_dir, view=view)
        if not key:
            return None
        try:
            return decrypt_bytes(body, key)
        except (ValueError, IndexError):
            return None
    return body
