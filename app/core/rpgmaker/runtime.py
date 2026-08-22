# -*- coding: utf-8 -*-
"""Runtime-overlay для RPG Maker MV/MZ — вариант 3.

Идея: НИКОГДА не трогать оригинальные файлы игры (data/*.json, Map*.json,
js/plugins/*.js). Вместо этого:

* извлечённый текст хранится отдельно — .ob.json проекта;
* при «Применить» переводы пишутся в ОДИН внешний JSON
  ``ob_translation/<lang>.json`` рядом с игрой (чистый текст, без кода);
* рантайм-плагин ``ob_runtime.js`` читает этот JSON при старте игры
  и подменяет текст в памяти через хуки Window_Base / Game_Actor и т.д.

Гарантии:
* Оригинальные ``data/`` и ``www/data/`` не модифицируются → игра не ломается
  на неизвестных играх/плагинах.
* Работает для обычных игр, MV-деплея в ``www/`` и MZ/MV без шифрования.
  Для Electron/asar и шифрованных карт — live-режим (CDP/мост) без патча
  архива: перевод виден при запуске через OctopusBridge.
* Откат = удалить два файла + запись в plugins.js.

Модуль используется из ``app.engines.rpgmaker`` (apply/restore) и не
зависит от UI.
"""
from __future__ import annotations

import json
import os
import re

from app.core.rpgmaker import variant as rpgm_variant

RUNTIME_PLUGIN_NAME = "ob_runtime"
RUNTIME_DIRNAME = "ob_translation"

# ── JS-плагин рантайма ────────────────────────────────────────────
# Тот же _TRANSLATION_PAYLOAD что в tentacle.py (хуки диалогов + обход
# $data*-таблиц в памяти). Словарь вшит прямо в файл — синхронный XHR
# за оверлеем убран: file://-запросы ненадёжны, а JSON-оверлей остаётся
# на диске как читаемый артефакт для внешних инструментов.
_RUNTIME_PLUGIN_TEMPLATE = r"""
// OctopusBridge runtime translation — не редактируйте
// targetLang={{LANG}}  entries={{COUNT}}
(function () {
  if (window.__octopus_runtime_loaded) return;
  window.__octopus_runtime_loaded = true;

{{TRANSLATION_PAYLOAD}}

  window.__octopus_trInstall({{DICT_JSON}});
})();
"""


def _overlay_rel_for_variant(variant: str) -> str:
    # MV www-деплой: www/js/plugins/ob_runtime.js грузится из www/,
    # оверлей кладём в www/ob_translation/ — xhr ../ob_translation
    # покрывает оба случая через tries[]
    return f"{RUNTIME_DIRNAME}/ru.json"


def _is_www_deploy(game_dir: str) -> bool:
    return (os.path.isdir(os.path.join(game_dir, "www", "data"))
            or os.path.isfile(os.path.join(game_dir, "www", "index.html")))


def _overlay_abs(game_dir: str, target_lang: str = "ru") -> str:
    if _is_www_deploy(game_dir):
        return os.path.join(game_dir, "www", RUNTIME_DIRNAME,
                            f"{target_lang}.json")
    return os.path.join(game_dir, RUNTIME_DIRNAME, f"{target_lang}.json")


def _runtime_plugin_rel(game_dir: str) -> str:
    if _is_www_deploy(game_dir):
        return "www/js/plugins/ob_runtime.js"
    return "js/plugins/ob_runtime.js"


def _runtime_plugin_abs(game_dir: str) -> str:
    return os.path.join(game_dir, _runtime_plugin_rel(game_dir).replace("/", os.sep))


def _plugins_list_rel_for_runtime(game_dir: str) -> str | None:
    # переиспользуем логику variant.py — ищем plugins.js
    from app.core.rpgmaker.fileview import DiskFileView
    view = DiskFileView(game_dir)
    variant = rpgm_variant.detect_variant(game_dir, view)
    from app.core.rpgmaker.variant import plugins_list_rel
    # предпочитаем js/plugins.js (куда кладём рантайм), но принимаем любой
    rel = plugins_list_rel(variant, game_dir, "data")
    if rel:
        return rel
    # fallback: js/plugins.js даже если детект не сработал
    for cand in ("js/plugins.js", "www/js/plugins.js",
                 "data/plugins.js", "www/data/plugins.js"):
        if os.path.isfile(os.path.join(game_dir, cand.replace("/", os.sep))):
            return cand
    return None


