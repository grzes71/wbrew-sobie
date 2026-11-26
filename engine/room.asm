; ==============================================================================
; ENGINE/ROOM.ASM — Reusable ANTIC Mode 4 Room Renderer & Display Setup
; Target: MOS 6502 (official opcodes only), 40x24 rooms from gen/*.asm
; ==============================================================================

; --- Assembly-time Hardware Boundary Assertions ---
    .if ((room_dlist) & $FC00) <> ((room_dlist + 31) & $FC00)
        .error 'room_dlist crosses 1KB ANTIC Display List boundary'
    .endif

    .if ((SCREEN_VRAM) & $F000) <> ((SCREEN_VRAM + ROOM_SCREEN_SIZE - 1) & $F000)
        .error 'SCREEN_VRAM crosses 4KB ANTIC scan boundary'
    .endif

    .ifndef room_block_map
room_block_map          = $3700     ; Fallback for standalone test harnesses
    .endif

ROOM_BLOCK_ROW_BYTES    = 5         ; 40 cells = 5 bytes/row (MSB = leftmost cell in group of 8)
ROOM_BLOCK_MAP_SIZE     = ROOM_HEIGHT * ROOM_BLOCK_ROW_BYTES ; 120 bytes

; --- Precomputed Screen Row Start Addresses (24 entries, SoA) ---
screen_row_lo
    :ROOM_HEIGHT dta <(SCREEN_VRAM + # * ROOM_WIDTH)
screen_row_hi
    :ROOM_HEIGHT dta >(SCREEN_VRAM + # * ROOM_WIDTH)

; --- Blocking Map Lookup Tables (SoA) ---
block_row_off
    :ROOM_HEIGHT dta (# * ROOM_BLOCK_ROW_BYTES)
col_byte_off
    :ROOM_WIDTH dta (# >> 3)
col_bit_mask
    :ROOM_WIDTH dta ($80 >> (# & 7))

; ------------------------------------------------------------------------------
; clear_screen_vram — Clears 960 bytes of SCREEN_VRAM ($3000..$33BF) to $00
; ------------------------------------------------------------------------------
.proc clear_screen_vram
    lda #0
    tax
@loop
    sta SCREEN_VRAM + $0000,x
    sta SCREEN_VRAM + $0100,x
    sta SCREEN_VRAM + $0200,x
    sta SCREEN_VRAM + $02C0,x
    inx
    bne @loop
    rts
.endp

; ------------------------------------------------------------------------------
; clear_room_block_map — Clears 120 bytes of room_block_map to $00
; ------------------------------------------------------------------------------
.proc clear_room_block_map
    lda #0
    ldx #(ROOM_BLOCK_MAP_SIZE - 1)
@loop
    sta room_block_map,x
    dex
    bpl @loop
    rts
.endp

; ------------------------------------------------------------------------------
; cell_blocked — Tests whether cell (col=X, row=Y) is blocked
; Inputs:
;   X = column (0..39), Y = row (0..23+)
; Outputs:
;   C = 1, A != 0 if blocked; C = 0, A = 0 if not blocked or outside room (Y>=24, X>=40)
; ------------------------------------------------------------------------------
.proc cell_blocked
    cpy #ROOM_HEIGHT            ; 2
    bcs @not_blocked            ; 2/3  Row >= 24 counts as NOT blocked
    cpx #ROOM_WIDTH             ; 2
    bcs @not_blocked            ; 2/3  Col >= 40 counts as NOT blocked
    lda block_row_off,y         ; 4    row * 5
    clc                         ; 2
    adc col_byte_off,x          ; 4    + (col >> 3)
    tay                         ; 2
    lda room_block_map,y        ; 4
    and col_bit_mask,x          ; 4    Test MSB-first bit
    beq @not_blocked            ; 2/3
    sec                         ; 2
    rts                         ; 6
@not_blocked
    lda #0                      ; 2
    clc                         ; 2
    rts                         ; 6
.endp

; ------------------------------------------------------------------------------
; row_range_blocked — Tests if any cell in row Y within columns A..X is blocked
; Inputs:
;   Y = row (0..23+), A = col_a, X = col_b (clamped to ROOM_WIDTH-1)
; Outputs:
;   C = 1, A != 0 if any cell in [col_a..col_b] is blocked; C = 0, A = 0 otherwise
; Clobbers:
;   A, X, Y, zp_room_blk_row, zp_room_col_save, zp_room_obj_nb
; ------------------------------------------------------------------------------
.proc row_range_blocked
    cpy #ROOM_HEIGHT            ; 2
    bcs @not_blocked            ; 2/3  Rows >= 24 are unblocked
    cmp #ROOM_WIDTH             ; 2
    bcs @not_blocked            ; 2/3  col_a >= 40
    cpx #ROOM_WIDTH             ; 2
    bcc @col_b_ok               ; 2/3
    ldx #(ROOM_WIDTH - 1)       ; 2    Clamp col_b to 39
@col_b_ok
    sta zp_room_col_save        ; 3    Save col_a
    txa                         ; 2
    cmp zp_room_col_save        ; 3    col_b < col_a?
    bcc @not_blocked            ; 2/3
    stx zp_room_obj_nb          ; 3    Save clamped col_b
    lda block_row_off,y         ; 4    row * 5
    sta zp_room_blk_row         ; 3
    ldx zp_room_col_save        ; 3    X = col_a
@range_loop
    lda zp_room_blk_row         ; 3
    clc                         ; 2
    adc col_byte_off,x          ; 4
    tay                         ; 2
    lda room_block_map,y        ; 4
    and col_bit_mask,x          ; 4
    bne @blocked                ; 2/3
    cpx zp_room_obj_nb          ; 3    Reached col_b?
    bcs @not_blocked            ; 2/3
    inx                         ; 2
    bne @range_loop             ; 3    Unconditional (X <= 39)
@not_blocked
    lda #0                      ; 2
    clc                         ; 2
    rts                         ; 6
@blocked
    sec                         ; 2
    rts                         ; 6
.endp

; ------------------------------------------------------------------------------
; col_range_blocked — Tests if any cell in column X within rows A..Y is blocked
; Inputs:
;   X = col (0..39+), A = row_a, Y = row_b (clamped to ROOM_HEIGHT-1)
; Outputs:
;   C = 1, A != 0 if any cell in [row_a..row_b] is blocked; C = 0, A = 0 otherwise
; Clobbers:
;   A, X, Y, zp_room_blk_row, zp_room_col_save, zp_room_obj_nb
; ------------------------------------------------------------------------------
.proc col_range_blocked
    cpx #ROOM_WIDTH             ; 2
    bcs @not_blocked            ; 2/3  Col >= 40 is unblocked
    cmp #ROOM_HEIGHT            ; 2
    bcs @not_blocked            ; 2/3  row_a >= 24 is unblocked
    cpy #ROOM_HEIGHT            ; 2
    bcc @row_b_ok               ; 2/3
    ldy #(ROOM_HEIGHT - 1)      ; 2    Clamp row_b to 23
@row_b_ok
    sta zp_room_col_save        ; 3    Current row = row_a
    tya                         ; 2
    cmp zp_room_col_save        ; 3    row_b < row_a?
    bcc @not_blocked            ; 2/3
    sty zp_room_obj_nb          ; 3    Save clamped row_b
    stx zp_room_blk_row         ; 3    Save column
@loop
    ldx zp_room_blk_row         ; 3    X = col
    ldy zp_room_col_save        ; 3    Y = current row
    jsr cell_blocked            ; 6+   Returns C=1, A!=0 iff blocked
    bcs @blocked                ; 2/3
    lda zp_room_col_save        ; 3
    cmp zp_room_obj_nb          ; 3    Reached row_b?
    bcs @not_blocked            ; 2/3
    inc zp_room_col_save        ; 5
    bne @loop                   ; 3    Unconditional (row <= 23)
@not_blocked
    lda #0                      ; 2
    clc                         ; 2
    rts                         ; 6
@blocked
    sec                         ; 2
    rts                         ; 6
.endp

; ------------------------------------------------------------------------------
; room_draw — Renders a compiled room into SCREEN_VRAM (40x24, 960 bytes) and
;             builds room_block_map (120 bytes)
; Input:
;   X = room ID (1..ROOM_MAX_ID)
; Uses:
;   Zero page $B0..$CE (see zeropage.asm)
; Notes:
;   - Clears SCREEN_VRAM and room_block_map to 0.
;   - Draws instances in stored order (non-blockable first, then blockable).
;   - Expands repeat-x / repeat-y / repeat-xy in steps of (obj_w, obj_h).
;   - Cell code 0 is transparent and never overwrites VRAM or sets blocking bits.
; ------------------------------------------------------------------------------
.proc room_draw
    txa
    pha                         ; Preserve room ID across clear routines
    jsr clear_screen_vram
    jsr clear_room_block_map
    pla
    tax                         ; X = room_id

    lda room_inst_count,x       ; N = instance count for room X
    bne @has_instances
    rts                         ; Empty room (N == 0)

@has_instances
    sta zp_room_inst_cnt

    ; Compute 5 contiguous SoA plane pointers:
    ;   obj = base, x = obj + N, yf = x + N, rep_w = yf + N, rep_h = rep_w + R
    lda room_inst_lo,x
    sta zp_room_inst_obj
    lda room_inst_hi,x
    sta zp_room_inst_obj+1

    clc
    lda zp_room_inst_obj
    adc zp_room_inst_cnt
    sta zp_room_inst_x
    lda zp_room_inst_obj+1
    adc #0
    sta zp_room_inst_x+1

    clc
    lda zp_room_inst_x
    adc zp_room_inst_cnt
    sta zp_room_inst_yf
    lda zp_room_inst_x+1
    adc #0
    sta zp_room_inst_yf+1

    clc
    lda zp_room_inst_yf
    adc zp_room_inst_cnt
    sta zp_room_rep_w
    lda zp_room_inst_yf+1
    adc #0
    sta zp_room_rep_w+1

    clc
    lda zp_room_rep_w
    adc room_rep_count,x
    sta zp_room_rep_h
    lda zp_room_rep_w+1
    adc #0
    sta zp_room_rep_h+1

    lda #0
    sta zp_room_inst_idx
    sta zp_room_rep_idx

@inst_loop
    ldy zp_room_inst_idx
    lda (zp_room_inst_obj),y
    sta zp_room_obj_id
    tax                         ; X = obj_id (1..OBJ_MAX_ID)
    lda obj_w,x
    sta zp_room_obj_w
    lda obj_h,x
    sta zp_room_obj_h
    lda obj_flags,x
    and #OBJ_FLAG_NON_BLOCKABLE
    sta zp_room_obj_nb

    lda (zp_room_inst_x),y
    sta zp_room_base_x

    lda (zp_room_inst_yf),y
    bpl @single_rep             ; Bit 7 clear -> 1x1 repeat
    and #INST_Y_COORD_MASK
    sta zp_room_cur_y
    ldy zp_room_rep_idx
    lda (zp_room_rep_w),y
    sta zp_room_rep_w_tot
    lda (zp_room_rep_h),y
    sta zp_room_rep_h_cnt
    inc zp_room_rep_idx
    jmp @rep_y_loop

@single_rep
    sta zp_room_cur_y
    lda #1
    sta zp_room_rep_w_tot
    sta zp_room_rep_h_cnt

@rep_y_loop
    lda zp_room_base_x
    sta zp_room_cur_x
    lda zp_room_rep_w_tot
    sta zp_room_rep_w_cnt

@rep_x_loop
    ldx zp_room_obj_id
    lda obj_data_lo,x
    sta zp_room_obj_ptr
    lda obj_data_hi,x
    sta zp_room_obj_ptr+1

    lda zp_room_cur_y
    sta zp_room_draw_y
    lda zp_room_obj_h
    sta zp_room_row_cnt

@stamp_row_loop
    ldx zp_room_draw_y
    clc
    lda screen_row_lo,x
    adc zp_room_cur_x
    sta zp_room_scr_ptr
    lda screen_row_hi,x
    adc #0
    sta zp_room_scr_ptr+1

    ldy zp_room_obj_w
    dey
    lda zp_room_obj_nb
    bne @stamp_col_loop         ; Non-blockable objects never mark room_block_map

    ldx zp_room_draw_y
    lda block_row_off,x
    sta zp_room_blk_row
@stamp_blk_col_loop
    lda (zp_room_obj_ptr),y
    beq @skip_blk_cell          ; Code 0 is transparent and never blocks
    sta (zp_room_scr_ptr),y
    sty zp_room_col_save
    tya
    clc
    adc zp_room_cur_x
    tax                         ; X = col (0..39)
    lda zp_room_blk_row
    clc
    adc col_byte_off,x
    tay
    lda room_block_map,y
    ora col_bit_mask,x
    sta room_block_map,y
    ldy zp_room_col_save
@skip_blk_cell
    dey
    bpl @stamp_blk_col_loop
    bmi @stamp_row_next         ; Unconditional (Y == $FF)

@stamp_col_loop
    lda (zp_room_obj_ptr),y
    beq @skip_cell              ; Code 0 is transparent
    sta (zp_room_scr_ptr),y
@skip_cell
    dey
    bpl @stamp_col_loop

@stamp_row_next
    dec zp_room_row_cnt
    beq @stamp_done

    clc
    lda zp_room_obj_ptr
    adc zp_room_obj_w
    sta zp_room_obj_ptr
    lda zp_room_obj_ptr+1
    adc #0
    sta zp_room_obj_ptr+1

    inc zp_room_draw_y
    jmp @stamp_row_loop

@stamp_done
    clc
    lda zp_room_cur_x
    adc zp_room_obj_w
    sta zp_room_cur_x
    dec zp_room_rep_w_cnt
    beq @rep_x_done
    jmp @rep_x_loop
@rep_x_done

    clc
    lda zp_room_cur_y
    adc zp_room_obj_h
    sta zp_room_cur_y
    dec zp_room_rep_h_cnt
    beq @rep_y_done
    jmp @rep_y_loop
@rep_y_done

    inc zp_room_inst_idx
    lda zp_room_inst_idx
    cmp zp_room_inst_cnt
    beq @done
    jmp @inst_loop

@done
    rts
.endp

; ------------------------------------------------------------------------------
; room_setup_display — Resolves row styles, builds room_dlist & DLI table, and
;                      applies row 0 style to OS shadow and hardware registers.
; Input:
;   X = room ID (1..ROOM_MAX_ID)
; Outputs:
;   cur_room_id          = X
;   cur_row_style[0..23] = style ID for each Mode 4 row
;   room_dlist[0..31]    = complete ANTIC Mode 4 Display List (24 rows + LMS + JVB)
;   room_dli_style[0..K] = style IDs for rows needing DLI switches
;   room_dli_count       = K (0 if uniform single style)
;   zp_dli_idx           = 0
; ------------------------------------------------------------------------------
.proc room_setup_display
    stx cur_room_id

    ; 1. Resolve 24 per-row styles into cur_row_style[0..23]
    lda room_flags,x
    and #ROOM_FLAG_UNIFORM_STYLE
    beq @mixed_styles

    lda room_rowstyle_lo,x      ; Uniform single style ID
    ldy #ROOM_HEIGHT-1
@fill_uniform
    sta cur_row_style,y
    dey
    bpl @fill_uniform
    jmp @build_dlist

@mixed_styles
    lda room_rowstyle_lo,x
    sta zp_room_obj_ptr
    lda room_rowstyle_hi,x
    sta zp_room_obj_ptr+1
    ldy #ROOM_HEIGHT-1
@copy_mixed
    lda (zp_room_obj_ptr),y
    sta cur_row_style,y
    dey
    bpl @copy_mixed

@build_dlist
    ; 2. Populate room_dlist ($3480..$349F) & room_dli_style
    lda #DL_BLANK8
    sta room_dlist+0
    sta room_dlist+1
    sta room_dlist+2

    lda #<SCREEN_VRAM
    sta room_dlist+4
    lda #>SCREEN_VRAM
    sta room_dlist+5

    ldy #0                      ; Y = number of scheduled DLIs

    ; Row 0 instruction (offset 3): DL_MODE_4 | DL_LMS [| DL_DLI]
    lda cur_row_style+0
    cmp cur_row_style+1
    beq @row0_no_dli
    lda cur_row_style+1
    sta room_dli_style,y
    iny
    lda #(DL_MODE_4 | DL_LMS | DL_DLI)
    bne @row0_store             ; Unconditional (non-zero)
@row0_no_dli
    lda #(DL_MODE_4 | DL_LMS)
@row0_store
    sta room_dlist+3

    ; Rows 1..22 (offsets 6..27 = room_dlist + 5 + X)
    ldx #1
@dl_row_loop
    lda cur_row_style,x
    cmp cur_row_style+1,x
    beq @row_no_dli
    lda cur_row_style+1,x
    sta room_dli_style,y
    iny
    lda #(DL_MODE_4 | DL_DLI)
    bne @row_store              ; Unconditional (non-zero)
@row_no_dli
    lda #DL_MODE_4
@row_store
    sta room_dlist+5,x
    inx
    cpx #ROOM_HEIGHT-1          ; 23
    bcc @dl_row_loop

    ; Row 23 (offset 28): final row never schedules a DLI
    lda #DL_MODE_4
    sta room_dlist+28

    ; JVB instruction (offsets 29..31)
    lda #DL_JVB
    sta room_dlist+29
    lda #<room_dlist
    sta room_dlist+30
    lda #>room_dlist
    sta room_dlist+31

    sty room_dli_count

    ; 3. Apply row 0 style to both OS shadows and hardware registers
    ldy cur_row_style+0
    lda style_chbase,y
    sta CHBAS
    sta CHBASE
    lda style_colbk,y
    sta COLOR4
    sta COLBK
    lda style_colpf0,y
    sta COLOR0
    sta COLPF0
    lda style_colpf1,y
    sta COLOR1
    sta COLPF1
    lda style_colpf2,y
    sta COLOR2
    sta COLPF2
    lda style_colpf3,y
    sta COLOR3
    sta COLPF3

    lda #0
    sta zp_dli_idx
    rts
.endp
