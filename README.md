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
2. `data` — kompilacja metadanych JSON ekranu tytułowego (`scripts/compile_title_screen.py`) oraz projektu komnat [`rooms.yaml`](rooms.yaml) + grafik PNG grup obiektów do plików MADS w katalogu `gen/` (`scripts/rooms_compile.py`; opis formatu: [`docs/rooms-data-format.md`](docs/rooms-data-format.md)).
3. `audio` — walidacja i kompilacja utworu tytułowego ([`music/title.dsl`](music/title.dsl)) oraz pliku aranżacji ([`music/title.arrangement.json`](music/title.arrangement.json)) do kodu MADS (`gen/title_music.asm`, format v2 SoA) przez skrypt [`scripts/compile_music.py`](scripts/compile_music.py) i wbudowany katalog pakietu `atari_music`.
4. `xex` — asemblacja `main.asm` przy użyciu MADS do pliku wynikowego `funky_koval.xex` (wraz z plikami `.lst` i `.lab` w `gen/`).
5. `tests` — uruchomienie testów automatycznych (`python -m pytest -v`), w tym testów logiki 6502 (RLE, PMG, fala sinusowa DLI, odtwarzacz POKEY v2) w emulatorze `py65` oraz testów edytora Sprite Studio.
6. `check_memory` — walidacja mapy pamięci pliku `funky_koval.xex` (`scripts/check_memory.py`, weryfikacja granicy `$BFFF` poniżej ROM systemu OS).

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

## Room Editor

Edytor komnat, grup obiektów (indeksowany obraz PNG + mapowanie kolorów + nazwane palety PAL, z automatyczną tabelą do 127 unikalnych glifów), przypisań par `(grupa, paleta)` dla każdego z 24 wierszy oraz układów ANTIC 4 (`40×24`) z zapisem do formatu `.yaml` w wersji 4 ([`room_editor/`](room_editor/), specyfikacja: [`room_editor/SPECIFICATION.md`](room_editor/SPECIFICATION.md)).

Uruchomienie edytora komnat:

```powershell
.venv\Scripts\python -m room_editor
```

---

## Struktura projektu

| Ścieżka | Opis |
| --- | --- |
| [`main.asm`](main.asm) | Punkt wejścia aplikacji, pętla główna (frame scheduler) oraz maszyna stanów (`TITLE_SCREEN`, `GAME`, `GAME_OVER_*`) |
| [`hardware.asm`](hardware.asm) | Definicje rejestrów sprzętowych ANTIC, GTIA, POKEY, PIA |
| [`colors.asm`](colors.asm) | Globalna paleta kolorów oraz konfiguracja elementów PMG ekranu tytułowego |
| [`zeropage.asm`](zeropage.asm) | Alokacje zmiennych na stronie zerowej (`$80`–`$FF`) |
| [`engine/`](engine/) | Moduły silnika: obsługa przerwań DLI ([`dli.asm`](engine/dli.asm) — przełączanie `CHBASE` i pozycji `HPOSM0..HPOSM3` co wiersz), odczyt joysticka ([`input.asm`](engine/input.asm)) |
| [`lib/`](lib/) | Biblioteki pomocnicze 6502: obsługa PMG ([`pmg.asm`](lib/pmg.asm)), dekompresja RLE ([`rle.asm`](lib/rle.asm)), relokowalny 4-kanałowy odtwarzacz muzyki POKEY v2 ([`player.asm`](lib/player.asm)) |
| [`scenes/`](scenes/) | Sceny gry: ekran tytułowy ([`title.asm`](scenes/title.asm) — grafika ANTIC 4, napisy PMG, animacja falowa 5. gracza i muzyka tytułowa), gra ([`game.asm`](scenes/game.asm)), ekran końcowy ([`gameover.asm`](scenes/gameover.asm)) |
| [`music/`](music/) | Źródłowe kompozycje muzyczne w formacie Music DSL ([`title.dsl`](music/title.dsl)) oraz manifesty aranżacji ([`title.arrangement.json`](music/title.arrangement.json)) |
| [`scripts/`](scripts/) | Narzędzia Python do konwersji grafiki, kompilacji danych (`rooms_compile.py`, `compile_title_screen.py`, `compile_music.py`) i walidacji mapy pamięci |
| [`docs/`](docs/) | Dokumentacja techniczna formatów danych ([`rooms-data-format.md`](docs/rooms-data-format.md)) |
| [`sprite_studio/`](sprite_studio/) | Edytor GUI (PySide6) sprajtów i klatek animacji |
| [`room_editor/`](room_editor/) | Edytor GUI (PySide6) komnat ANTIC 4, grup obiektów i teleportów |
| [`sprites/`](sprites/) | Dane źródłowe sprajtów (`project.sprite.json`) |
| [`images/`](images/), [`fonts/`](fonts/) | Zasoby graficzne i czcionki Atari |
| [`gen/`](gen/) | Pliki generowane automatycznie podczas budowania (nie edytować ręcznie) |
| [`tests/`](tests/) | Testy jednostkowe i integracyjne (`test_engine.py`, `test_sprite_studio.py`) |
| [`HISTORY.md`](HISTORY.md) | Dziennik zmian projektu |

