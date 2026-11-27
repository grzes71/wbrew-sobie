# Project History — Funky Koval - Wbrew Sobie

<!-- AGENT INSTRUCTIONS: Prepend new history entries directly below this comment. Use format: ## [YYYY-MM-DD] - [Brief Title] and relative file paths only. -->

## [2026-11-27] - Implement Hero Ladder Climbing (`HERO_STATE_ON_LADDER`) and Ladder Tag Validation
- **Build-Time Validation ([scripts/rooms_compile.py](scripts/rooms_compile.py)):** Added `RoomCompileError` validation rejecting the `"ladder"` tag on blockable objects (`non-blockable: false`); reused the existing SoA tag pipeline (`TAG_LADDER`, `TAG_LADDER_PLANE`, `obj_tags<P>`).
- **Runtime Ladder Bitmap & Helpers ([main.asm](main.asm), [engine/room.asm](engine/room.asm)):** Allocated `room_ladder_map` (`$3778..$37EF`, `120 B`, guarded `< PMG_BASE`), extended `room_draw` to mark non-zero cells of `"ladder"`-tagged objects via `ROOM_OBJ_FLAG_LADDER = $80` with zero extra ZP bytes, and added `clear_room_ladder_map`, `cell_ladder`, `row_range_ladder`, `row_range_support` (`room_block_map | room_ladder_map`), and `col_range_ladder`.
- **Hero Ladder State Machine ([engine/hero.asm](engine/hero.asm), [zeropage.asm](zeropage.asm)):**
  - Added `HERO_STATE_ON_LADDER = 4`, `HERO_CLIMB_SPEED = 1` (scanline/frame, guarded `1..4`), `HERO_LADDER_SET = HERO_UP_DOWN` (4-frame climb set from `sprites/project.sprite.json`), and `HERO_CMD_CLIMB_UP = 8` (`$E` in `hero_joy_cmd_tbl`). Controls follow project convention (`UP` = climb/grab, `DOWN` = descend/squat, `UP+LEFT`/`UP+RIGHT` = grounded jump, `FIRE` = jump from ladder).
  - Updated `hero_check_support` and `hero_update_fall` to use `row_range_support`, enabling walking across top rungs and landing on ladder rungs from jumps/falls.
  - Added `hero_ladder_under_feet`, `hero_can_descend_ladder`, `hero_ladder_behind`, `hero_try_ladder_step_x`, `hero_enter_ladder`, `hero_jump_from_ladder` (consumes `zp_fire_pressed` so `scenes/game.asm` does not exit on ladder jump), and `hero_update_ladder` (gravity disabled, stationary hold on release, sideways clamping within ladder columns and walls/edges, continuous stacked-ladder climbing, automatic top-rung exit to `STANDING`, floor landing, and hanging-ladder fall-off).
  - Enabled mid-jump/mid-fall ladder grab via pure `UP` (`HERO_CMD_CLIMB_UP` when `hero_ladder_behind` is true, after jump launch frame `zp_hero_jump_idx > 0`), while `UP+LEFT`/`UP+RIGHT` jumps pass cleanly through ladders while rising.
- **Tests, Docs & Verification ([tests/test_hero_ladder.py](tests/test_hero_ladder.py), [tests/test_hero_move.py](tests/test_hero_move.py), [docs/rooms-data-format.md](docs/rooms-data-format.md)):** Added `8` synthetic `py65` + `HeroLadderModel` parity tests covering compiler validation, `room_draw` SSOT ladder map parity, walking on top rung, descending/hold/sideways-clamping/floor-landing, stacked climbing/top-rung exit, `FIRE` jumps from top/middle/bottom, landing on rungs, mid-jump `UP` grab vs pass-through, screen-edge ladders, hanging fall-off, and cycle budget; updated [docs/rooms-data-format.md](docs/rooms-data-format.md); verified via `make all` (`135 passed`, `funky_koval.xex` highest address `$8014` with `16,363` B headroom) and live `AltirraSDL --bridge` E2E with 7 phase screenshots.

## [2026-11-26] - Change Hero Player 0 Color to `$AD`
- Updated `HERO_COLOR` from `$0E` to `$AD` in [engine/hero.asm](engine/hero.asm), removed hardcoded `$0E` color assertions in [tests/test_hero.py](tests/test_hero.py), updated [docs/rooms-data-format.md](docs/rooms-data-format.md), and verified via `make all`.

## [2026-11-26] - Increase Hero Walk Speed to 1/3 cc/frame
- Updated `HERO_WALK_SPEED_SUBSTEPS` from `4` to `3` (`1/3 ≈ 0.333` cc/frame, closest uniform cadence to `+25%` over `0.25` cc/frame) in [engine/hero.asm](engine/hero.asm), updated [tests/test_hero_move.py](tests/test_hero_move.py) and [docs/rooms-data-format.md](docs/rooms-data-format.md), and verified via `make all` and `AltirraSDL --bridge` (`60` frames -> `20` cc).

## [2026-11-26] - Tune Hero Walk Speed (-50%), Walk Animation (+50%), and Jump Height (+50%)
- **Hero Physics & Walk Cadence ([engine/hero.asm](engine/hero.asm)):** Halved grounded walking speed to `0.25` cc/frame (`HERO_WALK_SPEED_SUBSTEPS = 4`), decoupled walk animation via `HERO_WALK_ANIM_TICKS = 5` PAL frames/sprite frame (`hero_tick_walk_anim`, closest integer to `8 / 1.5 = 5.33` for `+50%` animation speed), and raised jump height by `+50%` from `18` to `27` scanlines (`hero_jump_steps = [4, 4, 3, 3, 3, 2, 2, 2, 1, 1, 1, 1]`, `HERO_JUMP_STEP_COUNT = 12`, `HERO_JUMP_HEIGHT = 27`).
- **Tests & Docs ([tests/test_hero_move.py](tests/test_hero_move.py), [docs/rooms-data-format.md](docs/rooms-data-format.md)):** Updated `HeroModel` and movement tests for `0.25` cc/frame walking, `5`-tick walk animation cadence, and `27`-scanline jump apex; updated [docs/rooms-data-format.md](docs/rooms-data-format.md); verified via `make all` (`127 passed`, `$7C54` with `17,323` B headroom) and live `AltirraSDL --bridge` (`60` frames -> `15` cc, `5`-tick anim cadence, `27`-scanline apex).

## [2026-11-26] - Hero DOWN-Only Squat and Half-Speed Grounded Walking
- **DOWN-Only Squat ([engine/hero.asm](engine/hero.asm)):** Added `HERO_CMD_SQUAT = 7` and mapped `hero_joy_cmd_tbl` entry `$D` (`DOWN` only, active-low `%1101`) to `HERO_CMD_SQUAT` instead of `HERO_CMD_NONE`; updated `hero_update` (`@squat_keep_facing`) and `hero_update_squat` to preserve `zp_hero_facing` on `DOWN`-only, hold crouched seamlessly across `DOWN`/`DOWN+LEFT`/`DOWN+RIGHT` without extra redraws, ignore `DOWN` while airborne, and exit cleanly to `STANDING` on release.
- **Half-Speed Grounded Walking ([zeropage.asm](zeropage.asm), [engine/hero.asm](engine/hero.asm)):** Allocated `zp_hero_walk_sub = $CF`, added tunable constants `HERO_WALK_STEP_CC = 1` and `HERO_WALK_SPEED_SUBSTEPS = 2` (`0.5` cc/frame, guarded in `1..4` cc and `1..16` substeps, keeping `HERO_JUMP_SPEED_CC = 1` unchanged), gated `hero_update_walk` to move and tick walk animation strictly on active move frames (`zp_hero_walk_sub == 0`), and reset `zp_hero_walk_sub = 0` on stop, direction reversal, wall/edge block, and non-walk transitions.
- **Tests & Docs ([tests/test_hero_move.py](tests/test_hero_move.py), [docs/rooms-data-format.md](docs/rooms-data-format.md)):** Updated `HeroModel` (`walk_sub`, `JOY_DOWN -> HERO_CMD_SQUAT`) and hero movement tests for `DOWN`-only squat, `N/2` displacement, phase reset on stop/turn, and wait-frame zero redraws; updated [docs/rooms-data-format.md](docs/rooms-data-format.md); verified via `make all` (`127 passed`, `funky_koval.xex` at `$7C34` with `17,355` B headroom) and live `AltirraSDL --bridge` (`60` frames -> `30` cc displacement, `DOWN`-only squat screenshots for both facings).

