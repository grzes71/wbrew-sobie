; ==============================================================================
; ENGINE/HERO.ASM — Hero Player 0 Sprite Physics, Animation & PMG Renderer
; Target: MOS 6502 (official opcodes only), Single-Line PMG ($3800, $3C00=P0)
; ==============================================================================

; --- Screen / PMG Coordinate Constants ---
PLAYFIELD_LEFT_CC       = 48        ; Left edge of 40-cell ANTIC 4 playfield in color clocks
PLAYFIELD_WIDTH_CC      = ROOM_WIDTH * 4 ; 160 playfield color clocks (cols 0..39)
PLAYFIELD_TOP_PMG_Y     = 32        ; PMG scanline matching playfield row 0 top (scanline 0)
PLAYFIELD_HEIGHT        = ROOM_HEIGHT * 8 ; 192 scanlines (rows 0..23)
PLAYFIELD_BOTTOM_PMG_Y  = PLAYFIELD_TOP_PMG_Y + PLAYFIELD_HEIGHT ; 224 (first line below playfield)
HERO_TOP_TO_PF_BOTTOM   = PLAYFIELD_TOP_PMG_Y - HERO_SPRITE_HEIGHT ; 14 (top_pmg = bottom_pf + 14)
HERO_MIN_PMG_Y          = PLAYFIELD_TOP_PMG_Y ; Top clamp preventing PMG_P0 underflow

; --- Hero Rendering, Movement & Collision Constants ---
HERO_COLOR              = $AD       ; PAL color for Player 0 (PCOLR0 / COLPM0)
HERO_SIZE               = 0         ; Normal width (SIZEP0 = 0, 1 cc per pixel = 8 cc total)
HERO_COLLISION_WIDTH_CC = HERO_SPRITE_WIDTH_CC ; Horizontal collision footprint width (8 cc, tunable)
HERO_MAX_X_CC           = PLAYFIELD_WIDTH_CC - HERO_COLLISION_WIDTH_CC ; 152 (rightmost valid x)
HERO_WALK_STEP_CC       = 1         ; Horizontal step per move tick (cc, 1..4)
HERO_WALK_SPEED_SUBSTEPS = 3        ; Grounded frames per walk step (3 = 1/3 cc/frame, closest uniform to +25% of 0.25)
HERO_WALK_ANIM_TICKS    = 5         ; PAL frames per walk anim frame (~+50% vs prior 8-frame pace)
HERO_WALK_SPEED_CC      = HERO_WALK_STEP_CC ; Tunable step size alias
HERO_JUMP_SPEED_CC      = 1         ; Tunable ballistic jump horizontal speed (cc/frame, 1..4)
HERO_FACING_RIGHT       = 0
HERO_FACING_LEFT        = 1
HERO_START_FACING       = HERO_FACING_RIGHT
HERO_JUMP_DIR_NONE      = $FF       ; Sentinel for vertical-only falling (no jump X velocity)

; --- Hero State Machine Constants ---
HERO_STATE_STANDING     = 0
HERO_STATE_FALLING      = 1
HERO_STATE_JUMPING      = 2
HERO_STATE_SQUATTING    = 3
HERO_STAND_SET          = HERO_WALK_RIGHT
HERO_STAND_FRAME        = 0
HERO_FALL_SET           = HERO_FALL

; --- Joystick 0 Input Masks & Decoded Commands (zp_joy_curr, 0 = pressed) ---
JOY_MASK_UP             = $01
JOY_MASK_DOWN           = $02
JOY_MASK_LEFT           = $04
JOY_MASK_RIGHT          = $08
JOY_MASK_ALL            = $0F

HERO_CMD_NONE           = 0
HERO_CMD_WALK_RIGHT     = 1
HERO_CMD_WALK_LEFT      = 2
HERO_CMD_JUMP_RIGHT     = 3
HERO_CMD_JUMP_LEFT      = 4
HERO_CMD_SQUAT_RIGHT    = 5
HERO_CMD_SQUAT_LEFT     = 6
HERO_CMD_SQUAT          = 7         ; DOWN only: squat keeping current zp_hero_facing

; --- Room Gameplay PMG Hardware Modes ---
GAME_DMACTL             = $3A       ; Normal PF ($02) + Players DMA ($08) + 1-line PMG ($10) + DL DMA ($20)
GAME_GRACTL             = $02       ; Players display enabled (no missiles)
GAME_PRIOR              = $01       ; P0..P3 priority in front of playfield

; --- Falling Vertical Step Table (PAL 1/50 s scanlines/frame, max <= 8 to prevent tunnelling) ---
hero_fall_steps
    dta 1, 1, 2, 2, 3, 3, 4
HERO_FALL_STEP_COUNT    = * - hero_fall_steps
HERO_FALL_MAX_STEP      = 4

; --- Jumping Vertical Step Table (decelerating rise, 27 scanlines = 3.375 cells, max <= 8) ---
hero_jump_steps
    dta 4, 4, 3, 3, 3, 2, 2, 2, 1, 1, 1, 1
HERO_JUMP_STEP_COUNT    = * - hero_jump_steps
HERO_JUMP_MAX_STEP      = 4
HERO_JUMP_HEIGHT        = 27

; --- Joystick 0 Command Lookup Table (16 entries indexed by zp_joy_curr & $0F, active-low %RLDU) ---
hero_joy_cmd_tbl
    dta HERO_CMD_NONE           ; $0 (%0000): all held -> neutral
    dta HERO_CMD_NONE           ; $1 (%0001): D+L+R -> neutral
    dta HERO_CMD_NONE           ; $2 (%0010): U+L+R -> neutral
    dta HERO_CMD_NONE           ; $3 (%0011): L+R -> neutral
    dta HERO_CMD_NONE           ; $4 (%0100): U+D+R -> neutral
    dta HERO_CMD_SQUAT_RIGHT    ; $5 (%0101): DOWN+RIGHT
    dta HERO_CMD_JUMP_RIGHT     ; $6 (%0110): UP+RIGHT
    dta HERO_CMD_WALK_RIGHT     ; $7 (%0111): RIGHT
    dta HERO_CMD_NONE           ; $8 (%1000): U+D+L -> neutral
    dta HERO_CMD_SQUAT_LEFT     ; $9 (%1001): DOWN+LEFT
    dta HERO_CMD_JUMP_LEFT      ; $A (%1010): UP+LEFT
    dta HERO_CMD_WALK_LEFT      ; $B (%1011): LEFT
    dta HERO_CMD_NONE           ; $C (%1100): UP+DOWN -> neutral
    dta HERO_CMD_SQUAT          ; $D (%1101): DOWN only -> squat facing preserved
    dta HERO_CMD_NONE           ; $E (%1110): UP only -> stand still
    dta HERO_CMD_NONE           ; $F (%1111): centre -> stand still

