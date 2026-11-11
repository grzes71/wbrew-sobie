; ==============================================================================
; ENGINE/DLI.ASM — Display List Interrupt & VBLANK Handlers
; ==============================================================================

; ------------------------------------------------------------------------------
; title_dli_handler — Switches CHBASE mid-frame between Title Screen charsets
; Triggered on the last scanline of each character row preceding a new charset band
; ------------------------------------------------------------------------------
.proc title_dli_handler
    pha                         ; 3  (3)  Save A
    txa                         ; 2  (5)
    pha                         ; 3  (8)  Save X

    ldx zp_dli_idx              ; 3  (11) Current DLI transition index (0..TITLE_DLI_COUNT-1)
    lda title_dli_chbase,x      ; 4  (15) Fetch high byte of next charset
    sta WSYNC                   ; 4  (19) Synchronize to horizontal blank (19 cycles pre-WSYNC)
    sta CHBASE                  ; 4  (23) Commit new charset base for next mode 4 row

    inx                         ; 2  (25) Advance DLI zone index
    cpx #TITLE_DLI_COUNT        ; 2  (27) Reached end of frame's DLI list?
    bcc @save_idx               ; 2/3(29/30)
    ldx #0                      ; 2  (31) Wrap index back to 0
@save_idx
    stx zp_dli_idx              ; 3  (34) Store updated DLI index

    pla                         ; 4  (38) Restore X
    tax                         ; 2  (40)
    pla                         ; 4  (44) Restore A
    rti                         ; 6  (50) Return from interrupt
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
