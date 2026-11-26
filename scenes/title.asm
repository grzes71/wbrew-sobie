; ==============================================================================
; SCENES/TITLE.ASM — Title Screen State (STATE_TITLE_SCREEN)
; Mode: ANTIC 4 (40x24 multicolor character mode) with DLI CHBASE switching
; ==============================================================================

.proc apply_global_palette
    lda #PAL_COLBK
    sta COLOR4
    sta COLBK

    lda #PAL_COLOR0
    sta COLOR0
    sta COLPF0

    lda #PAL_COLOR1
    sta COLOR1
    sta COLPF1

    lda #PAL_COLOR2
    sta COLOR2
    sta COLPF2

    lda #PAL_COLOR3
    sta COLOR3
    sta COLPF3
    rts
.endp

.proc title_enter
    ; 1. Disable DLI and display DMA during screen setup
    lda #$40
    sta NMIEN
    lda #0
    sta SDMCTL
    sta DMACTL
    sta zp_anim_active
    sta zp_anim_pending

    ; 2. Apply global colors from colors.asm
    jsr apply_global_palette

    ; 3. Decompress RLE title screen glyphs into SCREEN_VRAM ($3000)
    lda #<title_screen_rle
    sta zp_rle_src
    lda #>title_screen_rle
    sta zp_rle_src+1

    lda #<SCREEN_VRAM
    sta zp_rle_dst
    lda #>SCREEN_VRAM
    sta zp_rle_dst+1

    jsr rle_decompress

    ; 4. Set initial charset (band 0) and reset DLI transition index
    lda #0
    sta zp_dli_idx
    lda #>title_charset_0
    sta CHBAS
    sta CHBASE

    ; 5. Install Title Screen Display List and DLI vector
    lda #<title_dlist
    sta SDLSTL
    sta DLISTL
    lda #>title_dlist
    sta SDLSTH
    sta DLISTH

    lda #<title_dli_handler
    sta VDSLST
    lda #>title_dli_handler
    sta VDSLST+1

    ; 6. Configure PMG: clear buffer, render WBREW on P0, SOBIE on P1, and background blocks on P2 & P3
    jsr pmg_clear
    jsr pmg_init_single_line

    ; Setup Player 0, 1, 2, 3 colors and horizontal positions
    lda #TITLE_P0_COLOR
    sta PCOLR0
    sta COLPM0

    lda #TITLE_P1_COLOR
    sta PCOLR1
    sta COLPM1

    lda #TITLE_P2_COLOR
    sta PCOLR2
    sta COLPM2

    lda #TITLE_P3_COLOR
    sta PCOLR3
    sta COLPM3

    lda #TITLE_P0_X
    sta HPOSP0

    lda #TITLE_P1_X
    sta HPOSP1

    lda #TITLE_P2_X
    sta HPOSP2

    lda #TITLE_P3_X
    sta HPOSP3

    ; Render "WBREW" on Player 0 (normal, no inversion)
    lda #<(PMG_P0 + TITLE_P0_Y)
    sta zp_pmg_dst
    lda #>(PMG_P0 + TITLE_P0_Y)
    sta zp_pmg_dst+1

    lda #<text_wbrew
    sta zp_pmg_src_text
    lda #>text_wbrew
    sta zp_pmg_src_text+1

    lda #TEXT_WBREW_LEN
    sta zp_pmg_len
    lda #TITLE_P0_MARGIN
    sta zp_pmg_margin
    lda #0
    sta zp_pmg_invert
    jsr pmg_render_text

    ; Render "SOBIE" on Player 1 (normal, no inversion)
    lda #<(PMG_P1 + TITLE_P1_Y)
    sta zp_pmg_dst
    lda #>(PMG_P1 + TITLE_P1_Y)
    sta zp_pmg_dst+1

    lda #<text_sobie
    sta zp_pmg_src_text
    lda #>text_sobie
    sta zp_pmg_src_text+1

    lda #TEXT_SOBIE_LEN
    sta zp_pmg_len
    lda #TITLE_P1_MARGIN
    sta zp_pmg_margin
    lda #0
    sta zp_pmg_invert
    jsr pmg_render_text

    ; Render "WBREW" on Player 2 (inwersja)
    lda #<(PMG_P2 + TITLE_P2_Y)
    sta zp_pmg_dst
    lda #>(PMG_P2 + TITLE_P2_Y)
    sta zp_pmg_dst+1

    lda #<text_wbrew
    sta zp_pmg_src_text
    lda #>text_wbrew
    sta zp_pmg_src_text+1

    lda #TEXT_WBREW_LEN
    sta zp_pmg_len
    lda #TITLE_P2_MARGIN
    sta zp_pmg_margin
    lda #$FF
    sta zp_pmg_invert
    jsr pmg_render_text

    ; Render "SOBIE" on Player 3 (inwersja)
    lda #<(PMG_P3 + TITLE_P3_Y)
    sta zp_pmg_dst
    lda #>(PMG_P3 + TITLE_P3_Y)
    sta zp_pmg_dst+1

    lda #<text_sobie
    sta zp_pmg_src_text
    lda #>text_sobie
    sta zp_pmg_src_text+1

    lda #TEXT_SOBIE_LEN
    sta zp_pmg_len
    lda #TITLE_P3_MARGIN
    sta zp_pmg_margin
    lda #$FF
    sta zp_pmg_invert
    jsr pmg_render_text

    ; 7. Configure Fifth Player (4 Missiles combined into 5th player)
    ; Enable 5th player bit in PRIOR / GPRIOR (bit 4 = $10)
    lda #$10
    sta GPRIOR
    sta PRIOR

    ; Set color for 5th player via COLPF3 / COLOR3
    lda #TITLE_P5_COLOR
    sta COLOR3
    sta COLPF3

    ; Set x1 width for all 4 missiles ($00 = %00000000)
    lda #TITLE_P5_SIZEM
    sta SIZEM

    ; Initialize wave phase and compute initial per-row X positions
    lda #0
    sta zp_p5_wave_phase
    jsr title_update_p5_wave

    ; Set initial horizontal position for 4 missiles placed side-by-side (2 color clocks each at 1x width)
    ; Missile 0 (bits 0,1) at X
    ; Missile 1 (bits 2,3) at X+2
    ; Missile 2 (bits 4,5) at X+4
    ; Missile 3 (bits 6,7) at X+6
    lda p5_row_x
    sta HPOSM0
    clc
    adc #2
    sta HPOSM1
    adc #2
    sta HPOSM2
    adc #2
    sta HPOSM3

    ; Render static normal (non-inverted) "PRESS FIRE TO START" into PMG_MISSILES ($3B00)
    ldx #0
