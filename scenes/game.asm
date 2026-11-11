; ==============================================================================
; SCENES/GAME.ASM — Main Gameplay State (STATE_GAME)
; ==============================================================================

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

.proc game_enter
    lda #$40
    sta NMIEN
    lda #0
    sta SDMCTL
    sta DMACTL

    jsr apply_global_palette
    jsr clear_screen_vram

    ; Use standard ROM font ($E0) for placeholder game screen
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

.proc game_update
    ; If FIRE pressed:
    ;   - Joy UP held (bit 0 of zp_joy_curr == 0) -> STATE_GAME_OVER_SUCCESS
    ;   - Otherwise -> STATE_GAME_OVER_FAILURE
    lda zp_fire_pressed
    beq @stay

    lda zp_joy_curr
    and #$01
    beq @victory

    lda #STATE_GAME_OVER_FAILURE
    sta zp_next_state
    rts

@victory
    lda #STATE_GAME_OVER_SUCCESS
    sta zp_next_state
@stay
    rts
.endp