; --- Facing-Indexed Sprite Set Lookup Tables (SoA: 0=RIGHT, 1=LEFT) ---
hero_stand_set_tbl
    dta HERO_WALK_RIGHT, HERO_WALK_LEFT
hero_jump_set_tbl
    dta HERO_JUMP_RIGHT, HERO_JUMP_LEFT
hero_squat_set_tbl
    dta HERO_SQUAT_RIGHT, HERO_SQUAT_LEFT

; --- Assembly-Time Safety Invariants ---
    .if HERO_SPRITE_HEIGHT > PLAYFIELD_TOP_PMG_Y
        .error 'HERO_SPRITE_HEIGHT exceeds PLAYFIELD_TOP_PMG_Y (top cell Y=0 underflows PMG_P0)'
    .endif
    .if HERO_MIN_PMG_Y < HERO_SPRITE_HEIGHT
        .error 'HERO_MIN_PMG_Y is below HERO_SPRITE_HEIGHT'
    .endif
    .if (HERO_COLLISION_WIDTH_CC < 1) || (HERO_COLLISION_WIDTH_CC > PLAYFIELD_WIDTH_CC)
        .error 'HERO_COLLISION_WIDTH_CC must be in 1..PLAYFIELD_WIDTH_CC'
    .endif
    .if (HERO_WALK_STEP_CC < 1) || (HERO_WALK_STEP_CC > 4)
        .error 'HERO_WALK_STEP_CC must be in 1..4 cc (single cell step)'
    .endif
    .if (HERO_WALK_SPEED_SUBSTEPS < 1) || (HERO_WALK_SPEED_SUBSTEPS > 16)
        .error 'HERO_WALK_SPEED_SUBSTEPS must be in 1..16 frames'
    .endif
    .if (HERO_WALK_ANIM_TICKS < 1) || (HERO_WALK_ANIM_TICKS > 255)
        .error 'HERO_WALK_ANIM_TICKS must be in 1..255 PAL ticks'
    .endif
    .if (HERO_JUMP_SPEED_CC < 1) || (HERO_JUMP_SPEED_CC > 4)
        .error 'HERO_JUMP_SPEED_CC must be in 1..4 cc (single cell step)'
    .endif
    .if (HERO_FALL_MAX_STEP < 1) || (HERO_FALL_MAX_STEP > 8)
        .error 'HERO_FALL_MAX_STEP must be in 1..8 scanlines to guarantee single-boundary crossing'
    .endif
    .if (HERO_JUMP_MAX_STEP < 1) || (HERO_JUMP_MAX_STEP > 8)
        .error 'HERO_JUMP_MAX_STEP must be in 1..8 scanlines to guarantee single-boundary crossing'
    .endif
    .if HERO_JUMP_STEP_COUNT < 1
        .error 'HERO_JUMP_STEP_COUNT must be >= 1'
    .endif
    .if (PLAYFIELD_BOTTOM_PMG_Y + 8 + HERO_SPRITE_HEIGHT) > 256
        .error 'Hero bottom/clear coordinates exceed 8-bit PMG page bounds'
    .endif

; ------------------------------------------------------------------------------
; hero_pmg_clear_p0 — Clears all 256 bytes of PMG_P0 ($3C00..$3CFF)
; ------------------------------------------------------------------------------
.proc hero_pmg_clear_p0
    lda #0
    tax
@loop
    sta PMG_P0,x
    inx
    bne @loop
    rts
.endp

; ------------------------------------------------------------------------------
; hero_pmg_erase_drawn — Clears only the 18 lines previously drawn at zp_hero_draw_y
; ------------------------------------------------------------------------------
.proc hero_pmg_erase_drawn
    lda zp_hero_drawn
    beq @done
    ldx zp_hero_draw_y
    ldy #HERO_SPRITE_HEIGHT
    lda #0
@loop
    sta PMG_P0,x
    inx
    dey
    bne @loop
    lda #0
    sta zp_hero_drawn
    sta zp_hero_dirty
@done
    rts
.endp

; ------------------------------------------------------------------------------
; hero_pmg_disable — Cleanly disables PMG when leaving STATE_GAME
; ------------------------------------------------------------------------------
.proc hero_pmg_disable
    lda #0
    sta GRACTL
    sta GPRIOR
    sta PRIOR
    sta HPOSP0
    sta HPOSP1
    sta HPOSP2
    sta HPOSP3
    sta HPOSM0
    sta HPOSM1
    sta HPOSM2
    sta HPOSM3
    sta GRAFP0
    sta GRAFP1
    sta GRAFP2
    sta GRAFP3
    sta GRAFM
    sta zp_hero_drawn
    sta zp_hero_dirty
    jsr hero_pmg_clear_p0
    lda #$22                    ; Normal playfield + DL DMA only (PMG DMA off)
    sta SDMCTL
    sta DMACTL
    rts
.endp

