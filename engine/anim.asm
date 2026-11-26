; ==============================================================================
; ENGINE/ANIM.ASM — Deduplicated PAL 50 Hz VBI Object Frame Animation Engine
; ==============================================================================
; Updates ONLY really-changing dedicated 8-byte charset slots in place during
; deferred VBI using a shared 8-plane pattern pool and per-object representation:
;   - Form 1 (anim_flags bit 7 == 0): frame-major pattern sequence table +
;     runtime skip check against anim_slot_cur (per-slot current pattern index).
;   - Form 2 (anim_flags bit 7 != 0): cyclic delta lists [count, slot_0, pat_0, ...]
;     walking only slots that change into frame k (zero per-slot state bytes).
; Constant cells use the static pool and are never listed or touched.
;
; PAL ONLY (50 Hz): anim_speed counts PAL VBLANK frames (50 = 1.00 s).
; Strictly MOS 6502 instructions, explicit CLC/SEC before ADC/SBC.
; ==============================================================================

ANIM_VBI_GLYPH_BUDGET = 12      ; Max real 8-byte slot copies per VBI tick

; ------------------------------------------------------------------------------
; _anim_set_slot_dst — Computes 16-bit charset RAM address for base char code A
; Input : A = slot_code (1..127), zp_anim_chbase = >charset_<group>
; Output: zp_anim_dst = (zp_anim_chbase << 8) + slot_code * 8
; Clobbers: A, X, zp_anim_hi
; ------------------------------------------------------------------------------
.proc _anim_set_slot_dst
    ldx #0                      ; 2
    stx zp_anim_hi              ; 3
    asl                         ; 2     *2 (code 1..127 -> C=0)
    asl                         ; 2     *4 (bit7 -> C)
    rol zp_anim_hi              ; 5
    asl                         ; 2     *8 (bit7 -> C)
    rol zp_anim_hi              ; 5
    sta zp_anim_dst             ; 3
    lda zp_anim_hi              ; 3
    clc                         ; 2
    adc zp_anim_chbase          ; 3
    sta zp_anim_dst+1           ; 3
    rts                         ; 6     35 cycles (+JSR/RTS overhead = 41)
.endp

; ------------------------------------------------------------------------------
; _anim_copy_pattern — Copies 8-byte glyph for pattern index X into zp_anim_dst
; Input : X = pat_idx (0..255), zp_anim_dst, zp_anim_flags (bits 6..0 = bank)
; Clobbers: A, X, Y (plus zp_anim_psrc, zp_anim_pat, zp_anim_row when split pool)
; Preserves: zp_anim_src, zp_anim_scodes, zp_anim_ptr, zp_anim_tmp, zp_anim_hi
; ------------------------------------------------------------------------------
.proc _anim_copy_pattern
    .ifdef ANIM_COUNT_COPIES
    inc anim_copy_count         ; 6     Test harness telemetry: count real copies
    .endif

    .if ANIM_POOL_COUNT <= 1
        .if ANIM_COUNT > 0
        ldy #0                  ; 2
        lda anim_pool0_b0,X     ; 4+
        sta (zp_anim_dst),Y     ; 6
        iny                     ; 2
        lda anim_pool0_b1,X     ; 4+
        sta (zp_anim_dst),Y     ; 6
        iny                     ; 2
        lda anim_pool0_b2,X     ; 4+
        sta (zp_anim_dst),Y     ; 6
        iny                     ; 2
        lda anim_pool0_b3,X     ; 4+
        sta (zp_anim_dst),Y     ; 6
        iny                     ; 2
        lda anim_pool0_b4,X     ; 4+
        sta (zp_anim_dst),Y     ; 6
        iny                     ; 2
        lda anim_pool0_b5,X     ; 4+
        sta (zp_anim_dst),Y     ; 6
        iny                     ; 2
        lda anim_pool0_b6,X     ; 4+
        sta (zp_anim_dst),Y     ; 6
        iny                     ; 2
        lda anim_pool0_b7,X     ; 4+
        sta (zp_anim_dst),Y     ; 6
        .endif
    rts                         ; 6     108..116 cycles unrolled
    .else
    stx zp_anim_pat             ; 3     pat_idx (0..255)
    lda zp_anim_flags           ; 3
    and #ANIM_BANK_MASK         ; 2     bank index (0..ANIM_POOL_COUNT-1)
    asl                         ; 2
    asl                         ; 2
    asl                         ; 2     X = bank * 8
    tax                         ; 2
    lda #0                      ; 2
    sta zp_anim_row             ; 3