## [2026-11-26] - Hero Movement (Walk, Jump, Squat) and Horizontal/Ceiling Collision
- **Zero-Page & Blocking Helpers ([zeropage.asm](zeropage.asm), [engine/room.asm](engine/room.asm)):** Allocated `$AC..$AF` (`zp_hero_jump_idx`, `zp_hero_jump_dir`, `zp_hero_cmd`, `zp_hero_tmp3`) in [zeropage.asm](zeropage.asm); added `col_range_blocked` in [engine/room.asm](engine/room.asm) built on `cell_blocked` to check vertical column spans `[row_a..row_b]` with playfield boundary clamping.
- **Hero Movement State Machine & Collision ([engine/hero.asm](engine/hero.asm)):** Added tunable speed/bound constants (`HERO_WALK_SPEED_CC = 1`, `HERO_JUMP_SPEED_CC = 1`, `HERO_MAX_X_CC = 152`, `HERO_MIN_PMG_Y = 32`), `hero_jump_steps = [4, 3, 2, 2, 2, 1, 1, 1, 1, 1]` (`HERO_JUMP_HEIGHT = 18` scanlines), `hero_joy_cmd_tbl` & facing-indexed SoA tables (`hero_stand_set_tbl`, `hero_jump_set_tbl`, `hero_squat_set_tbl`), assembly-time safety invariants, `hero_body_rows`, `hero_blocked_at`, `hero_try_step_x` (screen-edge clamping and `step > 1` cell-edge flush snapping), `hero_read_input`, `hero_tick_anim`, `hero_enter_standing`, `hero_enter_falling`, and `hero_update_walk` / `hero_update_jump` / `hero_update_fall` / `hero_update_squat` supporting grounded walk, ledge fall, committed ballistic jump with ceiling/top-clamp/mid-air wall stops, and one-shot crouch hold (`HERO_STATE_SQUATTING = 3`), keeping idle fast-path `zp_hero_dirty == 0`.
- **Tests & Docs ([tests/test_hero_move.py](tests/test_hero_move.py), [docs/rooms-data-format.md](docs/rooms-data-format.md)):** Added `10` synthetic `py65` + `HeroModel` reference tests covering `col_range_blocked`, `hero_blocked_at`, all `16` joystick states, walking/wall stops across all overlapped body rows, screen-edge clamping, ledge falling, jump arcs/ceilings/walls/top clamp, squatting, idle zero-write fast path, and VBI cycle budget; updated [docs/rooms-data-format.md](docs/rooms-data-format.md); verified via `make all` (`127 passed`, `funky_koval.xex` at `$7BF4` with `17,419` B headroom) and live `AltirraSDL --bridge` gameplay + screenshots.

## [2026-11-26] - Hero Player 0 Sprite, Blocking Map, and Falling Physics
- **Hero Sprite Pipeline ([scripts/compile_hero_sprites.py](scripts/compile_hero_sprites.py), [Makefile](Makefile)):** Added hero sprite compiler validating IDs `1..8`, exact animation names, `8×18` pixel bitstrings, and `frame_duration` (`4`-tick fallback), deduplicating identical frames, and emitting SoA tables in [gen/hero_defs.asm](gen/hero_defs.asm) (`0 B`) and [gen/hero_sprites.asm](gen/hero_sprites.asm) (`8` sets, `29` unique frames, `604 B`).
- **Start Footprint Warnings & Blocking Map ([scripts/rooms_compile.py](scripts/rooms_compile.py), [engine/room.asm](engine/room.asm)):** Added `START_FOOTPRINT_BLOCKED` and `START_AT_BOTTOM_ROW` compiler warnings; added `120`-byte `room_block_map` (`$3700..$3777`, `40×24` bits MSB-first) populated by `room_draw` for blockable non-zero cells along with `clear_room_block_map`, `cell_blocked`, and `row_range_blocked`.
- **Hero Physics, PMG Rendering & Scene Wiring ([engine/hero.asm](engine/hero.asm), [scenes/game.asm](scenes/game.asm), [scenes/gameover.asm](scenes/gameover.asm), [main.asm](main.asm), [zeropage.asm](zeropage.asm)):** Configured single-line Player `0` (`PMG_BASE = $3800`, `PMG_P0 = $3C00`, `HPOSP0 = 48 + 4*x`, `COLPM0 = $0E`, `SIZEP0 = 0`, `GAME_DMACTL = $3A`, `GAME_GRACTL = $02`, `GAME_PRIOR = $01`); implemented `STANDING`/`FALLING` state machine with `hero_fall_steps = [1, 1, 2, 2, 3, 3, 4]`, zero-tunnelling boundary landing, bottom-edge Game Over (`zp_hero_y >= 224` -> `STATE_GAME_OVER_FAILURE`), partial vacated-scanline PMG clearing (`hero_pmg_draw`), clean PMG teardown (`hero_pmg_disable`), relocated gameplay code/data into `$6000..$7914`, and allocated `zp_hero_*`/`zp_room_*` zero-page variables.
- **Tests & Docs:** Created [tests/test_hero.py](tests/test_hero.py), updated [tests/test_room_screen.py](tests/test_room_screen.py), [tests/test_rooms_compile.py](tests/test_rooms_compile.py), and [docs/rooms-data-format.md](docs/rooms-data-format.md); verified with `make all` (`117 passed`), `scripts/check_memory.py` (`$7914`), `py65` cycle measurements, and live `AltirraSDL --bridge` execution + screenshots.

## [2026-11-26] - Frame Groups with Loop Repeat Across Editor, Compiler, and 6502 Engine
- **Room Editor & YAML v5 (`room_editor/`):** Added `FrameGroup(first, last, repeat=1)` (`MAX_GROUP_REPEAT = 255`, flat non-overlapping non-wrapping contiguous runs of `>= 2` frames) in [room_editor/model/glyphs.py](room_editor/model/glyphs.py); added `groups` field, pass-aware `initial_pass_counter`, `step_animation_frame`, `total_loop_ticks`, and `adjust_groups_on_remove` / `adjust_groups_on_reorder` helpers on `GameObject` in [room_editor/model/project.py](room_editor/model/project.py); added `AddFrameGroupCommand`, `RemoveFrameGroupCommand`, `SetFrameGroupRepeatCommand`, and `MoveFrameGroupCommand` plus group preservation on frame edits/reorders/removals/object updates in [room_editor/model/commands.py](room_editor/model/commands.py); added group validation errors/warnings in [room_editor/model/validation.py](room_editor/model/validation.py) and optional YAML `groups` serialization in [room_editor/io/yaml_io.py](room_editor/io/yaml_io.py); added frame list multi-select, `"Group frames"`, `"Loop repeat"` spinbox, `"Select Group"`, `"Ungroup"`, color-coded `[F..]` badges, whole-group moving, and grouped playback previews across [room_editor/ui/stamp_image_widget.py](room_editor/ui/stamp_image_widget.py), [room_editor/ui/objects_view.py](room_editor/ui/objects_view.py), and [room_editor/ui/room_editor_view.py](room_editor/ui/room_editor_view.py).
- **Rooms Compiler ([scripts/rooms_compile.py](scripts/rooms_compile.py)):** Compiled effective groups (`repeat > 1` and not covering all `0..F-1` frames) with zero cost for ungrouped/`repeat==1`/all-frame objects; added `ANIM_FLAG_GROUPS = $20` (`ANIM_BANK_MASK = $1F`), deduplicated compact `F + 2*G` control+pair tables (`anim_grp_lo/hi`, `anim_grp_<K>`), Form 2 reachable transitions including loop-back deltas (`last_g -> first_g`) with `[S][T][T lo][T hi]` headers and exact Form 1 vs Form 2 size comparison, and `ANIM_GRP_TABLE_COUNT` / `ANIM_GRP_BYTES` / `ANIM_F2_GRP_COUNT` equates in [gen/rooms_defs.asm](gen/rooms_defs.asm).
- **6502 Engine ([engine/anim.asm](engine/anim.asm), [zeropage.asm](zeropage.asm), [main.asm](main.asm)):** Extended `room_anim_init` and `anim_tick` Pass 1 & Form 2 Pass 2 with conditional group pass tracking (`anim_st_rep`, conditional `anim_st_vrep`), `zp_anim_f2str`/`zp_anim_nvis`/`zp_anim_nvrep` (`$FB..$FD`), safe `bne @active / rts` fast exit (`11` cyc when disabled), and single-flag skip (`ANIM_FLAG_GROUPS`) for ungrouped objects.
- **Tests & Docs:** Expanded [room_editor/tests/test_animation.py](room_editor/tests/test_animation.py), [tests/test_rooms_compile.py](tests/test_rooms_compile.py), and [tests/test_room_anim.py](tests/test_room_anim.py); updated [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md) and [docs/rooms-data-format.md](docs/rooms-data-format.md); verified via `make all` (`108 passed`), `scripts/check_memory.py` (`$6A7D`), `py65` cycle benchmarks, and `AltirraSDL --bridge`.

