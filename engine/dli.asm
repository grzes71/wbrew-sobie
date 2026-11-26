; ==============================================================================
; ENGINE/DLI.ASM — Display List Interrupt & VBLANK Handlers
; ==============================================================================

; ------------------------------------------------------------------------------
; title_dli_handler — Switches CHBASE & 5th-player HPOSM0..3 before each Mode 4 row
; Triggered before every Mode 4 row (0..23): once on 3rd DL_BLANK8, then rows 0..22
; ------------------------------------------------------------------------------
.proc title_dli_handler
    pha                         ; 3  (3)  Save A
    txa                         ; 2  (5)
    pha                         ; 3  (8)  Save X

    ldx zp_dli_idx              ; 3  (11) Current DLI row index (0..TITLE_DLI_COUNT-1)
    lda title_dli_chbase,x      ; 4  (15) Fetch high byte of charset for row X
    sta WSYNC                   ; 4  (19) Synchronize to horizontal blank before scanline 0
    sta CHBASE                  ; 4  (23) Commit charset base for row X before badline DMA

    lda p5_row_x,x              ; 4  (27) Fetch wave X position for row X (during blank scanline 0 of PMG)
    sta HPOSM0                  ; 4  (31) Missile 0 at X
    clc                         ; 2  (33)
    adc #2                      ; 2  (35)
    sta HPOSM1                  ; 4  (39) Missile 1 at X+2
    adc #2                      ; 2  (41)
    sta HPOSM2                  ; 4  (45) Missile 2 at X+4
    adc #2                      ; 2  (47)
    sta HPOSM3                  ; 4  (51) Missile 3 at X+6

    inx                         ; 2  (53) Advance DLI row index
    cpx #TITLE_DLI_COUNT        ; 2  (55) Reached end of frame's DLI list (24)?
    bcc @save_idx               ; 2/3(57/58)
    ldx #0                      ; 2  (59) Wrap index back to 0
@save_idx
    stx zp_dli_idx              ; 3  (62) Store updated DLI index

    pla                         ; 4  (66) Restore X
    tax                         ; 2  (68)
    pla                         ; 4  (72) Restore A
    rti                         ; 6  (78) Return from interrupt
.endp

; ------------------------------------------------------------------------------
; title_vbi_deferred — Resets DLI zone index and top-of-screen CHBASE every VBI
; ------------------------------------------------------------------------------
.proc title_vbi_deferred
    lda #0                      ; 2  (2)
    sta zp_dli_idx              ; 3  (5)  Reset DLI transition index to band 0
    lda #>title_charset_0       ; 2  (7)
    sta CHBAS                   ; 4  (11) Ensure OS shadow holds top charset
    sta CHBASE                  ; 4  (15) Ensure hardware CHBASE starts at charset 0
    jmp XITVBV                  ; 3  (18) Exit OS Deferred VBI
.endp

; ------------------------------------------------------------------------------
; room_dli_handler — Switches CHBASE and 5 GTIA playfield/background colors
; Triggered on scanline 7 of rows preceding a row-style change in room_dlist
; ------------------------------------------------------------------------------
.proc room_dli_handler
    pha                         ; 3  (3)  Save A
    txa                         ; 2  (5)
    pha                         ; 3  (8)  Save X
    tya                         ; 2  (10)
    pha                         ; 3  (13) Save Y

    ldx zp_dli_idx              ; 3  (16) Current DLI transition index (0..room_dli_count-1)
    ldy room_dli_style,x        ; 4  (20) Target style ID for next row
    lda style_chbase,y          ; 4  (24) Preload CHBASE before WSYNC
    ldx style_colbk,y           ; 4  (28) Preload COLBK before WSYNC

    sta WSYNC                   ; 4  (32) Wait for horizontal blank at end of scanline 7
    sta CHBASE                  ; 4  (4)  Commit charset base for next row
    stx COLBK                   ; 4  (8)  Commit background color
    lda style_colpf0,y          ; 4  (12)
    sta COLPF0                  ; 4  (16) Commit COLPF0
    lda style_colpf1,y          ; 4  (20)
    sta COLPF1                  ; 4  (24) Commit COLPF1
    lda style_colpf2,y          ; 4  (28)
    sta COLPF2                  ; 4  (32) Commit COLPF2
    lda style_colpf3,y          ; 4  (36)
    sta COLPF3                  ; 4  (40) Commit COLPF3

    ldx zp_dli_idx              ; 3  (43) Advance DLI transition index
    inx                         ; 2  (45)
    cpx room_dli_count          ; 4  (49) Reached last DLI transition in frame?
    bcc @save_idx               ; 2/3(51/52)
    ldx #0                      ; 2  (53) Wrap index back to 0
@save_idx
    stx zp_dli_idx              ; 3  (56) Store updated DLI index

    pla                         ; 4  (60) Restore Y
    tay                         ; 2  (62)
    pla                         ; 4  (66) Restore X
    tax                         ; 2  (68)
    pla                         ; 4  (72) Restore A
    rti                         ; 6  (78) Return from interrupt
.endp

; ------------------------------------------------------------------------------
; game_vbi_deferred — Deferred VBI handler for STATE_GAME (VVBLKD)
; Fast-exits in 9 cycles on static rooms (when zp_anim_active == 0) before
; clearing zp_dli_idx and jumping to XITVBV.
; ------------------------------------------------------------------------------
.proc game_vbi_deferred
    lda zp_anim_active          ; 3  (3) Any active room animations?
    beq @static_exit            ; 2/3 (6) 9 cycles incl. @static_exit reset path check
    jsr anim_tick               ; 6  (11) Update counters + budgeted charset copies
@static_exit
    lda #0                      ; 2  (8)  Reset per-frame DLI index at top of VBLANK
    sta zp_dli_idx              ; 3  (11)
    jmp XITVBV                  ; 3  (14) Exit OS Deferred VBI
.endp
