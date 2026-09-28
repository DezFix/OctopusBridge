# -*- coding: utf-8 -*-
"""Живое применение шрифта/размера к запущенной игре (без перезапуска).

Файловый патч (fontpatch.py, fontsize.py) меняет игру на диске и
вступает в силу при следующем запуске. Если игра уже запущена через
щупальце — пробуем применить тут же в памяти:

- RPG Maker (CDP/мост): JS-оценка в странице игры — переопределяем
  Window_Base.prototype.standardFontSize, правим $dataSystem.advanced,
  подгружаем @font-face и сбрасываем настройки шрифта у окон сцены.
  Всё best-effort: любая ошибка = False, файловый патч остаётся.
- Ren'Py (агент): cheat-команды font_size / font_reload — агент меняет
  gui.text_size + стили и делает restart_interaction().

Никаких исключений наружу: функции возвращают bool.
"""
from __future__ import annotations

import json


def _rpgm_refresh_snippet() -> str:
    """ES5-кусок обновления окон текущей сцены (для вставки в IIFE)."""
    return (
        "var refreshed=0,seen=[],nodes=[];"
        "function obHas(list,item){"
        "for(var i=0;i<list.length;i++){if(list[i]===item)return true;}"
        "return false;}"
        "function obIsWindow(w){"
        "if(!w)return false;"
        "try{if(typeof Window_Base!==\"undefined\"&&w instanceof Window_Base)"
        "return true;}catch(e1){}"
        "try{return !!w.contents&&(typeof w.resetFontSettings===\"function\""
        "||typeof w.updateMessage===\"function\");}catch(e2){return false;}"
        "}"
        "function obRefreshWindow(w){"
        "if(!obIsWindow(w)||obHas(seen,w))return;"
        "seen.push(w);var changed=false;"
        "try{if(typeof w.resetFontSettings===\"function\")"
        "{w.resetFontSettings();changed=true;}}catch(e3){}"
        "try{if(typeof w.refresh===\"function\"){w.refresh();}}catch(e4){}"
        "try{if(typeof w.updateMessage===\"function\")"
        "{w.updateMessage();}}catch(e5){}"
        "if(changed){refreshed++;}"
        "}"
        "function obWalk(node,depth){"
        "if(!node||depth>6||obHas(nodes,node))return;nodes.push(node);"
        "obRefreshWindow(node);"
        "try{if(node.children&&node.children.length){"
        "for(var i=0;i<node.children.length;i++)"
        "{obWalk(node.children[i],depth+1);}}}catch(e6){}"
        "try{if(node._windowLayer){obWalk(node._windowLayer,depth+1);}}catch(e7){}"
        "}"
        "function obScene(scene){"
        "if(!scene)return;"
        "try{for(var key in scene){if(!scene.hasOwnProperty(key))continue;"
        "try{obRefreshWindow(scene[key]);}catch(e8){}}}catch(e9){}"
        "try{obWalk(scene._windowLayer,0);}catch(e10){}"
        "try{if(scene._spriteset){obWalk(scene._spriteset._windowLayer,0);}}"
        "catch(e11){}"
        "}"
        "try{obScene(SceneManager._scene);}catch(e12){}"
    )


def build_rpgm_font_size_js(size: int) -> str:
    """JS (ES5) живого размера шрифта RPG Maker. Возвращает 'ok:N'."""
    n = max(12, min(64, int(size)))
    return (
        "(function(){var n=" + str(n) + ",patched=false,candidate;"
        "window.__octopus_fontSize=n;"
        "try{if(window.$dataSystem&&$dataSystem.advanced)"
        "{$dataSystem.advanced.fontSize=n;}}catch(e){}"
        "try{if(window.$gameSystem){"
        "$gameSystem._mainFontSize=n;"
        "if(typeof $gameSystem.mainFontSize===\"function\"){"
        "candidate=function(){return n;};$gameSystem.mainFontSize=candidate;}}}"
        "catch(e2){}"
        "try{if(typeof Window_Base!==\"undefined\"&&Window_Base.prototype){"
        "candidate=function(){return n;};"
        "Window_Base.prototype.standardFontSize=candidate;"
        "patched=Window_Base.prototype.standardFontSize===candidate;}}"
        "catch(e3){}"
        + _rpgm_refresh_snippet() +
        "return patched?\"ok:\"+refreshed:\"no-window-base\";})()"
    )


