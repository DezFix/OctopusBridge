# -*- coding: utf-8 -*-
"""Замена шрифта игры на шрифт с кириллицей (RPG Maker MV/MZ).

Два режима:
- авто (patch_font_auto): встроенный NotoSans-Regular.ttf — покрывает
  японский, кириллицу и латиницу, любой текст отрисовывается без
  квадратиков; текущий шрифт заменяется, только если в нём НЕТ
  кириллицы (cmap-проверка);
- свой файл (patch_font(game_dir, engine, path)).

MZ: шрифт задаётся в data/System.json -> advanced.mainFontFilename
    (FontManager грузит fonts/<имя файла>).
MV: шрифт задаётся в fonts/gamefont.css (@font-face GameFont), папка
    fonts/ может лежать в www/.

Оригиналы бэкапятся рядом (*.ob_backup), манифест ob_font.json хранит,
какие файлы мы добавили. restore_font() возвращает оригиналы.
"""
from __future__ import annotations

import json
import os
import re
import shutil

MZ_BACKUP_SUFFIX = ".ob_backup"
MANIFEST_NAME = "ob_font.json"


def _bundled_font() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "assets",
                        "fonts", "NotoSans-Regular.ttf")


def _cyr_check(path: str) -> bool:
    """True — шрифт ТОЧНО умеет кириллицу (sfnt-ttf с cmap).

    woff/woff2/битые файлы проверить нельзя — считаем «без кириллицы»
    (NotoSans их заменит без потерь, японские mplus кириллицы всё
    равно не содержат).
    """
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError:
        return False
    if head not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
        return False
    try:
        from app.core.renpy.fontpatch import font_supports_cyrillic
        return font_supports_cyrillic(path)
    except Exception:  # noqa: BLE001
        return False


def _resolve_fonts_dir(game_dir: str, engine: str) -> str:
    """Каталог шрифтов игры (www/fonts у деплоя MV)."""
    if engine == "mv":
        for d in (os.path.join(game_dir, "www", "fonts"),
                  os.path.join(game_dir, "fonts")):
            if os.path.isdir(d):
                return d
    else:
        d = os.path.join(game_dir, "fonts")
        if os.path.isdir(d):
            return d
    return ""


def _manifest_path(fonts_dir: str) -> str:
    return os.path.join(fonts_dir, MANIFEST_NAME)