## [2026-11-26] - Per-Frame Animation Durations Across Editor, Compiler, and 6502 Engine
- **Room Editor & YAML v5 (`room_editor/`):** Added `duration: int = 0` (`0..255` PAL ticks, `0` = inherit object `animation_speed`, omitted from YAML when `0`) to `StampRegion` in [room_editor/model/glyphs.py](room_editor/model/glyphs.py); added `effective_frame_duration`, `effective_frame_durations`, and `total_loop_ticks` helpers on `GameObject` in [room_editor/model/project.py](room_editor/model/project.py); added `SetObjectFrameDurationCommand` and preserved frame durations across frame replace/reorder/remove/object-update commands (new frames default to `0`) in [room_editor/model/commands.py](room_editor/model/commands.py); added `OBJECT_INVALID_FRAME_DURATION` error and `ANIM_FRAME_DURATION_SPEED_ZERO` warning in [room_editor/model/validation.py](room_editor/model/validation.py); added `"Frame time"` spin box, effective time & loop length labels, and single-shot variable preview timing in [room_editor/ui/stamp_image_widget.py](room_editor/ui/stamp_image_widget.py), [room_editor/ui/objects_view.py](room_editor/ui/objects_view.py), and [room_editor/ui/room_editor_view.py](room_editor/ui/room_editor_view.py).
- **Rooms Compiler ([scripts/rooms_compile.py](scripts/rooms_compile.py)):** Resolved per-frame `duration` overrides to effective ticks, kept uniform objects zero-cost via `ANIM_FLAG_VAR_DUR = $40` (`ANIM_BANK_MASK = $3F`), deduplicated non-uniform tables into compact `anim_dur_pool` (`<= 256 B`, offset in `anim_speed`) or wide `anim_dur_lo`/`anim_dur_hi` + `anim_dur_<K>`, updated `CompileReport` (`anim_uniform_count`, `anim_var_dur_count`, `anim_dur_table_count`, `anim_dur_bytes`), and added `ANIM_DUR_TABLE_COUNT` / `ANIM_DUR_BYTES` / `ANIM_DUR_WIDE` equates in [gen/rooms_defs.asm](gen/rooms_defs.asm).
- **6502 Engine ([engine/anim.asm](engine/anim.asm)):** Updated `room_anim_init` and `anim_tick` Pass 1 to reload `anim_st_cnt` from `anim_speed` for uniform objects or `anim_dur_pool` / `(anim_dur_lo/hi)` for variable-duration objects while keeping `zp_anim_active == 0` at 12 cycles (`+0` cyc when all objects are uniform).
- **Tests & Docs:** Expanded [room_editor/tests/test_animation.py](room_editor/tests/test_animation.py), [tests/test_rooms_compile.py](tests/test_rooms_compile.py), and [tests/test_room_anim.py](tests/test_room_anim.py); updated [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md) and [docs/rooms-data-format.md](docs/rooms-data-format.md); verified via `make all` (`104 passed`), `check_memory.py` (`$6A59`), `py65` cycle measurements, and `AltirraSDL --bridge`.

## [2026-11-26] - Deduplicate Object Animation Slots, Pattern Pool, and Form 1/Form 2 Delta Encoding
- **Room Editor & YAML v5 (`room_editor/`):** Switched [room_editor/model/project.py](room_editor/model/project.py) and [room_editor/model/glyphs.py](room_editor/model/glyphs.py) to classify cells into constant cells (shared static pool, 0 dedicated slots) vs varying cells (within-object sharing of identical per-frame sequences) via single-pass `1..127` code assignment and full budget recomputation on every change; removed `frame_data` in [room_editor/io/yaml_io.py](room_editor/io/yaml_io.py) in favor of `{code, data, object, cells, frames}` dedicated `glyphs` entries; replaced `ANIM_IDENTICAL_FRAMES` with `ANIM_NO_VARYING_CELLS` in [room_editor/model/validation.py](room_editor/model/validation.py); added constant/varying/dedicated breakdown and signed slot delta counter across [room_editor/ui/](room_editor/ui/).
- **Rooms Compiler ([scripts/rooms_compile.py](scripts/rooms_compile.py)):** Compiled animations with the unified constant/varying classification (with or without PNGs using YAML `{cells, frames}`), deduplicated cross-object 8-byte pattern pool (`anim_pool<b>_b0..b7`, automatic `anim_pb_lo/hi` split only when `> 256` patterns), per-object Form 1 (`anim_f1_*`) vs Form 2 cyclic delta (`anim_f2_*` + deduplicated `anim_d_*`) size selection, and expanded [gen/rooms_defs.asm](gen/rooms_defs.asm) / [gen/animations.asm](gen/animations.asm) metadata (`ANIM_POOL_COUNT`, `ANIM_PATTERN_COUNT`, `MAX_ROOM_FORM1_SLOTS`, `ANIM_FLAG_FORM2`, `ANIM_BANK_MASK`).
- **6502 VBI Engine ([engine/anim.asm](engine/anim.asm)):** Reworked `room_anim_init` and `anim_tick` to update only really-changing dedicated slots within `ANIM_VBI_GLYPH_BUDGET = 12` (Form 1 runtime `anim_slot_cur` skip check; Form 2 frame-by-frame cyclic deltas with `anim_st_vis` / mid-delta `anim_st_pos` resume), unrolled single-pool copies (`anim_pool0_b0..b7,X`) with automatic split-pool fallback, expanded ZP to `$E0..$FA` in [zeropage.asm](zeropage.asm) and RAM state arrays in [main.asm](main.asm), and exposed conditional `ANIM_COUNT_COPIES` telemetry for `py65`.
- **Tests & Docs:** Updated [room_editor/tests/test_animation.py](room_editor/tests/test_animation.py), [room_editor/tests/test_compression_and_yaml.py](room_editor/tests/test_compression_and_yaml.py), [tests/test_rooms_compile.py](tests/test_rooms_compile.py), [tests/test_room_anim.py](tests/test_room_anim.py), [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md), [docs/rooms-data-format.md](docs/rooms-data-format.md), and [README.md](README.md); verified with `make all`, `check_memory.py`, `py65` cycle measurements, and `AltirraSDL --bridge`.

## [2026-11-26] - End-to-End Object Frame Animation Across Editor, Compiler, and 6502 VBI Engine
- **Room Editor (`room_editor/`, YAML v5):** Added `1..16` equal-sized `frames` (`StampRegion`) and PAL 50 Hz `animation_speed` (`0..255`) on `GameObject` (`is_animated` iff `len(frames) >= 2 and animation_speed > 0`) in [room_editor/model/project.py](room_editor/model/project.py) and [room_editor/model/glyphs.py](room_editor/model/glyphs.py), with contiguous non-shared dedicated charset slot accounting (`static_unique + sum(dedicated) <= 127`), empty-in-frame-0 slot reservation when non-empty in later frames, foreign-group animated row placement restriction (`ANIMATED_OBJECT_ROW_GROUP_MISMATCH`), frame undo commands in [room_editor/model/commands.py](room_editor/model/commands.py), validation checks in [room_editor/model/validation.py](room_editor/model/validation.py), YAML v5 `frame_data` and `{code, data, object, cell}` serialization/verification in [room_editor/io/yaml_io.py](room_editor/io/yaml_io.py), and frame editing/PAL preview controls across [room_editor/ui/](room_editor/ui/). Migrated [rooms.yaml](rooms.yaml) to `version: 5`.
- **Rooms Compiler & Build:** Extended [scripts/rooms_compile.py](scripts/rooms_compile.py) and [Makefile](Makefile) to ingest YAML v5, emit [gen/animations.asm](gen/animations.asm) (`anim_speed`, `anim_frames`, `anim_slots`, `anim_dst_lo/hi`, `anim_ftbl_lo/hi`, deduplicated `anim_ftbl_<K>` / `anim_fblk_<K>`), `ANIM_*` constants in [gen/rooms_defs.asm](gen/rooms_defs.asm), `obj_anim` in [gen/objects.asm](gen/objects.asm), and `room_anim_count`/`room_anim_lo/hi`/`room_anim_list_<K>` in [gen/rooms.asm](gen/rooms.asm).
- **6502 Runtime Engine:** Fixed swapped `VVBLKI = $0222` / `VVBLKD = $0224` equates in [hardware.asm](hardware.asm), allocated `$E0..$EF` (`zp_anim_*`) in [zeropage.asm](zeropage.asm), implemented [engine/anim.asm](engine/anim.asm) (`room_anim_init`, `anim_tick` with `ANIM_VBI_GLYPH_BUDGET = 12`, round-robin fairness cursor `zp_anim_cursor`, whole-object anti-tear deferral, oversized `>12`-slot resume, and drift-free PAL counters), added `game_vbi_deferred` in [engine/dli.asm](engine/dli.asm), allocated runtime state arrays (`$34E0+`, guarded `< PMG_BASE`) in [main.asm](main.asm), and wired initialization/teardown across [scenes/game.asm](scenes/game.asm), [scenes/title.asm](scenes/title.asm), [scenes/intro.asm](scenes/intro.asm), and [scenes/gameover.asm](scenes/gameover.asm).
- **Tests & Docs:** Added [room_editor/tests/test_animation.py](room_editor/tests/test_animation.py) and [tests/test_room_anim.py](tests/test_room_anim.py), expanded [tests/test_rooms_compile.py](tests/test_rooms_compile.py) and [tests/test_room_screen.py](tests/test_room_screen.py), updated [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md), [docs/rooms-data-format.md](docs/rooms-data-format.md), and [README.md](README.md), and verified via `make all` (`99 passed`), `check_memory.py`, and `AltirraSDL --bridge`.