; ------------------------------------------------------------------------------
; hero_footprint_cols — Computes cell columns overlapped by hero collision width
; Outputs:
;   A = col_left = zp_hero_x / 4
;   X = col_right = (zp_hero_x + HERO_COLLISION_WIDTH_CC - 1) / 4
; ------------------------------------------------------------------------------
.proc hero_footprint_cols
    lda zp_hero_x                       ; 3
    clc                                 ; 2
    adc #(HERO_COLLISION_WIDTH_CC - 1)  ; 2
    lsr                                 ; 2
    lsr                                 ; 2
    tax                                 ; 2     X = col_right
    lda zp_hero_x                       ; 3
    lsr                                 ; 2
    lsr                                 ; 2     A = col_left
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_check_support — Checks whether hero bottom sits on a blocked cell row
; Outputs:
;   C = 1 if bottom % 8 == 0 and row (bottom / 8) is blocked within footprint; C = 0 else
; ------------------------------------------------------------------------------
.proc hero_check_support
    lda zp_hero_y                       ; 3
    sec                                 ; 2
    sbc #HERO_TOP_TO_PF_BOTTOM          ; 2     A = bottom_pf (exclusive)
    tay                                 ; 2
    and #$07                            ; 2
    bne @unsupported                    ; 2/3   Not aligned to 8-scanline cell boundary
    tya                                 ; 2
    lsr                                 ; 2
    lsr                                 ; 2
    lsr                                 ; 2     A = row at bottom boundary
    pha                                 ; 3
    jsr hero_footprint_cols             ; 6+    A = col_left, X = col_right
    sta zp_hero_tmp                     ; 3
    pla                                 ; 4
    tay                                 ; 2     Y = support row
    lda zp_hero_tmp                     ; 3     A = col_left
    jmp row_range_blocked               ; 3+    Returns C=1 supported / C=0 unsupported
@unsupported
    lda #0                              ; 2
    clc                                 ; 2
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_body_rows — Computes playfield cell row span overlapped by 18-line sprite body
; Inputs:
;   A = hero top PMG scanline (pmg_y)
; Outputs:
;   C = 1, A = top_row (0..23), Y = bot_row (0..23) if body overlaps playfield
;   C = 0 if body lies completely outside playfield rows 0..23
; Note: Excludes the support row below the feet (last body line = pmg_y + 17 = pf y - 15).
; ------------------------------------------------------------------------------
.proc hero_body_rows
    pha                                 ; 3     Save pmg_y
    sec                                 ; 2
    sbc #(HERO_TOP_TO_PF_BOTTOM + 1)    ; 2     A = pmg_y - 15 = last body scanline in PF
    bcc @none_pop                       ; 2/3   Entirely above playfield row 0
    lsr                                 ; 2
    lsr                                 ; 2
    lsr                                 ; 2     A = bot_row
    cmp #ROOM_HEIGHT                    ; 2
    bcc @bot_ok                         ; 2/3
    lda #(ROOM_HEIGHT - 1)              ; 2     Clamp bot_row to 23
@bot_ok
    tay                                 ; 2     Y = bot_row
    pla                                 ; 4     Restore pmg_y
    sec                                 ; 2
    sbc #PLAYFIELD_TOP_PMG_Y            ; 2     A = pmg_y - 32 = top scanline in PF
    bcc @top_zero                       ; 2/3   Head above playfield top -> top_row = 0
    lsr                                 ; 2
    lsr                                 ; 2
    lsr                                 ; 2     A = top_row
    cmp #ROOM_HEIGHT                    ; 2
    bcs @none                           ; 2/3   Entirely below row 23
    sec                                 ; 2
    rts                                 ; 6
@top_zero
    lda #0                              ; 2
    sec                                 ; 2
    rts                                 ; 6
@none_pop
    pla                                 ; 4
@none
    clc                                 ; 2
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_blocked_at — Tests whether hero collision box at (X, A) overlaps any blocked cell
; Inputs:
;   X = candidate X in playfield color clocks (0..HERO_MAX_X_CC)
;   A = candidate PMG top scanline
; Outputs:
;   C = 1 if blocked, C = 0 if unblocked
; Clobbers:
;   A, X, Y, zp_hero_tmp, zp_hero_tmp2, zp_hero_tmp3, zp_room_*
; ------------------------------------------------------------------------------
.proc hero_blocked_at
    stx zp_hero_tmp3                    ; 3     Save cand_x
    jsr hero_body_rows                  ; 6+    A = top_row, Y = bot_row
    bcc @free                           ; 2/3
    sta zp_hero_tmp                     ; 3     top_row
    sty zp_hero_tmp2                    ; 3     bot_row

    lda zp_hero_tmp3                    ; 3
    clc                                 ; 2
    adc #(HERO_COLLISION_WIDTH_CC - 1)  ; 2
    lsr                                 ; 2
    lsr                                 ; 2
    pha                                 ; 3     Stack: [col_right]
    lda zp_hero_tmp3                    ; 3
    lsr                                 ; 2
    lsr                                 ; 2
    sta zp_hero_tmp3                    ; 3     cur_col = col_left

@col_loop
    ldx zp_hero_tmp3                    ; 3     X = cur_col
    lda zp_hero_tmp                     ; 3     A = top_row
    ldy zp_hero_tmp2                    ; 3     Y = bot_row
    jsr col_range_blocked               ; 6+
    bcs @hit                            ; 2/3
    pla                                 ; 4     A = col_right
    cmp zp_hero_tmp3                    ; 3     cur_col == col_right?
    beq @free                           ; 2/3
    bcc @free                           ; 2/3
    pha                                 ; 3     Push col_right back
    inc zp_hero_tmp3                    ; 5
    bne @col_loop                       ; 3     Unconditional (cur_col >= 1)

@hit
    pla                                 ; 4     Discard col_right
    sec                                 ; 2
    rts                                 ; 6
@free
    clc                                 ; 2
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_try_step_x — Attempts horizontal move in dir A by step Y (1..4 cc)
;                   Clamps to screen edges [0..HERO_MAX_X_CC] and flushes to cell edge.
; Inputs:
;   A = direction (HERO_FACING_RIGHT=0 / HERO_FACING_LEFT=1)
;   Y = step in color clocks (1..4)
; Outputs:
;   C = 1 if zp_hero_x changed (and sets zp_hero_dirty = 1), C = 0 if stopped
; ------------------------------------------------------------------------------
.proc hero_try_step_x
    pha                                 ; 3     Stack: [dir]
    sty zp_hero_tmp                     ; 3     Save step (1..4)
    cmp #HERO_FACING_RIGHT              ; 2
    bne @calc_left                      ; 2/3

    lda zp_hero_x                       ; 3
    clc                                 ; 2
    adc zp_hero_tmp                     ; 3
    bcs @r_clamp                        ; 2/3
    cmp #(HERO_MAX_X_CC + 1)            ; 2
    bcc @cand_ready                     ; 2/3
