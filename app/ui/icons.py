# -*- coding: utf-8 -*-
"""SVG-иконки Lucide (https://lucide.dev) для UI.

Иконки отрисовываются из встроенных SVG-строк через QSvgRenderer
в QPixmap заданного размера — без внешних файлов и ресурсов.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

# ── Lucide (24x24, stroke=currentColor, stroke-width=2, round caps/joins) ──

_LUCIDE: dict[str, str] = {
    "house": ('<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8" />'
              '<path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />'),
    "folder": ('<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" />'),
    "folder-open": ('<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2" />'),
    "translate": ('<path d="m5 8 6 6" />'
                  '<path d="m4 14 6-6 2-3" />'
                  '<path d="M2 5h12" />'
                  '<path d="M7 2h1" />'
                  '<path d="m22 22-5-10-5 10" />'
                  '<path d="M14 18h6" />'),
    "broadcast": ('<path d="M16.247 7.761a6 6 0 0 1 0 8.478" />'
                  '<path d="M19.075 4.933a10 10 0 0 1 0 14.134" />'
                  '<path d="M4.925 19.067a10 10 0 0 1 0-14.134" />'
                  '<path d="M7.753 16.239a6 6 0 0 1 0-8.478" />'
                  '<circle cx="12" cy="12" r="2" />'),
    "sword": ('<path d="m11 19-6-6" />'
              '<path d="m5 21-2-2" />'
              '<path d="m8 16-4 4" />'
              '<path d="M9.5 17.5 21 6V3h-3L6.5 14.5" />'),
    "map-trifold": ('<path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z" />'
                    '<path d="M15 5.764v15" />'
                    '<path d="M9 3.236v15" />'),
    "image": ('<rect width="18" height="18" x="3" y="3" rx="2" ry="2" />'
              '<circle cx="9" cy="9" r="2" />'
              '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />'),
    "floppy-disk": ('<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" />'
                    '<path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7" />'
                    '<path d="M7 3v4a1 1 0 0 0 1 1h7" />'),
    "lightning": ('<path d="M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z" />'),
    "list-bullets": ('<path d="M3 5h.01" />'
                     '<path d="M3 12h.01" />'
                     '<path d="M3 19h.01" />'
                     '<path d="M8 5h13" />'
                     '<path d="M8 12h13" />'
                     '<path d="M8 19h13" />'),
    "sliders": ('<path d="M10 5H3" />'
                '<path d="M12 19H3" />'
                '<path d="M14 3v4" />'
                '<path d="M16 17v4" />'
                '<path d="M21 12h-9" />'
                '<path d="M21 19h-5" />'
                '<path d="M21 5h-7" />'
                '<path d="M8 10v4" />'
                '<path d="M8 12H3" />'),
    "gear": ('<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915" />'
             '<circle cx="12" cy="12" r="3" />'),
    "play": ('<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z" />'),
    "stop": ('<rect width="18" height="18" x="3" y="3" rx="2" />'),
    "pause": ('<rect x="14" y="3" width="5" height="18" rx="1" />'
              '<rect x="5" y="3" width="5" height="18" rx="1" />'),
    "arrow-left": ('<path d="m12 19-7-7 7-7" />'
                   '<path d="M19 12H5" />'),
    "arrow-right": ('<path d="M5 12h14" />'
                    '<path d="m12 5 7 7-7 7" />'),
    "check": ('<path d="M20 6 9 17l-5-5" />'),
    "x": ('<path d="M18 6 6 18" />'
          '<path d="m6 6 12 12" />'),
    "pencil": ('<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" />'
               '<path d="m15 5 4 4" />'),
    "magnifying-glass": ('<path d="m21 21-4.34-4.34" />'
                         '<circle cx="11" cy="11" r="8" />'),
    "sparkles": ('<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z" />'
                 '<path d="M20 2v4" />'
                 '<path d="M22 4h-4" />'
                 '<circle cx="4" cy="20" r="2" />'),
    "upload": ('<path d="M12 3v12" />'
               '<path d="m17 8-5-5-5 5" />'
               '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />'),
    "table": ('<path d="M12 3v18" />'
              '<rect width="18" height="18" x="3" y="3" rx="2" />'
              '<path d="M3 9h18" />'
              '<path d="M3 15h18" />'),
    "squares-four": ('<rect width="7" height="7" x="3" y="3" rx="1" />'
                     '<rect width="7" height="7" x="14" y="3" rx="1" />'
                     '<rect width="7" height="7" x="14" y="14" rx="1" />'
                     '<rect width="7" height="7" x="3" y="14" rx="1" />'),
    "star": ('<path d="M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z" />'),
    "circle": ('<circle cx="12" cy="12" r="10" />'),
    "info": ('<circle cx="12" cy="12" r="10" />'
             '<path d="M12 16v-4" />'
             '<path d="M12 8h.01" />'),
    "dots-three": ('<circle cx="12" cy="12" r="1" />'
                   '<circle cx="19" cy="12" r="1" />'
                   '<circle cx="5" cy="12" r="1" />'),
    "game-controller": ('<line x1="6" x2="10" y1="11" y2="11" />'
                        '<line x1="8" x2="8" y1="9" y2="13" />'
                        '<line x1="15" x2="15.01" y1="12" y2="12" />'
                        '<line x1="18" x2="18.01" y1="10" y2="10" />'
                        '<path d="M17.32 5H6.68a4 4 0 0 0-3.978 3.59c-.006.052-.01.101-.017.152C2.604 9.416 2 14.456 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.414-1.414A2 2 0 0 1 9.828 16h4.344a2 2 0 0 1 1.414.586L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.545-.604-6.584-.685-7.258-.007-.05-.011-.1-.017-.151A4 4 0 0 0 17.32 5z" />'),
    "plus": ('<path d="M5 12h14" />'
             '<path d="M12 5v14" />'),
    "clock": ('<circle cx="12" cy="12" r="10" />'
              '<path d="M12 6v6l4 2" />'),
    "download": ('<path d="M12 15V3" />'
                 '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />'
                 '<path d="m7 10 5 5 5-5" />'),
    "speaker-high": ('<path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z" />'
                     '<path d="M16 9a5 5 0 0 1 0 6" />'
                     '<path d="M19.364 18.364a9 9 0 0 0 0-12.728" />'),
    "film-strip": ('<rect width="18" height="18" x="3" y="3" rx="2" />'
                   '<path d="M7 3v18" />'
                   '<path d="M3 7.5h4" />'
                   '<path d="M3 12h18" />'
                   '<path d="M3 16.5h4" />'
                   '<path d="M17 3v18" />'
                   '<path d="M17 7.5h4" />'
                   '<path d="M17 16.5h4" />'),
    "file-text": ('<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z" />'
                  '<path d="M14 2v5a1 1 0 0 0 1 1h5" />'
                  '<path d="M10 9H8" />'
                  '<path d="M16 13H8" />'
                  '<path d="M16 17H8" />'),
    "tray": ('<polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />'
             '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />'),
    "tray-arrow-up": ('<rect width="20" height="5" x="2" y="3" rx="1" />'
                      '<path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" />'
                      '<path d="M10 12h4" />'
                      '<path d="M12 6v5" />'
                      '<path d="m9.5 8.5 2.5-2.5 2.5 2.5" />'),
    "arrows-clockwise": ('<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />'
                         '<path d="M21 3v5h-5" />'
                         '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />'
                         '<path d="M8 16H3v5" />'),
    "target": ('<circle cx="12" cy="12" r="10" />'
               '<circle cx="12" cy="12" r="6" />'
               '<circle cx="12" cy="12" r="2" />'),
    "trash": ('<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />'
              '<path d="M3 6h18" />'
              '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />'),
    "book-bookmark": ('<path d="M10 2v8l3-3 3 3V2" />'
                      '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20" />'),
}

# ── алиасы старых имён (Heroicons-стиль) → Lucide ────────────────────

_ALIASES: dict[str, str] = {
    "home": "house",
    "document-text": "file-text",
    "bolt": "lightning",
    "cheats": "sword",
    "triggers": "target",
    "map": "map-trifold",
    "mountains": "map-trifold",
    "save": "floppy-disk",
    "audio": "speaker-high",
    "video": "film-strip",
    "cross": "x",
    "dots-h": "dots-three",
    "run": "play",
    "gamepad": "game-controller",
    "cog": "gear",
    "dot": "circle",
    "search": "magnifying-glass",
    "ai": "sparkles",
    "cards": "squares-four",
    "grid": "squares-four",
}

_SVG_CACHE: dict[tuple[str, int, str], QIcon] = {}


def _resolve(name: str) -> str:
    return _ALIASES.get(name, name)


def _pixmap(name: str, size: int, color: str) -> QPixmap:
    svg = _LUCIDE.get(_resolve(name))
    if not svg:
        raise KeyError(f"unknown icon: {name}")
    body = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{svg}</svg>')
    from PySide6.QtSvg import QSvgRenderer
    renderer = QSvgRenderer(QByteArray(body.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    return pm


def icon(name: str, size: int = 18, color: str = "#b0b8cf") -> QIcon:
    """QIcon из Lucide-SVG. Цвет по умолчанию — светлый серо-голубой,
    читаемый на тёмном фоне интерфейса."""
    key = (name, size, color)
    ic = _SVG_CACHE.get(key)
    if ic is None:
        ic = QIcon(_pixmap(name, size, color))
        _SVG_CACHE[key] = ic
    return ic