@row_loop
    lda anim_pb_lo,X            ; 4
    sta zp_anim_psrc            ; 3
    lda anim_pb_hi,X            ; 4
    sta zp_anim_psrc+1          ; 3
    ldy zp_anim_pat             ; 3
    lda (zp_anim_psrc),Y        ; 5+
    ldy zp_anim_row             ; 3
    sta (zp_anim_dst),Y         ; 6
    inx                         ; 2
    inc zp_anim_row             ; 5
    lda zp_anim_row             ; 3
    cmp #8                      ; 2
    bcc @row_loop               ; 2/3
    rts                         ; 6
    .endif
.endp

; ------------------------------------------------------------------------------
; _anim_load_obj_meta — Loads metadata for anim_idx = A into ZP caches
; Output: zp_anim_id, zp_anim_chbase, zp_anim_flags, zp_anim_slots, zp_anim_scodes
; Clobbers: A, Y
; ------------------------------------------------------------------------------
.proc _anim_load_obj_meta
    sta zp_anim_id              ; 3
    tay                         ; 2
    lda anim_chbase,Y           ; 4
    sta zp_anim_chbase          ; 3
    lda anim_flags,Y            ; 4
    sta zp_anim_flags           ; 3
    lda anim_slots,Y            ; 4
    sta zp_anim_slots           ; 3
    lda anim_scodes_lo,Y        ; 4
    sta zp_anim_scodes          ; 3
    lda anim_scodes_hi,Y        ; 4
    sta zp_anim_scodes+1        ; 3
    rts                         ; 6
.endp

; ------------------------------------------------------------------------------
; _anim_mark_deferred — Records deferred animation work and preserves earliest cursor
; ------------------------------------------------------------------------------
.proc _anim_mark_deferred
    lda zp_anim_pending         ; 3
    bne @already                ; 2/3
    lda #1                      ; 2
    sta zp_anim_pending         ; 3
    lda zp_anim_idx             ; 3
    sta zp_anim_cursor          ; 3
@already
    rts                         ; 6
.endp

; ------------------------------------------------------------------------------
; room_anim_init — Initializes runtime state and loads frame 0 into charset RAM
; Call while display/VBI animations are stopped (e.g. from game_enter).
; Input : X = room_id (1..ROOM_MAX_ID)
; ------------------------------------------------------------------------------
.proc room_anim_init
    lda #0
    sta zp_anim_active          ; Disable VBI updates during setup
    sta zp_anim_pending
    sta zp_anim_cursor
    sta zp_anim_sbase           ; Running offset in anim_slot_cur for Form 1 objs

    lda room_anim_count,X
    sta anim_room_count
    beq @done                   ; Static room (zp_anim_active stays 0)

    lda room_anim_lo,X
    sta zp_anim_ptr
    lda room_anim_hi,X
    sta zp_anim_ptr+1

    lda #0
    sta zp_anim_idx
@init_obj_loop
    ldy zp_anim_idx
    lda (zp_anim_ptr),Y         ; A = 0-based anim_idx
    ldx zp_anim_idx
    sta anim_st_id,X
    jsr _anim_load_obj_meta     ; Sets zp_anim_id/chbase/flags/slots/scodes

    ldx zp_anim_idx
    ldy zp_anim_id
    lda anim_speed,Y
    sta anim_st_cnt,X
    lda #0
    sta anim_st_frame,X
    sta anim_st_vis,X
    sta anim_st_pend,X
    sta anim_st_pos,X
    lda zp_anim_sbase
    sta anim_st_sbase,X         ; Base offset inside anim_slot_cur (Form 1)

    ; Bytes 0..S-1 of anim_data hold frame-0 pattern indices in BOTH Form 1 & Form 2
    lda anim_data_lo,Y
    sta zp_anim_src
    lda anim_data_hi,Y
    sta zp_anim_src+1

    lda #0
    sta zp_anim_pos
