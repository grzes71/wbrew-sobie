# Room Data Format (MADS 6502 Assembly)

This document specifies the binary/assembly data format emitted into `gen/` by [`scripts/rooms_compile.py`](../scripts/rooms_compile.py) from [`rooms.yaml`](../rooms.yaml) (YAML v5 + indexed group PNGs; PAL 50 Hz timing).

---

## 1. Compiler Invocation & Build Integration

### Automatic Build (`Makefile`)

The seven generated `.asm` files belong to `data` (and are prerequisites of `funky_koval.xex`):

```bash
make data     # Regenerates gen/title_screen_data.asm and gen/rooms_*.asm when inputs change
make all      # Runs assets -> data -> audio -> xex -> tests -> check_memory
make clean    # Removes gen/ (which is in .gitignore) and funky_koval.xex
```

`Makefile` automatically tracks `rooms.yaml`, `scripts/rooms_compile.py`, and all group PNG paths returned by `--list-deps`.

### Manual Invocation

```powershell
.venv\Scripts\python.exe scripts/rooms_compile.py rooms.yaml --out gen [--strict] [--align-charsets]
```

| Flag | Meaning |
|---|---|
| `--out <dir>` | Destination directory (default: `gen`). Outputs are written atomically via temp files; errors (or warnings with `--strict`) write **nothing**. |
| `--strict` | Promotes validation warnings (e.g. `UNUSED_OBJECT`, `OBJECT_ROW_GROUP_MISMATCH`) to errors and exits non-zero. |
| `--align-charsets` | Emits unconditional `.align $400` before every `charset_<group>` (without it, `.align $400` is wrapped in `.ifdef ROOMS_ALIGN_CHARSETS`). |
| `--list-deps` | Prints referenced group PNG paths for `Makefile` dependency tracking and exits. |

Every generated file starts with a deterministic `GENERATED - DO NOT EDIT` header and the SHA-256 hash of `rooms.yaml` plus all group PNG bytes (no timestamps).

---

## 2. Including Generated Files Across Segments (`icl`)

Each concern lives in a separate file under `gen/` so `main.asm` can place them into the appropriate memory segments (`org` strictly ascending, all below `$C000`):

```asm
; At top of main.asm (equates emit 0 bytes, can be included anywhere before use)
    icl 'gen/rooms_defs.asm'

; Inside game data segment (e.g. $2000+ or $6000+)
    icl 'gen/styles.asm'
    icl 'gen/objects.asm'
    icl 'gen/rooms.asm'
    icl 'gen/teleports.asm'
    icl 'gen/animations.asm'

; Inside 1 KB-aligned charset segment (e.g. org $4000 or assembled with -d:ROOMS_ALIGN_CHARSETS=1)
    org $4000
    icl 'gen/charsets.asm'
```

### Charset 1 KB (`$0400`) Alignment Note

ANTIC Mode 4 reads `CHBASE` high byte only (`bits 7..2` select a 1 KB boundary for 1024-byte charsets, so low 10 bits of `charset_<group>` MUST be `$000`).  
- If you place `icl 'gen/charsets.asm'` immediately at `org $4000` (each charset is 1024 bytes, so consecutive charsets remain 1 KB-aligned automatically), no extra padding is needed.
- If you link `gen/charsets.asm` inside another segment or pass `-d:ROOMS_ALIGN_CHARSETS=1` to MADS (or `--align-charsets` to the compiler), MADS inserts `.align $400` before each `charset_<group>`.

---

## 3. ID-Indexed Table Trick (`base - 1`)

Room IDs and object IDs use `1`-based numbering (`1..ROOM_MAX_ID`, `1..OBJ_MAX_ID`, at most `255`).  
To allow direct 6502 indexing (`lda room_left,x` or `lda obj_w,x` with `X = id`, zero `dex` instructions), each ID-indexed table emits `MAX_ID` bytes under `<label>_base` (unused gap IDs contain `$00`) and defines:

```asm
room_left_base
    .byte $02, $04, $01, $00
room_left = room_left_base - 1
```

