; ==============================================================================
; SCENES/GAME.ASM — Main Gameplay State (STATE_GAME)
; ==============================================================================

.proc game_enter
    ; 1. Disable DLI, display DMA, and VBI animations while building room display
    lda #$40
    sta NMIEN
    lda #0
    sta SDMCTL
    sta DMACTL
    sta zp_anim_active
    sta zp_anim_pending

    ; 2. Silence / disable PMG inherited from Title Screen
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

    ; 3. Render START_ROOM into SCREEN_VRAM ($3000), build Display List, and init animations
    ldx #START_ROOM
    jsr room_draw
    ldx #START_ROOM
    jsr room_setup_display
    ldx #START_ROOM
    jsr room_anim_init

    ; 4. Atomically install room Display List, DLI handler, and Deferred VBI vector
    lda #$00
    sta NMIEN

    lda #<room_dlist
    sta SDLSTL
    sta DLISTL
    lda #>room_dlist
    sta SDLSTH
    sta DLISTH

    lda #<room_dli_handler
    sta VDSLST
    lda #>room_dli_handler
    sta VDSLST+1

    lda #<game_vbi_deferred
    sta VVBLKD
    lda #>game_vbi_deferred
    sta VVBLKD+1

    ; 5. Re-enable normal playfield DMA ($22) via OS shadow (and direct DMACTL)
    lda #$22
    sta SDMCTL
    sta DMACTL

    ; 6. Clear latched NMI flags and enable DLI only if room uses style changes
    sta NMIRES
    lda room_dli_count
    beq @no_dli
    lda #$C0                    ; VBI + DLI enabled
    bne @set_nmien              ; unconditional (non-zero)
@no_dli
    lda #$40                    ; VBI only (uniform room style)
@set_nmien
    sta NMIEN
    rts
.endp

.proc game_update
    ; Keep top-of-frame DLI index synchronized every VBLANK
    lda #0
    sta zp_dli_idx

    ; Wait for new FIRE press:
    ;   - Joy UP held (bit 0 of zp_joy_curr == 0) -> STATE_GAME_OVER_SUCCESS
    ;   - Otherwise -> STATE_GAME_OVER_FAILURE
    lda zp_fire_pressed
    beq @stay

    lda zp_joy_curr
    and #$01
    beq @victory

    lda #STATE_GAME_OVER_FAILURE
    bne @leave_game
@victory
    lda #STATE_GAME_OVER_SUCCESS
@leave_game
    sta zp_next_state
    lda #$00
    sta zp_anim_active
    sta zp_anim_pending
    sta NMIEN
    lda #<XITVBV
    sta VVBLKD
    lda #>XITVBV
    sta VVBLKD+1
    sta NMIRES
    lda #$40
    sta NMIEN
@stay
    rts
.endp

