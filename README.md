# OctopusBridge

Инструмент для перевода и модификации игр на ПК: **RPG Maker MV/MZ**, **Ren'Py** и **Twine**.
Перевод происходит в реальном времени (через встраивание в процесс игры) и в пакетном режиме (по файлам).

> **Статус: 0.2.0** — стабильно работают ядра RPG Maker и Ren'Py, Twine — экспериментальный.
> Планируется поддержка других движков визуальных новелл.

---

## Возможности

- **Пакетный перевод файлов** — извлечение текста из игры, перевод через выбранный провайдер, восстановление старых переводов при повторном извлечении, экспорт/импорт CSV.
- **Живой перевод (реалтайм)** — текст переводится прямо в игре:
  - RPG Maker MV/MZ — через CDP (Chromium/NW.js), читы, карты, редактор сейвов, ресурсы;
  - Ren'Py — через Frida-инъекцию Python-агента, читы (переменные/золото), подмена шрифта;
  - Twine — через локальный HTTP+WS мост (любой браузер), редактор сейвов SugarCube.
- **Провайдеры перевода**: Argos Translate (офлайн), Google Translate (бесплатный endpoint), Bing Translator (бесплатный endpoint), чередование Google+Bing с fallback, OpenAI-совместимый API (AI).
- **Глоссарий и память переводов** — единая база переводов (SQLite) на все проекты, маскирование кодов (`\C[8]`, `<center>` и т.п.).
- **i18n интерфейса**: русский / английский.
- Тёмная тема, трей, автозапуск, аварийный лог в `%APPDATA%\OctopusBridge\crash.log`.

## Поддерживаемые движки

| Движок | Статус | Технология |
|---|---|---|
| RPG Maker MV / MZ | ✅ стабильно | CDP (Chromium) |
| Ren'Py | ✅ стабильно | Frida + Python-агент |
| Twine (SugarCube) | 🧪 экспериментально | HTTP + WebSocket |

## Системные требования

- Windows 10/11 (64-бит)
- ~500 МБ диска (плюс языковые пакеты Argos ~100–300 МБ каждый)
- Для Ren'Py нужна инъекция через Frida — антивирус может запросить подтверждение

## Установка

1. Скачайте установщик `OctopusBridge-<version>-Setup.exe` (Inno Setup) из релизов.
2. Запустите и следуйте инструкциям.
3. При первом запуске приложение предложит скачать офлайн-языковые пакеты Argos (можно отказаться и использовать Google/Bing/AI).

> EXE не подписан — Windows SmartScreen может показать предупреждение («Дополнительно → Выполнить в любом случае»).

## Использование

1. **Открыть игру** — перетащите `Game.exe` (или папку игры) в окно приложения, либо выберите через «Обзор».
2. **Файлы** — вкладка «Файлы»: извлеките текст, переведите, внедрите обратно.
3. **Реалтайм** — запустите игру, нажмите «Live» — текст в игре начнёт переводиться.
4. **Читы / карты / сейвы** — доступны во вкладках движка после открытия проекта.

## Сборка из исходников

```bat
git clone <repo-url>
cd OctopusBridge
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_tests.py     :: тесты
build.bat                              :: exe в dist\
build.bat --installer                  :: + установщик Inno Setup
```

Управление сборкой — `build_app.py` (`python build_app.py --help`).
Версия берётся автоматически из `app/__init__.py` (`__version__`) и подставляется в exe-ресурсы и установщик.

## Тестирование

```bat
.venv\Scripts\python run_tests.py
```

14 тестовых файлов покрывают ядра, щупальца (CDP/Frida), переводчиков, GUI (offscreen).
Интеграционные тесты (`test_core`, `test_engines`, `test_gui`) дополнительно прогоняются на реальной
игре-образце, если она есть на машине разработчика (см. `tests/_test_game.py`); в CI эти тесты
пропускаются.

## Ограничения и примечания