@r_clamp
    lda #HERO_MAX_X_CC                  ; 2
    jmp @cand_ready                     ; 3

@calc_left
    lda zp_hero_x                       ; 3
    sec                                 ; 2
    sbc zp_hero_tmp                     ; 3
    bcs @cand_ready                     ; 2/3
    lda #0                              ; 2

@cand_ready
    cmp zp_hero_x                       ; 3
    beq @pop1_no_move                   ; 2/3   Already clamped against screen edge
    tax                                 ; 2     X = cand_x
    pha                                 ; 3     Stack: [dir, cand_x]
    lda zp_hero_tmp                     ; 3
    pha                                 ; 3     Stack: [dir, cand_x, step]
    lda zp_hero_y                       ; 3
    jsr hero_blocked_at                 ; 6+    Tests [top_row..bot_row] at (X=cand_x, A=y)
    bcc @commit_cand                    ; 2/3

    pla                                 ; 4     A = step (Stack: [dir, cand_x])
    cmp #2                              ; 2
    bcc @pop2_no_move                   ; 2/3   step == 1 is already flush
    pla                                 ; 4     A = cand_x (Stack: [dir])
    tay                                 ; 2     Y = cand_x
    pla                                 ; 4     A = dir (Stack empty)
    cmp #HERO_FACING_RIGHT              ; 2
    bne @l_flush                        ; 2/3

    ; Blocked moving right with step > 1: snap flush to ((cand_x + W - 1) & $FC) - W
    tya                                 ; 2
    clc                                 ; 2
    adc #(HERO_COLLISION_WIDTH_CC - 1)  ; 2
    and #$FC                            ; 2
    sec                                 ; 2
    sbc #HERO_COLLISION_WIDTH_CC        ; 2
    cmp zp_hero_x                       ; 3
    beq @no_move                        ; 2/3
    bcc @no_move                        ; 2/3
    bcs @check_flush                    ; 3     Unconditional (flush_x > zp_hero_x)

@l_flush
    ; Blocked moving left with step > 1: snap flush to (cand_x & $FC) + 4
    tya                                 ; 2
    and #$FC                            ; 2
    clc                                 ; 2
    adc #4                              ; 2
    cmp zp_hero_x                       ; 3
    bcs @no_move                        ; 2/3   Must move strictly left (< zp_hero_x)

@check_flush
    pha                                 ; 3     Stack: [flush_x]
    tax                                 ; 2     X = flush_x
    lda zp_hero_y                       ; 3
    jsr hero_blocked_at                 ; 6+
    bcs @pop1_no_move                   ; 2/3
    pla                                 ; 4     A = flush_x
    jmp @commit_a                       ; 3

@commit_cand
    pla                                 ; 4     Discard step
    pla                                 ; 4     A = cand_x
    tax                                 ; 2
    pla                                 ; 4     Discard dir
    txa                                 ; 2     A = cand_x
@commit_a
    sta zp_hero_x                       ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
    sec                                 ; 2
    rts                                 ; 6

@pop2_no_move
    pla                                 ; 4     Discard cand_x
@pop1_no_move
    pla                                 ; 4     Discard dir / flush_x
@no_move
    clc                                 ; 2
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_read_input — Decodes active-low Joystick 0 bits (zp_joy_curr) into HERO_CMD_*
; Outputs:
;   A = HERO_CMD_* (0..6)
; ------------------------------------------------------------------------------
.proc hero_read_input
    lda zp_joy_curr                     ; 3
    and #JOY_MASK_ALL                   ; 2
    tax                                 ; 2
    lda hero_joy_cmd_tbl,x              ; 4
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_tick_anim — Advances current looping animation set timer & frame
; ------------------------------------------------------------------------------
.proc hero_tick_anim
    dec zp_hero_anim_timer              ; 5
    bne @done                           ; 2/3
    ldx zp_hero_anim_set                ; 3
    lda hero_set_dur,x                  ; 4
    sta zp_hero_anim_timer              ; 3
    inc zp_hero_anim_frame              ; 5
    lda zp_hero_anim_frame              ; 3
    cmp hero_set_count,x                ; 4
    bcc @dirty                          ; 2/3
    lda #0                              ; 2
    sta zp_hero_anim_frame              ; 3
@dirty
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
@done
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_tick_walk_anim — Advances walk animation at HERO_WALK_ANIM_TICKS PAL cadence
; ------------------------------------------------------------------------------
.proc hero_tick_walk_anim
    dec zp_hero_anim_timer              ; 5
    bne @done                           ; 2/3
    lda #HERO_WALK_ANIM_TICKS           ; 2
    sta zp_hero_anim_timer              ; 3
    ldx zp_hero_anim_set                ; 3
    inc zp_hero_anim_frame              ; 5
    lda zp_hero_anim_frame              ; 3
    cmp hero_set_count,x                ; 4
    bcc @dirty                          ; 2/3
    lda #0                              ; 2
    sta zp_hero_anim_frame              ; 3
@dirty
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
@done
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_enter_standing — Enters STANDING state matching current zp_hero_facing
; ------------------------------------------------------------------------------
.proc hero_enter_standing
    lda #HERO_STATE_STANDING            ; 2
    sta zp_hero_state                   ; 3
    lda #0                              ; 2
    sta zp_hero_fall_idx                ; 3
    sta zp_hero_walk_sub                ; 3
    lda #HERO_JUMP_DIR_NONE             ; 2
    sta zp_hero_jump_dir                ; 3
    ldx zp_hero_facing                  ; 3
    lda hero_stand_set_tbl,x            ; 4
    sta zp_hero_anim_set                ; 3
    lda #HERO_WALK_ANIM_TICKS           ; 2
    sta zp_hero_anim_timer              ; 3
    lda #HERO_STAND_FRAME               ; 2
    sta zp_hero_anim_frame              ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_enter_falling — Enters vertical-only FALLING state (walk-off / unsupported)