## [2026-11-25] - Center `STATE_INTRO` Lines and Set `$C0`/`$CE` Colors
- Updated [scripts/compile_intro.py](scripts/compile_intro.py) to center each non-blank line inside 40 columns and emit 10-byte `intro_line_start` and `intro_line_end` tables alongside `intro_screen_data` in [gen/intro_text.asm](gen/intro_text.asm).
- Updated [scenes/intro.asm](scenes/intro.asm) to start and wrap typewriter reveals using `intro_line_start` / `intro_line_end` without typing delays on leading spaces.
- Updated intro palette constants in [colors.asm](colors.asm) to `INTRO_COLBK = $C0`, `INTRO_COLPF2 = $C0`, and `INTRO_COLPF1 = $CE`, and expanded [tests/test_intro_screen.py](tests/test_intro_screen.py) to verify centering and colors.

## [2026-11-25] - Add `STATE_INTRO` Typewriter Scene Between Title Screen and Game
- Added [scripts/compile_intro.py](scripts/compile_intro.py) to validate [texts/intro.txt](texts/intro.txt) (`1..10` lines, `<= 40` characters per line) and compile uppercase text with `title_charset_2` glyph mapping (offset `46` = SPACE, Polish uppercase `Ą..Ż` mapped to `111..119`, em/en dash to `-`) into deterministic [gen/intro_text.asm](gen/intro_text.asm) (`intro_line_len`, `intro_screen_data`), integrated into `data` and `funky_koval.xex` in [Makefile](Makefile).
- Added [scenes/intro.asm](scenes/intro.asm) implementing `STATE_INTRO` in ANTIC Mode 2 (`intro_dlist` with `10` rows separated by `$70` blank scanlines, reusing `400` bytes of `SCREEN_VRAM = $3000` and `title_charset_2`), frame-paced typewriter reveal, subtle POKEY `AUDC1` key-click SFX (silent on spaces and blank lines), immediate FIRE skip (showing all text silently and waiting for trigger release), and subsequent FIRE transition to `STATE_GAME`.
- Added intro palette constants (`INTRO_COLBK`, `INTRO_COLPF2`, `INTRO_COLPF1`) in [colors.asm](colors.asm), zero-page state variables (`$D0..$D9`) in [zeropage.asm](zeropage.asm), and wired `STATE_INTRO` into [main.asm](main.asm) and [scenes/title.asm](scenes/title.asm).
- Added [tests/test_intro_screen.py](tests/test_intro_screen.py) and updated state transition tests in [tests/test_engine.py](tests/test_engine.py), [tests/test_room_screen.py](tests/test_room_screen.py), and [README.md](README.md).

## [2026-11-25] - Implement Initial Room Screen in `funky_koval.xex`
- Added reusable ANTIC Mode 4 room renderer and display setup module [engine/room.asm](engine/room.asm) (`clear_screen_vram`, `room_draw`, `room_setup_display`, 24-entry `screen_row_lo`/`screen_row_hi` lookup tables, and assembly-time 1 KB/4 KB boundary assertions).
- Added room zero-page allocations `$B0..$CB` (`zp_room_*`) in [zeropage.asm](zeropage.asm) and `room_dli_handler` in [engine/dli.asm](engine/dli.asm) to switch `CHBASE`, `COLBK`, and `COLPF0..COLPF3` cleanly across `WSYNC` when adjacent rows differ in style.
- Integrated `gen/rooms_defs.asm`, `ROOMS_ALIGN_CHARSETS = 1` (`$6000+` segment for `gen/charsets.asm`, `gen/styles.asm`, `gen/objects.asm`, `gen/rooms.asm`, `gen/teleports.asm`), and runtime buffers (`room_dlist = $3480`, `cur_row_style = $34A0`, `room_dli_style = $34C0`, `room_dli_count = $34D8`, `cur_room_id = $34D9`) into [main.asm](main.asm) and [Makefile](Makefile).
- Updated `STATE_GAME` in [scenes/game.asm](scenes/game.asm) to silence title-screen PMG, render `START_ROOM` once on entry, enable DLI only when `room_dli_count > 0`, and transition cleanly on edge-detected FIRE (`zp_fire_pressed`).
- Added standalone development PNG renderer [tools/render_room_png.py](tools/render_room_png.py), headless `py65` + PNG verification suite [tests/test_room_screen.py](tests/test_room_screen.py), and documentation in [docs/rooms-data-format.md](docs/rooms-data-format.md) and [README.md](README.md).

## [2026-11-25] - Add `pickable` Object Property to Room Editor & Compiler
- Added `pickable: bool = False` to `GameObject` in [room_editor/model/project.py](room_editor/model/project.py) and `UpdateObjectCommand` in [room_editor/model/commands.py](room_editor/model/commands.py).
- Serialized/deserialized `pickable` (defaulting missing YAML entries to `False`) in [room_editor/io/yaml_io.py](room_editor/io/yaml_io.py).
- Added the `Pickable` checkbox directly below `Non-blockable (hero can pass)` (plus `[PICK]` list badge) in [room_editor/ui/objects_view.py](room_editor/ui/objects_view.py).
- Added `OBJ_FLAG_PICKABLE = $04` (bit 2 of `obj_flags`) in [scripts/rooms_compile.py](scripts/rooms_compile.py), updated [docs/rooms-data-format.md](docs/rooms-data-format.md) and [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md), and added test coverage in [room_editor/tests/test_compression_and_yaml.py](room_editor/tests/test_compression_and_yaml.py), [room_editor/tests/test_architecture_and_gui.py](room_editor/tests/test_architecture_and_gui.py), and [tests/test_rooms_compile.py](tests/test_rooms_compile.py).

## [2026-11-25] - Add MADS Room Data Compiler & Makefile Build Integration
- Added standalone compiler [scripts/rooms_compile.py](scripts/rooms_compile.py) compiling `rooms.yaml` (v4) and group PNGs into six deterministic MADS assembly files in `gen/` (`rooms_defs.asm`, `charsets.asm`, `styles.asm`, `objects.asm`, `rooms.asm`, `teleports.asm`) with 1-based `base - 1` ID indexing, deduplicated cell blocks and row-style tables, z-ordered non-blockable-first compact instance SoA blocks (`3*N + 2*R`), strict/atomic error handling, Polish-safe symbol sanitization, and size reporting.
- Integrated room compilation into [Makefile](Makefile) (`data` and `funky_koval.xex` depend on [rooms.yaml](rooms.yaml), group PNGs via `--list-deps`, and [scripts/rooms_compile.py](scripts/rooms_compile.py)).
- Added [tests/test_rooms_compile.py](tests/test_rooms_compile.py) with an independent `.asm` parser/player verified against a YAML/PNG reference composer, `room_editor.model.compose_room`, MADS assembly (`-d:ROOMS_ALIGN_CHARSETS=1` and `--align-charsets`), limits (`255` objects/instances, `127` glyphs), determinism, and error guarantees.
- Added [docs/rooms-data-format.md](docs/rooms-data-format.md) and updated [README.md](README.md).

## [2026-11-25] - Multi-Palette Object Groups, Per-Row (Group, Palette) Assignments & YAML v4
- Added `DEFAULT_PALETTE_NAME` and `NamedPalette` in [room_editor/model/palette.py](room_editor/model/palette.py) and replaced `ObjectGroup.palette` with an ordered list `ObjectGroup.palettes` (`>= 1`, unique names within the group, first = default) in [room_editor/model/project.py](room_editor/model/project.py) and [room_editor/model/__init__.py](room_editor/model/__init__.py).
- Added `RowAssignment(group, palette)` for per-row `(group, palette)` room DLI assignments, `Project.find_palette_usage()`, and pure model `render_room_row_rgb()` in [room_editor/model/project.py](room_editor/model/project.py).
- Added undoable group palette commands (`AddGroupPaletteCommand`, `RenameGroupPaletteCommand`, `DeleteGroupPaletteCommand`, `ReorderGroupPaletteCommand`, `UpdateGroupPaletteColorsCommand`) and updated `SetRoomRowGroupsCommand`, `UpdateGroupCommand`, and `DeleteGroupCommand` in [room_editor/model/commands.py](room_editor/model/commands.py).
- Added validation checks (`GROUP_NO_PALETTES`, `EMPTY_PALETTE_NAME`, `DUPLICATE_PALETTE_NAME`, `ROOM_INVALID_ROW_GROUP`, `ROOM_INVALID_ROW_PALETTE`, `UNUSED_PALETTE`) in [room_editor/model/validation.py](room_editor/model/validation.py), and bumped serialization to `PROJECT_VERSION = 4` (with compact shorthand/mapping `row_groups` normalization and strict v1/v2/v3 rejection) in [room_editor/io/yaml_io.py](room_editor/io/yaml_io.py).
- Updated [room_editor/ui/objects_view.py](room_editor/ui/objects_view.py), [room_editor/ui/stamp_image_widget.py](room_editor/ui/stamp_image_widget.py), [room_editor/ui/room_editor_view.py](room_editor/ui/room_editor_view.py), [room_editor/ui/rendering_qt.py](room_editor/ui/rendering_qt.py), [room_editor/ui/canvas_view.py](room_editor/ui/canvas_view.py), and [room_editor/ui/main_window.py](room_editor/ui/main_window.py) with named palette CRUD, UI-only Preview Palette selectors, 5-color row gutter swatches, paired `(group, palette)` row controls, and `Row: <group> / <palette>` status bar display.
- Updated [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md) (v4.0), [README.md](README.md), and existing test suites, and added [room_editor/tests/test_palettes_and_rows.py](room_editor/tests/test_palettes_and_rows.py).

