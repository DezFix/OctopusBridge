# -*- coding: utf-8 -*-
"""i18n: TR(key, **fmt) with full RU/EN coverage."""
from __future__ import annotations

_lang: str = "en"

_STRINGS = {
    # ── App ──
    "app_title": {
        "ru": "OctopusBridge — перевод и модификация игр",
        "en": "OctopusBridge — game translation & modding",
    },
    "tray_open": {"ru": "Открыть", "en": "Open"},
    "tray_quit": {"ru": "Выход", "en": "Quit"},
    "tray_minimized": {
        "ru": "Свёрнуто в трей. Выход — через иконку в трее.",
        "en": "Minimized to tray. Quit via the tray icon.",
    },

    # ── Диалоги ──
    "side_home": {"ru": "Открыть папку игры", "en": "Open game folder"},

    # ── Welcome ──
    "welcome_title": {"ru": "OctopusBridge", "en": "OctopusBridge"},
    "welcome_subtitle": {
        "ru": "Перевод и модификация игр",
        "en": "Game translation & modding",
    },
    "welcome_drop": {
        "ru": "Перетащите сюда Game.exe\nили папку игры",
        "en": "Drop Game.exe\nor the game folder here",
    },
    "welcome_browse": {
        "ru": "…или выберите папку",
        "en": "…or browse for a folder",
    },
    "welcome_loading": {"ru": "Загружаю игру", "en": "Loading game"},
    "welcome_unsupported": {
        "ru": "Движок не поддерживается.\nПоддерживаются: RPG Maker MV/MZ, Ren'Py, Twine и TyranoScript.",
        "en": "Engine not supported.\nSupported: RPG Maker MV/MZ, Ren'Py, Twine and TyranoScript.",
    },
    "welcome_hint": {
        "ru": "Поддерживаются: RPG Maker MV/MZ, Ren'Py, Twine и TyranoScript",
        "en": "Supported: RPG Maker MV/MZ, Ren'Py, Twine and TyranoScript",
    },
    "welcome_recent": {
        "ru": "Последние проекты",
        "en": "Recent projects",
    },
    "welcome_open": {
        "ru": "Открыть",
        "en": "Open",
    },
    "welcome_no_recent": {
        "ru": "Нет недавних проектов",
        "en": "No recent projects",
    },
    "projects_subtitle": {
        "ru": "Ваши игры — нажмите, чтобы продолжить перевод, или перетащите папку игры сюда",
        "en": "Your games — click one to continue translating, or drag a game folder here",
    },
    "projects_empty_title": {
        "ru": "Пока нет проектов",
        "en": "No projects yet",
    },
    "projects_empty_hint": {
        "ru": "Добавьте игру: перетащите папку на главный экран\nили нажмите «Добавить игру»",
        "en": "Add a game: drag its folder to the home screen\nor press \"Add game\"",
    },
    "projects_add": {
        "ru": "Добавить игру",
        "en": "Add game",
    },
    "projects_clear": {
        "ru": "Очистить список",
        "en": "Clear list",
    },
    "projects_clear_confirm": {
        "ru": "Удалить все проекты из списка?",
        "en": "Remove all projects from the list?",
    },
    "projects_open_folder": {
        "ru": "Открыть папку",
        "en": "Open folder",
    },
    "welcome_add_project": {
        "ru": "Добавить проект",
        "en": "Add project",
    },
    "welcome_edit_name": {
        "ru": "Изменить название",
        "en": "Rename",
    },
    "welcome_new_name": {
        "ru": "Новое название:",
        "en": "New name:",
    },
    "welcome_remove": {
        "ru": "Удалить из списка",
        "en": "Remove from list",
    },
    "welcome_remove_confirm": {
        "ru": "Удалить проект из списка последних?",
        "en": "Remove project from recent list?",
    },

    # ── Dashboard ──
    "dash_game_info": {"ru": "Информация об игре", "en": "Game Info"},
    "dash_engine": {"ru": "Движок:", "en": "Engine:"},
    "dash_folder": {"ru": "Папка:", "en": "Folder:"},
    "dash_encryption": {"ru": "Шифрование:", "en": "Encryption:"},
    "dash_saves": {"ru": "Сейвов:", "en": "Saves:"},
    "dash_stats": {"ru": "Статистика:", "en": "Statistics:"},
    "dash_actions": {"ru": "Быстрые действия", "en": "Quick Actions"},
    "dash_extract": {"ru": "1. Извлечь текст", "en": "1. Extract text"},
    "dash_translate": {"ru": "2. Перевести файлы", "en": "2. Translate files"},
    "dash_live": {"ru": "Реалтайм перевод", "en": "Live translation"},
    "dash_cheats": {"ru": "Читы", "en": "Cheats"},
    "dash_provider": {"ru": "Провайдер перевода", "en": "Translation Provider"},
    "dash_provider_engine": {"ru": "Движок:", "en": "Engine:"},
    "dash_provider_check": {"ru": "Проверить", "en": "Check"},
    "dash_change_game": {"ru": "Сменить игру", "en": "Change game"},
    "welcome_open_folder": {"ru": "Открыть папку игры", "en": "Open game folder"},
    "dash_settings": {"ru": "Настройки", "en": "Settings"},
    "dash_font": {"ru": "Шрифт с кириллицей", "en": "Cyrillic font"},
    "dash_no_extract": {
        "ru": "Текст ещё не извлечён. Нажмите «Извлечь текст».",
        "en": "Text not yet extracted. Click \"Extract text\".",
    },
    "dash_stats_fmt": {
        "ru": "Записей: {total}  |  Переведено: {done}  |  Осталось: {left}",
        "en": "Entries: {total}  |  Translated: {done}  |  Remaining: {left}",
    },
    "dash_enc_yes": {"ru": "да", "en": "yes"},
    "dash_enc_no": {"ru": "нет", "en": "no"},

    # ── Tabs ──
    "tab_home": {"ru": "Домой", "en": "Home"},
    "tab_projects": {"ru": "Проекты", "en": "Projects"},
    "tab_translate": {"ru": "Перевод", "en": "Translate"},
    "tab_live": {"ru": "Реалтайм", "en": "Live"},
    "tab_cheats": {"ru": "Читы", "en": "Cheats"},

    # ── Translate tab ──
    "tr_extract": {"ru": "1. Извлечь текст", "en": "1. Extract text"},
    "tr_extracting": {
        "ru": "Извлекаю текст из игры…",
        "en": "Extracting text from the game…",
    },
    "tr_mode_new": {"ru": "Только новые и сбойные", "en": "New & failed only"},
    "tr_mode_all": {"ru": "Перевести всё заново", "en": "Re-translate all"},
    "tr_translate": {"ru": "2. Перевести", "en": "2. Translate"},
    "tr_cancel": {"ru": "Отмена", "en": "Cancel"},
    "tr_apply": {"ru": "3. Внедрить в игру", "en": "3. Apply to game"},
    "tr_correct": {"ru": "ИИ-коррекция", "en": "AI Correction"},
    "tr_glossary": {"ru": "Глоссарий…", "en": "Glossary…"},
    "tr_export": {"ru": "Экспорт CSV", "en": "Export CSV"},
    "tr_import": {"ru": "Импорт CSV", "en": "Import CSV"},
    "tr_search": {"ru": "Поиск:", "en": "Search:"},
    "tr_search_ph": {
        "ru": "текст оригинала/перевода…",
        "en": "original/translation text…",
    },
    "tr_filter": {"ru": "Показать:", "en": "Show:"},
    "tr_filter_all": {"ru": "Все", "en": "All"},
    "tr_filter_untranslated": {"ru": "Без перевода", "en": "Untranslated"},
    "tr_filter_translated": {"ru": "Переведённые", "en": "Translated"},
    "tr_filter_skipped": {"ru": "Пропущенные", "en": "Skipped"},
    "tr_file": {"ru": "Файл:", "en": "File:"},
    "tr_files": {"ru": "Файлы", "en": "Files"},
    "tr_all_files": {"ru": "Все файлы", "en": "All files"},
    "tr_select_file": {"ru": "Выберите файл слева", "en": "Select a file on the left"},
    "tr_no_project": {
        "ru": "Сначала откройте игру",
        "en": "Open a game first",
    },
    "tr_no_data": {"ru": "Сначала извлеките текст", "en": "Extract text first"},
    "tr_engine_create_fail": {
        "ru": "Не удалось создать движок перевода. Проверьте настройки провайдера.",
        "en": "Failed to create translation engine. Check provider settings.",
    },
    "tr_no_engine": {"ru": "Движок игры не поддерживается", "en": "Engine not supported"},
    "tr_extract_done": {
        "ru": "Извлечено записей: {count}\nСохранено переводов: {restored}",
        "en": "Extracted: {count}\nRestored translations: {restored}",
    },
    "tr_translate_done": {
        "ru": "Переведено строк: {n}",
        "en": "Translated lines: {n}",
    },
    "tr_correct_done": {
        "ru": "ИИ-коррекция завершена: {n} строк вычитано",
        "en": "AI correction done: {n} lines reviewed",
    },
    "tr_correct_reviewed": {
        "ru": "Принято: {accepted} из {total} предложений",
        "en": "Accepted: {accepted} of {total} suggestions",
    },

    # ── Diff review ──
    "diff_title": {"ru": "Ревизия ИИ-коррекции", "en": "AI Correction Review"},
    "diff_hint": {
        "ru": "LLM предложил {n} исправлений. Принимайте или отклоняйте каждое.",
        "en": "LLM suggested {n} corrections. Accept or reject each one.",
    },
    "diff_col_orig": {"ru": "Оригинал", "en": "Original"},
    "diff_col_was": {"ru": "Было", "en": "Before"},
    "diff_col_became": {"ru": "Стало", "en": "After"},
    "diff_col_action": {"ru": "Действие", "en": "Action"},
    "diff_accept": {"ru": "", "en": ""},
    "diff_reject": {"ru": "", "en": ""},
    "diff_accept_all": {"ru": "Принять все", "en": "Accept all"},
    "diff_reject_all": {"ru": "Отклонить все", "en": "Reject all"},
    "diff_apply": {"ru": "Применить", "en": "Apply"},
    "diff_count": {
        "ru": "Принято: {acc} из {total}",
        "en": "Accepted: {acc} of {total}",
    },

    # ── Coverage ──
    "cov_file": {"ru": "Файл", "en": "File"},
    "cov_total": {"ru": "Всего", "en": "Total"},
    "cov_done": {"ru": "Переведено", "en": "Translated"},
    "cov_pct": {"ru": "%", "en": "%"},
    "tr_apply_title": {"ru": "Внедрение", "en": "Apply"},
    "tr_apply_msg": {
        "ru": "Внедрить {n} переведённых строк?",
        "en": "Apply {n} translated lines?",
    },
    "tr_apply_done": {
        "ru": "Файлов: {files}\nСтрок: {strings}",
        "en": "Files: {files}\nStrings: {strings}",
    },
    "tr_apply_backup": {
        "ru": "Бэкап: {n} файлов",
        "en": "Backup: {n} files",
    },
    "tr_apply_folder": {
        "ru": "Папка: {path}",
        "en": "Folder: {path}",
    },
    "tr_progress": {
        "ru": "Переведено {done}/{total}",
        "en": "Translated {done}/{total}",
    },
    "tr_status": {
        "ru": "Показано: {shown} из {total}{note}",
        "en": "Showing: {shown} of {total}{note}",
    },
    "tr_status_cap": {
        "ru": " (первые 10000, уточните фильтр)",
        "en": " (first 10000, refine your filter)",
    },

    # ── Live tab ──
    "live_title": {
        "ru": "OctopusBridge — перевод и читы в живой игре",
        "en": "OctopusBridge — live game translation & cheats",
    },
    "live_start": {
        "ru": "Запустить игру и подключиться",
        "en": "Launch game & attach",
    },
    "live_stop": {"ru": "Отключиться", "en": "Detach"},
    "live_status": {"ru": "Статус:", "en": "Status:"},
    "live_stopped": {"ru": "Остановлено", "en": "Stopped"},
    "live_no_game_dir": {
        "ru": "Папка игры не задана. Откройте проект.",
        "en": "Game folder not set. Open a project first.",
    },
    "live_starting": {
        "ru": "Запускаю игру…",
        "en": "Launching game…",
    },
    "live_log": {
        "ru": "Журнал перевода в реальном времени:",
        "en": "Real-time translation log:",
    },
    "live_connected": {
        "ru": "Щупальце в игре — перевод активен",
        "en": "Tentacle attached — translation active",
    },
    "live_waiting": {
        "ru": "Подключаюсь к игре…",
        "en": "Attaching to the game…",
    },
    "live_game_started": {"ru": "Игра запущена", "en": "Game launched"},
    "live_no_exe": {
        "ru": "Исполняемый файл не найден — запустите игру вручную",
        "en": "Executable not found — launch the game manually",
    },
    "live_stopped_hint": {
        "ru": "Отключено (игра продолжает работу)",
        "en": "Detached (game keeps running)",
    },
    "live_engine_missing": {
        "ru": "Неизвестный движок в настройках",
        "en": "Unknown engine in settings",
    },
    "live_engine_offline_msg": {
        "ru": "Движок недоступен. Запустить БЕЗ перевода?",
        "en": "Engine unavailable. Launch WITHOUT translation?",
    },
    "live_attach_group": {
        "ru": "…или подключиться к уже запущенной игре",
        "en": "…or attach to an already running game",
    },
    "live_refresh_procs": {
        "ru": "Обновить список",
        "en": "Refresh list",
    },
    "live_attach": {
        "ru": "Подключиться к выбранному",
        "en": "Attach to selected",
    },
    "live_no_procs": {
        "ru": "Запущенные процессы игры не найдены",
        "en": "No running game processes found",
    },
    "live_unsupported": {
        "ru": "Этот движок пока не поддерживает живое подключение",
        "en": "This engine does not support live attach yet",
    },
    "live_autofound": {
        "ru": "Найден процесс игры (pid {pid}) — подключаюсь…",
        "en": "Game process found (pid {pid}) — attaching…",
    },
    "live_engine_offline_silent": {
        "ru": "Движок перевода недоступен — показываю оригинал",
        "en": "Translation engine unavailable — showing original",
    },
    "live_translate_toggle": {
        "ru": "Перевод в реальном времени",
        "en": "Real-time translation",
    },
    "live_translate_off": {
        "ru": "Перевод выключен (текст без перевода)",
        "en": "Translation off (original text)",
    },

    # ── Cheat tab ──
    "cheat_hint": {
        "ru": "Читы работают через запущенный LiveBridge («Реалтайм» → «Запустить»).",
        "en": "Cheats require LiveBridge (\"Live\" → \"Launch\").",
    },
    "cheat_main": {"ru": "Главная", "en": "Main"},
    "cheat_party": {"ru": "Пати", "en": "Party"},
    "cheat_map": {"ru": "Карта", "en": "Map"},
    "cheat_items": {"ru": "Предметы", "en": "Items"},
    "cheat_vars": {"ru": "Переменные", "en": "Variables"},
    "cheat_switches": {"ru": "Переключатели", "en": "Switches"},
    "cheat_gold": {"ru": "Золото:", "en": "Gold:"},
    "cheat_menu": {"ru": "Меню игры", "en": "Game Menu"},
    "cheat_menu_main": {"ru": "Меню (Esc)", "en": "Menu (Esc)"},
    "cheat_menu_items": {"ru": "Предметы", "en": "Items"},
    "cheat_menu_skills": {"ru": "Навыки", "en": "Skills"},
    "cheat_menu_equip": {"ru": "Экипировка", "en": "Equipment"},
    "cheat_menu_status": {"ru": "Статус", "en": "Status"},
    "cheat_menu_save": {"ru": "Сохранить", "en": "Save"},
    "cheat_menu_load": {"ru": "Загрузить", "en": "Load"},
    "cheat_menu_options": {"ru": "Настройки", "en": "Options"},
    "cheat_menu_end": {"ru": "Конец игры", "en": "Game End"},
    "cheat_map_id": {"ru": "Карта №:", "en": "Map #:"},
    "cheat_in_battle": {"ru": "В бою:", "en": "In battle:"},
    "cheat_refresh": {"ru": "Обновить данные из игры", "en": "Refresh from game"},
    "cheat_heal": {"ru": "Вылечить партию (HP/MP)", "en": "Heal party (HP/MP)"},
    "cheat_win": {"ru": "Мгновенная победа", "en": "Instant win"},
    "cheat_speed": {"ru": "Скорость игрока", "en": "Player speed"},
    "cheat_noclip": {"ru": "Ноуклип (сквозь стены)", "en": "No-clip (through walls)"},
    "cheat_clicktp": {"ru": "Телепорт по Ctrl+клику", "en": "Teleport on Ctrl+click"},
    "cheat_gold_set": {"ru": "Задать", "en": "Set"},
    "cheat_gold_add": {"ru": "Добавить", "en": "Add"},
    "cheat_apply": {"ru": "Применить", "en": "Apply"},
    "cheat_tp": {"ru": "Телепорт на карту", "en": "Teleport to map"},
    "cheat_tp_hint": {
        "ru": "Если точка (X,Y) в стене — персонаж застрянет; включите ноуклип.",
        "en": "If point (X,Y) is in a wall, enable no-clip.",
    },
    "cheat_apply_party": {
        "ru": "Применить изменения (уровень/HP/MP/EXP)",
        "en": "Apply changes (level/HP/MP/EXP)",
    },
    "cheat_apply_items": {
        "ru": "Выдать (применить новые количества)",
        "en": "Give (apply new quantities)",
    },
    "cheat_apply_vars": {"ru": "Применить значения", "en": "Apply values"},
    "cheat_var_hint": {
        "ru": "Живое значение: меняете число — сразу меняется в игре. "
              "Имя редактируется и сохраняется в проекте.",
        "en": "Live value: edit a number — it changes in game at once. "
              "Names are editable and saved to project.",
    },
    "cheat_sw_hint": {
        "ru": "Галочка применяется сразу. Имя редактируется и сохраняется.",
        "en": "Toggle applies immediately. Names are editable.",
    },
    "cheat_map_search": {"ru": "Поиск карты:", "en": "Search map:"},
    "cheat_item_search": {"ru": "Поиск:", "en": "Search:"},
    "cheat_no_bridge": {
        "ru": "Запустите LiveBridge на вкладке «Реалтайм»",
        "en": "Launch LiveBridge on the Live tab",
    },
    "cheat_connected": {
        "ru": "Игра подключена — читы активны",
        "en": "Game connected — cheats active",
    },
    "cheat_disconnected": {"ru": "Жду подключения игры…", "en": "Waiting for game…"},
    "cheat_done": {"ru": "Чит {cmd}: выполнен", "en": "Cheat {cmd}: done"},
    "cheat_error": {"ru": "Чит {cmd}: ОШИБКА {err}", "en": "Cheat {cmd}: ERROR {err}"},
    "cheat_auto_refresh": {"ru": "Авто-обновление", "en": "Auto-refresh"},
    "cheat_changed": {"ru": "Изменено", "en": "Changed"},

    # ── Settings ──
    "settings_title": {"ru": "Настройки", "en": "Settings"},
    "settings_save": {"ru": "Сохранить", "en": "Save"},
    "settings_general": {"ru": "Основные", "en": "General"},
    "settings_languages": {"ru": "Языки перевода", "en": "Translation Languages"},
    "settings_live": {"ru": "Реалтайм", "en": "Real-time"},
    "settings_files": {"ru": "Файлы", "en": "Files"},
    "settings_corr_tab": {"ru": "ИИ корректор", "en": "AI Corrector"},
    "settings_provider": {"ru": "Провайдер перевода", "en": "Translation Provider"},
    "settings_live_provider": {
        "ru": "Провайдер для реалтайма (в игре)",
        "en": "Real-time provider (in game)",
    },
    "settings_files_provider": {
        "ru": "Провайдер для перевода файлов",
        "en": "File translation provider",
    },
    "settings_corr_provider": {
        "ru": "Провайдер для ИИ-коррекции",
        "en": "AI correction provider",
    },
    "settings_glossary_box": {"ru": "ИИ глоссарий", "en": "AI Glossary"},
    "settings_glossary_ai": {
        "ru": "Использовать движок ИИ-корректора для анализа терминов",
        "en": "Use the AI corrector engine for term analysis",
    },
    "settings_glossary_info": {
        "ru": "Кнопка «Анализ терминов (AI)…» в глоссарии использует тот же "
              "LLM-движок, что и ИИ-корректор.",
        "en": "The \"Analyze terms (AI)…\" button in the glossary uses the "
              "same LLM engine as the AI corrector.",
    },
    "settings_provider_lbl": {"ru": "Провайдер:", "en": "Provider:"},
    "settings_preset": {"ru": "Пресет:", "en": "Preset:"},
    "settings_base_url": {"ru": "Base URL:", "en": "Base URL:"},
    "settings_api_key": {"ru": "API-ключ:", "en": "API Key:"},
    "settings_model": {"ru": "Модель:", "en": "Model:"},
    "settings_ollama_url": {"ru": "Ollama URL:", "en": "Ollama URL:"},
    "settings_src_lang": {"ru": "Язык оригинала:", "en": "Source language:"},
    "settings_tgt_lang": {"ru": "Язык перевода:", "en": "Target language:"},
    "settings_check": {"ru": "Проверить провайдера", "en": "Check provider"},
    "settings_status": {"ru": "Статус:", "en": "Status:"},
    "settings_status_ready": {
        "ru": "Провайдер готов к работе",
        "en": "Provider ready",
    },
    "settings_status_fail": {
        "ru": "НЕ доступен (ключ? сервер? пакеты?)",
        "en": "Unavailable (key? server? packages?)",
    },
    "settings_auto_launch": {
        "ru": "Автозапуск реалтайма при открытии проекта",
        "en": "Auto-start realtime on project open",
    },
    "settings_overwrite": {"ru": "Режим перевода:", "en": "Translation mode:"},
    "settings_overwrite_new": {
        "ru": "Только новые и без перевода",
        "en": "New & untranslated only",
    },
    "settings_overwrite_all": {
        "ru": "Перевести всё заново (перезаписать)",
        "en": "Re-translate all (overwrite)",
    },
    "settings_backup": {"ru": "Автобэкап при внедрении", "en": "Auto-backup on apply"},
    "settings_close_behavior": {
        "ru": "При закрытии окна:",
        "en": "On window close:",
    },
    "settings_close_tray": {
        "ru": "Сворачивать в трей",
        "en": "Minimize to tray",
    },
    "settings_close_quit": {
        "ru": "Выход из приложения",
        "en": "Exit the app",
    },
    "settings_files_info": {
        "ru": "«Только новые» — переводит строки без перевода.\n«Всё заново» — заново переводит все строки.",
        "en": "\"New only\" — translates untranslated lines.\n\"Re-translate all\" — retranslates everything.",
    },
    "settings_api_key_ph": {
        "ru": "API-ключ для выбранного пресета",
        "en": "API key for selected preset",
    },
    "settings_ui_lang": {
        "ru": "Язык интерфейса:",
        "en": "UI Language:",
    },
    "settings_restart_hint": {
        "ru": "Язык изменится после перезапуска приложения.",
        "en": "Language will change after restarting the app.",
    },

    # ── Офлайн-модели honyaku ──
    "models_title": {
        "ru": "Офлайн-модели",
        "en": "Offline models",
    },
    "models_prompt": {
        "ru": "Офлайн-модели перевода не скачаны: {pairs}.\n"
              "Без них офлайн-перевод (Honyaku) работать не будет.",
        "en": "Offline translation models are missing: {pairs}.\n"
              "Without them offline translation (Honyaku) won't work.",
    },
    "models_prompt_size": {
        "ru": "Модели — часть приложения (~1,2 ГБ). Скачать сейчас?",
        "en": "Models are part of the app (~1.2 GB). Download now?",
    },
    "models_download": {
        "ru": "Скачать",
        "en": "Download",
    },
    "models_later": {
        "ru": "Позже",
        "en": "Later",
    },
    "models_downloading": {
        "ru": "Скачивание офлайн-моделей…",
        "en": "Downloading offline models…",
    },
    "models_cancel": {
        "ru": "Отмена",
        "en": "Cancel",
    },
    "models_done": {
        "ru": "Офлайн-модели готовы. Перевод работает автономно, "
              "без интернета.",
        "en": "Offline models are ready. Translation works autonomously, "
              "no internet needed.",
    },
    "models_group": {
        "ru": "Офлайн-модели Honyaku",
        "en": "Honyaku offline models",
    },
    "models_ready": {
        "ru": "Все модели на месте ({size}).",
        "en": "All models present ({size}).",
    },
    "models_partial": {
        "ru": "Скачано {done} из {total} пар ({size}). Остальное "
              "докачается кнопкой «Скачать».",
        "en": "{done} of {total} pairs downloaded ({size}). Download "
              "the rest with the button below.",
    },
    "models_missing0": {
        "ru": "Модели не скачаны (нужно ~{size}). Перевод включится "
              "после скачивания.",
        "en": "Models not downloaded yet (need ~{size}). Translation "
              "will work after download.",
    },
    "models_status_hint": {
        "ru": "Модели хранятся в папке models/ рядом с приложением — "
              "приложение работает автономно, без интернета.",
        "en": "Models are stored in models/ next to the app — the app "
              "works autonomously, no internet needed.",
    },
    "models_unit_gb": {"ru": "ГБ", "en": "GB"},
    "models_unit_mb": {"ru": "МБ", "en": "MB"},

    # ── Status bar ──
    "status_provider": {
        "ru": "Провайдер: {name}",
        "en": "Provider: {name}",
    },

    # ── Providers (engines) ──
    "prov_honyaku": {
        "ru": "Honyaku — встроенный офлайн (без ключа)",
        "en": "Honyaku — built-in offline (no key)",
    },
    "prov_google_free": {
        "ru": "Google Translate — бесплатный (без ключа)",
        "en": "Google Translate — free (no key)",
    },
    "prov_bing": {
        "ru": "Bing Translator — бесплатный (без ключа)",
        "en": "Bing Translator — free (no key)",
    },
    "prov_rotate": {
        "ru": "Google + Bing — чередование (быстрее)",
        "en": "Google + Bing — round-robin (faster)",
    },
    "prov_ai": {
        "ru": "AI — OpenAI/Ollama/LM Studio (требуется API или локальный сервер)",
        "en": "AI — OpenAI/Ollama/LM Studio (requires API or local server)",
    },
    "prov_short_honyaku": {
        "ru": "Honyaku (офлайн)",
        "en": "Honyaku (offline)",
    },
    "prov_short_google_free": {"ru": "Google Translate", "en": "Google Translate"},
    "prov_short_bing": {"ru": "Bing Translator", "en": "Bing Translator"},
    "prov_short_rotate": {
        "ru": "Google + Bing (чередование)",
        "en": "Google + Bing (round-robin)",
    },
    "prov_short_ai": {"ru": "AI (LLM / API)", "en": "AI (LLM / API)"},
    "hint_engine_ai": {
        "ru": "AI-провайдер недоступен.\n\n"
              "Локальный LLM: установите Ollama, скачайте модель — она "
              "работает на порту 11434.\n"
              "Удалённый API: укажите Base URL и API-ключ в настройках.\n"
              "Проверьте соединение кнопкой «Проверить провайдера».",
        "en": "AI provider is not connected.\n\n"
              "For local LLM: install Ollama, pull a model, it runs on "
              "port 11434.\n"
              "For remote API: set base URL and API key in Settings.\n"
              "Check connection with the 'Check provider' button.",
    },
    "hint_engine_honyaku": {
        "ru": "Офлайн-движок не готов.\n\n"
              "Если это первый запуск — скачайте модели кнопкой "
              "«Модели Honyaku» в настройках (fast ~60 МБ на пару, "
              "NLLB best ~1.2 ГБ, один раз).",
        "en": "Offline engine is not ready.\n\n"
              "If this is the first launch — download models with "
              "'Honyaku Models' button in Settings (~60 MB per fast pair, "
              "~1.2 GB for NLLB best, one-time download).",
    },

    # ── Engine tab titles ──
    "tab_live_realtime": {"ru": "Реал-тайм", "en": "Real-time"},
    "tab_vars": {"ru": "Переменные", "en": "Variables"},
    "tab_triggers": {"ru": "Триггеры", "en": "Triggers"},
    "tab_resources": {"ru": "Ресурсы", "en": "Resources"},
    "tab_maps": {"ru": "Карты", "en": "Maps"},
    "tab_save_editor": {"ru": "Save Editor", "en": "Save Editor"},

    # ── Map triggers ──
    "map_trigger_0": {"ru": "Кнопка", "en": "Button"},
    "map_trigger_1": {"ru": "Касание игрока", "en": "Player touch"},
    "map_trigger_2": {"ru": "Касание события", "en": "Event touch"},
    "map_trigger_3": {"ru": "Автозапуск", "en": "Auto-start"},
    "map_trigger_4": {"ru": "Параллельно", "en": "Parallel"},
    "map_vis_always": {"ru": "всегда виден", "en": "always visible"},

    # ── Parser context ──
    "ctx_comment": {"ru": "комментарий", "en": "comment"},
    "ctx_dialog": {"ru": "диалог", "en": "dialog"},
    "ctx_choice": {"ru": "выбор", "en": "choice"},
    "ctx_option": {"ru": "вариант", "en": "option"},
    "ctx_speaker": {"ru": "имя говорящего", "en": "speaker name"},
    "ctx_name_change": {"ru": "смена имени", "en": "name change"},
    "ctx_plugin": {"ru": "плагин", "en": "plugin"},
    "ctx_plugin_mv": {"ru": "плагин(MV)", "en": "plugin(MV)"},
    "ctx_map_name": {"ru": "имя карты", "en": "map name"},
    "ctx_common_event": {"ru": "общее событие", "en": "common event"},
    "ctx_enemy_group": {"ru": "группа врагов", "en": "enemy group"},
    "ctx_battle": {"ru": "бой", "en": "battle"},
    "ctx_game_title": {"ru": "название игры", "en": "game title"},
    "ctx_currency": {"ru": "валюта", "en": "currency"},
    "ctx_term": {"ru": "термин", "en": "term"},
    "ctx_variable": {"ru": "переменная", "en": "variable"},
    "ctx_switch": {"ru": "переключатель", "en": "switch"},
    "ctx_system_msg": {"ru": "сообщение системы", "en": "system message"},
    "ctx_map_name_list": {"ru": "имя карты (список)", "en": "map name (list)"},

    # ── Engine errors ──
    "err_engine_unavailable": {
        "ru": "недоступен: {e}",
        "en": "unavailable: {e}",
    },
    "err_ollama_bad_response": {
        "ru": "Ollama вернул некорректный ответ",
        "en": "Ollama returned invalid response",
    },
    "err_honyaku_not_installed": {
        "ru": "Пакет honyaku не установлен (pip install honyaku)",
        "en": "honyaku package not installed (pip install honyaku)",
    },
    "err_honyaku_no_models": {
        "ru": "Офлайн-перевод {s}→{t} невозможен: {e}\nСкачайте модели на вкладке «Настройки».",
        "en": "Offline translation {s}→{t} failed: {e}\nDownload models in Settings.",
    },
    "err_deepl_no_key": {
        "ru": "DeepL: укажите API-ключ в настройках",
        "en": "DeepL: provide API key in settings",
    },
    "err_unknown_engine": {
        "ru": "Неизвестный движок: {name}",
        "en": "Unknown engine: {name}",
    },
    "err_honyaku_model_missing": {
        "ru": "Модель {s}→{t} не найдена в каталоге Honyaku",
        "en": "Model {s}→{t} not found in Honyaku catalog",
    },
    "err_api_bad_response": {
        "ru": "Некорректный ответ API: {e}",
        "en": "Invalid API response: {e}",
    },
    "err_api_wrong_length": {
        "ru": "API вернул ответ другой длины",
        "en": "API returned response of wrong length",
    },
    "err_honyaku_not_installed2": {
        "ru": "honyaku не установлен",
        "en": "honyaku not installed",
    },

    # ── Bridge plugin errors ──
    "err_plugins_js_not_found": {
        "ru": "plugins.js: не найден массив плагинов",
        "en": "plugins.js: plugin array not found",
    },
    "err_no_js_plugins": {
        "ru": "Не найдены js/plugins или js/plugins.js — это точно RPG Maker MV/MZ?",
        "en": "js/plugins or js/plugins.js not found — is this RPG Maker MV/MZ?",
    },
    "err_no_game_folder": {
        "ru": "Папка game/ не найдена — это точно Ren'Py?",
        "en": "game/ folder not found — is this Ren'Py?",
    },
    "err_no_fonts": {
        "ru": "Не найдены fonts/ или data/System.json",
        "en": "fonts/ or data/System.json not found",
    },
    "err_no_fonts_folder": {
        "ru": "Не найдена папка fonts/ (ищется и в www/)",
        "en": "fonts/ folder not found (also checked www/)",
    },

    # ── Save file errors ──
    "err_not_sugarcube_lz": {
        "ru": "Не SugarCube-сейв (LZ-String не раскодировался)",
        "en": "Not a SugarCube save (LZ-String decode failed)",
    },
    "err_not_sugarcube_state": {
        "ru": "Не SugarCube-сейв (нет state)",
        "en": "Not a SugarCube save (no state)",
    },
    "err_no_active_moment": {
        "ru": "В сейве нет активного момента",
        "en": "No active moment in save",
    },

    # ── Crypto errors ──
    "err_not_encrypted": {
        "ru": "Не зашифрованный RPGM-файл (сигнатура не совпала)",
        "en": "Not an encrypted RPGM file (signature mismatch)",
    },

    # ── Resource tab ──
    "res_size_kb": {
        "ru": "{size} КБ",
        "en": "{size} KB",
    },

    # ── Welcome ──
    "welcome_settings_tooltip": {"ru": "Настройки", "en": "Settings"},

    # ── Bridge log ──
    "bridge_listening": {
        "ru": "Сервер LiveBridge слушает 127.0.0.1:{port}",
        "en": "LiveBridge server listening on 127.0.0.1:{port}",
    },
    "bridge_start_failed": {
        "ru": "Сервер не запустился: {e}",
        "en": "Server failed to start: {e}",
    },
    "bridge_client_connected": {
        "ru": "Игра подключилась",
        "en": "Game connected",
    },
    "bridge_client_disconnected": {
        "ru": "Игра отключилась",
        "en": "Game disconnected",
    },
    "bridge_translate_error": {
        "ru": "Ошибка перевода: {e}",
        "en": "Translation error: {e}",
    },
    "bridge_no_client": {
        "ru": "Игра не подключена — команда не отправлена",
        "en": "Game not connected — command not sent",
    },
    "bridge_send_failed": {
        "ru": "Отправка не удалась: {e}",
        "en": "Send failed: {e}",
    },

    # ── Check provider hint fallback ──
    "hint_check_provider": {
        "ru": "Проверьте, что движок запущен.",
        "en": "Check that the engine is running.",
    },

    # ── Glossary ──
    "glossary_title": {"ru": "Глоссарий", "en": "Glossary"},
    "glossary_pair": {"ru": "Пара языков:", "en": "Language pair:"},
    "glossary_add": {"ru": "Добавить строку", "en": "Add row"},
    "glossary_del": {"ru": "Удалить выбранную", "en": "Delete selected"},
    "glossary_save": {"ru": "Сохранить", "en": "Save"},
    "glossary_hint": {
        "ru": "Термины подставляются в перевод как есть — имена не будут искажаться.",
        "en": "Terms are inserted verbatim — names won't be distorted.",
    },
    "glossary_col_orig": {"ru": "Термин (оригинал)", "en": "Term (original)"},
    "glossary_col_tr": {"ru": "Перевод", "en": "Translation"},
    "glossary_analyze": {"ru": "Анализ терминов (AI)…", "en": "Analyze terms (AI)…"},
    "glossary_analyze_need_ai": {
        "ru": "Анализ требует AI-провайдера. Настройте его в Настройках (провайдер AI).",
        "en": "Analysis requires an AI provider. Configure it in Settings (AI provider).",
    },
    "glossary_analyze_running": {"ru": "Анализ…", "en": "Analyzing…"},
    "glossary_analyze_fail": {
        "ru": "Не удалось выполнить анализ: {}",
        "en": "Analysis failed: {}",
    },
    "glossary_analyze_none": {
        "ru": "Модель не нашла подходящих терминов.",
        "en": "The model found no suitable terms.",
    },
    "glossary_terms_title": {"ru": "Кандидаты терминов", "en": "Term candidates"},
    "glossary_terms_hint": {
        "ru": "Отметьте термины, которые хотите добавить в глоссарий.",
        "en": "Select terms to add to the glossary.",
    },
    "glossary_terms_apply": {"ru": "Добавить выбранные", "en": "Add selected"},
    "glossary_analyze_added": {
        "ru": "Добавлено: {accepted} из {total} терминов",
        "en": "Added {accepted} of {total} terms",
    },
    "glossary_terms_col_use": {"ru": "✓", "en": "✓"},
    "glossary_terms_col_orig": {"ru": "Термин", "en": "Term"},
    "glossary_terms_col_tr": {"ru": "Перевод", "en": "Translation"},

    # ── Map tab (H1) ──
    "map_list": {"ru": "Карты", "en": "Maps"},
    "map_search_ph": {"ru": "имя или id карты…", "en": "map name or id…"},
    "map_elements": {"ru": "Элементы (события)", "en": "Elements (events)"},
    "map_props": {"ru": "Свойства элемента", "en": "Element properties"},
    "map_name": {"ru": "Имя:", "en": "Name:"},
    "map_pos": {"ru": "Позиция:", "en": "Position:"},
    "map_page": {"ru": "Страница:", "en": "Page:"},
    "map_trigger": {"ru": "Триггер:", "en": "Trigger:"},
    "map_visibility": {"ru": "Видимость:", "en": "Visibility:"},
    "map_sw1": {"ru": "Переключатель 1", "en": "Switch 1"},
    "map_sw2": {"ru": "Переключатель 2", "en": "Switch 2"},
    "map_vis_now": {"ru": "Условие", "en": "Condition"},
    "map_zoom": {"ru": "Масштаб:", "en": "Zoom:"},
    "map_none": {
        "ru": "Выберите карту слева",
        "en": "Select a map on the left",
    },
    "map_info": {
        "ru": "Карта {id}: {w}×{h} {name}",
        "en": "Map {id}: {w}×{h} {name}",
    },
    "map_save": {"ru": "Сохранить карту в игру", "en": "Save map to game"},
    "map_saved": {
        "ru": "Карта сохранена ({path}). Оригинал — в .ob_backup.",
        "en": "Map saved ({path}). Original in .ob_backup.",
    },
    "map_discard": {
        "ru": "Есть несохранённые правки. Открыть другую карту и потерять их?",
        "en": "Unsaved changes. Open another map and discard them?",
    },
    "map_tp": {"ru": "Телепорт (live)", "en": "Teleport (live)"},
    "map_tp_go": {"ru": "Телепорт на эту карту", "en": "Teleport to this map"},
    "map_tp_event": {
        "ru": "Телепорт к событию",
        "en": "Teleport to event",
    },
    "map_player_map": {
        "ru": "Текущая карта игрока: #{map_id}",
        "en": "Player current map: #{map_id}",
    },
    "map_ctx_teleport": {
        "ru": "Телепорт сюда",
        "en": "Teleport here",
    },
    "map_ctx_teleport_here": {
        "ru": "Телепорт сюда",
        "en": "Teleport here",
    },
    "map_ctx_edit": {
        "ru": "Редактировать событие",
        "en": "Edit event",
    },
    "map_ctx_toggle_sw": {
        "ru": "Включить переключатель #{id}",
        "en": "Turn on switch #{id}",
    },
    "live_game_closed": {
        "ru": "Игра закрылась — мост остановлен",
        "en": "Game closed — bridge stopped",
    },
    "vars_from_save": {"ru": "Из .save файла…", "en": "From .save file…"},
    "vars_save_loaded": {
        "ru": "Сейв {path}: {n} переменных (правки пишутся в файл)",
        "en": "Save {path}: {n} variables (edits write to file)",
    },
    "vars_saved": {
        "ru": "{name} = {value} — записано в сейв",
        "en": "{name} = {value} — written to save",
    },
    "vars_console": {
        "ru": "Консоль (Python/JS в игре):",
        "en": "Console (Python/JS in game):",
    },

    # ── Save editor (H4) ──
    "save_load": {"ru": "Загрузить…", "en": "Load…"},
    "save_drop_ph": {
        "ru": "Перетащите .save сюда\nили нажмите «Загрузить…»",
        "en": "Drop .save here\nor press \"Load…\"",
    },
    "save_wait_drop": {
        "ru": "Перетащите .save — «Применить» перезапишет этот файл",
        "en": "Drop a .save — \"Apply\" will overwrite that file",
    },
    "save_apply_hint": {
        "ru": "Изменения применяются после нажатия «Применить» — файл перезаписывается (оригинал — *.ob_backup).",
        "en": "Changes apply after pressing \"Apply\" — the file is overwritten (original kept as *.ob_backup).",
    },
    "save_saved": {
        "ru": "Сохранено: {name} ({n} параметров)",
        "en": "Saved: {name} ({n} parameters)",
    },
    "save_browse_tip": {
        "ru": "Выбрать .save вручную",
        "en": "Pick a .save manually",
    },

    # ── Resource tab (H2) ──
    "res_select": {
        "ru": "Выберите файл слева",
        "en": "Select a file on the left",
    },
    "res_search_ph": {"ru": "имя файла…", "en": "file name…"},
    "res_filter_all": {"ru": "Все файлы", "en": "All files"},
    "res_filter_img": {"ru": "Картинки", "en": "Images"},
    "res_filter_audio": {"ru": "Аудио", "en": "Audio"},
    "res_filter_video": {"ru": "Видео", "en": "Videos"},
    "res_back": {"ru": "Назад к папкам", "en": "Back to folders"},
    "res_font": {
        "ru": "Установить шрифт с кириллицей…",
        "en": "Install Cyrillic font…",
    },
    "res_font_done": {
        "ru": "Шрифт {font} скопирован и прописан в игре.\n"
              "Оригиналы сохранены (*.ob_backup).",
        "en": "Font {font} copied and registered.\n"
              "Originals saved (*.ob_backup).",
    },
    "res_no_key": {"ru": "ключ шифрования не найден", "en": "no encryption key"},
    "res_empty": {"ru": "файл пуст или не найден", "en": "file empty or missing"},
    "res_decode_fail": {
        "ru": "не удалось декодировать изображение",
        "en": "failed to decode image",
    },
    "res_ctx_save": {
        "ru": "Сохранить как…",
        "en": "Save as…",
    },
    "res_ctx_save_audio": {
        "ru": "Сохранить аудио…",
        "en": "Save audio…",
    },
    "res_audio_fail": {
        "ru": "Не удалось конвертировать аудио",
        "en": "Failed to convert audio",
    },
    "res_no_ffmpeg": {
        "ru": "ffmpeg не найден. Установите ffmpeg и добавьте в PATH",
        "en": "ffmpeg not found. Install ffmpeg and add to PATH",
    },
    "res_ctx_save_video": {
        "ru": "Сохранить видео…",
        "en": "Save video…",
    },
    "res_video_fail": {
        "ru": "Не удалось воспроизвести видео",
        "en": "Failed to play video",
    },
    "res_font_restore": {
        "ru": "Откатить шрифт",
        "en": "Restore font",
    },
    "res_font_done_renpy": {
        "ru": "Заменено шрифтов: {n}. Оригиналы в game/ob_fonts_orig — "
              "кнопка «Откатить шрифт» вернёт их.",
        "en": "Replaced fonts: {n}. Originals in game/ob_fonts_orig — "
              "the «Restore font» button brings them back.",
    },
    "res_font_already": {
        "ru": "Все шрифты игры уже поддерживают кириллицу",
        "en": "All game fonts already support Cyrillic",
    },
    "res_font_restored": {
        "ru": "Оригинальные шрифты восстановлены",
        "en": "Original fonts restored",
    },

    # ── Ren'Py/Twine cheat tab (H3) ──
    "rpy_search_ph": {
        "ru": "имя или значение переменной…",
        "en": "variable name or value…",
    },
    "rpy_autorefresh": {"ru": "Автообновление", "en": "Auto-refresh"},
    "rpy_hide_text": {"ru": "Скрыть текст", "en": "Hide text"},
    "rpy_var_name": {"ru": "Переменная", "en": "Variable"},
    "rpy_var_value": {"ru": "Значение", "en": "Value"},
    "rpy_vars_hint": {
        "ru": "Изменения применяются сразу: числа и строки — по вводу, "
              "триггеры (да/нет) — по галочке. Список обновляется из "
              "запущенной игры.",
        "en": "Changes apply instantly: numbers/strings on typing, "
              "triggers (yes/no) on toggle. The list refreshes from "
              "the running game.",
    },
    "rpy_applied": {
        "ru": "{name} = {value}",
        "en": "{name} = {value}",
    },
    "rpy_bad_value": {
        "ru": "{name}: значение не подходит по типу",
        "en": "{name}: value type mismatch",
    },
    "rpy_exec_go": {"ru": "Запуск", "en": "Run"},

    # ── Generic ──
    "btn_yes": {"ru": "Да", "en": "Yes"},
    "btn_no": {"ru": "Нет", "en": "No"},
    "btn_ok": {"ru": "ОК", "en": "OK"},
    "btn_cancel": {"ru": "Отмена", "en": "Cancel"},
    "btn_close": {"ru": "Закрыть", "en": "Close"},
    "err": {"ru": "Ошибка", "en": "Error"},
    "info": {"ru": "Информация", "en": "Information"},
    "done": {"ru": "Готово", "en": "Done"},
    "about_title": {"ru": "О программе", "en": "About"},
    "about_version": {"ru": "Версия {v}", "en": "Version {v}"},
    "about_engines": {"ru": "Поддерживаемые движки:", "en": "Supported engines:"},
    "about_engines_list": {
        "ru": "RPG Maker MV/MZ, Ren'Py, Twine и TyranoScript",
        "en": "RPG Maker MV/MZ, Ren'Py, Twine and TyranoScript",
    },
    "about_check_updates": {"ru": "Проверить обновления", "en": "Check for updates"},
    "about_close": {"ru": "Закрыть", "en": "Close"},
    "changelog_title": {"ru": "Что нового в OctopusBridge", "en": "What's new in OctopusBridge"},
    "updates_title": {"ru": "Доступна новая версия", "en": "Update available"},
    "updates_msg": {
        "ru": "OctopusBridge {v} уже доступен.\nОткрыть страницу релизов?",
        "en": "OctopusBridge {v} is available.\nOpen the release page?",
    },
    "updates_none": {
        "ru": "Установлена последняя версия.",
        "en": "You have the latest version.",
    },
    "updates_check_failed": {
        "ru": "Не удалось проверить обновления.",
        "en": "Could not check for updates.",
    },
}