; ------------------------------------------------------------------------------
.proc hero_enter_falling
    lda #HERO_STATE_FALLING             ; 2
    sta zp_hero_state                   ; 3
    lda #HERO_FALL_SET                  ; 2
    sta zp_hero_anim_set                ; 3
    ldx #HERO_FALL_SET                  ; 2
    lda hero_set_dur,x                  ; 4
    sta zp_hero_anim_timer              ; 3
    lda #0                              ; 2
    sta zp_hero_anim_frame              ; 3
    sta zp_hero_fall_idx                ; 3
    sta zp_hero_walk_sub                ; 3
    lda #HERO_JUMP_DIR_NONE             ; 2
    sta zp_hero_jump_dir                ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_pmg_draw — Draws current 18-byte hero frame into PMG_P0 iff zp_hero_dirty != 0,
;                 clearing only vacated scanlines to prevent sprite trails.
; Trail-elimination rule:
;   - If !zp_hero_drawn: PMG_P0 is already zero -> clear 0 lines.
;   - Moving down (new_y > old_y, delta = new_y - old_y):
;     * delta < 18 -> clear [old_y .. old_y + delta - 1]
;     * delta >= 18 -> clear all 18 lines at old_y
;   - Moving up (new_y < old_y, delta = old_y - new_y):
;     * delta < 18 -> clear [new_y + 18 .. new_y + 18 + delta - 1]
;     * delta >= 18 -> clear all 18 lines at old_y
;   - Same vertical position (new_y == old_y): clear 0 lines.
; ------------------------------------------------------------------------------
.proc hero_pmg_draw
    lda zp_hero_dirty                   ; 3
    bne @redraw                         ; 2/3
    rts                                 ; 6     Fast exit (12 cyc incl. JSR/RTS = 18) when unchanged

@redraw
    ; Resolve zp_hero_ptr = hero_frame_lo/hi[hero_set_base[set] + frame]
    ldx zp_hero_anim_set                ; 3
    lda hero_set_base,x                 ; 4
    clc                                 ; 2
    adc zp_hero_anim_frame              ; 3
    tay                                 ; 2
    lda hero_frame_lo,y                 ; 4
    sta zp_hero_ptr                     ; 3
    lda hero_frame_hi,y                 ; 4
    sta zp_hero_ptr+1                   ; 3

    ; Clear ONLY vacated bytes when already drawn
    lda zp_hero_drawn                   ; 3
    beq @write_frame                    ; 2/3
    lda zp_hero_y                       ; 3     A = new_y
    cmp zp_hero_draw_y                  ; 3     Compare with old_y
    beq @write_frame                    ; 2/3   Same Y -> 0 bytes to clear
    bcc @moved_up                       ; 2/3

    ; Moved down: delta = new_y - old_y
    sec                                 ; 2
    sbc zp_hero_draw_y                  ; 3
    cmp #HERO_SPRITE_HEIGHT             ; 2
    bcc @down_cnt_ok                    ; 2/3
    lda #HERO_SPRITE_HEIGHT             ; 2
@down_cnt_ok
    tay                                 ; 2     Y = vacated line count (1..18)
    ldx zp_hero_draw_y                  ; 3     X = start clearing at old_y
    bne @clear_vacated                  ; 3     Unconditional (old_y >= 22)

@moved_up
    lda zp_hero_draw_y                  ; 3     delta = old_y - new_y
    sec                                 ; 2
    sbc zp_hero_y                       ; 3
    cmp #HERO_SPRITE_HEIGHT             ; 2
    bcs @full_old_clear                 ; 2/3
    tay                                 ; 2     Y = vacated count (1..17)
    lda zp_hero_y                       ; 3
    clc                                 ; 2
    adc #HERO_SPRITE_HEIGHT             ; 2
    tax                                 ; 2     X = new_y + 18
    bne @clear_vacated                  ; 3

@full_old_clear
    ldy #HERO_SPRITE_HEIGHT             ; 2
    ldx zp_hero_draw_y                  ; 3

@clear_vacated
    lda #0                              ; 2
@clear_loop
    sta PMG_P0,x                        ; 5
    inx                                 ; 2
    dey                                 ; 2
    bne @clear_loop                     ; 2/3

@write_frame
    ldy #0                              ; 2
    ldx zp_hero_y                       ; 3
@copy_loop
    lda (zp_hero_ptr),y                 ; 5
    sta PMG_P0,x                        ; 5
    inx                                 ; 2
    iny                                 ; 2
    cpy #HERO_SPRITE_HEIGHT             ; 2
    bne @copy_loop                      ; 2/3

    lda zp_hero_x                       ; 3
    clc                                 ; 2
    adc #PLAYFIELD_LEFT_CC              ; 2
    sta HPOSP0                          ; 4

    lda zp_hero_y                       ; 3
    sta zp_hero_draw_y                  ; 3
    lda #1                              ; 2
    sta zp_hero_drawn                   ; 3
    lda #0                              ; 2
    sta zp_hero_dirty                   ; 3
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_init — Initializes PMG Player 0 hardware & places hero at cell (X, Y)
; Inputs:
;   X = start cell column (0..39), Y = start cell row (0..23)
; ------------------------------------------------------------------------------
.proc hero_init
    stx zp_hero_tmp
    sty zp_hero_tmp2

    jsr hero_pmg_clear_p0

    lda #>PMG_BASE
    sta PMBASE
    lda #HERO_SIZE
    sta SIZEP0
    lda #0
    sta SIZEP1
    sta SIZEP2
    sta SIZEP3
    sta SIZEM
    sta HPOSP1
    sta HPOSP2
    sta HPOSP3
    sta HPOSM0
    sta HPOSM1
    sta HPOSM2
    sta HPOSM3
    sta GRAFP0
    sta GRAFP1
    sta GRAFP2
    sta GRAFP3
    sta GRAFM

    lda #HERO_COLOR
    sta PCOLR0
    sta COLPM0

    lda #GAME_PRIOR
    sta GPRIOR
    sta PRIOR

    lda #GAME_GRACTL
    sta GRACTL

    ; Convert cell (X, Y) -> playfield color clocks & PMG single-line top Y
    ; x_cc = X * 4, bottom_pf = (Y + 1) * 8, top_pmg = bottom_pf + (32 - 18)
    lda zp_hero_tmp
    asl
    asl
    sta zp_hero_x

    lda zp_hero_tmp2
    clc
    adc #1
    asl
    asl
    asl
    clc
    adc #HERO_TOP_TO_PF_BOTTOM
    sta zp_hero_y

    lda #HERO_START_FACING
    sta zp_hero_facing
    lda #0
    sta zp_hero_fall_idx
    sta zp_hero_jump_idx
    sta zp_hero_walk_sub
    sta zp_hero_fell_out
    sta zp_hero_drawn
    lda #HERO_JUMP_DIR_NONE
    sta zp_hero_jump_dir

    jsr hero_check_support
    bcc @start_falling
    jsr hero_enter_standing
    jmp @initial_draw

