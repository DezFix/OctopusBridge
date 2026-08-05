# -*- coding: utf-8 -*-
"""Данные для превью карт RPG Maker MV/MZ (Qt-free).

Геометрия тайлсетов (48px, как в rmmz_core/rpg_core):
- страницы B/C/D/E: tileId 0..1023, page = tileId // 256,
  номер = tileId % 256, сетка 16 тайлов в ряд;
- A5 (обычные): tileId 1536..1663, сетка 16 в ряд;
- автотайлы A1..A4: tileId >= 2048, 48 вариантов формы на автотайл;
  для превью рисуем базовый субтайл блока (аппроксимация).

Слои data[] карты: ground, overlay, shadow-биты, region — по w*h каждый.
"""
from __future__ import annotations

import json
import os

from . import crypto
from .fileview import DiskFileView, FileView

TILE = 48

# страницы тайлсета: индекс в tilesetNames — [A1,A2,A3,A4,A5,B,C,D,E]
# (по коду движка: автотайлы A1..A4 -> setNumber 0..3, A5 -> 4, B..E -> 5..8)
PAGE_A1, PAGE_A2, PAGE_A3, PAGE_A4, PAGE_A5 = 0, 1, 2, 3, 4
PAGE_B, PAGE_C, PAGE_D, PAGE_E = 5, 6, 7, 8

TILE_ID_A5 = 1536
TILE_ID_A1 = 2048
TILE_ID_A2 = 2816
TILE_ID_A3 = 3072
TILE_ID_A4 = 4352

PAGE_NAMES = ["A1", "A2", "A3", "A4", "A5", "B", "C", "D", "E"]


