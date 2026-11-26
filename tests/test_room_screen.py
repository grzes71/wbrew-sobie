"""Headless py65, display-list, state-flow, and PNG renderer tests for initial room screen."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

from room_editor.io.yaml_io import load_project
from room_editor.model.palette import load_default_pal_palette
from room_editor.model.project import (
    ROOM_DISPLAY_HEIGHT,
    ROOM_DISPLAY_WIDTH,
    ROOM_HEIGHT,
    ROOM_WIDTH,
    compose_room,
    render_room_row_rgb,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
XEX_PATH = ROOT_DIR / "funky_koval.xex"
LAB_PATH = ROOT_DIR / "gen" / "main.lab"
ROOMS_YAML = ROOT_DIR / "rooms.yaml"
RENDER_PNG_SCRIPT = ROOT_DIR / "tools" / "render_room_png.py"

# Hardware & OS shadow addresses
GRACTL = 0xD01D
COLPF0 = 0xD016
COLPF1 = 0xD017
COLPF2 = 0xD018
COLPF3 = 0xD019
COLBK = 0xD01A
TRIG0 = 0xD010
PORTA = 0xD300
CHBASE = 0xD409
NMIEN = 0xD40E
VDSLST = 0x0200
VVBLKD = 0x0224
SDMCTL = 0x022F
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
    """Load Atari DOS .xex segments into a 64 KB buffer."""
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


def run_subroutine(mpu: MPU, addr: int, max_steps: int = 400_000) -> int:
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
    assert mpu.pc == 0x0100, (
        f"ISR at ${addr:04X} did not RTI within {max_steps} steps (PC=${mpu.pc:04X})"
    )
    return mpu.processorCycles - c0


@pytest.fixture()
def emu() -> tuple[MPU, bytearray, dict[str, int]]:
    """Provide fresh 64K RAM + MPU loaded with funky_koval.xex and labels."""
    mem = bytearray(65536)
    load_xex(XEX_PATH, mem)
    labels = parse_labels(LAB_PATH)
    mpu = MPU(memory=mem)
    mpu.reset()
    return mpu, mem, labels


def _flatten_grid(grid: list[list[int]]) -> list[int]:
    return [cell for row in grid for cell in row]


def _expected_row_styles(proj_yaml: dict, mem: bytearray, labels: dict[str, int], room_id: int) -> list[int]:
    """Compute expected style IDs [0..23] dynamically from rooms.yaml + main.lab equates."""
    room_doc = next(r for r in proj_yaml["rooms"] if int(r["id"]) == room_id)
    raw_rows = room_doc["row_groups"]
    if len(raw_rows) == 1:
        raw_rows = raw_rows * ROOM_HEIGHT

    out: list[int] = []
    for entry in raw_rows:
        if isinstance(entry, dict):
            gname = str(entry["group"])
            pname = str(entry["palette"])
        else:
            gname = str(entry)
            gdoc = next(g for g in proj_yaml["object_groups"] if g["name"] == gname)
            pname = str(gdoc["palettes"][0]["name"])
        key = f"STYLE_{re.sub(r'[^A-Z0-9]+', '_', gname.upper()).strip('_')}_{re.sub(r'[^A-Z0-9]+', '_', pname.upper()).strip('_')}"
        out.append(labels[key])
    return out


def test_room_symbols_exist(emu: tuple[MPU, bytearray, dict[str, int]]) -> None:
    """Verify key room engine symbols and zero-page equates exist in main.lab."""
    _mpu, _mem, labels = emu
    for sym in (
        "START_ROOM",
        "ROOM_DRAW",
        "ROOM_SETUP_DISPLAY",
        "ROOM_DLI_HANDLER",
        "ROOM_DLIST",
        "CUR_ROW_STYLE",
        "ROOM_DLI_STYLE",
        "ROOM_DLI_COUNT",
        "CUR_ROOM_ID",
        "SCREEN_ROW_LO",
        "SCREEN_ROW_HI",
        "ZP_ROOM_INST_OBJ",
        "ZP_ROOM_DRAW_Y",
    ):
        assert sym in labels, f"Missing expected symbol '{sym}' in gen/main.lab"


def test_room_draw_start_room_matches_reference(emu: tuple[MPU, bytearray, dict[str, int]]) -> None:
    """room_draw(START_ROOM) fills 960 VRAM bytes identically to compose_room."""
    mpu, mem, labels = emu
    proj = load_project(ROOMS_YAML).project
    assert proj.start is not None
    assert labels["START_ROOM"] == proj.start.room_id

    start_room = proj.get_room(proj.start.room_id)
    assert start_room is not None
    expected = _flatten_grid(compose_room(proj, start_room))
    assert len(expected) == ROOM_WIDTH * ROOM_HEIGHT

    vram = labels["SCREEN_VRAM"]
    mem[vram - 1] = 0xA5
    mem[vram + 960] = 0x5A
    mem[vram : vram + 960] = b"\xff" * 960

    mpu.x = proj.start.room_id
    run_subroutine(mpu, labels["ROOM_DRAW"])

    assert list(mem[vram : vram + 960]) == expected
    assert mem[vram - 1] == 0xA5
    assert mem[vram + 960] == 0x5A


def test_room_draw_all_rooms_and_empty_room_match_reference(
    emu: tuple[MPU, bytearray, dict[str, int]],
) -> None:
    """room_draw reproduces every room in rooms.yaml accurately and clears N=0 rooms."""
    mpu, mem, labels = emu
    proj = load_project(ROOMS_YAML).project
    vram = labels["SCREEN_VRAM"]

    for room in proj.rooms:
        mem[vram : vram + 960] = b"\xff" * 960
        mpu.x = room.id
        run_subroutine(mpu, labels["ROOM_DRAW"])
        expected = _flatten_grid(compose_room(proj, room))
        assert list(mem[vram : vram + 960]) == expected, f"Mismatch in room {room.id} ({room.name})"

    # Also verify N == 0 edge case clears VRAM to all zeroes without drawing anything
    first_id = proj.rooms[0].id
    mem[labels["ROOM_INST_COUNT_BASE"] + (first_id - 1)] = 0
    mem[vram : vram + 960] = b"\xaa" * 960
    mpu.x = first_id
    run_subroutine(mpu, labels["ROOM_DRAW"])
    assert mem[vram : vram + 960] == bytearray(960)


def test_room_display_list_alignment_and_uniform_style(
    emu: tuple[MPU, bytearray, dict[str, int]],
) -> None:
    """Verify DLIST structure, DLI bit placement, hardware alignment, and NMIEN for uniform rooms."""
    mpu, mem, labels = emu
    proj = load_project(ROOMS_YAML).project
    raw_yaml = yaml.safe_load(ROOMS_YAML.read_text(encoding="utf-8"))

    # Static boundary checks
    dlist_addr = labels["ROOM_DLIST"]
    assert (dlist_addr & 0xFC00) == ((dlist_addr + 31) & 0xFC00), "room_dlist crosses 1 KB boundary"

    vram_addr = labels["SCREEN_VRAM"]
    assert (vram_addr & 0xF000) == ((vram_addr + 959) & 0xF000), "SCREEN_VRAM crosses 4 KB boundary"

    for group in proj.object_groups:
        cname = f"CHARSET_{re.sub(r'[^A-Z0-9]+', '_', group.name.upper()).strip('_')}"
        assert cname in labels
        assert (labels[cname] & 0x03FF) == 0, f"{cname} not 1 KB aligned (${labels[cname]:04X})"

    # Dynamic per-room Display List verification
    for room in proj.rooms:
        mpu.x = room.id
        run_subroutine(mpu, labels["ROOM_SETUP_DISPLAY"])

        expected_styles = _expected_row_styles(raw_yaml, mem, labels, room.id)
        expected_transitions = [
            expected_styles[r + 1]
            for r in range(ROOM_HEIGHT - 1)
            if expected_styles[r + 1] != expected_styles[r]
        ]

        assert mem[labels["CUR_ROOM_ID"]] == room.id
        assert list(mem[labels["CUR_ROW_STYLE"] : labels["CUR_ROW_STYLE"] + ROOM_HEIGHT]) == expected_styles
        assert mem[labels["ROOM_DLI_COUNT"]] == len(expected_transitions)
        assert (
            list(mem[labels["ROOM_DLI_STYLE"] : labels["ROOM_DLI_STYLE"] + len(expected_transitions)])
            == expected_transitions
        )

        # Inspect generated 32-byte ANTIC Display List
        assert list(mem[dlist_addr : dlist_addr + 3]) == [0x70, 0x70, 0x70]
        row0_expected = 0x44 | (0x80 if expected_styles[1] != expected_styles[0] else 0x00)
        assert mem[dlist_addr + 3] == row0_expected
        assert (mem[dlist_addr + 4] | (mem[dlist_addr + 5] << 8)) == vram_addr

        for r in range(1, ROOM_HEIGHT - 1):
            expected_op = 0x04 | (0x80 if expected_styles[r + 1] != expected_styles[r] else 0x00)
            assert mem[dlist_addr + 5 + r] == expected_op, f"Row {r} DLIST byte mismatch"

        # Row 23 never schedules a DLI
        assert mem[dlist_addr + 28] == 0x04
        # JVB termination back to room_dlist
        assert mem[dlist_addr + 29] == 0x41
        assert (mem[dlist_addr + 30] | (mem[dlist_addr + 31] << 8)) == dlist_addr

    # Test uniform-style room: game_enter must keep DLI disabled (NMIEN = $40)
    start_id = labels["START_ROOM"]
    mem[labels["ROOM_FLAGS_BASE"] + (start_id - 1)] = labels["ROOM_FLAG_UNIFORM_STYLE"]
    mem[labels["ROOM_ROWSTYLE_LO_BASE"] + (start_id - 1)] = 0
    mem[labels["ROOM_ROWSTYLE_HI_BASE"] + (start_id - 1)] = 0
    run_subroutine(mpu, labels["GAME_ENTER"])
    assert mem[labels["ROOM_DLI_COUNT"]] == 0
    assert mem[NMIEN] == 0x40
    assert (mem[dlist_addr + 3] & 0x80) == 0
    for r in range(1, ROOM_HEIGHT):
        assert (mem[dlist_addr + 5 + r] & 0x80) == 0


def test_room_dli_handler_switches_styles_and_preserves_registers() -> None:
    """Verify Row 0 setup and per-DLI style updates across the entire START_ROOM frame."""
    raw_mem = bytearray(65536)
    load_xex(XEX_PATH, raw_mem)
    labels = parse_labels(LAB_PATH)
    om = ObservableMemory(subject=raw_mem)
    mpu = MPU(memory=om)
    mpu.reset()

    wsync_cycles: list[int] = []
    colpf3_cycles: list[int] = []
    om.subscribe_to_write([0xD40A], lambda _addr, _val: wsync_cycles.append(mpu.processorCycles))
    om.subscribe_to_write([COLPF3], lambda _addr, _val: colpf3_cycles.append(mpu.processorCycles))

    run_subroutine(mpu, labels["GAME_ENTER"])

    assert raw_mem[0x02C0] == labels["HERO_COLOR"]  # PCOLR0
    assert raw_mem[0xD012] == labels["HERO_COLOR"]  # COLPM0

    dli_count = raw_mem[labels["ROOM_DLI_COUNT"]]
    if dli_count > 0:
        assert raw_mem[NMIEN] == 0xC0
    else:
        assert raw_mem[NMIEN] == 0x40

    row0_style = raw_mem[labels["CUR_ROW_STYLE"]]
    chbase_tbl = labels["STYLE_CHBASE"]
    colbk_tbl = labels["STYLE_COLBK"]
    colpf0_tbl = labels["STYLE_COLPF0"]
    colpf1_tbl = labels["STYLE_COLPF1"]
    colpf2_tbl = labels["STYLE_COLPF2"]
    colpf3_tbl = labels["STYLE_COLPF3"]

    assert raw_mem[CHBAS] == raw_mem[chbase_tbl + row0_style]
    assert raw_mem[CHBASE] == raw_mem[chbase_tbl + row0_style]
    assert raw_mem[COLOR4] == raw_mem[colbk_tbl + row0_style]
    assert raw_mem[COLBK] == raw_mem[colbk_tbl + row0_style]
    assert raw_mem[COLOR0] == raw_mem[colpf0_tbl + row0_style]
    assert raw_mem[COLPF0] == raw_mem[colpf0_tbl + row0_style]
    assert raw_mem[COLOR1] == raw_mem[colpf1_tbl + row0_style]
    assert raw_mem[COLPF1] == raw_mem[colpf1_tbl + row0_style]
    assert raw_mem[COLOR2] == raw_mem[colpf2_tbl + row0_style]
    assert raw_mem[COLPF2] == raw_mem[colpf2_tbl + row0_style]
    assert raw_mem[COLOR3] == raw_mem[colpf3_tbl + row0_style]
    assert raw_mem[COLPF3] == raw_mem[colpf3_tbl + row0_style]

    mpu.a = 0xAA
    mpu.x = 0x55
    mpu.y = 0x33

    for i in range(dli_count):
        wsync_cycles.clear()
        colpf3_cycles.clear()
        start_c = mpu.processorCycles
        total_cycles = run_interrupt_handler(mpu, labels["ROOM_DLI_HANDLER"])
        assert len(wsync_cycles) == 1, "Expected exactly one STA WSYNC in room_dli_handler"
        assert len(colpf3_cycles) == 1
        pre_wsync = wsync_cycles[0] - start_c
        post_wsync_writes = colpf3_cycles[0] - wsync_cycles[0]
        assert pre_wsync <= 40, f"Pre-WSYNC took {pre_wsync} cycles"
        assert post_wsync_writes <= 45, f"Post-WSYNC register writes took {post_wsync_writes} cycles"
        assert total_cycles <= 125

        target_style = raw_mem[labels["ROOM_DLI_STYLE"] + i]
        assert raw_mem[CHBASE] == raw_mem[chbase_tbl + target_style]
        assert raw_mem[COLBK] == raw_mem[colbk_tbl + target_style]
        assert raw_mem[COLPF0] == raw_mem[colpf0_tbl + target_style]
        assert raw_mem[COLPF1] == raw_mem[colpf1_tbl + target_style]
        assert raw_mem[COLPF2] == raw_mem[colpf2_tbl + target_style]
        assert raw_mem[COLPF3] == raw_mem[colpf3_tbl + target_style]
        # OS shadows stay Row 0 and Player 0 color is untouched by room DLIs
        assert raw_mem[CHBAS] == raw_mem[chbase_tbl + row0_style]
        assert raw_mem[COLOR4] == raw_mem[colbk_tbl + row0_style]
        assert raw_mem[0xD012] == labels["HERO_COLOR"]
        assert mpu.a == 0xAA
        assert mpu.x == 0x55
        assert mpu.y == 0x33

    assert raw_mem[labels["ZP_DLI_IDX"]] == 0


def test_initial_room_state_flow_and_static_screen_until_fire() -> None:
    """Verify full game state flow: static room screen while waiting for FIRE and single transition on FIRE."""
    raw_mem = bytearray(65536)
    load_xex(XEX_PATH, raw_mem)
    labels = parse_labels(LAB_PATH)
    vram = labels["SCREEN_VRAM"]
    vram_writes: list[int] = []

    om = ObservableMemory(subject=raw_mem)
    mpu = MPU(memory=om)
    mpu.reset()

    proj = load_project(ROOMS_YAML).project
    assert proj.start is not None
    start_room = proj.get_room(proj.start.room_id)
    assert start_room is not None
    expected_vram = _flatten_grid(compose_room(proj, start_room))

    # 1. Initialize game -> Title screen
    om[PORTA] = 0x0F
    om[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_INIT"])
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_TITLE_SCREEN"]

    # 2. Press FIRE -> enter STATE_INTRO, skip typewriter, release, and press FIRE -> enter STATE_GAME
    om[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_INTRO"]
    om[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    om[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    om[TRIG0] = 0x01
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    om[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]
    assert om[labels["CUR_ROOM_ID"]] == labels["START_ROOM"]
    assert (om[SDLSTL] | (om[SDLSTL + 1] << 8)) == labels["ROOM_DLIST"]
    assert (om[VDSLST] | (om[VDSLST + 1] << 8)) == labels["ROOM_DLI_HANDLER"]
    assert (om[VVBLKD] | (om[VVBLKD + 1] << 8)) == labels["GAME_VBI_DEFERRED"]
    expected_anim_active = min(1, len({inst.object_id for inst in start_room.instances if proj.get_object(inst.object_id) and proj.get_object(inst.object_id).is_animated}))
    assert (om[labels["ZP_ANIM_ACTIVE"]] != 0) == (expected_anim_active != 0)
    assert om[SDMCTL] == labels["GAME_DMACTL"]
    assert om[GRACTL] == labels["GAME_GRACTL"]
    assert om[0xD000] == labels["PLAYFIELD_LEFT_CC"] + 4 * labels["START_X"]
    assert om[0xD012] == labels["HERO_COLOR"]
    assert list(raw_mem[vram : vram + 960]) == expected_vram

    # Track VRAM writes during idle frames in STATE_GAME
    om.subscribe_to_write(range(vram, vram + 960), lambda addr, _val: vram_writes.append(addr))

    # 3. Hold FIRE down -> must NOT immediately trigger STATE_GAME -> GAME_OVER
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]

    # 4. Release FIRE and idle for several frames -> room remains static with zero VRAM redraws
    om[TRIG0] = 0x01
    for _ in range(5):
        run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
        assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]
    assert vram_writes == [], "game_update must not redraw SCREEN_VRAM every frame"

    # 5. Press FIRE -> single transition to STATE_GAME_OVER_FAILURE; holding FIRE stays there & PMG disabled
    om[TRIG0] = 0x00
    run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME_OVER_FAILURE"]
    assert om[GRACTL] == 0x00
    assert om[0xD000] == 0x00
    assert om[SDMCTL] == 0x22
    assert om[labels["ZP_ANIM_ACTIVE"]] == 0
    assert (om[VVBLKD] | (om[VVBLKD + 1] << 8)) == labels["XITVBV"]
    for _ in range(3):
        run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
        assert om[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME_OVER_FAILURE"]
    assert om[labels["ZP_ANIM_ACTIVE"]] == 0
    assert (om[VVBLKD] | (om[VVBLKD + 1] << 8)) == labels["XITVBV"]


def test_render_room_png_matches_editor_model(tmp_path: Path) -> None:
    """Verify tools/render_room_png.py produces exact 320x192 PNG matching room_editor's renderer."""
    proj = load_project(ROOMS_YAML).project
    pal_table = load_default_pal_palette()
    assert proj.start is not None

    # Test 'start' alias as well as all rooms by numeric ID
    targets: list[tuple[str, int]] = [("start", proj.start.room_id)] + [
        (str(r.id), r.id) for r in proj.rooms
    ]

    for spec, rid in targets:
        out_png = tmp_path / f"room_{spec}.png"
        proc = subprocess.run(
            [sys.executable, str(RENDER_PNG_SCRIPT), "--room", spec, "--out", str(out_png)],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"render_room_png.py failed: {proc.stderr}"
        assert out_png.exists()

        room = proj.get_room(rid)
        assert room is not None
        expected_rgb = bytearray()
        for r in range(ROOM_HEIGHT):
            scanlines = render_room_row_rgb(proj, room, r, pal_table)
            for scanline in scanlines:
                for red, green, blue in scanline:
                    expected_rgb.extend((red, green, blue, red, green, blue))

        with Image.open(out_png) as im:
            assert im.mode == "RGB"
            assert im.size == (ROOM_DISPLAY_WIDTH, ROOM_DISPLAY_HEIGHT)
            assert im.tobytes() == bytes(expected_rgb)