## [2026-11-25] - Resize Room Editor Grid to 40x24 (160x192 ANTIC 4 Pixels) & YAML v3
- Updated [room_editor/model/project.py](room_editor/model/project.py) and [room_editor/model/__init__.py](room_editor/model/__init__.py) to set `ROOM_HEIGHT = 24`, bump `PROJECT_VERSION = 3`, and define derived room pixel/display constants (`ANTIC4_PIXEL_ASPECT_X`, `ROOM_PIXEL_WIDTH = 160`, `ROOM_PIXEL_HEIGHT = 192`, `ROOM_DISPLAY_WIDTH = 320`, `ROOM_DISPLAY_HEIGHT = 192`) as the single source of truth.
- Updated [room_editor/ui/rendering_qt.py](room_editor/ui/rendering_qt.py), [room_editor/ui/canvas_view.py](room_editor/ui/canvas_view.py), [room_editor/ui/room_editor_view.py](room_editor/ui/room_editor_view.py), and [room_editor/ui/teleport_dialog.py](room_editor/ui/teleport_dialog.py) to derive rendering size, `5:3` (`320:192`) canvas cell aspect ratio, row-group controls (`Set All 24 Rows`), and coordinate bounds (`Y (0..23)`) from model constants.
- Updated [room_editor/model/graph.py](room_editor/model/graph.py), [room_editor/io/yaml_io.py](room_editor/io/yaml_io.py), [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md) (v3.0), and [README.md](README.md) for `40×24` rooms, 24 DLI rows, and YAML `version: 3`.
- Updated and expanded [room_editor/tests/test_png_and_glyphs.py](room_editor/tests/test_png_and_glyphs.py), [room_editor/tests/test_validation.py](room_editor/tests/test_validation.py), [room_editor/tests/test_canvas_and_graph.py](room_editor/tests/test_canvas_and_graph.py), [room_editor/tests/test_compression_and_yaml.py](room_editor/tests/test_compression_and_yaml.py), and [room_editor/tests/test_architecture_and_gui.py](room_editor/tests/test_architecture_and_gui.py) to verify `40×24` constants, `y=23`/`y=24` bounds, 24-row validation, `repeat-xy: [40, 24]`, `repeat-y: 24`, and 24-cell edge passages.

## [2026-11-25] - Replace `.fnt` Charsets with Indexed-PNG Image Groups & YAML v2 in Room Editor
- Removed `.fnt` charset loading and manual object grid editing (`room_editor/io/fnt.py`, `room_editor/model/charset.py`, `room_editor/tests/test_fnt_and_palette.py`) and added `Pillow>=10.0.0` to [pyproject.toml](pyproject.toml).
- Added pure image/glyph model in [room_editor/model/glyphs.py](room_editor/model/glyphs.py) (`IndexedImage`, `StampRegion`, `GlyphEntry`, `GlyphTable`, pixel mapping permutations, 127-glyph budget and mapping validation helpers) and indexed PNG loader/validator in [room_editor/io/png.py](room_editor/io/png.py) (enforcing mode `P`, palette indexes `0..3`, and `4×8`-multiple dimensions).
- Updated [room_editor/model/project.py](room_editor/model/project.py), [room_editor/model/commands.py](room_editor/model/commands.py), [room_editor/model/tools.py](room_editor/model/tools.py), and [room_editor/model/validation.py](room_editor/model/validation.py) with deterministic glyph table derivation (ascending object ID, row-major, pure-`00` transparent code `0`, `colpf3` codes `129..255`), `127`-glyph limit enforcement, and updated validation errors/warnings.
- Updated [room_editor/io/yaml_io.py](room_editor/io/yaml_io.py) to YAML `version: 2` (rejecting v1, storing `image`, `pixel_mapping`, derived `glyphs`, `colpf3`, and `region`, plus glyph-table consistency verification on load).
- Replaced the Charset Picker and Stamp Grid UI with [room_editor/ui/stamp_image_widget.py](room_editor/ui/stamp_image_widget.py) and [room_editor/ui/png_import_dialog.py](room_editor/ui/png_import_dialog.py), and updated [room_editor/ui/rendering_qt.py](room_editor/ui/rendering_qt.py), [room_editor/ui/objects_view.py](room_editor/ui/objects_view.py), [room_editor/ui/room_editor_view.py](room_editor/ui/room_editor_view.py), and [room_editor/ui/main_window.py](room_editor/ui/main_window.py).
- Added [room_editor/tests/test_png_and_glyphs.py](room_editor/tests/test_png_and_glyphs.py), updated all `room_editor/tests/` suites, and updated [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md) (v2.0) and [README.md](README.md).

## [2026-11-24] - Switch to Embedded Instrument Catalog in `atari_music` v0.21.0
- Upgraded `atari_music` to `v0.21.0` in [requirements.txt](requirements.txt) and `.venv`, using the built-in `atari_music/instruments/catalog.json` bundled in the wheel.
- Removed redundant local `data/instruments/catalog.json`, dropped `INSTRUMENT_CATALOG` and `--catalog` from [Makefile](Makefile), and updated [README.md](README.md).

## [2026-11-24] - Fix `make all` Audio Build (`CATALOG_NOT_FOUND`)
- Restored [data/instruments/catalog.json](data/instruments/catalog.json) matching the pinned `atari_music` `v0.17.1` wheel (whose package distribution omits `data/instruments/catalog.json`).
- Updated [Makefile](Makefile) to declare `INSTRUMENT_CATALOG := data/instruments/catalog.json` as an `audio` dependency and pass `--catalog $(INSTRUMENT_CATALOG)` to [scripts/compile_music.py](scripts/compile_music.py), and updated [README.md](README.md).


## [2026-11-24] - Add `--colors` Color Mapping Option to `png_to_charset.py`
- Added `parse_color_map`, `format_color_map`, and `--colors` / `--color-map` CLI option to [scripts/png_to_charset.py](scripts/png_to_charset.py), supporting positional 2-bit codes (`00,10,11,01`), ANTIC 4 register aliases (`bk,pf0,pf1,pf2`), and explicit `index=target` pairs (indices `0..255`), rejecting duplicate target codes.
- Updated `validate_image`, `extract_and_build_charset`, `extract_all_charsets`, and `process_image_to_charset` to apply the mapping and write `color_map` to the generated JSON metadata.
- Regenerated [gen/title_charsets.json](gen/title_charsets.json) and expanded unit tests in [tests/test_png_to_charset.py](tests/test_png_to_charset.py).


## [2026-11-24] - Reserve Empty Glyph at Index 0 in `png_to_charset.py`
- Updated `extract_and_build_charset` in [scripts/png_to_charset.py](scripts/png_to_charset.py) to initialize `unique_patterns` with `EMPTY_GLYPH` (`b"\x00" * 8`) at index `0`, guaranteeing index `0` is always reserved as an empty character in every generated `.fnt` charset.
- Added unit tests in [tests/test_png_to_charset.py](tests/test_png_to_charset.py) covering non-empty-only images, empty tile reuse at index `0`, multi-band splitting, and `--fill-font` offset preservation.


## [2026-11-24] - Layered Overlap Rules, Z-Order, and Room Composition in Room Editor
- Updated [room_editor/model/project.py](room_editor/model/project.py) so overlap checks enforce non-overlap only between blockable (`non-blockable = false`) non-zero cells, added `compose_room` / `compose_room_with_sources` (Layer 1 `non-blockable` in z-order, Layer 2 blockable on top, code `0` transparent), updated `find_instance_at` to target the topmost visible cell, added `find_blockable_overlaps_for_object`, and updated `Project.__eq__` to preserve non-blockable z-order.
- Updated [room_editor/model/tools.py](room_editor/model/tools.py) and [room_editor/model/commands.py](room_editor/model/commands.py) so line/rect/fill skip room overlap checks for `non-blockable` objects, and added undoable z-order commands (`ReorderNonBlockableCommand`, `BringToFrontCommand`, `SendToBackCommand`, `MoveInstanceUpCommand`, `MoveInstanceDownCommand`).
- Updated [room_editor/model/compression.py](room_editor/model/compression.py) and [room_editor/model/validation.py](room_editor/model/validation.py) to emit blockable entries first (greedy largest-rectangle) followed by non-blockable entries in exact z-order (merging only gapless consecutive row-major runs), restrict `INSTANCE_OVERLAP` errors to blockable pairs, and add `HIDDEN_NON_BLOCKABLE_INSTANCE` warnings.
- Updated [room_editor/ui/rendering_qt.py](room_editor/ui/rendering_qt.py), [room_editor/ui/room_editor_view.py](room_editor/ui/room_editor_view.py), [room_editor/ui/main_window.py](room_editor/ui/main_window.py), and [room_editor/ui/objects_view.py](room_editor/ui/objects_view.py) to render via `compose_room`, add z-order context menu and `Edit -> Arrange` shortcuts, and refuse turning `non-blockable` off when conflicts exist.
- Added [room_editor/SPECIFICATION.md](room_editor/SPECIFICATION.md) (v1.1), [room_editor/tests/test_layering_and_zorder.py](room_editor/tests/test_layering_and_zorder.py), and expanded tests in [room_editor/tests/test_compression_and_yaml.py](room_editor/tests/test_compression_and_yaml.py), [room_editor/tests/test_validation.py](room_editor/tests/test_validation.py), and [room_editor/tests/test_canvas_and_graph.py](room_editor/tests/test_canvas_and_graph.py).


