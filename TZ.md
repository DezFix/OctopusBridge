# Ren'Py Module — План восстановления (TZ.md)

> Этот файл — техническое задание для восстановления ядра Ren'Py.
> Если работа прервалась (кончились токены), прочитай этот файл,
> проверь статус «Готово/В работе» и продолжи с места остановки.

## Контекст

OctopusBridge — мультидвижковый инструмент перевода игр. Ядро Ren'Py сломано:
1. **Frida не запускает игру** — ошибка "device not found"
2. **Текст на перевод всего ~1500** вместо ожидаемых ~18000+
3. **Читы не работают** — грузится не та вкладка
4. **Подмена шрифта** — сломана из-за неверного пути к шрифту

Все баги связаны только с модулем Ren'Py. Другие модули трогать НЕЛЬЗЯ.

## Архитектура (ключевые файлы Ren'Py)

```
app/engines/renpy/__init__.py          — RenPyModule (detect/extract/apply/ui_tabs)
app/engines/renpy/tentacle.py          — RenPyTentacle (Frida launch/attach/TCP server)
app/engines/renpy/agent.py             — Python-агент (инъекция в игру через Frida)
app/core/renpy/parser.py               — извлечение текста из .rpy/.rpyc
app/core/renpy/rpa.py                  — чтение .rpa архивов
app/transport/frida_rpc/injector.py    — PythonInjector (Frida spawn/attach/exec)
app/core/tentacles/__init__.py         — create_tentacle("renpy") → RenPyTentacle
app/core/tentacles/base.py             — Tentacle (абстрактный базовый класс)
app/core/process.py                    — find_game_processes / _looks_like_renpy
app/ui/cheat_tab.py                    — CheatTab ДЛЯ RPG MAKER (НЕ Ren'Py)
app/ui/renpy_cheat_tab.py              — VariablesTab/TriggersTab ДЛЯ Ren'Py
app/ui/live_tab.py                     — автозапуск (autowatch)
app/core/assets/fonts/NotoSans-Regular.ttf  — шрифт кириллицы (РЕАЛЬНЫЙ путь)
```

## Найденные баги и план исправления

### БАГ 1 — Frida: "device not found" [КРИТИЧНЫЙ] — Статус: ✅ Готово

**Файл:** `app/transport/frida_rpc/injector.py` строки 27, 34, 40

**Проблема:** Все методы (`spawn`, `resume_pid`, `attach`) используют
`frida.get_usb_device()` — это возвращает USB-устройство (Android/iOS).
Для инъекции в локальный Windows процесс нужен `frida.get_local_device()`.
Без подключённого телефона `get_usb_device()` кидает
`frida.InvalidArgumentError: device not found`.