- Только Windows (Frida-инъекция и CDP-запуск заточены под ПК).
- Google/Bing — неофициальные бесплатные endpoint'ы: работают без ключей, но могут быть
  ограничены по объёму или временно недоступны. Для стабильного объёма используйте Argos или AI.
- Инъекции модифицируют процесс игры в памяти; используйте только для игр, которые вам принадлежат
  или на модификацию которых вы имеете разрешение.

## Дорожная карта (0.3+)

- Поддержка других движков (Wolf RPG, TyranoBuilder, VN-движки)
- AI-корректор перевода в пакетном режиме
- Проверка обновлений
- Цифровая подпись установщика

## Лицензия

MIT — см. [LICENSE](LICENSE). Проекты, которые вы создаёте в приложении, остаются вашими.

## Разработка

Технические заметки и статус ядра Ren'Py — [TZ.md](TZ.md), новые задачи — [TZ_new.md](TZ_new.md).

---

# English

**OctopusBridge** is a PC game translation & modding tool for **RPG Maker MV/MZ**, **Ren'Py** and **Twine**.
It translates games in real time (in-process injection) and in batch (file-based).

> **Status: 0.2.0** — RPG Maker and Ren'Py cores are stable, Twine is experimental.
> Support for more game engines is planned.

## Features

- **Batch file translation** — extract game text, translate via a provider, restore old translations, CSV import/export.
- **Live in-game translation**:
  - RPG Maker MV/MZ via CDP (Chromium/NW.js) — cheats, maps, save editor, resources;
  - Ren'Py via Frida Python-agent injection — cheats (variables/gold), font replacement;
  - Twine via a local HTTP+WS bridge (any browser) — SugarCube save editor.
- **Translation providers**: Argos Translate (offline), Google Translate (free endpoint), Bing Translator (free endpoint), Google+Bing rotation with fallback, OpenAI-compatible API.
- **Glossary & translation memory** — shared SQLite database, code masking (`\C[8]`, `<center>`, …).
- UI in Russian/English, dark theme, tray, first-run setup, crash log at `%APPDATA%\OctopusBridge\crash.log`.

## Supported engines

| Engine | Status | Technology |
|---|---|---|
| RPG Maker MV / MZ | ✅ stable | CDP (Chromium) |
| Ren'Py | ✅ stable | Frida + Python agent |
| Twine (SugarCube) | 🧪 experimental | HTTP + WebSocket |

## Requirements

- Windows 10/11 (x64)
- ~500 MB disk + Argos language packs (~100–300 MB each, optional)
- Frida injection for Ren'Py — antivirus may prompt for confirmation

## Install

1. Download `OctopusBridge-<version>-Setup.exe` from releases.
2. Run the installer and follow the wizard.
3. On first launch the app offers to download offline Argos language packs (skip → Google/Bing/AI).

> The EXE is unsigned — SmartScreen may warn («More info → Run anyway»).

## Build from source

```bat
git clone <repo-url>
cd OctopusBridge
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_tests.py
build.bat
```

Build orchestration: `build_app.py` (`python build_app.py --help`). The version comes from
`app/__init__.py` (`__version__`) and is embedded into the exe resources and the installer.

## Tests

```bat
.venv\Scripts\python run_tests.py
```

14 test files cover cores, tentacles (CDP/Frida), translators and GUI (offscreen).
Integration tests (`test_core`, `test_engines`, `test_gui`) additionally run against a sample game
if present on the developer machine (see `tests/_test_game.py`); they are skipped in CI.

## Notes

- Windows only.
- Google/Bing are unofficial free endpoints — no keys, but may be rate-limited or temporarily down.
  For heavy workloads use Argos or an AI provider.
- Injection modifies the game process in memory; use only on games you own or are allowed to mod.

## Roadmap (0.3+)

- More engines (Wolf RPG, TyranoBuilder, VN engines)
- AI corrector for batch translation
- Update checker
- Signed installer

## License

MIT — see [LICENSE](LICENSE). Projects you create in the app remain yours.

## Development

Ren'Py core notes & status — [TZ.md](TZ.md), new tasks — [TZ_new.md](TZ_new.md).