def build_rpgm_font_face_js(font_filename: str) -> str:
    """JS (ES5) живой подмены шрифта RPG Maker. Возвращает 'ok[:N]'."""
    fname = (font_filename or "").replace("\\", "/").split("/")[-1]
    if not fname:
        return ""
    jname = json.dumps(fname, ensure_ascii=False)
    return (
        "(function(){var fname=" + jname + ";"
        "try{"
        "var css=\"@font-face{font-family:\\\"GameFont\\\";"
        "src:url(\\\"fonts/\"+fname+\"\\\");}\""
        "+\"@font-face{font-family:\\\"rmmz-mainfont\\\";"
        "src:url(\\\"fonts/\"+fname+\"\\\");}\""
        "+\"@font-face{font-family:\\\"mplus-1m-regular\\\";"
        "src:url(\\\"fonts/\"+fname+\"\\\");}\";"
        "var st=document.createElement(\"style\");"
        "try{st.setAttribute(\"data-octopus-font\",fname);}catch(ex){}"
        "st.textContent=css;"
        "document.head.appendChild(st);"
        "}catch(e){}"
        "try{if(typeof FontManager!==\"undefined\"&&FontManager.loadGameFont){"
        "try{FontManager.loadGameFont(\"GameFont\",\"fonts/\"+fname);}"
        "catch(e2){}"
        "try{FontManager.loadGameFont(\"rmmz-mainfont\",\"fonts/\"+fname);}"
        "catch(e3){}"
        "}}catch(e4){}"
        + _rpgm_refresh_snippet() +
        "return \"ok:\"+refreshed;})()"
    )


def _tentacle_evaluate(tentacle, js: str):
    """Вызывает tentacle.evaluate(js) и возвращает (ok, value)."""
    try:
        meth = getattr(tentacle, "evaluate", None)
        if meth is None:
            return False, "no evaluate"
        return meth(js)
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def apply_rpgm_font_size_live(tentacle, size: int) -> bool:
    """Применяет размер шрифта к живой RPGM-игре. True — JS отработал."""
    if tentacle is None:
        return False
    try:
        attached = tentacle.is_attached()
    except Exception:  # noqa: BLE001
        attached = False
    if not attached:
        return False
    js = build_rpgm_font_size_js(size)
    ok, val = _tentacle_evaluate(tentacle, js)
    return bool(ok and str(val or "").startswith("ok:"))


def apply_rpgm_font_live(tentacle, font_filename: str) -> bool:
    """Применяет шрифт к живой RPGM-игре. True — JS отработал."""
    if tentacle is None or not font_filename:
        return False
    try:
        attached = tentacle.is_attached()
    except Exception:  # noqa: BLE001
        attached = False
    if not attached:
        return False
    js = build_rpgm_font_face_js(font_filename)
    if not js:
        return False
    ok, val = _tentacle_evaluate(tentacle, js)
    return bool(ok and str(val or "").startswith("ok:"))


def build_ajin_font_size_js(size: int) -> str:
    """JS живого кегля Tyrano: stat.font + default_font + config.
    Возвращает 'ok' / 'no-kag'. Значения — строки (движок хранит "42")."""
    n = max(12, min(64, int(size)))
    return (
        "(function(){var n=" + str(n) + ";"
        "var K=(window.kag||(window.TYRANO&&TYRANO.kag&&TYRANO.kag.kag)||"
        "(window.tyrano&&window.tyrano.plugin&&window.tyrano.plugin.kag));"
        "if(!K||!K.stat)return \"no-kag\";"
        "try{K.stat.font.size=String(n);}catch(e){}"
        "try{K.stat.default_font.size=String(n);}catch(e2){}"
        "try{if(K.config)K.config.defaultFontSize=String(n);}catch(e3){}"
        "return \"ok\";})()"
    )


def apply_ajin_font_size_live(tentacle, size: int) -> bool:
    """Применяет кегль к живой Ajin-игре (новые реплики — сразу,
    видимый текст — со следующего сообщения)."""
    if tentacle is None:
        return False
    try:
        attached = tentacle.is_attached()
    except Exception:  # noqa: BLE001
        attached = False
    if not attached:
        return False
    js = build_ajin_font_size_js(size)
    ok, val = _tentacle_evaluate(tentacle, js)
    return bool(ok and val == "ok")


def apply_renpy_font_size_live(tentacle, size: int) -> bool:
    """Применяет размер шрифта к живой Ren'Py-игре через агента."""
    if tentacle is None:
        return False
    try:
        attached = tentacle.is_attached()
    except Exception:  # noqa: BLE001
        attached = False
    if not attached:
        return False
    try:
        return bool(tentacle.send_cheat("font_size", value=int(size)))
    except Exception:  # noqa: BLE001
        return False


def apply_renpy_font_live(tentacle) -> bool:
    """Переприменяет карту шрифтов в живой Ren'Py-игре."""
    if tentacle is None:
        return False
    try:
        attached = tentacle.is_attached()
    except Exception:  # noqa: BLE001
        attached = False
    if not attached:
        return False
    try:
        return bool(tentacle.send_cheat("font_reload"))
    except Exception:  # noqa: BLE001
        return False