@start_falling
    jsr hero_enter_falling

@initial_draw
    lda #1
    sta zp_hero_dirty
    jsr hero_pmg_draw
    rts
.endp

; ------------------------------------------------------------------------------
; hero_update — Dispatches hero state machine once per frame, then updates PMG P0
; ------------------------------------------------------------------------------
.proc hero_update
    lda zp_hero_state                   ; 3
    beq @standing                       ; 2/3
    cmp #HERO_STATE_FALLING             ; 2
    bne @not_fall                       ; 2/3
    jmp hero_update_fall                ; 3
@not_fall
    cmp #HERO_STATE_JUMPING             ; 2
    bne @not_jump                       ; 2/3
    jmp hero_update_jump                ; 3
@not_jump
    jmp hero_update_squat               ; 3

@standing
    jsr hero_check_support              ; 6+
    bcs @supported                      ; 2/3
    jsr hero_enter_falling              ; 6+
    jmp hero_pmg_draw                   ; 3+

@supported
    jsr hero_read_input                 ; 6+    A = HERO_CMD_*
    sta zp_hero_cmd                     ; 3
    beq @cmd_idle                       ; 2/3
    cmp #HERO_CMD_JUMP_RIGHT            ; 2
    bcc @cmd_walk                       ; 2/3   1..2 = WALK_RIGHT / WALK_LEFT
    cmp #HERO_CMD_SQUAT_RIGHT           ; 2
    bcc @cmd_jump                       ; 2/3   3..4 = JUMP_RIGHT / JUMP_LEFT

    ; HERO_CMD_SQUAT_RIGHT (5) / HERO_CMD_SQUAT_LEFT (6) / HERO_CMD_SQUAT (7)
    ; Collision box stays 8x18 (squat frames already occupy bottom lines of 18B window).
    cmp #HERO_CMD_SQUAT                 ; 2
    beq @squat_keep_facing              ; 2/3   DOWN only preserves zp_hero_facing
    sec                                 ; 2
    sbc #HERO_CMD_SQUAT_RIGHT           ; 2     0=RIGHT, 1=LEFT
    sta zp_hero_facing                  ; 3
@squat_keep_facing
    ldx zp_hero_facing                  ; 3
    lda hero_squat_set_tbl,x            ; 4
    sta zp_hero_anim_set                ; 3
    tax                                 ; 2
    lda hero_set_dur,x                  ; 4
    sta zp_hero_anim_timer              ; 3
    lda #0                              ; 2
    sta zp_hero_anim_frame              ; 3
    sta zp_hero_walk_sub                ; 3
    lda #HERO_STATE_SQUATTING           ; 2
    sta zp_hero_state                   ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
    jmp hero_pmg_draw                   ; 3+

@cmd_walk
    jmp hero_update_walk                ; 3+

@cmd_jump
    ; HERO_CMD_JUMP_RIGHT (3) / HERO_CMD_JUMP_LEFT (4)
    ; Note: holding UP+LEFT/RIGHT across landing naturally starts a new jump on return to STANDING.
    sec                                 ; 2
    sbc #HERO_CMD_JUMP_RIGHT            ; 2     0=RIGHT, 1=LEFT
    sta zp_hero_facing                  ; 3
    sta zp_hero_jump_dir                ; 3
    tax                                 ; 2
    lda hero_jump_set_tbl,x             ; 4
    sta zp_hero_anim_set                ; 3
    tax                                 ; 2
    lda hero_set_dur,x                  ; 4
    sta zp_hero_anim_timer              ; 3
    lda #0                              ; 2
    sta zp_hero_anim_frame              ; 3
    sta zp_hero_jump_idx                ; 3
    sta zp_hero_walk_sub                ; 3
    lda #HERO_STATE_JUMPING             ; 2
    sta zp_hero_state                   ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
    jmp hero_update_jump                ; 3+

@cmd_idle
    lda #0                              ; 2
    sta zp_hero_walk_sub                ; 3     Reset fractional walk phase when idle
    ldx zp_hero_facing                  ; 3
    lda hero_stand_set_tbl,x            ; 4
    cmp zp_hero_anim_set                ; 3
    bne @reset_stand                    ; 2/3
    lda zp_hero_anim_frame              ; 3
    cmp #HERO_STAND_FRAME               ; 2
    beq @stand_draw                     ; 2/3   Fast path: zp_hero_dirty stays 0
@reset_stand
    jsr hero_enter_standing             ; 6+
@stand_draw
    jmp hero_pmg_draw                   ; 3+
.endp

