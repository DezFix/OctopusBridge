# -*- coding: utf-8 -*-
"""Поиск тестовых игр для интеграционных тестов.

Игры НЕ входят в репозиторий (авторские права). Тесты ищут их в
нескольких типичных местах на машине разработчика и пропускаются,
если игра не найдена (как в CI).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

_RPGM_GAME = "The Suffering of The Modest Witch"
_RPGM_CANDIDATES = [
    os.path.join(ROOT, "TEMP", _RPGM_GAME),
    os.path.join(ROOT, "..", "!TEMP", _RPGM_GAME),
    r"D:\CODE\!TEMP" + "\\" + _RPGM_GAME,
    r"D:\CODE\WrGameBridge\TEMP" + "\\" + _RPGM_GAME,
]


def find_rpgm_game() -> str:
    """Возвращает путь к тестовой RPG Maker игре или пустую строку."""
    for p in _RPGM_CANDIDATES:
        if os.path.isdir(p):
            return p
    return ""


def skip_no_game(name: str) -> None:
    print(f"ПРОПУСК: тестовая игра {name} не найдена")
    sys.exit(0)
