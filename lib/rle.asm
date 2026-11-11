; ==============================================================================
; LIB/RLE.ASM — Run-Length Encoding Decompressor (MOS 6502)
; Format:
;   - Control byte = $00 -> End of stream
;   - Control byte bit 0 = 1 -> Literal run of ((ctrl >> 1) + 1) raw bytes
;   - Control byte bit 0 = 0 -> Repeat run of ((ctrl >> 1) + 1) copies of next byte
; Inputs:
;   - zp_rle_src ($88-$89): Pointer to compressed RLE stream
;   - zp_rle_dst ($8A-$8B): Pointer to destination buffer
; ==============================================================================

.proc rle_decompress
    ldy #0                  ; 2  (2) Y = 0 for indirect indexed addressing
@next_packet
    jsr @get_byte           ; 6  (8) Fetch control byte
    beq @done               ; 2/3(10) $00 terminates stream
    lsr                     ; 2  (12) C = packet type (1=literal, 0=repeat), A = count - 1
    sta zp_rle_cnt          ; 3  (15) Store count - 1
    bcc @repeat_run         ; 2/3(17) Bit 0 == 0 -> repeat run

@literal_loop
    jsr @get_byte           ; 6  Fetch next literal byte
    jsr @put_byte           ; 6  Store to output buffer
    dec zp_rle_cnt          ; 5  Decrement remaining count
    bpl @literal_loop       ; 2/3 Loop while count >= 0
    jmp @next_packet        ; 3  Next control byte

@repeat_run
    jsr @get_byte           ; 6  Fetch repeated byte value
@repeat_loop
    jsr @put_byte           ; 6  Store repeated byte to output (preserves A)
    dec zp_rle_cnt          ; 5  Decrement remaining count
    bpl @repeat_loop        ; 2/3 Loop while count >= 0
    jmp @next_packet        ; 3  Next control byte

@done
    rts                     ; 6  Return

@get_byte
    lda (zp_rle_src),y      ; 5  Read byte from source stream
    pha                     ; 3  Preserve A and its value while incrementing pointer
    inc zp_rle_src          ; 5  Advance low byte of source pointer
    bne @get_ok             ; 2/3
    inc zp_rle_src+1        ; 5  Advance high byte on page crossing
@get_ok
    pla                     ; 4  Restore byte into A (sets N and Z flags!)
    rts                     ; 6

@put_byte
    sta (zp_rle_dst),y      ; 6  Write byte to destination buffer
    inc zp_rle_dst          ; 5  Advance low byte of destination pointer
    bne @put_ok             ; 2/3
    inc zp_rle_dst+1        ; 5  Advance high byte on page crossing
@put_ok
    rts                     ; 6
.endp