; ------------------------------------------------------------------------------
; hero_update_walk — Handles grounded left/right movement, wall stops & ledge falls
; Precondition: zp_hero_cmd is HERO_CMD_WALK_RIGHT (1) or HERO_CMD_WALK_LEFT (2)
; ------------------------------------------------------------------------------
.proc hero_update_walk
    lda zp_hero_cmd                     ; 3
    sec                                 ; 2
    sbc #HERO_CMD_WALK_RIGHT            ; 2     0=RIGHT, 1=LEFT
    sta zp_hero_facing                  ; 3
    tax                                 ; 2
    lda hero_stand_set_tbl,x            ; 4
    cmp zp_hero_anim_set                ; 3
    beq @set_ok                         ; 2/3
    sta zp_hero_anim_set                ; 3
    lda #HERO_WALK_ANIM_TICKS           ; 2
    sta zp_hero_anim_timer              ; 3
    lda #HERO_STAND_FRAME               ; 2
    sta zp_hero_anim_frame              ; 3
    lda #0                              ; 2
    sta zp_hero_walk_sub                ; 3     Reset fractional walk phase on turn
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
@set_ok
    ; Fractional walk gate: steps HERO_WALK_STEP_CC immediately when zp_hero_walk_sub == 0,
    ; then waits HERO_WALK_SPEED_SUBSTEPS-1 frames. Walk animation ticks every active frame at HERO_WALK_ANIM_TICKS.
    lda zp_hero_walk_sub                ; 3
    beq @do_step                        ; 2/3
    dec zp_hero_walk_sub                ; 5
    jsr hero_tick_walk_anim             ; 6+
    jmp hero_pmg_draw                   ; 3+

@do_step
    lda #(HERO_WALK_SPEED_SUBSTEPS - 1) ; 2
    sta zp_hero_walk_sub                ; 3
    lda zp_hero_facing                  ; 3
    ldy #HERO_WALK_STEP_CC              ; 2
    jsr hero_try_step_x                 ; 6+
    bcc @blocked                        ; 2/3

    jsr hero_tick_walk_anim             ; 6+
    jsr hero_check_support              ; 6+    Walked off a ledge?
    bcs @draw                           ; 2/3
    jsr hero_enter_falling              ; 6+
    jmp hero_pmg_draw                   ; 3+

@blocked
    lda #0                              ; 2
    sta zp_hero_walk_sub                ; 3     Reset walk phase against wall or screen edge
    lda zp_hero_anim_frame              ; 3
    cmp #HERO_STAND_FRAME               ; 2
    beq @draw                           ; 2/3   Already standing pose -> no redraw
    lda #HERO_WALK_ANIM_TICKS           ; 2
    sta zp_hero_anim_timer              ; 3
    lda #HERO_STAND_FRAME               ; 2
    sta zp_hero_anim_frame              ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
@draw
    jmp hero_pmg_draw                   ; 3+
.endp

; ------------------------------------------------------------------------------
; hero_update_jump — Advances committed ballistic jump arc, ceiling/top clamp & X
; ------------------------------------------------------------------------------
.proc hero_update_jump
    ldx zp_hero_jump_idx                ; 3
    cpx #HERO_JUMP_STEP_COUNT           ; 2
    bcs @at_min_y                       ; 2/3
    lda zp_hero_y                       ; 3
    cmp #(HERO_MIN_PMG_Y + 1)           ; 2     zp_hero_y <= HERO_MIN_PMG_Y?
    bcc @at_min_y                       ; 2/3

    lda hero_jump_steps,x               ; 4     step (1..8 scanlines)
    sta zp_hero_tmp2                    ; 3
    inc zp_hero_jump_idx                ; 5

    lda #0                              ; 2
    sta zp_hero_tmp                     ; 3     hit_top = 0
    lda zp_hero_y                       ; 3
    sec                                 ; 2
    sbc zp_hero_tmp2                    ; 3
    bcc @clamp_top                      ; 2/3
    cmp #HERO_MIN_PMG_Y                 ; 2
    bcs @cand_y_ok                      ; 2/3
@clamp_top
    lda #HERO_MIN_PMG_Y                 ; 2
    inc zp_hero_tmp                     ; 5     hit_top = 1
@cand_y_ok
    sta zp_hero_tmp2                    ; 3     cand_y

    lda zp_hero_y                       ; 3
    sec                                 ; 2
    sbc #PLAYFIELD_TOP_PMG_Y            ; 2
    lsr                                 ; 2
    lsr                                 ; 2
    lsr                                 ; 2
    sta zp_hero_tmp3                    ; 3     old_head_row

    lda zp_hero_tmp2                    ; 3
    sec                                 ; 2
    sbc #PLAYFIELD_TOP_PMG_Y            ; 2
    lsr                                 ; 2
    lsr                                 ; 2
    lsr                                 ; 2     new_head_row
    cmp zp_hero_tmp3                    ; 3
    beq @commit_rise                    ; 2/3

    pha                                 ; 3     Stack: [new_head_row]
    jsr hero_footprint_cols             ; 6+    A = col_left, X = col_right
    sta zp_hero_tmp3                    ; 3
    pla                                 ; 4
    pha                                 ; 3     Stack: [new_head_row]
    tay                                 ; 2     Y = new_head_row
    lda zp_hero_tmp3                    ; 3     A = col_left
    jsr row_range_blocked               ; 6+
    bcc @no_ceiling                     ; 2/3

    ; Ceiling hit: snap head flush below blocked row and begin falling immediately
    pla                                 ; 4     A = new_head_row
    clc                                 ; 2
    adc #1                              ; 2
    asl                                 ; 2
    asl                                 ; 2
    asl                                 ; 2
    clc                                 ; 2
    adc #PLAYFIELD_TOP_PMG_Y            ; 2     snapped_y
    cmp zp_hero_y                       ; 3
    beq @at_min_y                       ; 2/3
    sta zp_hero_y                       ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
@at_min_y
    lda #HERO_STATE_FALLING             ; 2
    sta zp_hero_state                   ; 3
    lda #0                              ; 2
    sta zp_hero_fall_idx                ; 3
    jmp @horiz_step                     ; 3

@no_ceiling
    pla                                 ; 4     Discard new_head_row
@commit_rise
    lda zp_hero_tmp2                    ; 3
    sta zp_hero_y                       ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
    lda zp_hero_tmp                     ; 3
    bne @at_min_y                       ; 2/3
    lda zp_hero_jump_idx                ; 3
    cmp #HERO_JUMP_STEP_COUNT           ; 2
    bcs @at_min_y                       ; 2/3

@horiz_step
    lda zp_hero_jump_dir                ; 3
    bmi @anim_step                      ; 2/3
    ldy #HERO_JUMP_SPEED_CC             ; 2
    jsr hero_try_step_x                 ; 6+    Side walls stop X only
