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
| `ANIM_DUR_TABLE_COUNT`, `ANIM_DUR_BYTES`, `ANIM_DUR_WIDE` | equate | Deduplicated non-uniform duration table count, total duration bytes, and lookup mode (`0` = compact pool `<= 256 B`, `1` = `_lo/_hi` pointers) |
| `ANIM_GRP_TABLE_COUNT`, `ANIM_GRP_BYTES`, `ANIM_F2_GRP_COUNT` | equate | Deduplicated effective group table count, total group table bytes (`0` when no effective groups), and grouped Form 2 object count |
| `MAX_ROOM_ANIMS` | equate | Maximum unique animated objects present in any single room (`0..255`) |
| `MAX_ROOM_ANIM_SLOTS`, `MAX_ROOM_FORM1_SLOTS` | equate | Maximum combined dedicated slots (`S`) and Form-1 slots (`anim_slot_cur` RAM capacity) in any single room |
| `ANIM_PAL_HZ` | equate | `50` (PAL 50 Hz VBLANK timebase; PAL only) |
| `ANIM_FLAG_FORM2`, `ANIM_FLAG_VAR_DUR`, `ANIM_FLAG_GROUPS`, `ANIM_BANK_MASK` | equate | `anim_flags` bit 7 (`$80` = Form 2 cyclic delta), bit 6 (`$40` = per-frame duration table), bit 5 (`$20` = effective frame groups), and bits 4..0 (`$1F` = pool bank index) |
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
| `anim_speed` | `ANIM_COUNT B` | `[anim_idx]` | When `anim_flags & $40 == 0`: uniform effective duration (`1..255` PAL ticks). When `anim_flags & $40 != 0` and `ANIM_DUR_WIDE == 0`: byte offset into `anim_dur_pool` (`0` when `ANIM_DUR_WIDE == 1`). |
| `anim_frames` | `ANIM_COUNT B` | `[anim_idx]` | Frame count `F` (`2..16`) |
| `anim_slots` | `ANIM_COUNT B` | `[anim_idx]` | Number `S` (`>= 1`) of dedicated charset slots owned by varying cells |
| `anim_chbase` | `ANIM_COUNT B` | `[anim_idx]` | High byte of target charset (`>charset_<group>`) |
| `anim_flags` | `ANIM_COUNT B` | `[anim_idx]` | Bit 7 (`$80`) = Form 2 cyclic delta (`0` = Form 1); bit 6 (`$40`) = per-frame duration table (`0` = uniform); bit 5 (`$20`) = effective frame groups (`0` = ungrouped); bits 4..0 (`$1F`) = pool bank `b` (`0..ANIM_POOL_COUNT-1`) |
| `anim_scodes_lo`, `anim_scodes_hi` | `ANIM_COUNT B` each | `[anim_idx]` | 16-bit pointer to `anim_scodes_<K>` (`S` base char codes in `1..127`) |
| `anim_data_lo`, `anim_data_hi` | `ANIM_COUNT B` each | `[anim_idx]` | 16-bit pointer to `anim_f1_<K>` (Form 1) or `anim_f2_<K>` (Form 2) |
| `anim_dur_lo`, `anim_dur_hi` | `ANIM_COUNT B` each | `[anim_idx]` | 16-bit pointer to `anim_dur_<K>` (`$0000` if uniform); emitted **only** when `ANIM_DUR_WIDE == 1` (`> 256` unique duration bytes) |
| `anim_grp_lo`, `anim_grp_hi` | `ANIM_COUNT B` each | `[anim_idx]` | 16-bit pointer to `anim_grp_<K>` (`$0000` if no effective groups); emitted **only** when `ANIM_GRP_BYTES > 0` |
| `anim_dur_pool` / `anim_dur_<K>` | `ANIM_DUR_BYTES B` | `[offset + f]` / `[f]` | Deduplicated per-frame effective durations (`1..255` PAL ticks, 1 byte/frame), emitted **only** for non-uniform objects |
| `anim_grp_<K>` | `F + 2*G B` each | `[ctrl 0..F-1][rep_0, first_0, ...]` | Deduplicated effective group control+pair table (`ctrl[f] = 0` interior/outside, `F + 2*g` at group start, `$80 | g` at group end), emitted **only** when `ANIM_GRP_BYTES > 0` |
| `anim_scodes_<K>` | `S B` each | `[slot 0..S-1]` | Dedicated charset base codes (`1..127`) matching each slot in `anim_f1`/`anim_f2` |
| `anim_f1_<K>` | `S * F B` | `[frame * S + slot]` | **Form 1** (selected when `size_f2 >= size_f1`): frame-major pattern indices into pool bank `b` |
| `anim_f2_<K>` | `S + 2*F B` (ungrouped) or `S + 1 + 2*(F+G) B` (grouped) | `[f0_pats]([T])[<d..][>d..]` | **Form 2** (selected when `size_f2 < size_f1`): frame-0 patterns (`S B`), optional `T = F + G` transition count byte (`ANIM_FLAG_GROUPS` set), and split pointers to `anim_d_<K>` (deltas `0..F-1` for `(k-1)->k` plus `F..F+G-1` for `last_g->first_g` loop-backs) |
| `anim_d_<K>` | `1 + 2*C B` | `[C, s0, p0, ...]` | Deduplicated cyclic delta block (`C` changed `[slot, pat]` pairs) |
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
3. `game_enter` disables DLI/DMA/animations, silences title-screen PMG, selects `START_ROOM` from `gen/rooms_defs.asm`, calls `room_draw`, `room_setup_display`, and `room_anim_init` (`X = START_ROOM`), initializes Player 0 at `(START_X, START_Y)` via `hero_init`, atomically installs `room_dlist`, `VDSLST = room_dli_handler`, and `VVBLKD = game_vbi_deferred` (`$0224`) with `NMIEN = $00`, enables playfield + single-line Players DMA (`GAME_DMACTL = $3A`, `GAME_GRACTL = $02`, `GAME_PRIOR = $01`), and enables `NMIEN = $C0` iff `room_dli_count > 0` (`$40` for uniform-style rooms).
4. `game_update` runs `hero_update` once per frame synchronized with `wait_frame`, transitioning to `STATE_GAME_OVER_FAILURE` (via `@leave_game` + `hero_pmg_disable`) when `zp_hero_fell_out != 0` or on FIRE press (`zp_fire_pressed`).

