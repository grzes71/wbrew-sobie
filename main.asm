; ==============================================================================
; MAIN.ASM — Funky Koval - Wbrew Sobie (Atari 800XL / 65XE)
; Entry point, Frame Scheduler, and Game State Machine
; ==============================================================================

    icl 'hardware.asm'
    icl 'colors.asm'
    icl 'zeropage.asm'

; --- Game State Machine Constants ---
STATE_TITLE_SCREEN      = 0
STATE_GAME              = 1
STATE_GAME_OVER_FAILURE = 2
STATE_GAME_OVER_SUCCESS = 3
STATE_GAME_OVER         = STATE_GAME_OVER_FAILURE
STATE_COUNT             = 4
STATE_NONE              = $FF

; --- Memory Map Constants ---
SCREEN_VRAM             = $3000     ; 40x24 screen buffer (960 bytes: $3000..$33BF)
PMG_BASE                = $3800     ; 2 KB PMG single-line buffer ($3800..$3FFF)
PMG_MISSILES            = PMG_BASE + $300 ; Missiles buffer ($3B00..$3BFF)
PMG_P0                  = PMG_BASE + $400 ; Player 0 buffer ($3C00..$3CFF)
PMG_P1                  = PMG_BASE + $500 ; Player 1 buffer ($3D00..$3DFF)
PMG_P2                  = PMG_BASE + $600 ; Player 2 buffer ($3E00..$3EFF)
PMG_P3                  = PMG_BASE + $700 ; Player 3 buffer ($3F00..$3FFF)

; ==============================================================================
; Code & Engine Segment ($2000)
; ==============================================================================
    org $2000

.proc main
    cld
    jsr state_machine_init

@frame_loop
    jsr wait_frame
    jsr state_machine_step
    jmp @frame_loop
.endp

; ------------------------------------------------------------------------------
; wait_frame — Synchronizes execution to the start of the next VBLANK interval
; ------------------------------------------------------------------------------
.proc wait_frame
    lda RTCLOK+2
@wait_tick
    cmp RTCLOK+2
    beq @wait_tick
    lda RTCLOK+2
    sta zp_last_rtclok
    rts
.endp

; ------------------------------------------------------------------------------
; state_machine_init — Initializes input and schedules initial state
; ------------------------------------------------------------------------------
.proc state_machine_init
    jsr input_init
    lda #STATE_NONE
    sta zp_current_state
    lda #STATE_TITLE_SCREEN
    sta zp_next_state
    jsr process_state_transition
    rts
.endp

; ------------------------------------------------------------------------------
; state_machine_step — Executes one deterministic frame update
; Order: 1. Input Poll -> 2. State Update -> 3. State Transition Commit
; ------------------------------------------------------------------------------
.proc state_machine_step
    jsr input_poll
    jsr process_state_transition
    jsr dispatch_state_update
    jsr process_state_transition
    rts
.endp

; ------------------------------------------------------------------------------
; process_state_transition — Handles pending zp_next_state transition if any
; ------------------------------------------------------------------------------
.proc process_state_transition
    lda zp_next_state
    bmi @no_change          ; $FF (STATE_NONE) means no pending transition
    cmp #STATE_COUNT
    bcs @clear_invalid

    sta zp_current_state
    lda #STATE_NONE
    sta zp_next_state
    jsr dispatch_state_enter
    rts

@clear_invalid
    lda #STATE_NONE
    sta zp_next_state
@no_change
    rts
.endp

; ------------------------------------------------------------------------------
; dispatch_state_enter — Calls the enter routine for zp_current_state
; ------------------------------------------------------------------------------
.proc dispatch_state_enter
    ldx zp_current_state
    lda state_enter_lo,x
    sta @jmp_vec+1
    lda state_enter_hi,x
    sta @jmp_vec+2
@jmp_vec
    jmp $FFFF
.endp

; ------------------------------------------------------------------------------
; dispatch_state_update — Calls the per-frame update routine for zp_current_state
; ------------------------------------------------------------------------------
.proc dispatch_state_update
    ldx zp_current_state
    lda state_update_lo,x
    sta @jmp_vec+1
    lda state_update_hi,x
    sta @jmp_vec+2
@jmp_vec
    jmp $FFFF
.endp

; --- State Machine Jump Tables (SoA) ---
state_enter_lo
    dta <title_enter, <game_enter, <gameover_failure_enter, <gameover_success_enter
state_enter_hi
    dta >title_enter, >game_enter, >gameover_failure_enter, >gameover_success_enter

state_update_lo
    dta <title_update, <game_update, <gameover_failure_update, <gameover_success_update
state_update_hi
    dta >title_update, >game_update, >gameover_failure_update, >gameover_success_update

; --- Core Libraries, Engine & Scenes ---
    icl 'lib/rle.asm'
    icl 'lib/pmg.asm'
    icl 'engine/input.asm'
    icl 'engine/dli.asm'
    icl 'scenes/title.asm'
    icl 'scenes/game.asm'
    icl 'scenes/gameover.asm'

; --- Auto-generated Title Screen Data, Display Lists ($3400) & Charsets ($4000) ---
    icl 'gen/title_screen_data.asm'

; --- DOS Binary Run Address ---
    run main

