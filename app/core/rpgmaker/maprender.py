# -*- coding: utf-8 -*-
"""Данные для превью карт RPG Maker MV/MZ (Qt-free).

Геометрия тайлсетов воспроизводит движок 1:1 (rmmz_core.js, Tilemap):
- обычные тайлы B..E и A5: `_addNormalTile`;
- автотайлы A1..A4: `_addAutotile` с таблицами форм FLOOR/WALL/WATERFALL
  (каждый тайл рисуется из 2x2 четвертинок — соседи «соединяются»);
- тени: 4 четверти тайла (данные слоя тени);
- «столы» A2 (флаг 0x80): края нижней кромки через `_addTableEdge`.

Слои data[] карты (MZ, 6n): z0,z1,z2,z3 — тайлы, z4 — тени, z5 — регионы.
MV-карты (4n): z0,z1 — тайлы, z2 — тени, z3 — регионы.
"""
from __future__ import annotations

import json
import os

from .fileview import DiskFileView, FileView

TILE = 48

# ── границы tileId (как в движке) ──
TILE_ID_B = 0
TILE_ID_C = 256
TILE_ID_D = 512
TILE_ID_E = 768
TILE_ID_A5 = 1536
TILE_ID_A1 = 2048
TILE_ID_A2 = 2816
TILE_ID_A3 = 4352
TILE_ID_A4 = 5888
TILE_ID_MAX = 8192

PAGE_A1, PAGE_A2, PAGE_A3, PAGE_A4, PAGE_A5 = 0, 1, 2, 3, 4
PAGE_B = 5

# флаги тайлов (Tilesets.json "flags"): 0x10 — рисуется поверх
# (upper layer), 0x80 — «стол» (A2)
FLAG_UPPER = 0x10
FLAG_TABLE = 0x80

# ── таблицы форм автотайлов (rmmz_core.js) ──
# shape 0..47 -> 4 части (четверти тайла): [qsx, qsy]
FLOOR_AUTOTILE_TABLE = [
    [[2, 4], [1, 4], [2, 3], [1, 3]],
    [[2, 0], [1, 4], [2, 3], [1, 3]],
    [[2, 4], [3, 0], [2, 3], [1, 3]],
    [[2, 0], [3, 0], [2, 3], [1, 3]],
    [[2, 4], [1, 4], [2, 3], [3, 1]],
    [[2, 0], [1, 4], [2, 3], [3, 1]],
    [[2, 4], [3, 0], [2, 3], [3, 1]],
    [[2, 0], [3, 0], [2, 3], [3, 1]],
    [[2, 4], [1, 4], [2, 1], [1, 3]],
    [[2, 0], [1, 4], [2, 1], [1, 3]],
    [[2, 4], [3, 0], [2, 1], [1, 3]],
    [[2, 0], [3, 0], [2, 1], [1, 3]],
    [[2, 4], [1, 4], [2, 1], [3, 1]],
    [[2, 0], [1, 4], [2, 1], [3, 1]],
    [[2, 4], [3, 0], [2, 1], [3, 1]],
    [[2, 0], [3, 0], [2, 1], [3, 1]],
    [[0, 4], [1, 4], [0, 3], [1, 3]],
    [[0, 4], [3, 0], [0, 3], [1, 3]],
    [[0, 4], [1, 4], [0, 3], [3, 1]],
    [[0, 4], [3, 0], [0, 3], [3, 1]],
    [[2, 2], [1, 2], [2, 3], [1, 3]],
    [[2, 2], [1, 2], [2, 3], [3, 1]],
    [[2, 2], [1, 2], [2, 1], [1, 3]],
    [[2, 2], [1, 2], [2, 1], [3, 1]],
    [[2, 4], [3, 4], [2, 3], [3, 3]],
    [[2, 4], [3, 4], [2, 1], [3, 3]],
    [[2, 0], [3, 4], [2, 3], [3, 3]],
    [[2, 0], [3, 4], [2, 1], [3, 3]],
    [[2, 4], [1, 4], [2, 5], [1, 5]],
    [[2, 0], [1, 4], [2, 5], [1, 5]],
    [[2, 4], [3, 0], [2, 5], [1, 5]],
    [[2, 0], [3, 0], [2, 5], [1, 5]],
    [[0, 4], [3, 4], [0, 3], [3, 3]],
    [[2, 2], [1, 2], [2, 5], [1, 5]],
    [[0, 2], [1, 2], [0, 3], [1, 3]],
    [[0, 2], [1, 2], [0, 3], [3, 1]],
    [[2, 2], [3, 2], [2, 3], [3, 3]],
    [[2, 2], [3, 2], [2, 1], [3, 3]],
    [[2, 4], [3, 4], [2, 5], [3, 5]],
    [[2, 0], [3, 4], [2, 5], [3, 5]],
    [[0, 4], [1, 4], [0, 5], [1, 5]],
    [[0, 4], [3, 0], [0, 5], [1, 5]],
    [[0, 2], [3, 2], [0, 3], [3, 3]],
    [[0, 2], [1, 2], [0, 5], [1, 5]],
    [[0, 4], [3, 4], [0, 5], [3, 5]],
    [[2, 2], [3, 2], [2, 5], [3, 5]],
    [[0, 2], [3, 2], [0, 5], [3, 5]],
    [[0, 0], [1, 0], [0, 1], [1, 1]],
]