### Blocking & Ladder Maps (`engine/room.asm`, `room_block_map`, `room_ladder_map`)
- During `room_draw`, `clear_room_block_map` and `clear_room_ladder_map` zero both `120`-byte bitmaps (`40 × 24` bits, `5` bytes/row, MSB-first: cell `(col, row)` is at `map[row * 5 + (col >> 3)]`, mask `$80 >> (col & 7)`).
- Blockable instances (`obj_flags & OBJ_FLAG_NON_BLOCKABLE == 0`) with non-zero cell codes set bits in `room_block_map`; non-blockable instances tagged `"ladder"` (`obj_tags<P> & TAG_LADDER != 0`) with non-zero cell codes set bits in `room_ladder_map`. [`scripts/rooms_compile.py`](../scripts/rooms_compile.py) enforces at build time that the `"ladder"` tag is only allowed on non-blockable objects.
- Helpers: `cell_blocked`, `row_range_blocked`, `col_range_blocked`, `cell_ladder`, `row_range_ladder`, `row_range_support` (`blocked | ladder`), and `col_range_ladder`; rows `>= 24` and cols `>= 40` always return `C=0`.

### Generated Hero Sprite Data ([`scripts/compile_hero_sprites.py`](../scripts/compile_hero_sprites.py))
- Validates [`sprites/project.sprite.json`](../sprites/project.sprite.json) (mandatory IDs `1..8`, exact names, `8×18` pixel grids, `frame_duration` `1..255` with fallback `HERO_DEFAULT_FRAME_TICKS = 4`) and deterministically emits [`gen/hero_defs.asm`](../gen/hero_defs.asm) (`0 B`: `HERO_WALK_RIGHT=1`..`HERO_FALL=8`, `HERO_NUM_SETS=8`, `HERO_SPRITE_HEIGHT=18`, `HERO_SPRITE_WIDTH_CC=8`) and [`gen/hero_sprites.asm`](../gen/hero_sprites.asm) (SoA 1-based metadata `hero_set_count`, `hero_set_dur`, `hero_set_base`, flat `hero_frame_lo`/`hero_frame_hi` + `hero_set_1..8_lo/hi`, and deduplicated 18-byte frames `hero_frame_0..`; currently `8` sets, `29` frames -> `29` unique, `604 B` total).
- [`scripts/rooms_compile.py`](../scripts/rooms_compile.py) also emits warnings `START_FOOTPRINT_BLOCKED` (start footprint overlaps blockable cells) and `START_AT_BOTTOM_ROW` (`start.y == 23`).

