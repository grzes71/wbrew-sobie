; ==============================================================================
; COLORS.ASM — Global Color Palette Configuration
; Project: Funky Koval - Wbrew Sobie
; ==============================================================================

PAL_COLBK       = $00       ; Kolor tła / ramki (COLBK / COLOR4)
PAL_COLOR1      = $32       ; Kolor pola gry 0 (COLPF0 / COLOR0)
PAL_COLOR2      = $2c       ; Kolor pola gry 1 (COLPF1 / COLOR1)
PAL_COLOR0      = $44       ; Kolor pola gry 2 (COLPF2 / COLOR2)
PAL_COLOR3      = $00       ; Kolor pola gry 3 (COLPF3 / COLOR3)

; --- Title Screen PMG Subtitle ("WBREW SOBIE") Configuration ---
; Pozycje poziome i pionowe oraz kolory graczy (łatwa edycja)
TITLE_PMG_CHAR_MARGIN   = 8         ; Domyślny margines (dla wstecznej kompatybilności)
TITLE_P0_MARGIN         = 8         ; Margines (odstęp w liniach) pomiędzy znakami na Player 0
TITLE_P1_MARGIN         = 8         ; Margines (odstęp w liniach) pomiędzy znakami na Player 1
TITLE_P2_MARGIN         = 8         ; Margines (odstęp w liniach) pomiędzy znakami na Player 2
TITLE_P3_MARGIN         = 8         ; Margines (odstęp w liniach) pomiędzy znakami na Player 3
TITLE_SUBTITLE_Y        = 32        ; Pozycja pionowa Y dla Playerów (bufor single-line PMG)
TITLE_P0_Y              = TITLE_SUBTITLE_Y ; Pozycja pionowa Y dla Player 0 ("WBREW ")
TITLE_P1_Y              = TITLE_SUBTITLE_Y ; Pozycja pionowa Y dla Player 1 (" SOBIE")
TITLE_P2_Y              = TITLE_SUBTITLE_Y+4 ; Pozycja pionowa Y dla Player 2 (podkład spacji pod P0)
TITLE_P3_Y              = TITLE_SUBTITLE_Y+4 ; Pozycja pionowa Y dla Player 3 (podkład spacji pod P1)

TITLE_START_X           = 128                 ; Pozycja pozioma
TITLE_P0_X              = TITLE_START_X       ; Pozycja pozioma HPOSP0 (na wierzchu, "WBREW ")
TITLE_P1_X              = TITLE_START_X+20+4  ; Pozycja pozioma HPOSP1 (na wierzchu, " SOBIE")
TITLE_P2_X              = TITLE_START_X+2       ; Pozycja pozioma HPOSP2 (podkład pod Player 0)
TITLE_P3_X              = TITLE_START_X+20+4+2  ; Pozycja pozioma HPOSP3 (podkład pod Player 1)

; Szerokość graczy (0 = normalna 1x, 1 = podwójna 2x, 3 = poczwórna 4x):
TITLE_P0_SIZE           = 1         ; Player 0 szerokość x4
TITLE_P1_SIZE           = 1         ; Player 1 szerokość x4
TITLE_P2_SIZE           = 1         ; Player 2 szerokość x4 (podkład)
TITLE_P3_SIZE           = 1         ; Player 3 szerokość x4 (podkład)

; Kolory graczy:
; P0 (tekst WBREW) i P1 (tekst SOBIE) są w inwersji (litera to wycięcie/dziura)
; P2 (pod P0) i P3 (pod P1) przebijają przez wycięcia liter, podkolorowując napis!
TITLE_P0_COLOR          = $a6       ; Kolor gracza 0 / PCOLR0 (tło napisu WBREW)
TITLE_P1_COLOR          = $86       ; Kolor gracza 1 / PCOLR1 (tło napisu SOBIE)
TITLE_P2_COLOR          = $a4       ; Kolor gracza 2 / PCOLR2 (litery WBREW przebijające przez P0)
TITLE_P3_COLOR          = $84       ; Kolor gracza 3 / PCOLR3 (litery SOBIE przebijające przez P1)

