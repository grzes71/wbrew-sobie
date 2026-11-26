; ==============================================================================
; MAIN.ASM — Funky Koval - Wbrew Sobie (Atari 800XL / 65XE)
; Entry point, Frame Scheduler, and Game State Machine
; ==============================================================================

    icl 'hardware.asm'
    icl 'colors.asm'
    icl 'zeropage.asm'
    icl 'gen/rooms_defs.asm'
    icl 'gen/hero_defs.asm'

; --- Game State Machine Constants ---
STATE_TITLE_SCREEN      = 0
STATE_INTRO             = 1
STATE_GAME              = 2
STATE_GAME_OVER_FAILURE = 3
STATE_GAME_OVER_SUCCESS = 4
STATE_GAME_OVER         = STATE_GAME_OVER_FAILURE
STATE_COUNT             = 5
STATE_NONE              = $FF

; --- Memory Map Constants ---
SCREEN_VRAM             = $3000     ; 40x24 screen buffer (960 bytes: $3000..$33BF)
room_dlist              = $3480     ; Dynamic room Display List (32 bytes: $3480..$349F)
cur_row_style           = $34A0     ; Active room per-row style cache (24 bytes: $34A0..$34B7)
room_dli_style          = $34C0     ; Target style ID per DLI transition (24 bytes: $34C0..$34D7)
room_dli_count          = $34D8     ; Active DLI count for current room (0..23)
cur_room_id             = $34D9     ; Currently active room ID (1..ROOM_MAX_ID)

; --- Room Animation Runtime State ($34E0+, below PMG_BASE=$3800) ---
    .if MAX_ROOM_ANIMS > 0
ANIM_STATE_CAP          = MAX_ROOM_ANIMS
    .else
ANIM_STATE_CAP          = 1
    .endif
    .if MAX_ROOM_FORM1_SLOTS > 0
ANIM_SLOT_CAP           = MAX_ROOM_FORM1_SLOTS
    .else
ANIM_SLOT_CAP           = 1
    .endif

anim_room_count         = $34E0                             ; 1 B: active animated objs
anim_st_id              = anim_room_count + 1               ; ANIM_STATE_CAP B
anim_st_cnt             = anim_st_id + ANIM_STATE_CAP       ; ANIM_STATE_CAP B
anim_st_frame           = anim_st_cnt + ANIM_STATE_CAP      ; ANIM_STATE_CAP B
anim_st_vis             = anim_st_frame + ANIM_STATE_CAP    ; ANIM_STATE_CAP B (Form 2 applied frame)
anim_st_pend            = anim_st_vis + ANIM_STATE_CAP      ; ANIM_STATE_CAP B
anim_st_pos             = anim_st_pend + ANIM_STATE_CAP     ; ANIM_STATE_CAP B (slot / delta pair cursor)
anim_st_sbase           = anim_st_pos + ANIM_STATE_CAP      ; ANIM_STATE_CAP B (Form 1 offset in slot_cur)
anim_st_rep             = anim_st_sbase + ANIM_STATE_CAP    ; ANIM_STATE_CAP B (group pass counter)
    .if ANIM_F2_GRP_COUNT > 0
anim_st_vrep            = anim_st_rep + ANIM_STATE_CAP      ; ANIM_STATE_CAP B (Form 2 visible pass counter)
anim_slot_cur           = anim_st_vrep + ANIM_STATE_CAP     ; ANIM_SLOT_CAP B (Form 1 last pat_idx)
    .else
anim_slot_cur           = anim_st_rep + ANIM_STATE_CAP      ; ANIM_SLOT_CAP B (Form 1 last pat_idx)
    .endif
    .ifdef ANIM_COUNT_COPIES
anim_copy_count         = anim_slot_cur + ANIM_SLOT_CAP     ; 1 B: per-tick copy telemetry
ANIM_RAM_END            = anim_copy_count + 1
    .else
ANIM_RAM_END            = anim_slot_cur + ANIM_SLOT_CAP
    .endif
room_block_map          = $3700                             ; 120 B ($3700..$3777): 40x24 cell blocking bitmap
    .if ANIM_RAM_END > room_block_map
        .error "Animation state RAM overflows into room_block_map ($3700)!"
    .endif

PMG_BASE                = $3800     ; 2 KB PMG single-line buffer ($3800..$3FFF)
    .if (PMG_BASE & $07FF) <> 0
        .error "PMG_BASE must be 2 KB aligned for single-line resolution!"
    .endif
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
    lda #0
    sta zp_anim_active
    sta zp_anim_pending
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
    dta <title_enter, <intro_enter, <game_enter, <gameover_failure_enter, <gameover_success_enter
state_enter_hi
    dta >title_enter, >intro_enter, >game_enter, >gameover_failure_enter, >gameover_success_enter

state_update_lo
    dta <title_update, <intro_update, <game_update, <gameover_failure_update, <gameover_success_update
state_update_hi
    dta >title_update, >intro_update, >game_update, >gameover_failure_update, >gameover_success_update

; --- Core Libraries, Title Engine & Title Scene ($2000) ---
    icl 'lib/rle.asm'
    icl 'lib/pmg.asm'
    icl 'engine/input.asm'
    icl 'engine/dli.asm'
    icl 'scenes/title.asm'

    .if * >= SCREEN_VRAM
        .error "$2000 segment overflows into SCREEN_VRAM ($3000)!"
    .endif

; --- Auto-generated Title Screen Data, Display Lists ($3400) & Charsets ($4000) ---
    icl 'gen/title_screen_data.asm'

; --- Audio Player and Title Music Data Segment ($5000) ---
    org $5000
    icl 'lib/player.asm'
    icl 'gen/title_music.asm'

; --- Room Charsets (1 KB aligned at $6000), Compiled Data & Gameplay Engine ---
ROOMS_ALIGN_CHARSETS = 1
    org $6000
    icl 'gen/charsets.asm'
    icl 'gen/styles.asm'
    icl 'gen/objects.asm'
    icl 'gen/rooms.asm'
    icl 'gen/teleports.asm'
    icl 'gen/animations.asm'
    icl 'gen/intro_text.asm'
    icl 'gen/hero_sprites.asm'
    icl 'engine/room.asm'
    icl 'engine/anim.asm'
    icl 'engine/hero.asm'
    icl 'scenes/intro.asm'
    icl 'scenes/game.asm'
    icl 'scenes/gameover.asm'

; --- DOS Binary Run Address ---
    run main