### Hero Physics, Movement, PMG Player 0 & Trail-Free Draw ([`engine/hero.asm`](../engine/hero.asm))
- **Coordinates & Visuals:** Player `0`, normal width (`HERO_SIZE = 0`), `PCOLR0 = COLPM0 = HERO_COLOR` (`$AD`), `GPRIOR = PRIOR = $01`. Room DLIs do not touch `COLPM0`. Horizontal `HPOSP0 = PLAYFIELD_LEFT_CC (48) + zp_hero_x` (`zp_hero_x` in `0..HERO_MAX_X_CC (152)`, initialized to `4 * cell_x`, `8` colour clocks width). Vertical PMG top `zp_hero_y = (cell_y + 1) * 8 + HERO_TOP_TO_PF_BOTTOM` (`32 - 18 = 14`), so feet sit at `bottom_pf = (cell_y + 1) * 8`. Collision footprint width: `HERO_COLLISION_WIDTH_CC = 8` colour clocks (`col_left..col_right`). Start facing: `HERO_FACING_RIGHT` (`0`); standing pose: `hero_stand_set_tbl[zp_hero_facing]`, frame `HERO_STAND_FRAME` (`0`).
- **Five-State Machine (`HERO_STATE_STANDING = 0`, `HERO_STATE_FALLING = 1`, `HERO_STATE_JUMPING = 2`, `HERO_STATE_SQUATTING = 3`, `HERO_STATE_ON_LADDER = 4`):**
  - **Standing (`0`):** Checks `hero_check_support` (`row_range_support`: supported iff `bottom_pf % 8 == 0` and row `bottom_pf / 8` is blocked **or** a ladder within `[col_left..col_right]`); falls if unsupported. Pressing `FIRE` while standing on a ladder (`hero_ladder_under_feet`) consumes `zp_fire_pressed` and launches a normal jump (`hero_jump_from_ladder`). Decodes active-low Joystick `0` (`zp_joy_curr` via `hero_read_input`): `LEFT`/`RIGHT` enters `hero_update_walk`, `UP+LEFT`/`UP+RIGHT` enters `HERO_STATE_JUMPING`, `UP` only (`HERO_CMD_CLIMB_UP = 8`) enters `HERO_STATE_ON_LADDER` when a ladder overlaps the hero's body (`hero_ladder_behind`) or stays idle otherwise, `DOWN`/`DOWN+LEFT`/`DOWN+RIGHT` enters `HERO_STATE_ON_LADDER` when the support row has an unblocked ladder shaft (`hero_can_descend_ladder`) or enters `HERO_STATE_SQUATTING` otherwise, while centre/`UP+DOWN` resets `zp_hero_walk_sub = 0` and stays idle standing (`HERO_STAND_FRAME`, `zp_hero_dirty == 0` fast path).
  - **Walking (`hero_update_walk`):** Updates `zp_hero_facing`, uses fractional speed `HERO_WALK_STEP_CC = 1` cc per `HERO_WALK_SPEED_SUBSTEPS = 3` frames (`1/3` cc/frame; steps immediately when `zp_hero_walk_sub == 0`, resets phase on stop, turn, wall/edge stop, or state exit) via `hero_try_step_x` (clamped to `[0..152]`, testing all body rows `[top_row..bot_row]` via `hero_body_rows`/`hero_blocked_at` + `col_range_blocked`, flushing to cell edge when `step > 1`), advances `HERO_WALK_RIGHT`/`HERO_WALK_LEFT` via `hero_tick_walk_anim` at `HERO_WALK_ANIM_TICKS = 5` PAL frames/sprite frame, resets to `HERO_STAND_FRAME` against walls/edges, and enters vertical `FALLING` (`zp_hero_jump_dir = HERO_JUMP_DIR_NONE = $FF`) when stepping off a ledge.
  - **Jumping (`HERO_STATE_JUMPING = 2`):** Triggered from grounded `UP+LEFT`/`UP+RIGHT` or `FIRE` while on/atop a ladder; committed ballistic arc (`hero_jump_steps = [4, 4, 3, 3, 3, 2, 2, 2, 1, 1, 1, 1]`, `HERO_JUMP_HEIGHT = 27` scanlines, max step `<= 8`), clamping Y at `HERO_MIN_PMG_Y = PLAYFIELD_TOP_PMG_Y (32)`, stopping head against blocked ceilings (`row_range_blocked` over `[col_left..col_right]`), passing freely through non-blockable ladders while rising unless pure `UP` (`HERO_CMD_CLIMB_UP`) is held after the launch frame (`zp_hero_jump_idx > 0`) to latch onto a ladder behind the body (`HERO_STATE_ON_LADDER`), moving horizontally by `HERO_JUMP_SPEED_CC = 1` cc/frame (side walls/edges stop X only), animating `HERO_JUMP_RIGHT`/`HERO_JUMP_LEFT` through rise and descent, and switching to `FALLING` at the apex (`zp_hero_fall_idx = 0`).
  - **Falling (`HERO_STATE_FALLING = 1`):** Allows mid-air ladder grab with pure `UP` (`HERO_CMD_CLIMB_UP`) whenever `hero_ladder_behind` is true; applies committed jump X velocity if `zp_hero_jump_dir != $FF` (walk-off falls ignore air input), steps vertically by `hero_fall_steps = [1, 1, 2, 2, 3, 3, 4]` (max `<= 8`), lands cleanly in `STANDING` on any crossed blocked **or** ladder row boundary (`row_range_support`), or sets `zp_hero_fell_out = 1` -> `STATE_GAME_OVER_FAILURE` when `zp_hero_y >= PLAYFIELD_BOTTOM_PMG_Y (224)`.
  - **Squatting (`HERO_STATE_SQUATTING = 3`):** Grounded-only hold on `DOWN` (`HERO_CMD_SQUAT`, facing preserved) or `DOWN+LEFT`/`DOWN+RIGHT` (when not above an unblocked ladder shaft); keeps X stationary, plays `HERO_SQUAT_RIGHT`/`HERO_SQUAT_LEFT` as a one-shot crouch (`0 -> count-1`, holding final crouched frame with `zp_hero_dirty == 0`), supports mid-squat direction flips (`DOWN+LEFT` <-> `DOWN` <-> `DOWN+RIGHT`) without flicker, falls if support disappears, and returns to `STANDING` on release.
  - **On Ladder (`HERO_STATE_ON_LADDER = 4`):** Gravity disabled; uses `HERO_UP_DOWN` (4 frames, `hero_set_dur`) while moving and holds current frame with `zp_hero_dirty == 0` when stationary. `UP` climbs at `HERO_CLIMB_SPEED = 1` scanline/frame (stopping at blocked ceilings/`HERO_MIN_PMG_Y`, and transitioning cleanly to `STANDING` upon reaching the top rung where `ladder_under_feet` is true and `ladder_behind` is false — stacked vertical ladders climb seamlessly). `DOWN` descends at `HERO_CLIMB_SPEED = 1` scanline/frame (landing in `STANDING` on any crossed blockable floor below, or entering `FALLING` if descending off a hanging ladder). `LEFT`/`RIGHT` (including diagonal climb/descend) moves sideways within ladder columns via `hero_try_ladder_step_x` (enforcing screen edges, blockable walls, and `col_range_ladder` on the leading column). `FIRE` consumes `zp_fire_pressed` and launches a normal jump (`hero_jump_from_ladder`).
