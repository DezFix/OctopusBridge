<p align="center">
  <a href="https://github.com/DezFix/OctopusBridge/blob/main/assets/ico.ico">
    <img src="https://github.com/DezFix/OctopusBridge/raw/main/assets/ico.ico" width="96" alt="OctopusBridge logo">
  </a>
</p>

<h1 align="center">OctopusBridge</h1>

<p align="center">
  <b>AI-powered translation & modding tool for Twine, Ren'Py, RPG Maker and Tyrano games</b>
</p>

<p align="center">
  <a href="https://github.com/DezFix/OctopusBridge/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-GPL--3.0-blue.svg" alt="License">
  </a>
  <a href="https://github.com/DezFix/OctopusBridge/releases">
    <img src="https://img.shields.io/github/v/release/DezFix/OctopusBridge?color=blue" alt="Release">
  </a>
  <img src="https://img.shields.io/badge/platform-Windows%2010%2F11-blue" alt="Platform">
  <img src="https://img.shields.io/badge/lang-RU%20%7C%20EN-lightgrey" alt="Languages">
  <a href="https://ko-fi.com/k_k">
    <img src="https://img.shields.io/badge/Ko--fi-support-FF5E5B?logo=ko-fi&logoColor=white" alt="Ko-fi">
  </a>
</p>

<p align="center">
  <a href="https://github.com/DezFix/OctopusBridge/blob/main/README.ru.md">Русская версия</a>
</p>

<!-- 🖼️ Drop a GIF or screenshot of the app here — this is the single highest-impact addition you can make.
     Something like: open a project → extract text → translate → apply, 5–10 seconds, looping.
     ![demo](docs/demo.gif) -->

> **⚠️ Work in progress.** OctopusBridge is under active development. Bugs, crashes and corrupted translations are possible, especially for the **Twine** engine. Always keep a backup of your game before translating, and report any issues you find.

---

## Table of contents

- [What it does](#what-it-does)
- [Features](#features)
- [Supported engines](#supported-engines)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Notes](#notes)
- [License](#license)

---

## What it does

OctopusBridge translates and mods PC games. Translation is **batch-based**: text is extracted from the game files, translated, and written back before the game is launched — no manual copy-pasting, no editing the game's source files by hand.

---

## Features

|  |  |
|---|---|
| ⚡ **Fast batch translation** | Up to 100 lines per batch, several batches in parallel — ~28,600 lines/min on Google's free endpoints. |
| 🤖 **AI-assisted & free options** | No keys, no sign-up needed (free Google/Bing endpoints). For heavy workloads, connect any OpenAI-compatible API. |
| 🎮 **In-game cheats & tools** | Variables, gold, teleport, map editor, save editor, resource browser, font patch — per engine. |
| 📚 **Glossary & translation memory** | Shared SQLite database across all your projects, with automatic game-code masking (`\C[8]`, `<center>`, …). |
| 🧠 **AI corrector** | Polishes translations using glossary + context, and shows you a diff to review before applying. |
| 🌙 **Clean UI** | Dark theme, Russian/English, system tray, drag-and-drop, built-in changelog. |

**Under the hood:** old translations are automatically restored on re-extraction, CSV import/export is supported, and all engines share a single unified cache (`octopus_cache.json`) written to the game folder — legacy caches are migrated automatically.

---

## Screenshots

![Project list](assets/screenshots/home.png)
![Translation](assets/screenshots/translate.png)
![Main window](assets/screenshots/main.png)
![RPG Maker cheats](assets/screenshots/Cheats-rpg.png)
![Map editor](assets/screenshots/Map-rpg.png)
![Resource browser](assets/screenshots/Resource.png)
![Save editor (Twine)](assets/screenshots/Save%20editor%20Tvine.png)

---

## Supported engines

| Engine | Status |
|---|---|
| RPG Maker MV / MZ | ✅ Stable (incl. Electron builds with `app.asar`) |
| Ren'Py | ✅ Stable |
| TyranoScript / TyranoBuilder | ✅ Supported |
| Twine (SugarCube) | 🧪 Experimental |

---

## Requirements

- Windows 10/11 (64-bit)
- ~500 MB of free disk space

---

## Installation

1. Download `OctopusBridge.exe` from the [releases page](https://github.com/DezFix/OctopusBridge/releases) and run it.

> The EXE is unsigned — Windows SmartScreen may show a warning. Click **"More info" → "Run anyway"**.

---

## Quick start

1. **Open a game** — drag the game folder or `Game.exe` into the app window (or use the "Projects" tab).
2. **Translate** — go to the "File translation" tab, extract the text, press **Translate**, then **Apply** to write it back into the game.
3. **Cheats / maps / saves** — available in the engine tabs once a project is open. Cheats and maps work with a running game; the save editor works directly with save files.

---

## Notes

- Google/Bing are unofficial free endpoints — no keys required, but volume may be limited. For large projects, connect an AI provider in settings.
- Injections modify the game process in memory — only use this tool on games you own or are authorized to modify.
- Full changelog: [CHANGELOG.md](https://github.com/DezFix/OctopusBridge/blob/main/CHANGELOG.md)

---

## License

GPL-3.0 — see [LICENSE](https://github.com/DezFix/OctopusBridge/blob/main/LICENSE). Projects you create with the app remain yours.

---

<p align="center">
  ⭐ If OctopusBridge helped you, consider starring the repo — it helps others find it.<br>
  Found a bug? <a href="https://github.com/DezFix/OctopusBridge/issues">Open an issue</a> ·
  Want to support development? <a href="https://ko-fi.com/k_k">Buy me a coffee on Ko-fi</a>
</p>