# Project History — Funky Koval - Wbrew Sobie

<!-- AGENT INSTRUCTIONS: Prepend new history entries directly below this comment. Use format: ## [YYYY-MM-DD] - [Brief Title] and relative file paths only. -->

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