- **Partial PMG Clearing (`hero_pmg_draw`):** Skips all writes (`18` cyc incl. `JSR/RTS`) when `zp_hero_dirty == 0`. On move/frame change, clears **only vacated scanlines** (`[old_y .. old_y + delta - 1]` when moving down by `delta < 18`, `[new_y + 18 .. new_y + 18 + delta - 1]` when moving up by `delta < 18`, or `18` bytes when jumping `>= 18` lines), copies 18 frame bytes into `PMG_P0 + zp_hero_y`, and updates `HPOSP0`. Runs right after `wait_frame` (vertical blank / overscan before scanline `32`) without flicker.

### VBI Object Animation Engine (`engine/anim.asm`, PAL 50 Hz Only)
- **Deferred VBI (`game_vbi_deferred` via `VVBLKD`):** Tests `zp_anim_active` first; on static rooms (`zp_anim_active == 0`) `anim_tick` exits in `11` cycles (`bne @active / rts`; `19` cycles total for `game_vbi_deferred` up to `XITVBV`), resets `zp_dli_idx = 0`, and exits cleanly.
- **Minimal Real Copies Only & Budget (`ANIM_VBI_GLYPH_BUDGET = 12` slots/VBI = `<= 96` bytes):**
  - Pass 1 decrements all `anim_st_cnt[0..anim_room_count-1]` counters unconditionally (zero timer drift even when copies defer), advances `anim_st_frame` (applying `anim_grp_*` pass counters `anim_st_rep` when `ANIM_FLAG_GROUPS` is set: decrementing `anim_st_rep` on group end to jump to `first_g`, or initializing `anim_st_rep = repeat_g` when entering `first_g` from outside), and reloads `anim_st_cnt` with the entered frame's effective duration (`anim_speed[id]` when `ANIM_FLAG_VAR_DUR == 0`, else `anim_dur_pool[anim_speed[id] + frame]` in compact mode or `(anim_dur_lo/hi[id])[frame]` when `ANIM_DUR_WIDE == 1`).
  - Pass 2 services pending objects round-robin from `zp_anim_cursor`:
    - **Form 1:** Compares each slot's target pattern index against `anim_slot_cur[sbase + s]`, skipping unchanged slots with `0` charset writes and `0` budget cost.
    - **Form 2:** Walks `[count, slot, pat]` delta pairs transition-by-transition (`(anim_st_vis, anim_st_vrep)` -> `(anim_st_frame, anim_st_rep)` using `anim_grp_*` and loop-back deltas `F + g` when `ANIM_FLAG_GROUPS` is set), preserving any in-flight `anim_st_pos` if deferred mid-delta so no frame change is lost.
  - When `ANIM_POOL_COUNT <= 1`, `_anim_copy_pattern` uses unrolled `anim_pool0_b0..b7,X` loads (`~110` cycles/glyph); when `ANIM_POOL_COUNT > 1` (`> 256` unique patterns), it indexes `(anim_pb_lo/hi)` per bank.
