; ==============================================================================
; SCENES/GAMEOVER.ASM — Game Over States (FAILURE & SUCCESS)
; ==============================================================================

.proc gameover_failure_enter
    lda #$40
    sta NMIEN
    lda #0
    sta SDMCTL
    sta DMACTL

    jsr apply_global_palette
    jsr clear_screen_vram

    lda #$E0
    sta CHBAS
    sta CHBASE

    lda #<game_dlist
    sta SDLSTL
    sta DLISTL
    lda #>game_dlist
    sta SDLSTH
    sta DLISTH

    lda #$22
    sta SDMCTL
    sta DMACTL
    lda #$40
    sta NMIEN
    rts
.endp

.proc gameover_failure_update
    lda zp_fire_pressed
    beq @stay
    lda #STATE_TITLE_SCREEN
    sta zp_next_state
@stay
    rts
.endp

.proc gameover_success_enter
    jsr gameover_failure_enter
    rts
.endp

.proc gameover_success_update
    lda zp_fire_pressed
    beq @stay
    lda #STATE_TITLE_SCREEN
    sta zp_next_state
@stay
    rts
.endp