@init_slot_loop
    ldy zp_anim_pos
    lda (zp_anim_src),Y         ; A = frame-0 pattern index
    sta zp_anim_tmp

    ; If Form 1 (bit 7 of zp_anim_flags == 0), record pattern in anim_slot_cur
    bit zp_anim_flags
    bmi @init_copy
    ldx zp_anim_sbase
    sta anim_slot_cur,X
    inc zp_anim_sbase

@init_copy
    ldy zp_anim_pos
    lda (zp_anim_scodes),Y      ; A = dedicated base char code (1..127)
    jsr _anim_set_slot_dst
    ldx zp_anim_tmp             ; X = pattern index
    jsr _anim_copy_pattern

    inc zp_anim_pos
    lda zp_anim_pos
    cmp zp_anim_slots
    bcc @init_slot_loop

    inc zp_anim_idx
    lda zp_anim_idx
    cmp anim_room_count
    bcc @init_obj_loop

    lda anim_room_count
    sta zp_anim_active          ; Enable VBI animation ticks
@done
    rts
.endp

; ------------------------------------------------------------------------------
; anim_tick — Advances PAL frame counters and copies ONLY changed slots (<=12/VBI)
;
; Worst-case cost (ANIM_POOL_COUNT=1, single Form 2 object updating 12 slots):
;   Pass 1 timer + Pass 2 Form 2 dispatch + 12*(pair + dst + 110B copy) ~ 2,150 cyc
; Static disabled exit (zp_anim_active == 0): 12 cycles (incl. RTS).
; ------------------------------------------------------------------------------
.proc anim_tick
    .ifdef ANIM_COUNT_COPIES
    lda #0                      ; 2
    sta anim_copy_count         ; 4     Reset per-tick telemetry counter
    .endif

    lda zp_anim_active          ; 3
    beq @exit                   ; 2/3   Fast exit when disabled (12 cyc incl. RTS)

    ; --- Pass 1: Decrement all PAL counters unconditionally (zero counter drift) ---
    ldx #0                      ; 2
@timer_loop
    dec anim_st_cnt,X           ; 7
    bne @timer_next             ; 2/3
    ldy anim_st_id,X            ; 4
    lda anim_speed,Y            ; 4
    sta anim_st_cnt,X           ; 5     Reload PAL tick countdown
    lda anim_st_frame,X         ; 4
    clc                         ; 2
    adc #1                      ; 2
    cmp anim_frames,Y           ; 4
    bcc @frame_ok               ; 2/3
    lda #0                      ; 2     Wrap frame N -> 0
@frame_ok
    sta anim_st_frame,X         ; 5
    lda #1                      ; 2
    sta anim_st_pend,X          ; 5
    sta zp_anim_pending         ; 3
    ; Form 1 restarts slot check at 0 on a new target frame; Form 2 keeps any
    ; in-flight delta pair cursor so intermediate delta finishes cleanly first.
    lda anim_flags,Y            ; 4
    bmi @timer_next             ; 2/3
    lda #0                      ; 2
    sta anim_st_pos,X           ; 5
@timer_next
    inx                         ; 2
    cpx anim_room_count         ; 4
    bcc @timer_loop             ; 2/3

    ; --- Pass 2: Copy changed/delta slots within ANIM_VBI_GLYPH_BUDGET ---
    lda zp_anim_pending         ; 3
    bne @start_copy             ; 2/3
@exit
    rts                         ; 6

@start_copy
    lda #ANIM_VBI_GLYPH_BUDGET  ; 2
    sta zp_anim_budget          ; 3
    lda #0                      ; 2
    sta zp_anim_pending         ; 3     Re-set only if work remains after this VBI

    lda anim_room_count         ; 4
    sta zp_anim_rem             ; 3
    lda zp_anim_cursor          ; 3
    cmp anim_room_count         ; 4
    bcc @cursor_ok              ; 2/3
    lda #0                      ; 2
@cursor_ok
    sta zp_anim_idx             ; 3

@copy_loop
    ldx zp_anim_idx             ; 3
    lda anim_st_pend,X          ; 4
    bne @obj_pending            ; 2/3
    jmp @copy_next              ; 3

