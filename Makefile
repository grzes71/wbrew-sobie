# ==============================================================================
# Makefile — Funky Koval - Wbrew Sobie (Atari 800XL / 65XE)
# Target: 64 KB RAM MOS 6502 (MADS Assembler + Python Tooling)
# ==============================================================================

VENV_PYTHON     := .venv/Scripts/python.exe
PYTHON          ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python)
MADS            ?= c:/Apps/Mad-Assembler-2.1.6/bin/windows_x86_64/mads.exe
ALTIRRA_SDL     ?= C:/Users/grzes/Documents/Projects/AltirraSDL/build/windows-sdl-release/src/AltirraSDL/Release/AltirraSDL.exe

MKDIR           := $(PYTHON) -c "import os, sys; os.makedirs(sys.argv[1], exist_ok=True)"
RM              := $(PYTHON) -c "import os, sys, shutil; [shutil.rmtree(a, ignore_errors=True) if os.path.isdir(a) else os.remove(a) for a in sys.argv[1:] if os.path.exists(a)]"

TARGET          := funky_koval.xex
GEN_DIR         := gen

TITLE_PNG       := images/title.png
FONTS_DIR       := fonts
GAME_FONT       := $(FONTS_DIR)/font.fnt
TITLE_JSON      := $(GEN_DIR)/title_charsets.json
TITLE_FNT_BASE  := $(GEN_DIR)/title_charset.fnt
TITLE_DATA_ASM  := $(GEN_DIR)/title_screen_data.asm

TITLE_DSL           := music/title.dsl
TITLE_ARRANGEMENT   := music/title.arrangement.json
TITLE_MUSIC_JSON    := $(GEN_DIR)/title_music.json
TITLE_MUSIC_ASM     := $(GEN_DIR)/title_music.asm

ASM_SRCS        := main.asm hardware.asm colors.asm zeropage.asm \
                   lib/rle.asm lib/pmg.asm lib/player.asm engine/input.asm engine/dli.asm \
                   scenes/title.asm scenes/game.asm scenes/gameover.asm

.PHONY: all assets data audio xex tests test check_memory run clean

all: assets data audio xex tests check_memory

# ------------------------------------------------------------------------------
# 1. Assets conversion (PNG -> Antic 4 .fnt charsets + JSON metadata)
# ------------------------------------------------------------------------------
assets: $(TITLE_JSON)

$(TITLE_JSON): $(TITLE_PNG) $(GAME_FONT) scripts/png_to_charset.py
	@$(MKDIR) $(GEN_DIR)
	$(PYTHON) scripts/png_to_charset.py $(TITLE_PNG) --font-output $(TITLE_FNT_BASE) --json-output $(TITLE_JSON) --fill-font $(GAME_FONT)

# ------------------------------------------------------------------------------
# 2. Data compilation (JSON -> RLE compressed ASM + Display List + DLI tables)
# ------------------------------------------------------------------------------
data: $(TITLE_DATA_ASM)

$(TITLE_DATA_ASM): $(TITLE_JSON) scripts/compile_title_screen.py
	@$(MKDIR) $(GEN_DIR)
	$(PYTHON) scripts/compile_title_screen.py --json-input $(TITLE_JSON) --gen-dir $(GEN_DIR) --asm-output $(TITLE_DATA_ASM)

# ------------------------------------------------------------------------------
# 3. Audio compilation (Music DSL + arrangement JSON -> JSON IR -> MADS v2 SoA ASM)
# ------------------------------------------------------------------------------
audio: $(TITLE_MUSIC_ASM)

$(TITLE_MUSIC_JSON) $(TITLE_MUSIC_ASM): $(TITLE_DSL) $(TITLE_ARRANGEMENT) scripts/compile_music.py
	@$(MKDIR) $(GEN_DIR)
	$(PYTHON) scripts/compile_music.py --dsl $(TITLE_DSL) --arrangement $(TITLE_ARRANGEMENT) --json-output $(TITLE_MUSIC_JSON) --asm-output $(TITLE_MUSIC_ASM)

# ------------------------------------------------------------------------------
# 4. Binary assembly (MADS)
# ------------------------------------------------------------------------------
xex: $(TARGET)

$(TARGET): $(ASM_SRCS) $(TITLE_DATA_ASM) $(TITLE_MUSIC_ASM)
	@$(MKDIR) $(GEN_DIR)
	$(MADS) main.asm -o:$(TARGET) -l:$(GEN_DIR)/main.lst -t:$(GEN_DIR)/main.lab

# ------------------------------------------------------------------------------
# 5. Automated testing (pytest + py65 CPU emulation)
# ------------------------------------------------------------------------------
tests: $(TARGET)
	$(PYTHON) -m pytest -v

test: tests

# ------------------------------------------------------------------------------
# 6. Automated memory map validation
# ------------------------------------------------------------------------------
check_memory: $(TARGET) scripts/check_memory.py
	$(PYTHON) scripts/check_memory.py $(TARGET)

# ------------------------------------------------------------------------------
# 7. Run in AltirraSDL
# ------------------------------------------------------------------------------
run: $(TARGET)
	"$(ALTIRRA_SDL)" "$(TARGET)"

clean:
	@$(RM) $(GEN_DIR) $(TARGET)
	@echo "Clean completed."

