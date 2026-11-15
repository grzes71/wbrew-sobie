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
