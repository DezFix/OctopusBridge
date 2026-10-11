# -*- coding: utf-8 -*-
"""РћР±С‰РёРµ РїСѓС‚Рё РїСЂРёР»РѕР¶РµРЅРёСЏ.

Р’ СЃР±РѕСЂРєРµ PyInstaller __file__ СѓРєР°Р·С‹РІР°РµС‚ РІРѕ РІСЂРµРјРµРЅРЅСѓСЋ РїР°РїРєСѓ СЂР°СЃРїР°РєРѕРІРєРё,
РїРѕСЌС‚РѕРјСѓ РІСЃРµ РїСѓС‚Рё СЃС‡РёС‚Р°РµРј С‡РµСЂРµР· СЌС‚Рё С…РµР»РїРµСЂС‹:

- bundle_dir():  РїР°РїРєР° СЂРµСЃСѓСЂСЃРѕРІ (РІРЅСѓС‚СЂРё exe / СЂСЏРґРѕРј СЃ РёСЃС…РѕРґРЅРёРєР°РјРё);
- user_data_dir(): РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёРµ РґР°РЅРЅС‹Рµ вЂ” %APPDATA%\\OctopusBridge
  (РїСЂРѕРµРєС‚С‹, Р±Р°Р·Р° РїРµСЂРµРІРѕРґР°, crash.log), РїРµСЂРµР¶РёРІР°СЋС‚ РїРµСЂРµСѓСЃС‚Р°РЅРѕРІРєСѓ;
- icon_path(): РёРєРѕРЅРєР° РїСЂРёР»РѕР¶РµРЅРёСЏ.
"""
from __future__ import annotations

import os
import sys

__version__ = "7.35"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> str:
    """РџР°РїРєР°, РіРґРµ Р»РµР¶Р°С‚ СЂРµСЃСѓСЂСЃС‹ РїСЂРёР»РѕР¶РµРЅРёСЏ (СЂР°СЃРїР°РєРѕРІР°РЅРЅС‹Р№ exe / СЂРµРїРѕР·РёС‚РѕСЂРёР№)."""
    if is_frozen():
        return sys._MEIPASS  # noqa: SLF001
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def user_data_dir() -> str:
    """РџР°РїРєР° РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРёС… РґР°РЅРЅС‹С… (СЃРѕР·РґР°С‘С‚СЃСЏ РїСЂРё РЅРµРѕР±С…РѕРґРёРјРѕСЃС‚Рё)."""
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "OctopusBridge")
    os.makedirs(d, exist_ok=True)
    return d


def projects_dir() -> str:
    """РџР°РїРєР° РїСЂРѕРµРєС‚РѕРІ (.ob.json)."""
    d = os.path.join(user_data_dir(), "projects")
    os.makedirs(d, exist_ok=True)
    return d


def temp_dir() -> str:
    """РџР°РїРєР° РІСЂРµРјРµРЅРЅС‹С… С„Р°Р№Р»РѕРІ (tmp-РїСЂРѕРµРєС‚С‹, РєРµС€)."""
    d = os.path.join(user_data_dir(), "temp")
    os.makedirs(d, exist_ok=True)
    return d


def glossary_dir() -> str:
    """РџР°РїРєР° РіР»РѕСЃСЃР°СЂРёСЏ (glossary.json)."""
    d = os.path.join(user_data_dir(), "glossary")
    os.makedirs(d, exist_ok=True)
    return d


def _safe_move_noclobber(src: str, dst: str) -> bool:
    """РџРµСЂРµРјРµСЃС‚РёС‚СЊ src -> dst, РЅРµ Р·Р°С‚РёСЂР°СЏ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёР№ dst.

    Р’РѕР·РІСЂР°С‰Р°РµС‚ True РµСЃР»Рё РїРµСЂРµРјРµС‰РµРЅРёРµ РІС‹РїРѕР»РЅРµРЅРѕ. Р•СЃР»Рё dst СѓР¶Рµ СЃСѓС‰РµСЃС‚РІСѓРµС‚ вЂ”
    РЅРёС‡РµРіРѕ РЅРµ С‚СЂРѕРіР°РµРј (Р±РµР· РїРѕС‚РµСЂСЊ): РЅРё dst РЅРµ РїРµСЂРµР·Р°РїРёСЃС‹РІР°РµС‚СЃСЏ, РЅРё src
    РЅРµ СѓРґР°Р»СЏРµС‚СЃСЏ. РћС€РёР±РєРё РїРѕРґР°РІР»СЏСЋС‚СЃСЏ (РјРёРіСЂР°С†РёСЏ best-effort).
    """
    try:
        if not os.path.isfile(src):
            return False
        if os.path.isfile(dst):
            return False
        parent = os.path.dirname(dst)
        if parent:
            os.makedirs(parent, exist_ok=True)
        os.replace(src, dst)
        return True
    except OSError:
        return False


def migrate_appdata() -> None:
    """РћРґРЅРѕСЂР°Р·РѕРІР°СЏ РјРёРіСЂР°С†РёСЏ СЃС‚Р°СЂРѕР№ СЃС‚СЂСѓРєС‚СѓСЂС‹ %APPDATA%\\OctopusBridge:

    - glossary.json РёР· РєРѕСЂРЅСЏ/РїСЂРѕРµРєС‚РѕРІ -> glossary\\glossary.json;
    - РІСЂРµРјРµРЅРЅС‹Рµ РїСЂРѕРµРєС‚С‹ tmp*.ob.json РёР· projects\\ -> temp\\.
    """
    root = user_data_dir()
    for src in (os.path.join(root, "glossary.json"),
                os.path.join(projects_dir(), "glossary.json")):
        if os.path.isfile(src):
            _safe_move_noclobber(
                src, os.path.join(glossary_dir(), "glossary.json"))
    proj = os.path.join(root, "projects")
    if os.path.isdir(proj):
        for name in os.listdir(proj):
            if name.startswith("tmp") and name.endswith(".ob.json"):
                _safe_move_noclobber(os.path.join(proj, name),
                                     os.path.join(temp_dir(), name))


def icon_path() -> str:
    return os.path.join(bundle_dir(), "assets", "ico.ico")


def crash_log_path() -> str:
    return os.path.join(user_data_dir(), "crash.log")
