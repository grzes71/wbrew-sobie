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

    ; Set horizontal position for 4 missiles placed side-by-side (2 color clocks each)
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

    ; Initialize scroller position: start scrolling from bottom of screen (pos = 0)
    lda #0
    sta zp_scroller_pos
    sta zp_scroller_pos+1
    sta zp_scroller_speed_cnt

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

    ; Animate Fifth Player scroller (PRESS FIRE TO START)
    jsr title_update_scroller

    ; Transition TITLE_SCREEN -> GAME on FIRE press
    lda zp_fire_pressed
    beq @stay
    lda #STATE_GAME
    sta zp_next_state
@stay
    rts
.endp

; ------------------------------------------------------------------------------
; title_update_scroller — Advances vertical scroll position of 5th player text
; and copies the visible window into PMG_MISSILES ($3B00)
; Visible screen scanline range: ~32..223 (192 scanlines)
; ------------------------------------------------------------------------------
SCROLLER_TEXT_LEN = 190
SCROLLER_TOTAL_RANGE = 192 + SCROLLER_TEXT_LEN ; 382 scanlines per cycle

.proc title_update_scroller
    ; 1. Clear 192 active scanlines of missiles buffer ($3B00 + 32 .. $3B00 + 223)
    lda #0
    ldx #32
@clear_loop
    sta PMG_MISSILES,x
    inx
    cpx #224
    bne @clear_loop

    ; 2. Advance scroll position by TITLE_P5_SCROLL_SPEED
    clc
    lda zp_scroller_pos
    adc #TITLE_P5_SCROLL_SPEED
    sta zp_scroller_pos
    lda zp_scroller_pos+1
    adc #0
    sta zp_scroller_pos+1

    ; Wrap around when zp_scroller_pos >= SCROLLER_TOTAL_RANGE
    sec
    lda zp_scroller_pos
    sbc #<SCROLLER_TOTAL_RANGE
    lda zp_scroller_pos+1
    sbc #>SCROLLER_TOTAL_RANGE
    bcc @pos_ok

    ; Wrap back to 0
    lda #0
    sta zp_scroller_pos
    sta zp_scroller_pos+1

@pos_ok
    ; 3. Render visible slice of scroller text into PMG_MISSILES
    ; For text byte i in 0..SCROLLER_TEXT_LEN-1:
    ; Screen Y = 224 - zp_scroller_pos + i
    ; If Y >= 32 and Y < 224:
    ;   PMG_MISSILES[Y] = scroller_text_data[i]
    ; Let's iterate over visible screen scanlines Y from 32 to 223:
    ; i = Y + zp_scroller_pos - 224
    ; If 0 <= i < SCROLLER_TEXT_LEN:
    ;   PMG_MISSILES[Y] = scroller_text_data[i]
    ldx #32                     ; X = screen scanline Y (32..223)
@scanline_loop
    ; Calculate 16-bit offset: i = X + zp_scroller_pos - 224
    txa
    clc
    adc zp_scroller_pos
    sta @temp_lo
    lda zp_scroller_pos+1
    adc #0
    sta @temp_hi

    ; Subtract 224
    sec
    lda @temp_lo
    sbc #224
    sta @temp_lo
    lda @temp_hi
    sbc #0
    sta @temp_hi

    ; Check if i >= 0 (temp_hi must be 0)
    bmi @next_scanline
    bne @next_scanline          ; if temp_hi > 0, i >= 256 > SCROLLER_TEXT_LEN
    lda @temp_lo
    cmp #SCROLLER_TEXT_LEN
    bcs @next_scanline

    ; Valid index in scroller_text_data!
    tay
    lda scroller_text_data,y
    sta PMG_MISSILES,x

@next_scanline
    inx
    cpx #224
    bne @scanline_loop
    rts

@temp_lo
    dta 0
@temp_hi
    dta 0
.endp

; --- Precompiled 1-byte per scanline bitmap for "PRESS FIRE TO START" ---
; 19 characters * (8 font rows + 2 blank rows) = 190 bytes
; Mapped to Fifth Player hardware missile bit layout:
; M0 (leftmost) takes bits 1 (left) and 0 (right)
; M1 takes bits 3 (left) and 2 (right)
; M2 takes bits 5 (left) and 4 (right)
; M3 (rightmost) takes bits 7 (left) and 6 (right)
scroller_text_data
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