Because `room_left` points 1 byte before `room_left_base`:
- `lda room_left,x` with `X = 1` reads `room_left_base + 0` (Room 1).
- `lda room_left,x` with `X = N` reads `room_left_base + (N - 1)` (Room N).
- Never index with `X = 0` (`X = 0` means "none").

---

## 4. Generated Files & Symbols Reference

### `gen/rooms_defs.asm` (0 bytes emitted — equates only)

| Symbol | Size | Meaning |
|---|---|---|
| `ROOM_WIDTH`, `ROOM_HEIGHT`, `ROOM_SCREEN_SIZE` | equate | `40`, `24`, `960` |
| `ROOM_COUNT`, `ROOM_MAX_ID` | equate | Active room count and highest room ID (`1..255`) |
| `OBJ_COUNT`, `OBJ_MAX_ID` | equate | Active object count and highest object ID (`1..255`) |
| `GROUP_COUNT`, `STYLE_COUNT` | equate | Group/charset count and count of unique `(group, palette)` row styles (`<= 256`) |
| `TAG_COUNT`, `TAG_PLANE_COUNT` | equate | Global tag count and byte planes required (`ceil(TAG_COUNT / 8)`) |
| `TELEPORT_COUNT` | equate | Bidirectional teleport entry count (`0..255`) |
| `ANIM_COUNT` | equate | Active animated object count (`0..255`) with `len(frames) >= 2`, `animation_speed > 0`, and `>= 1` varying cell |
| `ANIM_POOL_COUNT`, `ANIM_PATTERN_COUNT` | equate | Pattern-pool bank count (`ceil(pats / 256)` when `ANIM_COUNT > 0`) and deduplicated 8-byte pattern count |
| `MAX_ROOM_ANIMS` | equate | Maximum unique animated objects present in any single room (`0..255`) |
| `MAX_ROOM_ANIM_SLOTS`, `MAX_ROOM_FORM1_SLOTS` | equate | Maximum combined dedicated slots (`S`) and Form-1 slots (`anim_slot_cur` RAM capacity) in any single room |
| `ANIM_PAL_HZ` | equate | `50` (PAL 50 Hz VBLANK timebase; PAL only) |
| `ANIM_FLAG_FORM2`, `ANIM_BANK_MASK` | equate | `anim_flags` bit 7 (`$80` = Form 2 cyclic delta) and bits 6..0 (`$7F` = pool bank index) |
| `OBJ_FLAG_NON_BLOCKABLE`, `OBJ_FLAG_COLPF3`, `OBJ_FLAG_PICKABLE` | equate | Bit masks `$01`, `$02`, and `$04` for `obj_flags` |
| `ROOM_FLAG_UNIFORM_STYLE` | equate | Bit mask `$01` for `room_flags` |
| `INST_Y_REPEAT_MASK`, `INST_Y_COORD_MASK` | equate | Bit masks `$80` and `$1F` for instance `y_flag` byte |
| `START_ROOM`, `START_X`, `START_Y` | equate | Hero starting room ID and cell `(x, y)` (`0..39`, `0..23`) |
| `GROUP_<NAME>` | equate | `0..GROUP_COUNT-1` (sanitized ASCII uppercase) |
| `STYLE_<GROUP>_<PALETTE>` | equate | `0..STYLE_COUNT-1` style ID |
| `TAG_<NAME>`, `TAG_<NAME>_IDX`, `TAG_<NAME>_PLANE` | equate | Single-bit mask (`$01..$80`), bit index, and `obj_tags<P>` plane index |
| `ANIM_<OBJ>` | equate | 0-based index `0..ANIM_COUNT-1` into `gen/animations.asm` tables (emitted for animated objects only) |
| `OBJ_<NAME>` | equate | Object ID (`1..OBJ_MAX_ID`) |
| `ROOM_<NAME>` | equate | Room ID (`1..ROOM_MAX_ID`) |

### `gen/charsets.asm`