def set_language(lang: str):
    global _lang
    _lang = lang


def language() -> str:
    return _lang


def TR(key: str, **fmt) -> str:
    entry = _STRINGS.get(key)
    if not entry:
        return key
    text = entry.get(_lang, entry.get("ru", key))
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text


_PROVIDER_KEYS = {
    "honyaku": ("prov_honyaku", "prov_short_honyaku"),
    "google_free": ("prov_google_free", "prov_short_google_free"),
    "bing": ("prov_bing", "prov_short_bing"),
    "rotate": ("prov_rotate", "prov_short_rotate"),
    "ai": ("prov_ai", "prov_short_ai"),
}


def provider_name(key: str) -> str:
    """Полное локализованное имя провайдера (для выпадающих списков)."""
    pair = _PROVIDER_KEYS.get(key)
    return TR(pair[0]) if pair else key


def provider_short_name(key: str) -> str:
    """Краткое локализованное имя провайдера (для дашборда/статус-бара)."""
    pair = _PROVIDER_KEYS.get(key)
    return TR(pair[1]) if pair else key


def engine_hint(name: str) -> str:
    """Локализованная подсказка при недоступном провайдере."""
    key = {"ai": "hint_engine_ai", "honyaku": "hint_engine_honyaku"}.get(name)
    if key is None:
        return TR("hint_check_provider")
    return TR(key)