WALL_AUTOTILE_TABLE = [
    [[2, 2], [1, 2], [2, 1], [1, 1]],
    [[0, 2], [1, 2], [0, 1], [1, 1]],
    [[2, 0], [1, 0], [2, 1], [1, 1]],
    [[0, 0], [1, 0], [0, 1], [1, 1]],
    [[2, 2], [3, 2], [2, 1], [3, 1]],
    [[0, 2], [3, 2], [0, 1], [3, 1]],
    [[2, 0], [3, 0], [2, 1], [3, 1]],
    [[0, 0], [3, 0], [0, 1], [3, 1]],
    [[2, 2], [1, 2], [2, 3], [1, 3]],
    [[0, 2], [1, 2], [0, 3], [1, 3]],
    [[2, 0], [1, 0], [2, 3], [1, 3]],
    [[0, 0], [1, 0], [0, 3], [1, 3]],
    [[2, 2], [3, 2], [2, 3], [3, 3]],
    [[0, 2], [3, 2], [0, 3], [3, 3]],
    [[2, 0], [3, 0], [2, 3], [3, 3]],
    [[0, 0], [3, 0], [0, 3], [3, 3]],
]

WATERFALL_AUTOTILE_TABLE = [
    [[2, 0], [1, 0], [2, 1], [1, 1]],
    [[0, 0], [1, 0], [0, 1], [1, 1]],
    [[2, 0], [3, 0], [2, 1], [3, 1]],
    [[0, 0], [3, 0], [0, 1], [3, 1]],
]


def is_tile_a1(tile_id: int) -> bool:
    return TILE_ID_A1 <= tile_id < TILE_ID_A2


def is_tile_a2(tile_id: int) -> bool:
    return TILE_ID_A2 <= tile_id < TILE_ID_A3


def is_tile_a3(tile_id: int) -> bool:
    return TILE_ID_A3 <= tile_id < TILE_ID_A4


def is_tile_a4(tile_id: int) -> bool:
    return TILE_ID_A4 <= tile_id < TILE_ID_MAX


def is_autotile(tile_id: int) -> bool:
    return tile_id >= TILE_ID_A1


def is_shadowing_tile(tile_id: int) -> bool:
    """A3/A4 — отбрасывают тень (условие края стола)."""
    return is_tile_a3(tile_id) or is_tile_a4(tile_id)


def autotile_kind(tile_id: int) -> int:
    return (tile_id - TILE_ID_A1) // 48


def autotile_shape(tile_id: int) -> int:
    return (tile_id - TILE_ID_A1) % 48


