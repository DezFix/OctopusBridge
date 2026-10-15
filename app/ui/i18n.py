# -*- coding: utf-8 -*-
"""i18n: TR(key, **fmt) with full RU/EN coverage."""
from __future__ import annotations

#: Языки интерфейса, которые реально переведены в _STRINGS.
#: Новый язык = добавить код сюда + "xx" к каждому ключу + пункт в селектор.
SUPPORTED_UI_LANGS = ("ru", "en", "zh")

_lang: str = "en"


def system_ui_lang() -> str:
    """Язык системы, если интерфейс его поддерживает, иначе "en".

    Сначала пробуем Qt (QLocale — то, что видит пользователь в системе),
    при недоступности Qt — модуль locale. Ручной выбор в настройках
    всегда перекрывает это значение: функция нужна только для дефолта
    при первом запуске.
    """
    code = ""
    try:
        from PySide6.QtCore import QLocale
        code = QLocale.system().name().lower()  # вида "ru_RU"
    except Exception:
        code = ""
    if not code:
        try:
            import locale
            loc = (locale.getdefaultlocale()[0] or "").lower()  # "ru_RU"
            code = loc
        except Exception:
            code = ""
    short = code.split("_")[0].split("-")[0]
    if short in SUPPORTED_UI_LANGS:
        return short
    return "en"


def default_target_lang() -> str:
    """Цель перевода по умолчанию = язык системы, если провайдеры его знают.

    Список известных кодов — TARGET_LANGS из translate.engines
    (ja/zh/ko/en/ru/...). Если системного там нет — "en".
    """
    code = ""
    try:
        from PySide6.QtCore import QLocale
        code = QLocale.system().name().lower()
    except Exception:
        code = ""
    if not code:
        try:
            import locale
            code = ((locale.getdefaultlocale()[0] or "").lower())
        except Exception:
            code = ""
    short = code.split("_")[0].split("-")[0]
    try:
        from app.core.translate.engines import TARGET_LANGS
        if short in TARGET_LANGS:
            return short
    except Exception:
        pass
    return "en"

