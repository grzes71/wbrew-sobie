"""Automated py65 and pipeline tests for Funky Koval - Wbrew Sobie."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU

from scripts.compile_title_screen import rle_compress, rle_decompress

ROOT_DIR = Path(__file__).resolve().parent.parent
XEX_PATH = ROOT_DIR / "funky_koval.xex"
LAB_PATH = ROOT_DIR / "gen" / "main.lab"
JSON_PATH = ROOT_DIR / "gen" / "title_charsets.json"

# Hardware & OS shadow register addresses from hardware.asm
COLPF0 = 0xD016
COLPF1 = 0xD017
COLPF2 = 0xD018
COLPF3 = 0xD019
COLBK = 0xD01A
PORTA = 0xD300
TRIG0 = 0xD010
CHBASE = 0xD409
WSYNC = 0xD40A
NMIEN = 0xD40E
VDSLST = 0x0200
SDLSTL = 0x0230
COLOR0 = 0x02C4
COLOR1 = 0x02C5
COLOR2 = 0x02C6
COLOR3 = 0x02C7
COLOR4 = 0x02C8
CHBAS = 0x02F4


def parse_labels(lab_path: Path) -> dict[str, int]:
    """Parse MADS .lab file into upper-case symbol -> address mapping."""
    assert lab_path.exists(), f"Missing {lab_path}; run 'make all' first."
    labels: dict[str, int] = {}
    pattern = re.compile(r"^[0-9a-fA-F]{2}\t([0-9a-fA-F]{4})\t([A-Za-z0-9_.\@?]+)")
    for line in lab_path.read_text(encoding="utf-8").splitlines():
        m = pattern.match(line.strip())
        if m:
            labels[m.group(2).upper()] = int(m.group(1), 16)
    return labels


def load_xex(xex_path: Path, mem: bytearray) -> None:
    """Load Atari DOS .xex segments into a 64KB memory buffer."""
    assert xex_path.exists(), f"Missing {xex_path}; run 'make all' first."
    data = xex_path.read_bytes()
    idx = 0
    n = len(data)
    while idx < n:
        if idx + 2 <= n and data[idx] == 0xFF and data[idx + 1] == 0xFF:
            idx += 2
            if idx == n:
                break
        start = data[idx] | (data[idx + 1] << 8)
        end = data[idx + 2] | (data[idx + 3] << 8)
        idx += 4
        length = end - start + 1
        mem[start : end + 1] = data[idx : idx + length]
        idx += length


def run_subroutine(mpu: MPU, addr: int, max_steps: int = 200_000) -> int:
    """Execute a 6502 subroutine via JSR-equivalent return sentinel at $0100."""
    mpu.sp = 0xFD
    mpu.stPushWord(0x0100 - 1)
    mpu.memory[0x0100] = 0x00
    mpu.pc = addr
    c0 = mpu.processorCycles
    steps = 0
    while mpu.pc != 0x0100 and steps < max_steps:
        mpu.step()
        steps += 1
    assert mpu.pc == 0x0100, f"Subroutine at ${addr:04X} did not return within {max_steps} steps (PC=${mpu.pc:04X})"
    return mpu.processorCycles - c0


def run_interrupt_handler(mpu: MPU, addr: int, max_steps: int = 1_000) -> int:
    """Execute a 6502 interrupt handler ending with RTI ($40)."""
    mpu.sp = 0xFD
    mpu.stPushWord(0x0100)
    mpu.stPush(0x00)
    mpu.memory[0x0100] = 0x00
    mpu.pc = addr
    c0 = mpu.processorCycles
    steps = 0
    while mpu.pc != 0x0100 and steps < max_steps:
        mpu.step()
        steps += 1
    assert mpu.pc == 0x0100, f"ISR at ${addr:04X} did not RTI within {max_steps} steps (PC=${mpu.pc:04X})"
    return mpu.processorCycles - c0


@pytest.fixture()
def emu() -> tuple[MPU, bytearray, dict[str, int]]:
    """Provide fresh 64K RAM + MPU loaded with the built XEX and symbol table."""
    mem = bytearray(65536)
    load_xex(XEX_PATH, mem)
    labels = parse_labels(LAB_PATH)
    mpu = MPU(memory=mem)
    mpu.reset()
    return mpu, mem, labels


def test_rle_python_roundtrip() -> None:
    """Verify Python RLE compressor/decompressor on edge patterns."""
    samples = [
        [0] * 960,
        list(range(128)) * 7 + list(range(64)),
        [5, 5, 5, 1, 2, 3, 4, 9, 9, 9, 9, 0],
    ]
    for sample in samples:
        packed = rle_compress(sample)
        assert rle_decompress(packed) == sample


def test_title_rle_decompression_matches_json_ssot(emu: tuple[MPU, bytearray, dict[str, int]]) -> None:
    """Verify that 6502 rle_decompress produces the exact 960 glyph bytes from title_charsets.json."""
    mpu, mem, labels = emu
    raw_json = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    expected_glifs = [g for cs in raw_json["charsets"] for g in cs["glifs"]]
    assert len(expected_glifs) == 960

    run_subroutine(mpu, labels["TITLE_ENTER"])

    vram_addr = labels["SCREEN_VRAM"]
    actual_vram = list(mem[vram_addr : vram_addr + 960])
    assert actual_vram == expected_glifs


def test_title_palette_and_dli_setup(emu: tuple[MPU, bytearray, dict[str, int]]) -> None:
    """Verify global color registers and DLI/DLIST vectors after title_enter."""
    mpu, mem, labels = emu
    run_subroutine(mpu, labels["TITLE_ENTER"])

    assert mem[COLBK] == labels["PAL_COLBK"]
    assert mem[COLOR4] == labels["PAL_COLBK"]
    assert mem[COLPF0] == labels["PAL_COLOR0"]
    assert mem[COLOR0] == labels["PAL_COLOR0"]
    assert mem[COLPF1] == labels["PAL_COLOR1"]
    assert mem[COLOR1] == labels["PAL_COLOR1"]
    assert mem[COLPF2] == labels["PAL_COLOR2"]
    assert mem[COLOR2] == labels["PAL_COLOR2"]

    dlist_ptr = mem[SDLSTL] | (mem[SDLSTL + 1] << 8)
    assert dlist_ptr == labels["TITLE_DLIST"]

    vdslst_ptr = mem[VDSLST] | (mem[VDSLST + 1] << 8)
    assert vdslst_ptr == labels["TITLE_DLI_HANDLER"]

    assert mem[CHBAS] == (labels["TITLE_CHARSET_0"] >> 8)
    assert mem[CHBASE] == (labels["TITLE_CHARSET_0"] >> 8)
    assert mem[NMIEN] == 0xC0


def test_title_dli_handler_switches_charsets(emu: tuple[MPU, bytearray, dict[str, int]]) -> None:
    """Verify that title_dli_handler cycles through all secondary charsets and wraps around."""
    mpu, mem, labels = emu
    raw_json = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    num_charsets = len(raw_json["charsets"])
    dli_count = num_charsets - 1

    run_subroutine(mpu, labels["TITLE_ENTER"])

    # Guard registers A, X, Y to ensure DLI handler preserves CPU registers
    mpu.a = 0xAA
    mpu.x = 0x55
    mpu.y = 0x33

    for i in range(dli_count):
        cycles = run_interrupt_handler(mpu, labels["TITLE_DLI_HANDLER"])
        assert cycles <= 55, f"DLI took {cycles} cycles, exceeding safe scanline budget"
        expected_chbase = labels[f"TITLE_CHARSET_{i + 1}"] >> 8
        assert mem[CHBASE] == expected_chbase
        assert mpu.a == 0xAA
        assert mpu.x == 0x55
        assert mpu.y == 0x33

    # After the last DLI in the frame, zp_dli_idx must wrap back to 0
    assert mem[labels["ZP_DLI_IDX"]] == 0


def test_state_machine_transitions(emu: tuple[MPU, bytearray, dict[str, int]]) -> None:
    """Verify full state machine lifecycle: TITLE_SCREEN -> GAME -> GAME_OVER (FAILURE & SUCCESS) -> TITLE_SCREEN."""
    mpu, mem, labels = emu

    # Initialize state machine -> enters STATE_TITLE_SCREEN (0)
    mem[PORTA] = 0x0F
    mem[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_INIT"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_TITLE_SCREEN"]

    # Frame with FIRE released -> stays in STATE_TITLE_SCREEN
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_TITLE_SCREEN"]

    # Press FIRE (TRIG0 = 0) -> transitions to STATE_GAME
    mem[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]

    # Holding FIRE down on the next frame must NOT trigger another transition (edge detection)
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]

    # Release FIRE, then press FIRE (without UP) -> transitions to STATE_GAME_OVER_FAILURE
    mem[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    mem[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME_OVER_FAILURE"]

    # Release FIRE, then press FIRE -> returns to STATE_TITLE_SCREEN
    mem[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    mem[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_TITLE_SCREEN"]

    # Advance to STATE_GAME again, then press UP + FIRE -> transitions to STATE_GAME_OVER_SUCCESS
    mem[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    mem[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]

    mem[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    mem[PORTA] = 0x0E  # Joy UP pressed (bit 0 = 0)
    mem[TRIG0] = 0x00  # FIRE pressed
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME_OVER_SUCCESS"]

    # Release FIRE, then press FIRE -> returns to STATE_TITLE_SCREEN
    mem[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    mem[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_TITLE_SCREEN"]


def test_last_charset_filled_with_game_font(emu: tuple[MPU, bytearray, dict[str, int]]) -> None:
    """Verify that remaining slots of the last charset (82 glyphs) match fonts/font.fnt."""
    mpu, mem, labels = emu
    font_file = ROOT_DIR / "fonts" / "font.fnt"
    assert font_file.exists(), f"Missing {font_file}"
    font_data = font_file.read_bytes()

    raw_json = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    last_cs_meta = raw_json["charsets"][-1]
    unique_count = last_cs_meta["unique_characters"]
    filled_count = last_cs_meta.get("filled_glyphs", 0)

    assert unique_count + filled_count == 128
    assert filled_count == 82
    assert labels["GAME_FONT_GLYPH_OFFSET"] == unique_count
    assert labels["GAME_FONT_GLYPH_COUNT"] == filled_count

    last_cs_addr = labels[f"TITLE_CHARSET_{last_cs_meta['index']}"]
    free_slots_offset = unique_count * 8
    actual_filled_bytes = bytes(mem[last_cs_addr + free_slots_offset : last_cs_addr + 1024])
    expected_bytes = font_data[: filled_count * 8]

    assert actual_filled_bytes == expected_bytes


def test_title_pmg_subtitle_setup(emu: tuple[MPU, bytearray, dict[str, int]]) -> None:
    """Verify that title_enter sets up PMG registers and renders WBREW on P1 and SOBIE on P2."""
    mpu, mem, labels = emu
    run_subroutine(mpu, labels["TITLE_ENTER"])

    # PMG configuration in GTIA and ANTIC (single-line PMG: SDMCTL=$3E)
    pmbase = labels["PMG_BASE"] >> 8
    assert mem[0xD407] == pmbase  # PMBASE ($D407)
    assert mem[0xD01D] == 0x03    # GRACTL ($D01D)
    assert mem[0x022F] == 0x3E    # SDMCTL ($022F)

    # Player horizontal positions and colors (P0, P1, P2, P3)
    assert mem[0xD000] == labels["TITLE_P0_X"]      # HPOSP0
    assert mem[0xD001] == labels["TITLE_P1_X"]      # HPOSP1
    assert mem[0xD002] == labels["TITLE_P2_X"]      # HPOSP2
    assert mem[0xD003] == labels["TITLE_P3_X"]      # HPOSP3
    assert mem[0x02C0] == labels["TITLE_P0_COLOR"]  # PCOLR0
    assert mem[0x02C1] == labels["TITLE_P1_COLOR"]  # PCOLR1
    assert mem[0x02C2] == labels["TITLE_P2_COLOR"]  # PCOLR2
    assert mem[0x02C3] == labels["TITLE_P3_COLOR"]  # PCOLR3

    # Players size: P0 and P1 are 2x width (1), P2 and P3 are 4x width (3)
    assert mem[0xD008] == labels["TITLE_P0_SIZE"]  # SIZEP0 (1 = 2x width)
    assert mem[0xD009] == labels["TITLE_P1_SIZE"]  # SIZEP1 (1 = 2x width)
    assert mem[0xD00A] == labels["TITLE_P2_SIZE"]  # SIZEP2 (3 = 4x width)
    assert mem[0xD00B] == labels["TITLE_P3_SIZE"]  # SIZEP3 (3 = 4x width)

    # Check rendered glyph bytes in PMG buffers:
    # Player 0 = "WBREW" (5 chars) at TITLE_P0_Y with TITLE_P0_MARGIN
    # Player 1 = "SOBIE" (5 chars) at TITLE_P1_Y with TITLE_P1_MARGIN
    # Player 2 = "WBREW" (5 chars) at TITLE_P2_Y with TITLE_P2_MARGIN
    # Player 3 = "SOBIE" (5 chars) at TITLE_P3_Y with TITLE_P3_MARGIN
    p0_buf = labels["PMG_P0"] + labels["TITLE_P0_Y"]
    p1_buf = labels["PMG_P1"] + labels["TITLE_P1_Y"]
    p2_buf = labels["PMG_P2"] + labels["TITLE_P2_Y"]
    p3_buf = labels["PMG_P3"] + labels["TITLE_P3_Y"]
    stride_p0 = 32 + labels["TITLE_P0_MARGIN"]
    stride_p1 = 32 + labels["TITLE_P1_MARGIN"]
    stride_p2 = 32 + labels["TITLE_P2_MARGIN"]
    stride_p3 = 32 + labels["TITLE_P3_MARGIN"]

    # Verify P0, P1, P2, P3 buffers contain non-zero bitmap patterns (5 chars * stride)
    total_span_p0 = 5 * stride_p0
    total_span_p1 = 5 * stride_p1
    total_span_p2 = 5 * stride_p2
    total_span_p3 = 5 * stride_p3
    assert any(mem[p0_buf + i] != 0 for i in range(total_span_p0))
    assert any(mem[p1_buf + i] != 0 for i in range(total_span_p1))
    assert any(mem[p2_buf + i] != 0 for i in range(total_span_p2))
    assert any(mem[p3_buf + i] != 0 for i in range(total_span_p3))

    # Verify first glyph on P0 & P2 matches 'W' (glyph 101 in title_charset_2) normal (non-inverted) with each row quadrupled
    font_w_addr = labels["TITLE_CHARSET_2"] + (101 * 8)
    font_w_bytes = bytes(mem[font_w_addr : font_w_addr + 8])
    expected_w_bytes = bytes(b for b in font_w_bytes for _ in range(4))
    actual_p0_w_bytes = bytes(mem[p0_buf : p0_buf + 32])
    actual_p2_w_bytes = bytes(mem[p2_buf : p2_buf + 32])
    assert actual_p0_w_bytes == expected_w_bytes
    assert actual_p2_w_bytes == expected_w_bytes

    # Verify 1st glyph on P1 & P3 matches 'S' (glyph 97 in title_charset_2) normal (non-inverted) with each row quadrupled
    font_s_addr = labels["TITLE_CHARSET_2"] + (97 * 8)
    font_s_bytes = bytes(mem[font_s_addr : font_s_addr + 8])
    expected_s_bytes = bytes(b for b in font_s_bytes for _ in range(4))
    actual_p1_s_bytes = bytes(mem[p1_buf : p1_buf + 32])
    actual_p3_s_bytes = bytes(mem[p3_buf : p3_buf + 32])
    assert actual_p1_s_bytes == expected_s_bytes
    assert actual_p3_s_bytes == expected_s_bytes

    # Verify margin between character 0 and character 1 on P0, P1, P2, P3 is 0 (blank)
    if labels["TITLE_P0_MARGIN"] > 0:
        for m in range(labels["TITLE_P0_MARGIN"]):
            assert mem[p0_buf + 32 + m] == 0
    if labels["TITLE_P1_MARGIN"] > 0:
        for m in range(labels["TITLE_P1_MARGIN"]):
            assert mem[p1_buf + 32 + m] == 0
    if labels["TITLE_P2_MARGIN"] > 0:
        for m in range(labels["TITLE_P2_MARGIN"]):
            assert mem[p2_buf + 32 + m] == 0
    if labels["TITLE_P3_MARGIN"] > 0:
        for m in range(labels["TITLE_P3_MARGIN"]):
            assert mem[p3_buf + 32 + m] == 0
