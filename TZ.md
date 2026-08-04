# TZ — Архитектура движков и дорожная карта

> Актуально для версии **0.5.0** · Обновлено: 2026-08-04

---

## 1. Поддерживаемые движки

| Движок | Язык данных | Файловый режим | Живой перевод | Читы/инструменты |
|---|---|---|---|---|
| RPG Maker MV/MZ | JSON (`www/data`) | ✅ extract/apply | ✅ CDP (Chromium/NW.js) | ✅ переменные, карты, сейвы, ресурсы, шрифт |
| Ren'Py | Python (`.rpy` → bytecode) | ✅ extract/apply | ✅ Frida + Python-агент в процессе | ✅ переменные, золото, heal, телепорт |
| Twine (SugarCube) | HTML+JS (`<tw-storydata>`) | ✅ extract/apply | ✅ HTTP+WS мост (любой браузер) | ✅ редактор сейвов (LZ-String) |
| TyranoScript / TyranoBuilder | KAG-подобный `.ks`/`.tjs` | ✅ extract/apply | ✅ CDP (NW.js) | ⛔ (переменных движка нет) |

Кэш переводов — единый для всех движков: `octopus_cache.json` в папке игры (см. раздел 4).

---

## 2. Контракт движкового модуля

Чтобы добавить новый движок, достаточно:

1. **Класс `EngineModule`** (`app/engines/base.py`):
   - `key` — `'rpgmaker'`, `'renpy'`, `'twine'`, `'tyrano'`, …;
   - `title` — отображаемое имя;
   - `features` — множество `{"files"}`, плюс `"live"`, `"cheats"`, `"resources"`, `"font"`, `"maps"`, …;
   - `detect(game_dir) -> int` — вес уверенности (0 = не наш движок);
   - `extract(game_dir) -> list[TranslationEntry]`;
   - `apply(game_dir, entries, **kwargs) -> dict` — статистика;
   - `ui_tabs(main_window)` — движковые вкладки GUI (читы, карты, сейвы, …).
2. **Регистрация** — `app/engines/registry.py` (`MODULES`, `detect_engine`).
3. **Парсер данных** — `app/core/<engine>/parser.py`.
4. **Щупальце** для живого перевода — `app/core/tentacles/` (CDP-база в
   `cdp_base.py`, остальное — `create_tentacle` в `app/core/tentacles/__init__.py`),
   подключение и жизненный цикл — `app/core/session.py` (`GameSession`).

Главный вопрос для каждого кандидата — насколько просто написать `extract/apply`;
живой перевод — бонус, который не блокирует релиз.

---

## 3. Провайдеры перевода

Реестр — `app/core/translate/engines.py` (`PROVIDERS`):

| Ключ | Провайдер | Тип |
|---|---|---|
| `honyaku` | Argos Translate / NLLB (CTranslate2) | офлайн |
| `google_free` | Google Translate, бесплатный endpoint | сеть |
| `bing` | Bing Translator, бесплатный endpoint | сеть |
| `rotate` | чередование Google+Bing с fallback | сеть |
| `ai` | OpenAI-совместимый API | сеть |

Офлайн-движок — `app/translators/honyaku/` (скачивание моделей, конвертация в
CTranslate2, батчи). Поверх: глоссарий, память переводов (SQLite), маскирование
игровых кодов, AI-корректор (`app/core/translate/`).

---

## 4. Единый кэш переводов

Все движки пишут один файл в папке игры:

```json
{ "format": 1, "engine": "tyrano", "pairs": {"оригинал": "перевод"}, "skip": [] }
```

- Реализация — `app/core/translate/game_cache.py` (`load_game_cache`,
  `save_game_cache`; атомарная запись через tmp + rename).
- Старые кэши движков (`.translation_cache.json`, `tyrano_cache.json` и др.)
  читаются автоматически как fallback и мигрируют при следующем сохранении.
- Мусор фильтруется: identity-записи, нестроковые значения, ключи > 500 симв.

---

## 5. Дорожная карта (бэклог)

Выполнено: TyranoScript (файлы + live) — релиз 0.4/0.5; полировка (единый кэш,
переключатель перевода на лету, drag-and-drop, «О программе»/«Что нового») — 0.5.

| Кандидат | Формат | Файл-режим | Live | Сложность | Приоритет |
|---|---|---|---|---|---|
| RPG Maker XP/VX/Ace | Ruby Marshal (`.rvdata*`) + `.rgss*` | ✅ да | 🟡 патч | средняя | **1** |
| KiriKiri / KAG | `.xp3` + `.ks` | ✅ да | 🟡 патч | средняя | **2** |
| NScripter / ONScripter | `nscript.dat` | ✅ да | ⛔ | низкая | 3 |
| Wolf RPG Editor | `.arc` | 🟡 с распаковкой | ⛔ | высокая | 4 |
| YU-RIS (AliceSoft) | `.ybn` / `.ypf` | ✅ да | ⛔ | средняя | 4 |
| Godot | `.tscn` / `.po` | ✅ да | ⛔ | средняя | 4 |
| Pygame и др. Python-движки | `.py` / `.json` | 🟡 нестабильно | 🔴 | высокая | 5 |
| Unity / Unreal | `.assets` / бинарный | 🔴 | 🔴 | очень высокая | — |

Для классических RPG Maker есть готовые Python-решения Marshal/RGSSAD
(`RPGMTL`, `rvpacker`) — можно переиспользовать подход. Live-режим для не-Python
движков дорог: файловый (патчевой) режим приносит 90% ценности.

---

## 6. Разработка и тесты

- Тесты: `python run_tests.py` — 8 файлов (ядра, щупальца, переводчики, GUI offscreen).
- CI (GitHub Actions, `.github/workflows/ci.yml`): тесты + сборка exe на Windows.
- Сборка: `build.bat` / `build_app.py` (PyInstaller + Inno Setup), версия — из `app/__init__.py`.

*Смежные материалы: README.md, README.en.md, CHANGELOG.md, app/engines/base.py, app/engines/registry.py.*