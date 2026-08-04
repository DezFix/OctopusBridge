# -*- coding: utf-8 -*-
"""Жёсткая замена шрифтов Ren'Py на универсальный NotoSans.

Универсальный метод (работает с любой игрой, включая японские):
шрифт NotoSans-Regular.ttf покрывает японский, кириллицу, латиницу —
любой текст (RU/JP/EN) отрисовывается без квадратиков.
- локальные файлы шрифтов в game/ — перезаписываются на месте,
  оригиналы копируются в game/ob_fonts_orig/ (манифест manifest.json);
- шрифты ВНУТРИ .rpa-архивов — не трогая архив, в game/ кладётся
  перекрывающий файл с тем же путём: движок Ren'Py ищет файл сначала
  на диске и лишь потом в архивах, поэтому перекрытие гарантированно
  побеждает. Оригинал остаётся в архиве нетронутым.

Заменяются только шрифты, в cmap которых НЕТ кириллицы (U+0400–U+04FF).
Имена файлов сохраняются — все ссылки (gui.text_font, style.*.font и т.п.)
продолжают работать, «квадратики» исчезают даже при запуске игры напрямую,
без моста. restore_font() возвращает оригиналы и удаляет перекрытия.
"""
from __future__ import annotations

import os
import shutil

FONT_EXTS = (".ttf", ".otf", ".ttc", ".otc", ".woff", ".woff2")
ORIG_DIR = "ob_fonts_orig"
MANIFEST = "manifest.json"

_CYR_START = 0x0400
_CYR_END = 0x04FF


def _bundled_font() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "assets",
                        "fonts", "NotoSans-Regular.ttf")


def _cmap_subtable_has_cyr(data: bytes, sub: int) -> bool:
    if sub + 2 > len(data):
        return False
    fmt = int.from_bytes(data[sub:sub + 2], "big")

    def glyph_ok(gid: int) -> bool:
        return gid != 0

    if fmt == 4:
        if sub + 14 > len(data):
            return False
        segx2 = int.from_bytes(data[sub + 6:sub + 8], "big")
        if segx2 < 2 or sub + 14 + 4 * segx2 > len(data):
            return False
        seg = segx2 // 2
        endc = sub + 14
        startc = endc + segx2 + 2
        deltac = startc + segx2
        rangec = deltac + segx2
        for j in range(seg):
            e = int.from_bytes(data[endc + 2 * j:endc + 2 * j + 2], "big")
            s = int.from_bytes(data[startc + 2 * j:startc + 2 * j + 2], "big")
            if not (s <= _CYR_END and e >= _CYR_START):
                continue
            delta = int.from_bytes(data[deltac + 2 * j:deltac + 2 * j + 2], "big")
            if delta == 0:
                ro = int.from_bytes(data[rangec + 2 * j:rangec + 2 * j + 2], "big")
                if ro == 0:
                    continue
                for c in range(max(s, _CYR_START), min(e, _CYR_END) + 1):
                    addr = rangec + 2 * j + ro + 2 * (c - s)
                    if addr + 2 > len(data):
                        break
                    if glyph_ok(int.from_bytes(data[addr:addr + 2], "big")):
                        return True
            else:
                return True
        return False
    if fmt == 6:
        if sub + 10 > len(data):
            return False
        first = int.from_bytes(data[sub + 6:sub + 8], "big")
        cnt = int.from_bytes(data[sub + 8:sub + 10], "big")
        if not (first <= _CYR_END and first + cnt >= _CYR_START):
            return False
        gly = sub + 10
        for c in range(max(first, _CYR_START), min(first + cnt - 1, _CYR_END) + 1):
            off = gly + 2 * (c - first)
            if off + 2 > len(data):
                break
            if glyph_ok(int.from_bytes(data[off:off + 2], "big")):
                return True
        return False
    if fmt == 12:
        if sub + 16 > len(data):
            return False
        n = int.from_bytes(data[sub + 12:sub + 16], "big")
        g = sub + 16
        for j in range(n):
            o = g + 12 * j
            if o + 12 > len(data):
                break
            s = int.from_bytes(data[o:o + 4], "big")
            e = int.from_bytes(data[o + 4:o + 8], "big")
            sgid = int.from_bytes(data[o + 8:o + 12], "big")
            if s <= _CYR_END and e >= _CYR_START and sgid != 0:
                return True
        return False
    return False