- **Measured CPU Cost (`py65`, Room 1 production build `count_copies=False`):**
  - `game_vbi_deferred` (Room 1 animated: `anim_tick` + `zp_dli_idx = 0` + `XITVBV`): `134` cyc on countdown-only VBI ticks, `1,325`–`3,378` cyc on glyph-copy ticks. Static room (`zp_anim_active == 0`): `anim_tick` = `11` cyc (`bne @active / rts`).
  - `hero_update` (runs post-`wait_frame` each VBLANK): `221` cyc standing idle (0 PMG writes), `234` cyc walk wait frame (`1,855` cyc walk move frame), `234` cyc crouch hold (`661` cyc squat start/frame swap), `1,366`–`2,084` cyc jump rise/descent/landing, `338` cyc bottom-edge exit (`hero_pmg_erase_drawn`). Worst-case combined VBI + hero frame (`3,378 + 2,084 = 5,462` cyc, fitting comfortably within PAL frame budget).
  - Animation micro-benchmarks (`count_copies=False`): ungrouped idle = `40` cyc; 1-slot advance = `531` cyc (Form 1 ungrouped) / `618` cyc (Form 2 ungrouped); mixed ungrouped 1-slot = `552` / `676` cyc; grouped Form 1 1-slot = `565`–`662` cyc; grouped Form 2 = `773`–`1,033` cyc.
- **Room Re-entry Reset:** `room_anim_init` copies frame `0` bytes into each varying dedicated charset RAM slot, initializes `anim_slot_cur` for Form 1 objects, initializes `anim_st_rep`/`anim_st_vrep` to `repeat_0` when frame `0` begins an effective group (`0` otherwise), and resets `anim_st_cnt` to frame `0`'s effective duration and `anim_st_vis = anim_st_frame = anim_st_pos = 0`.

### Runtime Memory Map & Zero-Page Usage