_STRINGS = {
    # ── App ──
    "app_title": {
        "ru": "OctopusBridge — перевод и модификация игр",
        "en": "OctopusBridge — game translation & modding", "zh": "OctopusBridge — 游戏翻译与模组制作",
    },
    # ── Диалоги ──
    "side_home": {"ru": "Открыть папку игры", "en": "Open game folder", "zh": "打开游戏文件夹"},

    # ── Welcome ──
    "welcome_title": {"ru": "OctopusBridge", "en": "OctopusBridge", "zh": "OctopusBridge"},
    "welcome_subtitle": {
        "ru": "Перевод и модификация игр",
        "en": "Game translation & modding", "zh": "游戏翻译与模组制作",
    },
    "welcome_drop": {
        "ru": "Перетащите сюда Game.exe\nили папку игры",
        "en": "Drop Game.exe\nor the game folder here", "zh": "将 Game.exe\n或游戏文件夹拖到此处",
    },
    "welcome_browse": {
        "ru": "…или выберите папку",
        "en": "…or browse for a folder", "zh": "…或浏览选择文件夹",
    },
    "welcome_loading": {"ru": "Загружаю игру", "en": "Loading game", "zh": "正在加载游戏"},
    "welcome_unsupported": {
        "ru": "Движок не поддерживается.\nПоддерживаются: RPG Maker MV/MZ, Ren'Py, Twine и TyranoScript.",
        "en": "Engine not supported.\nSupported: RPG Maker MV/MZ, Ren'Py, Twine and TyranoScript.", "zh": "不支持该引擎。\n支持：RPG Maker MV/MZ、Ren'Py、Twine 和 TyranoScript。",
    },
    "welcome_hint": {
        "ru": "Поддерживаются: RPG Maker MV/MZ, Ren'Py, Twine и TyranoScript",
        "en": "Supported: RPG Maker MV/MZ, Ren'Py, Twine and TyranoScript", "zh": "支持：RPG Maker MV/MZ、Ren'Py、Twine 和 TyranoScript",
    },
    "welcome_recent": {
        "ru": "Последние проекты",
        "en": "Recent projects", "zh": "最近的项目",
    },
    "welcome_open": {
        "ru": "Открыть",
        "en": "Open", "zh": "打开",
    },
    "welcome_no_recent": {
        "ru": "Нет недавних проектов",
        "en": "No recent projects", "zh": "没有最近的项目",
    },
    "projects_subtitle": {
        "ru": "Нажмите, чтобы продолжить перевод, или перетащите папку игры.",
        "en": "Click to continue, or drag a game folder here.", "zh": "点击继续，或将游戏文件夹拖到此处。",
    },
    "projects_empty_title": {
        "ru": "Пока нет проектов",
        "en": "No projects yet", "zh": "暂无项目",
    },
    "projects_empty_hint": {
        "ru": "Перетащите папку игры или нажмите «Добавить игру».",
        "en": "Drag a game folder or press Add game.", "zh": "拖入游戏文件夹或点击添加游戏。",
    },
    "projects_add": {
        "ru": "Добавить игру",
        "en": "Add game", "zh": "添加游戏",
    },
    "projects_clear": {
        "ru": "Очистить список",
        "en": "Clear list", "zh": "清空列表",
    },
    "projects_clear_confirm": {
        "ru": "Удалить все проекты из списка?",
        "en": "Remove all projects from the list?", "zh": "从列表中删除所有项目？",
    },
    "projects_open_folder": {
        "ru": "Открыть папку",
        "en": "Open folder", "zh": "打开文件夹",
    },
    "welcome_add_project": {
        "ru": "Добавить проект",
        "en": "Add project", "zh": "添加项目",
    },
    "welcome_edit_name": {
        "ru": "Изменить название",
        "en": "Rename", "zh": "重命名",
    },
    "welcome_new_name": {
        "ru": "Новое название:",
        "en": "New name:", "zh": "新名称：",
    },
    "welcome_remove": {
        "ru": "Удалить из списка",
        "en": "Remove from list", "zh": "从列表中删除",
    },
    "welcome_remove_confirm": {
        "ru": "Удалить проект из списка последних?",
        "en": "Remove project from recent list?", "zh": "从最近列表中删除该项目？",
    },

    # ── Dashboard ──
    "dash_game_info": {"ru": "Информация об игре", "en": "Game Info", "zh": "游戏信息"},
    "dash_engine": {"ru": "Движок:", "en": "Engine:", "zh": "引擎："},
    "dash_folder": {"ru": "Папка:", "en": "Folder:", "zh": "文件夹："},
    "dash_encryption": {"ru": "Шифрование:", "en": "Encryption:", "zh": "加密："},
    "dash_saves": {"ru": "Сейвов:", "en": "Saves:", "zh": "存档："},
    "dash_stats": {"ru": "Статистика:", "en": "Statistics:", "zh": "统计："},
    "dash_actions": {"ru": "Быстрые действия", "en": "Quick Actions", "zh": "快捷操作"},
    "dash_extract": {"ru": "1. Извлечь текст", "en": "1. Extract text", "zh": "1. 提取文本"},
    "dash_translate": {"ru": "2. Перевести файлы", "en": "2. Translate files", "zh": "2. 翻译文件"},
    "dash_launch": {
        "ru": "Запустить игру (для читов)",
        "en": "Launch game (for cheats)", "zh": "启动游戏（用于作弊）",
    },
    "dash_stop": {"ru": "Остановить игру", "en": "Stop game", "zh": "停止游戏"},
    "dash_launching": {"ru": "Запускаю игру…", "en": "Launching game…", "zh": "正在启动游戏…"},
    "project_opening": {"ru": "Открываю проект…", "en": "Opening project…", "zh": "正在打开项目…"},
    "dash_session_idle": {"ru": "Игра не запущена", "en": "Game not running", "zh": "游戏未运行"},
    "dash_session_connected": {
        "ru": "Игра запущена и подключена",
        "en": "Game running and attached", "zh": "游戏运行中并已连接",
    },
    "dash_session_closed": {"ru": "Игра завершена", "en": "Game closed", "zh": "游戏已关闭"},
    "dash_session_nocdp": {
        "ru": "Игра запущена (перевод через ob_runtime.js, читы недоступны — нет отладчика)",
        "en": "Game running (translation via ob_runtime.js, cheats unavailable — no debugger)", "zh": "游戏运行中（通过 ob_runtime.js 翻译，作弊不可用——无调试器）",
    },
    "dash_session_unsupported": {
        "ru": "Этот движок не поддерживает подключение к игре",
        "en": "This engine does not support attach yet", "zh": "该引擎暂不支持连接",
    },
    "dash_cheats": {"ru": "Читы", "en": "Cheats", "zh": "作弊"},
    "dash_provider": {"ru": "Провайдер перевода", "en": "Translation Provider", "zh": "翻译服务"},
    "dash_provider_engine": {"ru": "Движок:", "en": "Engine:", "zh": "引擎："},
    "dash_provider_check": {"ru": "Проверить", "en": "Check", "zh": "检查"},
    "dash_change_game": {"ru": "Сменить игру", "en": "Change game", "zh": "更换游戏"},
    "welcome_open_folder": {"ru": "Открыть папку игры", "en": "Open game folder", "zh": "打开游戏文件夹"},
    "dash_settings": {"ru": "Настройки", "en": "Settings", "zh": "设置"},
    "dash_font": {"ru": "Шрифт с кириллицей", "en": "Cyrillic font", "zh": "西里尔字体"},
    "dash_font_common": {"ru": "Шрифт", "en": "Font", "zh": "字体"},
    "dash_font_cyr": {"ru": "Кириллица", "en": "Cyrillic", "zh": "西里尔字母"},
    "dash_font_size": {"ru": "Размер шрифта в игре", "en": "In-game font size", "zh": "游戏内字体大小"},
    "dash_font_size_lbl": {"ru": "Размер", "en": "Size", "zh": "大小"},
    "dash_font_smaller": {
        "ru": "Сделать текст игры меньше", "en": "Make in-game text smaller", "zh": "调小游戏内文本"},
    "dash_font_bigger": {
        "ru": "Сделать текст игры больше", "en": "Make in-game text bigger", "zh": "调大游戏内文本"},
    "dash_font_size_hint": {
        "ru": "Применяется сразу, если игра запущена, иначе — после перезапуска.",
        "en": "Applies live if the game is running, else after restart.", "zh": "游戏运行时即时生效，否则重启后生效。",
    },
    "dash_font_live_ok": {
        "ru": "Применено к запущенной игре без перезапуска.",
        "en": "Applied to the running game without restart.", "zh": "已应用于正在运行的游戏，无需重启。",
    },
    "dash_font_live_failed": {
        "ru": "Сохранено, но текущая игра не обновлена — повторите после подключения.",
        "en": "Saved, but the running game was not updated; retry after connecting.", "zh": "已保存，但正在运行的游戏未更新；连接后重试。",
    },
    "dash_font_size_live_ok": {
        "ru": "Размер шрифта применён к запущенной игре.",
        "en": "Font size applied to the running game.", "zh": "字体大小已应用于正在运行的游戏。",
    },
    "dash_font_size_live_failed": {
        "ru": "Размер сохранён, но текущая игра не обновлена.",
        "en": "Font size saved, but the running game was not updated.", "zh": "字体大小已保存，但正在运行的游戏未更新。",
    },
    "dash_font_need_restart": {
        "ru": "Игра не запущена — вступит в силу после перезапуска.",
        "en": "Game not running — takes effect after restart.", "zh": "游戏未运行——重启后生效。",
    },
    "dash_no_extract": {
        "ru": "Текст ещё не извлечён. Нажмите «Извлечь текст».",
        "en": "Text not yet extracted. Click \"Extract text\".", "zh": "文本尚未提取。点击“提取文本”。",
    },
    "dash_stats_fmt": {
        "ru": "Записей: {total}  |  Переведено: {done}  |  Осталось: {left}",
        "en": "Entries: {total}  |  Translated: {done}  |  Remaining: {left}", "zh": "条目：{total}  |  已翻译：{done}  |  剩余：{left}",
    },
    "dash_enc_yes": {"ru": "да", "en": "yes", "zh": "是"},
    "dash_enc_no": {"ru": "нет", "en": "no", "zh": "否"},

    # ── Tabs ──
    "tab_home": {"ru": "Домой", "en": "Home", "zh": "首页"},
    "tab_projects": {"ru": "Проекты", "en": "Projects", "zh": "项目"},
    "tab_translate": {"ru": "Перевод", "en": "Translate", "zh": "翻译"},
    "tab_live": {"ru": "Реалтайм", "en": "Live", "zh": "实时"},
    "tab_cheats": {"ru": "Читы", "en": "Cheats", "zh": "作弊"},

    # ── Translate tab ──
    "tr_extract": {"ru": "Извлечь текст", "en": "Extract text", "zh": "提取文本"},
    "tr_extracting": {
        "ru": "Извлекаю текст из игры…",
        "en": "Extracting text from the game…", "zh": "正在从游戏中提取文本…",
    },
    "tr_translating": {"ru": "Перевожу…", "en": "Translating…", "zh": "翻译中…"},
    "tr_status_ping": {
        "ru": "Проверка связи с переводчиком…",
        "en": "Checking translator connection…", "zh": "正在检查翻译器连接…",
    },
    "tr_status_wait": {
        "ru": "Провайдеры отдыхают от лимита, жду {sec} с…",
        "en": "Providers cooling down, waiting {sec}s…", "zh": "服务商冷却中，等待 {sec} 秒…",
    },
    "tr_mode_new": {"ru": "Только новые и сбойные", "en": "New & failed only", "zh": "仅新增和失败"},
    "tr_mode_all": {"ru": "Перевести всё заново", "en": "Re-translate all", "zh": "全部重新翻译"},
    "tr_mode": {"ru": "Режим перевода", "en": "Translation mode", "zh": "翻译模式"},
    "tr_mode_new_desc": {"ru": "Переведёт только непереведённые строки и строки с ошибками",
                         "en": "Translate only untranslated lines and failed ones", "zh": "仅翻译未翻译和失败的行"},
    "tr_mode_all_desc": {"ru": "Перезапишет все строки, включая уже переведённые",
                         "en": "Rewrite all lines, including already translated", "zh": "重写所有行，包括已翻译的"},
    "tr_translate": {"ru": "Перевести", "en": "Translate", "zh": "翻译"},
    "tr_src_filter": {"ru": "Какие языки гнать в переводчик (остальные не трогаем):",
                      "en": "Which source languages to send (rest are left alone):", "zh": "要发送哪些源语言（其余保持不动）："},
    "tr_src_all": {"ru": "Все", "en": "All", "zh": "全部"},
    "tr_src_none": {"ru": "Ничего", "en": "None", "zh": "无"},
    "tr_src_selected": {"ru": "Выбрано: {n}", "en": "Selected: {n}", "zh": "已选：{n}"},
    "tr_unity_typetree": {"ru": "typetree: {status} (MonoBehaviour пропущены)",
                          "en": "typetree: {status} (MonoBehaviour skipped)", "zh": "typetree：{status}（已跳过 MonoBehaviour）"},
    "tr_lang_unknown": {"ru": "Без букв", "en": "No letters", "zh": "无字母"},
    "tr_cancel": {"ru": "Отмена", "en": "Cancel", "zh": "取消"},
    "tr_apply": {"ru": "Внедрить в игру", "en": "Apply to game", "zh": "应用到游戏"},
    "tr_glossary": {"ru": "Глоссарий…", "en": "Glossary…", "zh": "术语表…"},
    "tr_export": {"ru": "Экспорт CSV", "en": "Export CSV", "zh": "导出 CSV"},
    "tr_import": {"ru": "Импорт CSV", "en": "Import CSV", "zh": "导入 CSV"},
    "tr_search": {"ru": "Поиск:", "en": "Search:", "zh": "搜索："},
    "tr_search_ph": {
        "ru": "текст оригинала/перевода…",
        "en": "original/translation text…", "zh": "原文/译文…",
    },
    "tr_filter": {"ru": "Показать:", "en": "Show:", "zh": "显示："},
    "tr_filter_all": {"ru": "Все", "en": "All", "zh": "全部"},
    "tr_filter_untranslated": {"ru": "Без перевода", "en": "Untranslated", "zh": "未翻译"},
    "tr_filter_translated": {"ru": "Переведённые", "en": "Translated", "zh": "已翻译"},
    "tr_filter_skipped": {"ru": "Пропущенные", "en": "Skipped", "zh": "已跳过"},
    "tr_file": {"ru": "Файл:", "en": "File:", "zh": "文件："},
    "tr_files": {"ru": "Файлы", "en": "Files", "zh": "文件"},
    "tr_all_files": {"ru": "Все файлы", "en": "All files", "zh": "所有文件"},
    "tr_select_file": {"ru": "Выберите файл слева", "en": "Select a file on the left", "zh": "请在左侧选择文件"},
    "tr_no_project": {
        "ru": "Сначала откройте игру",
        "en": "Open a game first", "zh": "请先打开游戏",
    },
    "tr_no_data": {"ru": "Сначала извлеките текст", "en": "Extract text first", "zh": "请先提取文本"},
    "tr_engine_create_fail": {
        "ru": "Не удалось создать движок перевода. Проверьте настройки провайдера.",
        "en": "Failed to create translation engine. Check provider settings.", "zh": "无法创建翻译引擎。请检查服务商设置。",
    },
    "tr_no_engine": {"ru": "Движок игры не поддерживается", "en": "Engine not supported", "zh": "不支持该引擎"},
    "tr_extract_done": {
        "ru": "Извлечено записей: {count}\nСохранено переводов: {restored}",
        "en": "Extracted: {count}\nRestored translations: {restored}", "zh": "已提取：{count}\n已恢复译文：{restored}",
    },
    "tr_translate_done": {
        "ru": "Переведено строк: {n}{skipped}{skipped_note}",
        "en": "Translated lines: {n}{skipped}{skipped_note}", "zh": "已翻译行数：{n}{skipped}{skipped_note}",
    },
    "tr_translate_done_skipped": {
        "ru": "\nСтрок на целевом языке (не требуют перевода): {skipped}",
        "en": "\nLines already in target language (skipped): {skipped}", "zh": "\n已是目标语言的行（已跳过）：{skipped}",
    },
    "tr_file_target_lang": {
        "ru": "на целевом языке",
        "en": "in target language", "zh": "目标语言",
    },
    "tr_file_target_lang_hint": {
        "ru": "Файл не требует перевода: текст уже на целевом языке.",
        "en": "No translation needed: the text is already in the target language.", "zh": "无需翻译：文本已是目标语言。",
    },
    "tr_translate_lang": {
        "ru": "Язык игры",
        "en": "Game language", "zh": "游戏语言",
    },
    "tr_lang_all": {
        "ru": "Весь текст игры",
        "en": "All game text", "zh": "全部游戏文本",
    },
    "tr_lang_dialog_title": {
        "ru": "Язык перевода",
        "en": "Translation language", "zh": "翻译语言",
    },
    "tr_lang_dialog_question": {
        "ru": "В игре несколько официальных переводов (tl/). Что переводить?",
        "en": "The game has several official translations (tl/). What should be translated?", "zh": "游戏有多个官方翻译（tl/）。要翻译哪个？",
    },
    "tr_lang_dialog_remember": {
        "ru": "Не спрашивать больше (запомнить для этого проекта)",
        "en": "Don't ask again (remember for this project)", "zh": "不再询问（记住本项目的选择）",
    },
    "tr_lang_applied": {
        "ru": "Язык применён: извлечено {count} строк",
        "en": "Language applied: {count} lines extracted", "zh": "已应用语言：提取了 {count} 行",
    },
    "tr_cancelling": {"ru": "Отмена…", "en": "Cancelling…", "zh": "正在取消…"},
    "tr_cancelled": {
        "ru": "Отменено: переведено {done} из {total} строк (перевод сохранён в проекте — его можно доработать или применить)",
        "en": "Cancelled: {done} of {total} lines translated (kept in project)", "zh": "已取消：已翻译 {done}/{total} 行（保留在项目中）",
    },
    # ── Coverage ──
    "cov_file": {"ru": "Файл", "en": "File", "zh": "文件"},
    "cov_total": {"ru": "Всего", "en": "Total", "zh": "总数"},
    "cov_done": {"ru": "Переведено", "en": "Translated", "zh": "已翻译"},
    "cov_pct": {"ru": "%", "en": "%", "zh": "%"},
    "tr_apply_title": {"ru": "Внедрение", "en": "Apply", "zh": "应用"},
    "tr_apply_msg": {
        "ru": "Внедрить {n} переведённых строк?",
        "en": "Apply {n} translated lines?", "zh": "应用 {n} 条已翻译的行？",
    },
    "tr_apply_done": {
        "ru": "Файлов: {files}\nСтрок: {strings}",
        "en": "Files: {files}\nStrings: {strings}", "zh": "文件：{files}\n字符串：{strings}",
    },
    "tr_apply_live": {
        "ru": "Перевод внедрён в запущенную игру (live-хук MV/MZ).",
        "en": "Translation pushed to the running game (MV/MZ live hook).", "zh": "译文已推送到正在运行的游戏（MV/MZ 实时钩子）。",
    },
    "tr_apply_backup": {
        "ru": "Бэкап: {n} файлов",
        "en": "Backup: {n} files", "zh": "备份：{n} 个文件",
    },
    "tr_apply_folder": {
        "ru": "Папка: {path}",
        "en": "Folder: {path}", "zh": "文件夹：{path}",
    },
    "tr_apply_newfile": {
        "ru": "Создан файл: {path}\nОригинал не тронут.",
        "en": "Created file: {path}\nOriginal left untouched.", "zh": "已创建文件：{path}\n原文件未改动。",
    },
    "tr_apply_orphans": {
        "ru": "Удалено устаревших файлов: {n}",
        "en": "Removed stale files: {n}", "zh": "已删除过期文件：{n}",
    },
    "tr_apply_skipped": {
        "ru": "Пропущено: {n} ({details})",
        "en": "Skipped: {n} ({details})", "zh": "已跳过：{n}（{details}）",
    },
    "tr_apply_longlines": {
        "ru": "⚠ Длинных строк (могут налезать): {n}\n{problems}\n"
              "Уменьшите шрифт на «Домой» или сократите перевод.",
        "en": "⚠ Overlong lines (may overlap): {n}\n{problems}\n"
              "Lower the font size on \"Home\" or shorten the translation.", "zh": "⚠ 过长行（可能重叠）：{n}\n{problems}\n请在“首页”调小字体或缩短译文。",
    },
    "tr_verify_failed": {
        "ru": "Проверка файлов игры НЕ пройдена — перевод откачен, игра не тронута:\n{problems}",
        "en": "Game files check FAILED — translation rolled back, game untouched:\n{problems}", "zh": "游戏文件校验失败——译文已回滚，游戏未改动：\n{problems}",
    },
    "tr_verify_restored": {
        "ru": "Оригиналы восстановлены из бэкапа.",
        "en": "Originals restored from backup.", "zh": "已从备份恢复原文。",
    },
    "tr_verify_broken": {
        "ru": "ВНИМАНИЕ: файлы остались битыми и после отката:\n{remaining}\nВосстанови игру из своей копии вручную.",
        "en": "WARNING: files are still broken after rollback:\n{remaining}\nRestore the game from your own copy manually.", "zh": "警告：回滚后文件仍损坏：\n{remaining}\n请手动用自己的备份恢复游戏。",
    },
    "tr_restore": {
        "ru": "Восстановить оригинал",
        "en": "Restore original", "zh": "恢复原文",
    },
    "tr_restore_title": {
        "ru": "Восстановление оригинала",
        "en": "Restore original", "zh": "恢复原文",
    },
    "tr_restore_msg": {
        "ru": "Вернуть файлы игры из бэкапа (сбросить переводы)?",
        "en": "Restore game files from backup (discard translations)?", "zh": "从备份恢复游戏文件（丢弃译文）？",
    },
    "tr_restore_done": {
        "ru": "Восстановлено файлов: {n}",
        "en": "Files restored: {n}", "zh": "已恢复文件：{n}",
    },
    "tr_progress": {
        "ru": "Переведено {done}/{total}",
        "en": "Translated {done}/{total}", "zh": "已翻译 {done}/{total}",
    },
    "tr_status": {
        "ru": "Показано: {shown} из {total}{note}",
        "en": "Showing: {shown} of {total}{note}", "zh": "显示：{shown}/{total}{note}",
    },
    "tr_status_cap": {
        "ru": " (первые 10000, уточните фильтр)",
        "en": " (first 10000, refine your filter)", "zh": "（前 10000 条，请细化筛选）",
    },
    # ── Translate tab: redesigned UI ──
    "tr_files_search_ph": {"ru": "Поиск: файлы и текст…", "en": "Search files and text…", "zh": "搜索文件和文本…"},
    "tr_files_summary": {
        "ru": "{files} · завершено: {done}",
        "en": "{files} · done: {done}", "zh": "{files} · 已完成：{done}",
    },
    "tr_donut_caption": {
        "ru": "переведено · {pct}%",
        "en": "translated · {pct}%", "zh": "已翻译 · {pct}%",
    },
    "tr_status_empty": {"ru": "Пусто", "en": "Empty", "zh": "空"},
    "tr_status_draft": {"ru": "Черновик", "en": "Draft", "zh": "草稿"},
    "tr_status_done": {"ru": "Готово", "en": "Done", "zh": "完成"},
    "tr_status_skip": {"ru": "Пропуск", "en": "Skipped", "zh": "已跳过"},
    "tr_trans_placeholder": {
        "ru": "Нажмите, чтобы перевести…",
        "en": "Click to translate…", "zh": "点击翻译…",
    },
    "tr_edit_hint": {
        "ru": "Enter — сохранить · Esc — отмена",
        "en": "Enter — save · Esc — cancel", "zh": "回车——保存 · Esc——取消",
    },
    "tr_saved": {"ru": "Сохранено", "en": "Saved", "zh": "已保存"},
    "tr_resuming": {
        "ru": "Продолжаем незаконченный перевод...",
        "en": "Resuming unfinished translation...", "zh": "正在继续未完成的翻译…",
    },
    "tr_waiting_providers": {
        "ru": "Провайдеры отдыхают от лимита, ждём. Осталось не переведено: {n}",
        "en": "Providers are resting on their limits, waiting. "
              "Still untranslated: {n}", "zh": "服务商达到限额休息中，等待中。仍未翻译：{n}",
    },
    "tr_left_over": {
        "ru": "Не переведено {n} строк — повторятся при следующем запуске.",
        "en": "{n} lines untranslated — will retry next run.", "zh": "{n} 行未翻译——下次运行时重试。",
    },
    "tr_autoresume": {
        "ru": "Предлагать дотянуть перевод при открытии проекта",
        "en": "Offer to resume unfinished translation when opening a project", "zh": "打开项目时提示继续未完成的翻译",
    },
    "tr_resume_offer": {
        "ru": "Прошлый перевод не закончен (осталось строк: {n}). "
              "Нажмите «Перевести», чтобы продолжить, — или игнорируйте.",
        "en": "Previous translation did not finish ({n} lines left). "
              "Press Translate to continue — or ignore this.", "zh": "上次翻译未完成（剩余 {n} 行）。按“翻译”继续——或忽略。",
    },
    "tr_filter_all_lines": {"ru": "Все строки", "en": "All lines", "zh": "所有行"},
    "tr_filter_drafts": {"ru": "Черновики", "en": "Drafts", "zh": "草稿"},
    "tr_filter_finished": {"ru": "Готовые", "en": "Finished", "zh": "已完成"},
    "tr_col_idx": {"ru": "#", "en": "#", "zh": "#"},
    "tr_col_context": {"ru": "Контекст", "en": "Context", "zh": "上下文"},
    "tr_col_original": {"ru": "Оригинал", "en": "Original", "zh": "原文"},
    "tr_col_translation": {"ru": "Перевод", "en": "Translation", "zh": "译文"},
    "tr_col_status": {"ru": "Статус", "en": "Status", "zh": "状态"},
    "tr_copy_original": {"ru": "Копировать оригинал", "en": "Copy original", "zh": "复制原文"},
    "tr_copy_translation": {
        "ru": "Копировать перевод",
        "en": "Copy translation", "zh": "复制译文",
    },
    "tr_copy_row": {"ru": "Копировать строку", "en": "Copy row", "zh": "复制行"},
    "sb_done": {"ru": "переведено", "en": "translated", "zh": "已翻译"},
    "sb_draft": {"ru": "черновиков", "en": "drafts", "zh": "草稿"},
    "sb_empty": {"ru": "пусто", "en": "empty", "zh": "空"},

    # ── Cheat tab ──
    "cheat_hint": {
        "ru": "Читы работают через запущенную игру («Домой» → «Запустить игру»).",
        "en": "Cheats require the running game (\"Home\" → \"Launch game\").", "zh": "作弊需要正在运行的游戏（“首页”→“启动游戏”）。",
    },
    "cheat_names_translating": {
        "ru": "ИИ переводит имена…",
        "en": "AI translating names…", "zh": "AI 正在翻译名称…",
    },
    "cheat_main": {"ru": "Главная", "en": "Main", "zh": "主要"},
    "cheat_party": {"ru": "Пати", "en": "Party", "zh": "队伍"},
    "cheat_map": {"ru": "Карта", "en": "Map", "zh": "地图"},
    "cheat_items": {"ru": "Предметы", "en": "Items", "zh": "物品"},
    "cheat_vars": {"ru": "Переменные", "en": "Variables", "zh": "变量"},
    "cheat_switches": {"ru": "Переключатели", "en": "Switches", "zh": "开关"},
    "cheat_gold": {"ru": "Золото:", "en": "Gold:", "zh": "金钱："},
    "cheat_menu": {"ru": "Меню игры", "en": "Game Menu", "zh": "游戏菜单"},
    "cheat_menu_main": {"ru": "Меню (Esc)", "en": "Menu (Esc)", "zh": "菜单（Esc）"},
    "cheat_menu_items": {"ru": "Предметы", "en": "Items", "zh": "物品"},
    "cheat_menu_skills": {"ru": "Навыки", "en": "Skills", "zh": "技能"},
    "cheat_menu_equip": {"ru": "Экипировка", "en": "Equipment", "zh": "装备"},
    "cheat_menu_status": {"ru": "Статус", "en": "Status", "zh": "状态"},
    "cheat_menu_save": {"ru": "Сохранить", "en": "Save", "zh": "保存"},
    "cheat_menu_load": {"ru": "Загрузить", "en": "Load", "zh": "读取"},
    "cheat_menu_options": {"ru": "Настройки", "en": "Options", "zh": "选项"},
    "cheat_menu_end": {"ru": "Конец игры", "en": "Game End", "zh": "结束游戏"},
    "cheat_map_id": {"ru": "Карта №:", "en": "Map #:", "zh": "地图编号："},
    "cheat_in_battle": {"ru": "В бою:", "en": "In battle:", "zh": "战斗中："},
    "cheat_refresh": {"ru": "Обновить данные из игры", "en": "Refresh from game", "zh": "从游戏刷新"},
    "cheat_heal": {"ru": "Вылечить партию (HP/MP)", "en": "Heal party (HP/MP)", "zh": "治疗队伍（HP/MP）"},
    "cheat_win": {"ru": "Мгновенная победа", "en": "Instant win", "zh": "立即获胜"},
    "cheat_box_battle": {"ru": "Бой", "en": "Battle", "zh": "战斗"},
    "cheat_box_movement": {"ru": "Перемещение", "en": "Movement", "zh": "移动"},
    "cheat_kind_all": {"ru": "Все", "en": "All", "zh": "全部"},
    "cheat_kind_items": {"ru": "Предметы", "en": "Items", "zh": "物品"},
    "cheat_kind_weapons": {"ru": "Оружие", "en": "Weapons", "zh": "武器"},
    "cheat_kind_armor": {"ru": "Броня", "en": "Armor", "zh": "防具"},
    "tbl_col_idx": {"ru": "#", "en": "#", "zh": "#"},
    "tbl_col_id": {"ru": "ID", "en": "ID", "zh": "ID"},
    "tbl_col_name": {"ru": "Имя", "en": "Name", "zh": "名称"},
    "tbl_col_value": {"ru": "Значение", "en": "Value", "zh": "数值"},
    "tbl_col_type": {"ru": "Тип", "en": "Type", "zh": "类型"},
    "tbl_col_count": {"ru": "Кол-во", "en": "Count", "zh": "数量"},
    "tbl_col_on": {"ru": "Вкл", "en": "On", "zh": "开"},
    "party_col_class": {"ru": "Класс", "en": "Class", "zh": "职业"},
    "party_col_level": {"ru": "Уровень", "en": "Level", "zh": "等级"},
    "party_col_hp": {"ru": "HP", "en": "HP", "zh": "HP"},
    "party_col_mp": {"ru": "MP", "en": "MP", "zh": "MP"},
    "party_col_exp": {"ru": "EXP", "en": "EXP", "zh": "EXP"},
    "party_col_inparty": {"ru": "В партии", "en": "In Party", "zh": "在队伍中"},
    "cheat_speed": {"ru": "Скорость игрока", "en": "Player speed", "zh": "玩家速度"},
    "cheat_noclip": {"ru": "Ноуклип (сквозь стены)", "en": "No-clip (through walls)", "zh": "穿墙"},
    "cheat_clicktp": {"ru": "Телепорт по Ctrl+клику", "en": "Teleport on Ctrl+click", "zh": "Ctrl+点击传送"},
    "cheat_gold_set": {"ru": "Задать", "en": "Set", "zh": "设置"},
    "cheat_gold_add": {"ru": "Добавить", "en": "Add", "zh": "增加"},
    "cheat_apply": {"ru": "Применить", "en": "Apply", "zh": "应用"},
    "cheat_apply_party": {
        "ru": "Применить изменения (уровень/HP/MP/EXP)",
        "en": "Apply changes (level/HP/MP/EXP)", "zh": "应用更改（等级/HP/MP/EXP）",
    },
    "cheat_apply_items": {
        "ru": "Выдать (применить новые количества)",
        "en": "Give (apply new quantities)", "zh": "发放（应用新数量）",
    },
    "cheat_apply_vars": {"ru": "Применить значения", "en": "Apply values", "zh": "应用数值"},
    "cheat_var_hint": {
        "ru": "Enter — применить, Escape — отмена.",
        "en": "Enter applies, Escape cancels.", "zh": "回车应用，Esc 取消。",
    },
    "cheat_sw_hint": {
        "ru": "Галочка применяется сразу. Имя редактируется и сохраняется.",
        "en": "Toggle applies immediately. Names are editable.", "zh": "切换即时生效。名称可编辑。",
    },
    "cheat_freeze": {
        "ru": "Заморозить #{idx} (держать значение)",
        "en": "Freeze #{idx} (hold value)", "zh": "冻结 #{idx}（保持数值）",
    },
    "cheat_unfreeze": {
        "ru": "Снять заморозку #{idx}",
        "en": "Unfreeze #{idx}", "zh": "解冻 #{idx}",
    },
    "cheat_frozen": {
        "ru": "Заморожено: значение удерживается каждый тик",
        "en": "Frozen: value is re-applied every tick", "zh": "已冻结：每 tick 重新写入数值",
    },
    "cheat_map_search": {"ru": "Поиск карты:", "en": "Search map:", "zh": "搜索地图："},
    "cheat_item_search": {"ru": "Поиск:", "en": "Search:", "zh": "搜索："},
    "cheat_no_bridge": {
        "ru": "Нет подключения к игре. Запустите игру через приложение",
        "en": "No game connection. Launch the game via the app", "zh": "无游戏连接。请通过本应用启动游戏",
    },
    "cheat_connected": {
        "ru": "Игра подключена — читы активны",
        "en": "Game connected — cheats active", "zh": "游戏已连接——作弊生效中",
    },
    "cheat_reconnecting": {
        "ru": "Восстанавливаю подключение к игре…",
        "en": "Reconnecting to the game…", "zh": "正在重新连接游戏…",
    },
    "cheat_disconnected": {"ru": "Жду подключения игры…", "en": "Waiting for game…", "zh": "等待游戏中…"},
    "cheat_done": {"ru": "Чит {cmd}: выполнен", "en": "Cheat {cmd}: done", "zh": "作弊 {cmd}：完成"},
    "cheat_error": {"ru": "Чит {cmd}: ОШИБКА {err}", "en": "Cheat {cmd}: ERROR {err}", "zh": "作弊 {cmd}：错误 {err}"},
    "cheat_auto_refresh": {"ru": "Авто-обновление", "en": "Auto-refresh", "zh": "自动刷新"},
    "cheat_changed": {"ru": "Изменено", "en": "Changed", "zh": "已更改"},
    "cheat_box_party": {"ru": "Отряд", "en": "Party", "zh": "队伍"},
    "cheat_heal_full": {
        "ru": "Полное исцеление (HP/MP + состояния)",
        "en": "Full heal (HP/MP + states)", "zh": "完全治疗（HP/MP + 状态）",
    },
    "cheat_clear_states": {"ru": "Снять состояния", "en": "Clear states", "zh": "清除状态"},
    "cheat_turbo": {"ru": "Турбо (скорость игры)", "en": "Turbo (game speed)", "zh": "加速（游戏速度）"},
    "cheat_reload_map": {"ru": "Перезагрузить карту", "en": "Reload map", "zh": "重载地图"},
    "cheat_screenshot": {"ru": "Скриншот", "en": "Screenshot", "zh": "截图"},
    "cheat_screenshot_ok": {
        "ru": "Скриншот сохранён: {path}",
        "en": "Screenshot saved: {path}", "zh": "截图已保存：{path}",
    },
    "cheat_screenshot_fail": {
        "ru": "Не удалось сделать скриншот",
        "en": "Screenshot failed", "zh": "截图失败",
    },
    "cheat_sel_item": {"ru": "Выделенное:", "en": "Selected:", "zh": "已选："},

    # ── Settings ──
    "settings_title": {"ru": "Настройки", "en": "Settings", "zh": "设置"},
    "settings_save": {"ru": "Сохранить", "en": "Save", "zh": "保存"},
    "settings_general": {"ru": "Основные", "en": "General", "zh": "常规"},
    "settings_languages": {"ru": "Языки перевода", "en": "Translation Languages", "zh": "翻译语言"},
    "settings_files": {"ru": "Файлы", "en": "Files", "zh": "文件"},
    "settings_system_tab": {"ru": "Система", "en": "System", "zh": "系统"},
    "settings_cache_box": {"ru": "Кеш", "en": "Cache", "zh": "缓存"},
    "settings_cache_size_lbl": {
        "ru": "Папка проектов:",
        "en": "Projects folder:", "zh": "项目文件夹：",
    },
    "settings_cache_size": {
        "ru": "{size} ({files} файлов) · Кеш: {tmp}",
        "en": "{size} ({files} files) · Cache: {tmp}", "zh": "{size}（{files} 个文件）· 缓存：{tmp}",
    },
    "settings_cache_clean": {"ru": "Очистить кеш", "en": "Clear cache", "zh": "清理缓存"},
    "settings_cache_open": {"ru": "Открыть папку", "en": "Open folder", "zh": "打开文件夹"},
    "settings_cache_auto": {
        "ru": "Автоочистка: удалять временные проекты при запуске, "
             "если кеш превысит",
        "en": "Auto-clean: remove temp projects on start when cache "
             "exceeds", "zh": "自动清理：缓存超限时启动时删除临时项目",
    },
    "settings_cache_limit": {
        "ru": "Порог (когда чистить):",
        "en": "Limit (when to clean):", "zh": "上限（何时清理）：",
    },
    "settings_cache_mb": {"ru": "МБ", "en": "MB", "zh": "MB"},
    "settings_cache_cleaned": {
        "ru": "Очищено: {size}",
        "en": "Cleaned: {size}", "zh": "已清理：{size}",
    },
    "settings_cache_nothing": {
        "ru": "Кеш пуст — удалять нечего",
        "en": "Cache is empty — nothing to clean", "zh": "缓存为空——无需清理",
    },
    "settings_cache_info": {
        "ru": "Временные файлы прерванных сессий. Проекты и база "
              "переводов не удаляются.",
        "en": "Temp files of interrupted sessions. Projects and the "
              "translation memory are kept.", "zh": "中断会话的临时文件。项目和翻译记忆保留。",
    },
    "settings_provider": {"ru": "Провайдер перевода", "en": "Translation Provider", "zh": "翻译服务"},
    "settings_files_provider": {
        "ru": "Провайдер для перевода файлов",
        "en": "File translation provider", "zh": "文件翻译服务",
    },
    "settings_corr_provider": {
        "ru": "Провайдер для ИИ-коррекции",
        "en": "AI correction provider", "zh": "AI 校对服务",
    },
    "settings_provider_lbl": {"ru": "Провайдер:", "en": "Provider:", "zh": "服务商："},
    "settings_provider_fixed": {
        "ru": "Автопилот: Google → Bing → MyMemory, по кругу.",
        "en": "Autopilot: Google → Bing → MyMemory, cycling.", "zh": "自动驾驶：Google → Bing → MyMemory 轮询。",
    },
    "settings_mymemory_email": {
        "ru": "Почта для MyMemory:",
        "en": "MyMemory e-mail:", "zh": "MyMemory 邮箱：",
    },
    "settings_mymemory_email_ph": {
        "ru": "необязательно — с почтой 50K символов/день",
        "en": "optional — 50K chars/day with e-mail", "zh": "可选——填写邮箱后每天 50K 字符",
    },
    "settings_src_lang": {"ru": "Язык оригинала:", "en": "Source language:", "zh": "源语言："},
    "settings_src_lang_auto": {
        "ru": "Язык оригинала:",
        "en": "Source language:", "zh": "源语言：",
    },
    "settings_src_lang_auto_note": {
        "ru": "определяется автоматически",
        "en": "detected automatically", "zh": "自动检测",
    },
    "settings_tgt_lang": {"ru": "Язык перевода:", "en": "Target language:", "zh": "目标语言："},
    "settings_check": {"ru": "Проверить провайдера", "en": "Check provider", "zh": "检查服务商"},
    "settings_status_ping": {
        "ru": "Проверяю соединение…",
        "en": "Checking connection…", "zh": "正在检查连接…",
    },
    "settings_status": {"ru": "Статус:", "en": "Status:", "zh": "状态："},
    "settings_status_ready": {
        "ru": "Провайдер готов к работе",
        "en": "Provider ready", "zh": "服务商就绪",
    },
    "settings_status_fail": {
        "ru": "НЕ доступен (ключ? сервер? пакеты?)",
        "en": "Unavailable (key? server? packages?)", "zh": "不可用（密钥？服务器？依赖？）",
    },
    "settings_game": {"ru": "Игра", "en": "Game", "zh": "游戏"},
    "settings_auto_launch": {
        "ru": "Автозапуск игры (для читов) при открытии проекта",
        "en": "Auto-launch game (for cheats) on project open", "zh": "打开项目时自动启动游戏（用于作弊）",
    },
    "settings_overwrite": {"ru": "Режим перевода:", "en": "Translation mode:", "zh": "翻译模式："},
    "settings_overwrite_new": {
        "ru": "Только новые и без перевода",
        "en": "New & untranslated only", "zh": "仅新增和未翻译",
    },
    "settings_overwrite_all": {
        "ru": "Перевести всё заново (перезаписать)",
        "en": "Re-translate all (overwrite)", "zh": "全部重新翻译（覆盖）",
    },
    "settings_backup": {"ru": "Автобэкап при внедрении", "en": "Auto-backup on apply", "zh": "应用时自动备份"},
    "settings_files_info": {
        "ru": "«Только новые» — без перевода. «Всё заново» — все строки.",
        "en": "\"New only\" — untranslated. \"Re-translate all\" — everything.", "zh": "“仅新增”——未翻译。“全部重新翻译”——所有内容。",
    },
    "settings_ui_lang": {
        "ru": "Язык интерфейса:",
        "en": "UI Language:", "zh": "界面语言：",
    },
    "settings_ui_ru": {"ru": "Русский", "en": "Russian", "zh": "俄语"},
    "settings_ui_en": {"ru": "Английский", "en": "English", "zh": "英语"},
    "settings_restart_hint": {
        "ru": "Язык изменится после перезапуска приложения.",
        "en": "Language will change after restarting the app.", "zh": "重启应用后语言生效。",
    },

    # ── Названия языков (перевод текста игр) ──
    "lang_auto": {"ru": "Автоопределение", "en": "Auto-detect", "zh": "自动检测"},
    "lang_ja": {"ru": "Японский", "en": "Japanese", "zh": "日语"},
    "lang_zh": {"ru": "Китайский", "en": "Chinese", "zh": "中文"},
    "lang_ko": {"ru": "Корейский", "en": "Korean", "zh": "韩语"},
    "lang_en": {"ru": "Английский", "en": "English", "zh": "英语"},
    "lang_ru": {"ru": "Русский", "en": "Russian", "zh": "俄语"},
    "lang_uk": {"ru": "Украинский", "en": "Ukrainian", "zh": "乌克兰语"},
    "lang_de": {"ru": "Немецкий", "en": "German", "zh": "德语"},
    "lang_fr": {"ru": "Французский", "en": "French", "zh": "法语"},
    "lang_es": {"ru": "Испанский", "en": "Spanish", "zh": "西班牙语"},
    "lang_it": {"ru": "Итальянский", "en": "Italian", "zh": "意大利语"},
    "lang_pt": {"ru": "Португальский", "en": "Portuguese", "zh": "葡萄牙语"},
    "lang_pl": {"ru": "Польский", "en": "Polish", "zh": "波兰语"},
    "lang_cs": {"ru": "Чешский", "en": "Czech", "zh": "捷克语"},
    "lang_ar": {"ru": "Арабский", "en": "Arabic", "zh": "阿拉伯语"},
    "lang_id": {"ru": "Индонезийский", "en": "Indonesian", "zh": "印尼语"},
    "lang_th": {"ru": "Тайский", "en": "Thai", "zh": "泰语"},
    "lang_vi": {"ru": "Вьетнамский", "en": "Vietnamese", "zh": "越南语"},
    "lang_tr": {"ru": "Турецкий", "en": "Turkish", "zh": "土耳其语"},
    "lang_nl": {"ru": "Нидерландский", "en": "Dutch", "zh": "荷兰语"},
    "lang_sv": {"ru": "Шведский", "en": "Swedish", "zh": "瑞典语"},

    "settings_show_wizard": {
        "ru": "Показать мастер настройки заново",
        "en": "Show setup wizard again", "zh": "重新显示设置向导",
    },

    # ── Setup wizard (первый запуск) ──
    "wizard_title": {"ru": "Первоначальная настройка", "en": "Initial setup", "zh": "初始设置"},
    "wizard_skip": {"ru": "Пропустить", "en": "Skip", "zh": "跳过"},
    "wizard_back": {"ru": "Назад", "en": "Back", "zh": "上一步"},
    "wizard_next": {"ru": "Далее", "en": "Next", "zh": "下一步"},
    "wizard_finish": {"ru": "Готово", "en": "Finish", "zh": "完成"},
    "wizard_step": {"ru": "Шаг {n} из {total}", "en": "Step {n} of {total}", "zh": "第 {n} 步，共 {total} 步"},
    "wizard_welcome_title": {
        "ru": "Добро пожаловать в OctopusBridge!",
        "en": "Welcome to OctopusBridge!", "zh": "欢迎使用 OctopusBridge！",
    },
    "wizard_welcome_text": {
        "ru": "Перевод игр: RPG Maker MV/MZ, Ren'Py, Twine, Tyrano. "
              "Настройки можно изменить позже.",
        "en": "Game translation: RPG Maker MV/MZ, Ren'Py, Twine, Tyrano. "
              "Settings can be changed later.", "zh": "游戏翻译：RPG Maker MV/MZ、Ren'Py、Twine、Tyrano。设置以后可以更改。",
    },
    "wizard_langs_title": {
        "ru": "Языки",
        "en": "Languages", "zh": "语言",
    },
    "wizard_langs_text": {
        "ru": "Язык интерфейса и язык перевода.",
        "en": "UI language and translation language.", "zh": "界面语言和翻译语言。",
    },
    "wizard_provider_title": {
        "ru": "Переводчик",
        "en": "Translator", "zh": "翻译器",
    },
    "wizard_provider_lbl": {
        "ru": "Провайдер перевода:",
        "en": "Translation provider:", "zh": "翻译服务商：",
    },
    "wizard_behavior_title": {
        "ru": "Поведение",
        "en": "Behavior", "zh": "行为",
    },
    "wizard_behavior_text": {
        "ru": "Значения по умолчанию. Меняются в «Настройках».",
        "en": "Defaults. Changeable in Settings.", "zh": "默认值。可在设置中更改。",
    },

    # ── Status bar ──
    "status_provider": {
        "ru": "Провайдер: {name}",
        "en": "Provider: {name}", "zh": "服务商：{name}",
    },

    # ── Providers (engines) ──
    "prov_rotate": {
        "ru": "Google + Bing — чередование (быстрее)",
        "en": "Google + Bing — round-robin (faster)", "zh": "Google + Bing —— 轮询（更快）",
    },
    "prov_short_rotate": {
        "ru": "Google + Bing (чередование)",
        "en": "Google + Bing (round-robin)", "zh": "Google + Bing（轮询）",
    },
    # ── Engine tab titles ──
    "tab_vars": {"ru": "Переменные", "en": "Variables", "zh": "变量"},
    "tab_triggers": {"ru": "Триггеры", "en": "Triggers", "zh": "触发器"},
    "tab_resources": {"ru": "Ресурсы", "en": "Resources", "zh": "资源"},
    "tab_maps": {"ru": "Карты", "en": "Maps", "zh": "地图"},
    "tab_save_editor": {"ru": "Редактор сейвов", "en": "Save Editor", "zh": "存档编辑器"},
    "tab_twine_text": {"ru": "Текст игры", "en": "Game text", "zh": "游戏文本"},

    # ── Twine game text tab ──
    "twine_text_title": {
        "ru": "Текст игры — как его читает игрок (код свёрнут в ⟦…⟧)",
        "en": "Game text — as the player reads it (code collapsed into ⟦…⟧)", "zh": "游戏文本——玩家看到的样子（代码折叠为 ⟦…⟧）",
    },
    "twine_text_refresh": {"ru": "Обновить", "en": "Refresh", "zh": "刷新"},
    "twine_text_copy": {"ru": "Копировать", "en": "Copy", "zh": "复制"},
    "twine_text_no_project": {
        "ru": "Откройте игру, чтобы увидеть её текст.",
        "en": "Open a game to see its text.", "zh": "打开游戏以查看其文本。",
    },
    "twine_text_empty": {
        "ru": "Пассажей с текстом не найдено.",
        "en": "No passages with text found.", "zh": "未找到带文本的段落。",
    },
    "twine_text_info": {"ru": "{n} пассажей", "en": "{n} passages", "zh": "{n} 个段落"},
    "twine_text_json": {
        "ru": "Сохранить JSON",
        "en": "Save JSON", "zh": "保存 JSON",
    },
    "twine_text_json_saved": {
        "ru": "JSON-модель игры сохранена:\n{path}",
        "en": "Game JSON model saved:\n{path}", "zh": "游戏 JSON 模型已保存：\n{path}",
    },

    # ── Map triggers ──
    "map_trigger_0": {"ru": "Кнопка", "en": "Button", "zh": "按钮"},
    "map_trigger_1": {"ru": "Касание игрока", "en": "Player touch", "zh": "玩家触碰"},
    "map_trigger_2": {"ru": "Касание события", "en": "Event touch", "zh": "事件触碰"},
    "map_trigger_3": {"ru": "Автозапуск", "en": "Auto-start", "zh": "自动开始"},
    "map_trigger_4": {"ru": "Параллельно", "en": "Parallel", "zh": "并行"},
    "ev_none": {"ru": "(нет)", "en": "(none)", "zh": "（无）"},
    "ev_dir_down": {"ru": "Вниз", "en": "Down", "zh": "下"},
    "ev_dir_left": {"ru": "Влево", "en": "Left", "zh": "左"},
    "ev_dir_right": {"ru": "Вправо", "en": "Right", "zh": "右"},
    "ev_dir_up": {"ru": "Вверх", "en": "Up", "zh": "上"},
    "ev_priority_0": {"ru": "Под игроком", "en": "Below player", "zh": "在玩家下方"},
    "ev_priority_1": {"ru": "На уровне игрока", "en": "Same as player", "zh": "与玩家同层"},
    "ev_priority_2": {"ru": "Над игроком", "en": "Above player", "zh": "在玩家上方"},
    "ev_move_0": {"ru": "Стоит", "en": "Fixed", "zh": "固定"},
    "ev_move_1": {"ru": "Случайно", "en": "Random", "zh": "随机"},
    "ev_move_2": {"ru": "Подход к игроку", "en": "Approach", "zh": "接近"},
    "ev_move_3": {"ru": "Свой маршрут", "en": "Custom", "zh": "自定义"},
    "ev_choice": {"ru": "Выбор {n}", "en": "Choice {n}", "zh": "选项 {n}"},
    "ev_param": {"ru": "Параметр {n}", "en": "Parameter {n}", "zh": "参数 {n}"},
    "ev_cmd_map": {
        "ru": "{name}: карта {mid} ({x},{y})",
        "en": "{name}: map {mid} ({x},{y})", "zh": "{name}：地图 {mid}（{x},{y}）",
    },
    "ev_cond_switch": {"ru": "переключатель {id}=ВКЛ", "en": "switch {id}=ON", "zh": "开关 {id}=ON"},
    "ev_cond_var": {
        "ru": "переменная {id} {op} {v}", "en": "variable {id} {op} {v}", "zh": "变量 {id} {op} {v}"},
    "ev_cond_self": {
        "ru": "self-переключатель {id}=ВКЛ", "en": "self switch {id}=ON", "zh": "独立开关 {id}=ON"},
    "ev_cond_timer": {"ru": "таймер {s}", "en": "timer {s}", "zh": "计时器 {s}"},
    "ev_cond_actor": {"ru": "актёр {id}", "en": "actor {id}", "zh": "角色 {id}"},
    "ev_cond_char": {"ru": "персонаж {id}", "en": "character {id}", "zh": "人物 {id}"},
    "ev_cond_gold": {"ru": "золото {v}", "en": "gold {v}", "zh": "金钱 {v}"},
    "ev_cond_item": {"ru": "предмет {v}", "en": "item {v}", "zh": "物品 {v}"},
    "ev_cond_button": {"ru": "кнопка {id}", "en": "button {id}", "zh": "按钮 {id}"},
    "ev_cond_script": {"ru": "скрипт: {s}", "en": "script: {s}", "zh": "脚本：{s}"},
    "ev_cond_type": {"ru": "тип {t}", "en": "type {t}", "zh": "类型 {t}"},
    "cmd_text_ph": {"ru": "Текст…", "en": "Text…", "zh": "文本…"},
    "cmd_choice_1": {"ru": "Вариант 1", "en": "Choice 1", "zh": "选项 1"},
    "cmd_cond_script": {"ru": "Скрипт:", "en": "Script:", "zh": "脚本："},
    "ev_cond_t_switch": {"ru": "Переключатель", "en": "Switch", "zh": "开关"},
    "ev_cond_t_var": {"ru": "Переменная", "en": "Variable", "zh": "变量"},
    "ev_cond_t_self": {"ru": "Self-переключатель", "en": "Self switch", "zh": "独立开关"},
    "ev_cond_t_timer": {"ru": "Таймер", "en": "Timer", "zh": "计时器"},
    "ev_cond_t_actor": {"ru": "Актёр", "en": "Actor", "zh": "角色"},
    "ev_cond_t_enemy": {"ru": "Враг", "en": "Enemy", "zh": "敌人"},
    "ev_cond_t_char": {"ru": "Персонаж", "en": "Character", "zh": "人物"},
    "ev_cond_t_gold": {"ru": "Золото", "en": "Gold", "zh": "金钱"},
    "ev_cond_t_item": {"ru": "Предмет", "en": "Item", "zh": "物品"},
    "ev_cond_t_weapon": {"ru": "Оружие", "en": "Weapon", "zh": "武器"},
    "ev_cond_t_armor": {"ru": "Броня", "en": "Armor", "zh": "防具"},
    "ev_cond_t_button": {"ru": "Кнопка", "en": "Button", "zh": "按钮"},
    "ev_cond_t_script": {"ru": "Скрипт", "en": "Script", "zh": "脚本"},
    "map_vis_always": {"ru": "всегда виден", "en": "always visible", "zh": "始终可见"},

    # ── Parser context ──
    "ctx_comment": {"ru": "комментарий", "en": "comment", "zh": "注释"},
    "ctx_dialog": {"ru": "диалог", "en": "dialog", "zh": "对话"},
    "ctx_choice": {"ru": "выбор", "en": "choice", "zh": "选项"},
    "ctx_option": {"ru": "вариант", "en": "option", "zh": "分支"},
    "ctx_speaker": {"ru": "имя говорящего", "en": "speaker name", "zh": "说话人"},
    "ctx_name_change": {"ru": "смена имени", "en": "name change", "zh": "改名"},
    "ctx_plugin": {"ru": "плагин", "en": "plugin", "zh": "插件"},
    "ctx_plugin_mv": {"ru": "плагин(MV)", "en": "plugin(MV)", "zh": "插件(MV)"},
    "ctx_map_name": {"ru": "имя карты", "en": "map name", "zh": "地图名"},
    "ctx_common_event": {"ru": "общее событие", "en": "common event", "zh": "公共事件"},
    "ctx_enemy_group": {"ru": "группа врагов", "en": "enemy group", "zh": "敌群"},
    "ctx_battle": {"ru": "бой", "en": "battle", "zh": "战斗"},
    "ctx_game_title": {"ru": "название игры", "en": "game title", "zh": "游戏标题"},
    "ctx_currency": {"ru": "валюта", "en": "currency", "zh": "货币"},
    "ctx_term": {"ru": "термин", "en": "term", "zh": "术语"},
    "ctx_variable": {"ru": "переменная", "en": "variable", "zh": "变量"},
    "ctx_switch": {"ru": "переключатель", "en": "switch", "zh": "开关"},
    "ctx_system_msg": {"ru": "сообщение системы", "en": "system message", "zh": "系统消息"},
    "ctx_map_name_list": {"ru": "имя карты (список)", "en": "map name (list)", "zh": "地图名（列表）"},

    # ── Engine errors ──
    "err_engine_unavailable": {
        "ru": "недоступен: {e}",
        "en": "unavailable: {e}", "zh": "不可用：{e}",
    },
    "err_ollama_bad_response": {
        "ru": "Ollama вернул некорректный ответ",
        "en": "Ollama returned invalid response", "zh": "Ollama 返回了无效响应",
    },
    "err_deepl_no_key": {
        "ru": "DeepL: укажите API-ключ в настройках",
        "en": "DeepL: provide API key in settings", "zh": "DeepL：请在设置中填写 API 密钥",
    },
    "err_unknown_engine": {
        "ru": "Неизвестный движок: {name}",
        "en": "Unknown engine: {name}", "zh": "未知引擎：{name}",
    },
    "err_api_bad_response": {
        "ru": "Некорректный ответ API: {e}",
        "en": "Invalid API response: {e}", "zh": "API 响应无效：{e}",
    },
    "err_api_wrong_length": {
        "ru": "API вернул ответ другой длины",
        "en": "API returned response of wrong length", "zh": "API 返回了长度错误的响应",
    },

    # ── Bridge plugin errors ──
    "err_plugins_js_not_found": {
        "ru": "plugins.js: не найден массив плагинов",
        "en": "plugins.js: plugin array not found", "zh": "plugins.js：未找到插件数组",
    },
    "err_no_js_plugins": {
        "ru": "Не найдены js/plugins или js/plugins.js — это точно RPG Maker MV/MZ?",
        "en": "js/plugins or js/plugins.js not found — is this RPG Maker MV/MZ?", "zh": "未找到 js/plugins 或 js/plugins.js——这是 RPG Maker MV/MZ 吗？",
    },
    "err_no_game_folder": {
        "ru": "Папка game/ не найдена — это точно Ren'Py?",
        "en": "game/ folder not found — is this Ren'Py?", "zh": "未找到 game/ 文件夹——这是 Ren'Py 吗？",
    },
    "err_no_fonts": {
        "ru": "Не найдены fonts/ или data/System.json",
        "en": "fonts/ or data/System.json not found", "zh": "未找到 fonts/ 或 data/System.json",
    },
    "err_no_fonts_folder": {
        "ru": "Не найдена папка fonts/ (ищется и в www/)",
        "en": "fonts/ folder not found (also checked www/)", "zh": "未找到 fonts/ 文件夹（也检查了 www/）",
    },

    # ── Save file errors ──
    "err_not_sugarcube_lz": {
        "ru": "Не SugarCube-сейв (LZ-String не раскодировался)",
        "en": "Not a SugarCube save (LZ-String decode failed)", "zh": "不是 SugarCube 存档（LZ-String 解码失败）",
    },
    "err_not_sugarcube_state": {
        "ru": "Не SugarCube-сейв (нет state)",
        "en": "Not a SugarCube save (no state)", "zh": "不是 SugarCube 存档（无状态）",
    },
    "err_no_active_moment": {
        "ru": "В сейве нет активного момента",
        "en": "No active moment in save", "zh": "存档中无活动 moment",
    },

    # ── Crypto errors ──
    "err_not_encrypted": {
        "ru": "Не зашифрованный RPGM-файл (сигнатура не совпала)",
        "en": "Not an encrypted RPGM file (signature mismatch)", "zh": "不是加密的 RPGM 文件（签名不匹配）",
    },

    # ── Resource tab ──
    "res_size_kb": {
        "ru": "{size} КБ",
        "en": "{size} KB", "zh": "{size} KB",
    },

    # ── Welcome ──
    "welcome_settings_tooltip": {"ru": "Настройки", "en": "Settings", "zh": "设置"},

    # ── Bridge log ──
    "bridge_listening": {
        "ru": "Сервер LiveBridge слушает 127.0.0.1:{port}",
        "en": "LiveBridge server listening on 127.0.0.1:{port}", "zh": "LiveBridge 服务器监听于 127.0.0.1:{port}",
    },
    "bridge_start_failed": {
        "ru": "Сервер не запустился: {e}",
        "en": "Server failed to start: {e}", "zh": "服务器启动失败：{e}",
    },
    "bridge_client_connected": {
        "ru": "Игра подключилась",
        "en": "Game connected", "zh": "游戏已连接",
    },
    "bridge_client_disconnected": {
        "ru": "Игра отключилась",
        "en": "Game disconnected", "zh": "游戏已断开",
    },
    "bridge_translate_error": {
        "ru": "Ошибка перевода: {e}",
        "en": "Translation error: {e}", "zh": "翻译错误：{e}",
    },
    "bridge_no_client": {
        "ru": "Игра не подключена — команда не отправлена",
        "en": "Game not connected — command not sent", "zh": "游戏未连接——命令未发送",
    },
    "bridge_send_failed": {
        "ru": "Отправка не удалась: {e}",
        "en": "Send failed: {e}", "zh": "发送失败：{e}",
    },

    # ── Check provider hint fallback ──
    "hint_check_provider": {
        "ru": "Проверьте, что движок запущен.",
        "en": "Check that the engine is running.", "zh": "请检查引擎是否运行。",
    },

    # ── Glossary ──
    "glossary_title": {"ru": "Глоссарий", "en": "Glossary", "zh": "术语表"},
    "glossary_src": {"ru": "Источник:", "en": "Source:", "zh": "原文："},
    "glossary_tgt": {"ru": "Перевод:", "en": "Target:", "zh": "译文："},
    "glossary_search": {"ru": "Поиск по терминам…", "en": "Search terms…", "zh": "搜索术语…"},
    "glossary_count": {
        "ru": "Показано: {shown} из {total}",
        "en": "Showing {shown} of {total}", "zh": "显示 {shown}/{total}",
    },
    "glossary_lang_ja": {"ru": "Японский", "en": "Japanese", "zh": "日语"},
    "glossary_lang_zh": {"ru": "Китайский", "en": "Chinese", "zh": "中文"},
    "glossary_lang_en": {"ru": "Английский", "en": "English", "zh": "英语"},
    "glossary_lang_ru": {"ru": "Русский", "en": "Russian", "zh": "俄语"},
    "glossary_add": {"ru": "Добавить", "en": "Add", "zh": "添加"},
    "glossary_edit": {"ru": "Изменить", "en": "Edit", "zh": "编辑"},
    "glossary_del": {"ru": "Удалить", "en": "Delete", "zh": "删除"},
    "glossary_save": {"ru": "Сохранить", "en": "Save", "zh": "保存"},
    "glossary_hint": {
        "ru": "Термины подставляются как есть. "
              "Двойной клик — редактировать.",
        "en": "Terms are inserted as-is. "
              "Double-click to edit.", "zh": "术语按原样插入。双击编辑。",
    },
    "glossary_col_orig": {"ru": "Термин", "en": "Term", "zh": "术语"},
    "glossary_col_tr": {"ru": "Перевод", "en": "Translation", "zh": "译文"},
    "glossary_col_group": {"ru": "Категория", "en": "Category", "zh": "分类"},
    "glossary_group_all": {"ru": "Все категории", "en": "All categories", "zh": "全部分类"},
    "glossary_group_none": {"ru": "(без категории)", "en": "(no category)", "zh": "（无分类）"},
    "glossary_edit_title": {"ru": "Термин глоссария", "en": "Glossary term", "zh": "术语表条目"},
    "glossary_term": {"ru": "Термин:", "en": "Term:", "zh": "术语："},
    "glossary_term_tr": {"ru": "Перевод:", "en": "Translation:", "zh": "译文："},
    "glossary_term_group": {"ru": "Категория:", "en": "Category:", "zh": "分类："},
    "tr_gloss_bar": {"ru": "Глоссарий:", "en": "Glossary:", "zh": "术语表："},
    "tr_gloss_chip_tip": {
        "ru": "Вставить перевод термина в ячейку перевода",
        "en": "Insert the term's translation into the translation cell", "zh": "将该术语的译文插入译文格",
    },
    # ── Map tab (H1) ──
    "map_list": {"ru": "Карты", "en": "Maps", "zh": "地图"},
    "map_search_ph": {"ru": "имя или id карты…", "en": "map name or id…", "zh": "地图名或编号…"},
    "map_elements": {"ru": "Элементы (события)", "en": "Elements (events)", "zh": "元素（事件）"},
    "map_props": {"ru": "Свойства элемента", "en": "Element properties", "zh": "元素属性"},
    "map_name": {"ru": "Имя:", "en": "Name:", "zh": "名称："},
    "map_pos": {"ru": "Позиция:", "en": "Position:", "zh": "位置："},
    "map_page": {"ru": "Страница:", "en": "Page:", "zh": "页："},
    "map_trigger": {"ru": "Триггер:", "en": "Trigger:", "zh": "触发："},
    "map_visibility": {"ru": "Видимость:", "en": "Visibility:", "zh": "可见性："},
    "map_sw1": {"ru": "Переключатель 1", "en": "Switch 1", "zh": "开关 1"},
    "map_sw2": {"ru": "Переключатель 2", "en": "Switch 2", "zh": "开关 2"},
    "map_vis_now": {"ru": "Условие", "en": "Condition", "zh": "条件"},
    "map_cond_switch": {
        "ru": "Переключатель {id}=ВКЛ",
        "en": "Switch {id}=ON", "zh": "开关 {id}=ON",
    },
    "map_cond_variable": {
        "ru": "Переменная {id} {op} {value}",
        "en": "Variable {id} {op} {value}", "zh": "变量 {id} {op} {value}",
    },
    "map_cond_self": {
        "ru": "Переключатель события {id}=ВКЛ",
        "en": "Event switch {id}=ON", "zh": "事件开关 {id}=ON",
    },
    "map_cond_item": {
        "ru": "В инвентаре есть предмет #{id}",
        "en": "Inventory contains item #{id}", "zh": "背包中有物品 #{id}",
    },
    "map_cond_actor": {
        "ru": "В группе есть герой #{id}",
        "en": "Party contains actor #{id}", "zh": "队伍中有角色 #{id}",
    },
    "map_cond_timer": {
        "ru": "Таймер ≥ {value} сек.",
        "en": "Timer ≥ {value} sec", "zh": "计时器 ≥ {value} 秒",
    },
    "map_cond_turn": {
        "ru": "Условие направления #{id}",
        "en": "Direction condition #{id}", "zh": "朝向条件 #{id}",
    },
    "map_cond_area": {
        "ru": "Область #{id}",
        "en": "Area #{id}", "zh": "区域 #{id}",
    },
    "map_zoom": {"ru": "Масштаб:", "en": "Zoom:", "zh": "缩放："},
    "map_none": {
        "ru": "Выберите карту слева",
        "en": "Select a map on the left", "zh": "请在左侧选择地图",
    },
    "map_info": {
        "ru": "Карта {id}: {w}×{h} {name}",
        "en": "Map {id}: {w}×{h} {name}", "zh": "地图 {id}：{w}×{h} {name}",
    },
    "map_save": {"ru": "Сохранить карту в игру", "en": "Save map to game", "zh": "保存地图到游戏"},
    "map_rendering": {
        "ru": "Отрисовка карты…",
        "en": "Rendering map…", "zh": "正在渲染地图…",
    },
    "map_saved": {
        "ru": "Карта сохранена ({path}). Оригинал — в .ob_backup.",
        "en": "Map saved ({path}). Original in .ob_backup.", "zh": "地图已保存（{path}）。原文件在 .ob_backup 中。",
    },
    "map_discard": {
        "ru": "Есть несохранённые правки. Открыть другую карту и потерять их?",
        "en": "Unsaved changes. Open another map and discard them?", "zh": "有未保存的更改。打开另一张地图并放弃它们？",
    },
    "map_tp": {"ru": "Телепорт (live)", "en": "Teleport (live)", "zh": "传送（实时）"},
    "map_tp_go": {"ru": "Телепорт на эту карту", "en": "Teleport to this map", "zh": "传送到该地图"},
    "map_tp_event": {
        "ru": "Телепорт к событию",
        "en": "Teleport to event", "zh": "传送到事件",
    },
    "map_player_map": {
        "ru": "Текущая карта игрока: #{map_id} ({x}, {y})",
        "en": "Player current map: #{map_id} ({x}, {y})", "zh": "玩家当前地图：#{map_id}（{x}, {y}）",
    },
    "map_ctx_teleport": {
        "ru": "Переместить игрока сюда",
        "en": "Move player here", "zh": "将玩家移到这里",
    },
    "map_ctx_teleport_here": {
        "ru": "Переместить игрока сюда",
        "en": "Move player here", "zh": "将玩家移到这里",
    },
    "map_cell_selected": {
        "ru": "Выбрана клетка ({x}, {y})",
        "en": "Selected cell ({x}, {y})", "zh": "已选格子（{x}, {y}）",
    },
    "map_tp_done": {
        "ru": "Телепорт: карта #{map_id} ({x}, {y}) — выполнено",
        "en": "Teleport: map #{map_id} ({x}, {y}) — done", "zh": "传送：地图 #{map_id}（{x}, {y}）——完成",
    },
    "map_tp_fail": {
        "ru": "Телепорт не удался: {error}",
        "en": "Teleport failed: {error}", "zh": "传送失败：{error}",
    },
    "map_saved_live": {
        "ru": "Игра перезагрузила карту — изменения уже в игре",
        "en": "Game reloaded the map — changes are live", "zh": "游戏已重载地图——更改即时生效",
    },
    "map_saved_file": {
        "ru": "Игра не подключена — перезайдите на карту в игре "
              "(выйти/зайти или телепорт)",
        "en": "Game not connected — re-enter the map in game", "zh": "游戏未连接——请在游戏中重进地图",
    },
    "ev_mode_simple": {
        "ru": "Быстрый просмотр",
        "en": "Quick view", "zh": "快速查看",
    },
    "ev_close": {"ru": "Закрыть", "en": "Close", "zh": "关闭"},
    "ev_mode_expanded": {
        "ru": "Полный редактор",
        "en": "Full editor", "zh": "完整编辑器",
    },
    "ev_make_visible": {
        "ru": "Подготовить условия",
        "en": "Prepare conditions", "zh": "准备条件",
    },
    "ev_live_run": {
        "ru": "Запустить сценарий сейчас",
        "en": "Run scenario now", "zh": "立即运行剧情",
    },
    "ev_live_title": {
        "ru": "Состояние в запущенной игре",
        "en": "State in the running game", "zh": "运行中游戏的状态",
    },
    "ev_live_current_map": {
        "ru": "Карта игрока: #{id}",
        "en": "Player map: #{id}", "zh": "玩家地图：#{id}",
    },
    "ev_live_map_unknown": {
        "ru": "Состояние игры ещё не получено",
        "en": "Game state has not been received yet", "zh": "尚未收到游戏状态",
    },
    "ev_live_switch": {
        "ru": "Переключатель #{id}{name}",
        "en": "Switch #{id}{name}", "zh": "开关 #{id}{name}",
    },
    "ev_live_variable": {
        "ru": "Переменная #{id} {op} {value}",
        "en": "Variable #{id} {op} {value}", "zh": "变量 #{id} {op} {value}",
    },
    "ev_live_self": {
        "ru": "Переключатель события {id}",
        "en": "Event switch {id}", "zh": "事件开关 {id}",
    },
    "ev_live_item": {
        "ru": "Нужен предмет #{id}",
        "en": "Required item #{id}", "zh": "需要物品 #{id}",
    },
    "ev_live_item_named": {
        "ru": "Нужен предмет: {name} (#{id})",
        "en": "Required item: {name} (#{id})", "zh": "需要物品：{name}（#{id}）",
    },
    "ev_live_give_item": {
        "ru": "Выдать 1",
        "en": "Give 1", "zh": "给予 1 个",
    },
    "ev_live_actor": {
        "ru": "Нужен герой #{id}",
        "en": "Required actor #{id}", "zh": "需要角色 #{id}",
    },
    "ev_live_actor_named": {
        "ru": "Нужен герой: {name} (#{id})",
        "en": "Required actor: {name} (#{id})", "zh": "需要角色：{name}（#{id}）",
    },
    "ev_live_join_actor": {
        "ru": "Добавить в группу",
        "en": "Add to party", "zh": "加入队伍",
    },
    "ev_live_set_value": {
        "ru": "Установить",
        "en": "Set", "zh": "设置",
    },
    "ev_live_now": {
        "ru": "Сейчас: {value}",
        "en": "Now: {value}", "zh": "当前：{value}",
    },
    "ev_live_on": {"ru": "ВКЛ", "en": "ON", "zh": "开"},
    "ev_live_off": {"ru": "ВЫКЛ", "en": "OFF", "zh": "关"},
    "ev_live_yes": {"ru": "ДА", "en": "YES", "zh": "是"},
    "ev_live_no": {"ru": "НЕТ", "en": "NO", "zh": "否"},
    "ev_live_no_supported": {
        "ru": "Для этой страницы нет условий, которые можно подготовить.",
        "en": "This page has no conditions that can be prepared.", "zh": "此页没有可准备的条件。",
    },
    "ev_live_bypass": {
        "ru": "Условие можно обойти кнопкой «Запустить сценарий сейчас».",
        "en": "You can bypass the condition with “Run scenario now”.", "zh": "可用“立即运行剧情”绕过条件。",
    },
    "ev_visible_sent": {
        "ru": "Условия отправлены в игру",
        "en": "Conditions sent to the game", "zh": "条件已发送到游戏",
    },
    "ev_live_prepared": {
        "ru": "Условия выполнены",
        "en": "Conditions prepared", "zh": "条件已准备",
    },
    "ev_live_run_started": {
        "ru": "Сценарий события запущен",
        "en": "Event scenario started", "zh": "事件剧情已开始",
    },
    "ev_live_run_attached": {
        "ru": "Сценарий добавлен после текущего события",
        "en": "Scenario queued after the current event", "zh": "剧情已排队，将在当前事件后执行",
    },
    "ev_live_battle": {
        "ru": "Сначала закончите текущий бой",
        "en": "Finish the current battle first", "zh": "请先结束当前战斗",
    },
    "ev_live_not_map": {
        "ru": "Вернитесь на экран карты, затем запустите сценарий",
        "en": "Return to the map screen before running the scenario", "zh": "运行剧情前请回到地图画面",
    },
    "ev_live_page_missing": {
        "ru": "Выбранная страница события не найдена в игре",
        "en": "The selected event page was not found in the game", "zh": "在游戏中未找到所选事件页",
    },
    "ev_live_event_missing": {
        "ru": "Событие не найдено в загруженной карте",
        "en": "The event was not found in the loaded map", "zh": "在已加载地图中未找到该事件",
    },
    "ev_live_run_inactive": {
        "ru": "Игрок находится на другой карте. Сначала переместите его сюда.",
        "en": "The player is on another map. Move the player here first.", "zh": "玩家在另一张地图。请先将玩家移到这里。",
    },
    "ev_live_run_busy": {
        "ru": "Это событие уже выполняется",
        "en": "This event is already running", "zh": "该事件已在运行",
    },
    "ev_live_run_empty": {
        "ru": "У выбранной страницы нет команд",
        "en": "The selected page has no commands", "zh": "所选页面没有命令",
    },
    "ev_live_interpreter_unsupported": {
        "ru": "Эта версия RPG Maker не поддерживает такой запуск события",
        "en": "This RPG Maker version cannot run the event this way", "zh": "此 RPG Maker 版本无法以这种方式运行事件",
    },
    "ev_live_interpreter_busy": {
        "ru": "Слишком глубокая цепочка событий; повторите после завершения",
        "en": "The event chain is too deep; try again after it finishes", "zh": "事件链太深；等它结束后再试",
    },
    "ev_live_interpreter_failed": {
        "ru": "Не удалось настроить интерпретатор события",
        "en": "Failed to prepare the event interpreter", "zh": "无法准备事件解释器",
    },
    "ev_live_run_failed": {
        "ru": "Не удалось запустить сценарий: {error}",
        "en": "Failed to run the scenario: {error}", "zh": "运行剧情失败：{error}",
    },
    "ev_run_warn": {
        "ru": "Сценарий может сразу начать другую сцену, перенести игрока "
              "или открыть меню. Запустить?",
        "en": "The scenario may immediately start another scene, transfer "
              "the player, or open a menu. Run it?", "zh": "剧情可能立即切换场景、传送玩家或打开菜单。运行吗？",
    },
    "ev_undo": {
        "ru": "Вернуть исходные значения",
        "en": "Restore original values", "zh": "恢复原始值",
    },
    "ev_undone": {
        "ru": "Исходные значения восстановлены",
        "en": "Original values restored", "zh": "已恢复原始值",
    },
    "ev_nothing_to_restore": {
        "ru": "В этом диалоге ещё нечего восстанавливать",
        "en": "There are no original values to restore yet", "zh": "尚无可恢复的原始值",
    },
    "ev_autorun_warn": {
        "ru": "Условие может сразу запустить сценарий. Продолжить?",
        "en": "This condition may start the scenario immediately. Continue?", "zh": "此条件可能立即启动剧情。继续？",
    },
    "ev_live_no_channel": {
        "ru": "Запустите игру через приложение, чтобы применять изменения сразу.",
        "en": "Launch the game via the app to apply changes immediately.", "zh": "请通过本应用启动游戏以即时应用更改。",
    },
    "ev_live_no_cond": {
        "ru": "Событие видно всегда",
        "en": "The event is always visible", "zh": "该事件始终可见",
    },
    "ev_live_ok": {
        "ru": "Изменение применено",
        "en": "Change applied", "zh": "更改已应用",
    },
    "ev_live_err": {
        "ru": "Ошибка: {error}",
        "en": "Error: {error}", "zh": "错误：{error}",
    },
    "ev_live_ack_timeout": {
        "ru": "Игра не подтвердила команду за 15 с — блокировка снята, "
              "повторите или перезапустите игру",
        "en": "The game did not acknowledge the command within 15 s — "
              "lock released, retry or relaunch the game", "zh": "游戏 15 秒内未确认命令——锁定已释放，请重试或重启游戏",
    },
    "map_ctx_edit": {
        "ru": "Открыть событие",
        "en": "Open event", "zh": "打开事件",
    },
    "map_ctx_toggle_sw": {
        "ru": "Включить переключатель #{id}",
        "en": "Turn on switch #{id}", "zh": "打开开关 #{id}",
    },
    "map_ctx_dup": {
        "ru": "Дублировать событие",
        "en": "Duplicate event", "zh": "复制事件",
    },
    "map_ctx_del": {
        "ru": "Удалить событие",
        "en": "Delete event", "zh": "删除事件",
    },
    "map_ctx_del_q": {
        "ru": "Удалить событие «{name}»?",
        "en": "Delete event \"{name}\"?", "zh": "删除事件“{name}”？",
    },
    "map_ctx_new_event": {
        "ru": "Новое событие",
        "en": "New event", "zh": "新事件",
    },
    "ev_new_name": {
        "ru": "Событие #{id}",
        "en": "Event #{id}", "zh": "事件 #{id}",
    },
    "ev_pages": {"ru": "Страницы:", "en": "Pages:", "zh": "页："},
    "ev_add_page": {"ru": "+ Страница", "en": "+ Page", "zh": "+ 页"},
    "ev_dup_page": {"ru": "Дублировать", "en": "Duplicate", "zh": "复制"},
    "ev_del_page": {"ru": "Удалить", "en": "Delete", "zh": "删除"},
    "ev_no_del": {
        "ru": "Нельзя удалить единственную страницу",
        "en": "Cannot delete the only page", "zh": "无法删除唯一的页面",
    },
    "ev_image": {"ru": "Изображение:", "en": "Image:", "zh": "图像："},
    "ev_image_opt": {"ru": "Вариант/напр./паттерн:", "en": "Index/dir/pattern:", "zh": "索引/方向/样式："},
    "ev_tile": {"ru": "Тайл события (ID):", "en": "Event tile (ID):", "zh": "事件图块（ID）："},
    "ev_trigger": {"ru": "Триггер:", "en": "Trigger:", "zh": "触发："},
    "ev_priority": {"ru": "Приоритет:", "en": "Priority:", "zh": "优先级："},
    "ev_move": {"ru": "Движение:", "en": "Movement:", "zh": "移动："},
    "ev_speed": {"ru": "Скорость:", "en": "Speed:", "zh": "速度："},
    "ev_freq": {"ru": "Частота:", "en": "Frequency:", "zh": "频率："},
    "ev_options": {"ru": "Опции:", "en": "Options:", "zh": "选项："},
    "ev_walk_anime": {"ru": "Анимация ходьбы", "en": "Walk animation", "zh": "行走动画"},
    "ev_step_anime": {"ru": "Анимация шага", "en": "Step animation", "zh": "踏步动画"},
    "ev_dir_fix": {"ru": "Фикс. направление", "en": "Direction fix", "zh": "固定朝向"},
    "ev_through": {"ru": "Сквозной", "en": "Through", "zh": "穿透"},
    "ev_conditions": {"ru": "Условия видимости:", "en": "Visibility:", "zh": "可见性："},
    "ev_sw1": {"ru": "Переключатель 1:", "en": "Switch 1:", "zh": "开关 1："},
    "ev_sw2": {"ru": "Переключатель 2:", "en": "Switch 2:", "zh": "开关 2："},
    "ev_var": {"ru": "Переменная:", "en": "Variable:", "zh": "变量："},
    "ev_self": {"ru": "Self-переключатель:", "en": "Self switch:", "zh": "独立开关："},
    "cmd_add": {"ru": "Добавить", "en": "Add", "zh": "添加"},
    "cmd_edit": {"ru": "Изменить", "en": "Edit", "zh": "编辑"},
    "cmd_del": {"ru": "Удалить", "en": "Delete", "zh": "删除"},
    "cmd_up": {"ru": "Вверх", "en": "Up", "zh": "上移"},
    "cmd_down": {"ru": "Вниз", "en": "Down", "zh": "下移"},
    "cmd_no_params": {
        "ru": "У этой команды нет параметров.",
        "en": "This command has no parameters.", "zh": "此命令没有参数。",
    },
    "cmd_text": {"ru": "Текст сообщения", "en": "Message text", "zh": "消息文本"},
    "cmd_choices": {"ru": "Варианты выбора", "en": "Choices", "zh": "选项"},
    "cmd_cancel": {"ru": "Отмена → (0-4, 4=запретить):", "en": "Cancel (0-4, 4=forbid):", "zh": "取消（0-4，4=禁止）："},
    "cmd_default": {"ru": "Выбор по умолчанию:", "en": "Default choice:", "zh": "默认选项："},
    "cmd_position": {"ru": "Позиция (0-2, 2=центр):", "en": "Position (0-2, 2=center):", "zh": "位置（0-2，2=居中）："},
    "cmd_choice_new": {"ru": "Вариант", "en": "Choice", "zh": "选项"},
    "cmd_cond": {"ru": "Условие", "en": "Condition", "zh": "条件"},
    "cmd_cond_type": {"ru": "Тип:", "en": "Type:", "zh": "类型："},
    "cmd_cond_p1": {"ru": "Параметр 1:", "en": "Parameter 1:", "zh": "参数 1："},
    "cmd_cond_op": {"ru": "Операция:", "en": "Operation:", "zh": "操作："},
    "cmd_cond_p2": {"ru": "Параметр 2:", "en": "Parameter 2:", "zh": "参数 2："},
    "cmd_route": {"ru": "Маршрут движения", "en": "Movement route", "zh": "移动路线"},
    "cmd_route_char": {"ru": "Персонаж (0=это, 1=игрок):", "en": "Character (0=this, 1=player):", "zh": "角色（0=本事件，1=玩家）："},
    "cmd_new_page_comment": {
        "ru": "// Новая страница",
        "en": "// New page", "zh": "// 新页面",
    },

    "vars_from_save": {"ru": "Из .save файла…", "en": "From .save file…", "zh": "从 .save 文件…"},
    "vars_save_loaded": {
        "ru": "Сейв {path}: {n} переменных (правки пишутся в файл)",
        "en": "Save {path}: {n} variables (edits write to file)", "zh": "存档 {path}：{n} 个变量（编辑将写入文件）",
    },
    "vars_saved": {
        "ru": "{name} = {value} — записано в сейв",
        "en": "{name} = {value} — written to save", "zh": "{name} = {value} —— 已写入存档",
    },
    "vars_console": {
        "ru": "Консоль (Python/JS в игре):",
        "en": "Console (Python/JS in game):", "zh": "控制台（游戏内 Python/JS）：",
    },

    # ── Save editor (H4) ──
    "save_load": {"ru": "Загрузить…", "en": "Load…", "zh": "加载…"},
    "save_drop_ph": {
        "ru": "Перетащите .save сюда\nили нажмите «Загрузить…»",
        "en": "Drop .save here\nor press \"Load…\"", "zh": "将 .save 拖到此处\n或按“加载…”",
    },
    "save_wait_drop": {
        "ru": "Перетащите .save — «Применить» перезапишет этот файл",
        "en": "Drop a .save — \"Apply\" will overwrite that file", "zh": "拖入 .save —— “应用”将覆盖该文件",
    },
    "save_apply_hint": {
        "ru": "«Применить» пишет в файл (оригинал — *.ob_backup). "
              "Игра файл сама не подхватит — загрузите слот в меню игры.",
        "en": "\"Apply\" writes the file (original kept as *.ob_backup). "
              "The game won't pick it up by itself — load the slot in the game menu.", "zh": "“应用”写入文件（原文件保留为 *.ob_backup）。游戏不会自己读取——请在游戏菜单中读取该槽位。",
    },
    "save_saved": {
        "ru": "Сохранено: {name} ({n} параметров)",
        "en": "Saved: {name} ({n} parameters)", "zh": "已保存：{name}（{n} 个参数）",
    },
    "save_browse_tip": {
        "ru": "Выбрать .save вручную",
        "en": "Pick a .save manually", "zh": "手动选择 .save",
    },
    "sv_search_ph": {"ru": "имя или значение…", "en": "name or value…", "zh": "名称或数值…"},
    "sv_open_title": {"ru": "Выберите .save", "en": "Pick a .save file", "zh": "选择 .save 文件"},
    "sv_params": {
        "ru": "{name} — {n} параметров",
        "en": "{name} — {n} variables", "zh": "{name} —— {n} 个变量",
    },
    "sv_unsaved": {
        "ru": "{name} = {value} (не сохранено)",
        "en": "{name} = {value} (not saved)", "zh": "{name} = {value}（未保存）",
    },
    "sv_save_err": {"ru": "Ошибка сохранения", "en": "Save error", "zh": "保存错误"},
    "sv_save_verify_fail": {
        "ru": "Записанный сейв не прошёл самопроверку ({n} значений "
              "не сошлись) — файл возвращён из бэкапа, игра не тронута.",
        "en": "Written save failed self-check ({n} mismatched values) — "
              "file restored from backup, game untouched.", "zh": "写入的存档自检失败（{n} 个值不匹配）——文件已从备份恢复，游戏未改动。",
    },

    # ── Resource tab (H2) ──
    "res_select": {
        "ru": "Выберите файл слева",
        "en": "Select a file on the left", "zh": "请在左侧选择文件",
    },
    "res_search_ph": {"ru": "имя файла…", "en": "file name…", "zh": "文件名…"},
    "res_filter_all": {"ru": "Все файлы", "en": "All files", "zh": "所有文件"},
    "res_filter_img": {"ru": "Картинки", "en": "Images", "zh": "图片"},
    "res_filter_audio": {"ru": "Аудио", "en": "Audio", "zh": "音频"},
    "res_filter_video": {"ru": "Видео", "en": "Videos", "zh": "视频"},
    "res_filter_animated": {"ru": "GIF", "en": "GIF", "zh": "GIF"},
    "res_refresh": {"ru": "Обновить список", "en": "Refresh list", "zh": "刷新列表"},
    "res_loading": {"ru": "Загрузка…", "en": "Loading…", "zh": "加载中…"},
    "res_found": {"ru": "Показано: {count} из {total}", "en": "Showing: {count} of {total}", "zh": "显示：{count}/{total}"},
    "res_fit": {"ru": "Вписать", "en": "Fit", "zh": "适应"},
    "res_scan_fail": {"ru": "Не удалось просканировать ресурсы", "en": "Failed to scan resources", "zh": "扫描资源失败"},
    "res_read_fail": {"ru": "не удалось прочитать файл", "en": "failed to read file", "zh": "读取文件失败"},
    "res_ctx_save_resource": {"ru": "Сохранить ресурс…", "en": "Save resource…", "zh": "保存资源…"},
    "res_saved": {"ru": "Сохранено: {path}", "en": "Saved: {path}", "zh": "已保存：{path}"},
    "res_back": {"ru": "Назад к папкам", "en": "Back to folders", "zh": "返回文件夹"},
    "res_font": {
        "ru": "Установить шрифт с кириллицей…",
        "en": "Install Cyrillic font…", "zh": "安装西里尔字体…",
    },
    "res_font_done": {
        "ru": "Шрифт {font} прописан в игре. Оригиналы — *.ob_backup.{live}",
        "en": "Font {font} registered. Originals in *.ob_backup.{live}", "zh": "字体 {font} 已注册。原文件在 *.ob_backup 中。{live}",
    },
    "res_no_key": {"ru": "ключ шифрования не найден", "en": "no encryption key", "zh": "无加密密钥"},
    "res_empty": {"ru": "файл пуст или не найден", "en": "file empty or missing", "zh": "文件为空或缺失"},
    "res_decode_fail": {
        "ru": "не удалось декодировать изображение",
        "en": "failed to decode image", "zh": "图片解码失败",
    },
    "res_ctx_save": {
        "ru": "Сохранить как…",
        "en": "Save as…", "zh": "另存为…",
    },
    "res_ctx_save_audio": {
        "ru": "Сохранить аудио…",
        "en": "Save audio…", "zh": "保存音频…",
    },
    "res_audio_fail": {
        "ru": "Не удалось конвертировать аудио",
        "en": "Failed to convert audio", "zh": "音频转换失败",
    },
    "res_no_ffmpeg": {
        "ru": "ffmpeg не найден. Установите ffmpeg и добавьте в PATH",
        "en": "ffmpeg not found. Install ffmpeg and add to PATH", "zh": "未找到 ffmpeg。请安装 ffmpeg 并加入 PATH",
    },
    "res_ctx_save_video": {
        "ru": "Сохранить видео…",
        "en": "Save video…", "zh": "保存视频…",
    },
    "res_video_fail": {
        "ru": "Не удалось воспроизвести видео",
        "en": "Failed to play video", "zh": "视频播放失败",
    },
    "res_font_restore": {
        "ru": "Откатить шрифт",
        "en": "Restore font", "zh": "恢复字体",
    },
    "res_font_choose": {
        "ru": "Загрузить свой шрифт…",
        "en": "Load own font…", "zh": "加载自己的字体…",
    },
    "res_font_nothing": {
        "ru": "Нечего откатывать — шрифт не менялся",
        "en": "Nothing to restore — font was not patched", "zh": "无需恢复——字体未被修改",
    },
    "res_font_done_renpy": {
        "ru": "Шрифтов: {n}. Оригиналы — game/ob_fonts_orig.{live}",
        "en": "Fonts: {n}. Originals in game/ob_fonts_orig.{live}", "zh": "字体：{n} 个。原文件在 game/ob_fonts_orig 中。{live}",
    },
    "res_font_done_unity": {
        "ru": "Шрифтов: {n} в {files} файлах. Оригиналы — backup/unity.",
        "en": "Fonts: {n} in {files} files. Originals in backup/unity.", "zh": "字体：{n} 个，位于 {files} 个文件。原文件在 backup/unity 中。",
    },
    "res_font_already": {
        "ru": "Все шрифты игры уже поддерживают кириллицу",
        "en": "All game fonts already support Cyrillic", "zh": "游戏字体已全部支持西里尔字母",
    },
    "res_font_restored": {
        "ru": "Оригинальные шрифты восстановлены",
        "en": "Original fonts restored", "zh": "已恢复原始字体",
    },

    # ── Unity: читы через PlayerPrefs (реестр, без канала в процесс) ──
    # ── Unity: единый список переменных (игра + сейвы + реестр) ──
    "unity_col_src": {
        "ru": "Где",
        "en": "Where", "zh": "位置",
    },
    "unity_cheats_written": {
        "ru": "Записано: {name}",
        "en": "Written: {name}", "zh": "已写入：{name}",
    },
    "unity_cheats_restore_q": {
        "ru": "Вернуть значения из автобэкапов? Правки будут потеряны.",
        "en": "Restore values from auto-backups? Edits will be lost.", "zh": "从自动备份恢复数值？编辑将丢失。",
    },
    "unity_cheats_restored_errors": {
        "ru": "Восстановлено: {n}. Не вышло:\n{problems}",
        "en": "Restored: {n}. Failed:\n{problems}", "zh": "已恢复：{n}。失败：\n{problems}",
    },
    "unity_live_not_written": {
        "ru": "Игра не приняла запись.",
        "en": "The game rejected the write.", "zh": "游戏拒绝了写入。",
    },
    "unity_prefs_name": {
        "ru": "Ключ",
        "en": "Key", "zh": "键",
    },
    "unity_prefs_kind": {
        "ru": "Тип",
        "en": "Type", "zh": "类型",
    },
    "unity_prefs_value": {
        "ru": "Значение (можно править)",
        "en": "Value (editable)", "zh": "数值（可编辑）",
    },
    "unity_prefs_show_system": {
        "ru": "Служебные",
        "en": "System", "zh": "系统",
    },
    "unity_prefs_reload": {
        "ru": "Обновить",
        "en": "Reload", "zh": "重新加载",
    },
    "unity_prefs_backup": {
        "ru": "Сохранить копию",
        "en": "Back up", "zh": "备份",
    },
    "unity_prefs_restore": {
        "ru": "Восстановить",
        "en": "Restore", "zh": "恢复",
    },
    "unity_prefs_backup_done": {
        "ru": "Сохранено {n} ключей в {path}",
        "en": "Saved {n} keys to {path}", "zh": "已保存 {n} 个键到 {path}",
    },
    "unity_prefs_restored": {
        "ru": "Восстановлено ключей: {n}",
        "en": "Restored keys: {n}", "zh": "已恢复键：{n}",
    },
    "tab_unity_saves": {
        "ru": "Сейвы",
        "en": "Saves", "zh": "存档",
    },
    "unity_live_empty": {
        "ru": "Запустите игру из дашборда, затем «Обновить».",
        "en": "Launch the game from the dashboard, then press Reload.", "zh": "请从面板启动游戏，然后按重新加载。",
    },
    "unity_live_no_game": {
        "ru": "Игра не запущена через это приложение (или ещё не "
              "записала данные). Запустите её здесь.",
        "en": "The game was not launched by this app (or has not written "
              "any data yet). Launch it here.", "zh": "游戏不是由本应用启动的（或尚未写入数据）。请在这里启动。",
    },
    "unity_live_class": {
        "ru": "Класс",
        "en": "Class", "zh": "类",
    },
    "unity_live_field": {
        "ru": "Поле",
        "en": "Field", "zh": "字段",
    },
    "unity_live_type": {
        "ru": "Тип",
        "en": "Type", "zh": "类型",
    },
    "unity_live_value": {
        "ru": "Значение",
        "en": "Value", "zh": "数值",
    },
    "unity_live_count": {
        "ru": "Переменных: {n}",
        "en": "Variables: {n}", "zh": "变量：{n}",
    },
    "unity_live_written": {
        "ru": "Записано: {field}",
        "en": "Written: {field}", "zh": "已写入：{field}",
    },
    "unity_live_not_written": {
        "ru": "Игра не приняла запись.",
        "en": "The game rejected the write.", "zh": "游戏拒绝了写入。",
    },
    "unity_live_game_only": {
        "ru": "Только сборка игры",
        "en": "Game assembly only", "zh": "仅游戏程序集",
    },
    "unity_live_scope_safe": {
        "ru": "Безопасные",
        "en": "Safe", "zh": "安全",
    },
    "unity_live_scope_game": {
        "ru": "Вся сборка игры",
        "en": "Whole game assembly", "zh": "整个游戏程序集",
    },
    "unity_live_scope_all": {
        "ru": "Все сборки",
        "en": "All assemblies", "zh": "所有程序集",
    },
    "unity_live_shown": {
        "ru": "Показано {n} из {total}",
        "en": "Showing {n} of {total}", "zh": "显示 {n}/{total}",
    },
    "unity_live_readonly_lib": {
        "ru": "Чужая библиотека: внутренности движка и физики, запись "
              "вылетает игру. Только чтение.",
        "en": "Third-party library: engine and physics internals — "
              "writing here crashes the game. Read-only.", "zh": "第三方库：引擎和物理内部——写入此处会导致游戏崩溃。只读。",
    },
    "unity_live_readonly": {
        "ru": "Чужая библиотека: здесь внутренности движка и физики, "
              "запись вылетает игру. Только чтение.",
        "en": "Third-party library: engine and physics internals — "
              "writing here crashes the game. Read-only.", "zh": "第三方库：引擎和物理内部——写入此处会导致游戏崩溃。只读。",
    },
    "unity_live_undo": {
        "ru": "Вернуть",
        "en": "Undo", "zh": "撤销",
    },
    "unity_live_undone": {
        "ru": "Возвращено значений: {n}",
        "en": "Values restored: {n}", "zh": "已恢复数值：{n}",
    },
    "unity_saves_search_hint": {
        "ru": "Ищите по названию ключа, например level или exp.",
        "en": "Search by key name, e.g. level or exp.", "zh": "按键名搜索，如 level 或 exp。",
    },
    "unity_saves_game_running": {
        "ru": "Игра запущена и перезапишет сейв при выходе.",
        "en": "The game is running and will overwrite the save on exit.", "zh": "游戏正在运行，退出时会覆盖存档。",
    },
    "dash_delete_saves": {
        "ru": "Удалить сейвы",
        "en": "Delete saves", "zh": "删除存档",
    },
    "dash_delete_saves_q": {
        "ru": "Удалить файлы сохранений ({n}): {names}?\n\n"
              "Перед удалением они будут отложены в папку backup, "
              "так что вернуть их можно будет.",
        "en": "Delete save files ({n}): {names}?\n\n"
              "They will be moved to the backup folder first, "
              "so they can be restored.", "zh": "删除存档文件（{n} 个）：{names}？\n\n它们会先移到备份文件夹，可恢复。",
    },
    "dash_delete_saves_more": {
        "ru": " и ещё {n}",
        "en": " and {n} more", "zh": "还有 {n} 个",
    },
    "dash_delete_saves_done": {
        "ru": "Удалено файлов: {n}",
        "en": "Files deleted: {n}", "zh": "已删除文件：{n}",
    },
    "dash_delete_saves_none": {
        "ru": "Сейвов не найдено — удалять нечего.",
        "en": "No saves found — nothing to delete.", "zh": "未找到存档——无需删除。",
    },
    "dash_delete_saves_running": {
        "ru": "Сначала закройте игру: запущенная игра перезапишет сейв "
              "при выходе.",
        "en": "Close the game first: a running game will overwrite "
              "the save on exit.", "zh": "请先关闭游戏：运行中的游戏退出时会覆盖存档。",
    },
    # ── живые читы Twine ──
    "twine_cheat_reload": {
        "ru": "Обновить",
        "en": "Reload", "zh": "重新加载",
    },
    "twine_cheat_auto": {
        "ru": "Следить",
        "en": "Live", "zh": "实时",
    },
    "twine_cheat_var": {
        "ru": "Переменная",
        "en": "Variable", "zh": "变量",
    },
    "twine_cheat_type": {
        "ru": "Тип",
        "en": "Type", "zh": "类型",
    },
    "twine_cheat_val": {
        "ru": "Значение",
        "en": "Value", "zh": "数值",
    },
    "twine_cheat_empty": {
        "ru": "Запустите игру из дашборда, затем «Обновить».",
        "en": "Launch the game from the dashboard, then press Reload.", "zh": "请从面板启动游戏，然后按重新加载。",
    },
    "twine_cheat_no_channel": {
        "ru": "Нет связи с игрой. Запустите её здесь и подождите "
              "загрузку.",
        "en": "No connection to the game. Launch it here and wait "
              "for it to load.", "zh": "无游戏连接。请在这里启动并等待加载。",
    },
    "twine_cheat_count": {
        "ru": "Переменных: {n}",
        "en": "Variables: {n}", "zh": "变量：{n}",
    },
    "twine_cheat_none": {
        "ru": "Переменных не показано: движок игры не опознан или игра "
              "не выставила своё состояние в окно страницы.",
        "en": "No variables shown: the game engine was not recognized, "
              "or the game does not expose its state on the page.", "zh": "无可显示变量：未识别游戏引擎，或游戏未在页面暴露状态。",
    },
    "twine_cheat_no_edit": {
        "ru": "Это объект или список — правьте его отдельные поля.",
        "en": "This is an object or list — edit its separate fields.", "zh": "这是对象或列表——请编辑其单独字段。",
    },
    "twine_cheat_write_err": {
        "ru": "Игра не приняла значение.",
        "en": "The game rejected the value.", "zh": "游戏拒绝了该值。",
    },
    "twine_cheat_bool": {
        "ru": "Нужно true или false.",
        "en": "Need true or false.", "zh": "需要 true 或 false。",
    },
    "twine_cheat_number": {
        "ru": "Не число: {s}",
        "en": "Not a number: {s}", "zh": "不是数字：{s}",
    },
    # ── поиск по памяти (как в Cheat Engine) ──
    "unity_scan_value_ph": {
        "ru": "значение",
        "en": "value", "zh": "数值",
    },
    "unity_scan_find": {
        "ru": "Найти",
        "en": "Scan", "zh": "扫描",
    },
    "unity_scan_next": {
        "ru": "Далее",
        "en": "Next", "zh": "下一步",
    },
    "unity_scan_reset": {
        "ru": "Сброс",
        "en": "Reset", "zh": "重置",
    },
    "unity_scan_restore": {
        "ru": "Вернуть",
        "en": "Undo", "zh": "撤销",
    },
    "unity_scan_addr": {
        "ru": "Адрес",
        "en": "Address", "zh": "地址",
    },
    "unity_scan_val": {
        "ru": "Значение",
        "en": "Value", "zh": "数值",
    },
    "unity_scan_empty": {
        "ru": "Запустите игру, введите число и нажмите «Найти».",
        "en": "Launch the game, enter a number and press Scan.", "zh": "请启动游戏，输入数字并按扫描。",
    },
    "unity_scan_hint": {
        "ru": "Меняйте значение в игре и жмите «Далее» — список "
              "сожмётся. Правьте только то, что узнали.",
        "en": "Change the value in game and press Next to narrow the "
              "list. Only edit what you identified.", "zh": "在游戏中改变数值后按下一步缩小范围。只编辑已确认的内容。",
    },
    "unity_scan_kind": {
        "ru": "{t}, {n} б",
        "en": "{t}, {n} B", "zh": "{t}，{n} 字节",
    },
    "unity_scan_k_int": {
        "ru": "целое",
        "en": "int", "zh": "整数",
    },
    "unity_scan_k_uint": {
        "ru": "без знака",
        "en": "uint", "zh": "无符号整数",
    },
    "unity_scan_k_float": {
        "ru": "дробное",
        "en": "float", "zh": "浮点数",
    },
    "unity_scan_f_changed": {
        "ru": "Изменилось",
        "en": "Changed", "zh": "已更改",
    },
    "unity_scan_f_same": {
        "ru": "Не изменилось",
        "en": "Unchanged", "zh": "未更改",
    },
    "unity_scan_f_inc": {
        "ru": "Увеличилось",
        "en": "Increased", "zh": "已增加",
    },
    "unity_scan_f_dec": {
        "ru": "Уменьшилось",
        "en": "Decreased", "zh": "已减少",
    },
    "unity_scan_working": {
        "ru": "Ищу…",
        "en": "Scanning…", "zh": "扫描中…",
    },
    "unity_scan_found": {
        "ru": "Найдено: {n} за {ms} мс ({mb} МБ памяти)",
        "en": "Found: {n} in {ms} ms ({mb} MB of memory)", "zh": "找到：{n}（{ms} 毫秒，{mb} MB 内存）",
    },
    "unity_scan_truncated": {
        "ru": "Найдено: {n} — список показан не полностью",
        "en": "Found: {n} — list is not complete", "zh": "找到：{n}——列表不完整",
    },
    "unity_scan_none": {
        "ru": "Ничего не найдено.",
        "en": "Nothing found.", "zh": "未找到。",
    },
    "unity_scan_skipped": {
        "ru": "(пропущено в текстурах и коде: {n})",
        "en": "(skipped in textures and code: {n})", "zh": "（在纹理和代码中跳过：{n}）",
    },
    "unity_scan_left": {
        "ru": "Осталось: {n}",
        "en": "Remaining: {n}", "zh": "剩余：{n}",
    },
    "unity_scan_all_gone": {
        "ru": "Все адреса недоступны — вероятно, игра перезапущена.",
        "en": "All addresses are gone — the game probably restarted.", "zh": "所有地址都消失了——游戏可能重启了。",
    },
    "unity_scan_written": {
        "ru": "Записано: {addr} = {v}",
        "en": "Written: {addr} = {v}", "zh": "已写入：{addr} = {v}",
    },
    "unity_scan_write_err": {
        "ru": "Запись не удалась: {e}",
        "en": "Write failed: {e}", "zh": "写入失败：{e}",
    },
    "unity_scan_restored": {
        "ru": "Возвращено значений: {n}",
        "en": "Values restored: {n}", "zh": "已恢复数值：{n}",
    },
    "unity_scan_no_value": {
        "ru": "Введите число.",
        "en": "Enter a number.", "zh": "请输入数字。",
    },
    "unity_scan_bad_number": {
        "ru": "Не число: {s}",
        "en": "Not a number: {s}", "zh": "不是数字：{s}",
    },
    "unity_saves_readonly": {
        "ru": "Только просмотр: правка сейвов ломала игру.",
        "en": "View only: editing saves crashed the game.", "zh": "仅查看：编辑存档曾导致游戏崩溃。",
    },
    "unity_saves_empty2": {        "ru": "Править нечего: сейвов и настроек не найдено. Сыграйте "
              "хотя бы раз — игра их создаст.",
        "en": "Nothing to edit: no saves or settings found. Play once — "
              "the game will create them.", "zh": "无可编辑内容：未找到存档或设置。请先玩一次——游戏会创建它们。",
    },
    "unity_saves_count": {
        "ru": "сейв: {save}, реестр: {prefs}",
        "en": "save: {save}, registry: {prefs}", "zh": "存档：{save}，注册表：{prefs}",
    },
    "unity_saves_all_files": {
        "ru": "Все файлы ({n})",
        "en": "All files ({n})", "zh": "所有文件（{n}）",
    },

    # ── Ren'Py/Twine cheat tab (H3) ──
    "rpy_search_ph": {
        "ru": "имя или значение переменной…",
        "en": "variable name or value…", "zh": "变量名或数值…",
    },
    "rpy_autorefresh": {"ru": "Автообновление", "en": "Auto-refresh", "zh": "自动刷新"},
    "rpy_hide_text": {"ru": "Скрыть текст", "en": "Hide text", "zh": "隐藏文本"},
    "rpy_var_name": {"ru": "Переменная", "en": "Variable", "zh": "变量"},
    "rpy_var_value": {"ru": "Значение", "en": "Value", "zh": "数值"},
    "rpy_vars_hint": {
        "ru": "Enter — применить, Escape — отмена.",
        "en": "Enter applies, Escape cancels.", "zh": "回车应用，Esc 取消。",
    },
    "rpy_freeze": {"ru": "Заморозка", "en": "Freeze", "zh": "冻结"},
    "rpy_frozen": {
        "ru": "❄ Заморожено: {name} = {value}",
        "en": "❄ Frozen: {name} = {value}", "zh": "❄ 已冻结：{name} = {value}",
    },
    "rpy_unfrozen": {
        "ru": "Заморозка снята: {name}",
        "en": "Unfrozen: {name}", "zh": "已解冻：{name}",
    },
    "rpy_applied": {
        "ru": "{name} = {value}",
        "en": "{name} = {value}", "zh": "{name} = {value}",
    },
    "rpy_bad_value": {
        "ru": "{name}: значение не подходит по типу",
        "en": "{name}: value type mismatch", "zh": "{name}：数值类型不匹配",
    },
    "rpy_exec_go": {"ru": "Запуск", "en": "Run", "zh": "运行"},
    "rpy_scan_value": {"ru": "Значение:", "en": "Value:", "zh": "数值："},
    "rpy_scan_eq": {"ru": "равно", "en": "equals", "zh": "等于"},
    "rpy_scan_changed": {"ru": "изменилось", "en": "changed", "zh": "已更改"},
    "rpy_scan_unchanged": {"ru": "не изменилось", "en": "unchanged", "zh": "未更改"},
    "rpy_scan_increased": {"ru": "увеличилось", "en": "increased", "zh": "已增加"},
    "rpy_scan_decreased": {"ru": "уменьшилось", "en": "decreased", "zh": "已减少"},
    "rpy_scan_go": {"ru": "Сканировать", "en": "Scan", "zh": "扫描"},
    "rpy_scan_next": {"ru": "Уточнить", "en": "Next scan", "zh": "下次扫描"},
    "rpy_scan_reset": {"ru": "Сброс", "en": "Reset", "zh": "重置"},
    "rpy_scan_found": {
        "ru": "Найдено: {n} — измените значение в игре и нажмите «Уточнить»",
        "en": "Found: {n} — change the value in game, then press \"Next scan\"", "zh": "找到：{n}——请在游戏中改变数值，然后按“下次扫描”",
    },
    "rpy_scan_need_value": {
        "ru": "Введите значение для поиска (число или текст)",
        "en": "Enter a value to scan for (number or text)", "zh": "请输入要扫描的值（数字或文本）",
    },
    "rpy_scan_no_active": {
        "ru": "Сначала нажмите «Сканировать»",
        "en": "Run a scan first", "zh": "请先运行一次扫描",
    },

    # ── Generic ──
    "btn_yes": {"ru": "Да", "en": "Yes", "zh": "是"},
    "btn_no": {"ru": "Нет", "en": "No", "zh": "否"},
    "btn_ok": {"ru": "ОК", "en": "OK", "zh": "确定"},
    "btn_cancel": {"ru": "Отмена", "en": "Cancel", "zh": "取消"},
    "btn_close": {"ru": "Закрыть", "en": "Close", "zh": "关闭"},
    "err": {"ru": "Ошибка", "en": "Error", "zh": "错误"},
    "info": {"ru": "Информация", "en": "Information", "zh": "信息"},
    "done": {"ru": "Готово", "en": "Done", "zh": "完成"},
    "about_title": {"ru": "О программе", "en": "About", "zh": "关于"},
    "about_version": {"ru": "Версия {v}", "en": "Version {v}", "zh": "版本 {v}"},
    "about_desc": {
        "ru": "Программа для перевода и модификации игр.",
        "en": "App for translating and modding games.", "zh": "用于翻译和修改游戏的应用。",
    },
    "about_free": {
        "ru": "Приложение бесплатно и без подписок",
        "en": "The app is free with no subscriptions", "zh": "应用免费，无订阅",
    },
    "about_engines": {"ru": "Поддерживаемые движки", "en": "Supported engines", "zh": "支持的引擎"},
    "about_kofi": {"ru": "Поддержать проект на Ko-fi", "en": "Support the project on Ko-fi", "zh": "在 Ko-fi 上支持本项目"},
    "about_close": {"ru": "Закрыть", "en": "Close", "zh": "关闭"},
    "update_title": {"ru": "Доступна новая версия", "en": "Update available", "zh": "有可用更新"},
    "update_found": {
        "ru": "Вышла новая версия OctopusBridge — {v}!",
        "en": "A new version of OctopusBridge is available — {v}!", "zh": "OctopusBridge 有新版本——{v}！",
    },
    "update_open_release": {
        "ru": "Скачать можно на странице релиза GitHub.",
        "en": "Download it from the GitHub release page.", "zh": "可从 GitHub 发布页下载。",
    },
    "update_open": {"ru": "Открыть страницу", "en": "Open release page", "zh": "打开发布页"},
    "update_later": {"ru": "Позже", "en": "Later", "zh": "稍后"},
}