def _check_cyr_bytes(data: bytes) -> bool:
    """True — байты шрифта уже умеют кириллицу (или формат неизвестен)."""
    if len(data) < 12:
        return True
    if data[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
        return True
    num = int.from_bytes(data[4:6], "big")
    for i in range(num):
        off = 12 + 16 * i
        if off + 16 > len(data):
            break
        if data[off:off + 4] == b"cmap":
            tbl = int.from_bytes(data[off + 8:off + 12], "big")
            if tbl + 4 > len(data):
                continue
            nsub = int.from_bytes(data[tbl + 2:tbl + 4], "big")
            for k in range(nsub):
                rec = tbl + 4 + 8 * k
                if rec + 8 > len(data):
                    break
                sub = tbl + int.from_bytes(data[rec + 4:rec + 8], "big")
                if _cmap_subtable_has_cyr(data, sub):
                    return True
    return False


def font_supports_cyrillic(path: str) -> bool:
    """True — шрифт уже умеет кириллицу (или формат неизвестен — не трогаем)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return True
    return _check_cyr_bytes(data)


def is_patched(game_dir: str) -> bool:
    """True — есть манифест жёсткого патча (можно откатывать)."""
    return os.path.isfile(os.path.join(game_dir, "game", ORIG_DIR, MANIFEST))


def _save_manifest(manifest_path: str, patched: dict, overrides: dict):
    import json
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({"patched": patched, "overrides": overrides,
                   "count": len(patched) + len(overrides)}, f,
                  ensure_ascii=False, indent=1)


def _load_manifest(manifest_path: str) -> dict:
    import json
    if not os.path.isfile(manifest_path):
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def patch_font(game_dir: str) -> dict:
    """Заменяет шрифты без кириллицы на NotoSans. Возвращает отчёт.

    Работает и с локальными шрифтами, и со шрифтами внутри .rpa-архивов
    (перекрывающие файлы в game/ — Ren'Py читает диск раньше архивов).
    """
    font_src = _bundled_font()
    if not os.path.isfile(font_src):
        raise RuntimeError("NotoSans-Regular.ttf не найден в комплекте")
    with open(font_src, "rb") as f:
        noto = f.read()
    game_sub = os.path.join(game_dir, "game")
    if not os.path.isdir(game_sub):
        raise RuntimeError("game/ не найдена")
    orig_dir = os.path.join(game_sub, ORIG_DIR)
    manifest_path = os.path.join(orig_dir, MANIFEST)
    manifest = _load_manifest(manifest_path)
    patched = manifest.get("patched", {})
    overrides = manifest.get("overrides", {})
    os.makedirs(orig_dir, exist_ok=True)
    replaced = 0
    for root, dirs, files in os.walk(game_sub):
        dirs[:] = [d for d in dirs
                   if d not in (ORIG_DIR, "ob_fonts", "tl", "__pycache__")]
        for name in files:
            if not name.lower().endswith(FONT_EXTS):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, game_sub).replace(os.sep, "/")
            if font_supports_cyrillic(path):
                continue
            try:
                with open(path, "rb") as f:
                    cur = f.read()
            except OSError as e:
                raise RuntimeError(f"Не удалось прочитать {rel}: {e}")
            if cur == noto:
                continue  # уже заменён
            if rel not in patched:
                back = f"_b{replaced}_{name}"
                try:
                    with open(os.path.join(orig_dir, back), "wb") as f:
                        f.write(cur)
                except OSError as e:
                    raise RuntimeError(
                        f"Не удалось сохранить оригинал {rel}: {e}")
                patched[rel] = back
            try:
                with open(path, "wb") as f:
                    f.write(noto)
            except OSError:
                raise RuntimeError(
                    "Не удалось перезаписать шрифт — закройте игру и повторите")
            replaced += 1
            _save_manifest(manifest_path, patched, overrides)
    # шрифты внутри .rpa-архивов → перекрывающие файлы в game/
    from app.core.renpy.rpa import find_rpa_archives, RpaArchive
    for arch_path in find_rpa_archives(game_dir):
        try:
            arch = RpaArchive(arch_path)
        except Exception:
            continue  # битый архив — не мешаем остальным
        for name in arch.files:
            low = name.lower()
            if not low.endswith(FONT_EXTS):
                continue
            rel = name.replace("\\", "/")
            dst = os.path.join(game_sub, *rel.split("/"))
            if os.path.isfile(dst):
                continue  # локальный файл уже в приоритете над архивом
            try:
                data = arch.read(name)
            except Exception:
                continue
            if _check_cyr_bytes(data) or data == noto:
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(noto)
            except OSError:
                continue  # запись перекрытия не удалась — пропускаем
            overrides[rel] = os.path.relpath(arch_path, game_dir) \
                .replace(os.sep, "/")
            replaced += 1
            _save_manifest(manifest_path, patched, overrides)
    return {"replaced": replaced,
            "total": len(patched) + len(overrides)}


def restore_font(game_dir: str) -> bool:
    """Возвращает оригинальные шрифты и удаляет перекрытия архивов."""
    game_sub = os.path.join(game_dir, "game")
    orig_dir = os.path.join(game_sub, ORIG_DIR)
    manifest_path = os.path.join(orig_dir, MANIFEST)
    manifest = _load_manifest(manifest_path)
    if not manifest:
        return False
    patched = manifest.get("patched", {})
    for rel, back in patched.items():
        src = os.path.join(orig_dir, back)
        dst = os.path.join(game_sub, *rel.split("/"))
        if os.path.isfile(src):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            except OSError as e:
                raise RuntimeError(f"Не удалось восстановить {rel}: {e}")
    for rel in manifest.get("overrides", {}):
        dst = os.path.join(game_sub, *rel.split("/"))
        try:
            os.remove(dst)
        except OSError:
            pass
        d = os.path.dirname(dst)
        while d.startswith(game_sub) and d != game_sub:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
    shutil.rmtree(orig_dir, ignore_errors=True)
    return True
