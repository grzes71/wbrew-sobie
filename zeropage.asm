; ==============================================================================
; ZEROPAGE.ASM — Zero Page Allocations ($80-$FF only)
; Project: Funky Koval - Wbrew Sobie
; ==============================================================================

; --- State Machine & Frame Scheduler ($80-$88) ---
zp_current_state    = $80   ; Aktualny stan maszyny stanów (STATE_*)
zp_next_state       = $81   ; Żądany kolejny stan ($FF = brak zmiany)
zp_dli_idx          = $82   ; Indeks strefy DLI dla przełączania CHBASE
zp_last_rtclok      = $83   ; Ostatnia wartość RTCLOK+2 (synchronizacja klatki)
zp_joy_curr         = $84   ; Bieżący stan kierunków joysticka 0 (PORTA/STICK0)
zp_trig_curr        = $85   ; Bieżący stan przycisku FIRE (0=wciśnięty, 1=puszczony)
zp_trig_prev        = $86   ; Poprzedni stan przycisku FIRE
zp_fire_pressed     = $87   ; Flaga nowego wciśnięcia FIRE w bieżącej klatce (0/1)
zp_title_timer      = $88   ; Licznik animacji na ekranie tytułowym (miganie napisu)

; --- RLE Decompressor Pointers ($89-$8D) ---
zp_rle_src          = $89   ; Wskaźnik źródłowy RLE (2 bajty: $89-$8A)
zp_rle_dst          = $8B   ; Wskaźnik docelowy RLE (2 bajty: $8B-$8C)
zp_rle_cnt          = $8D   ; Licznik bajtów przebiegu RLE (1 bajt)

; --- PMG Text Renderer Pointers ($8E-$96) ---
zp_pmg_dst          = $8E   ; Wskaźnik docelowy w pamięci PMG (2 bajty: $8E-$8F)
zp_pmg_src_text     = $90   ; Wskaźnik do ciągu znaków (2 bajty: $90-$91)
zp_pmg_char_ptr     = $92   ; Wskaźnik do definicji znaku w foncie (2 bajty: $92-$93)
zp_pmg_len          = $94   ; Długość generowanego napisu (1 bajt)
zp_pmg_margin       = $95   ; Margines (odstęp) w liniach pomiędzy znakami dla danego Playera (1 bajt)
zp_pmg_invert       = $96   ; Flaga inwersji znaku: 0 = normalny, $FF = inwersja (1 bajt)
zp_p5_wave_phase    = $97   ; Bieżąca faza fali sinusowej dla 5. gracza (1 bajt)

; --- Audio Player Zero Page Base ($A0-$A9) ---
PLAYER_ZP_BASE      = $A0

; --- Room Renderer & Display Pointers ($B0-$CB) ---
zp_room_inst_obj    = $B0   ; Wskaźnik płaszczyzny obj_id instancji (2 bajty: $B0-$B1)
zp_room_inst_x      = $B2   ; Wskaźnik płaszczyzny X instancji (2 bajty: $B2-$B3)
zp_room_inst_yf     = $B4   ; Wskaźnik płaszczyzny y_flag instancji (2 bajty: $B4-$B5)
zp_room_rep_w       = $B6   ; Wskaźnik płaszczyzny rep_w instancji (2 bajty: $B6-$B7)
zp_room_rep_h       = $B8   ; Wskaźnik płaszczyzny rep_h instancji (2 bajty: $B8-$B9)
zp_room_obj_ptr     = $BA   ; Wskaźnik danych komórek obiektu / tymczasowy (2 bajty: $BA-$BB)
zp_room_scr_ptr     = $BC   ; Wskaźnik docelowy wiersza ekranu SCREEN_VRAM (2 bajty: $BC-$BD)
zp_room_inst_cnt    = $BE   ; Liczba instancji w komnacie N (1 bajt)
zp_room_inst_idx    = $BF   ; Bieżący indeks instancji 0..N-1 (1 bajt)
zp_room_rep_idx     = $C0   ; Bieżący indeks powtórzeń 0..R-1 (1 bajt)
zp_room_obj_id      = $C1   ; Bieżące ID obiektu 1..OBJ_MAX_ID (1 bajt)
zp_room_obj_w       = $C2   ; Szerokość bieżącego obiektu w komórkach (1 bajt)
zp_room_obj_h       = $C3   ; Wysokość bieżącego obiektu w komórkach (1 bajt)
zp_room_base_x      = $C4   ; Bazowa współrzędna X instancji (1 bajt)
zp_room_cur_x       = $C5   ; Bieżąca współrzędna X kopii stempla (1 bajt)
zp_room_cur_y       = $C6   ; Bieżąca współrzędna Y kopii stempla (1 bajt)
zp_room_rep_w_cnt   = $C7   ; Licznik pozostałych powtórzeń w poziomie (1 bajt)
zp_room_rep_w_tot   = $C8   ; Całkowita liczba powtórzeń w poziomie rep_w (1 bajt)
zp_room_rep_h_cnt   = $C9   ; Licznik pozostałych powtórzeń w pionie (1 bajt)
zp_room_row_cnt     = $CA   ; Licznik pozostałych wierszy kopiowanego stempla (1 bajt)
zp_room_draw_y      = $CB   ; Bieżący wiersz ekranu Y podczas rysowania stempla (1 bajt)