## [2026-11-24] - Implement Atari 8-bit ANTIC 4 Room Editor (PySide6)
- Added [pyproject.toml](pyproject.toml), updated [requirements.txt](requirements.txt) with `PyYAML>=6.0.2`, and added the 256-entry Atari PAL GTIA RGB table in [room_editor/data/pal_palette.json](room_editor/data/pal_palette.json).
- Implemented the Qt-free model layer under `room_editor/model/` ([room_editor/model/palette.py](room_editor/model/palette.py), [room_editor/model/charset.py](room_editor/model/charset.py), [room_editor/model/project.py](room_editor/model/project.py), [room_editor/model/graph.py](room_editor/model/graph.py), [room_editor/model/compression.py](room_editor/model/compression.py), [room_editor/model/validation.py](room_editor/model/validation.py), [room_editor/model/tools.py](room_editor/model/tools.py), [room_editor/model/commands.py](room_editor/model/commands.py)) covering 40x20 rooms, connected room groups, bidirectional teleports, passage computation, deterministic `repeat-x`/`repeat-y`/`repeat-xy` compression, validation, and undo/redo commands.
- Implemented `.fnt` (1024-byte) loading, relative path resolution, and deterministic YAML round-trip serialization in [room_editor/io/fnt.py](room_editor/io/fnt.py) and [room_editor/io/yaml_io.py](room_editor/io/yaml_io.py).
- Built the PySide6 GUI in `room_editor/ui/` ([room_editor/ui/main_window.py](room_editor/ui/main_window.py), [room_editor/ui/canvas_view.py](room_editor/ui/canvas_view.py), [room_editor/ui/room_editor_view.py](room_editor/ui/room_editor_view.py), [room_editor/ui/objects_view.py](room_editor/ui/objects_view.py), [room_editor/ui/settings_view.py](room_editor/ui/settings_view.py), [room_editor/ui/color_picker.py](room_editor/ui/color_picker.py), [room_editor/ui/teleport_dialog.py](room_editor/ui/teleport_dialog.py), [room_editor/ui/validation_dialog.py](room_editor/ui/validation_dialog.py), [room_editor/ui/rendering_qt.py](room_editor/ui/rendering_qt.py)) and entry points [room_editor/main.py](room_editor/main.py) and [room_editor/__main__.py](room_editor/__main__.py).
- Added comprehensive pytest coverage (`T-1`..`T-10`, architecture isolation, undo/redo, and offscreen GUI smoke tests) in `room_editor/tests/` and documented usage in [README.md](README.md).


## [2026-11-20] - Remove Redundant Local `data/instruments/catalog.json`
- Removed redundant `data/instruments/catalog.json` from the repository, upgraded `atari_music` to `v0.17.1` in [requirements.txt](requirements.txt), and updated [Makefile](Makefile) and [README.md](README.md) to rely on the built-in instrument catalog packaged inside `atari_music`.


## [2026-11-20] - Drive Title Music Arrangement from `music/title.arrangement.json`
- Added [scripts/compile_music.py](scripts/compile_music.py) to parse `channel_assignments`, `program_change_policy`, and `player_version` from [music/title.arrangement.json](music/title.arrangement.json) and invoke `atari_music` (`import-dsl` + `arrange`) on [music/title.dsl](music/title.dsl).
- Updated [Makefile](Makefile) `audio` target to depend on [music/title.arrangement.json](music/title.arrangement.json) and compile [gen/title_music.asm](gen/title_music.asm) via [scripts/compile_music.py](scripts/compile_music.py).
- Updated `test_title_music_playback` in [tests/test_engine.py](tests/test_engine.py) to derive expected `AUDCTL` and channel mapping dynamically from [music/title.arrangement.json](music/title.arrangement.json), and updated [README.md](README.md).


## [2026-11-17] - AI Composition Prompt System Upgrade (`atari-music` `ai-compose`)
- Updated [.agents/skills/atari-music-composer/SKILL.md](.agents/skills/atari-music-composer/SKILL.md) with the new opt-in `ai-compose` options (`--prompt-profile rich`, `--key`, `--mode`, `--notes`, `--tempo-grid`, `--plan-first`, `--quality-passes`) implemented in `atari-music` (`feat/rich-prompts`).
- Updated [README.md](README.md) with the `audio` build stage (`music/title.dsl`, `data/instruments/catalog.json`, `lib/player.asm`) and per-row DLI sine-wave animation in `engine/dli.asm` and `scenes/title.asm`.


## [2026-11-17] - Title Screen Music Playback Integration (atari-music v2)
- Added `music/title.dsl` ("Shadow of the Citadel", 136 BPM, 16-bit POKEY bass on CH1+CH2) and SSOT instrument catalog in [data/instruments/catalog.json](data/instruments/catalog.json).
- Integrated `atari-music import-dsl` and `atari-music arrange` (--channel-instrument 1=bass_16bit_pure 3=lead_pure_pluck 4=perc_hihat_closed --program-change-policy replace --player-version v2) into [Makefile](Makefile) generating [gen/title_music.asm](gen/title_music.asm).
- Integrated relocatable 4-channel POKEY v2 player in [lib/player.asm](lib/player.asm) at `org $5000` with zero page allocation `PLAYER_ZP_BASE = $A0` in [zeropage.asm](zeropage.asm) and sequential assembly in [main.asm](main.asm).
- Hooked music playback into title state in [scenes/title.asm](scenes/title.asm): `music_init` and `music_play` in `title_enter`, per-frame `music_update` in `title_update`, and `music_stop` when exiting to `STATE_GAME` on FIRE press.
- Added automated integration test `test_title_music_playback` in [tests/test_engine.py](tests/test_engine.py) (py65) and verified live playback with AltirraSDL / AltirraBridge.


## [2026-11-15] - Sine-Wave Animation for Fifth Player Text via Per-Row DLI
- Configured `TITLE_P5_Y = 48`, `TITLE_P5_WAVE_SPEED = 1`, and `TITLE_P5_WAVE_STEP = 3` in [colors.asm](colors.asm), and added `zp_p5_wave_phase = $97` in [zeropage.asm](zeropage.asm).
- Updated [scripts/compile_title_screen.py](scripts/compile_title_screen.py) to emit `TITLE_DLI_COUNT = 24`, per-row `title_dli_chbase` entries (rows `0..23`), and `DL_DLI` before every Mode 4 row (`3rd DL_BLANK8` + rows `0..22`) in `title_dlist`.
- Extended `title_dli_handler` in [engine/dli.asm](engine/dli.asm) to update both `CHBASE` and `HPOSM0..HPOSM3` from `p5_row_x,x` on every Mode 4 row (`78` cycles).
- Added 64-entry sine table `p5_sin_table` (-20..+20), `p5_row_x` (24 bytes), and `title_update_p5_wave` in [scenes/title.asm](scenes/title.asm), and compacted `p5_text_data` to 8 bytes per character (`P5_TEXT_LEN = 152`, leading `$00` on Mode 4 badline scanline 0 followed by 7 glyph rows) aligned to Mode 4 rows `2..20`.
- Updated `test_title_dli_handler_switches_charsets` and `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to verify 24 per-row DLIs, sine-wave phase progression, and `HPOSM0..HPOSM3` updates.


## [2026-11-12] - Render Fifth Player Text ("PRESS FIRE TO START") Without Inversion
- Removed `eor #$FF` and `$FF` border padding in `title_enter` ([scenes/title.asm](scenes/title.asm)) so `p5_text_data` is copied directly to `PMG_MISSILES + TITLE_P5_Y`.
- Updated `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to assert non-inverted missile bytes and `0x00` padding.


## [2026-11-12] - Restore 1x Missile Width for Static Inverted Fifth Player Text
- Changed `TITLE_P5_SIZEM` to `$00` (1x width) and `TITLE_P5_X` to `200` in [colors.asm](colors.asm).
- Updated `HPOSM0..HPOSM3` spacing back to 2 color clocks (`200, 202, 204, 206`) in [scenes/title.asm](scenes/title.asm).
- Updated `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to verify 1x `SIZEM` and 2-clock missile spacing.


## [2026-11-12] - Static x2 Inverted Fifth Player Text ("PRESS FIRE TO START")
- Replaced the vertical Fifth Player scroller with a static, inverted, 2x-wide missile bar in [scenes/title.asm](scenes/title.asm) (`p5_text_data`, `P5_TEXT_LEN = 190`).
- Set `SIZEM = $55` (`TITLE_P5_SIZEM`) and spaced `HPOSM0..HPOSM3` by 4 color clocks starting at `TITLE_P5_X = 192` in [colors.asm](colors.asm) and [scenes/title.asm](scenes/title.asm).
- Copied `p5_text_data` with `eor #$FF` into `PMG_MISSILES + TITLE_P5_Y` (`33..222`, padded with `$FF` at `32` and `223`) during `title_init`, and removed `title_update_scroller` and unused `TITLE_P5_SCROLL_SPEED` / `zp_scroller_pos` / `zp_scroller_speed_cnt` from [zeropage.asm](zeropage.asm).
- Updated [tests/test_engine.py](tests/test_engine.py) (`test_title_pmg_subtitle_setup`) to assert `SIZEM`, `HPOSM0..HPOSM3` 4-clock spacing, and inverted missile bitmap bytes.