def set_language(lang: str):
    global _lang
    _lang = lang


def current_lang() -> str:
    """Текущий язык интерфейса ("ru" | "en" | "zh")."""
    return _lang


def TR(key: str, **fmt) -> str:
    entry = _STRINGS.get(key)
    if not entry:
        return key
    text = entry.get(_lang, entry.get("ru", key))
    if fmt or ("{" in text and "}" in text):
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            # необязательные плейсхолдеры ({live}) — подставляем "".
            try:
                import string as _s
                fields = [f[1] for f in _s.Formatter().parse(text)
                          if f[1]]
                safe = {k: fmt.get(k, "") for k in fields}
                return text.format(**safe)
            except Exception:  # noqa: BLE001
                return text
    return text


_PROVIDER_KEYS = {
    "rotate": ("prov_rotate", "prov_short_rotate"),
}


def provider_short_name(key: str) -> str:
    """Краткое локализованное имя провайдера (для дашборда/статус-бара)."""
    pair = _PROVIDER_KEYS.get(key)
    return TR(pair[1]) if pair else key


def engine_hint(name: str) -> str:
    """Локализованная подсказка при недоступном провайдере."""
    # Движок один (rotate-пул): именованных подсказок больше нет.
    _ = name
    return TR("hint_check_provider")
