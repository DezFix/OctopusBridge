# Release v7.36 — What's new

Build: `OctopusBridge_v7.36.exe` (138 MB, FileVersion 7.36).
Tests: 31/31 green, ruff clean.

## Ren'Py translation that actually shows up in games

The headline fix of this cycle. Previously translations were written but
never appeared in-game (English everywhere despite 5000+ translated lines).
Root causes found by live-game experiments, not guesses:

- **The language activator lived in `tl/<lang>/`, where Ren'Py never
  executes scripts.** Translation directories are data, not code — so
  `config.language` was never set and stock `translate` blocks never
  loaded. Proven with marker probes (block in `tl/` never ran, same block
  in `game/` ran). The activator now lives at `game/zz_ob_lang.rpy`.
- **`old`/`new` inside `translate <lang> <label>:` does not substitute
  dialogue.** The blocks load into memory (verified: 646 labels for
  `russian`) but Ren'Py matches say-statements by node identifier, which
  compiled games don't carry. This format never translated anything —
  earlier visible translation came from the runtime hook.
- **Safe runtime hook restored** (`Text.__init__` + `Character.__call__`):
  dictionary holds display strings only (labels/screens, never
  python-expression keys), exact match first, whitespace-normalized
  fallback second, every failure fails open to the original text.
  Found and fixed on a live game: Ren'Py shadows builtin `dict` with
  `RevertableDict` (and `list` with `RevertableList`), so naive
  `isinstance` checks silently disabled the hook.
- **`translate <lang> strings:` stays removed.** It rewrites Python
  strings inside game code and kills games built on string-keyed data
  (SR24 mod-loader crash). Never coming back.
- **Coverage 49.8% → 69.2% on SR24, 99.5% on Shoretown Saga** (label
  recovery from `.rpyc` AST, structural node-kind routing, honest
  `skipped_by` reasons instead of silence).
- **Universal method picker** (`universal.py`): source-direct for games
  with loose `.rpy`, native blocks when identifiers exist, hooks
  otherwise. The engine routes `apply()` through it automatically.

## Godot engine core (new)

File-based translation core for Godot games: `.pck` v2/v3 reader,
streaming rebuild with backup → write → verify → rollback, extract from
`.csv`/`.tscn`/`.tres`/`.gd`, honest refusals (encrypted packs, embedded
exe, Godot 3.x, binary resources). Verified by reading a real Godot 4.6
game (13,271 files, all checksums match). Not yet registered in the UI.

## System language defaults

The app now starts in the system language (QLocale with fallback) and
defaults the translation target to it. Manual choice always wins.

## Chinese interface (draft)

All 783 UI strings translated to Chinese (machine draft, needs native
review). Language selectors rebuilt on the supported-languages list.

## Rust, one parser at a time

Behavior-identical ports with conformance suites, zero-panic on malformed
input. Python stays for UI/network/orchestration; Rust plugs in via PyO3.

- `rust/ob_pck` — Godot `.pck` reader (v2/v3), 18/18 tests.
- `rust/ob_renpy` — Ren'Py string logic + method-choice rule, 19/19 tests.
- `rust/ob_renpy_rpyc` — `.rpyc` framing + pickle-VM with Ren'Py mocks +
  AST extraction, 14/14 tests, 384 conformance comparisons with zero
  divergences, 200-mutation fuzzer with zero panics.
- The Ren'Py extractor now tries Rust first and falls back to Python on
  any refusal (verified live on real game archives).

## Honest limitations

- Dynamic strings with counters (`ENG:136`-style language+number UI) and
  text baked into images (20 Tips PNGs in the tested game) are not
  covered by text hooks — each needs its own technique.
- Ren'Py games whose text lives only in compiled blueprints-style data
  without identifiers cannot use stock translation blocks.
- The Chinese translation is an unreviewed machine draft.
- Rust covers parsers (readers); writes stay on Python with backup/verify.