| Label | Size | Indexing / Format |
|---|---|---|
| `charset_<group>` | `1024 B` each | `128` glyphs × `8` bytes. Glyph `0` is all `$00` (transparent). Codes `1..127` are assigned in one pass (ascending object ID, row-major): static cells and **constant cells** of animated objects share the deduplicated static pool, while **varying cells** of each animated object take dedicated slots shared only across identical per-frame sequences within that same object (`static_unique + dedicated_slots <= 127`), initialized with frame `0`. High bit (`128..255`) uses the exact same `8`-byte shapes in hardware (`COLPF3` instead of `COLPF2`). |

### `gen/styles.asm`

Each unique `(group, palette)` pair used by at least one room row receives a style ID `0..STYLE_COUNT-1`. Stored as SoA indexed directly by `Y` or `X = style_id`:

| Label | Size | Indexing | Meaning |
|---|---|---|---|
| `style_chbase` | `STYLE_COUNT B` | `[style_id]` | High byte of `charset_<group>` (`>charset_<group>`) for `CHBASE` |
| `style_colbk` | `STYLE_COUNT B` | `[style_id]` | PAL color byte for `COLBK` (`$D01A`) |
| `style_colpf0` | `STYLE_COUNT B` | `[style_id]` | PAL color byte for `COLPF0` (`$D016`) |
| `style_colpf1` | `STYLE_COUNT B` | `[style_id]` | PAL color byte for `COLPF1` (`$D017`) |
| `style_colpf2` | `STYLE_COUNT B` | `[style_id]` | PAL color byte for `COLPF2` (`$D018`) |
| `style_colpf3` | `STYLE_COUNT B` | `[style_id]` | PAL color byte for `COLPF3` (`$D019`) |

### `gen/objects.asm`

All `obj_*` tables are 1-based ID-indexed via `base - 1` (`1 <= X <= OBJ_MAX_ID`):

| Label | Size | Indexing | Meaning |
|---|---|---|---|
| `obj_w` (`obj_w_base - 1`) | `OBJ_MAX_ID B` | `[obj_id]` | Stamp width in cells (`1..40`) |
| `obj_h` (`obj_h_base - 1`) | `OBJ_MAX_ID B` | `[obj_id]` | Stamp height in cells (`1..24`) |
| `obj_flags` (`obj_flags_base - 1`) | `OBJ_MAX_ID B` | `[obj_id]` | Bit 0 (`$01`) = `non-blockable`; bit 1 (`$02`) = `colpf3`; bit 2 (`$04`) = `pickable`; bits 3..7 reserved (`0`) |
| `obj_anim` (`obj_anim_base - 1`) | `OBJ_MAX_ID B` | `[obj_id]` | `0` = static object; otherwise `anim_idx + 1` (`1..ANIM_COUNT`) |
| `obj_tags<P>` (`obj_tags<P>_base - 1`) | `OBJ_MAX_ID B` | `[obj_id]` | Tag bitmask plane `P` (`0..TAG_PLANE_COUNT-1`, 8 tags per byte). Omitted if `TAG_COUNT == 0`. |
| `obj_data_lo`, `obj_data_hi` | `OBJ_MAX_ID B` each | `[obj_id]` | 16-bit pointer to deduplicated row-major `w * h` cell code block |
| `obj_cells_<K>` | `w * h B` (`<= 255 B`) | `[dy * w + dx]` | Row-major cell codes. `0` = transparent (never drawn). If `colpf3` is enabled, all non-zero cells already include `+$80` (`129..255`). |

### `gen/rooms.asm`

All `room_*` tables are 1-based ID-indexed via `base - 1` (`1 <= X <= ROOM_MAX_ID`):