**Решение:**
1. Заменить `frida.get_usb_device()` на `frida.get_local_device()` во всех 3 методах.
2. Кешировать устройство в `self._device` (вызывается последовательно в launch: spawn → resume_pid.

**Код:**
```python
def _get_device(self):
    if self._device is None:
        self._device = frida.get_local_device()
    return self._device
```
Добавить `self._device = None` в `__init__`, использовать `self._get_device()`.

---

### БАГ 2 — .rpyc на диске никогда не парсятся [КРИТИЧНЫЙ] — Статус: ✅ Готово

**Файл:** `app/core/renpy/parser.py` строка 278 (`_iter_rpy`)

**Проблема:** `_iter_rpy` обходит диск иyield только `.rpy` файлы (строка 278:
`if f.endswith(".rpy")`). Файлы `.rpyc` на диске игнорируются полностью.
Фолбэк на строке 350 (`rpyc_path = path + "c"`) срабатывает ТОЛЬКО если чтение
соответствующего `.rpy` упадёт с `OSError`/`UnicodeDecodeError`.

Реальные игры почти всегда поставляют скомпилированные `.rpyc` БЕЗ `.rpy`.
Вот почему извлекается ~1500 строк вместо ~18000+ — большая часть
диалогов находится именно в `.rpyc`.

**Решение:** В `_iter_rpy` добавить yield для .rpyc файлов с диска:
```python
if f.endswith(".rpy") or f.endswith(".rpyc"):
    path = os.path.join(root, f)
    rel = os.path.relpath(path, game_dir).replace(os.sep, "/")
    yield path, rel
```
В `extract()` (строка 343) для `.rpyc` файлов с диска сразу парсить через
`_unpickle_rpyc` + `_walk_ast` (как уже делается для .rpa .rpyc).

---

### БАГ 3 — .rpy диалоги не извлекаются (regex) [КРИТИЧНЫЙ] — Статус: ✅ Готово

**Файл:** `app/core/renpy/parser.py` строки 75-79, 365-385 (`_extract_line`)

**Проблема:** `_extract_line` извлекает ТОЛЬКО:
- `old "..."` (RE_OLD) — translate-блоки
- `"choice":` (RE_CHOICE) — элементы меню
- `_("...")` (RE_TR_FN) — функция перевода

Самая частая форма Ren'Py диалога — `e "Hello"` или `character "line"` —
**НЕ извлекается**. Диалоги попадают в выдачу только через `.rpyc` AST
(баг #2), а из `.rpy` — нет.

**Решение:** Добавить regex для диалогов вида `<speaker> "text"`:
```python
RE_DIALOGUE = re.compile(
    r'^\s*(?:[a-zA-Z_][\w.]*\s+)?' + _STR + r'(?:\s|$)')
```
И в `_extract_line` проверять `RE_DIALOGUE` (но НЕ после `old`, `menu`,
`define`, `if`, `with`, `show` — это не диалоги, а другие конструкции).
Точное место — после проверки `RE_OLD` и `RE_CHOICE`.

Важно: НЕ матчить строки после ключевых слов Ren'Py: `define`, `default`,
`menu`, `label`, `scene`, `show`, `hide`, `play`, `jump`, `call`, `$`,
`if`, `elif`, `else`, `while`, `for`, `with`, `image`, `screen`, `transform`.

---

### БАГ 4 — Грузится не та вкладка читов [КРИТИЧНЫЙ] — Статус: ✅ Готово

**Файл:** `app/engines/renpy/__init__.py` строка 45 (`ui_tabs`)

**Проблема:** `ui_tabs` импортирует `from app.ui.cheat_tab import CheatTab`
— это вкладка ЧИТОВ ДЛЯ RPG MAKER. Она отправляет команды
`var_set index=N` (числовой индекс), `switch_set index= N`,
`open_menu`, `give_item`, `actor_set`, `win_battle` и т.д.

Ren'Py агент (`agent.py` строки 240-275) ожидает СОВЕРШЕННО другие команды:
`var_set name=...` (имя переменной, не индекс), `exec`, `get_vars`,
`gold_set/add`, `heal`, `teleport`. Несовпадение → читы молча не работают.

Правильная вкладка существует: `app/ui/renpy_cheat_tab.py` содержит
`VariablesTab` (отправляет `var_set name=...`, `exec`) и
`TriggersTab` (bool-переменные). Она НИКОГДА не грузится.

**Решение:** В `RenPyModule.ui_tabs` импортировать `renpy_cheat_tab`:
```python
def ui_tabs(self, main_window) -> list[tuple]:
    from app.ui.cheat_tab import CheatTab
    from app.ui.renpy_cheat_tab import VariablesTab, TriggersTab
    translate = main_window.translate_tab
    var_tab = VariablesTab(main_window)
    trg_tab = TriggersTab(main_window)
    main_window.cheat_tab = var_tab
    return [
        (translate, TR("tab_translate"), "translate"),
        (var_tab, TR("tab_cheats"), "cheats"),
        (trg_tab, "Triggers", "triggers"),
    ]
```
Также проверить флаги `bridge_vars`/`bridge_cheat_ack`/`bridge_client`
в `renpy_cheat_tab.py` — они должны корректно подключаться к MainWindow.

---

### БАГ 5 — Неверный путь к шрифту в tentacle.py [КРИТИЧНЫЙ] — Статус: ✅ Готово

**Файл:** `app/engines/renpy/tentacle.py` строка 87 (`install_font`)

**Проблема:** `install_font` ищет шрифт по пути
`os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", FONT_NAME)`.
Файл `tentacle.py` лежит в `app/engines/renpy/`, значит `".."` = `app/engines/`,
а `"assets"` = `app/engines/assets/fonts/` — ЭТОЙ ПАПКИ НЕ СУЩЕСТВУЕТ.

Реальный шрифт лежит в `app/core/assets/fonts/NotoSans-Regular.ttf`.

**Решение:** Исправить путь в `install_font`:
```python
font_src = os.path.join(os.path.dirname(__file__), "..", "..", "core",
                        "assets", "fonts", FONT_NAME)
```
Проверить что `parser.py:440` (тоже копирует шрифт) ссылается правильно —
он в `app/core/renpy/`, значит `".."` = `app/core/`, `"assets"` = правильно.

---

### БАГ 6 — Ren'Py автозапуск отключён — Статус: ✅ Готово

**Файл:** `app/ui/live_tab.py` строка 102 (`_autowatch_tick`)

**Проблема:** `_autowatch_tick` рано возвращает (return), если ключ движка
не rpgmaker:
```python
if self._engine_key() != "rpgmaker":
    return
```
Ren'Py игры не автодетектятся в списке attach. Нужно добавить ветку для renpy.

**Решение:** Добавить обработку renpy:
```python
engine = self._engine_key()
if engine == "rpgmaker":
    for p in proc.find_game_processes("rpgmaker", game_dir):
        # существующая логика CDP (probe_game_port)
        ...
elif engine == "renpy":
    for p in proc.find_game_processes("renpy", game_dir):
        if p["pid"] not in self._autowatch_failed:
            self._attach_auto(p["pid"])
            return
```
`_attach_auto` для renpy не использует port (Frida attach по PID).
Нужно проверить, что `_attach_auto` работает без port для renpy.

---

### БАГ 7 — Process detection слишком строгий — Статус: ✅ Готово

**Файл:** `app/core/process.py` строка 61 (`_looks_like_renpy`)

**Проблема:** Функция возвращает True только если:
1. Имя exe содержит "renpy" — большинство игр переименовывают exe
2. Рядом с exe есть папка `renpy/` — дистрибутивы её не поставляют

Игры вроде `MyGame.exe` БЕЗ папки `renpy/` не детектятся.

**Решение:** Добавить kiểmу по признакам Ren'Py игры:
```python
def _looks_like_renpy(exe_path: str, game_dir: str = "") -> bool:
    base = os.path.basename(exe_path).lower()
    if any(h in base for h in _RENPY_HINTS):
        return True
    root = os.path.dirname(exe_path)
    # renpy/ SDK folder
    if os.path.isdir(os.path.join(root, "renpy")):
        return True
    # game/ folder with .rpyc/.rpa + lib/ folder (очень характерно для Ren'Py)
    game_sub = os.path.join(root, "game")
    lib_dir = os.path.join(root, "lib")
    if os.path.isdir(game_sub) and os.path.isdir(lib_dir):
        return True
    return False
```

---

### БАГ 8 — Агент внедряется до загрузки renpy — Статус: ✅ Готово

**Файл:** `app/transport/frida_rpc/injector.py` строка 57 (`exec_python`)

**Проблема:** `exec_python` ждёт только загрузки `ctypes` модуля Python:
```python
result = self._session.evaluate(
    "Module.isLoaded('ctypes') ? 'ready' : 'wait'")
```
Но `ctypes` грузится РАНЬШЕ чем `renpy`. Агент (`agent.py`) делает
`import renpy` в самом начале, и если модуль ещё не загружен — падает
с `ImportError`. `_inject_agent` ретраит 60 секунд вслепую.

**Решение:** В `exec_python` ждать и `renpy` тоже:
```python
result = self._session.evaluate(
    "Module.isLoaded('ctypes') && Module.isLoaded('renpy') "
    "? 'ready' : 'wait'")
```

---

### БАГ 9 — FontGroup диапазоны перекрываются — Статус: ✅ Готово

**Файл:** `app/engines/renpy/agent.py` строки 318-319, `parser.py` 539-540

**Проблема:** FontGroup делает:
```python
fg.add(base, 0x0000, 0x00FF)       # оригинальный шрифт — Latin
fg.add(_OB_FONT, 0x0000, 0x10FFFF) # NotoSans — ВСЁ включая Latin
```
Диапазоны 0x00-0xFF перекрываются. Ren'Py FontGroup берёт первый
совпавший диапазон — работает (Latin из base), но хрупко.

**Решение:** Сузить диапазон NotoSans до `0x0100-0x10FFFF` (без Latin):
```python
fg.add(_base, 0x0000, 0x00FF)
fg.add(_ob_fallback_font, 0x0100, 0x10FFFF)
```

---

### БАГ 10 — spawn() не вызывает device.attach() [КРИТИЧНЫЙ] — Статус: ✅ Готово

**Файл:** `app/transport/frida_rpc/injector.py` (`PythonInjector.spawn`)

**Проблема:** `spawn()` создавал suspended процесс через `device.spawn(argv)`,
но НЕ вызывал `device.attach(pid)`. `self._session` оставался `None`.
Дальше в `tentacle.launch`:
1. `injector.spawn(...)` — suspended процесс создан, `_session=None`
2. `injector.resume_pid(pid)` — resume, `_session` всё ещё `None`
3. `_inject_agent(wait=60.0)` → `exec_python()` падает `RuntimeError("not attached")`,
   цикл крутит 60 сек с `time.sleep(1.0)` → **GUI зависает на минуту**.
4. В конце: «Не удалось внедрить агента: not attached»

Правильный Frida паттерн — `spawn → attach → resume`. Шаг `attach` был пропущен.

**Решение:** В `spawn` сразу создать сессию:
```python
def spawn(self, argv, cwd=""):
    device = self._get_device()
    pid = device.spawn(argv)
    self._pid = pid
    self._session = device.attach(pid)   # ← добавлено
    return pid
```

---

### БАГ 11 — exec_python: используется Session.evaluate (которого нет) [КРИТИЧНЫЙ] — Статус: ✅ Готово

**Файл:** `app/transport/frida_rpc/injector.py` (`exec_python` + `python_version`)

**Симптом у пользователя:** `Не удалось внедрить агента: Frida-ошибка:
'Session' object has no attribute 'evaluate'`

**Проблема:** В старом коде и `exec_python`, и `python_version` вызывают
`self._session.evaluate(js_code)` — но у Frida **Session** НЕТ метода
`evaluate`. Frida API работает иначе:
```
device.spawn / device.attach   →  Session
session.create_script(source)  →  Script
script.load()                  →  активен
script.exports_sync.fn(...)    →  синхронный RPC-вызов JS-функции
```
То есть весь `exec_python` был написан против выдуманного API. Каждая
попытка инъекции сразу падала в `except Exception` и `exec_python`
молча возвращал 1 → `_inject_agent` писал generic «агент вернул ошибку
(renpy ещё не готов?)». Реальная причина скрывалась.

Также монолитно были зашиты (после прошлых фикс):
- **`Module.isLoaded('renpy')` / `Module.isLoaded('ctypes')`** — никогда
  не true: `renpy` это Python-пакет, `ctypes` — реальное имя `_ctypes.pyd`.
  цикл ожидания крутил впустую 10 секунд (но даже если wait timed out,
  дальше всё равно не работало из-за `evaluate`).
- **`Module.findExportByName('python*.dll', ...)`** — Frida НЕ поддерживает
  wildcard, ища литерал `python*.dll` (не существует). Всегда null.
- **JS всегда возвращал `0;`** — `exec_python` не видел реальный rc
  `PyRun_SimpleString` (-1 при Python-креше агента).

**Решение:** Полная переписка `injector.py` через правильный Frida-паттерн:

1. `__init__`: добавить `self._script = None`, `self._last_error = ""`.
2. Создать модульный JS `_HELPER_JS` — загружается один раз в Session,
   предоставляет `rpc.exports`:
   - `isReady()` — нашёл `PyRun_SimpleString`?
   - `loadedModules()` — список загруженных модулей (для диагностики)
   - `execPython(code)` — выполнение кода, возвращает int rc (0/−1/−2)
   - `pythonVersion()` — строка версии CPython
3. `_load_helper()`: `session.create_script(_HELPER_JS)` → `script.load()`.
4. JS по `_findInPythonDlls` ищет сначала `findByName(null)`, потом перебирает
   типичные python3XX.dll/libpython*.dll, потом`Process.enumerateModules*()`
   для фоллбэка по `python*`/`libpython*`.
5. `spawn`: spawn → attach → `_load_helper` (сразу).
6. `attach`: attach → `_load_helper`.
7. `exec_python`:
   - ждёт `is_ready()` до `wait_python` (0.3с интервал)
   - если не готов — собирает `loaded_modules()` и пишет в `_last_error`
   - вызывает `exec_python(code)` через `script.exports_sync.exec_python(code)`
   - возвращает реальный rc; при ошибке сохраняет текст в `_last_error`
8. Возвращаемые коды:
     - `0` успех
     - `-1` Python-исключение в агенте (смотри stderr Ren'Py)
     - `-2` PyRun_SimpleString не найден (диагностика — `loaded_modules`)
     - `-3` Session/Script-ошибка (в `_last_error`)
9. `python_version`: через `script.exports_sync.python_version()`.
10. `is_alive`: вызывает `is_ready()` в try — отпадает, если session умерла.
11. `detach`: unload script, detach session.

**В `tentacle._inject_agent`** различаем типы ошибок для пользователя:
- rc 0 → «Агент внедрён (CPython ...)»
- rc −1 → «Python-исключение при выполнении агента (смотри лог Ren'Py в stderr игры)»
- rc −2 → «PyRun_SimpleString не найден — {loaded_modules}»
- rc −3 → «Frida-ошибка: {last_error}»
- прочее → «неизвестный код {rc}»

---

## Порядок выполнения (важно!)

1. ✅ БАГ 1 — Frida get_local_device (injector.py) — без этого не запустится
2. ✅ БАГ 10 — spawn() не вызывает device.attach() — без этого инъекция не работает
3. ✅ БАГ 11 — exec_python: Session.evaluate не существует — переписан через Script + RPC
4. ✅ БАГ 5 — Путь к шрифту (tentacle.py) — без этого шрифт не копируется
5. ✅ БАГ 2 — .rpyc на диске (parser.py `_iter_rpy` + `extract`) — кол-во текста
6. ✅ БАГ 3 — Dialogues regex (parser.py `_extract_line`) — кол-во текста
7. ✅ БАГ 4 — Правильная вкладка читов (engines/renpy/__init__.py) — читы
8. ✅ БАГ 7 — Process detection (process.py) — автозапуск/attach
9. ✅ БАГ 6 — Autowatch для Ren'Py (live_tab.py) — автозапуск
10. ✅ БАГ 9 — FontGroup диапазоны (agent.py + parser.py) — стабильность шрифта

---

## Реализация (что сделано)

Все 11 багов исправлены. Изменённые файлы:

### `app/transport/frida_rpc/injector.py` (БАГ 1 + 8 + 10 + 11)

Полностью переписан.

- `__init__`: добавлены `self._script = None`, `self._last_error = ""`
- `_get_device()` — кеширует `frida.get_local_device()` (вместо `get_usb_device`, БАГ 1)
- `_HELPER_JS` — модульный JS-скрипт с `rpc.exports` {isReady, loadedModules,
  execPython, pythonVersion}. Кеш в `_pyRunAddr`. Поиск символа через
  `findByName(null)` → список `python3XX.dll`/`libpython*.dll`/`.so` →
  фоллбэк по `Process.enumerateModules*()` с фильтром `python*`/`libpython*`.
- `_load_helper()`: `session.create_script(_HELPER_JS).load()` (БАГ 11 —
  Session.evaluate не существует; правильный путь через Script RPC)
- `spawn`: spawn → `device.attach(pid)` (БАГ 10) → `_load_helper()`.
- `attach`: attach → `_load_helper()`.
- `exec_python`:
  - ждёт `exports_sync.is_ready()` до `wait_python` (0.3с интервал)
  - не готов → `-2`, в `_last_error` пишет `loaded_modules()`
  - вызывает `exports_sync.exec_python(code)`, возвращает int rc
  - Session-ошибка → `-3`, текст в `_last_error`
  - Возвращаемые коды: 0 = успех; -1 = Python-креш ( смотри stderr); -2 = не
    найден PyRun_SimpleString (смотри модули); -3 = Session-ошибка
- `python_version`: через `exports_sync.python_version()`.
- `is_alive`: вызывает `is_ready()` в try — отваливается, если session пала.
- `detach`: unload script, detach session.

### `app/engines/renpy/tentacle.py` (БАГ 5)
- `install_font`: путь к шрифту исправлен с `.., "assets", "fonts"` на `"..", "..", "core", "assets", "fonts"`
- Было: `app/engines/assets/fonts/` (не существует) → Стало: `app/core/assets/fonts/` (реальный шрифт)

### `app/core/renpy/parser.py` (БАГ 2 + 3 + 9)
- `_iter_rpy`: добавлен yield для файлов `.rpyc` (раньше только `.rpy`)
- `extract()`: третья ветка `elif path.endswith(".rpyc"):` — парсит .rpyc с диска через `_unpickle_rpyc` + `_walk_ast`
- Добавлен `_DLG_SKIP_RE` — regex для отсева ключевых слов Ren'Py (define/label/scene/show/...)
- Добавлен `RE_DIALOGUE` — matching `e "text"`, `"text"`, `character "text"`, `extend "text"`
- `_extract_line`: добавлена проверка диалоговой формы через RE_DIALOGUE (после RE_OLD/RE_CHOICE)
- `_ACTIVATE_TEMPLATE`: диапазон NotoSans 0x0000-0x10FFFF → 0x0100-0x10FFFF (без перекрытия с Latin)
- Тесты 23/23 passed (e "Hello", "Hello", eileen "Hi there", define e = Character(...), play music "...", $ x = "hello" и т.д.)

### `app/engines/renpy/agent.py` (БАГ 9)
- `_patch_text`: FontGroup.add(_OB_FONT, 0x0100, 0x10FFFF) (раньше 0x0000, 0x10FFFF — перекрытие)
- `_patch_font`: та же правка

### `app/engines/renpy/__init__.py` (БАГ 4)
- `ui_tabs`: вместо `from app.ui.cheat_tab import CheatTab` (RPG Maker) →
  `from app.ui.renpy_cheat_tab import VariablesTab, TriggersTab`
- Возвращает 3 вкладки: translate, VariablesTab (var_set name=...), TriggersTab (bool)

### `app/core/process.py` (БАГ 7)
- `_looks_like_renpy`: добавлена проверка `game/ + lib/` папок рядом с exe (классическая поставка Ren'Py)
- Добавлена проверка .rpyc/.rpa в game/ (более строгий признак)
- Раньше детектило только игры с "renpy" в имени exe или папкой `renpy/` рядом с exe

### `app/ui/live_tab.py` (БАГ 6)
- `_autowatch_tick`: убран ранний return для не-rpgmaker — теперь обрабатывает `renpy` тоже
- Для renpy: `_attach_auto(pid, 0)` — Frida attach прямо по PID, port не нужен

## Тестирование

После исправлений проверить:
- `python -m pytest tests/test_renpy*.py -v` (если тесты есть)
- Ручной запуск: загрузить Ren'Py игру → Извлечь → проверь кол-во строк
- Live: Запустить игру → агент внедряется → текст переводится
- Читы: VariablesTab/TriggersTab открываются → переменные читаются
- Шрифт: кириллица отображается, Latin — из оригинального шрифта

## Заметки для продолжающей ИИ модели

- Работай ТОЛЬКО с файлами Ren'Py (список выше). RPG Maker / Twine не трогать.
- `app/ui/cheat_tab.py` — вкладка ДЛЯ RPG MAKER (index= команды).
  `RPG Maker не трогать.
- Возврат `app/ui/renpy_cheat_tab.py` — вкладка ДЛЯ Ren'Py (name= команды).
- Шрифт реально в `app/core/assets/fonts/NotoSans-Regular.ttf`.
- Файлы `_protect_interp`/`_restore_interp` в tentacle.py — защита
  Ren'Py-интерполяции [..]/{..} от переводчика — работают правильно.
- `agent.py` — полиглот Py2/Py3 (нет f-string, только % форматирование).
- `rpa.py` — чтение .rpa архивов v1/v2/v3, менять осторожно.
- Проговаривание симптом на языке оригинала:
  - "device not found" → БАГ 1 (Frida USB → local)
  - "not attached" → БАГ 10 (spawn не вызывает attach, _session=None)
  - "'Session' object has no attribute 'evaluate'" → БАГ 11 — у Session НЕТ
    evaluate; весь exec_python переписан через Session.create_script()
    → Script.load() → script.exports_sync.fnname()
  - "агент вернул ошибку (renpy ещё не готов?)" → старый generic текст;
    после БАГ 11 будет реальная причина в сообщении:
      rc −1: Python-креш агента — смотри stderr Ren'Py
      rc −2: PyRun_SimpleString не найден — смотри loaded modules
      rc −3: Frida-ошибка — смотри `_last_error` (текст пишется в лог)
  - "1500 вместо 18000" → БАГ 2 + 3 + дедупликация
  - "читы не работают / switch/var" → БАГ 4 (RPGM tab вместо Ren'Py)
  - "квадратики / ??? вместо кириллицы" → БАГ 5 + 9 (шрифт)
  - "GUI зависает на минуту при запуске" → БАГ 10 (cycle крутит вслепую
    при None сессии) и БАГ 11 (10 сек wait loop без реального состояния)

- Frida API критичный момент:
  - `device.attach(pid)` возвращает **Session** (НЕ имеет `.evaluate`)
  - `session.create_script(source)` → **Script**; `script.load()` активирует
  - RPC: `script.exports_sync.snake_name(args)` → вызывает JS `rpc.exports.snakeName`
    (Frida автоматически конвертирует snake_case ↔ camelCase)
  - Session.execute / Session.evaluate НЕ существуют — это воображаемый API.
    Любой код с `self._session.evaluate(...)` баг и должен быть переписан
    через create_script + exports.

- Если после всех фиксов «Агент внедрён (CPython ...)» но перевод не идёт:
  1. Проверь, что провайдер перевода настроен и `engine.ping() == True`
     (см. `welcome_tab._action_live_launch` — fallback `lambda text: text`).
  2. Агент подключается к TCP-серверу tentacle (port = `self._server.port`).
     Лог tentacle «Агент игры подключился.» должен появиться.
  3. Иначе: возможно агент работает, но text hook не находит строки в кэше
     переводчика, или обходит его — `_patch_text` отстутствует/не успел.
  4. Если `Agent внедрён` нет, но rc=-2 (PyRun не найден) — нужно посмотреть,
     как в данной сборке Ren'Py встроен Python. Список загруженных модулей
     пишется в `_last_error` tentacle. Ищи отличия от `python*.dll`.

- Если PyRun_SimpleString не находится совсем (сборка Ren'Py статически
  линкует Python) — нужен другой подход впрыска: навигация по IAT,
  `Py_GetVersion` как маркер, или расчёт смещения вручную. Это следующий
  уровень — НЕ тривиально, вынести в отдельную ветку/рsearch.