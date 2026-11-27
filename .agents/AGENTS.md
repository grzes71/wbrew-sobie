# Project Context — Funky Koval: Wbrew Sobie (Atari 800XL / 65XE)

> **Note to Agent:** Generic 6502 hardware rules, Zero Page limits, syntax restrictions and cycle-counting are in `.agents/rules/`. This file describes the **actual** layout, build pipeline and tooling of THIS project. If it disagrees with the code, trust the code and fix this file.

## 1. ROLE & SCOPE
- You act as a Senior Embedded Systems Architect and Python Tooling Engineer.
- The project is an adventure/action game (see `MECHANIKA.md`) built from 6502 assembly (MADS) for the engine, plus Python (PyYAML, Pillow, PySide6, pytest, py65) for data compilers, editors and tests.
- Target: stock 64 KB Atari 800XL/65XE (no extended RAM, no VBXE).
- Before changing an unfamiliar subsystem read, as relevant:
  - `MECHANIKA.md` — game rules and hero movement (Polish),
  - `README.md` — build pipeline and tools,
  - `docs/rooms-data-format.md` — `rooms.yaml` format (objects, tags, rooms, animations, teleports),
  - `room_editor/SPECIFICATION.md` — room editor spec,
  - `HISTORY.md` — recent changes.
- There are no `ARCHITECTURE.md` or `MEMORY_USAGE.md` files. Memory facts come from `main.asm` and `scripts/check_memory.py`.

---

## 2. DEVELOPMENT WORKFLOW (CRITICAL)
- After modifying any code or data file (`.asm`, Python, `rooms.yaml`, sprites, music, texts), run:
  ```bash
  make all
  ```
- Target chain: `assets → data → audio → xex → tests → check_memory`.
  Other targets: `make run` (launch in AltirraSDL), `make clean` (removes `gen/` and `funky_koval.xex`).
- Prerequisites: MADS (path in `Makefile`, override with `MADS=...`), Python 3.10+ with `.venv` and `requirements.txt`, GNU Make.
- Resolve all errors, warnings and test failures before proposing further edits.
- All tests must pass before a task is complete. Where possible, py65 tests should check that the Python model and the 6502 routine give identical results.

---

## 3. MEMORY LAYOUT
- OS ROM stays enabled: all code, graphics and data **MUST end at or below `$BFFF`**. `$C000`–`$DFFF` is never RAM.
- `main.asm` includes in strictly ascending `org` order (no location-counter backtracking):
  - `$2000`: `lib/rle.asm`, `lib/pmg.asm`, `engine/input.asm`, `engine/dli.asm`, `scenes/title.asm`, title screen data.
  - `$5000`: `lib/player.asm` (POKEY music player), `gen/title_music.asm`.
  - `$6000`: `gen/*` data (charsets, styles, objects, rooms, teleports, animations, intro text, hero sprites), then `engine/room.asm`, `engine/anim.asm`, `engine/hero.asm`, `scenes/intro.asm`, `scenes/game.asm`, `scenes/gameover.asm`.
- Keep audio player code and song data isolated from dynamic buffers, sprite tables and graphics data.
- `scripts/check_memory.py` is the single source of truth for segment bounds and headroom. It runs in `make all`.
- Do not keep the whole world in RAM: load the current room only (see `MECHANIKA.md` §8.2).

---

## 4. PROJECT STRUCTURE

| Path | Purpose |
| --- | --- |
| `main.asm` | Entry point; includes all modules in ascending `org` order |
| `hardware.asm`, `colors.asm` | Hardware equates (ANTIC/GTIA/POKEY/PIA) and color constants |
| `zeropage.asm` | Zero-page allocations (`$80`–`$FF` only) |
| `engine/` | `input.asm`, `dli.asm`, `room.asm` (room rendering/logic), `anim.asm` (object animations), `hero.asm` (hero movement/state/sprites) |
| `lib/` | `rle.asm` (RLE decompressor), `pmg.asm` (PMG helpers), `player.asm` (POKEY music player) |
| `scenes/` | `title.asm`, `intro.asm`, `game.asm`, `gameover.asm` |
| `gen/` | Generated ASM/data/`.lab`/`.lst` — **never edit by hand**; recreated by `make` |
| `rooms.yaml` | SSOT for rooms, object groups, tags, animations, teleports |
| `sprites/` | `project.sprite.json` (hero sprites SSOT), `enemies.sprite.json` |
| `music/` | `title.dsl`, `title.arrangement.json` (music SSOT) |
| `texts/intro.txt` | Intro text SSOT |
| `images/`, `fonts/` | `title.png`, `castle.png`; `font.fnt` (game charset) |
| `scripts/` | Compilers and tools: `rooms_compile.py`, `compile_hero_sprites.py`, `compile_title_screen.py`, `compile_intro.py`, `compile_music.py`, `png_to_charset.py`, `check_memory.py` |
| `room_editor/` | PySide6 room editor; writes `rooms.yaml` |
| `sprite_studio/` | PySide6 sprite/animation editor; writes `sprites/project.sprite.json` |
| `tools/` | `render_room_png.py` |
| `tests/` | pytest + py65 tests (`test_engine.py`, `test_hero.py`, `test_hero_move.py`, `test_room_*.py`, `test_rooms_compile.py`, ...) |
| `docs/` | Data format docs |
| `.github/workflows/` | `portal-deploy.yml`, `release.yml` |