def _normal_tile_xy(num: int) -> tuple[int, int]:
    """Позиция тайла 0..255 на листе 16x16 (левая/правая половины по 128)."""
    sx = (num % 8) + (8 if num >= 128 else 0)
    sy = (num // 8) % 16
    return sx * TILE, sy * TILE


def tile_source(tile_id: int) -> tuple[int, int, int] | None:
    """tileId -> (страница, px_x, px_y) базового субтайла 48x48 или None.

    Обычные тайлы (B-E, A5) — точная геометрия движка; автотайлы A1-A4 —
    аппроксимация базовым блоком (2x2 или 2x3, 8 в ряд), достаточная
    для превью: точный выбор субтайла зависит от соседей клетки.
    """
    if tile_id <= 0:
        return None
    if tile_id < TILE_ID_A5:                       # B/C/D/E
        page = PAGE_B + tile_id // 256
        sx, sy = _normal_tile_xy(tile_id % 256)
        return page, sx, sy
    if tile_id < TILE_ID_A1:                       # A5: лист 8x16
        num = tile_id - TILE_ID_A5
        return PAGE_A5, (num % 8) * TILE, (num // 8) * TILE
    if tile_id < TILE_ID_A2:                       # A1: блоки 2x3, 8 в ряд
        idx = (tile_id - TILE_ID_A1) // 48
        return PAGE_A1, (idx % 8) * 2 * TILE, (idx // 8) * 3 * TILE
    if tile_id < TILE_ID_A3:                       # A2: fill — нижний ряд блока
        idx = (tile_id - TILE_ID_A2) // 48
        return PAGE_A2, (idx % 8) * 2 * TILE, (idx // 8) * 3 * TILE + 2 * TILE
    if tile_id < TILE_ID_A4:                       # A3: блоки 2x2, 8 в ряд
        idx = (tile_id - TILE_ID_A3) // 48
        return PAGE_A3, (idx % 8) * 2 * TILE, (idx // 8) * 2 * TILE
    if tile_id < TILE_ID_A4 + 48 * 80:             # A4: стены 2x3, 8 в ряд
        idx = (tile_id - TILE_ID_A4) // 48
        return PAGE_A4, (idx % 8) * 2 * TILE, (idx // 8) * 3 * TILE
    return None


def data_root(game_dir: str, view: FileView | None = None) -> str:
    """Относительный путь к data/ ("data" или "www/data")."""
    view = view or DiskFileView(game_dir)
    if view.is_dir("data"):
        return "data"
    return "www/data"


def map_path(game_dir: str, map_id: int,
             view: FileView | None = None) -> str | None:
    rel = f"{data_root(game_dir, view)}/Map{map_id:03d}.json"
    view = view or DiskFileView(game_dir)
    return rel if view.exists(rel) else None


def load_map(game_dir: str, map_id: int,
             view: FileView | None = None) -> dict | None:
    """Загружает MapXXX.json. None, если карты нет/битая."""
    rel = map_path(game_dir, map_id, view)
    if not rel:
        return None
    text = (view or DiskFileView(game_dir)).read_text(rel)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def map_layers(data: dict) -> tuple[int, int, list, list, list]:
    """-> (width, height, ground, overlay, shadow)."""
    w = int(data.get("width") or 0)
    h = int(data.get("height") or 0)
    flat = data.get("data") or []
    n = w * h
    ground = flat[0:n]
    overlay = flat[n:2 * n]
    shadow = flat[2 * n:3 * n]
    return w, h, ground, overlay, shadow


def load_tilesets(game_dir: str, view: FileView | None = None) -> list[dict]:
    """Tilesets.json -> список словарей (index 0 пустой-служебный)."""
    view = view or DiskFileView(game_dir)
    text = view.read_text(f"{data_root(game_dir, view)}/Tilesets.json")
    if text is None:
        return []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    return [t for t in data if isinstance(t, dict)]


def tileset_for_map(tilesets: list[dict], tileset_id: int) -> dict | None:
    for t in tilesets:
        if t.get("id") == tileset_id:
            return t
    return tilesets[0] if tilesets else None


def tileset_page_paths(game_dir: str, tileset: dict,
                       view: FileView | None = None) -> dict[int, str]:
    """{страница: rel_png_без_расширения} — только существующие файлы."""
    names = tileset.get("tilesetNames") or []
    out: dict[int, str] = {}
    for page, name in enumerate(names):
        if not name:
            continue
        rel = f"img/tilesets/{name}"
        if crypto.find_resource(game_dir, rel, (".png",), view=view):
            out[page] = rel
    return out


# ---------- события ----------

from app.ui.i18n import TR as _TR

TRIGGER_NAMES = {0: _TR("map_trigger_0"), 1: _TR("map_trigger_1"),
                 2: _TR("map_trigger_2"),
                 3: _TR("map_trigger_3"), 4: _TR("map_trigger_4")}


def event_summary(ev: dict) -> dict:
    """Ключевые свойства события для левой панели."""
    pages = ev.get("pages") or []
    img = (pages[0].get("image") or {}) if pages else {}
    return {
        "id": ev.get("id"),
        "name": ev.get("name", ""),
        "x": ev.get("x", 0),
        "y": ev.get("y", 0),
        "pages": len(pages),
        "trigger": TRIGGER_NAMES.get((pages[0] or {}).get("trigger", 0), "?")
        if pages else "—",
        "image": img.get("characterName") or "",
        "tileId": img.get("tileId", 0),
    }


def page_conditions(page: dict) -> dict:
    """Условия видимости страницы события."""
    c = page.get("conditions") or {}
    return {
        "switch1_valid": bool(c.get("switch1Valid")),
        "switch1_id": c.get("switch1Id", 1),
        "switch2_valid": bool(c.get("switch2Valid")),
        "switch2_id": c.get("switch2Id", 1),
        "variable_valid": bool(c.get("variableValid")),
        "variable_id": c.get("variableId", 1),
        "variable_value": c.get("variableValue", 0),
        "self_switch_valid": bool(c.get("selfSwitchValid")),
        "self_switch_ch": c.get("selfSwitchCh", "A"),
    }


def visibility_text(page: dict) -> str:
    """Человекочитаемое условие видимости страницы."""
    c = page_conditions(page)
    parts = []
    if c["switch1_valid"]:
        parts.append(f"SW {c['switch1_id']}=ON")
    if c["switch2_valid"]:
        parts.append(f"SW {c['switch2_id']}=ON")
    if c["variable_valid"]:
        parts.append(f"VAR {c['variable_id']}>={c['variable_value']}")
    if c["self_switch_valid"]:
        parts.append(f"Self {c['self_switch_ch']}=ON")
    return ", ".join(parts) if parts else _TR("map_vis_always")


def save_map(game_dir: str, map_id: int, data: dict,
             backup_suffix: str = ".ob_backup",
             view: FileView | None = None) -> str:
    """Перезаписывает MapXXX.json (с бэкапом рядом). Возвращает путь/rel."""
    rel = map_path(game_dir, map_id, view)
    if not rel:
        raise FileNotFoundError(f"Map{map_id:03d}.json не найдена")
    text = json.dumps(data, ensure_ascii=False)
    if view is None:
        view = DiskFileView(game_dir)
        path = os.path.join(game_dir, *rel.split("/"))
        backup = path + backup_suffix
        if not os.path.exists(backup):
            import shutil
            shutil.copy2(path, backup)
    view.write_text(rel, text)
    if not isinstance(view, DiskFileView):
        view.commit()
    return rel
