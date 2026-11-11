; ==============================================================================
; LIB/PMG.ASM — Player-Missile Graphics Helpers & Text Renderer (Single-Line 2KB)
; ==============================================================================

; PMG buffer size for single-line resolution (2 KB):
;   Missiles: 256 bytes (+$300..+$3FF)
;   Player 0: 256 bytes (+$400..+$4FF)
;   Player 1: 256 bytes (+$500..+$5FF)
;   Player 2: 256 bytes (+$600..+$6FF)
;   Player 3: 256 bytes (+$700..+$7FF)
; Total: 2048 bytes ($0000..$07FF relative to PMG_BASE)

.proc pmg_clear
    lda #0
    tax
@loop
    sta PMG_BASE + $0000,x
    sta PMG_BASE + $0100,x
    sta PMG_BASE + $0200,x
    sta PMG_BASE + $0300,x
    sta PMG_BASE + $0400,x
    sta PMG_BASE + $0500,x
    sta PMG_BASE + $0600,x
    sta PMG_BASE + $0700,x
    inx
    bne @loop
    rts
.endp

.proc pmg_init_single_line
    ; PMBASE requires page number of 2KB-aligned buffer (bits 3..7)
    lda #>PMG_BASE
    sta PMBASE

    ; Enable Players & Missiles DMA with 1-line resolution (SDMCTL bit 4 = 1)
    ; GRACTL: bit 1 = players, bit 0 = missiles ($03 = enable both)
    lda #$03
    sta GRACTL

    ; Set width for players (0=1x, 1=2x, 3=4x width)
    lda #0
    sta SIZEM

    ; Players size configuration (from colors.asm)
    lda #TITLE_P0_SIZE
    sta SIZEP0
    lda #TITLE_P1_SIZE
    sta SIZEP1
    lda #TITLE_P2_SIZE
    sta SIZEP2
    lda #TITLE_P3_SIZE
    sta SIZEP3
    rts
.endp

; ------------------------------------------------------------------------------
; pmg_render_text — Renders vertical text onto a specified Player's buffer
; Each glyph row is written 4 times into the single-line PMG buffer (4 bytes = 4 scanlines)
; to match the 4x horizontal hardware player width for an exact 1:1 square pixel aspect ratio.
; Each 8-row glyph produces 32 PMG bytes (32 scanlines).
; Inputs:
;   - zp_pmg_dst      ($8E-$8F): destination pointer in PMG buffer (e.g. PMG_P1 + Y_start)
;   - zp_pmg_src_text ($90-$91): pointer to array of charset glyph indices
;   - zp_pmg_len      ($94)    : number of characters to render
;   - zp_pmg_margin   ($95)    : margin in scanlines between characters (e.g. TITLE_P0_MARGIN)
; Font source:
;   - Title charset 2 base address is title_charset_2 ($4800)
;   - Each glyph is 8 bytes in font: address = title_charset_2 + (glyph_index * 8)
; ------------------------------------------------------------------------------
.proc pmg_render_text
    lda #0
    sta @char_idx           ; Initialize character counter to 0

@char_loop
    lda @char_idx
    cmp zp_pmg_len
    bcs @done

    ; Get character glyph index from text array
    tay
    lda (zp_pmg_src_text),y ; A = glyph index in charset 2

    ; Compute glyph address in font: title_charset_2 ($4800) + A * 8
    sta zp_pmg_char_ptr     ; temporarily save A
    lda #0
    sta zp_pmg_char_ptr+1

    ; Multiply 16-bit by 8
    asl zp_pmg_char_ptr
    rol zp_pmg_char_ptr+1
    asl zp_pmg_char_ptr
    rol zp_pmg_char_ptr+1
    asl zp_pmg_char_ptr
    rol zp_pmg_char_ptr+1

    ; Add base address of title_charset_2
    clc
    lda zp_pmg_char_ptr
    adc #<title_charset_2
    sta zp_pmg_char_ptr
    lda zp_pmg_char_ptr+1
    adc #>title_charset_2
    sta zp_pmg_char_ptr+1

    ; Copy 8 rows of glyph into PMG player buffer, quadrupling each row (4 bytes per row)
    ldy #0                  ; Y = source glyph row index (0..7)
    ldx #0                  ; X = destination buffer offset (0..31)

@copy_glyph_rows
    lda (zp_pmg_char_ptr),y
    pha                     ; Save glyph row byte
    txa
    tay                     ; Y = destination buffer offset
    pla                     ; A = glyph row byte
    sta (zp_pmg_dst),y      ; Byte 1
    iny
    sta (zp_pmg_dst),y      ; Byte 2
    iny
    sta (zp_pmg_dst),y      ; Byte 3
    iny
    sta (zp_pmg_dst),y      ; Byte 4
    iny
    tya
    tax                     ; X = updated destination offset
    inc @src_row_idx        ; advance source row index
    ldy @src_row_idx
    cpy #8
    bcc @copy_glyph_rows

    ; Advance destination pointer in player buffer by 32 bytes (8 rows * 4) + zp_pmg_margin
    clc
    lda zp_pmg_dst
    adc #32
    adc zp_pmg_margin
    sta zp_pmg_dst
    lda zp_pmg_dst+1
    adc #0
    sta zp_pmg_dst+1

    lda #0
    sta @src_row_idx
    inc @char_idx
    jmp @char_loop

@done
    rts

@src_row_idx
    dta 0
@char_idx
    dta 0
.endp