def _normal_tile_xy(num: int) -> tuple[int, int]:
    """Позиция обычного тайла 0..255 на листе (16x16) — `_addNormalTile`."""
    sx = ((num // 128) % 2) * 8 + (num % 8)
    sy = ((num % 256) // 8) % 16
    return sx * TILE, sy * TILE


def tile_source(tile_id: int) -> tuple[int, int, int] | None:
    """tileId -> (страница, px_x, px_y) базового субтайла 48x48 или None.

    Для автотайлов — первая четверть (для совместимости/превью-значков);
    полную геометрию даёт tile_parts().
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
    parts = tile_parts(tile_id)
    if not parts:
        return None
    page, sx, sy, w, h, dx, dy = parts[0]
    return page, sx, sy


def tile_parts(tile_id: int, flags: list[int] | None = None,
               frame: int = 0) -> list[tuple[int, int, int, int, int, int, int]]:
    """Квадранты тайла по коду движка `_addNormalTile`/`_addAutotile`.

    Возвращает части (setNumber, sx, sy, w, h, dx, dy) в пикселях —
    как addRect в игре; рисуются в порядке списка.
    """
    if tile_id <= 0 or tile_id >= TILE_ID_MAX:
        return []
    if not is_autotile(tile_id):
        if tile_id < TILE_ID_A5:                    # B/C/D/E
            page = PAGE_B + tile_id // 256
        else:                                       # A5
            page = PAGE_A5
        sx, sy = _normal_tile_xy(tile_id % 256) if tile_id < TILE_ID_A5 \
            else ((tile_id - TILE_ID_A5) % 8 * TILE,
                  (tile_id - TILE_ID_A5) // 8 * TILE)
        return [(page, sx, sy, TILE, TILE, 0, 0)]

    kind = autotile_kind(tile_id)
    shape = autotile_shape(tile_id)
    tx, ty = kind % 8, kind // 8
    set_number = 0
    bx = by = 0
    table = FLOOR_AUTOTILE_TABLE
    is_table = False
    if is_tile_a1(tile_id):
        water_surface = [0, 1, 2, 1][frame % 4]
        if kind == 0:
            bx, by = water_surface * 2, 0
        elif kind == 1:
            bx, by = water_surface * 2, 3
        elif kind == 2:
            bx, by = 6, 0
        elif kind == 3:
            bx, by = 6, 3
        else:
            bx = (tx // 4) * 8
            by = ty * 6 + (tx // 2 % 2) * 3
            if kind % 2 == 0:
                bx += water_surface * 2
            else:
                bx += 6
                table = WATERFALL_AUTOTILE_TABLE
                by += frame % 3
    elif is_tile_a2(tile_id):
        set_number = 1
        bx, by = tx * 2, (ty - 2) * 3
        is_table = bool(flags) and (flags[tile_id] & FLAG_TABLE)
    elif is_tile_a3(tile_id):
        set_number = 2
        bx, by = tx * 2, (ty - 6) * 2
        table = WALL_AUTOTILE_TABLE
    elif is_tile_a4(tile_id):
        set_number = 3
        bx = tx * 2
        by = int((ty - 10) * 2.5 + (0.5 if ty % 2 == 1 else 0))
        if ty % 2 == 1:
            table = WALL_AUTOTILE_TABLE

    w1, h1 = TILE // 2, TILE // 2
    out: list[tuple[int, int, int, int, int, int, int]] = []
    for i in range(4):
        qsx, qsy = table[shape][i]
        sx1 = (bx * 2 + qsx) * w1
        sy1 = (by * 2 + qsy) * h1
        dx1 = (i % 2) * w1
        dy1 = (i // 2) * h1
        if is_table and (qsy == 1 or qsy == 5):
            qsx2 = (4 - qsx) % 4 if qsy == 1 else qsx
            sy2 = (by * 2 + 3) * h1
            out.append((set_number, (bx * 2 + qsx2) * w1, sy2,
                        w1, h1, dx1, dy1))
            out.append((set_number, sx1, sy1, w1, h1 // 2, dx1, dy1 + h1 // 2))
        else:
            out.append((set_number, sx1, sy1, w1, h1, dx1, dy1))
    return out


def table_edge_parts(tile_id: int) -> list[tuple[int, int, int, int, int, int, int]]:
    """Нижняя кромка «стола» A2 — `_addTableEdge` (2 половины)."""
    if not is_tile_a2(tile_id):
        return []
    kind = autotile_kind(tile_id)
    shape = autotile_shape(tile_id)
    tx, ty = kind % 8, kind // 8
    bx, by = tx * 2, (ty - 2) * 3
    w1, h1 = TILE // 2, TILE // 2
    out = []
    for i in range(2):
        qsx, qsy = FLOOR_AUTOTILE_TABLE[shape][2 + i]
        sx1 = (bx * 2 + qsx) * w1
        sy1 = (by * 2 + qsy) * h1 + h1 // 2
        dx1 = (i % 2) * w1
        dy1 = (i // 2) * h1
        out.append((1, sx1, sy1, w1, h1, dx1, dy1))
    return out


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


def map_layers(data: dict) -> tuple[int, int, list, list, list, list, list]:
    """-> (width, height, lower, upper, shadow, region, is_mz).

    Слои: lower = z0+z1 (нижние тайлы), upper = z2+z3 (верхние тайлы),
    shadow = биты теней, region. MZ-карты (6n) — z4 тени/z5 регионы;
    MV-карты (4n) — z2 тени/z3 регионы.
    """
    w = int(data.get("width") or 0)
    h = int(data.get("height") or 0)
    flat = data.get("data") or []
    n = w * h
    if n <= 0:
        return 0, 0, [], [], [], [], False
    layers = len(flat) // n
    is_mz = layers >= 5
    lower = flat[0:2 * n]
    upper = flat[2 * n:4 * n]
    if is_mz:
        shadow = flat[4 * n:5 * n]
        region = flat[5 * n:6 * n]
    else:
        shadow = flat[2 * n:3 * n]
        region = flat[3 * n:4 * n]
    return w, h, lower, upper, shadow, region, is_mz


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


# ---------- события ----------

from app.ui.i18n import TR as _TR


def trigger_name(code: int) -> str:
    """Локализованное имя триггера (вычисляется на лету — язык может
    смениться после импорта модуля)."""
    return _TR(f"map_trigger_{int(code)}") if 0 <= int(code) <= 4 else "?"


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
        "trigger": trigger_name((pages[0] or {}).get("trigger", 0))
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
