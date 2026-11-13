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

