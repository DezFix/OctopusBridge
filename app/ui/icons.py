# -*- coding: utf-8 -*-
"""SVG-иконки Phosphor (https://phosphoricons.com) для UI.

Иконки отрисовываются из встроенных SVG-строк через QSvgRenderer
в QPixmap заданного размера — без внешних файлов и ресурсов.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

# ── Phosphor regular (256x256, stroke=currentColor, stroke-width=16) ──

_PHOSPHOR: dict[str, str] = {
    "house": ('<path d="M104,216V152h48v64h64V120a8,8,0,0,0-2.34-5.66l-80-80a8,8,0,0,0-11.32,0l-80,80A8,8,0,0,0,40,120v96Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "folder": ('<path d="M216.89,208H39.38A7.4,7.4,0,0,1,32,200.62V80H216a8,8,0,0,1,8,8V200.89A7.11,7.11,0,0,1,216.89,208Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M32,80V56a8,8,0,0,1,8-8H92.69a8,8,0,0,1,5.65,2.34L128,80" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "folder-open": ('<path d="M32,208V64a8,8,0,0,1,8-8H93.33a8,8,0,0,1,4.8,1.6L128,80h72a8,8,0,0,1,8,8v24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M32,208l30.18-90.53A8,8,0,0,1,69.77,112H232a8,8,0,0,1,7.59,10.53L211.09,208Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "translate": ('<polyline points="240 216 184 104 128 216" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="144" y1="184" x2="224" y2="184" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="96" y1="32" x2="96" y2="56" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="32" y1="56" x2="160" y2="56" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M128,56a96,96,0,0,1-96,96" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M69.47,88A96,96,0,0,0,160,152" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "broadcast": ('<circle cx="128" cy="128" r="32" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M181.67,80a71.94,71.94,0,0,1,0,96" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M74.33,176a71.94,71.94,0,0,1,0-96" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M208,49.62a111.88,111.88,0,0,1,0,156.76" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M48,206.38A111.88,111.88,0,0,1,48,49.62" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "sword": ('<rect x="75.02" y="102.75" width="33.96" height="122.49" rx="8.01" transform="translate(-89.02 113.09) rotate(-45)" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="160" y1="96" x2="104" y2="152" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M68,164,34.34,197.66a8,8,0,0,0,0,11.31L47,221.66a8,8,0,0,0,11.32,0L92,188" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polyline points="82.44 130.43 152 40 216 40 216 104 125.57 173.56" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "map-trifold": ('<line x1="96" y1="184" x2="96" y2="40" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="160" y1="72" x2="160" y2="216" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polygon points="96 184 32 200 32 56 96 40 160 72 224 56 224 200 160 216 96 184" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "image": ('<rect x="32" y="48" width="192" height="160" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><circle cx="156" cy="100" r="12" fill="currentColor" stroke="none"/><path d="M147.31,164,173,138.34a8,8,0,0,1,11.31,0L224,178.06" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M32,168.69l54.34-54.35a8,8,0,0,1,11.32,0L191.31,208" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "floppy-disk": ('<path d="M216,83.31V208a8,8,0,0,1-8,8H48a8,8,0,0,1-8-8V48a8,8,0,0,1,8-8H172.69a8,8,0,0,1,5.65,2.34l35.32,35.32A8,8,0,0,1,216,83.31Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M80,216V152a8,8,0,0,1,8-8h80a8,8,0,0,1,8,8v64" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="152" y1="72" x2="96" y2="72" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "lightning": ('<polygon points="160 16 144 96 208 120 96 240 112 160 48 136 160 16" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "list-bullets": ('<line x1="88" y1="64" x2="216" y2="64" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="88" y1="128" x2="216" y2="128" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="88" y1="192" x2="216" y2="192" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><circle cx="44" cy="64" r="12" fill="currentColor" stroke="none"/><circle cx="44" cy="128" r="12" fill="currentColor" stroke="none"/><circle cx="44" cy="192" r="12" fill="currentColor" stroke="none"/>'),
    "sliders": ('<circle cx="56" cy="136" r="24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><circle cx="128" cy="88" r="24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><circle cx="200" cy="168" r="24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="56" y1="40" x2="56" y2="112" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="200" y1="40" x2="200" y2="144" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="128" y1="40" x2="128" y2="64" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="56" y1="160" x2="56" y2="216" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="200" y1="192" x2="200" y2="216" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="128" y1="112" x2="128" y2="216" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "gear": ('<circle cx="128" cy="128" r="40" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M41.43,178.09A99.14,99.14,0,0,1,31.36,153.8l16.78-21a81.59,81.59,0,0,1,0-9.64l-16.77-21a99.43,99.43,0,0,1,10.05-24.3l26.71-3a81,81,0,0,1,6.81-6.81l3-26.7A99.14,99.14,0,0,1,102.2,31.36l21,16.78a81.59,81.59,0,0,1,9.64,0l21-16.77a99.43,99.43,0,0,1,24.3,10.05l3,26.71a81,81,0,0,1,6.81,6.81l26.7,3a99.14,99.14,0,0,1,10.07,24.29l-16.78,21a81.59,81.59,0,0,1,0,9.64l16.77,21a99.43,99.43,0,0,1-10,24.3l-26.71,3a81,81,0,0,1-6.81,6.81l-3,26.7a99.14,99.14,0,0,1-24.29,10.07l-21-16.78a81.59,81.59,0,0,1-9.64,0l-21,16.77a99.43,99.43,0,0,1-24.3-10l-3-26.71a81,81,0,0,1-6.81-6.81Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "play": ('<path d="M72,39.88V216.12a8,8,0,0,0,12.15,6.69l144.08-88.12a7.82,7.82,0,0,0,0-13.38L84.15,33.19A8,8,0,0,0,72,39.88Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "stop": ('<rect x="48" y="48" width="160" height="160" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "pause": ('<rect x="152" y="40" width="56" height="176" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><rect x="48" y="40" width="56" height="176" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "arrow-left": ('<line x1="216" y1="128" x2="40" y2="128" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polyline points="112 56 40 128 112 200" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "arrow-right": ('<line x1="40" y1="128" x2="216" y2="128" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polyline points="144 56 216 128 144 200" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "check": ('<polyline points="40 144 96 200 224 72" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "x": ('<line x1="200" y1="56" x2="56" y2="200" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="200" y1="200" x2="56" y2="56" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "pencil": ('<path d="M92.69,216H48a8,8,0,0,1-8-8V163.31a8,8,0,0,1,2.34-5.65L165.66,34.34a8,8,0,0,1,11.31,0L221.66,79a8,8,0,0,1,0,11.31L98.34,213.66A8,8,0,0,1,92.69,216Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="136" y1="64" x2="192" y2="120" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="164" y1="92" x2="68" y2="188" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="95.49" y1="215.49" x2="40.51" y2="160.51" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "magnifying-glass": ('<circle cx="116" cy="116" r="84" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="175.4" y1="175.4" x2="224" y2="224" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "sparkles": ('<path d="M143.84,85.2,126.19,50.2a8.27,8.27,0,0,0-14.38,0L94.16,85.2A35.42,35.42,0,0,1,71.5,106.16L36.2,123.81a8.27,8.27,0,0,0,0,14.38l35.3,17.65a35.43,35.43,0,0,1,22.66,23l17.65,35.3a8.27,8.27,0,0,0,14.38,0l17.65-35.3a35.43,35.43,0,0,1,22.66-23l35.3-17.65a8.27,8.27,0,0,0,0-14.38l-35.3-17.65A35.42,35.42,0,0,1,143.84,85.2Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "upload": ('<path d="M184,128h40a8,8,0,0,1,8,8v64a8,8,0,0,1-8,8H32a8,8,0,0,1-8-8V136a8,8,0,0,1,8-8H72" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="128" y1="232" x2="128" y2="128" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polyline points="80 176 128 128 176 176" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><circle cx="68" cy="168" r="12" fill="currentColor" stroke="none"/>'),
    "table": ('<path d="M32,80H224a8,8,0,0,0,8-8V48a8,8,0,0,0-8-8H32a8,8,0,0,0-8,8V72A8,8,0,0,0,32,80Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M32,160H224a8,8,0,0,0,8-8V104a8,8,0,0,0-8-8H32a8,8,0,0,0-8,8v48A8,8,0,0,0,32,160Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M32,240H224a8,8,0,0,0,8-8V192a8,8,0,0,0-8-8H32a8,8,0,0,0-8,8v40A8,8,0,0,0,32,240Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "squares-four": ('<rect x="40" y="40" width="80" height="80" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><rect x="136" y="40" width="80" height="80" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><rect x="40" y="136" width="80" height="80" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><rect x="136" y="136" width="80" height="80" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "star": ('<path d="M128,189.09l54.72,33.65a8.4,8.4,0,0,0,12.52-9.17l-14.88-62.79,48.7-42A8.46,8.46,0,0,0,224.27,94L160.36,88.8,135.74,29.2a8.36,8.36,0,0,0-15.48,0L95.64,88.8,31.73,94a8.46,8.46,0,0,0-4.79,14.83l48.7,42L60.76,213.57a8.4,8.4,0,0,0,12.52,9.17Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "circle": ('<circle cx="128" cy="128" r="96" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "info": ('<circle cx="128" cy="128" r="96" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="128" y1="120" x2="128" y2="176" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="126" y1="88" x2="130" y2="88" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "dots-three": ('<circle cx="128" cy="128" r="12" fill="currentColor" stroke="none"/><circle cx="196" cy="128" r="12" fill="currentColor" stroke="none"/><circle cx="60" cy="128" r="12" fill="currentColor" stroke="none"/>'),
    "game-controller": ('<line x1="152" y1="104" x2="176" y2="104" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="72" y1="104" x2="104" y2="104" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="88" y1="88" x2="88" y2="120" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M105.91,152,63.8,199.8a28,28,0,0,1-47.37-24.66L32.79,91a52,52,0,0,1,51.1-43H172a52,52,0,1,1,0,104Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M150.09,152l42.11,47.8a28,28,0,0,0,47.37-24.66L223.21,91" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "plus": ('<line x1="40" y1="128" x2="216" y2="128" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="128" y1="40" x2="128" y2="216" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "clock": ('<circle cx="128" cy="128" r="96" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polyline points="128 72 128 128 184 128" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "download": ('<path d="M184,128h40a8,8,0,0,1,8,8v64a8,8,0,0,1-8,8H32a8,8,0,0,1-8-8V136a8,8,0,0,1,8-8H72" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="128" y1="24" x2="128" y2="128" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polyline points="80 80 128 128 176 80" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><circle cx="188" cy="168" r="12" fill="currentColor" stroke="none"/>'),
    "speaker-high": ('<path d="M80,168H32a8,8,0,0,1-8-8V96a8,8,0,0,1,8-8H80l72-56V224Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="80" y1="88" x2="80" y2="168" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M192,106.85a32,32,0,0,1,0,42.3" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M221.67,80a72,72,0,0,1,0,96" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "film-strip": ('<rect x="32" y="72" width="192" height="112" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M120,72v112" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M136,72v112" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="32" y1="104" x2="72" y2="104" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="32" y1="152" x2="72" y2="152" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="184" y1="104" x2="224" y2="104" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="184" y1="152" x2="224" y2="152" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "file-text": ('<path d="M200,224H56a8,8,0,0,1-8-8V40a8,8,0,0,1,8-8h96l56,56V216A8,8,0,0,1,200,224Z" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polyline points="152 32 152 88 208 88" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="96" y1="136" x2="160" y2="136" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="96" y1="168" x2="160" y2="168" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "tray": ('<rect x="40" y="40" width="176" height="176" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M40,160H76.69a8,8,0,0,1,5.65,2.34l19.32,19.32a8,8,0,0,0,5.65,2.34h41.38a8,8,0,0,0,5.65-2.34l19.32-19.32a8,8,0,0,1,5.65-2.34H216" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "tray-arrow-up": ('<rect x="40" y="40" width="176" height="176" rx="8" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M40,160H76.69a8,8,0,0,1,5.65,2.34l19.32,19.32a8,8,0,0,0,5.65,2.34h41.38a8,8,0,0,0,5.65-2.34l19.32-19.32a8,8,0,0,1,5.65-2.34H216" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="128" y1="32" x2="128" y2="136" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><polyline points="80 80 128 128 176 80" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "arrows-clockwise": ('<polyline points="71.91 215.09 32 175.18 71.91 135.27" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M32,175.18h88a88,88,0,1,0-30.47-67.71" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "target": ('<line x1="128" y1="128" x2="224" y2="32" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M195.88,60.12a95.88,95.88,0,1,0,18.77,26.49" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M161.94,94.06a48,48,0,1,0,14,31.2" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
    "trash": ('<line x1="216" y1="56" x2="40" y2="56" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="104" y1="104" x2="104" y2="168" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><line x1="152" y1="104" x2="152" y2="168" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M200,56V208a8,8,0,0,1-8,8H64a8,8,0,0,1-8-8V56" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/><path d="M168,56V40a16,16,0,0,0-16-16H104A16,16,0,0,0,88,40V56" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="16"/>'),
}

# ── алиасы старых имён (Heroicons-стиль) → Phosphor ──────────────────

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
    svg = _PHOSPHOR.get(_resolve(name))
    if not svg:
        raise KeyError(f"unknown icon: {name}")
    body = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
            f'fill="none" stroke="{color}" stroke-width="16" '
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
    """QIcon из Phosphor-SVG. Цвет по умолчанию — светлый серо-голубой,
    читаемый на тёмном фоне интерфейса."""
    key = (name, size, color)
    ic = _SVG_CACHE.get(key)
    if ic is None:
        ic = QIcon(_pixmap(name, size, color))
        _SVG_CACHE[key] = ic
    return ic
