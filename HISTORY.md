# Project History — Funky Koval - Wbrew Sobie

<!-- AGENT INSTRUCTIONS: Prepend new history entries directly below this comment. Use format: ## [YYYY-MM-DD] - [Brief Title] and relative file paths only. -->

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