| Region / Symbol | Address | Size | Purpose |
| --- | --- | --- | --- |
| Code Segment (Low) | `$2000..$269E` | `1695 B` | Entrypoint, state machine, RLE, PMG helpers, input, DLI/VBI, title scene |
| `SCREEN_VRAM` | `$3000..$33BF` | `960 B` | Shared `40×24` ANTIC Mode 4 screen buffer (does not cross 4 KB boundary) |
| `room_dlist` | `$3480..$349F` | `32 B` | Runtime ANTIC Mode 4 Display List (`3×DL_BLANK8`, `24×DL_MODE_4`, `LMS`, `JVB`; does not cross 1 KB boundary) |
| `cur_row_style` | `$34A0..$34B7` | `24 B` | Active room per-row style cache (`0..23`) |
| `room_dli_style` | `$34C0..$34D7` | `24 B` | Ordered target style IDs for DLI transitions |
| `room_dli_count` | `$34D8` | `1 B` | Scheduled DLI transition count (`0..23`) |
| `cur_room_id` | `$34D9` | `1 B` | Currently displayed 1-based room ID |
| `anim_room_count`, `anim_st_*`, `anim_slot_cur` | `$34E0..` | `1 + (8 + (1 if ANIM_F2_GRP_COUNT > 0 else 0))*ANIM_STATE_CAP + ANIM_SLOT_CAP B` | Active-room animated object count, IDs, counters, target/visible frames, group pass counters (`anim_st_rep`, conditional `anim_st_vrep`), pending flags, cursors, Form 1 bases, and `anim_slot_cur` cache (guarded `< $3700`) |
| `room_block_map` | `$3700..$3777` | `120 B` | `40×24` cell blocking bitmap (5 B/row, built by `room_draw`) |
| `room_ladder_map` | `$3778..$37EF` | `120 B` | `40×24` cell ladder bitmap (5 B/row, built by `room_draw` for `"ladder"`-tagged objects) |
| `PMG_BASE` (`PMG_P0`) | `$3800..$3FFF` (`$3C00..$3CFF`) | `2048 B` (`256 B`) | 2 KB-aligned single-line PMG buffer (`PMG_P0` holds Hero Player `0` sprite) |
| Title & Music | `$4000..$4BFF`, `$5000..$5D3F` | `3072 B`, `3392 B` | Title charsets and isolated POKEY audio player/song segment |
| Room Data & Gameplay Engine | `$6000..$7905`, `$7920..$7C54` | `7227 B` | `gen/charsets.asm` (`1 KB` aligned at `$6000`), `gen/styles.asm`, `objects.asm`, `rooms.asm`, `teleports.asm`, `animations.asm`, `intro_text.asm`, `hero_sprites.asm`, plus `engine/room.asm`, `engine/anim.asm`, `engine/hero.asm`, `scenes/intro.asm`, `scenes/game.asm`, `scenes/gameover.asm` |
| `zp_hero_*` | `$98..$9F`, `$AA..$AF`, `$CF`, `$DA..$DF` | `21 B` | Hero coordinates, draw tracking, 4-state machine, facing, animation timer, fall/jump step indices, jump direction, decoded command, walk sub-step countdown, collision scratch, and frame pointer in [`zeropage.asm`](../zeropage.asm) |
| `zp_room_*` | `$B0..$CE` | `31 B` | Plane pointers, stamp cursor, repeat counters, and blocking-map scratch bytes in [`zeropage.asm`](../zeropage.asm) (`zp_dli_idx = $82` reused for DLI indexing) |
| `zp_anim_*` | `$E0..$FD` | `30 B` | VBI-safe animation state flags, budget, cursor, source/scode/dest/bank pointers, and Form 1/2/group scratch bytes in [`zeropage.asm`](../zeropage.asm) |

### Known Limitations
- PAL-only timing (`50` Hz VBLANK ticks; NTSC timing is uncalibrated).
- Room transitions, shooting/projectiles, enemies, pickups, and teleports are not yet implemented — currently grounded walking, committed ballistic jumping, squatting, ladder climbing (`HERO_UP_DOWN`), gravity falling, wall/ceiling/screen-edge collision, and falling out the bottom into `STATE_GAME_OVER_FAILURE` are active.
- Each DLI transition writes `CHBASE`, `COLBK`, and `COLPF0..COLPF3` after `STA WSYNC` (preloading `CHBASE` and `COLBK` before `WSYNC`); `COLPF2` and `COLPF3` complete slightly into the start of scanline 0 of the new row (~cycle 32–40), which is glitch-free on scanlines with background border (`COLBK`) or `COLPF0`/`COLPF1` content, and could show a brief mid-scanline tint if `COLPF2`/`COLPF3` pixels appear at column 0 of a transition row.
