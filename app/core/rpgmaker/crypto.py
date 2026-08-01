# -*- coding: utf-8 -*-
"""Расшифровка ресурсов RPG Maker MV/MZ (.png_, .ogg_, .m4a_).

Формат: 16-байтный заголовок 'RPGMV\\0\\0\\0\\3\\0\\1\\0\\0\\0\\0\\0',
затем первые 16 байт исходного файла, XOR-енные ключом из
System.json:encryptionKey (MZ) или rpg_core.js (MV).
"""
from __future__ import annotations

import json
import os
import re

SIGNATURE = b"RPGMV\x00\x00\x00\x00\x03\x01\x00\x00\x00\x00\x00"
HEADER_LEN = 16


def get_key_mz(game_dir: str) -> str | None:
    path = os.path.join(game_dir, "data", "System.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("encryptionKey")


def get_key_mv(game_dir: str) -> str | None:
    path = os.path.join(game_dir, "js", "rpg_core.js")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="ignore") as f:
        m = re.search(r'encryptionKey["\s:]+([0-9a-f]{32})', f.read())
    return m.group(1) if m else None


def decrypt_file(path: str, key_hex: str) -> bytes:
    """Расшифровывает файл ресурса и возвращает исходные байты."""
    with open(path, "rb") as f:
        body = f.read()
    return decrypt_bytes(body, key_hex)


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


def get_key(game_dir: str) -> str | None:
    """Ключ шифрования: MZ (System.json) или MV (rpg_core.js), и в www/."""
    key = get_key_mz(game_dir) or get_key_mv(game_dir)
    if key:
        return key
    www = os.path.join(game_dir, "www")
    if os.path.isdir(www):
        return get_key_mz(www) or get_key_mv(www)
    return None


# варианты имени для незашифрованного ext: (MZ-суффикс, MV-замена ext)
_MV_ENC_EXT = {".png": ".rpgmvp", ".ogg": ".rpgmvo", ".m4a": ".rpgmvm"}


def find_resource(game_dir: str, rel_no_ext: str,
                  exts: tuple[str, ...] = (".png",)) -> str | None:
    """Ищет ресурс с учётом деплоя в www/ и шифрованных вариантов имени.

    find_resource(game, "img/tilesets/Outside") найдёт
    img/tilesets/Outside.png, Outside.png_ (MZ) или Outside.rpgmvp (MV),
    в том числе в www/.
    """
    roots = [game_dir, os.path.join(game_dir, "www")]
    for root in roots:
        base = os.path.join(root, *rel_no_ext.split("/"))
        for ext in exts:
            candidates = [base + ext, base + ext + "_"]
            mv_ext = _MV_ENC_EXT.get(ext)
            if mv_ext:
                candidates.append(base + mv_ext)
            for path in candidates:
                if os.path.isfile(path):
                    return path
    return None


def read_image(game_dir: str, rel_no_ext: str,
               key: str | None = None) -> bytes | None:
    """Возвращает байты PNG (расшифровывая при необходимости) или None."""
    path = find_resource(game_dir, rel_no_ext, (".png",))
    if not path:
        return None
    with open(path, "rb") as f:
        body = f.read()
    if is_encrypted_name(path):
        if key is None:
            key = get_key(game_dir)
        if not key:
            return None
        try:
            return decrypt_bytes(body, key)
        except (ValueError, IndexError):
            return None
    return body