## [2026-11-12] - Add Animation Frames Reverse Option to Sprite Studio
- Added `btn_reverse` ("Reverse") and `reverse_requested` signal to `TimelineWidget` in [sprite_studio/widgets/timeline.py](sprite_studio/widgets/timeline.py).
- Added "Reverse Frames" action in the Edit menu and connected `reverse_requested` to `_on_reverse_frames` in [sprite_studio/main.py](sprite_studio/main.py).
- Implemented `_on_reverse_frames` with full undo/redo command history support, reversing the sprite's animation frame sequence and adjusting active frame selection.
- Added automated unit tests in [tests/test_sprite_studio.py](tests/test_sprite_studio.py) verifying button signal emission, frame reversal, and undo/redo behavior.


## [2026-11-11] - Correct Pairwise Bit Alignment for Fifth Player Missiles
- Resolved split/gap distortion on glyphs (such as 'I' and 'T') by correctly mapping font pixels across the four 2-bit missile registers:
  - Missile 0 (leftmost): bits 1 (left) and 0 (right)
  - Missile 1: bits 3 (left) and 2 (right)
  - Missile 2: bits 5 (left) and 4 (right)
  - Missile 3 (rightmost): bits 7 (left) and 6 (right)
- Recompiled `scroller_text_data` in [scenes/title.asm](scenes/title.asm).
- Verified sharp and solid rendering of all letters (`I`, `T`, `P`, `R`, `E`, `S`, `F`, `O`, `A`) in AltirraSDL emulator.


## [2026-11-11] - Correct Fifth Player Bit Order (Fix Mirrored Glyph Rendering)
- Replaced missile text bitmap table `scroller_text_data` in [scenes/title.asm](scenes/title.asm) with bit-reversed values.
- Mapped font bit 7 to missile 3 (rightmost) and bit 0 to missile 0 (leftmost) to correct the horizontal mirroring on GTIA hardware.
- Verified correct orientation of letters in AltirraSDL emulator screenshot.


## [2026-11-11] - Implement Fifth Player Vertical Scroller ("PRESS FIRE TO START")
- Enabled Fifth Player mode in GTIA (`PRIOR = $10` / `GPRIOR = $10`), combining all 4 missiles into an 8-color-clock wide 5th player.
- Configured 5th player color via `COLPF3` / `COLOR3` (`TITLE_P5_COLOR = $0E`) and horizontal position at the right screen edge (`TITLE_P5_X = 200` with `HPOSM0..HPOSM3` spaced by 2 color clocks) in [colors.asm](colors.asm).
- Added precompiled scanline bitmap table for `"PRESS FIRE TO START"` in [scenes/title.asm](scenes/title.asm).
- Implemented `title_update_scroller` called each frame in `title_update` to smoothly scroll text from bottom to top through `PMG_MISSILES` (`$3B00`).
- Added Zero-Page state variables `zp_scroller_pos` (`$97-$98`) and `zp_scroller_speed_cnt` (`$99`) in [zeropage.asm](zeropage.asm).
- Updated integration tests in [tests/test_engine.py](tests/test_engine.py) covering 5th player register setup and scroller execution.
- Verified in AltirraSDL emulator.


## [2026-11-11] - Update Title Screen Image and PMG Horizontal Coordinates
- Updated source image [images/title.png](images/title.png).
- Adjusted `TITLE_START_X = 48` in [colors.asm](colors.asm) for PMG subtitle horizontal positioning.
- Verified test suite and memory checks.


## [2026-11-11] - Selectable Glyphs Inversion Flag in PMG Text Renderer
- Added `zp_pmg_invert` (`$96`) to [zeropage.asm](zeropage.asm) and integrated `eor zp_pmg_invert` into `pmg_render_text` in [lib/pmg.asm](lib/pmg.asm).
- Configured Player 0 (`"WBREW"`) and Player 1 (`"SOBIE"`) to render in normal mode (`zp_pmg_invert = 0`).
- Configured Player 2 (`"WBREW"`) and Player 3 (`"SOBIE"`) to render in inverse mode (`zp_pmg_invert = $FF`) in [scenes/title.asm](scenes/title.asm).
- Updated py65 test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to assert normal bitmaps on P0/P1 and inverted bitmaps on P2/P3.
- Rebuilt and verified with AltirraSDL emulator.


## [2026-11-11] - Normal Text Rendering (No Inversion) and Duplicate Text on P2/P3
- Removed byte inversion (`eor #$FF`) in `pmg_render_text` ([lib/pmg.asm](lib/pmg.asm)), restoring normal font glyph rendering for all Players.
- Configured Player 2 to render the exact same text as Player 0 (`"WBREW"` via `text_wbrew`) in [scenes/title.asm](scenes/title.asm).
- Configured Player 3 to render the exact same text as Player 1 (`"SOBIE"` via `text_sobie`) in [scenes/title.asm](scenes/title.asm).
- Updated integration test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to assert non-inverted font bitmaps on P0, P1, P2, and P3.
- Verified in AltirraSDL emulator.


## [2026-11-11] - Set Underlay Blocks on Players 2 & 3 to 5 Spaces
- Updated `text_spaces` in [scenes/title.asm](scenes/title.asm) to 5 inverted spaces (`TEXT_SPACES_LEN = 5`).
- Updated py65 test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to assert 5 glyph spans for Player 2 and Player 3.
- Rebuilt and verified with AltirraSDL emulator.


## [2026-11-11] - Decouple Vertical Position Assertions in PMG Subtitle Tests
- Removed rigid assumption that all 4 players must have identical Y positions (`TITLE_P0_Y == TITLE_P1_Y == TITLE_P2_Y == TITLE_P3_Y`) from `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py).
- Allowed independent vertical offsets between the foreground text (Player 0/1) and the background underlay blocks (Player 2/3).
- Rebuilt and verified all 7 unit/py65 tests pass.


## [2026-11-11] - Per-Player Character Margin Configuration
- Added individual margin labels in [colors.asm](colors.asm): `TITLE_P0_MARGIN`, `TITLE_P1_MARGIN`, `TITLE_P2_MARGIN`, and `TITLE_P3_MARGIN`.
- Added Zero-Page parameter `zp_pmg_margin` (`$95`) in [zeropage.asm](zeropage.asm).
- Updated `pmg_render_text` in [lib/pmg.asm](lib/pmg.asm) to read character spacing dynamically from `zp_pmg_margin`.
- Updated [scenes/title.asm](scenes/title.asm) to supply each player's individual margin before invoking `pmg_render_text`.
- Updated py65 test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to assert buffer strides based on each player's individual margin label.
- Verified in AltirraSDL emulator.


## [2026-11-11] - Restore 6 Underlay Spaces on Players 2 & 3
- Set `text_spaces` back to 6 inverted spaces (`TEXT_SPACES_LEN = 6`) in [scenes/title.asm](scenes/title.asm) for Player 2 and Player 3.
- Kept trimmed 5-character titles on Player 0 (`"WBREW"`) and Player 1 (`"SOBIE"`).
- Updated py65 test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to assert 5 chars for P0/P1 and 6 blocks for P2/P3.
- Verified in AltirraSDL emulator.


## [2026-11-11] - Trim Spaces from PMG Subtitle Strings ("WBREW" and "SOBIE")
- Updated `text_wbrew` in [scenes/title.asm](scenes/title.asm) to 5 characters (`W, B, R, E, W`, removed trailing space).
- Updated `text_sobie` in [scenes/title.asm](scenes/title.asm) to 5 characters (`S, O, B, I, E`, removed leading space).
- Adjusted underlay blocks `text_spaces` to 5 spaces (`TEXT_SPACES_LEN = 5`).
- Updated py65 test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py).
- Rebuilt and verified with AltirraSDL emulator.


## [2026-11-11] - Adjust PMG Width: 2x Width for P0 & P1, 4x Width for P2 & P3
- Added `TITLE_P0_SIZE = 1`, `TITLE_P1_SIZE = 1`, `TITLE_P2_SIZE = 3`, `TITLE_P3_SIZE = 3` configuration labels in [colors.asm](colors.asm).
- Updated `pmg_init_single_line` in [lib/pmg.asm](lib/pmg.asm) to configure `SIZEP0` & `SIZEP1` to 2x width (`1`) and `SIZEP2` & `SIZEP3` to 4x width (`3`).
- Updated `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to assert individual player size register values.
- Verified in AltirraSDL bridge and emulator.


