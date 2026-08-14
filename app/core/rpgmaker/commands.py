# -*- coding: utf-8 -*-
"""Каталог команд событий RPG Maker MV/MZ (Game_Interpreter).

code -> (имя_ru, имя_en, группа_ru, группа_en, схема параметров).
Схема параметра:
  ("n", подпись_ru, подпись_en)      — целое число
  ("s", подпись_ru, подпись_en)      — строка
  ("b", подпись_ru, подпись_en)      — bool (в MZ хранится true/false)
  ("e", подпись_ru, подпись_en, варианты_ru, варианты_en) — выбор
  ("any", подпись_ru, подпись_en)    — число или строка (авто)

Команды с континуаторами (текст 401, выборы 402/403/404, ветвления
111/411/412, маршруты 205/505, плагины 357/657, скрипты 355/655)
обрабатываются редактором отдельно; здесь только заголовки.
"""
from __future__ import annotations

# (code, имя_ru, имя_en, группа_ru, группа_en, параметры)
COMMANDS: dict[int, tuple[str, str, str, str, list]] = {
    101: ("Показать текст", "Show Text", "Сообщение", "Message", [
        ("s", "Лицо", "Face"), ("n", "Индекс лица", "Face index"),
        ("e", "Фон", "Background", ["Обычный", "Тёмный", "Прозрачный"],
         ["Normal", "Dark", "Transparent"]),
        ("e", "Позиция", "Position", ["Снизу", "Сверху", "Центр"],
         ["Bottom", "Top", "Middle"])]),
    102: ("Показать выборы", "Show Choices", "Сообщение", "Message", []),
    104: ("Показать выборы (старый)", "Show Choices (old)", "Сообщение", "Message", []),
    105: ("Показать прокрутку текста", "Scroll Text", "Сообщение", "Message", []),
    108: ("Комментарий", "Comment", "Сообщение", "Message",
          [("s", "Комментарий", "Comment")]),
    111: ("Условное ветвление", "Conditional Branch", "Поток", "Flow", []),
    112: ("Повтор", "Loop", "Поток", "Flow", []),
    113: ("Прервать повтор", "Break Loop", "Поток", "Flow", []),
    115: ("Выйти из события", "Exit Event Processing", "Поток", "Flow", []),
    117: ("Вызов общего события", "Call Common Event", "Поток", "Flow",
          [("n", "ID общего события", "Common event ID")]),
    118: ("Метка", "Label", "Поток", "Flow", [("s", "Имя метки", "Label name")]),
    119: ("Перейти к метке", "Jump to Label", "Поток", "Flow",
          [("s", "Имя метки", "Label name")]),
    121: ("Управление переключателями", "Control Switches", "Переключатели",
         "Switches", [
             ("n", "Начальный ID", "Start ID"), ("n", "Конечный ID", "End ID"),
             ("e", "Значение", "Value", ["ВКЛ", "ВЫКЛ"], ["ON", "OFF"])]),
    122: ("Управление переменными", "Control Variables", "Переменные",
         "Variables", []),
    123: ("Управление локальным переключателем", "Control Self Switch",
         "Переключатели", "Switches", [
             ("e", "Переключатель", "Switch", ["A", "B", "C", "D"]),
             ("e", "Значение", "Value", ["ВКЛ", "ВЫКЛ"], ["ON", "OFF"])]),
    124: ("Управление таймером", "Control Timer", "Система", "System", [
        ("n", "Операция (1=запуск, 0=стоп)", "Operation (1=start, 0=stop)"),
        ("n", "Секунды", "Seconds")]),
    125: ("Изменить золото", "Change Gold", "Экономика", "Economy", [
        ("e", "Операция", "Operation", ["+", "-"]),
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "Значение", "Value")]),
    126: ("Изменить предметы", "Change Items", "Экономика", "Economy", [
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "ID", "ID"),
        ("n", "Количество", "Amount")]),
    127: ("Изменить оружие", "Change Weapons", "Экономика", "Economy", [
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "ID", "ID"),
        ("n", "Количество", "Amount")]),
    128: ("Изменить броню", "Change Armors", "Экономика", "Economy", [
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "ID", "ID"),
        ("n", "Количество", "Amount")]),
    129: ("Изменить участника партии", "Change Party Member", "Группа", "Party", [
        ("n", "ID актёра", "Actor ID"),
        ("e", "Операция", "Operation", ["Добавить", "Убрать"],
         ["Add", "Remove"]),
        ("b", "Инициализировать", "Initialize")]),
    132: ("Изменить BGM битвы", "Change Battle BGM", "Аудио", "Audio",
          [("s", "Имя", "Name")]),
    133: ("Изменить ME победы", "Change Victory ME", "Аудио", "Audio",
          [("s", "Имя", "Name")]),
    134: ("Изменить ME побега", "Change Escape ME", "Аудио", "Audio",
          [("s", "Имя", "Name")]),
    135: ("Изменить врагов в стычке", "Change Encounter Enemies", "Битва",
         "Battle", []),
    136: ("Отключить стычки", "Disable Encounters", "Битва", "Battle",
          [("b", "Отключить", "Disable")]),
    137: ("Включить стычки", "Enable Encounters", "Битва", "Battle",
          [("b", "Включить", "Enable")]),
    138: ("Изменить шаги до стычки", "Change Encounter Step Count", "Битва",
         "Battle", [("n", "Шаги", "Steps")]),
    201: ("Перенести игрока", "Transfer Player", "Игрок", "Player", [
        ("e", "Тип", "Type", ["Прямо", "Через переменные"],
         ["Direct", "By variable"]), ("any", "ID карты", "Map ID"),
        ("any", "X", "X"), ("any", "Y", "Y"),
        ("e", "Направление", "Direction", ["Вниз", "Влево", "Вправо", "Вверх"],
         ["Down", "Left", "Right", "Up"]),
        ("e", "Затемнение", "Fade", ["Чёрное", "Белое", "Нет"],
         ["Black", "White", "None"])]),
    202: ("Задать положение транспорта", "Set Vehicle Location", "Игрок",
         "Player", [
             ("e", "Транспорт", "Vehicle", ["Лодка", "Корабль", "Дирижабль"],
              ["Boat", "Ship", "Airship"]),
             ("e", "Тип", "Type", ["Прямо", "Через переменные"],
              ["Direct", "By variable"]), ("any", "ID карты", "Map ID"),
             ("any", "X", "X"), ("any", "Y", "Y")]),
    203: ("Задать положение события", "Set Event Location", "События", "Events",
         [
             ("e", "Событие", "Event", ["Это событие", "Игрок", "Другое (ID)"],
              ["This event", "Player", "Other (ID)"]),
             ("e", "Тип", "Type", ["Прямо", "Через переменные"],
              ["Direct", "By variable"]), ("any", "X", "X"), ("any", "Y", "Y")]),
    204: ("Прокрутка карты", "Scroll Map", "Игрок", "Player", [
        ("e", "Направление", "Direction", ["Вниз", "Влево", "Вправо", "Вверх"],
         ["Down", "Left", "Right", "Up"]),
        ("n", "Клеток", "Tiles"), ("n", "Скорость", "Speed")]),
    205: ("Задать маршрут движения", "Set Movement Route", "Движение",
         "Movement", []),
    206: ("Сесть/сойти с транспорта", "Get on/off Vehicle", "Игрок", "Player", []),
    211: ("Прозрачность игрока", "Player Transparency", "Игрок", "Player",
          [("b", "Прозрачный", "Transparent")]),
    212: ("Показать анимацию", "Show Animation", "События", "Events", [
        ("e", "Цель", "Target", ["Это событие", "Игрок", "Другое (ID)"],
         ["This event", "Player", "Other (ID)"]),
        ("n", "ID анимации", "Animation ID"), ("b", "Ждать", "Wait")]),
    213: ("Показать реплику", "Show Balloon Icon", "События", "Events", [
        ("e", "Цель", "Target", ["Это событие", "Игрок", "Другое (ID)"],
         ["This event", "Player", "Other (ID)"]),
        ("n", "ID реплики", "Balloon ID")]),
    214: ("Стереть событие", "Erase Event", "События", "Events", []),
    217: ("Задать маршрут игрока", "Set Player Movement Route", "Движение",
         "Movement", []),
    221: ("Затемнение экрана", "Fadeout Screen", "Экран", "Screen", []),
    222: ("Осветление экрана", "Fadein Screen", "Экран", "Screen", []),
    223: ("Тонировать экран", "Tint Screen", "Экран", "Screen", [
        ("n", "R", "R"), ("n", "G", "G"), ("n", "B", "B"), ("n", "Серый", "Gray"),
        ("n", "Время (кадры)", "Time (frames)"), ("b", "Ждать", "Wait")]),
    224: ("Вспышка экрана", "Flash Screen", "Экран", "Screen", [
        ("n", "R", "R"), ("n", "G", "G"), ("n", "B", "B"),
        ("n", "Интенсивность", "Intensity"),
        ("n", "Длительность", "Duration"), ("b", "Ждать", "Wait")]),
    225: ("Тряска экрана", "Shake Screen", "Экран", "Screen", [
        ("n", "Сила", "Power"), ("n", "Скорость", "Speed"),
        ("n", "Длительность", "Duration"), ("b", "Ждать", "Wait")]),
    230: ("Пауза", "Wait", "Тайминг", "Timing", [("n", "Кадры", "Frames")]),
    231: ("Показать картинку", "Show Picture", "Картинки", "Pictures", [
        ("n", "Номер", "Number"), ("s", "Имя файла", "File name"),
        ("e", "Точка", "Origin", ["Верхний левый", "Центр"],
         ["Top-left", "Center"]),
        ("n", "X", "X"), ("n", "Y", "Y"), ("n", "Масштаб X", "Scale X"),
        ("n", "Масштаб Y", "Scale Y"), ("n", "Непрозрачность", "Opacity"),
        ("e", "Смешивание", "Blend", ["Норма", "Добав.", "Умнож.", "Экран"],
         ["Normal", "Additive", "Multiply", "Screen"])]),
    232: ("Двигать картинку", "Move Picture", "Картинки", "Pictures", [
        ("n", "Номер", "Number"), ("n", "X", "X"), ("n", "Y", "Y"),
        ("n", "Масштаб X", "Scale X"), ("n", "Масштаб Y", "Scale Y"),
        ("n", "Непрозрачность", "Opacity"),
        ("e", "Смешивание", "Blend", ["Норма", "Добав.", "Умнож.", "Экран"],
         ["Normal", "Additive", "Multiply", "Screen"]),
        ("n", "Время (кадры)", "Time (frames)"), ("b", "Ждать", "Wait")]),
    233: ("Вращать картинку", "Rotate Picture", "Картинки", "Pictures", [
        ("n", "Номер", "Number"), ("n", "Скорость", "Speed")]),
    234: ("Тонировать картинку", "Tint Picture", "Картинки", "Pictures", [
        ("n", "Номер", "Number"), ("n", "R", "R"), ("n", "G", "G"),
        ("n", "B", "B"), ("n", "Серый", "Gray"),
        ("n", "Время (кадры)", "Time (frames)"), ("b", "Ждать", "Wait")]),
    235: ("Стереть картинку", "Erase Picture", "Картинки", "Pictures",
          [("n", "Номер", "Number")]),
    236: ("Погода", "Set Weather Effect", "Экран", "Screen", [
        ("e", "Тип", "Type", ["Нет", "Дождь", "Буря", "Снег"],
         ["None", "Rain", "Storm", "Snow"]),
        ("n", "Сила", "Power"), ("n", "Время (кадры)", "Time (frames)"),
        ("b", "Ждать", "Wait")]),
    241: ("Играть BGM", "Play BGM", "Аудио", "Audio", [
        ("s", "Имя", "Name"), ("n", "Громкость", "Volume"),
        ("n", "Тон", "Pitch"), ("n", "Панорама", "Pan")]),
    242: ("Затухание BGM", "Fadeout BGM", "Аудио", "Audio",
          [("n", "Время (сек)", "Time (sec)")]),
    243: ("Играть BGS", "Play BGS", "Аудио", "Audio", [
        ("s", "Имя", "Name"), ("n", "Громкость", "Volume"),
        ("n", "Тон", "Pitch"), ("n", "Панорама", "Pan")]),
    244: ("Затухание BGS", "Fadeout BGS", "Аудио", "Audio",
          [("n", "Время (сек)", "Time (sec)")]),
    245: ("Играть ME", "Play ME", "Аудио", "Audio", [
        ("s", "Имя", "Name"), ("n", "Громкость", "Volume"),
        ("n", "Тон", "Pitch"), ("n", "Панорама", "Pan")]),
    246: ("Играть SE", "Play SE", "Аудио", "Audio", [
        ("s", "Имя", "Name"), ("n", "Громкость", "Volume"),
        ("n", "Тон", "Pitch"), ("n", "Панорама", "Pan")]),
    249: ("Стоп SE", "Stop SE", "Аудио", "Audio", []),
    250: ("Играть фильм", "Play Movie", "Видео", "Video",
          [("s", "Имя файла", "File name")]),
    251: ("Показать сообщение (старое)", "Show Message (old)", "Сообщение",
         "Message", []),
    301: ("Обработка битвы", "Battle Processing", "Битва", "Battle", [
        ("e", "Тип", "Type", ["Прямо", "Через переменные"],
         ["Direct", "By variable"]),
        ("any", "ID врага/группы", "Enemy/group ID"),
        ("b", "Можно бежать", "Allow escape"), ("b", "Можно проиграть",
                                                 "Allow defeat")]),
    302: ("Обработка магазина", "Shop Processing", "Экономика", "Economy", [
        ("b", "Только покупка", "Purchase only")]),
    303: ("Ввод имени", "Name Input Processing", "Группа", "Party", [
        ("n", "ID актёра", "Actor ID"), ("n", "Макс. символов", "Max chars")]),
    311: ("Изменить HP", "Change HP", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("any", "Значение", "Value"), ("b", "Разрешить KO", "Allow KO"),
        ("b", "Ждать", "Wait")]),
    312: ("Изменить MP", "Change MP", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("any", "Значение", "Value")]),
    313: ("Изменить TP", "Change TP", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("any", "Значение", "Value")]),
    314: ("Изменить состояние", "Change State", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("e", "Операция", "Operation", ["Добавить", "Убрать"],
         ["Add", "Remove"]),
        ("any", "ID состояния", "State ID"), ("b", "Показать анимацию",
                                               "Show animation")]),
    315: ("Полное восстановление", "Recover All", "Акторы", "Actors",
          [("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)")]),
    316: ("Изменить EXP", "Change EXP", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("e", "Операция", "Operation", ["+", "-"]),
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "Значение", "Value"),
        ("b", "Показать уровень", "Show level up")]),
    317: ("Изменить уровень", "Change Level", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("e", "Операция", "Operation", ["+", "-"]),
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "Значение", "Value"),
        ("b", "Показать уровень", "Show level up")]),
    318: ("Изменить параметр", "Change Parameter", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("e", "Параметр", "Parameter",
         ["MHP", "MMP", "АТК", "ЗАЩ", "МАГ", "МАГ.ЗАЩ", "ЛОВ", "УДАЧ"],
         ["MHP", "MMP", "ATK", "DEF", "MAT", "MDF", "AGI", "LUK"]),
        ("e", "Операция", "Operation", ["+", "-"]),
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "Значение", "Value")]),
    319: ("Изменить навык", "Change Skill", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("e", "Операция", "Operation", ["Выучить", "Забыть"],
         ["Learn", "Forget"]),
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "ID навыка", "Skill ID")]),
    320: ("Изменить экипировку", "Change Equipment", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "ID предмета", "Item ID")]),
    321: ("Изменить имя", "Change Name", "Акторы", "Actors", [
        ("n", "ID актёра", "Actor ID"), ("s", "Новое имя", "New name")]),
    322: ("Изменить класс", "Change Class", "Акторы", "Actors", [
        ("n", "ID актёра (0=вся партия)", "Actor ID (0=whole party)"),
        ("e", "Операнд", "Operand", ["Константа", "Переменная"],
         ["Constant", "Variable"]), ("any", "ID класса", "Class ID")]),
    323: ("Изменить никнейм", "Change Nickname", "Акторы", "Actors", [
        ("n", "ID актёра", "Actor ID"), ("s", "Новый никнейм", "New nickname")]),
    324: ("Изменить профиль", "Change Profile", "Акторы", "Actors", [
        ("n", "ID актёра", "Actor ID"), ("s", "Новый профиль", "New profile")]),
    331: ("Изменить золото (старое)", "Change Gold (old)", "Экономика",
         "Economy", []),
    332: ("Изменить предметы (старое)", "Change Items (old)", "Экономика",
         "Economy", []),
    341: ("Изменить изображения актёра", "Change Actor Images", "Акторы",
         "Actors", [
             ("n", "ID актёра", "Actor ID"), ("s", "Лицо", "Face"),
             ("n", "Индекс лица", "Face index"), ("s", "Персонаж", "Character"),
             ("n", "Индекс персонажа", "Character index")]),
    342: ("Изменить изображение транспорта", "Change Vehicle Image", "Игрок",
         "Player", [
             ("e", "Транспорт", "Vehicle", ["Лодка", "Корабль", "Дирижабль"],
              ["Boat", "Ship", "Airship"]), ("s", "Изображение", "Image")]),
    351: ("Открыть экран меню", "Open Menu Screen", "Сцены", "Scenes", []),
    352: ("Открыть экран сохранения", "Open Save Screen", "Сцены", "Scenes", []),
    353: ("Открыть экран загрузки", "Open Load Screen", "Сцены", "Scenes", []),
    354: ("Открыть экран окончания", "Open End Screen", "Сцены", "Scenes", []),
    355: ("Скрипт", "Script", "Программирование", "Programming", []),
    356: ("Скрипт (плагин-команда MV)", "Script (MV plugin command)",
         "Программирование", "Programming", []),
    357: ("Плагин-команда", "Plugin Command", "Программирование",
         "Programming", []),
    401: ("Текст сообщения", "Message Text", "Сообщение", "Message",
          [("s", "Текст", "Text")]),
    402: ("Когда (выбор)", "When (choice)", "Сообщение", "Message",
          [("n", "Индекс", "Index"), ("s", "Имя", "Name")]),
    403: ("Когда (отмена)", "When (cancel)", "Сообщение", "Message", []),
    404: ("Конец выбора", "End Choices", "Сообщение", "Message", []),
    405: ("Строка прокрутки", "Scroll Text Line", "Сообщение", "Message",
          [("s", "Текст", "Text")]),
    408: ("Комментарий (продолжение)", "Comment (continued)", "Сообщение",
         "Message", [("s", "Комментарий", "Comment")]),
    411: ("Иначе", "Else", "Поток", "Flow", []),
    412: ("Конец ветвления", "End Branch", "Поток", "Flow", []),
    413: ("Конец повтора", "Repeat Above", "Поток", "Flow", []),
    414: ("Конец общей команды", "End Common Event", "Поток", "Flow", []),
    505: ("Команда маршрута", "Route Command", "Движение", "Movement", []),
    601: ("Команда маршрута (продолжение)", "Route Command (cont.)", "Движение",
         "Movement", []),
    602: ("Команда маршрута (продолжение)", "Route Command (cont.)", "Движение",
         "Movement", []),
    603: ("Команда маршрута (продолжение)", "Route Command (cont.)", "Движение",
         "Movement", []),
    604: ("Команда маршрута (продолжение)", "Route Command (cont.)", "Движение",
         "Movement", []),
    605: ("Команда маршрута (продолжение)", "Route Command (cont.)", "Движение",
         "Movement", []),
    655: ("Скрипт (продолжение)", "Script (continued)", "Программирование",
         "Programming", [("s", "Строка скрипта", "Script line")]),
    657: ("Плагин-команда (продолжение)", "Plugin Command (continued)",
         "Программирование", "Programming", [("s", "Аргумент", "Argument")]),
}