| Label | Size | Indexing | Meaning |
|---|---|---|---|
| `room_left`, `room_right`, `room_up`, `room_down` | `ROOM_MAX_ID B` each | `[room_id]` | Adjacent neighbour room ID (`0` = no neighbour) |
| `room_flags` | `ROOM_MAX_ID B` | `[room_id]` | Bit 0 (`$01`) = `ROOM_FLAG_UNIFORM_STYLE` (all 24 rows share one style ID); bits 1..7 reserved (`0`) |
| `room_rowstyle_lo` | `ROOM_MAX_ID B` | `[room_id]` | If `room_flags & $01`: single `style_id` directly. Else: low byte of 24-byte `room_rowstyle_tbl_<K>`. |
| `room_rowstyle_hi` | `ROOM_MAX_ID B` | `[room_id]` | If `room_flags & $01`: `$00`. Else: high byte of 24-byte `room_rowstyle_tbl_<K>`. |
| `room_inst_count` | `ROOM_MAX_ID B` | `[room_id]` | Total instance records `N` (`0..255`) in the room's draw block |
| `room_rep_count` | `ROOM_MAX_ID B` | `[room_id]` | Count `R` (`0..N`) of entries in the draw block that carry repeats (`y_flag` bit 7 set) |
| `room_inst_lo`, `room_inst_hi` | `ROOM_MAX_ID B` each | `[room_id]` | 16-bit pointer to deduplicated `room_inst_block_<K>` (`$0000` when `N == 0`) |
| `room_anim_count` (`_base - 1`) | `ROOM_MAX_ID B` | `[room_id]` | Count `A` (`0..ANIM_COUNT`) of unique animated objects placed in the room |
| `room_anim_lo`, `room_anim_hi` | `ROOM_MAX_ID B` each | `[room_id]` | 16-bit pointer to deduplicated `room_anim_list_<K>` (`$0000` when `A == 0`) |
| `room_anim_list_<K>` | `A B` | `[0..A-1]` | Sorted unique 0-based `anim_idx` bytes present in the room (shared instances animate in sync) |
| `room_rowstyle_tbl_<K>` | `24 B` each | `[row 0..23]` | Deduplicated 24-byte table of `style_id`s for mixed-style rooms |
| `room_inst_block_<K>` | `3*N + 2*R B` | Plane-based SoA | See Section 5 below |

### `gen/animations.asm` (PAL 50 Hz Only)

All `anim_*` metadata arrays are **0-based SoA** (`0 <= Y < ANIM_COUNT`) so `room_anim_list_<K>` bytes index directly without adjustment. Constant cells are excluded completely (they remain in `obj_cells_*` using static pool codes and are never touched at runtime).

| Label | Size | Indexing | Meaning |
|---|---|---|---|
| `anim_speed` | `ANIM_COUNT B` | `[anim_idx]` | PAL VBLANK ticks between frame changes (`1..255`; `50` = 1.00 s) |
| `anim_frames` | `ANIM_COUNT B` | `[anim_idx]` | Frame count `F` (`2..16`) |
| `anim_slots` | `ANIM_COUNT B` | `[anim_idx]` | Number `S` (`>= 1`) of dedicated charset slots owned by varying cells |
| `anim_chbase` | `ANIM_COUNT B` | `[anim_idx]` | High byte of target charset (`>charset_<group>`) |
| `anim_flags` | `ANIM_COUNT B` | `[anim_idx]` | Bit 7 (`$80`) = Form 2 cyclic delta (`0` = Form 1 sequence table); bits 6..0 (`$7F`) = pool bank `b` (`0..ANIM_POOL_COUNT-1`) |
| `anim_scodes_lo`, `anim_scodes_hi` | `ANIM_COUNT B` each | `[anim_idx]` | 16-bit pointer to `anim_scodes_<K>` (`S` base char codes in `1..127`) |
| `anim_data_lo`, `anim_data_hi` | `ANIM_COUNT B` each | `[anim_idx]` | 16-bit pointer to `anim_f1_<K>` (Form 1) or `anim_f2_<K>` (Form 2) |
| `anim_scodes_<K>` | `S B` each | `[slot 0..S-1]` | Dedicated charset base codes (`1..127`) matching each slot in `anim_f1`/`anim_f2` |
| `anim_f1_<K>` | `S * F B` | `[frame * S + slot]` | **Form 1** (selected when `size_f2 >= size_f1`): frame-major pattern indices into pool bank `b` |
| `anim_f2_<K>` | `S + 2*F B` | `[f0_pats][<d..][>d..]` | **Form 2** (selected when `size_f2 < size_f1`): frame-0 patterns (`S B`) + split pointers to `anim_d_<K>` |
| `anim_d_<K>` | `1 + 2*C B` | `[C, s0, p0, ...]` | Deduplicated cyclic delta block entering frame `k` from `(k-1) mod F` (`C` changed pairs) |
| `anim_pool<b>_b0..b7` | `P B` × 8 | `[pat_idx]` | Deduplicated cross-object pattern pool split across `8` byte planes (`P <= 256` per bank) |
| `anim_pb_lo`, `anim_pb_hi` | `8 * ANIM_POOL_COUNT B` | `[b * 8 + row]` | Plane lookup tables emitted **only** when `ANIM_POOL_COUNT > 1` (`> 256` total patterns) |