@p5_copy_loop
    lda p5_text_data,x
    sta PMG_MISSILES + TITLE_P5_Y,x
    inx
    cpx #P5_TEXT_LEN
    bne @p5_copy_loop

    ; 8. Re-enable DMA ($3E = single-line PMG + playfield) and VBI + DLI interrupts ($C0)
    lda #$3E
    sta SDMCTL
    sta DMACTL
    lda #$C0
    sta NMIEN

    ; 9. Initialize and start title music playback
    ldx #<song_data
    ldy #>song_data
    jsr music_init
    jsr music_play
    rts
.endp

; --- Title Screen PMG Subtitle Character Indices (title_charset_2, base 46) ---
text_wbrew
    dta 101, 80, 96, 83, 101       ; W, B, R, E, W
TEXT_WBREW_LEN = 5

text_sobie
    dta 97, 93, 80, 87, 83         ; S, O, B, I, E
TEXT_SOBIE_LEN = 5

text_spaces
    dta 46, 46, 46, 46, 46         ; 5x [SPACE] dla podkładu P2 i P3
TEXT_SPACES_LEN = 5

.proc title_update
    ; Advance title music playback
    jsr music_update

    ; Keep top-of-frame DLI index and base charset synchronized every VBLANK
    lda #0
    sta zp_dli_idx
    lda #>title_charset_0
    sta CHBAS

    ; Advance 5th player sine-wave animation table
    jsr title_update_p5_wave

    ; Transition TITLE_SCREEN -> INTRO on FIRE press
    lda zp_fire_pressed
    beq @stay
    jsr music_stop
    lda #STATE_INTRO
    sta zp_next_state