def build_runtime_source(tr_dict: dict, target_lang: str = "ru",
                         overlay_rel: str | None = None) -> str:
    """JS-код рантайм-плагина с вшитым словарём."""
    from app.engines.rpgmaker.tentacle import _TRANSLATION_PAYLOAD
    from app.core.rpgmaker.mv_bridge import js_json
    dict_json = js_json(tr_dict) if tr_dict else "{}"
    # payload заканчивается на window.__octopus_trInstall(__TR_DICT__); —
    # убираем его и вставляем свой вызов с реальным словарём,
    # чтобы не дублировать пустую установку
    payload = _TRANSLATION_PAYLOAD.replace("__TR_DICT__", "{}")
    if "window.__octopus_trInstall({});" in payload:
        payload = payload.replace(
            "window.__octopus_trInstall({});", "")
    return (_RUNTIME_PLUGIN_TEMPLATE
            .replace("{{TRANSLATION_PAYLOAD}}", payload)
            .replace("{{DICT_JSON}}", dict_json)
            .replace("{{LANG}}", target_lang)
            .replace("{{COUNT}}", str(len(tr_dict))))


def _ensure_plugins_entry(game_dir: str, plugin_name: str = RUNTIME_PLUGIN_NAME) -> bool:
    rel = _plugins_list_rel_for_runtime(game_dir)
    if not rel:
        return False
    path = os.path.join(game_dir, rel.replace("/", os.sep))
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    if f'"{plugin_name}"' in text:
        return True
    entry = (f'{{"name":"{plugin_name}","status":true,'
             f'"description":"OctopusBridge runtime translation","parameters":{{}}}}')
    is_json = text.lstrip().startswith("[")
    if is_json:
        try:
            data = json.loads(text)
        except ValueError:
            return False
        data.append(json.loads(entry))
        new_text = json.dumps(data, ensure_ascii=False, indent=1)
    else:
        idx = text.rfind("]")
        if idx < 0:
            return False
        head = text[:idx].rstrip()
        if head.endswith(","):
            head = head[:-1]
        new_text = head + ",\n" + entry + "\n" + text[idx:]
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_text)
        return True
    except OSError:
        return False


def _remove_plugins_entry(game_dir: str, plugin_name: str = RUNTIME_PLUGIN_NAME) -> bool:
    rel = _plugins_list_rel_for_runtime(game_dir)
    if not rel:
        return False
    path = os.path.join(game_dir, rel.replace("/", os.sep))
    if not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    # JSON-массив (MZ: data/plugins.js) — фильтруем через json
    if text.lstrip().startswith("["):
        try:
            data = json.loads(text)
            new_data = [p for p in data if p.get("name") != plugin_name]
            if len(new_data) == len(data):
                return False
            new_text = json.dumps(new_data, ensure_ascii=False, indent=1)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_text)
            return True
        except ValueError:
            pass
    from app.core.rpgmaker.mv_bridge import _remove_entry_by_name
    new_text = _remove_entry_by_name(text, plugin_name)
    if new_text == text:
        return False
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_text)
        return True
    except OSError:
        return False