### `gen/teleports.asm`

| Label | Size | Indexing | Meaning |
|---|---|---|---|
| `tp_a_room`, `tp_a_x`, `tp_a_y` | `TELEPORT_COUNT B` each | `[0..TELEPORT_COUNT-1]` | Endpoint A room ID and cell `(x, y)` |
| `tp_b_room`, `tp_b_x`, `tp_b_y` | `TELEPORT_COUNT B` each | `[0..TELEPORT_COUNT-1]` | Endpoint B room ID and cell `(x, y)` |

Each teleport entry is **bidirectional**: when standing at `(curr_room, px, py)`, scan `0..TELEPORT_COUNT-1`: if it matches `tp_a_*`, warp to `tp_b_*`; if it matches `tp_b_*`, warp to `tp_a_*`.

---

## 5. Draw Semantics, COLPF3, and Compact Instance Layout

### Draw Order & Transparency
1. Clear the 960-byte screen buffer (`$3000..$33BF`) to `$00` (code `0`, pure `COLBK`).
2. Iterate `room_inst_block_<K>` entries `0..N-1` sequentially:
   - The compiler **always places all `non-blockable` instances first** (in exact YAML z-order), followed by **all `blockable` instances**.
   - Expand `repeat-w x repeat-h` in steps of `(obj_w[id], obj_h[id])`.
   - For each cell byte in `obj_cells_*`: **if the byte is `$00`, skip it** (transparent — preserves whatever was previously drawn, including underlying non-blockable layers or empty background). Write only non-zero bytes.

### How `COLPF3` Works
In ANTIC Mode 4, glyph shape bytes in `charsets.asm` only encode codes `0..127` (`1024` bytes). When screen RAM contains a byte with bit 7 set (`128..255`), ANTIC still fetches glyph `(code & $7F)` from the charset, **but substitutes `COLPF3` (`$D019`) instead of `COLPF2` (`$D018`) for pixel value `%11`**. Because the compiler already adds `+$80` to every non-zero cell in `obj_cells_*` for objects with `colpf3: true` (keeping empty `0` cells as `$00`), runtime draw code copies each non-zero cell byte directly to VRAM with zero runtime masking or branching.

### Compact Instance Layout vs 5-Plane Baseline
For a room with `N` entries where `R` entries have repeats (`rw > 1` or `rh > 1`), `room_inst_block_<K>` lays out up to 5 contiguous SoA byte planes:

| Offset from block start | Length | Contents |
|---|---|---|
| `0` | `N` bytes | `inst_obj[0..N-1]` (`obj_id`) |
| `N` | `N` bytes | `inst_x[0..N-1]` (`0..39`) |
| `2 * N` | `N` bytes | `inst_y_flag[0..N-1]`: bits `0..4` = `y` (`0..23`), bit 7 (`$80`) = `1` if entry has repeat counts |
| `3 * N` (present iff `R > 0`) | `R` bytes | `rep_w[0..R-1]` (`1..40`), one entry per entry whose bit 7 is set |
| `3 * N + R` (present iff `R > 0`) | `R` bytes | `rep_h[0..R-1]` (`1..24`), in the same repeat order |

Compared to the 5-plane baseline (`5 * N` bytes, storing `rep_w = 1, rep_h = 1` for every single instance), this saves `2 * (N - R)` bytes per room while keeping every array 8-bit indexed (`bpl` tests repeat bit in 2 cycles) and preserving exact z-order. On `rooms.yaml` (`K1`–`K4`), total instance payload drops from **550 B** (baseline) to **386 B** (`-164 B`, **29.8% reduction**, or `~11.3%` of a `960 B` uncompressed screen including rowstyles).