---

## 5. DATA PIPELINE
- **SSOT:** `rooms.yaml`, `sprites/*.sprite.json`, `music/*`, `texts/intro.txt`, `images/*.png`, `fonts/font.fnt`. Compilers in `scripts/` turn them into `gen/*.asm`.
- **Do not modify SSOT files without user permission** (scripts are fine). The editors (`room_editor`, `sprite_studio`) write the SSOT directly.
- **Structure-of-Arrays** for all generated tables, so the 6502 can index with `LDA table,X`.
- **Build-time validation** in the Python compilers (bounds, references, tags/flags) before ASM generation.
- Makefile dependencies must regenerate `gen/` whenever sources or compilers change.

---

## 6. ENGINE NOTES
- Game scenes are state-like modules in `scenes/` (title → intro → game → game over), each with `*_enter` / `*_update` procs. `zp_next_state` requests a scene change.
- `game_update` (`scenes/game.asm`) runs once per frame: reset `zp_dli_idx`, call `hero_update`, check `zp_hero_fell_out`, then handle the temporary FIRE exit (FIRE + joy UP → success, otherwise failure). There is no separate collision or render phase: input reading, movement, collision and PMG drawing all happen inside `hero_update` (`engine/hero.asm`).
- Hero is a state machine in `engine/hero.asm`: standing/walk (`hero_update_walk`), `hero_update_jump`, `hero_update_fall`, `hero_update_squat`, `hero_update_ladder`. Transitions use `hero_enter_*` procs. Collision uses per-room block and ladder bitmaps (`engine/room.asm`: `cell_blocked`, `row_range_blocked`, `col_range_blocked`, `cell_ladder`, `row_range_ladder`, `row_range_support`).
- Modules communicate through shared variables/flags (zero page or fixed RAM); the consumer handles and clears the request in its own phase (e.g. `zp_anim_pending` / `zp_anim_active` for object animations).
- Deferred VBI (`game_vbi_deferred` in `engine/dli.asm`, installed in `game_enter` via `VVBLKD`): runs `anim_tick` only when `zp_anim_active` is set, resets `zp_dli_idx`, exits via `XITVBV`. DLI (`room_dli_handler`): only mid-frame register changes (colors, `CHBASE`, PMG positions); enabled only when `room_dli_count` is non-zero.
- Keep hero movement/collision logic tied to the data model of `rooms.yaml` objects (blockable flag, tags); see `docs/rooms-data-format.md`.

---

## 7. PYTHON & TESTING
- Type hints everywhere; dataclasses or Pydantic v2 for parsing. Keep `requirements.txt` minimal.
- Run tests with `make tests` or `python -m pytest -v` (use the `.venv` interpreter).
- py65 pattern: assemble a harness with MADS, load the binary into `py65.devices.mpu6502.MPU` memory, set inputs, run until `BRK`, assert against the Python model.
- Test design rules: `.agents/rules/05-tests.md` (no hardcoded asset counts).

---

## 8. EMULATOR VERIFICATION
- Use AltirraSDL/AltirraBridge to verify `funky_koval.xex` — rules and pitfalls in `.agents/rules/06-altirra-sdl-rules.md`, usage in the `altirra-bridge` skill.

---

## 9. AVAILABLE AGENT SKILLS
Under `.agents/skills/`:

| Skill | Path | Use for |
| --- | --- | --- |
| `atari8bit` | `.agents/skills/atari8bit/SKILL.md` | Atari hardware/OS reference (router to topic files) |
| `mads` | `.agents/skills/mads/SKILL.md` | MADS syntax, directives, macros |
| `py65` | `.agents/skills/py65/SKILL.md` | py65 test harnesses |
| `altirra-bridge` | `.agents/skills/altirra-bridge/SKILL.md` | Driving AltirraSDL from Python |
| `atari-image-converter` | `.agents/skills/atari-image-converter/SKILL.md` | Image → ANTIC graphics converter |
| `atari-music-composer` | `.agents/skills/atari-music-composer/SKILL.md` | POKEY music DSL and tooling |
