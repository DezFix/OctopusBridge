[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/k_k)

# OctopusBridge

Translate and mod PC games. Supported: **RPG Maker MV/MZ** (including Electron builds), **Ren'Py**, **Twine** and **TyranoScript**.

Translation is **batch-based**: text is extracted from the game files, translated and written back before the game is launched.

Version:  [Русская версия](README.md)

## Features

- **Batch translation** — extract game text, translate, write it back, CSV import/export. Old translations are restored on re-extraction.
- **Fast translation** — batches of up to 100 lines, several batches in parallel (~28,600 lines/min on Google's free endpoints).
- **No keys, no sign-up** — free Google endpoints (a cascade of three, with built-in rate-limit protection) and Bing; for heavy workloads connect an AI provider (OpenAI-compatible API).
- **AI corrector** — polish translations with glossary and context, review diffs before applying.
- **Cheats & tools** — per engine: variables, gold, teleport, map editor, save editor, resource browser, font patch.
- **Glossary & translation memory** — shared database across all projects (SQLite), game-code masking (`\C[8]`, `<center>`, …).
- **Unified translation cache** — all engines write one `octopus_cache.json` in the game folder; legacy caches are migrated automatically.
- **Nice UI** — dark theme, Russian/English, system tray, drag-and-drop, About dialog with a changelog.

## Engines

| Engine | Status |
|---|---|
| RPG Maker MV / MZ | stable (incl. Electron builds with `app.asar`) |
| Ren'Py | stable |
| TyranoScript / TyranoBuilder | supported |
| Twine (SugarCube) | experimental |

## Requirements

- Windows 10/11 (x64).
- ~500 MB disk.

## Install

1. Download `OctopusBridge.exe` from the releases and run it.

> The EXE is unsigned — Windows SmartScreen may warn («More info → Run anyway»).

## Quick start

1. **Open a game** — drag the game folder or `Game.exe` into the app window (or into the Projects tab list).
2. **Translate** — the Translate tab: extract the text, press Translate, then Apply to write the translation into the game.
3. **Cheats / maps / saves** — appear in the engine tabs after a project is opened: cheats and maps work with the running game, the save editor works directly on save files.

## Notes

- Google/Bing are unofficial free endpoints — no keys, but may be rate-limited. For heavy workloads connect an AI provider in the settings.
- Injection modifies the game process in memory; use the tool only on games you own or are allowed to mod.
- Version history: [CHANGELOG.md](CHANGELOG.md).

## License

GPL-3.0 — see [LICENSE](LICENSE). Projects you create in the app remain yours.