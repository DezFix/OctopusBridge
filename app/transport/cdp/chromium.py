# -*- coding: utf-8 -*-
"""Поиск Chromium-браузера в системе для запуска Twine-игр под CDP."""
from __future__ import annotations

import os
import shutil

_CANDIDATES = [
    r"Microsoft\Edge\Application\msedge.exe",
    r"Google\Chrome\Application\chrome.exe",
    r"Chromium\Application\chrome.exe",
    r"BraveSoftware\Brave-Browser\Application\brave.exe",
]

_PROG_DIRS = [
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    os.environ.get("ProgramFiles", r"C:\Program Files"),
    os.environ.get("LOCALAPPDATA", ""),
]


def find_chromium() -> str | None:
    for base in _PROG_DIRS:
        if not base:
            continue
        for rel in _CANDIDATES:
            path = os.path.join(base, rel)
            if os.path.isfile(path):
                return path
    for name in ("msedge.exe", "chrome.exe", "brave.exe", "chromium.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None
