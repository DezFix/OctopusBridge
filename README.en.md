# OctopusBridge

Translate and mod PC games: **RPG Maker MV/MZ**, **Ren'Py**, **Twine** and **TyranoScript**.

Text is translated in real time inside the game, or in batch from files.

[Русская версия](README.md)

## Features

- **Batch translation** — extract game text, translate, write it back, CSV import/export.
- **Live translation** — in-game text is translated on the fly; can be toggled off/on without stopping the game.
- **Cheats & tools** — per-engine: variables, gold, map editor, save editor, resource browser.
- **Translation providers** — Argos Translate (offline), Google Free, Bing, Google+Bing rotation, OpenAI-compatible API.
- **Glossary & translation memory** — shared SQLite database, game-code masking (`\C[8]`, `<center>`, …).
- **UI** — Russian/English, dark theme, system tray, auto-start.

## Engines

| Engine | Status | Technology |
|---|---|---|
| RPG Maker MV / MZ | stable | CDP (Chromium/NW.js) |
| Ren'Py | stable | Frida + Python agent |
| Twine (SugarCube) | experimental | HTTP + WebSocket |
| TyranoScript / TyranoBuilder | stable | CDP (NW.js) |

## Requirements

- Windows 10/11 (x64).
- ~500 MB disk plus optional Argos offline packs (100–300 MB each).

## Install

1. Download the installer from the releases and run it.
2. On first launch the app offers to download the offline translator (skip → Google/Bing/AI).

> The EXE is unsigned — SmartScreen may warn («More info → Run anyway»).

## Quick start

1. **Open a game** — drag the game folder or `Game.exe` into the app window.
2. **Files** — extract text, translate, write it back.
3. **Live** — launch the game through the app: text starts translating automatically.

## Build & test from source

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_tests.py   :: tests
build.bat                            :: exe into dist\
build.bat --installer                :: + Inno Setup installer
```

Builds are driven by `build_app.py` (`python build_app.py --help`); the version comes from `app/__init__.py`.

## Notes

- Google/Bing are unofficial free endpoints — no keys, but may be rate-limited.
- Injection modifies the game process in memory; use only on games you own or are allowed to mod.
- See [CHANGELOG.md](CHANGELOG.md) for version history.

## Development

- Engine technical notes: [TZ.md](TZ.md).
- Tests: `python run_tests.py` (8 files: cores, tentacles, translators, GUI offscreen).

## License

MIT — see [LICENSE](LICENSE). Projects you create in the app remain yours.