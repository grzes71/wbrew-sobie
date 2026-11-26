; ==============================================================================
; SCENES/INTRO.ASM — Intro Typewriter State (STATE_INTRO)
; Mode: ANTIC Mode 2 (40x10 text rows separated by DL_BLANK8, reusing SCREEN_VRAM)
; Charset: title_charset_2 (glyph offset 46 = SPACE, Polish uppercase 111..119)
; ==============================================================================

INTRO_CHAR_DELAY    = 3         ; Frames between revealed characters (50 Hz PAL)

; --- ANTIC Mode 2 Intro Display List (29 bytes, 1 KB aligned) ---
    .align $20
intro_dlist
    dta DL_BLANK8, DL_BLANK8, DL_BLANK8, DL_BLANK8, DL_BLANK8
    dta DL_MODE_2 | DL_LMS, a(SCREEN_VRAM)
    :9 dta DL_BLANK8, DL_MODE_2
    dta DL_JVB, a(intro_dlist)
INTRO_DLIST_LEN     = * - intro_dlist

    .if ((intro_dlist) & $FC00) <> ((intro_dlist + INTRO_DLIST_LEN - 1) & $FC00)
        .error 'intro_dlist crosses 1KB ANTIC Display List boundary'
    .endif

; --- Precomputed 10-entry Row Start Address Tables (SoA) ---
intro_src_lo
    :INTRO_LINES dta <(intro_screen_data + # * INTRO_COLS)
intro_src_hi
    :INTRO_LINES dta >(intro_screen_data + # * INTRO_COLS)

intro_dst_lo
    :INTRO_LINES dta <(SCREEN_VRAM + # * INTRO_COLS)
intro_dst_hi
    :INTRO_LINES dta >(SCREEN_VRAM + # * INTRO_COLS)

; ------------------------------------------------------------------------------
; intro_clear_vram — Fills 400 bytes of SCREEN_VRAM ($3000..$318F) with SPACE
; ------------------------------------------------------------------------------
.proc intro_clear_vram
    lda #INTRO_SPACE_CODE
    ldx #0
@loop_lo
    sta SCREEN_VRAM,x
    inx
    bne @loop_lo
@loop_hi
    sta SCREEN_VRAM + $0100,x
    inx
    cpx #(INTRO_VRAM_SIZE - 256)
    bne @loop_hi
    rts
.endp

; ------------------------------------------------------------------------------
; intro_show_all — Copies all 400 bytes of intro text and silences key SFX
; ------------------------------------------------------------------------------
.proc intro_show_all
    ldx #0
@copy_lo
    lda intro_screen_data,x
    sta SCREEN_VRAM,x
    inx
    bne @copy_lo
@copy_hi
    lda intro_screen_data + $0100,x
    sta SCREEN_VRAM + $0100,x
    inx
    cpx #(INTRO_VRAM_SIZE - 256)
    bne @copy_hi

    lda #0
    sta AUDC1
    sta zp_intro_sfx_timer
    sta zp_intro_col
    lda #INTRO_LINES
    sta zp_intro_row
    lda #1
    sta zp_intro_done
    rts
.endp

; ------------------------------------------------------------------------------
; intro_sfx_tick — Decays POKEY Ch1 mechanical typewriter key click
; ------------------------------------------------------------------------------
.proc intro_sfx_tick
    lda zp_intro_sfx_timer
    beq @done
    dec zp_intro_sfx_timer
    beq @silence
    lda #$81                    ; Soft 1-frame noise tail
    sta AUDC1
    rts
@silence
    lda #0
    sta AUDC1
@done
    rts
.endp

; ------------------------------------------------------------------------------
; intro_enter — Initializes ANTIC Mode 2 intro screen and typewriter state
; ------------------------------------------------------------------------------
.proc intro_enter
    ; 1. Disable DLI and display DMA during screen setup
    lda #$40
    sta NMIEN
    lda #0
    sta SDMCTL
    sta DMACTL
    sta zp_anim_active
    sta zp_anim_pending

    ; 2. Silence POKEY & disable PMG inherited from Title Screen
    sta AUDCTL
    sta AUDF1
    sta AUDC1
    sta AUDF2
    sta AUDC2
    sta AUDF3
    sta AUDC3
    sta AUDF4
    sta AUDC4
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

    lda #$03
    sta SKCTL                   ; Ensure POKEY poly counters run for noise clicks

    ; 3. Set ANTIC 2 colors (black border & char cell background, bright text)
    lda #INTRO_COLBK
    sta COLOR4
    sta COLBK
    lda #INTRO_COLPF2
    sta COLOR2
    sta COLPF2
    lda #INTRO_COLPF1
    sta COLOR1
    sta COLPF1

    ; 4. Clear 400 bytes of SCREEN_VRAM to SPACE (code 46)
    jsr intro_clear_vram

    ; 5. Point charset to title_charset_2 (glyphs 46..127 from fonts/font.fnt)
    lda #>title_charset_2
    sta CHBAS
    sta CHBASE

    ; 6. Install intro Display List
    lda #<intro_dlist
    sta SDLSTL
    sta DLISTL
    lda #>intro_dlist
    sta SDLSTH
    sta DLISTH

    ; 7. Reset typewriter & skip state (start at line 0 centered column)
    lda #0
    sta zp_intro_row
    sta zp_intro_sfx_timer
    sta zp_intro_done
    sta zp_intro_wait_rel
    lda intro_line_start
    sta zp_intro_col
    lda #1
    sta zp_intro_timer

    ; 8. Re-enable normal playfield DMA ($22) and VBI only ($40)
    lda #$22
    sta SDMCTL
    sta DMACTL
    lda #$40
    sta NMIEN
    rts
.endp

; ------------------------------------------------------------------------------
; intro_update — Advances typewriter reveal, plays key click, and handles FIRE
; ------------------------------------------------------------------------------
.proc intro_update
    lda zp_intro_done
    beq @typing_phase

    ; --- Text is fully displayed: keep decaying any final key click ---
    jsr intro_sfx_tick

    lda zp_intro_wait_rel
    beq @wait_next_fire
    lda zp_trig_curr
    beq @stay                   ; Still holding skip FIRE -> keep waiting
    lda #0
    sta zp_intro_wait_rel       ; FIRE released; arm transition for next press
    rts

@wait_next_fire
    lda zp_fire_pressed
    beq @stay
    lda #0
    sta AUDC1
    sta zp_intro_sfx_timer
    lda #STATE_GAME
    sta zp_next_state
@stay
    rts

@typing_phase
    ; Skip animation immediately on new FIRE press (before any sfx tick)
    lda zp_fire_pressed
    beq @type_tick
    jsr intro_show_all
    lda #1
    sta zp_intro_wait_rel
    rts

@type_tick
    jsr intro_sfx_tick
    dec zp_intro_timer
    bne @type_done
    lda #INTRO_CHAR_DELAY
    sta zp_intro_timer

@find_row
    ldx zp_intro_row
    cpx #INTRO_LINES
    bcs @mark_finished
    lda intro_line_end,x
    bne @reveal_char            ; Non-blank line found
    inc zp_intro_row            ; Skip blank line silently without sound
    ldx zp_intro_row
    cpx #INTRO_LINES
    bcs @mark_finished
    lda intro_line_start,x
    sta zp_intro_col
    jmp @find_row

@reveal_char
    lda intro_src_lo,x
    sta zp_intro_src
    lda intro_src_hi,x
    sta zp_intro_src+1
    lda intro_dst_lo,x
    sta zp_intro_dst
    lda intro_dst_hi,x
    sta zp_intro_dst+1

    ldy zp_intro_col
    lda (zp_intro_src),y
    sta (zp_intro_dst),y

    cmp #INTRO_SPACE_CODE
    beq @advance_cursor         ; Silent on space characters

    ; Short subtle mechanical typewriter key click on POKEY Ch1
    lda zp_intro_col
    and #$03
    clc
    adc #$0E
    sta AUDF1
    lda #$84                    ; Poly noise ($80) + low volume (4)
    sta AUDC1
    lda #2
    sta zp_intro_sfx_timer

@advance_cursor
    inc zp_intro_col
    lda zp_intro_col
    ldx zp_intro_row
    cmp intro_line_end,x
    bcc @type_done

    inc zp_intro_row

@skip_trailing_blank
    ldx zp_intro_row
    cpx #INTRO_LINES
    bcs @mark_finished
    lda intro_line_end,x
    bne @set_next_col
    inc zp_intro_row
    jmp @skip_trailing_blank

@set_next_col
    lda intro_line_start,x
    sta zp_intro_col
    rts

@mark_finished
    lda #1
    sta zp_intro_done
    lda zp_trig_curr
    bne @type_done
    lda #1
    sta zp_intro_wait_rel
@type_done
    rts
.endp