## [2026-11-11] - Multi-Player PMG Underlay (P2/P3 under P0/P1) for Subtitle Coloring
- Assigned Player 0 (`TITLE_P0_X = 128`) for `"WBREW "` and Player 1 (`TITLE_P1_X = 160`) for `" SOBIE"`.
- Assigned Player 2 (`TITLE_P2_X = TITLE_P0_X = 128`) and Player 3 (`TITLE_P3_X = TITLE_P1_X = 160`) underneath Player 0 and Player 1 respectively.
- Rendered 6 inverted spaces (`$FF` solid blocks) via `pmg_render_text` onto Player 2 and Player 3 taking into account `TITLE_PMG_CHAR_MARGIN`.
- Inverted text on P0 and P1 acts as cutouts letting Player 2 and Player 3 colors (`TITLE_P2_COLOR`, `TITLE_P3_COLOR`) shine through, creating two-color text with background in [scenes/title.asm](scenes/title.asm) and [colors.asm](colors.asm).
- Added configurable color labels `TITLE_P0_COLOR..TITLE_P3_COLOR` and position coordinates in [colors.asm](colors.asm).
- Configured 4x player widths for all 4 players (`SIZEP0..SIZEP3 = 3`) in [lib/pmg.asm](lib/pmg.asm).
- Updated integration test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) covering all 4 player buffers, positions, sizes, and colors.
- Verified visual output and register states in AltirraSDL emulator.


## [2026-11-11] - Align PMG Subtitles and Add Edge Spaces ("WBREW " and " SOBIE")
- Set both Player 1 and Player 2 to the same starting vertical position (`TITLE_P1_Y = TITLE_SUBTITLE_Y`, `TITLE_P2_Y = TITLE_SUBTITLE_Y`) in [colors.asm](colors.asm).
- Updated strings in [scenes/title.asm](scenes/title.asm) to `"WBREW "` (6 characters, space at end) on Player 1 and `" SOBIE"` (6 characters, space at start) on Player 2.
- Updated `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to verify the inverted space blocks and character alignment.
- Verified visual output in AltirraSDL.


## [2026-11-11] - Configurable Margin Between PMG Characters
- Added `TITLE_PMG_CHAR_MARGIN = 1` constant to [colors.asm](colors.asm) for easily configuring the vertical line spacing between characters on Players.
- Updated `pmg_render_text` in [lib/pmg.asm](lib/pmg.asm) to advance the destination pointer by `(32 + TITLE_PMG_CHAR_MARGIN)`.
- Adjusted `TITLE_P2_Y = 65` in [colors.asm](colors.asm) and updated tests in [tests/test_engine.py](tests/test_engine.py).
- Verified in AltirraSDL emulator.


## [2026-11-11] - Switch PMG to Single-Line (2 KB) with 4x Line Duplication
- Switched PMG buffer to Single-Line resolution (2 KB at `$3800..$3FFF`): Player buffers are 256 bytes each (`PMG_P1 = $3D00`, `PMG_P2 = $3E00`) with DMA control `SDMCTL = $3E` in [main.asm](main.asm) and [scenes/title.asm](scenes/title.asm).
- Updated `pmg_clear` to clear all 8 pages of 2 KB PMG RAM in [lib/pmg.asm](lib/pmg.asm).
- Updated `pmg_render_text` ([lib/pmg.asm](lib/pmg.asm)) to quadruple each font row (4 bytes = 4 scanlines), writing 32 bytes per glyph.
- Updated scanline offsets in [colors.asm](colors.asm): `TITLE_P1_Y = 32`, `TITLE_P2_Y = 64` (1:1 visual match with previous 2-line rendering).
- Updated test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) and verified pixel-exact identical appearance in AltirraSDL.


## [2026-11-11] - Inverted PMG Subtitle ("WBREW SOBIE")
- Added `eor #$FF` pixel inversion in `pmg_render_text` ([lib/pmg.asm](lib/pmg.asm)) so that characters on Player 1 and Player 2 are rendered in inverse video (solid background with transparent letter cutouts).
- Added `lib/pmg.asm` dependency to `ASM_SRCS` in [Makefile](Makefile).
- Updated test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) to assert inverted bitmap patterns.
- Verified in AltirraSDL emulator.


## [2026-11-10] - Offset Player 2 "SOBIE" Down by 1 Character
- Split vertical position configuration in [colors.asm](colors.asm) into `TITLE_P1_Y = 16` and `TITLE_P2_Y = 32` (+16 bytes = 1 full quadrupled character row offset).
- Updated PMG rendering in [scenes/title.asm](scenes/title.asm) and test assertions in [tests/test_engine.py](tests/test_engine.py).
- Verified visually in AltirraSDL.


## [2026-11-10] - PMG 4x Width and Quadruple Height Proportions
- Configured hardware Player 1 and Player 2 width expansion to 4x (`SIZEP1 = 3`, `SIZEP2 = 3`) in [lib/pmg.asm](lib/pmg.asm).
- Updated `pmg_render_text` to duplicate each font row twice in double-line PMG memory (2 bytes = 4 scanlines), matching the 4-color-clock horizontal expansion for an exact 1:1 square pixel aspect ratio.
- Adjusted subtitle positioning in [colors.asm](colors.asm): `TITLE_SUBTITLE_Y = 16`, `TITLE_P1_X = 128`, `TITLE_P2_X = 160`.
- Updated test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) for 4x PMG verification and confirmed through AltirraSDL bridge.


## [2026-11-10] - PMG Double-Line Subtitle "WBREW SOBIE" on Title Screen
- Reserved 1 KB memory buffer for Double-Line Player-Missile Graphics at `$3800..$3BFF` (`PMG_BASE`) with equates for players and missiles in [main.asm](main.asm).
- Created [lib/pmg.asm](lib/pmg.asm) with procedures `pmg_clear`, `pmg_init_double_line`, and `pmg_render_text` rendering glyph bitmaps from `title_charset_2` (base index 46 = space) into player graphic buffers.
- Added configurable position and color equates in [colors.asm](colors.asm): `TITLE_SUBTITLE_Y`, `TITLE_P1_X`, `TITLE_P2_X`, `TITLE_P1_COLOR`, `TITLE_P2_COLOR`.
- In [scenes/title.asm](scenes/title.asm), Player 1 renders "WBREW" and Player 2 renders "SOBIE", placed adjacent to each other in the title screen center.
- Added automated `py65` test `test_title_pmg_subtitle_setup` in [tests/test_engine.py](tests/test_engine.py) and visually verified through AltirraSDL bridge.


## [2026-11-10] - Export Game Font Equates from Title Charset Metadata
- Updated [scripts/compile_title_screen.py](scripts/compile_title_screen.py) to read `filled_glyphs` and emit `GAME_FONT_GLYPH_OFFSET` ($2E / 46) and `GAME_FONT_GLYPH_COUNT` (82) equates into [gen/title_screen_data.asm](gen/title_screen_data.asm).
- Extended [tests/test_engine.py](tests/test_engine.py) to assert presence and correctness of the generated `GAME_FONT_*` symbol equates in `main.lab`.


## [2026-11-10] - Fill Last Charset Free Slots with Game Font
- Added `--fill-font` flag to [scripts/png_to_charset.py](scripts/png_to_charset.py) and integrated `fonts/font.fnt` into the build pipeline in [Makefile](Makefile).
- The remaining 82 unused glyph slots of the 3rd title charset (`title_charset_2.fnt`, addresses `$4800 + 46*8 .. $4BFF`) are now filled with the first 82 characters of `fonts/font.fnt`.
- Added automated `py65` test `test_last_charset_filled_with_game_font` in [tests/test_engine.py](tests/test_engine.py) verifying byte-exact matching of the filled slots against `fonts/font.fnt`.


## [2026-11-10] - Initial Engine, State Machine, and Antic 4 Title Screen with DLI & RLE
- Extended [scripts/png_to_charset.py](scripts/png_to_charset.py) to split a 4-color indexed PNG into multiple non-overlapping 1KB character sets (`.fnt`, max 128 glyphs each) aligned to full 8-pixel character rows and export combined metadata to JSON.
- Added [scripts/compile_title_screen.py](scripts/compile_title_screen.py) to compress the 960-byte `glifs` map using Tebe/MadTeam Run-Length Encoding (RLE) and generate [gen/title_screen_data.asm](gen/title_screen_data.asm) with the ANTIC Mode 4 Display List (`DL_DLI` transitions), `CHBASE` lookup table, and 1KB-aligned font inclusions.
- Created [colors.asm](colors.asm) with configurable global palette constants (`PAL_COLBK = $00`, `PAL_COLOR0 = $FF`, `PAL_COLOR1 = $2E`, `PAL_COLOR2 = $96`).
- Implemented the 6502 RLE decompressor in [lib/rle.asm](lib/rle.asm), mid-frame `CHBASE` DLI switching in [engine/dli.asm](engine/dli.asm), edge-triggered joystick polling in [engine/input.asm](engine/input.asm), and the game state machine (`STATE_TITLE_SCREEN`, `STATE_GAME`, `STATE_GAME_OVER_FAILURE`, `STATE_GAME_OVER_SUCCESS`) across [main.asm](main.asm), [scenes/title.asm](scenes/title.asm), [scenes/game.asm](scenes/game.asm), and [scenes/gameover.asm](scenes/gameover.asm).
- Added [Makefile](Makefile), [scripts/check_memory.py](scripts/check_memory.py), and `py65` emulation tests in [tests/test_engine.py](tests/test_engine.py).