def _load_manifest(fonts_dir: str) -> dict:
    path = _manifest_path(fonts_dir)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_manifest(fonts_dir: str, data: dict):
    with open(_manifest_path(fonts_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _current_game_font(game_dir: str, engine: str) -> str | None:
    """Путь к шрифту, который игра использует сейчас (None — не нашли)."""
    if engine == "mv":
        fonts_dir = _resolve_fonts_dir(game_dir, "mv")
        css = os.path.join(fonts_dir, "gamefont.css")
        if os.path.isfile(css):
            try:
                with open(css, encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                return None
            m = re.search(r"url\(\s*[\"']?([^\"')\s]+)[\"']?\s*\)", text)
            if m:
                return os.path.join(fonts_dir, m.group(1))
        return None
    sj = os.path.join(game_dir, "data", "System.json")
    if os.path.isfile(sj):
        try:
            with open(sj, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        name = (data.get("advanced") or {}).get("mainFontFilename")
        if name:
            return os.path.join(game_dir, "fonts", name)
    return None


def _is_same_font(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == \
            os.path.normcase(os.path.abspath(b))
    except OSError:
        return False


def _copy_backup(path: str):
    if os.path.isfile(path) and not os.path.isfile(path + MZ_BACKUP_SUFFIX):
        shutil.copy2(path, path + MZ_BACKUP_SUFFIX)


def _patch(game_dir: str, engine: str, font_path: str | None) -> dict:
    fonts_dir = _resolve_fonts_dir(game_dir, engine)
    if not fonts_dir:
        raise FileNotFoundError(
            "Не найдена папка fonts/ (ищется и в www/fonts)")
    src = font_path or _bundled_font()
    if not os.path.isfile(src):
        raise FileNotFoundError(
            "Шрифт не найден: " + src)
    if font_path is None:
        # авто: текущий шрифт уже с кириллицей — не трогаем
        cur = _current_game_font(game_dir, engine)
        if cur and os.path.isfile(cur) and _cyr_check(cur):
            return {"already": True, "font": os.path.basename(cur)}

    font_name = os.path.basename(src)
    dst_font = os.path.join(fonts_dir, font_name)
    if not os.path.isfile(dst_font):
        shutil.copy2(src, dst_font)

    manifest = _load_manifest(fonts_dir)
    manifest.setdefault("engine", engine)
    fonts_list = manifest.setdefault("fonts", [])
    backups = manifest.setdefault("backups", [])
    if font_name not in fonts_list:
        fonts_list.append(font_name)

    if engine == "mv":
        css_path = os.path.join(fonts_dir, "gamefont.css")
        _copy_backup(css_path)
        with open(css_path, "w", encoding="utf-8") as f:
            f.write("@font-face {\n"
                    "    font-family: GameFont;\n"
                    f"    src: url(\"{font_name}\") format(\"truetype\");\n"
                    "}\n")
        rel = os.path.relpath(css_path, game_dir).replace(os.sep, "/")
        if rel + MZ_BACKUP_SUFFIX not in backups:
            backups.append(rel + MZ_BACKUP_SUFFIX)
        css_abs = css_path
        backup_abs = css_path + MZ_BACKUP_SUFFIX
    else:
        system_json = os.path.join(game_dir, "data", "System.json")
        if not os.path.isfile(system_json):
            raise FileNotFoundError("Не найден data/System.json")
        _copy_backup(system_json)
        with open(system_json, encoding="utf-8") as f:
            data = json.load(f)
        advanced = data.setdefault("advanced", {})
        advanced["mainFontFilename"] = font_name
        advanced["numberFontFilename"] = font_name
        with open(system_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        rel = "data/System.json"
        if rel + MZ_BACKUP_SUFFIX not in backups:
            backups.append(rel + MZ_BACKUP_SUFFIX)
        css_abs = system_json
        backup_abs = system_json + MZ_BACKUP_SUFFIX

    _save_manifest(fonts_dir, manifest)
    return {"font": font_name, "backup": backup_abs, "css": css_abs}


def patch_font(game_dir: str, engine: str, font_path: str) -> dict:
    """Прописывает выбранный пользователем шрифт (MV/MZ)."""
    return _patch(game_dir, engine, font_path)


def patch_font_auto(game_dir: str, engine: str) -> dict:
    """Один клик: встроенный NotoSans вместо шрифта без кириллицы."""
    return _patch(game_dir, engine, None)


def is_patched(game_dir: str, engine: str) -> bool:
    """True — есть манифест патча (можно откатывать)."""
    fonts_dir = _resolve_fonts_dir(game_dir, engine)
    return bool(fonts_dir and os.path.isfile(_manifest_path(fonts_dir)))


def restore_font(game_dir: str, engine: str) -> bool:
    """Возвращает оригинальные css/System.json и удаляет наши шрифты."""
    fonts_dir = _resolve_fonts_dir(game_dir, engine)
    if not fonts_dir:
        return False
    manifest = _load_manifest(fonts_dir)
    if not manifest:
        return False
    changed = False
    for name in manifest.get("fonts", []):
        p = os.path.join(fonts_dir, name)
        try:
            if os.path.isfile(p):
                os.remove(p)
                changed = True
        except OSError:
            pass
    for rel in manifest.get("backups", []):
        bak = os.path.join(game_dir, *rel.split("/"))
        dst = bak[:-len(MZ_BACKUP_SUFFIX)] if bak.endswith(MZ_BACKUP_SUFFIX) \
            else bak
        try:
            if os.path.isfile(bak):
                shutil.copy2(bak, dst)
                os.remove(bak)
                changed = True
        except OSError:
            pass
    try:
        os.remove(_manifest_path(fonts_dir))
    except OSError:
        pass
    return changed


def patch_font_mz(game_dir: str, font_path: str) -> dict:
    """Совместимость со старым API (ручной выбор, MZ)."""
    return _patch(game_dir, "mz", font_path)


def patch_font_mv(game_dir: str, font_path: str) -> dict:
    """Совместимость со старым API (ручной выбор, MV)."""
    return _patch(game_dir, "mv", font_path)
