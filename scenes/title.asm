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

    ; Set horizontal position for 4 missiles placed side-by-side (2 color clocks each at 1x width)
    ; Missile 0 (bits 0,1) at X
    ; Missile 1 (bits 2,3) at X+2
    ; Missile 2 (bits 4,5) at X+4
    ; Missile 3 (bits 6,7) at X+6
    lda #TITLE_P5_X
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
    ; Keep top-of-frame DLI index and base charset synchronized every VBLANK
    lda #0
    sta zp_dli_idx
    lda #>title_charset_0
    sta CHBAS

    ; Transition TITLE_SCREEN -> GAME on FIRE press
    lda zp_fire_pressed
    beq @stay
    lda #STATE_GAME
    sta zp_next_state
@stay
    rts
.endp

; --- Precompiled 1-byte per scanline bitmap for "PRESS FIRE TO START" ---
; 19 characters * (8 font rows + 2 blank rows) = 190 bytes
; Mapped to Fifth Player hardware missile bit layout:
; M0 (leftmost) takes bits 1 (left) and 0 (right)
; M1 takes bits 3 (left) and 2 (right)
; M2 takes bits 5 (left) and 4 (right)
; M3 (rightmost) takes bits 7 (left) and 6 (right)
P5_TEXT_LEN = 190
p5_text_data
    dta $3F, $93, $93, $3F, $03, $03, $03, $00, $00, $00 ; P
    dta $3F, $93, $93, $3F, $27, $33, $93, $00, $00, $00 ; R
    dta $BF, $03, $03, $BF, $03, $03, $BF, $00, $00, $00 ; E
    dta $BD, $03, $09, $2C, $30, $90, $3F, $00, $00, $00 ; S
    dta $BD, $03, $09, $2C, $30, $90, $3F, $00, $00, $00 ; S
    dta $00, $00, $00, $00, $00, $00, $00, $00, $00, $00 ;  
    dta $BF, $03, $03, $BF, $03, $03, $03, $00, $00, $00 ; F
    dta $24, $24, $24, $24, $24, $24, $24, $00, $00, $00 ; I
    dta $3F, $93, $93, $3F, $27, $33, $93, $00, $00, $00 ; R
    dta $BF, $03, $03, $BF, $03, $03, $BF, $00, $00, $00 ; E
    dta $00, $00, $00, $00, $00, $00, $00, $00, $00, $00 ;  
    dta $FF, $24, $24, $24, $24, $24, $24, $00, $00, $00 ; T
    dta $2C, $39, $93, $93, $93, $39, $2C, $00, $00, $00 ; O
    dta $00, $00, $00, $00, $00, $00, $00, $00, $00, $00 ;  
    dta $BD, $03, $09, $2C, $30, $90, $3F, $00, $00, $00 ; S
    dta $FF, $24, $24, $24, $24, $24, $24, $00, $00, $00 ; T
    dta $04, $2C, $2C, $39, $3D, $93, $93, $00, $00, $00 ; A
    dta $3F, $93, $93, $3F, $27, $33, $93, $00, $00, $00 ; R
    dta $FF, $24, $24, $24, $24, $24, $24, $00, $00, $00 ; T


