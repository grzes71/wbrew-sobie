# Funky Koval - Wbrew Sobie

Gra oraz narzędzia deweloperskie dla komputerów **Atari 800XL / 65XE** (64 KB RAM, procesor MOS 6502), łącząca kod w asemblerze 6502 (**MADS**) z potokiem danych i testów w **Pythonie** (`pytest`, `py65`, `PySide6`).

---

## Wymagania

- **MADS (Mad-Assembler)** — domyślna ścieżka w `Makefile`: `c:/Apps/Mad-Assembler-2.1.6/bin/windows_x86_64/mads.exe` (można nadpisać zmienną `MADS=...`)
- **Python 3.10+** oraz zależności z [`requirements.txt`](requirements.txt):
  - `pillow>=10.0.0`
  - `pytest>=8.0.0`
  - `PySide6>=6.5.0`
  - `py65>=1.1.0`
  - `atari_music`
- **GNU Make**
- **AltirraSDL** (opcjonalnie, do uruchamiania i weryfikacji binarnego pliku `.xex`)

### Konfiguracja środowiska Python (`.venv`)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

---

## Budowanie i uruchamianie

Pełny potok budowania realizowany jest przez `Makefile`:

```bash
make all
```

Kolejność etapów `make all`:
1. `assets` — konwersja obrazu tytułowego (`images/title.png`) do zestawów znaków ANTIC 4 (`.fnt`) oraz metadanych JSON (`scripts/png_to_charset.py`).
2. `data` — kompilacja metadanych JSON do spakowanych danych RLE, Display Listy oraz tablic DLI w plikach ASM w katalogu `gen/` (`scripts/compile_title_screen.py`).
3. `xex` — asemblacja `main.asm` przy użyciu MADS do pliku wynikowego `funky_koval.xex` (wraz z plikami `.lst` i `.lab` w `gen/`).
4. `tests` — uruchomienie testów automatycznych (`python -m pytest -v`), w tym testów logiki 6502 w emulatorze `py65` oraz testów edytora Sprite Studio.
5. `check_memory` — walidacja mapy pamięci pliku `funky_koval.xex` (`scripts/check_memory.py`, weryfikacja granicy `$BFFF` poniżej ROM systemu OS).

Pozostałe cele `Makefile`:
- `make run` — uruchomienie `funky_koval.xex` w emulatorze AltirraSDL.
- `make clean` — usunięcie wygenerowanego katalogu `gen/` oraz pliku `funky_koval.xex`.

---

## Sprite Studio

Projekt zawiera dedykowany edytor sprajtów i animacji oparty na `PySide6` ([`sprite_studio/`](sprite_studio/)), operujący na pliku projektu [`sprites/project.sprite.json`](sprites/project.sprite.json).

Uruchomienie edytora:

```powershell
.venv\Scripts\python -m sprite_studio.main
```

---

## Struktura projektu

| Ścieżka | Opis |
| --- | --- |
| [`main.asm`](main.asm) | Punkt wejścia aplikacji, pętla główna (frame scheduler) oraz maszyna stanów (`TITLE_SCREEN`, `GAME`, `GAME_OVER_*`) |
| [`hardware.asm`](hardware.asm) | Definicje rejestrów sprzętowych ANTIC, GTIA, POKEY, PIA |
| [`colors.asm`](colors.asm) | Globalna paleta kolorów oraz konfiguracja elementów PMG ekranu tytułowego |
| [`zeropage.asm`](zeropage.asm) | Alokacje zmiennych na stronie zerowej (`$80`–`$FF`) |
| [`engine/`](engine/) | Moduły silnika: obsługa przerwań DLI ([`dli.asm`](engine/dli.asm)), odczyt joysticka ([`input.asm`](engine/input.asm)) |
| [`lib/`](lib/) | Biblioteki pomocnicze 6502: obsługa PMG ([`pmg.asm`](lib/pmg.asm)), dekompresja RLE ([`rle.asm`](lib/rle.asm)) |
| [`scenes/`](scenes/) | Sceny gry: ekran tytułowy ([`title.asm`](scenes/title.asm)), gra ([`game.asm`](scenes/game.asm)), ekran końcowy ([`gameover.asm`](scenes/gameover.asm)) |
| [`scripts/`](scripts/) | Narzędzia Python do konwersji grafiki, kompilacji danych i walidacji mapy pamięci |
| [`sprite_studio/`](sprite_studio/) | Edytor GUI (PySide6) sprajtów i klatek animacji |
| [`sprites/`](sprites/) | Dane źródłowe sprajtów (`project.sprite.json`) |
| [`images/`](images/), [`fonts/`](fonts/) | Zasoby graficzne i czcionki Atari |
| [`gen/`](gen/) | Pliki generowane automatycznie podczas budowania (nie edytować ręcznie) |
| [`tests/`](tests/) | Testy jednostkowe i integracyjne (`test_engine.py`, `test_sprite_studio.py`) |
| [`HISTORY.md`](HISTORY.md) | Dziennik zmian projektu |

