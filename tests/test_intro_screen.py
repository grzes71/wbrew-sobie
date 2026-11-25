"""Tests for STATE_INTRO compiler, Display List, Polish glyph encoding, SFX, and FIRE skip."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

from scripts.compile_intro import (
    INTRO_COLS,
    INTRO_LINES,
    INTRO_SPACE_CODE,
    INTRO_VRAM_SIZE,
    POLISH_CHAR_MAP,
    IntroCompileError,
    compile_intro_text,
    encode_intro_char,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
XEX_PATH = ROOT_DIR / "funky_koval.xex"
LAB_PATH = ROOT_DIR / "gen" / "main.lab"
INTRO_TXT_PATH = ROOT_DIR / "texts" / "intro.txt"

AUDC1 = 0xD201
AUDF1 = 0xD200
SKCTL = 0xD20F
COLPF1 = 0xD017
COLPF2 = 0xD018
COLBK = 0xD01A
GRACTL = 0xD01D
TRIG0 = 0xD010
PORTA = 0xD300
CHBASE = 0xD409
NMIEN = 0xD40E
SDMCTL = 0x022F
SDLSTL = 0x0230
COLOR1 = 0x02C5
COLOR2 = 0x02C6
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
    """Load Atari DOS .xex segments into a 64 KB memory buffer."""
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


def run_subroutine(mpu: MPU, addr: int, max_steps: int = 300_000) -> int:
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
    assert mpu.pc == 0x0100, (
        f"Subroutine at ${addr:04X} did not return within {max_steps} steps (PC=${mpu.pc:04X})"
    )
    return mpu.processorCycles - c0


def test_intro_txt_lines_within_40_chars_and_10_lines() -> None:
    """Validate SSOT texts/intro.txt fits 1..10 lines with every line <= 40 characters."""
    assert INTRO_TXT_PATH.exists(), f"Missing {INTRO_TXT_PATH}"
    lines = INTRO_TXT_PATH.read_text(encoding="utf-8-sig").splitlines()
    assert 1 <= len(lines) <= INTRO_LINES, f"Expected 1..{INTRO_LINES} lines, got {len(lines)}"
    for idx, line in enumerate(lines, start=1):
        assert len(line) <= INTRO_COLS, (
            f"texts/intro.txt line {idx} exceeds {INTRO_COLS} characters ({len(line)}): {line!r}"
        )
    line_starts, line_ends, screen_bytes = compile_intro_text("\n".join(lines))
    assert len(line_starts) == INTRO_LINES
    assert len(line_ends) == INTRO_LINES
    assert len(screen_bytes) == INTRO_VRAM_SIZE
    for idx, line in enumerate(lines):
        trimmed = line.strip(" ")
        expected_start = (INTRO_COLS - len(trimmed)) // 2 if trimmed else 0
        assert line_starts[idx] == expected_start
        assert line_ends[idx] == (expected_start + len(trimmed) if trimmed else 0)


def test_compile_intro_validation_and_polish_encoding() -> None:
    """Verify uppercase Polish encoding, horizontal centering, blank lines, and rejections."""
    assert POLISH_CHAR_MAP == {
        "Ą": 111,
        "Ć": 112,
        "Ę": 113,
        "Ł": 114,
        "Ń": 115,
        "Ó": 116,
        "Ś": 117,
        "Ź": 118,
        "Ż": 119,
    }
    assert encode_intro_char(" ") == 46
    assert encode_intro_char("a") == encode_intro_char("A") == 79
    assert encode_intro_char("ź") == 118
    assert encode_intro_char("—") == 59

    sample = "ąćęłńóśźż\n\nA—Z"
    starts, ends, data = compile_intro_text(sample)
    # 9 chars -> left_pad = (40 - 9) // 2 = 15, end = 24
    # blank -> start=0, end=0
    # 3 chars -> left_pad = (40 - 3) // 2 = 18, end = 21
    assert starts == [15, 0, 18, 0, 0, 0, 0, 0, 0, 0]
    assert ends == [24, 0, 21, 0, 0, 0, 0, 0, 0, 0]
    assert all(b == INTRO_SPACE_CODE for b in data[:15])
    assert data[15:24] == [111, 112, 113, 114, 115, 116, 117, 118, 119]
    assert all(b == INTRO_SPACE_CODE for b in data[24:INTRO_COLS])
    assert all(b == INTRO_SPACE_CODE for b in data[INTRO_COLS : 2 * INTRO_COLS])
    row2 = data[2 * INTRO_COLS : 3 * INTRO_COLS]
    assert all(b == INTRO_SPACE_CODE for b in row2[:18])
    assert row2[18:21] == [79, 59, 104]
    assert all(b == INTRO_SPACE_CODE for b in row2[21:])

    with pytest.raises(IntroCompileError, match="exceeds max 40"):
        compile_intro_text("X" * 41)

    with pytest.raises(IntroCompileError, match="maximum allowed is 10"):
        compile_intro_text("\n".join(["OK"] * 11))

    with pytest.raises(IntroCompileError, match="Unsupported character"):
        compile_intro_text("HELLO €")


def test_intro_display_list_vram_and_charset() -> None:
    """Verify ANTIC Mode 2 Display List structure, 1 KB alignment, $70 spacers, and 400B SPACE VRAM."""
    mem = bytearray(65536)
    load_xex(XEX_PATH, mem)
    labels = parse_labels(LAB_PATH)

    dlist_addr = labels["INTRO_DLIST"]
    dlist_len = labels["INTRO_DLIST_LEN"]
    assert (dlist_addr & 0xFC00) == ((dlist_addr + dlist_len - 1) & 0xFC00), (
        "intro_dlist crosses 1 KB boundary"
    )

    run_subroutine(mpu := MPU(memory=mem), labels["INTRO_ENTER"])

    vram = labels["SCREEN_VRAM"]
    assert mem[vram : vram + INTRO_VRAM_SIZE] == bytearray([INTRO_SPACE_CODE] * INTRO_VRAM_SIZE)
    assert mem[CHBAS] == (labels["TITLE_CHARSET_2"] >> 8)
    assert mem[CHBASE] == (labels["TITLE_CHARSET_2"] >> 8)
    assert (mem[SDLSTL] | (mem[SDLSTL + 1] << 8)) == dlist_addr
    assert mem[COLOR4] == labels["INTRO_COLBK"] == 0xC0
    assert mem[COLOR2] == labels["INTRO_COLPF2"] == 0xC0
    assert mem[COLOR1] == labels["INTRO_COLPF1"] == 0xCE
    assert mem[SDMCTL] == 0x22
    assert mem[GRACTL] == 0x00
    assert mem[NMIEN] == 0x40
    assert mem[SKCTL] == 0x03

    # Verify Display List opcodes: 5x $70, LMS Mode 2 ($42, lo, hi), 9x ($70, $02), JVB ($41, lo, hi)
    expected_dl = (
        [0x70] * 5
        + [0x42, vram & 0xFF, (vram >> 8) & 0xFF]
        + [0x70, 0x02] * 9
        + [0x41, dlist_addr & 0xFF, (dlist_addr >> 8) & 0xFF]
    )
    assert len(expected_dl) == dlist_len
    assert list(mem[dlist_addr : dlist_addr + dlist_len]) == expected_dl


def test_intro_typewriter_polish_chars_sfx_and_blank_line_silence() -> None:
    """Verify char-by-char reveal, POKEY click SFX + decay, Polish codes, and silent blank lines."""
    raw_mem = bytearray(65536)
    load_xex(XEX_PATH, raw_mem)
    labels = parse_labels(LAB_PATH)
    audc1_writes: list[int] = []

    om = ObservableMemory(subject=raw_mem)
    om.subscribe_to_write([AUDC1], lambda _addr, val: audc1_writes.append(val))
    mpu = MPU(memory=om)
    mpu.reset()

    text = INTRO_TXT_PATH.read_text(encoding="utf-8-sig")
    _starts, _ends, expected_screen = compile_intro_text(text)

    om[PORTA] = 0x0F
    om[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_INIT"])
    om[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])  # TITLE -> INTRO
    om[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])  # Release FIRE

    vram = labels["SCREEN_VRAM"]
    non_space_events = 0
    saw_decay = False
    revealed_steps = 0

    for _ in range(2500):
        before = bytes(raw_mem[vram : vram + INTRO_VRAM_SIZE])
        audc1_writes.clear()
        run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
        after = bytes(raw_mem[vram : vram + INTRO_VRAM_SIZE])

        diffs = [i for i in range(INTRO_VRAM_SIZE) if before[i] != after[i]]
        assert len(diffs) <= 1, "Typewriter must reveal at most 1 character per frame"
        if diffs:
            revealed_steps += 1
            pos = diffs[0]
            assert after[pos] == expected_screen[pos]
            assert audc1_writes, "Visible character reveal must emit POKEY click"
            assert audc1_writes[-1] == 0x84
            non_space_events += 1
        elif 0x81 in audc1_writes or 0x00 in audc1_writes:
            saw_decay = True

        if om[labels["ZP_INTRO_DONE"]] == 1:
            break

    assert om[labels["ZP_INTRO_DONE"]] == 1
    assert revealed_steps > 0
    assert non_space_events == revealed_steps
    assert saw_decay
    assert list(raw_mem[vram : vram + INTRO_VRAM_SIZE]) == expected_screen

    # Let trailing click decay completely
    for _ in range(4):
        run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert raw_mem[AUDC1] == 0x00

    # Explicitly verify silent blank line handling when a row has intro_line_end == 0
    raw_mem2 = bytearray(65536)
    load_xex(XEX_PATH, raw_mem2)
    om2 = ObservableMemory(subject=raw_mem2)
    blank_audc_writes: list[int] = []
    om2.subscribe_to_write([AUDC1], lambda _addr, val: blank_audc_writes.append(val))
    # Hardware TRIG0 ($D010 read) is distinct from GRAFP3 ($D010 write) cleared in intro_enter
    om2.subscribe_to_read([TRIG0], lambda _addr: 0x01)
    mpu2 = MPU(memory=om2)
    mpu2.reset()

    blank_starts, blank_ends, blank_screen = compile_intro_text("A\n\nB")
    start_tbl = labels["INTRO_LINE_START"]
    end_tbl = labels["INTRO_LINE_END"]
    data_tbl = labels["INTRO_SCREEN_DATA"]
    raw_mem2[start_tbl : start_tbl + INTRO_LINES] = bytes(blank_starts)
    raw_mem2[end_tbl : end_tbl + INTRO_LINES] = bytes(blank_ends)
    raw_mem2[data_tbl : data_tbl + INTRO_VRAM_SIZE] = bytes(blank_screen)

    om2[PORTA] = 0x0F
    run_subroutine(mpu2, labels["INPUT_INIT"])
    run_subroutine(mpu2, labels["INTRO_ENTER"])

    # Step until 'A' typed and decayed, then track frames while crossing blank line 1 to 'B'
    row_states: list[tuple[int, int, list[int]]] = []
    for _ in range(15):
        blank_audc_writes.clear()
        run_subroutine(mpu2, labels["INPUT_POLL"])
        run_subroutine(mpu2, labels["INTRO_UPDATE"])
        row_states.append(
            (om2[labels["ZP_INTRO_ROW"]], om2[labels["ZP_INTRO_COL"]], list(blank_audc_writes))
        )
        if om2[labels["ZP_INTRO_DONE"]] == 1:
            break

    # When cursor reaches row 1 (blank) on the transition after row 0, row 1 is skipped with NO extra AUDC1 click
    clicks = [writes[-1] for _, _, writes in row_states if writes and writes[-1] == 0x84]
    assert len(clicks) == 2, f"Expected clicks only for 'A' and 'B', got clicks={clicks}"
    assert list(raw_mem2[vram : vram + INTRO_VRAM_SIZE]) == blank_screen


def test_intro_fire_skip_waits_for_release_then_transitions_to_game() -> None:
    """Verify FIRE during typing shows full text without SFX, waits for release, then enters STATE_GAME."""
    raw_mem = bytearray(65536)
    load_xex(XEX_PATH, raw_mem)
    labels = parse_labels(LAB_PATH)
    _starts, expected_ends, expected_screen = compile_intro_text(
        INTRO_TXT_PATH.read_text(encoding="utf-8-sig")
    )
    assert expected_ends[0] > 0

    om = ObservableMemory(subject=raw_mem)
    audc_after_skip: list[int] = []
    mpu = MPU(memory=om)
    mpu.reset()

    om[PORTA] = 0x0F
    om[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_INIT"])

    # Press FIRE on title -> enter STATE_INTRO (keep FIRE held for 2 more frames!)
    om[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_INTRO"]

    for _ in range(2):
        run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
        assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_INTRO"]
        assert om[labels["ZP_INTRO_DONE"]] == 0

    # Release FIRE so a few characters reveal, then press FIRE to skip
    om[TRIG0] = 0x01
    for _ in range(5):
        run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert om[labels["ZP_INTRO_DONE"]] == 0

    om.subscribe_to_write([AUDC1], lambda _addr, val: audc_after_skip.append(val))
    om[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])

    vram = labels["SCREEN_VRAM"]
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_INTRO"]
    assert om[labels["ZP_INTRO_DONE"]] == 1
    assert om[labels["ZP_INTRO_WAIT_REL"]] == 1
    assert list(raw_mem[vram : vram + INTRO_VRAM_SIZE]) == expected_screen
    assert om[AUDC1] == 0x00
    assert all(val == 0x00 for val in audc_after_skip)

    # Holding FIRE down while text is complete must NOT advance to STATE_GAME or emit sound
    audc_after_skip.clear()
    for _ in range(4):
        run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
        assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_INTRO"]
    assert audc_after_skip == []

    # Releasing FIRE clears wait flag while staying in STATE_INTRO
    om[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_INTRO"]
    assert om[labels["ZP_INTRO_WAIT_REL"]] == 0

    # New FIRE press transitions cleanly to STATE_GAME
    om[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]