---

## 6. Example 6502 / MADS Reference Sketches (Illustrative Only — Not Part of Build)

> [!NOTE]
> The snippets below are documentation examples illustrating how runtime code should consume the generated tables. They are **not** included in the game build.

### Example: Resolving Row Styles into a 24-Byte Screen Cache & DLI

```asm
; Input: X = current room ID (1..ROOM_MAX_ID)
; Output: fills `cur_row_style` (24 bytes in RAM) with style IDs 0..STYLE_COUNT-1
.proc example_load_room_styles
    lda room_flags,x
    and #ROOM_FLAG_UNIFORM_STYLE
    beq @mixed

    lda room_rowstyle_lo,x      ; uniform style ID
    ldy #ROOM_HEIGHT-1
@fill_uniform
    sta cur_row_style,y
    dey
    bpl @fill_uniform
    rts

@mixed
    lda room_rowstyle_lo,x
    sta zp_ptr
    lda room_rowstyle_hi,x
    sta zp_ptr+1
    ldy #ROOM_HEIGHT-1
@copy_mixed
    lda (zp_ptr),y
    sta cur_row_style,y
    dey
    bpl @copy_mixed
    rts
.endp

; Example DLI triggered before each Mode 4 row (zp_dli_idx = 0..23)
.proc example_room_dli
    pha
    txa
    pha
    ldx zp_dli_idx
    ldy cur_row_style,x         ; style ID for row X
    sta WSYNC
    lda style_chbase,y
    sta CHBASE
    lda style_colbk,y
    sta COLBK
    lda style_colpf0,y
    sta COLPF0
    lda style_colpf1,y
    sta COLPF1
    lda style_colpf2,y
    sta COLPF2
    lda style_colpf3,y
    sta COLPF3
    inx
    cpx #ROOM_HEIGHT
    bcc @ok
    ldx #0
@ok stx zp_dli_idx
    pla
    tax
    pla
    rti
.endp
```

### Example: Decoding a Room's Instance Block

```asm
; Input: X = room ID (1..ROOM_MAX_ID)
; Computes 5 SoA plane ZP pointers once, then draws N instances in order:
;   zp_inst_obj = base, zp_inst_x = base + N, zp_inst_yf = base + 2*N,
;   zp_rep_w    = base + 3*N, zp_rep_h = base + 3*N + R
.proc example_draw_room
    ; Clear SCREEN_VRAM (960 bytes) to $00 first ...
    lda room_inst_count,x
    beq @done
    sta zp_inst_total
    lda room_inst_lo,x
    sta zp_inst_obj
    clc
    adc zp_inst_total
    sta zp_inst_x
    ; (propagate carry into zp_inst_x+1, repeat +N for zp_inst_yf and zp_rep_w, +R for zp_rep_h)
    ...
    ldy #0                      ; instance index 0..N-1
    sty zp_rep_idx              ; repeat plane index 0..R-1
@inst_loop
    lda (zp_inst_obj),y
    tax                         ; X = obj_id
    lda (zp_inst_x),y
    sta zp_cur_x
    lda (zp_inst_yf),y
    bpl @single_rep             ; bit 7 clear -> rw=1, rh=1
    and #INST_Y_COORD_MASK
    sta zp_cur_y
    sty zp_save_y
    ldy zp_rep_idx
    lda (zp_rep_w),y
    sta zp_rw
    lda (zp_rep_h),y
    sta zp_rh
    inc zp_rep_idx
    ldy zp_save_y
    jmp @draw_grid
@single_rep
    sta zp_cur_y
    lda #1
    sta zp_rw
    sta zp_rh
@draw_grid
    ; Draw zp_rw x zp_rh copies with step (obj_w[X], obj_h[X]); skip cell bytes == $00!
    ...
    iny
    cpy zp_inst_total
    bne @inst_loop
@done
    rts
.endp
```

### Example: Bidirectional Teleport Check