# группы для меню «Добавить команду»: (ru, en)
GROUPS: list[tuple[str, str]] = [
    ("Сообщение", "Message"), ("Поток", "Flow"), ("Переключатели", "Switches"),
    ("Переменные", "Variables"), ("Экономика", "Economy"), ("Группа", "Party"),
    ("Акторы", "Actors"), ("Битва", "Battle"), ("Игрок", "Player"),
    ("События", "Events"), ("Движение", "Movement"), ("Тайминг", "Timing"),
    ("Экран", "Screen"), ("Картинки", "Pictures"), ("Аудио", "Audio"),
    ("Видео", "Video"), ("Сцены", "Scenes"), ("Программирование", "Programming"),
    ("Система", "System"),
]

# команды маршрута движения (код 505): routeCode -> (имя_ru, имя_en, [типы параметров])
ROUTE_COMMANDS: dict[int, tuple[str, str, list]] = {
    1: ("Вниз", "Down", []), 2: ("Влево", "Left", []),
    3: ("Вправо", "Right", []), 4: ("Вверх", "Up", []),
    5: ("Вниз-влево", "Lower Left", []), 6: ("Вниз-вправо", "Lower Right", []),
    7: ("Вверх-влево", "Upper Left", []), 8: ("Вверх-вправо", "Upper Right", []),
    9: ("Случайно", "Random", []), 10: ("К игроку", "Toward Player", []),
    11: ("От игрока", "Away from Player", []), 12: ("Вперёд", "Forward", []),
    13: ("Назад", "Back", []),
    14: ("Прыжок", "Jump", [("n", "X", "X"), ("n", "Y", "Y")]),
    15: ("Пауза", "Wait", [("n", "Кадры", "Frames")]),
    16: ("Поворот вниз", "Turn Down", []), 17: ("Поворот влево", "Turn Left", []),
    18: ("Поворот вправо", "Turn Right", []), 19: ("Поворот вверх", "Turn Up", []),
    20: ("Поворот на 90° вправо", "Turn 90° Right", []),
    21: ("Поворот на 90° влево", "Turn 90° Left", []),
    22: ("Поворот на 180°", "Turn 180°", []),
    23: ("Поворот на 90° вправо или влево", "Turn 90° Right/Left", []),
    24: ("Поворот к игроку", "Turn Toward Player", []),
    25: ("Поворот от игрока", "Turn Away from Player", []),
    26: ("Поворот случайно", "Turn Random", []),
    27: ("Переключатель ВКЛ", "Switch ON", [("n", "ID", "ID")]),
    28: ("Переключатель ВЫКЛ", "Switch OFF", [("n", "ID", "ID")]),
    29: ("Изменить скорость", "Change Speed", [("n", "Скорость", "Speed")]),
    30: ("Изменить частоту", "Change Frequency", [("n", "Частота", "Frequency")]),
    31: ("Анимация ходьбы ВКЛ", "Walk Animation ON", []),
    32: ("Анимация ходьбы ВЫКЛ", "Walk Animation OFF", []),
    33: ("Анимация шага ВКЛ", "Step Animation ON", []),
    34: ("Анимация шага ВЫКЛ", "Step Animation OFF", []),
    35: ("Фиксация направления ВКЛ", "Direction Fix ON", []),
    36: ("Фиксация направления ВЫКЛ", "Direction Fix OFF", []),
    37: ("Проход ВКЛ", "Through ON", []), 38: ("Проход ВЫКЛ", "Through OFF", []),
    39: ("Прозрачность ВКЛ", "Transparent ON", []),
    40: ("Прозрачность ВЫКЛ", "Transparent OFF", []),
    41: ("Изменить изображение", "Change Image", [("s", "Имя", "Name"),
                                                  ("n", "Индекс", "Index")]),
    42: ("Изменить непрозрачность", "Change Opacity", [("n", "Непрозрачность",
                                                         "Opacity")]),
    43: ("Изменить смешивание", "Change Blend Mode", [("n", "Режим", "Mode")]),
    44: ("Играть SE", "Play SE", [("s", "Имя", "Name"), ("n", "Громкость",
                                                         "Volume"),
                                 ("n", "Тон", "Pitch"), ("n", "Панорама",
                                                          "Pan")]),
    45: ("Скрипт", "Script", [("s", "Скрипт", "Script")]),
    46: ("Скрипт (продолжение)", "Script (continued)",
         [("s", "Скрипт", "Script")]),
}

