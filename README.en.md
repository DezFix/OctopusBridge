[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/k_k) · Support the project — [ko-fi.com/k_k](https://ko-fi.com/k_k)

# OctopusBridge

Translate and mod PC games. Supported: **RPG Maker MV/MZ**, **Ren'Py**, **Twine** and **TyranoScript**.

Text is translated in two ways: **in real time** inside the game, and **in batch** from files.

Version: **0.5.0** · [Русская версия](README.md)

## Features

- **Batch translation** — extract game text, translate, write it back, CSV import/export. Old translations are restored on re-extraction.
- **Live translation** — in-game text is translated on the fly; translation can be toggled off/on at any time without stopping the game.
- **Cheats & tools** — per engine: variables, gold, map editor, save editor, resource browser, font patch.
- **Translation providers** — Argos Translate / NLLB (offline), Google Free, Bing, Google+Bing rotation, OpenAI-compatible API.
- **Glossary & translation memory** — shared database across all projects (SQLite), game-code masking (`\C[8]`, `<center>`, …).
- **Unified translation cache** — all engines write one `octopus_cache.json` in the game folder; legacy caches are read and migrated automatically.
- **Nice UI** — dark theme, Russian/English, system tray, drag-and-drop, About and What's New dialogs.

## Engines

| Engine | Status | Transport |
|---|---|---|
| RPG Maker MV / MZ | stable | CDP (Chromium/NW.js) |
| Ren'Py | stable | Frida + in-process Python agent |
| Twine (SugarCube) | experimental | HTTP + WebSocket bridge |
| TyranoScript / TyranoBuilder | supported | CDP (NW.js) |

## Requirements

- Windows 10/11 (x64).
- ~500 MB disk + optional Argos offline packs (100–300 MB each).
- Ren'Py requires Frida injection — antivirus may prompt for confirmation.

## Install

1. Download the installer `OctopusBridge-0.5.0-Setup.exe` from the releases and run it.
2. On first launch the app offers to download the offline translator (skip → Google/Bing/AI).

> The EXE is unsigned — Windows SmartScreen may warn («More info → Run anyway»).

## Quick start

1. **Open a game** — drag the game folder or `Game.exe` into the app window (or into the Projects tab list).
2. **Files** — the Files tab: extract text, translate, write it back.
3. **Live** — launch the game through the app: text starts translating automatically.
4. **Cheats / maps / saves** — appear in the engine tabs after a project is opened.

## Build & test from source

Requires Python 3.13.

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_tests.py       :: tests (8 files)
.venv\Scripts\python main.py            :: run the app
build.bat                               :: exe into dist\
build.bat --installer                   :: + Inno Setup installer
```

Builds are driven by `build_app.py` (`python build_app.py --help`); the version comes from `app/__init__.py` and is embedded into the exe resources and the installer. CI (GitHub Actions) runs tests and the exe build on Windows.

## Notes

- Google/Bing are unofficial free endpoints — no keys, but may be rate-limited. For heavy workloads use offline Argos or an AI provider.
- Injection modifies the game process in memory; use the tool only on games you own or are allowed to mod.
- Version history: [CHANGELOG.md](CHANGELOG.md).

## Development

- Engine architecture and roadmap: [TZ.md](TZ.md).

## License

MIT — see [LICENSE](LICENSE). Projects you create in the app remain yours.