```asm
; Checks player position (zp_room, zp_px, zp_py) against TELEPORT_COUNT entries.
.proc example_check_teleport
    ldx #TELEPORT_COUNT
    beq @none
    dex
@loop
    lda tp_a_room,x
    cmp zp_room
    bne @check_b
    lda tp_a_x,x
    cmp zp_px
    bne @check_b
    lda tp_a_y,x
    cmp zp_py
    bne @check_b
    ; Matched A -> warp to B
    lda tp_b_room,x
    sta zp_next_room
    lda tp_b_x,x
    sta zp_next_x
    lda tp_b_y,x
    sta zp_next_y
    sec
    rts
@check_b
    lda tp_b_room,x
    cmp zp_room
    bne @next
    lda tp_b_x,x
    cmp zp_px
    bne @next
    lda tp_b_y,x
    cmp zp_py
    bne @next
    ; Matched B -> warp to A
    lda tp_a_room,x
    sta zp_next_room
    lda tp_a_x,x
    sta zp_next_x
    lda tp_a_y,x
    sta zp_next_y
    sec
    rts
@next
    dex
    bpl @loop
@none
    clc
    rts
.endp
```

---

## 7. Runtime Initial Room Screen (`STATE_GAME`)

### State Flow & Start Room Selection
1. `state_machine_init` in [`main.asm`](../main.asm) initializes input, clears `zp_anim_active`/`zp_anim_pending`, and enters `STATE_TITLE_SCREEN`.
2. Pressing FIRE on the title screen transitions through `STATE_INTRO` to `STATE_GAME` (`game_enter` in [`scenes/game.asm`](../scenes/game.asm)).
3. `game_enter` disables DLI/DMA/animations, silences title-screen PMG, selects `START_ROOM` from `gen/rooms_defs.asm`, calls `room_draw`, `room_setup_display`, and `room_anim_init` (`X = START_ROOM`), atomically installs `room_dlist`, `VDSLST = room_dli_handler`, and `VVBLKD = game_vbi_deferred` (`$0224`) with `NMIEN = $00`, enables playfield DMA (`SDMCTL = $22`), and enables `NMIEN = $C0` iff `room_dli_count > 0` (`$40` for uniform-style rooms).
4. `game_update` waits for a rising edge on `zp_fire_pressed` (`engine/input.asm`) and restores `VVBLKD = XITVBV` + `zp_anim_active = 0` before transitioning to `STATE_GAME_OVER_*`.

### VBI Object Animation Engine (`engine/anim.asm`, PAL 50 Hz Only)
- **Deferred VBI (`game_vbi_deferred` via `VVBLKD`):** Tests `zp_anim_active` first; on static rooms (`zp_anim_active == 0`) `anim_tick` exits in `12` cycles (`20` cycles total for `game_vbi_deferred` up to `XITVBV`), resets `zp_dli_idx = 0`, and exits cleanly.
- **Minimal Real Copies Only & Budget (`ANIM_VBI_GLYPH_BUDGET = 12` slots/VBI = `<= 96` bytes):**
  - Pass 1 decrements all `anim_st_cnt[0..anim_room_count-1]` counters unconditionally (zero timer drift even when copies defer) and advances `anim_st_frame` modulo `anim_frames`.
  - Pass 2 services pending objects round-robin from `zp_anim_cursor`:
    - **Form 1:** Compares each slot's target pattern index against `anim_slot_cur[sbase + s]`, skipping unchanged slots with `0` charset writes and `0` budget cost.
    - **Form 2:** Walks `[count, slot, pat]` delta pairs frame-by-frame (`anim_st_vis` -> `anim_st_frame`), preserving any in-flight `anim_st_pos` if deferred mid-delta so no frame change is lost.
  - When `ANIM_POOL_COUNT <= 1`, `_anim_copy_pattern` uses unrolled `anim_pool0_b0..b7,X` loads (`~110` cycles/glyph); when `ANIM_POOL_COUNT > 1` (`> 256` unique patterns), it indexes `(anim_pb_lo/hi)` per bank.
