# -*- coding: utf-8 -*-
"""Модуль HTML (generic) — overlay-only движок для обычных HTML-игр.

Детект нарочно слабый (вес 10): уступаем Twine (60), RenPy (60-80)
и RPG Maker (90-110). Если в папке найден <tw-storydata> или маркеры
других движков — возвращаем 0, пусть их модули забирают игру.

Файлового перевода нет: extract() пуст, apply() — no-op. Весь перевод —
live-оверлей через HtmlTentacle (HTTP+WS, тот же generic DOM-механизм,
что у Twine: TreeWalker + MutationObserver поверх text nodeValue).
"""
from __future__ import annotations

import os

from app.engines.base import EngineModule

_HEAD_SIZE = 2 * 1024 * 1024


def _head_contains(path: str, needle: str) -> bool:
    """Есть ли needle в голове файла (до 2 МБ)."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            return needle in fh.read(_HEAD_SIZE)
    except OSError:
        return False


def _iter_html_at(game_dir: str, sub: str):
    """Пути .html/.htm (case-insensitive) в подпапке sub ("" = корень)."""
    base = game_dir if not sub else os.path.join(game_dir, sub)
    try:
        entries = os.listdir(base)
    except OSError:
        return
    for f in entries:
        if f.lower().endswith((".html", ".htm")):
            p = os.path.join(base, f)
            if os.path.isfile(p):
                yield p


def _has_tw_storydata(game_dir: str) -> bool:
    """Scope как TwineModule.detect: корень + 1 подуровень, голова 2 МБ."""
    for p in _iter_html_at(game_dir, ""):
        if _head_contains(p, "<tw-storydata"):
            return True
    try:
        entries = os.listdir(game_dir)
    except OSError:
        return False
    for f in entries:
        sub = os.path.join(game_dir, f)
        if not os.path.isdir(sub):
            continue
        for p in _iter_html_at(game_dir, f):
            if _head_contains(p, "<tw-storydata"):
                return True
    return False


def _has_rpgm_markers(game_dir: str) -> bool:
    """Маркеры RPG Maker: data/System.json, js-рантайм, .rpgmvm, .asar."""
    if os.path.isfile(os.path.join(game_dir, "data", "System.json")):
        return True
    for js_rel in (os.path.join("www", "js"), "js"):
        js_dir = os.path.join(game_dir, js_rel)
        try:
            for f in os.listdir(js_dir):
                if f.lower().endswith(".js") and os.path.isfile(
                        os.path.join(js_dir, f)):
                    return True
        except OSError:
            pass
    try:
        for f in os.listdir(game_dir):
            if f.lower().endswith((".rpgmvm", ".asar")):
                return True
    except OSError:
        pass
    if os.path.isfile(os.path.join(game_dir, "resources", "app.asar")):
        return True
    try:
        for f in os.listdir(os.path.join(game_dir, "data")):
            if f.lower().endswith(".rpgmvm"):
                return True
    except OSError:
        pass
    return False


def _has_renpy_markers(game_dir: str) -> bool:
    """Маркеры RenPy: game/*.rpy|*.rpyc|*.rpa, каталог renpy/."""
    game_sub = os.path.join(game_dir, "game")
    if os.path.isdir(game_sub):
        for _root, _dirs, files in os.walk(game_sub):
            for f in files:
                if f.lower().endswith((".rpy", ".rpyc", ".rpa")):
                    return True
    if os.path.isdir(os.path.join(game_dir, "renpy")):
        return True
    return False


def _has_html(game_dir: str) -> bool:
    """Есть ли .html/.htm в корне или на уровень вглубь."""
    for _p in _iter_html_at(game_dir, ""):
        return True
    try:
        entries = os.listdir(game_dir)
    except OSError:
        return False
    for f in entries:
        if not os.path.isdir(os.path.join(game_dir, f)):
            continue
        for _p in _iter_html_at(game_dir, f):
            return True
    return False


class HtmlModule(EngineModule):
    key = "html"
    title = "HTML"
    maturity = "experimental"
    features = {"live"}

    @classmethod
    def detect(cls, game_dir: str) -> int:
        # Прямой файл .html/.htm: наш, если это не Twine-история.
        if os.path.isfile(game_dir) \
                and game_dir.lower().endswith((".html", ".htm")):
            if _head_contains(game_dir, "<tw-storydata"):
                return 0
            return 10
        if not os.path.isdir(game_dir):
            return 0
        # Чужие движки забирают игру первыми.
        if _has_tw_storydata(game_dir):
            return 0
        if _has_rpgm_markers(game_dir):
            return 0
        if _has_renpy_markers(game_dir):
            return 0
        if _has_html(game_dir):
            return 10
        return 0

    def __init__(self, game_dir: str):
        self.game_path: str | None = None
        if os.path.isfile(game_dir) \
                and game_dir.lower().endswith((".html", ".htm")):
            self.game_path = game_dir

    @property
    def display(self) -> str:
        return "HTML"

    def extract(self, game_dir: str) -> list:
        # Overlay-only: файлового потока нет, всё — live поверх игры.
        return []

    def apply(self, game_dir: str, entries: list, **kwargs) -> dict:
        # Overlay-only: файлы игры не трогаем вообще.
        return {"files": 0, "strings": 0}