# коды команд 505 в обратную сторону: (name_ru, name_en) -> code
ROUTE_BY_NAME = {name: code for code, (name, _, _) in ROUTE_COMMANDS.items()}
ROUTE_BY_NAME_EN = {name: code for code, (_, name, _) in ROUTE_COMMANDS.items()}

# условия страницы (page.conditions)
COND_SWITCH1 = "switch1Valid"
COND_SWITCH2 = "switch2Valid"
COND_VARIABLE = "variableValid"
COND_SELF = "selfSwitchValid"


def _lang(lang: str) -> int:
    """0 = ru, 1 = en."""
    return 1 if lang == "en" else 0


def command_name(code: int, lang: str = "ru") -> str:
    found = COMMANDS.get(code)
    if found:
        return found[_lang(lang)]
    if code in ROUTE_COMMANDS:
        return ROUTE_COMMANDS[code][_lang(lang)]
    return f"Команда {code}" if lang != "en" else f"Command {code}"


def command_group(code: int, lang: str = "ru") -> str:
    found = COMMANDS.get(code)
    if found:
        return found[2 + _lang(lang)]
    return "Прочее" if lang != "en" else "Other"


def groups(lang: str = "ru") -> list[str]:
    return [g[_lang(lang)] for g in GROUPS]


def command_params(code: int, lang: str = "ru") -> list:
    """Схема параметров, локализованная: (тип, подпись, варианты|None)."""
    found = COMMANDS.get(code)
    if not found:
        return []
    out = []
    for spec in found[4]:
        t = spec[0]
        label = spec[1 + _lang(lang)]
        if t == "e" and len(spec) > 3:
            out.append((t, label, spec[3 + _lang(lang)]))
        else:
            out.append((t, label, None))
    return out


def route_command_code(cmd) -> int:
    """Код маршрутной команды: MZ хранит {code: N}, MV — число."""
    return cmd["code"] if isinstance(cmd, dict) else int(cmd)


def route_command_name(code, lang: str = "ru") -> str:
    rc = route_command_code(code)
    found = ROUTE_COMMANDS.get(rc)
    if found:
        return found[_lang(lang)]
    return f"Маршрут {rc}" if lang != "en" else f"Route {rc}"


def route_command_params(code, lang: str = "ru") -> list:
    found = ROUTE_COMMANDS.get(route_command_code(code))
    if not found:
        return []
    out = []
    for spec in found[2]:
        t = spec[0]
        label = spec[1 + _lang(lang)]
        if t == "e" and len(spec) > 3:
            out.append((t, label, spec[3 + _lang(lang)]))
        else:
            out.append((t, label, None))
    return out