- **Measured CPU Cost (`py65`, production build `count_copies=False`):**
  - Static room (`zp_anim_active == 0`): `room_anim_init` = `32` cyc, `anim_tick` = `12` cyc, `game_vbi_deferred` = `20` cyc.
  - Single-pool Form 1 (`12` varying slots): `0` changed slots = `842` cyc; `1` changed slot = `531`–`550` cyc; `12` worst case = `3,047` cyc (`game_vbi_deferred` = `3,072` cyc, ~26.9 scanlines).
  - Single-pool Form 2 (`12` varying slots): `1` delta pair = `626` cyc (`game_vbi_deferred` = `651` cyc); `12` worst case = `3,057` cyc (`game_vbi_deferred` = `3,082` cyc, ~27.0 scanlines).
  - Split-pool (`ANIM_POOL_COUNT = 2`, `12` worst case): `anim_tick` = `6,535` cyc (`game_vbi_deferred` = `6,560` cyc).
- **Room Re-entry Reset:** `room_anim_init` copies frame `0` bytes into each varying dedicated charset RAM slot, initializes `anim_slot_cur` for Form 1 objects, and resets `anim_st_cnt = anim_speed` and `anim_st_vis = anim_st_frame = anim_st_pos = 0`.

### Runtime Memory Map & Zero-Page Usage

| Region / Symbol | Address | Size | Purpose |
| --- | --- | --- | --- |
| `SCREEN_VRAM` | `$3000..$33BF` | `960 B` | Shared `40×24` ANTIC Mode 4 screen buffer (does not cross 4 KB boundary) |
| `room_dlist` | `$3480..$349F` | `32 B` | Runtime ANTIC Mode 4 Display List (`3×DL_BLANK8`, `24×DL_MODE_4`, `LMS`, `JVB`; does not cross 1 KB boundary) |
| `cur_row_style` | `$34A0..$34B7` | `24 B` | Active room per-row style cache (`0..23`) |
| `room_dli_style` | `$34C0..$34D7` | `24 B` | Ordered target style IDs for DLI transitions |
| `room_dli_count` | `$34D8` | `1 B` | Scheduled DLI transition count (`0..23`) |
| `cur_room_id` | `$34D9` | `1 B` | Currently displayed 1-based room ID |
| `anim_room_count`, `anim_st_*`, `anim_slot_cur` | `$34E0..` | `1 + 7*ANIM_STATE_CAP + ANIM_SLOT_CAP B` | Active-room animated object count, IDs, counters, target/visible frames, pending flags, pair/slot cursors, Form 1 bases, and `anim_slot_cur` cache (guarded `< $3800`) |
| Room Data & Charsets | `$6000..$6949` | `2378 B` | `gen/charsets.asm` (`1 KB` aligned via `ROOMS_ALIGN_CHARSETS = 1`), `gen/styles.asm`, `gen/objects.asm`, `gen/rooms.asm`, `gen/teleports.asm`, `gen/animations.asm`, `gen/intro_text.asm` |
| `zp_room_*` | `$B0..$CB` | `28 B` | Plane pointers, stamp cursor, repeat counters, and scratch bytes in [`zeropage.asm`](../zeropage.asm) (`zp_dli_idx = $82` reused for DLI indexing) |
| `zp_anim_*` | `$E0..$FA` | `27 B` | VBI-safe animation state flags, budget, cursor, source/scode/dest/bank pointers, and Form 1/2 scratch bytes in [`zeropage.asm`](../zeropage.asm) |

### Known Limitations
- PAL-only animation timing (`50` Hz VBLANK ticks; NTSC timing is uncalibrated).
- Gameplay mechanics (hero sprite/PMG, movement, collisions, room scrolling/transitions, enemies, pickups, and teleports) are not yet implemented.
- Each DLI transition writes `CHBASE`, `COLBK`, and `COLPF0..COLPF3` after `STA WSYNC` (preloading `CHBASE` and `COLBK` before `WSYNC`); `COLPF2` and `COLPF3` complete slightly into the start of scanline 0 of the new row (~cycle 32–40), which is glitch-free on scanlines with background border (`COLBK`) or `COLPF0`/`COLPF1` content, and could show a brief mid-scanline tint if `COLPF2`/`COLPF3` pixels appear at column 0 of a transition row.