@stay
    rts
.endp

; ------------------------------------------------------------------------------
; title_update_p5_wave — Computes per-row X offsets in p5_row_x[0..23]
; Uses 64-entry sine table (-20..+20) centered on TITLE_P5_X
; ------------------------------------------------------------------------------
.proc title_update_p5_wave
    clc
    lda zp_p5_wave_phase
    adc #TITLE_P5_WAVE_SPEED
    sta zp_p5_wave_phase
    tay                         ; Y holds running angle for row X
    ldx #0
@row_loop
    tya
    and #$3F
    tay
    lda p5_sin_table,y
    clc
    adc #TITLE_P5_X
    sta p5_row_x,x
    tya
    clc
    adc #TITLE_P5_WAVE_STEP
    tay
    inx
    cpx #24
    bne @row_loop
    rts
.endp

; Per-row horizontal base position (HPOSM0) updated each frame & read by DLI
p5_row_x
    :24 dta TITLE_P5_X

; 64-entry signed sine table with amplitude 20 (-20..+20)
p5_sin_table
    dta $00, $02, $04, $06, $08, $09, $0B, $0D, $0E, $0F, $11, $12, $12, $13, $14, $14
    dta $14, $14, $14, $13, $12, $12, $11, $0F, $0E, $0D, $0B, $09, $08, $06, $04, $02
    dta $00, $FE, $FC, $FA, $F8, $F7, $F5, $F3, $F2, $F1, $EF, $EE, $EE, $ED, $EC, $EC
    dta $EC, $EC, $EC, $ED, $EE, $EE, $EF, $F1, $F2, $F3, $F5, $F7, $F8, $FA, $FC, $FE

; --- Precompiled 1-byte per scanline bitmap for "PRESS FIRE TO START" ---
; 19 characters * (1 blank badline row + 7 font rows) = 152 bytes (8 lines/char, aligned to Mode 4 rows)
; Mapped to Fifth Player hardware missile bit layout:
; M0 (leftmost) takes bits 1 (left) and 0 (right)
; M1 takes bits 3 (left) and 2 (right)
; M2 takes bits 5 (left) and 4 (right)
; M3 (rightmost) takes bits 7 (left) and 6 (right)
P5_TEXT_LEN = 152
p5_text_data
    dta $00, $3F, $93, $93, $3F, $03, $03, $03 ; P
    dta $00, $3F, $93, $93, $3F, $27, $33, $93 ; R
    dta $00, $BF, $03, $03, $BF, $03, $03, $BF ; E
    dta $00, $BD, $03, $09, $2C, $30, $90, $3F ; S
    dta $00, $BD, $03, $09, $2C, $30, $90, $3F ; S
    dta $00, $00, $00, $00, $00, $00, $00, $00 ;  
    dta $00, $BF, $03, $03, $BF, $03, $03, $03 ; F
    dta $00, $24, $24, $24, $24, $24, $24, $24 ; I
    dta $00, $3F, $93, $93, $3F, $27, $33, $93 ; R
    dta $00, $BF, $03, $03, $BF, $03, $03, $BF ; E
    dta $00, $00, $00, $00, $00, $00, $00, $00 ;  
    dta $00, $FF, $24, $24, $24, $24, $24, $24 ; T
    dta $00, $2C, $39, $93, $93, $93, $39, $2C ; O
    dta $00, $00, $00, $00, $00, $00, $00, $00 ;  
    dta $00, $BD, $03, $09, $2C, $30, $90, $3F ; S
    dta $00, $FF, $24, $24, $24, $24, $24, $24 ; T
    dta $00, $04, $2C, $2C, $39, $3D, $93, $93 ; A
    dta $00, $3F, $93, $93, $3F, $27, $33, $93 ; R
    dta $00, $FF, $24, $24, $24, $24, $24, $24 ; T