@anim_step
    jsr hero_tick_anim                  ; 6+
    jmp hero_pmg_draw                   ; 3+
.endp

; ------------------------------------------------------------------------------
; hero_update_fall — Advances falling physics (and jump X velocity if airborne jump)
; ------------------------------------------------------------------------------
.proc hero_update_fall
    lda zp_hero_jump_dir                ; 3
    bmi @no_air_x                       ; 2/3   Vertical-only fall -> skip X step
    ldy #HERO_JUMP_SPEED_CC             ; 2
    jsr hero_try_step_x                 ; 6+    Continue committed jump horizontal velocity
@no_air_x
    ldx zp_hero_fall_idx                ; 3
    lda hero_fall_steps,x               ; 4     A = step (1..8 scanlines)
    sta zp_hero_tmp2                    ; 3
    cpx #(HERO_FALL_STEP_COUNT - 1)     ; 2
    bcs @step_ready                     ; 2/3
    inc zp_hero_fall_idx                ; 5
@step_ready
    lda zp_hero_y                       ; 3
    sec                                 ; 2
    sbc #HERO_TOP_TO_PF_BOTTOM          ; 2     old_bottom_pf
    pha                                 ; 3
    lsr                                 ; 2
    lsr                                 ; 2
    lsr                                 ; 2     old_row = old_bottom_pf >> 3
    sta zp_hero_tmp                     ; 3
    pla                                 ; 4     old_bottom_pf
    clc                                 ; 2
    adc zp_hero_tmp2                    ; 3     new_bottom_pf = old_bottom_pf + step
    pha                                 ; 3     Stack: [new_bottom_pf]
    lsr                                 ; 2
    lsr                                 ; 2
    lsr                                 ; 2     new_row = new_bottom_pf >> 3
    cmp zp_hero_tmp                     ; 3     Crossed row boundary?
    beq @no_landing                     ; 2/3

    pha                                 ; 3     Stack: [new_bottom_pf, new_row]
    jsr hero_footprint_cols             ; 6+    A = col_left, X = col_right
    sta zp_hero_tmp                     ; 3
    pla                                 ; 4     A = new_row (Stack: [new_bottom_pf])
    tay                                 ; 2     Y = new_row
    sty zp_hero_tmp2                    ; 3     Save new_row for snap
    lda zp_hero_tmp                     ; 3     A = col_left
    jsr row_range_blocked               ; 6+
    bcc @no_landing                     ; 2/3

    ; Landed cleanly on boundary (new_row * 8) -> snap and switch to STANDING
    pla                                 ; 4     Discard new_bottom_pf
    lda zp_hero_tmp2                    ; 3     new_row
    asl                                 ; 2
    asl                                 ; 2
    asl                                 ; 2     new_row * 8
    clc                                 ; 2
    adc #HERO_TOP_TO_PF_BOTTOM          ; 2
    sta zp_hero_y                       ; 3
    jsr hero_enter_standing             ; 6+
    jmp hero_pmg_draw                   ; 3+

@no_landing
    pla                                 ; 4     A = new_bottom_pf
    clc                                 ; 2
    adc #HERO_TOP_TO_PF_BOTTOM          ; 2     A = new zp_hero_y
    cmp #PLAYFIELD_BOTTOM_PMG_Y         ; 2     Top >= bottom of playfield (224)?
    bcs @fell_out                       ; 2/3

    sta zp_hero_y                       ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
    jsr hero_tick_anim                  ; 6+
    jmp hero_pmg_draw                   ; 3+

@fell_out
    sta zp_hero_y                       ; 3
    lda #HERO_JUMP_DIR_NONE             ; 2
    sta zp_hero_jump_dir                ; 3
    jsr hero_pmg_erase_drawn            ; 6+    Ensure P0 buffer is clean on Game Over
    lda #1                              ; 2
    sta zp_hero_fell_out                ; 3
    rts                                 ; 6
.endp

; ------------------------------------------------------------------------------
; hero_update_squat — Handles crouched hold (one-shot squat frames) & release
; ------------------------------------------------------------------------------
.proc hero_update_squat
    jsr hero_check_support              ; 6+
    bcs @supported                      ; 2/3
    jsr hero_enter_falling              ; 6+
    jmp hero_pmg_draw                   ; 3+

@supported
    jsr hero_read_input                 ; 6+
    cmp #HERO_CMD_SQUAT_RIGHT           ; 2
    bcc @exit_squat                     ; 2/3   Not squat command (< 5)
    cmp #HERO_CMD_SQUAT                 ; 2
    beq @same_dir                       ; 2/3   DOWN only preserves current facing seamlessly
    sec                                 ; 2
    sbc #HERO_CMD_SQUAT_RIGHT           ; 2     0=RIGHT, 1=LEFT
    cmp zp_hero_facing                  ; 3
    beq @same_dir                       ; 2/3

    sta zp_hero_facing                  ; 3
    tax                                 ; 2
    lda hero_squat_set_tbl,x            ; 4
    sta zp_hero_anim_set                ; 3
    tax                                 ; 2
    lda hero_set_dur,x                  ; 4
    sta zp_hero_anim_timer              ; 3
    lda #0                              ; 2
    sta zp_hero_anim_frame              ; 3
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
    jmp hero_pmg_draw                   ; 3+

@same_dir
    ; One-shot crouch animation: play frames 0..count-1 and hold crouched pose
    ldx zp_hero_anim_set                ; 3
    lda zp_hero_anim_frame              ; 3
    clc                                 ; 2
    adc #1                              ; 2
    cmp hero_set_count,x                ; 4
    bcs @draw_squat                     ; 2/3   At final frame -> dirty stays 0
    dec zp_hero_anim_timer              ; 5
    bne @draw_squat                     ; 2/3
    lda hero_set_dur,x                  ; 4
    sta zp_hero_anim_timer              ; 3
    inc zp_hero_anim_frame              ; 5
    lda #1                              ; 2
    sta zp_hero_dirty                   ; 3
@draw_squat
    jmp hero_pmg_draw                   ; 3+

@exit_squat
    jsr hero_enter_standing             ; 6+
    jmp hero_pmg_draw                   ; 3+
.endp