@obj_pending
    lda anim_st_id,X            ; 4
    jsr _anim_load_obj_meta     ; 6+    Sets id/chbase/flags/slots/scodes

    ldx zp_anim_idx             ; 3
    lda anim_st_pos,X           ; 4
    sta zp_anim_pos             ; 3

    bit zp_anim_flags           ; 3
    bpl @handle_form1           ; 2/3
    jmp @handle_form2           ; 3

    ; ==========================================================================
    ; Form 1: Sequence table — skip slots whose pattern matches anim_slot_cur
    ; ==========================================================================
@handle_form1
    lda anim_st_sbase,X         ; 4
    sta zp_anim_sbase           ; 3
    ldy zp_anim_id              ; 3
    lda anim_data_lo,Y          ; 4
    sta zp_anim_src             ; 3
    lda anim_data_hi,Y          ; 4
    sta zp_anim_src+1           ; 3
    lda anim_st_frame,X         ; 4     Compute zp_anim_src += frame * S
    beq @f1_slot_loop           ; 2/3
    sta zp_anim_tmp             ; 3
@f1_mul_loop
    lda zp_anim_src             ; 3
    clc                         ; 2
    adc zp_anim_slots           ; 3
    sta zp_anim_src             ; 3
    bcc @f1_mul_nc              ; 2/3
    inc zp_anim_src+1           ; 5
@f1_mul_nc
    dec zp_anim_tmp             ; 5
    bne @f1_mul_loop            ; 2/3

@f1_slot_loop
    ldy zp_anim_pos             ; 3     Y = slot index s (0..S-1)
    lda (zp_anim_src),Y         ; 5+    A = target pattern index
    sta zp_anim_tmp             ; 3
    lda zp_anim_sbase           ; 3
    clc                         ; 2
    adc zp_anim_pos             ; 3
    tax                         ; 2     X = sbase + s
    lda zp_anim_tmp             ; 3
    cmp anim_slot_cur,X         ; 4     Unchanged from current displayed pattern?
    beq @f1_next_slot           ; 2/3   Yes -> skip! (0 copies, 0 budget)

    lda zp_anim_budget          ; 3     Check VBI copy budget before copying
    bne @f1_have_budget         ; 2/3
    ldx zp_anim_idx             ; 3     Save slot resume cursor
    lda zp_anim_pos             ; 3
    sta anim_st_pos,X           ; 5
    jsr _anim_mark_deferred     ; 6+
    jmp @copy_next              ; 3

@f1_have_budget
    lda zp_anim_tmp             ; 3     Record new displayed pattern index
    sta anim_slot_cur,X         ; 5
    dec zp_anim_budget          ; 5     Account real copy against VBI budget
    lda (zp_anim_scodes),Y      ; 5+    Y = s -> base char code (1..127)
    jsr _anim_set_slot_dst      ; 6+
    ldx zp_anim_tmp             ; 3
    jsr _anim_copy_pattern      ; 6+

@f1_next_slot
    inc zp_anim_pos             ; 5
    lda zp_anim_pos             ; 3
    cmp zp_anim_slots           ; 4
    bcc @f1_slot_loop           ; 2/3

    ldx zp_anim_idx             ; 3
    lda #0                      ; 2
    sta anim_st_pend,X          ; 5
    sta anim_st_pos,X           ; 5
    jmp @copy_next              ; 3

    ; ==========================================================================
    ; Form 2: Cyclic delta lists [count, slot_0, pat_0, ...]
    ; ==========================================================================
@handle_form2
    ; Set zp_anim_src = anim_data[id] + S (points to [<delta_0..F-1][>delta_0..F-1])
    ldy zp_anim_id              ; 3
    lda anim_data_lo,Y          ; 4
    clc                         ; 2
    adc zp_anim_slots           ; 3
    sta zp_anim_src             ; 3
    lda anim_data_hi,Y          ; 4
    adc #0                      ; 2
    sta zp_anim_src+1           ; 3

@f2_frame_loop
    ldx zp_anim_idx             ; 3
    ; Exit iff no partial delta is mid-flight AND anim_st_vis == anim_st_frame
    lda zp_anim_pos             ; 3
    bne @f2_apply_delta         ; 2/3
    lda anim_st_vis,X           ; 4
    cmp anim_st_frame,X         ; 4
    bne @f2_apply_delta         ; 2/3
    lda #0                      ; 2
    sta anim_st_pend,X          ; 5
    jmp @copy_next              ; 3

