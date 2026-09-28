# -*- coding: utf-8 -*-
"""Фабрика вкладок движков — UI-слой модульного монолита.

Правило границы:
- Движки (app/engines/*) НЕ знают про Qt. Их ui_tabs() deprecated.
- Весь Qt живет ТОЛЬКО здесь: по ключу движка строим виджеты.
- Движок отдает detect/extract/apply/verify, UI решает что показать.

Чтобы добавить движок: parser в app/core/<name>/ + запись в registry
+ ветка в build_tabs() ниже. Никаких импортов UI внутри движков.
"""
from __future__ import annotations


def build_tabs(engine_key: str, main_window) -> list[tuple]:
    """Построить вкладки для движка. Возврат: [(widget, title, role)]."""
    from app.ui.i18n import TR

    translate = main_window.translate_tab

    if engine_key == "rpgmaker":
        from app.ui.cheat_tab import CheatTab
        from app.ui.map_tab import MapTab
        from app.ui.resource_tab import ResourceTab
        cheats = CheatTab(main_window)
        maps = MapTab(main_window)
        resources = ResourceTab(main_window)
        main_window.cheat_tab = cheats
        return [
            (translate, TR("tab_translate"), "translate"),
            (cheats, TR("tab_cheats"), "cheats"),
            (maps, TR("tab_maps"), "module"),
            (resources, TR("tab_resources"), "module"),
        ]

    if engine_key == "renpy":
        from app.ui.renpy_cheat_tab import VariablesTab, TriggersTab
        from app.ui.resource_tab import ResourceTab
        var_tab = VariablesTab(main_window)
        trg_tab = TriggersTab(main_window)
        resources = ResourceTab(main_window)
        main_window.cheat_tab = var_tab
        return [
            (translate, TR("tab_translate"), "translate"),
            (var_tab, TR("tab_cheats"), "cheats"),
            (trg_tab, TR("tab_triggers"), "triggers"),
            (resources, TR("tab_resources"), "module"),
        ]

    if engine_key == "twine":
        from app.ui.save_editor_tab import SaveEditorTab
        from app.ui.twine_text_tab import TwineTextTab
        save_tab = SaveEditorTab(main_window)
        text_tab = TwineTextTab(main_window)
        return [
            (translate, TR("tab_translate"), "translate"),
            (text_tab, TR("tab_twine_text"), "module"),
            (save_tab, TR("tab_save_editor"), "module"),
        ]

    if engine_key == "ajin":
        from app.ui.ajin_cheat_tab import AjinTriggersTab, AjinVariablesTab
        var_tab = AjinVariablesTab(main_window)
        trg_tab = AjinTriggersTab(main_window)
        main_window.cheat_tab = var_tab
        return [
            (translate, TR("tab_translate"), "translate"),
            (var_tab, TR("tab_cheats"), "cheats"),
            (trg_tab, TR("tab_triggers"), "triggers"),
        ]

    # tyrano / wolf / unity и остальные: только файловый перевод.
    # Читы и live сюда не добавляем, пока ядро не станет железным.
    return [
        (translate, TR("tab_translate"), "translate"),
    ]
