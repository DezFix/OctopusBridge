# Changelog

All notable changes to the project. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: `X.Y` — `X` is the update number (new features), `Y` fixes for the last update (e.g. `154.6`).

## [7.0] — 2026-08-18

### Added
- **First-run setup wizard** (`app/ui/setup_wizard.py`): 4 steps — welcome, languages, translator provider (Google/Bing/Rotate/AI with URL/key/model), behavior (auto-launch, auto-backup). Shown once on first launch (`setup_done` flag); "Skip" and "Show setup wizard again" button in Settings. Switching the UI language inside the wizard retranslates it live.
- **More translation languages**: 20 + auto-detect (ja, zh, ko, en, ru, uk, de, fr, es, it, pt, pl, cs, ar, id, th, vi, tr, nl, sv). Language combos show localized names while codes are stored (`SOURCE_LANGS`/`TARGET_LANGS` in engines.py, `LANG_NAMES` extended for Bing); source language defaults to **auto** (auto-detect) everywhere, including new projects.
- **Font size editing on the dashboard**: the size row now has a spin box (12–64 px) in addition to A−/A+ buttons; the value is written to the game file immediately. Ren'Py `gui.text_size` detection relaxed (`define`/`default`/plain assignment, indented inside `init python:`, searched in `gui.rpy` and `screens.rpy`).
- **"Load own font…" button on the dashboard** (RPG Maker MV/MZ and Ren'Py): replaces the game fonts with the user-picked `.ttf/.otf/.woff` — for Ren'Py all fonts including Cyrillic-capable ones are replaced, originals backed up and restorable.

### Changed
- **Version scheme**: `X.Y` instead of `0.X.Y` — the first number is the update count, the second fixes for the latest update (e.g. `154.6`). Update check and build scripts handle the new format.
- **System tray removed**: closing the window always quits the app; the tray settings and code were removed (`close_to_tray` key is cleaned up on startup).
- **Translation cancel fixed**: cancel no longer kills worker threads mid-C-code (the app crashed and lost progress). Engines now raise `InterruptedError` on `cancel()`, the project is autosaved every 10 s during translation, and the project is saved before workers are stopped on exit.

## [0.6.8] — 2026-08-17

### Added
- **RPG Maker MV/MZ: one-click Cyrillic font patch** (`app/core/rpgmaker/fontpatch.py` rewritten). New `patch_font_auto` mode: the bundled NotoSans-Regular.ttf (Japanese + Cyrillic + Latin coverage) replaces the current font only when the game's font lacks Cyrillic (sfnt-cmap check; woff/woff2/corrupt files count as «no Cyrillic» — NotoSans replaces them losslessly). MV supports the `www/fonts` deploy layout; MZ writes `advanced.mainFontFilename`/`numberFontFilename` in `data/System.json`. Originals are backed up (`*.ob_backup`) and the `ob_font.json` manifest tracks added files; `restore_font()` returns them, repeated auto-patch does not duplicate the manifest.
- **Custom font file** ("Own font…" button in the resource browser) — pick any `.ttf/.otf/.woff` via file dialog; the restore button reverts to the original font.
- **Unified font block on the dashboard** (welcome tab): "Cyrillic" row + "Size" row for RPG Maker MV/MZ and Ren'Py, shown per engine/variant (`is_patched` per engine).
- **Animated UI polish**: `AnimatedComboBox` (chevron rotates 180° on open, custom-drawn), `AnimatedMenu` (check/right-arrow indicators from PNG assets), `AnimatedTabWidget` (fade transition), slide animations — applied across main window, resource browser, event editor, cheat tab, settings dialog, contexts menus.
- **QSS asset URLs fixed on Windows**: `file://` and `data:` URIs don't load in QSS on Windows — `_asset_url` now returns a plain forward-slash path.
- **Font-patch tests** (test_rpgmaker.py): MV auto-patch skips Cyrillic-capable fonts, www-deploy patch + manifest + restore round-trip, MZ System.json patch/restore.

## [0.6.7] — 2026-08-15

### Added
- **RPG Maker MV: bridge profile for the official runtime.** The stock MV runtime is a non-SDK NW.js build where remote debugging is removed — CDP is unavailable, so MV now gets an in-game HTTP bridge: the `octopus_ob.js` plugin (NW.js Node API, HTTP server on `127.0.0.1`) carries probe/eval/tr/errlog requests. Cheats, state and live translation transparently route through the bridge; the game is no longer force-restarted when it's already running without debugging. A leftover-bridge reattach path (`find_bridge_port`) is used in `launch()`/`attach()`.
- **RPG Maker MV: encrypted maps**. `MapXXX.rpgmvm` files are decrypted for extraction and re-encrypted on write (`crypto.encrypt_bytes`); `maprender.load_map`/`save_map` support them; `parser.extract`/`apply` handle the encrypted data files.
- **RPG Maker: MV/MZ variant detection** (`app/core/rpgmaker/variant.py`) — used to pick the right plugins list location (`js/plugins.js` JS-format for MV, `data/plugins.js` JSON-array for MZ), plugin call command codes (356 MV / 357, 657 MZ) and encrypted-map suffix.
- **MV live translation**: the static original→translation dictionary is embedded into the bridge plugin at apply time (`update_tr_dict`), so translations work even when the game is launched outside OctopusBridge; apply/restore register/unregister the bridge plugin idempotently (no double entries, old versions regenerated keeping the deployed dictionary).
- **Turbo speed rewritten for MV 1.6+/MZ**: instead of calling `updateMain` k times (which multiplied `requestAnimationFrame` requests exponentially and froze/crashed the game), the frame delta time is divided by k, letting the engine's own accumulator run k ticks per frame; legacy MV without an accumulator uses a guarded k-loop with requestUpdate suppression.
- **Ren'Py orphan cleanup hardened**: empty apply runs (`files == 0`) now also remove broken `ob_*.rpy`/`ob_*.rpyc` from old builds (raw multiline strings that Ren'Py 8 can't parse — «Could not parse string» crash) and self-translated duplicates (`__ob_` names that cause «A translation … already exists»); healthy files are never touched. Entries sourced from our own `ob_*` artifacts are no longer written at all.
- **NW.js profile cleanup extended**: `%LOCALAPPDATA%\User Data` (MV runtime with an empty name in package.json) is scanned; `Web Data`, `Preferences`, `Secure Preferences` are renamed alongside `Local State` when a real profile is detected.
- **MZ plugins list in `data/plugins.js`** (JSON array) is parsed; YEP-style plugin parameter *keys* are no longer extracted as translatable text (only values/strings are).

### Fixed
- `heal_all`/`clear_states` cheats no longer use the MZ-only `removeAllStates()` — states are removed via `states().forEach(removeState)` (also revives dead actors).
- `maprender`/event editor tolerate malformed event data (non-dict pages/tilesets) instead of crashing the map tab.
- Old bridge plugins with a literal `__TR_DICT__` marker (which threw ReferenceError before the HTTP server started) are regenerated with a real dictionary.

### Tests
- MV bridge plugin: registration/regeneration/unregister in JS and JSON plugins lists, static dictionary update, legacy-marker recovery; `.rpgmvm` round-trip through `maprender`; MZ `data/plugins.js`; YEP parameter keys excluded; malformed event data; MV profile dirs.

## [0.6.6] — 2026-08-15

### Added
- **Ren'Py: extraction from compiled games** — `.rpyc` files (legacy zlib+pickle and RPC2 formats) and `.rpa` archives (v1, v2.0, v3.0) are now parsed. Games that ship only compiled sources (no `.rpy`) are recognized and fully extracted; engine detection now accepts `.rpyc` and case-insensitive `.rpa`.
- **Ren'Py: screen texts from compiled SL2 screens** — `text`/`textbutton` strings are extracted from compiled `.rpyc`; variable interpolation parts (PyExpr/RawCode) are no longer mistaken for translatable text, and interpolated line fragments keep their exact whitespace.
- **Ren'Py: dual-dialect in-game agent** — separate py2 (Ren'Py 7.x) and py3 (Ren'Py 8.x) branches generated from one template. Attaching to an already-running game now bootstraps the agent via Frida `exec_python` with per-ABI offsets; a leftover `ob_agent.rpy` from a previous session is reused only when its port matches the current server.
- **Cheat tab redesigned** — compact two-column grid: Turbo (game speed 1–20 + 1x/2x/4x/8x presets), quick gold add buttons (+1000/+10000/−1000), reload-map button, screenshot button (CDP capture → PNG in `game/screenshots/`), full heal (HP/MP + states) and clear-states actions; quick give/take buttons on the Items tab.
- **RPG Maker**: MV maps now use the same 6-layer layout as MZ (shadows from z4, regions z5) with 4/5-layer fallbacks; plugins listed with a `.js` extension in `plugins.js` are no longer read with a doubled extension; plugin call (357) arguments supported as both dict (MZ) and list (older MZ); MV decryption key read from `System.json:encryptionKey` with a `rpg_core.js` fallback; asar backups store full relative paths.
- Event editor: command 102 (choices) gained the position parameter; command 122 (control variables) now writes the full 6-parameter MZ form.

### Fixed
- Ren'Py: RPA index parsing rewritten against `renpy/loader.py` 8.2.3 / 7.7.3 (3.0: zlib+pickle with XOR key, 2.0: hex offset without key, 1: whole-file zlib). `.rpa` archives are opened once instead of once per embedded file (was O(files × archives)).
- Ren'Py: extracted strings kept verbatim (no more `strip()`) — leading/trailing-space fragments of interpolated lines now match the in-game text exactly, so runtime hooks and `tl/*` blocks apply.
- RPG Maker: asar backups written with full relative paths; `restore_original` restores modern backups first and falls back to legacy name-only backups.

### Tests
- New coverage: `.rpyc` (legacy + RPC2) with stubbed Ren'Py classes, `.rpyc` inside `.rpa` v3.0/v2/v1, hybrid single-pass extraction (.rpy + .rpyc + .rpa), dual-ABI agent generation & compilation, MV/MZ map layers, plugins with `.js`, 357 dict/list arguments, MV crypto key from `System.json`/`rpg_core.js`, asar rel-path backup restore, new cheat expressions.

## [0.6.5] — 2026-08-14

### Added
- **RPG Maker maps now render 1:1 with the engine** (pixel-exact). The tilemap algorithm was copied from `rmmz_core.js`: autotile tables (floor/wall/waterfall), upper-tile flag (0x10) and table flag (0x80) from `Tilesets.json`, shadows from the dedicated shadow layer (z4 in MZ, z2 in MV), table edges drawn from the two halves. Both MZ (6-layer) and MV (4-layer) maps are supported. Previously the approximation produced broken textures and unreadable maps.
- **Full RPG Maker event editor** — everything that can be changed about an event is now editable:
  - event name and X/Y position; pages: add / duplicate / delete;
  - page: character image (picked from the game's `img/characters`, with a 48×64 preview via the decryption layer), event tile ID, trigger, priority, movement type/speed/frequency, walk/step animation, direction fix, through, visibility conditions (switches, variable, self-switch);
  - command list editor: add commands from the full RPG Maker MV/MZ catalog grouped by category, edit parameters (numbers / strings / choices), auto-inserted continuators (101→401, 102→402+404, 111→411+412, 205→505), dedicated editors for message text, choices, conditional branches (all 13 types) and movement routes (all 46 route commands); both MZ (`{code, indent, parameters}`) and MV (`[code, indent, …]`) command formats are supported.
- **Glossary redesigned**:
  - clear language pickers (Source / Target combos) instead of the editable `ja->ru` code box;
  - per-row edit dialog (term / translation / category) with explicit confirmation — no more error-prone inline cell editing;
  - category column, click-to-sort on every column, category filter, search across term/translation/category;
  - **glossary applied right in the translation table**: for the selected row a chip bar shows matched terms (`「アイラ」 → Айра`), clicking a chip inserts the translation into the translation cell;
  - glossary file format extended with categories while keeping old files compatible (plain string values still work; categories survive re-saving).
- **Full RU/EN localization sweep**: the RPG Maker command catalog (names, groups, parameter labels, route commands) is now bilingual and follows the interface language live; triggers, priorities, movement types, directions, condition briefs, default choice names and the UI language picker are translated too. A checker verifies that every `TR(...)` key in the code exists in both languages.

### Fixed
- Twine: backing up a single-`start_game.html` game failed with `NotADirectoryError` — the backup directory is now created next to the file (`_backup_dir` helper used in load/apply/restore).
- Resource tab: "Audio" info dialog crashed on relative RPG Maker paths (e.g. encrypted `audio/me/Curse2.ogg_`) — size is now resolved through the item's own storage lookup.
- Event editor: MZ movement-route commands are stored as `{"code": N}` dicts (not bare ints) — the catalog now accepts both formats.
- Glossary hint bar: the layout stretch item could not be removed, causing an infinite loop when rebuilding chips — chips are now removed by index with the stretch kept in place.
- Event direction order is now stable (down/left/right/up) — previously a Python `set` ordering made the editor occasionally write the wrong facing.

## [0.6.1] — 2026-08-12

### Added
- About dialog: engine tags are pulled automatically from the registry (`app/engines/registry.py`) — a new engine appears on its own; each tag has its own color.
- About dialog: the changelog is rendered as Markdown (headings, lists, code, links); it is fetched from GitHub and falls back to the bundled file when offline.

### Changed
- About dialog redesigned: app icon, version and a short description on top, changelog at the bottom; the "What's new" popup on startup removed.
- Removed the stub "Check for updates" button and the "Faster translation" tagline.
- Added a "free, no subscriptions" note and a "Support the project on Ko-fi" button that opens ko-fi.com/k_k in the browser.
- Window size removed from the title bar.

### Fixed
- Translate tab layout: nothing is cut off anymore. The file panel is fixed at 403 px, table columns — # 33 / context 180 / original 343 / translation 340 / status 82 (user-measured).
- The changelog in About showed only the version line — the section body was cut off when splitting Markdown (inner "### " headings were counted as section boundaries). The whole release section is now shown.

## [0.6.0] — 2026-08-12

### Added
- **Google engine rewritten: ~11× faster (measured: 28,600 lines/min vs ~2,500).** Cascade of free endpoints:
  1. `translate-pa.googleapis.com/v1/translateHtml` (the same service the Google Translate extension uses) — one request per batch of up to 100 lines, each line a separate element (no fragile `\n`-joining); measured ~90 ms per 50 lines. Primary path.
  2. Classic `translate_a/single` (`\n`-joined) — fallback for lines containing newlines (the fast endpoint drops them) and when path #1 fails.
  3. `translate.google.com/m` (HTML version, generous limits) — last resort.
- Connections are reused (`requests.Session`, keep-alive) — previously every request did a new TLS handshake. Bigger batches: up to 100 lines, 4 parallel workers (was 32 lines / 2 workers).
- Rate-limit protection kept: 429/captcha — 60 s cooldown, rotation switches to Bing; fast-endpoint public-key revocation (403) — automatic switch to the classic endpoint without a pause.

### Changed
- Translation service batches enlarged (32 → 100 lines, token limit 600 → 1500) — fewer requests for the same work.

## [0.5.12] — 2026-08-12

### Changed
- Default window 1390×755 (chosen for the actual screen); the file panel in the Translate tab moved 4 px left.

## [0.5.11] — 2026-08-12

### Fixed
- **After "Cancel", file lists were not updated and showed 0%.** Cancellation did not save the translated lines and did not rebuild the file list — the left panel kept old "0/N" counters, and the translation was lost on restart. Now on cancel (and on error) the translation is saved to the project, the file list is rebuilt, and the bars and "done/total" digits show the real state.

### Added
- **Window size shown in the title** ("…v0.5.11 — 1440×900", updates while resizing); the window size is remembered between runs. Default window enlarged to 1440×900; the status label at the bottom of the Translate tab no longer gets squeezed (text wraps), the file panel is wider — "translated/total" digits are visible.

## [0.5.10] — 2026-08-12

### Added
- **Multilingual games (Ren'Py `tl/`): pick ONE language.** If the game has several official translation languages (`tl/english`, `tl/french`, … — on disk or in `.rpa`), a warning with a choice appears on project open: only the chosen language is translated (plus the game's main text), the rest are skipped. Previously all languages were extracted at once — the same lines were duplicated per language (13k lines × 5 languages = 65k). The choice is saved in the project and used by "Extract text"; the dialog can switch back to the legacy "all languages" mode (slow, with duplicates).

## [0.5.9] — 2026-08-12

### Fixed
- **Ren'Py 8.2: game load crash "Could not parse string".** Multi-line game strings (with `\n` inside a line) were written to `game/tl/<lang>/ob_*.rpy` with real newlines — Ren'Py cannot parse such literals. Now newlines go out as escaped `\n` (same for `\t`), the file is valid, and the in-game text still shows line breaks. Already broken `ob_*.rpy` files self-heal on the next "Apply".
- **"Cancel" during translation no longer breaks the UI.** Previously cancellation blocked the interface (`wait` in the GUI thread) and jerked all progress bars. Now: soft stop without blocking, overlay shows "Cancelling…", smooth hide on finish, "Cancelled: translated N of M" text, and the progress bar stops exactly at the actual count (instead of jumping to 100%) then hides. What was translated before the cancel stays in the project — it can be refined or applied.
- AI correction: the "accept edits" dialog no longer pops up if the user pressed "Cancel".

### Added
- Smooth overlay animations (fade-in/out 150 ms); the spinner no longer spins uselessly when the overlay is hidden (removed the CPU load).

## [0.5.8] — 2026-08-11

### Added
- **Batch translation (the real speed-up behind "Fast translation").** Google no longer sends lines one by one: up to 32 lines go in a single request (lines are joined and split back on `\n`), several batches run in parallel. Measured on the live service: ~4,625 lines/min batched vs ~71 one by one — dozens of times faster. When Google merges lines (count mismatch), the batch is reliably translated line-by-line — no results lost.
- "Google + Bing" mode rebuilt: the primary path is Google in batches (that ×60), Bing is a safety net — on Google failure translation continues line-by-line on Bing.
- Rate-limit protection: on 429/captcha (`/sorry/` page) Google enters a 60-second cooldown — no requests are sent to it during that time, translation automatically runs on Bing; the cooldown lifts by itself.

## [0.5.7] — 2026-08-11

### Added
- **Fast translation**: one "Translate" button runs game translation in the background — the app stays responsive, progress is visible in the status bar, the game is ready to launch when done.
- "Launch with translation" button translates the game and launches it right away, without waiting manually.
- Animations for long operations: spinner over the window when launching the game, extracting text, translating and opening projects.

### Removed
- Live (per-line) translation in all engines: CDP tentacles for Tyrano/RPG Maker/Twine and the Ren'Py agent no longer connect to the game and translate text at runtime — translation is batch-only, before launching the game. This speeds up launch and removes in-game freezes during translation.

## [0.5.5] — 2026-08-07

### Fixed
- Game freezes with translation disabled: the Ren'Py agent now knows about the pause (`set_paused`) — it doesn't send requests and doesn't block the game thread on every line when translation is off.
- Ren'Py freezes caused by the cache: capped at 20k pairs (pruned on load and on add), disk writes at most once per 5 seconds and only after a successful write (previously `json.dump` of the whole cache ran in the game's main thread on every frame).
- "Hang during translation" in Tyrano/RPG Maker: bulk pretranslation no longer fills the shared worker pool of live translation (direct call in its own background thread), live translation no longer waits up to 12 seconds in the queue.
- JS payloads for Tyrano/RPG Maker/Twine kept scanning the DOM and sending requests with translation disabled — added an `enabled`/`__octopus_setEnabled` flag with status sync on connect and reconnect.
- RPG Maker: with translation disabled the dialog window no longer holds on "…" placeholders and doesn't wait for the gate timeout on every line.
- Tyrano: added skip detection (`isSkip` via `kag.config.skip`/`tyrano_skip` class) — during skip the DOM is not scanned and stabilization timers are not set; lines skipped during fast-forward are not lost and get translated on the next display.

## [0.5.4] — 2026-08-05

### Added
- New engine **RPG Maker (Electron)** — support for RPG Maker MZ/MV games packaged in Electron (data inside `resources/app.asar`, e.g. «遥かなるセレスフィア»).
- ASAR archive reading and patching (`app/core/asar.py`): header parsing, prefix-based extraction, in-place file injection (padded with spaces, header untouched) or rebuild when the file grows, backups of the original to `backup/<date>/`, the file saved as `.ob.bak`.
- Variant detection (MZ by `game.rmmzproject`/`js/rmmz_core.js`, MV by `js/rpg_core.js`), extraction/injection through a temporary project from `project/data` (the RPG Maker parser is reused), cheats tab.
- Live translation for RPG Maker (Electron): the same CDP tentacle as regular RPG Maker.

## [0.5.4] — 2026-08-06

### Removed
- Local offline translator Honyaku (NLLB-200): didn't meet quality expectations — temporarily removed from the app and the build. The "Honyaku" provider disappeared from settings, models (~0.6 GB) are no longer copied to dist — the build got lighter. The library code stays in the repo (`app/translators/honyaku/`): we'll bring it back when a better solution appears.

### Changed
- Default provider — "Google + Bing" (rotation with fallback). Old settings with honyaku/nllb/argos selected are migrated automatically on startup.

## [0.5.3] — 2026-08-05

### Changed
- Dead code removed: `honyaku_download`, `honyaku_models_status`, `honyaku_missing_pairs_all` and `HONYAKU_ALL_PAIRS` — leftovers of the removed model-download button (models ship with the app, nothing to download).
- Outdated texts updated: hints and error messages no longer promise "models will be downloaded automatically" — models are bundled; if the folder goes missing, the hint explains how to restore.

### Fixed
- "Google + Bing" (rotate) engine: Bing sessions were created by list multiplication — all "several sessions" referenced one and the same instance with a shared token and quota, contrary to the docs. Now each Bing session is an independent instance.

## [0.5.2] — 2026-08-05

### Added
- Honyaku v0.3.0: hallucination detection — a suspicious translation (low model confidence, repetitions, foreign script) is re-computed with beam=4; on repeated garbage the original is returned.
- Honyaku v0.3.0: automatic compute_type selection (int8_float16 → int8 → float16 → float32) and splitting long lines by tokens — stable speed on any hardware.

### Changed
- Honyaku: fast tier (OPUS-MT) removed — it hallucinated on many lines. One multilingual NLLB model (best) remains for all language pairs; the build with models slimmed from ~1.2 GB to ~0.65 GB. Best speed on CPU: ~190 chars/s (10 phrases ~0.9 s).
- Offline models no longer require any action: the "Download" button, the first-run window and the settings block were removed — models ship with the app, the app only warms them up.
- Build: CHANGELOG.md is included in the exe — "What's new" works in the built app too.

### Fixed
- Translation: single alphabet characters (kana ホ, ァ…, Cyrillic, Latin) are no longer sent to the translator — kana-keyboard buttons and hotkeys return as-is instead of "Home" (NLLB/Google hallucination). The guard works in all providers and modes (live session, files, batch translation), and before the translation memory — old garbage doesn't leak from the cache.
- Performance: after closing the game the app no longer loads the CPU. Honyaku models are loaded into the shared cache exactly once per session (all tabs and threads use it), and warmup starts only together with the live session — previously it ran on app start, loaded models into one-off objects and duplicated NLLB loading for each tab.
- Crash on exit: RuntimeError "Internal C++ object (_HonyakuWarm) already deleted" when closing the window during background model warmup.
- **App crash (access violation in `_sentencepiece.pyd`).** One shared honyaku Translator was used from several threads at once (live session + file translation + warmup), and the sentencepiece tokenizer is not thread-safe — concurrent calls crashed the process at the C++ level. Model calls are serialized with a shared lock.
- Model warmup now actually loads NLLB into memory in the background when the live session starts (warms the active pair from settings, not all 5) — previously it created empty objects and the first translation still waited for the model load in the game thread.

## [0.5.1] — 2026-08-05

### Added
- Fully offline operation: honyaku offline models (fast + best, ~1.2 GB) are downloaded to the `models/` folder next to the app (repo root when running from sources) and copied into the build `dist/models/` — translation works without internet and without contacting HuggingFace.
- First-run popup if offline models are not downloaded: "Download" / "Later" with a progress bar and cancel.
- Settings → General: "Honyaku offline models" block — status (pairs downloaded, size) and a "Download" button just in case.

### Fixed
- **Critical bug: live translation hung and didn't translate (all engines).** Honyaku with missing models ran a synchronous re-download from HuggingFace right in the Ren'Py server thread / Tyrano CDP thread without a timeout — the game "hung" up to 30 s on each dialog line, no translation appeared at all (had to be killed via Task Manager).
- Honyaku: models are no longer re-downloaded into the translation path — with missing models the original is returned instantly, without blocking; models still download in a background task at startup, and translation starts working on its own once they are ready.
- Tentacles: live-session translation is time-limited (12 s per line) — a hung/slow engine (network down, endless retries) no longer freezes the game in any engine.
- Ren'Py: the agent waits 10 s per line for the server response instead of 30 s — even if the server hangs completely, the game doesn't stall for dozens of seconds.
- Honyaku: after the background download models are warmed up (loaded into memory) — the first lines of a live session no longer pay the full NLLB load (~10–30 s) in the server thread.

## [0.5.0] — 2026-08-04

### Added
- **TyranoScript / TyranoBuilder core**: detection by `data/scenario/*.ks` + `tyrano/`, text extraction/injection (line segments + `text="..."` attributes of link/button/ruby tags, skipping `[iscript]` blocks, comments and labels), automatic UTF-8/Shift-JIS encoding detection, backups, shift protection and variable-preservation checks (`%var`, `&var`, `tf./f./sf.`).
- TyranoScript core: live translation via CDP (NW.js/Electron) — MutationObserver on `#tyrano_base`, translation cache in `tyrano_cache.json`, bulk preloading of translated .ks.
- TyranoScript live: protection against hallucinations and double translations — lines shorter than 2 characters and Cyrillic are not sent to the translator (single kana during character-by-character typing no longer give "Home"), 300 ms text stabilization (fast-forward no longer spams the translator), node text verification before replacement (stale responses are not applied), re-setting already translated lines excludes the feedback loop.
- TyranoScript live: whole dialogue lines `.message_inner p` are translated (instead of separate text nodes with single kana), replacement inside `span.current_span` without breaking the engine's layout.
- TyranoScript live: the translation cache is injected into the page right on connect and again after every page reload (title, save load) — the same lines are no longer requested/translated repeatedly.
- TyranoScript engine icon in the project list.
- Unified translation cache: all engines (RPG Maker, Ren'Py, Twine, TyranoScript) write one `octopus_cache.json` in the game folder; old caches (`.translation_cache.json`, `tyrano_cache.json` and others) are read automatically and migrated to the new format on the next save.
- "Live translation" toggle on the dashboard: translation can be turned off/on on the fly without interrupting the session — cheats, variables and game state keep working, text shows untranslated (all engines).
- Projects tab: games can be dragged into the list from Explorer.
- "About" dialog (version, engines) and "What's new" (shown on version update, content from CHANGELOG.md).
- Update check via GitHub Releases — disabled until a public repository appears (`GITHUB_REPO` constant in `app/ui/app_info.py`).

### Fixed
- Tyrano parser: tags with nested `]` in attributes (`text="a[b]"`, `[emb expr="arr[0]"]`) are parsed whole — `text="..."` is extracted and translated, no garbage text segments from attribute tails, tags don't break on injection (previously translating a segment in such a line could erase the closing `]`).
- Tyrano parser: injection preserves the file's line endings (CRLF/LF) and the trailing newline — files are not rewritten from CRLF to LF.
- Tyrano parser: .ks paths on extraction use correct separators (match the encoding-cache keys on injection).
- Dead code removed: `_KAG_LIKE_NAMES`, `_TAG_ONLY_RE`.

### Removed
- TyranoScript: the "Variables"/cheats tab removed — Tyrano games have no game variables (only internal engine config: volume, CG gallery), nothing to cheat.

### Under the hood (0.5.0)
- Project license changed: MIT → GPL-3.0.
- Docs: README split into Russian (README.md) and English (README.en.md), CHANGELOG updated.

## [0.2.0] — 2026-08-01

First public version. RPG Maker MV/MZ and Ren'Py cores are stable, Twine is experimental.

### Added
- Ren'Py core: text extraction from `.rpy`/`.rpyc` (dialogs, menus, translate blocks), `.rpa` archive reading v1/v2/v3.
- Ren'Py core: live translation via Frida Python-agent injection, font replacement (FontGroup), cheats (variables, gold, heal, teleport), auto-launch and process auto-detection.
- RPG Maker MV/MZ core: batch translation of `www/data`, live translation via CDP, cheats, map editor, save editor, resource viewer (`.png_`, `.rpgmvp`, audio), font patching.
- Twine (SugarCube) core: translation extraction/injection, live HTTP+WS bridge, save editor (LZ-String).
- Translation providers: Honyaku (offline, NLLB), Google Free, Bing, Google+Bing rotation with fallback, OpenAI-compatible API.
- Glossary, translation memory (SQLite), game-code masking, AI corrector.
- GUI: dark theme, SVG icons, RU/EN localization, system tray, first run with language pack installation.
- Build: PyInstaller + Inno Setup, version in exe resources, single version source `app/__init__.py`.

### Fixed (Ren'Py core, 11 bugs)
- Frida: `get_usb_device` → `get_local_device`; `spawn` now calls `attach`; all `exec_python` rewritten via `Script`/RPC (`Session.evaluate` doesn't exist in Frida).
- Extraction: `.rpyc` files on disk are now parsed, dialogue regex `<speaker> "text"` added, string deduplication.
- Ren'Py cheats tab instead of the wrong RPG Maker one; Ren'Py auto-launch; process detection via `game/`+`lib/`; fixed the font path; FontGroup ranges without overlaps.

### Under the hood (0.2.0)
- Repository prepared for publication: `.gitignore`, README (RU/EN), CHANGELOG, CI (GitHub Actions), duplicate modules removed.