; --- Intro Screen Typewriter State ($D0-$D9) ---
zp_intro_src        = $D0   ; Wskaźnik źródłowy wiersza intro_screen_data (2 bajty: $D0-$D1)
zp_intro_dst        = $D2   ; Wskaźnik docelowy wiersza w SCREEN_VRAM (2 bajty: $D2-$D3)
zp_intro_row        = $D4   ; Bieżący wiersz efektu maszyny do pisania (0..INTRO_LINES)
zp_intro_col        = $D5   ; Bieżąca kolumna efektu maszyny do pisania (0..INTRO_COLS-1)
zp_intro_timer      = $D6   ; Licznik klatek opóźnienia kolejnego znaku
zp_intro_sfx_timer  = $D7   ; Licznik czasu zanikania kliku POKEY (0..2 klatki)
zp_intro_done       = $D8   ; Flaga zakończenia pisania tekstu (0=pisze, 1=cały tekst)
zp_intro_wait_rel   = $D9   ; Flaga oczekiwania na puszczenie FIRE po pominięciu intro (0/1)

; --- Room Animation Engine ($E0-$FD, VBI-safe) ---
zp_anim_active      = $E0   ; Non-zero while current room has active animated objects
zp_anim_pending     = $E1   ; Non-zero while any object awaits VBI charset copy
zp_anim_budget      = $E2   ; Remaining 8-byte glyph slot budget for current VBI
zp_anim_idx         = $E3   ; Current active-room animation index (0..anim_room_count-1)
zp_anim_rem         = $E4   ; Remaining active-room objects to inspect in copy pass
zp_anim_cursor      = $E5   ; Round-robin start index for copy budget fairness
zp_anim_id          = $E6   ; Current 0-based anim_idx (0..ANIM_COUNT-1)
zp_anim_chbase      = $E7   ; Cached >charset_<group> page byte for active object
zp_anim_flags       = $E8   ; Cached anim_flags byte (bit7=Form2, bit6=VarDur, bit5=Groups, bits4..0=bank)
zp_anim_slots       = $E9   ; Cached dedicated slot count S (1..127)
zp_anim_pos         = $EA   ; Deferred slot (Form 1) or delta pair (Form 2) cursor
zp_anim_sbase       = $EB   ; Base offset in anim_slot_cur for current Form 1 object
zp_anim_tmp         = $EC   ; Scratch byte (target frame / pattern index / mul counter)
zp_anim_hi          = $ED   ; Scratch byte (slot*8 hi / delta count)
zp_anim_src         = $EE   ; Frame/init sequence table pointer (2 bytes: $EE-$EF)
zp_anim_dst         = $F0   ; Dedicated charset destination pointer (2 bytes: $F0-$F1)
zp_anim_scodes      = $F2   ; Dedicated base char code list pointer (2 bytes: $F2-$F3)
zp_anim_ptr         = $F4   ; Room list / Form 2 delta block / dur / group pointer (2 bytes: $F4-$F5)
zp_anim_psrc        = $F6   ; Split-pool plane pointer when ANIM_POOL_COUNT > 1 ($F6-$F7)
zp_anim_pat         = $F8   ; Pattern index scratch for split-pool copy ($F8)
zp_anim_row         = $F9   ; Row index scratch for split-pool copy ($F9)
zp_anim_dcnt        = $FA   ; Form 2 delta pair count ($FA, never clobbered by dst math)
zp_anim_f2str       = $FB   ; Form 2 delta pointer table stride (F or F+G) ($FB)
zp_anim_nvis        = $FC   ; Form 2 next visible frame committed on delta completion ($FC)
zp_anim_nvrep       = $FD   ; Form 2 next visible pass counter committed on delta completion ($FD)


