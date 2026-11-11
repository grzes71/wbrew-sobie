; ==============================================================================
; ENGINE/INPUT.ASM — Joystick 0 & Console Button Polling
; ==============================================================================

.proc input_init
    lda #1
    sta zp_trig_curr
    sta zp_trig_prev
    lda #0
    sta zp_fire_pressed
    lda #$0F
    sta zp_joy_curr
    rts
.endp

.proc input_poll
    ; Clear attract mode so OS never scrambles colors after idle timeout
    lda #0
    sta ATRACT

    ; Read Joystick 0 directions (bits 0..3: 0 = pressed)
    lda PORTA
    and #$0F
    sta zp_joy_curr

    ; Preserve previous trigger state
    lda zp_trig_curr
    sta zp_trig_prev

    ; Read Joystick 0 FIRE (TRIG0 bit 0: 0 = pressed, 1 = released)
    lda TRIG0
    and #$01
    sta zp_trig_curr

    ; Edge detection: fire_pressed = 1 iff prev == 1 (released) and curr == 0 (pressed)
    lda #0
    sta zp_fire_pressed
    lda zp_trig_prev
    beq @done               ; Was already held last frame
    lda zp_trig_curr
    bne @done               ; Still not pressed
    lda #1
    sta zp_fire_pressed
@done
    rts
.endp