@f2_apply_delta
    ; next_f = (anim_st_vis,X + 1) % anim_frames[id]
    lda anim_st_vis,X           ; 4
    clc                         ; 2
    adc #1                      ; 2
    ldy zp_anim_id              ; 3
    cmp anim_frames,Y           ; 4
    bcc @f2_nf_ok               ; 2/3
    lda #0                      ; 2
@f2_nf_ok
    sta zp_anim_tmp             ; 3     zp_anim_tmp = next_f

    ; Resolve delta block pointer zp_anim_ptr = delta_k(next_f)
    tay                         ; 2     Y = next_f
    lda (zp_anim_src),Y         ; 5+
    sta zp_anim_ptr             ; 3
    tya                         ; 2
    clc                         ; 2
    ldy zp_anim_id              ; 3
    adc anim_frames,Y           ; 4
    tay                         ; 2     Y = next_f + F
    lda (zp_anim_src),Y         ; 5+
    sta zp_anim_ptr+1           ; 3

    ; Check delta count = (zp_anim_ptr)[0]
    ldy #0                      ; 2
    lda (zp_anim_ptr),Y         ; 5+
    sta zp_anim_dcnt            ; 3     zp_anim_dcnt = pair count (0..S)
    lda zp_anim_pos             ; 3
    cmp zp_anim_dcnt            ; 3     pair_idx >= count?
    bcs @f2_delta_done          ; 2/3

@f2_pair_loop
    lda zp_anim_budget          ; 3     Check VBI copy budget before copying pair
    bne @f2_have_budget         ; 2/3
    ldx zp_anim_idx             ; 3     Save pair cursor and leave anim_st_vis unchanged
    lda zp_anim_pos             ; 3
    sta anim_st_pos,X           ; 5
    jsr _anim_mark_deferred     ; 6+
    jmp @copy_next              ; 3

@f2_have_budget
    dec zp_anim_budget          ; 5
    ; Read pair p = zp_anim_pos at offset Y = 1 + 2 * p (max Y = 254)
    lda zp_anim_pos             ; 3
    asl                         ; 2     2 * p
    clc                         ; 2
    adc #1                      ; 2     1 + 2 * p
    tay                         ; 2
    lda (zp_anim_ptr),Y         ; 5+    A = slot_idx (0..S-1)
    tax                         ; 2
    iny                         ; 2     2 + 2 * p
    lda (zp_anim_ptr),Y         ; 5+    A = target pattern index
    sta zp_anim_tmp             ; 3     Save pat_idx (overwrites temp next_f; reload from vis+1 on exit)

    txa                         ; 2
    tay                         ; 2     Y = slot_idx
    lda (zp_anim_scodes),Y      ; 5+    A = dedicated base char code (1..127)
    jsr _anim_set_slot_dst      ; 6+
    ldx zp_anim_tmp             ; 3     X = pat_idx
    jsr _anim_copy_pattern      ; 6+

    inc zp_anim_pos             ; 5
    lda zp_anim_pos             ; 3
    cmp zp_anim_dcnt            ; 3
    bcc @f2_pair_loop           ; 2/3

@f2_delta_done
    ; Recompute next_f = (anim_st_vis,X + 1) % anim_frames[id] cleanly
    ldx zp_anim_idx             ; 3
    lda anim_st_vis,X           ; 4
    clc                         ; 2
    adc #1                      ; 2
    ldy zp_anim_id              ; 3
    cmp anim_frames,Y           ; 4
    bcc @f2_adv_ok              ; 2/3
    lda #0                      ; 2
@f2_adv_ok
    sta anim_st_vis,X           ; 5
    lda #0                      ; 2
    sta zp_anim_pos             ; 3
    sta anim_st_pos,X           ; 5
    jmp @f2_frame_loop          ; 3     Catch up if multiple ticks accumulated

@copy_next
    inc zp_anim_idx             ; 5
    lda zp_anim_idx             ; 3
    cmp anim_room_count         ; 4
    bcc @no_wrap                ; 2/3
    lda #0                      ; 2
    sta zp_anim_idx             ; 3
@no_wrap
    dec zp_anim_rem             ; 5
    beq @copy_done              ; 2/3
    jmp @copy_loop              ; 3
@copy_done
    rts                         ; 6
.endp