def install_runtime(game_dir: str, entries, target_lang: str = "ru") -> dict:
    """Установить рантайм-оверлей. Не трогает data/*.json.

    Возвращает stats как у parser.apply (files/strings/runtime).
    Для Electron/asar — только оверлей на диске (без патча архива),
    перевод работает при запуске через OctopusBridge (live).
    """
    tr_dict: dict[str, str] = {}
    for e in entries:
        if isinstance(e, dict):
            orig = e.get("original", "")
            trans = e.get("translation", "") or ""
            status = e.get("status", "")
        else:
            orig = getattr(e, "original", "")
            trans = getattr(e, "translation", "") or ""
            status = getattr(e, "status", "")
        if orig and trans.strip() and status != "skip":
            tr_dict[orig] = trans
    if not tr_dict:
        return {"files": 0, "strings": 0, "runtime": False}

    # 1. оверлей JSON (источник правды, Twine-style)
    overlay_abs = _overlay_abs(game_dir, target_lang)
    overlay_rel = os.path.relpath(overlay_abs, game_dir).replace(os.sep, "/")
    # www-деплой: релятивный путь от корня www/ для XHR
    # runtime-плагин лежит в www/js/plugins/, XHR tries[] покроет оба
    os.makedirs(os.path.dirname(overlay_abs), exist_ok=True)
    payload = {
        "version": 1,
        "engine": rpgm_variant.detect_variant(game_dir),
        "target_lang": target_lang,
        "count": len(tr_dict),
        "dict": tr_dict,
    }
    with open(overlay_abs, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # 2. рантайм-плагин (для обычных игр, не asar)
    # asar/Electron: архив не патчим — live через CDP/мост
    try:
        from app.engines.rpgmaker import asar as asar_mod
        is_asar = bool(asar_mod.detect_variant(game_dir))
    except Exception:
        is_asar = False
    if is_asar:
        return {"files": 1, "strings": len(tr_dict),
                "runtime": True, "overlay": overlay_rel,
                "asar_live_only": True}

    plugin_abs = _runtime_plugin_abs(game_dir)
    os.makedirs(os.path.dirname(plugin_abs), exist_ok=True)
    # overlay_rel для плагина — относительно корня игры
    # (плагин делает tries[] с www/ префиксом)
    rel_for_plugin = f"{RUNTIME_DIRNAME}/{target_lang}.json"
    src = build_runtime_source(tr_dict, target_lang, rel_for_plugin)
    with open(plugin_abs, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    _ensure_plugins_entry(game_dir, RUNTIME_PLUGIN_NAME)
    return {"files": 1, "strings": len(tr_dict),
            "runtime": True, "overlay": overlay_rel,
            "plugin": _runtime_plugin_rel(game_dir)}


def uninstall_runtime(game_dir: str, target_lang: str = "ru") -> dict:
    """Удалить рантайм-плагин и оверлей. + откат legacy file-патча если был."""
    removed = 0
    # плагин
    plugin_abs = _runtime_plugin_abs(game_dir)
    if os.path.isfile(plugin_abs):
        try:
            os.remove(plugin_abs)
            removed += 1
        except OSError:
            pass
    # также чистим возможный www/-вариант если детект ошибся
    alt = os.path.join(game_dir, "www", "js", "plugins", "ob_runtime.js")
    if alt != plugin_abs and os.path.isfile(alt):
        try:
            os.remove(alt)
            removed += 1
        except OSError:
            pass
    _remove_plugins_entry(game_dir, RUNTIME_PLUGIN_NAME)
    # оверлей(и)
    for lang in (target_lang, "ru", "en"):
        p = _overlay_abs(game_dir, lang)
        if os.path.isfile(p):
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
        # www-вариант
        alt_o = os.path.join(game_dir, "www", RUNTIME_DIRNAME, f"{lang}.json")
        if os.path.isfile(alt_o):
            try:
                os.remove(alt_o)
                removed += 1
            except OSError:
                pass
    # чистим пустые папки оверлея
    for base in (os.path.join(game_dir, RUNTIME_DIRNAME),
                 os.path.join(game_dir, "www", RUNTIME_DIRNAME)):
        try:
            if os.path.isdir(base) and not os.listdir(base):
                os.rmdir(base)
        except OSError:
            pass
    # legacy: если раньше был file-патч (backup/), откатываем его разово
    legacy_restored = 0
    backup_root = os.path.join(game_dir, "backup")
    if os.path.isdir(backup_root):
        try:
            from app.core.rpgmaker import parser as parser_mod
            # parser.restore_original уже идемпотентен
            legacy_restored = parser_mod.restore_original(game_dir).get("restored", 0)
        except Exception:  # noqa: BLE001
            pass
    # legacy MV-мост с вшитым словарём — тоже чистим если остался
    try:
        from app.core.rpgmaker import mv_bridge
        if mv_bridge.unregister_bridge(game_dir):
            removed += 1
    except Exception:  # noqa: BLE001
        pass
    return {"removed": removed, "legacy_restored": legacy_restored}
