<p align="center">
  <img src="ico.ico" width="96" alt="OctopusBridge" />
</p>

<h1 align="center">OctopusBridge</h1>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0-blue.svg" alt="License"></a>
  <a href="https://ko-fi.com/k_k"><img src="https://img.shields.io/badge/Ko--fi-support-F16061?logo=ko-fi&logoColor=white" alt="Ko-fi"></a>
  <a href="https://github.com/DezFix/OctopusBridge/releases"><img src="https://img.shields.io/github/v/release/DezFix/OctopusBridge?color=blue" alt="Release"></a>
</p>

<p align="center">
  Translate and mod PC games.<br>
  Supported: <b>RPG Maker MV/MZ</b> (including Electron builds), <b>Ren'Py</b>, <b>Twine</b> and <b>TyranoScript</b>.<br>
  Translation is <b>batch-based</b>: text is extracted from the game files, translated and written back before the game is launched.
</p>

<p align="center">
  <a href="README.ru.md">Русская версия</a>
</p>

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

- Windows 10/11 (64-bit).
- ~500 MB of disk space.

## Installation

1. Download `OctopusBridge.exe` from the releases and run it.

> The EXE is unsigned — Windows SmartScreen may show a warning («More info → Run anyway»).

## Quick start

1. **Open a game** — drag the game folder or `Game.exe` into the app window (or into the list on the "Projects" tab).
2. **Translate** — "File translation" tab: extract the text, press "Translate", then "Apply" to write the translation back into the game.
3. **Cheats / maps / saves** — appear in the engine tabs after opening a project: cheats and maps work with a running game, the save editor works with files directly.

## Notes

- Google/Bing are unofficial free endpoints: no keys, but they may limit volume. For big projects, connect an AI provider in the settings.
- Injections modify the game process in memory — use the tool only on games you own or are allowed to modify.
- Changelog — [CHANGELOG.md](CHANGELOG.md).

## License

GPL-3.0 — see [LICENSE](LICENSE). Projects you create in the app remain yours.
