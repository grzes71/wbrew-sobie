"""Comprehensive pytest + py65 tests for hero sprites, blocking map, and falling physics."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory

from room_editor.io.yaml_io import load_project
from room_editor.model.project import ROOM_HEIGHT, ROOM_WIDTH
from scripts.compile_hero_sprites import (
    HERO_DEFAULT_FRAME_TICKS,
    HERO_SPRITE_HEIGHT,
    HERO_SPRITE_WIDTH_CC,
    REQUIRED_HERO_SETS,
    HeroCompileError,
    compile_hero_sprites,
)
from scripts.rooms_compile import compile_rooms

ROOT_DIR = Path(__file__).resolve().parent.parent
XEX_PATH = ROOT_DIR / "funky_koval.xex"
LAB_PATH = ROOT_DIR / "gen" / "main.lab"
ROOMS_YAML = ROOT_DIR / "rooms.yaml"
HERO_JSON = ROOT_DIR / "sprites" / "project.sprite.json"
DEFAULT_MADS = Path("c:/Apps/Mad-Assembler-2.1.6/bin/windows_x86_64/mads.exe")

# Atari hardware & OS shadow addresses
HPOSP0 = 0xD000
SIZEP0 = 0xD008
COLPM0 = 0xD012
PRIOR = 0xD01B
GRACTL = 0xD01D
TRIG0 = 0xD010
PORTA = 0xD300
DMACTL = 0xD400
PMBASE = 0xD407
SDMCTL = 0x022F
GPRIOR = 0x026F
PCOLR0 = 0x02C0


def _find_mads() -> Path | None:
    if DEFAULT_MADS.exists():
        return DEFAULT_MADS
    found = shutil.which("mads") or shutil.which("mads.exe")
    return Path(found) if found else None


def _parse_labels(lab_path: Path) -> dict[str, int]:
    assert lab_path.exists(), f"Missing {lab_path}; run 'make all' first."
    labels: dict[str, int] = {}
    pat = re.compile(r"^[0-9a-fA-F]{2}\t([0-9a-fA-F]{4})\t([A-Za-z0-9_.\@?]+)")
    for line in lab_path.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if m:
            labels[m.group(2).upper()] = int(m.group(1), 16)
    return labels


def _load_xex(xex_path: Path, mem: bytearray) -> None:
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


def _run_subroutine(mpu: MPU, addr: int, max_steps: int = 300_000) -> int:
    mpu.sp = 0xFD
    mpu.stPushWord(0x0100 - 1)
    mpu.memory[0x0100] = 0x00
    mpu.pc = addr
    c0 = mpu.processorCycles
    steps = 0
    while mpu.pc != 0x0100 and steps < max_steps:
        mpu.step()
        steps += 1
    assert mpu.pc == 0x0100, f"Subroutine ${addr:04X} did not return within {max_steps} steps"
    return int(mpu.processorCycles - c0)


def _signed8(val: int) -> int:
    return val if val < 128 else val - 256


def _ref_blocking_grid(proj_yaml_path: Path, room_id: int) -> list[list[bool]]:
    """Compute reference 40x24 blocking bool grid for room_id using YAML/project SSOT."""
    proj = load_project(proj_yaml_path).project
    room = proj.get_room(room_id)
    assert room is not None
    _grid, sources = proj.compose_room_with_sources(room)
    objs = {o.id: o for o in proj.objects}
    return [
        [
            (
                sources[r][c] is not None
                and not objs[room.instances[sources[r][c]].object_id].non_blockable
            )
            for c in range(ROOM_WIDTH)
        ]
        for r in range(ROOM_HEIGHT)
    ]


def _read_block_map(mem: bytearray | ObservableMemory, bmap_addr: int) -> list[list[bool]]:
    out: list[list[bool]] = []
    for r in range(ROOM_HEIGHT):
        row_bits: list[bool] = []
        base = bmap_addr + r * 5
        for c in range(ROOM_WIDTH):
            b = mem[base + (c >> 3)]
            row_bits.append(bool(b & (0x80 >> (c & 7))))
        out.append(row_bits)
    return out


def _assert_no_trails(
    mem: bytearray | ObservableMemory,
    pmg_p0: int,
    top_y: int,
    expected_bytes: list[int] | None,
) -> None:
    """Assert PMG_P0 (256 B) holds exact expected 18-byte frame at [top_y..top_y+17] and 0 elsewhere."""
    buf = list(mem[pmg_p0 : pmg_p0 + 256])
    if expected_bytes is None:
        assert buf == [0] * 256, "Expected completely cleared PMG_P0 buffer"
        return
    assert len(expected_bytes) == HERO_SPRITE_HEIGHT
    expected_buf = [0] * 256
    expected_buf[top_y : top_y + HERO_SPRITE_HEIGHT] = expected_bytes
    assert buf == expected_buf


def _write_test_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 16 * 4, 4 * 8
    buf = bytearray(w * h)
    # Tile (0,0)=all 0 (transparent), (1,0)=solid 1, (2,0)=solid 2, (3,0)=solid 3
    for gy in range(4):
        for gx in range(16):
            val = (gx + gy * 16) % 4 if (gx, gy) != (0, 0) else 0
            if (gx, gy) == (1, 0):
                val = 1
            elif (gx, gy) == (2, 0):
                val = 2
            elif (gx, gy) == (3, 0):
                val = 3
            for py in range(8):
                for px in range(4):
                    buf[(gy * 8 + py) * w + (gx * 4 + px)] = val
    im = Image.new("P", (w, h))
    im.putpalette([0, 0, 0, 200, 100, 50, 50, 200, 100, 240, 240, 240] + [0] * (768 - 12))
    im.putdata(buf)
    im.save(path, format="PNG")


def _build_synthetic_hero_env(
    tmp_path: Path,
    *,
    placed: list[dict[str, Any]],
    start_x: int,
    start_y: int,
    extra_objects: list[dict[str, Any]] | None = None,
    sprite_doc_override: dict[str, Any] | None = None,
) -> tuple[MPU, bytearray, dict[str, int]]:
    mads = _find_mads()
    if mads is None:
        pytest.skip("MADS assembler binary not installed")

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    _write_test_png(proj_dir / "g.png")

    objects: list[dict[str, Any]] = [
        # id 1: 1x1 blockable solid
        {
            "id": 1,
            "name": "blk_1x1",
            "group": "g",
            "tags": [],
            "non-blockable": False,
            "colpf3": False,
            "animation_speed": 0,
            "frames": [{"x": 1, "y": 0, "w": 1, "h": 1}],
        },
        # id 2: 1x1 non-blockable solid
        {
            "id": 2,
            "name": "nb_1x1",
            "group": "g",
            "tags": [],
            "non-blockable": True,
            "colpf3": False,
            "animation_speed": 0,
            "frames": [{"x": 2, "y": 0, "w": 1, "h": 1}],
        },
        # id 3: 2x1 blockable with left transparent (0,0) and right solid (1,0)
        {
            "id": 3,
            "name": "blk_half_2x1",
            "group": "g",
            "tags": [],
            "non-blockable": False,
            "colpf3": False,
            "animation_speed": 0,
            "frames": [{"x": 0, "y": 0, "w": 2, "h": 1}],
        },
    ]
    if extra_objects:
        objects.extend(extra_objects)

    doc = {
        "version": 5,
        "object_groups": [
            {
                "name": "g",
                "image": "g.png",
                "pixel_mapping": [0, 1, 2, 3],
                "palettes": [{"name": "default", "colbk": 0, "colpf0": 1, "colpf1": 2, "colpf2": 3, "colpf3": 4}],
            }
        ],
        "objects": objects,
        "rooms": [
            {
                "id": 1,
                "name": "TestRoom",
                "pos": [0, 0],
                "row_groups": ["g"],
                "placed": placed,
            }
        ],
        "teleports": [],
        "start": {"room": 1, "x": start_x, "y": start_y},
    }
    yf = proj_dir / "rooms.yaml"
    yf.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    gen_dir = tmp_path / "gen"
    compile_rooms(yf, out_dir=gen_dir)

    if sprite_doc_override is not None:
        sjson = proj_dir / "hero.sprite.json"
        sjson.write_text(json.dumps(sprite_doc_override), encoding="utf-8")
        compile_hero_sprites(sjson, gen_dir)
    else:
        compile_hero_sprites(HERO_JSON, gen_dir)

    harness = tmp_path / "harness.asm"
    harness.write_text(
        "\n".join(
            [
                f"    icl '{(ROOT_DIR / 'hardware.asm').as_posix()}'",
                f"    icl '{(ROOT_DIR / 'zeropage.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'rooms_defs.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'hero_defs.asm').as_posix()}'",
                "SCREEN_VRAM     = $3000",
                "room_dlist      = $3480",
                "cur_row_style   = $34A0",
                "room_dli_style  = $34C0",
                "room_dli_count  = $34D8",
                "cur_room_id     = $34D9",
                "anim_room_count = $34E0",
                "anim_st_id      = $34E1",
                "anim_st_cnt     = $34E2",
                "anim_st_frame   = $34E3",
                "anim_st_vis     = $34E4",
                "anim_st_pend    = $34E5",
                "anim_st_pos     = $34E6",
                "anim_st_sbase   = $34E7",
                "anim_st_rep     = $34E8",
                "anim_slot_cur   = $34E9",
                "room_block_map  = $3700",
                "PMG_BASE        = $3800",
                "PMG_MISSILES    = PMG_BASE + $300",
                "PMG_P0          = PMG_BASE + $400",
                "PMG_P1          = PMG_BASE + $500",
                "PMG_P2          = PMG_BASE + $600",
                "PMG_P3          = PMG_BASE + $700",
                "    org $2000",
                "main_stub rts",
                f"    icl '{(ROOT_DIR / 'engine/room.asm').as_posix()}'",
                f"    icl '{(ROOT_DIR / 'engine/hero.asm').as_posix()}'",
                "ROOMS_ALIGN_CHARSETS = 1",
                "    org $6000",
                f"    icl '{(gen_dir / 'charsets.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'styles.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'objects.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'rooms.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'teleports.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'animations.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'hero_sprites.asm').as_posix()}'",
                "    org $02E0",
                "    .word main_stub",
                "",
            ]
        ),
        encoding="utf-8",
    )
    xex = tmp_path / "harness.xex"
    lab = tmp_path / "harness.lab"
    proc = subprocess.run(
        [str(mads), str(harness), f"-o:{xex}", f"-t:{lab}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"MADS failed:\n{proc.stdout}\n{proc.stderr}"
    mem = bytearray(65536)
    _load_xex(xex, mem)
    mpu = MPU(memory=mem)
    mpu.reset()
    return mpu, mem, _parse_labels(lab)


# ---------------------------------------------------------------------------
# 1. Hero Sprite Compiler & Generated Tables Tests
# ---------------------------------------------------------------------------


def test_generated_hero_tables_match_sprite_json(tmp_path: Path) -> None:
    """All 8 hero sets, names, 18B frames, durations, deduplication & error checks match JSON."""
    raw = json.loads(HERO_JSON.read_text(encoding="utf-8"))
    out1 = tmp_path / "hero_a"
    out2 = tmp_path / "hero_b"
    rep1 = compile_hero_sprites(HERO_JSON, out1)
    rep2 = compile_hero_sprites(HERO_JSON, out2)
    assert (out1 / "hero_defs.asm").read_text(encoding="utf-8") == (out2 / "hero_defs.asm").read_text(encoding="utf-8")
    assert (out1 / "hero_sprites.asm").read_text(encoding="utf-8") == (out2 / "hero_sprites.asm").read_text(encoding="utf-8")

    # Verify all 8 sets in compiled XEX match sprites/project.sprite.json byte-for-byte
    mem = bytearray(65536)
    _load_xex(XEX_PATH, mem)
    labels = _parse_labels(LAB_PATH)

    assert labels["HERO_SPRITE_HEIGHT"] == HERO_SPRITE_HEIGHT
    assert labels["HERO_SPRITE_WIDTH_CC"] == HERO_SPRITE_WIDTH_CC
    assert labels["HERO_NUM_SETS"] == 8

    sprites_by_id = {int(s["id"]): s for s in raw["sprites"]}
    total_frames_json = 0
    for sid, (expected_name, const_name) in REQUIRED_HERO_SETS.items():
        assert labels[const_name] == sid
        s_json = sprites_by_id[sid]
        assert s_json["description"] == expected_name
        assert s_json["width"] == 8 and s_json["height"] == 18

        cnt = mem[labels["HERO_SET_COUNT"] + sid]
        dur = mem[labels["HERO_SET_DUR"] + sid]
        base = mem[labels["HERO_SET_BASE"] + sid]
        assert cnt == len(s_json["frames"])
        assert dur == s_json["animation"]["frame_duration"]
        total_frames_json += cnt

        for f_idx, f_obj in enumerate(s_json["frames"]):
            expected_bytes = [int(row, 2) for row in f_obj["pixels"]]
            ptr = mem[labels["HERO_FRAME_LO"] + base + f_idx] | (
                mem[labels["HERO_FRAME_HI"] + base + f_idx] << 8
            )
            assert list(mem[ptr : ptr + 18]) == expected_bytes
            # Also verify per-set pointer aliases match flat table
            alias_ptr = mem[labels[f"HERO_SET_{sid}_LO"] + f_idx] | (
                mem[labels[f"HERO_SET_{sid}_HI"] + f_idx] << 8
            )
            assert alias_ptr == ptr

    assert labels["HERO_TOTAL_FRAMES"] == total_frames_json
    assert rep1.total_bytes > 0

    # Verify fallback timing when animation.frame_duration is omitted & deduplication of identical frames
    no_dur_doc = copy.deepcopy(raw)
    s8 = next(s for s in no_dur_doc["sprites"] if s["id"] == 8)
    del s8["animation"]
    s8["frames"].append(copy.deepcopy(s8["frames"][0]))
    p_nodur = tmp_path / "nodur.sprite.json"
    p_nodur.write_text(json.dumps(no_dur_doc), encoding="utf-8")
    rep_nd = compile_hero_sprites(p_nodur, tmp_path / "nd_out")
    assert rep_nd.sets[7].frame_duration == HERO_DEFAULT_FRAME_TICKS
    assert rep_nd.total_frames == rep1.total_frames + 1
    assert rep_nd.unique_frames == rep1.unique_frames  # identical appended frame deduplicated

    # Verify validation failures (missing ID, mismatched name, wrong height)
    for mut_fn in (
        lambda d: d["sprites"].__setitem__(0, {**d["sprites"][0], "id": 99}),
        lambda d: d["sprites"].__setitem__(0, {**d["sprites"][0], "description": "wrong-name"}),
        lambda d: d["sprites"].__setitem__(0, {**d["sprites"][0], "height": 16}),
    ):
        bad = copy.deepcopy(raw)
        mut_fn(bad)
        bp = tmp_path / "bad.sprite.json"
        bp.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(HeroCompileError):
            compile_hero_sprites(bp, tmp_path / "bad_out")


# ---------------------------------------------------------------------------
# 2. Blocking Map Tests (rooms.yaml + synthetic edge cases)
# ---------------------------------------------------------------------------


def test_blocking_map_matches_reference_all_rooms() -> None:
    """room_draw builds room_block_map matching reference across every room of rooms.yaml."""
    mem = bytearray(65536)
    _load_xex(XEX_PATH, mem)
    labels = _parse_labels(LAB_PATH)
    proj = load_project(ROOMS_YAML).project
    mpu = MPU(memory=mem)
    mpu.reset()

    bmap_addr = labels["ROOM_BLOCK_MAP"]
    assert labels["ROOM_BLOCK_MAP_SIZE"] == 120

    for room in proj.rooms:
        mem[bmap_addr : bmap_addr + 120] = b"\xff" * 120
        mpu.x = room.id
        _run_subroutine(mpu, labels["ROOM_DRAW"])

        expected = _ref_blocking_grid(ROOMS_YAML, room.id)
        actual = _read_block_map(mem, bmap_addr)
        assert actual == expected, f"room_block_map mismatch for room {room.id} ({room.name})"

        # Verify cell_blocked across every row 0..23 and out-of-bounds row 24..25 / col 40
        for r in range(ROOM_HEIGHT):
            for c in range(ROOM_WIDTH):
                mpu.x = c
                mpu.y = r
                _run_subroutine(mpu, labels["CELL_BLOCKED"])
                is_set = (mpu.p & 0x01) != 0
                assert is_set == expected[r][c]
                assert (mpu.a != 0) == expected[r][c]

        for r_oob in (ROOM_HEIGHT, ROOM_HEIGHT + 1):
            mpu.x = 0
            mpu.y = r_oob
            _run_subroutine(mpu, labels["CELL_BLOCKED"])
            assert (mpu.p & 0x01) == 0 and mpu.a == 0

        mpu.x = ROOM_WIDTH
        mpu.y = 0
        _run_subroutine(mpu, labels["CELL_BLOCKED"])
        assert (mpu.p & 0x01) == 0 and mpu.a == 0

    # Verify N=0 empty room clears room_block_map
    first_id = proj.rooms[0].id
    mem[labels["ROOM_INST_COUNT_BASE"] + (first_id - 1)] = 0
    mem[bmap_addr : bmap_addr + 120] = b"\xaa" * 120
    mpu.x = first_id
    _run_subroutine(mpu, labels["ROOM_DRAW"])
    assert mem[bmap_addr : bmap_addr + 120] == bytearray(120)


def test_blocking_map_synthetic_transparent_nonblockable_and_repeats(tmp_path: Path) -> None:
    """Non-blockable objects and transparent cells never set blocking bits; repeats set all stamped solid cells."""
    placed = [
        {"object": 2, "x": 4, "y": 5, "repeat-xy": [3, 2]},   # non-blockable -> never blocks
        {"object": 3, "x": 10, "y": 10, "repeat-x": 2},       # 2x1 [0, solid] x 2 -> cols 11 & 13 blocked, 10 & 12 unblocked!
        {"object": 1, "x": 20, "y": 15, "repeat-xy": [2, 2]}, # 2x2 blockable solid
    ]
    mpu, mem, labels = _build_synthetic_hero_env(tmp_path, placed=placed, start_x=0, start_y=0)
    mpu.x = 1
    _run_subroutine(mpu, labels["ROOM_DRAW"])

    expected = _ref_blocking_grid(tmp_path / "proj" / "rooms.yaml", 1)
    assert _read_block_map(mem, labels["ROOM_BLOCK_MAP"]) == expected
    assert not expected[5][4] and not expected[6][6]
    assert not expected[10][10] and expected[10][11] and not expected[10][12] and expected[10][13]
    assert all(expected[r][c] for r in (15, 16) for c in (20, 21))

    # row_range_blocked spot checks including col_b >= 40 clamping and row >= 24
    for row, ca, cb, exp in (
        (10, 9, 10, False),
        (10, 10, 11, True),
        (10, 12, 13, True),
        (10, 14, 15, False),
        (15, 38, 42, False),
        (24, 0, 39, False),
    ):
        mpu.y = row
        mpu.a = ca
        mpu.x = cb
        _run_subroutine(mpu, labels["ROW_RANGE_BLOCKED"])
        assert ((mpu.p & 0x01) != 0) == exp


# ---------------------------------------------------------------------------
# 3. Hero Physics, PMG Hardware Setup, Trail-Free Draws & Game Over Tests
# ---------------------------------------------------------------------------


def _ref_fall_trace(steps: list[int], start_y_cell: int, blocked_rows: set[int]) -> tuple[list[int], int | None]:
    """Reference Python simulation of hero_fall_steps returning (top_pmg_y_per_frame, landed_row or None)."""
    top_to_bot = 32 - HERO_SPRITE_HEIGHT  # 14
    y_top = (start_y_cell + 1) * 8 + top_to_bot
    trace: list[int] = []
    idx = 0
    for _ in range(300):
        step = steps[idx]
        if idx < len(steps) - 1:
            idx += 1
        old_bot = y_top - top_to_bot
        old_row = old_bot >> 3
        new_bot = old_bot + step
        new_row = new_bot >> 3
        if new_row != old_row and new_row in blocked_rows:
            y_top = (new_row << 3) + top_to_bot
            trace.append(y_top)
            return trace, new_row
        y_top += step
        if y_top >= 224:
            return trace, None
        trace.append(y_top)
    raise AssertionError("Reference trace did not terminate")


def test_hero_standing_no_movement_and_pmg_registers(tmp_path: Path) -> None:
    """Supported start stays STANDING with zero PMG redraws after init; verify PMG & disable registers."""
    # Hero starts at x=6, y=9 (bottom at row 10); place solid brick at x=6, y=10 -> supported!
    mpu, mem, labels = _build_synthetic_hero_env(
        tmp_path,
        placed=[{"object": 1, "x": 6, "y": 10}],
        start_x=6,
        start_y=9,
    )
    om = ObservableMemory(subject=mem)
    mpu_obs = MPU(memory=om)
    mpu_obs.reset()

    mpu_obs.x = 1
    _run_subroutine(mpu_obs, labels["ROOM_DRAW"])
    mpu_obs.x = labels["START_X"]
    mpu_obs.y = labels["START_Y"]
    _run_subroutine(mpu_obs, labels["HERO_INIT"])

    assert mem[PMBASE] == labels["PMG_BASE"] >> 8
    assert mem[SIZEP0] == labels["HERO_SIZE"] == 0
    assert mem[PCOLR0] == labels["HERO_COLOR"]
    assert mem[COLPM0] == labels["HERO_COLOR"]
    assert mem[HPOSP0] == labels["PLAYFIELD_LEFT_CC"] + 4 * 6
    assert mem[GPRIOR] == labels["GAME_PRIOR"]
    assert mem[PRIOR] == labels["GAME_PRIOR"]
    assert mem[GRACTL] == labels["GAME_GRACTL"] == 0x02

    assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_STANDING"]
    assert mem[labels["ZP_HERO_ANIM_SET"]] == labels["HERO_STAND_SET"]
    assert mem[labels["ZP_HERO_ANIM_FRAME"]] == labels["HERO_STAND_FRAME"]

    stand_ptr = mem[labels["HERO_FRAME_LO"] + mem[labels["HERO_SET_BASE"] + labels["HERO_STAND_SET"]] + 0] | (
        mem[labels["HERO_FRAME_HI"] + mem[labels["HERO_SET_BASE"] + labels["HERO_STAND_SET"]] + 0] << 8
    )
    stand_bytes = list(mem[stand_ptr : stand_ptr + 18])
    init_y = (9 + 1) * 8 + labels["HERO_TOP_TO_PF_BOTTOM"]
    assert mem[labels["ZP_HERO_Y"]] == init_y
    _assert_no_trails(mem, labels["PMG_P0"], init_y, stand_bytes)

    # Track writes to PMG_P0 and HPOSP0 during hero_update -> ZERO writes when staying STANDING
    pmg_writes: list[int] = []
    om.subscribe_to_write(range(labels["PMG_P0"], labels["PMG_P0"] + 256), lambda a, _v: pmg_writes.append(a))
    om.subscribe_to_write([HPOSP0], lambda a, _v: pmg_writes.append(a))
    for _ in range(10):
        _run_subroutine(mpu_obs, labels["HERO_UPDATE"])
        assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_STANDING"]
        assert mem[labels["ZP_HERO_Y"]] == init_y
    assert pmg_writes == []

    # Verify hero_pmg_disable cleanly turns PMG off
    _run_subroutine(mpu_obs, labels["HERO_PMG_DISABLE"])
    assert mem[GRACTL] == 0x00
    assert mem[HPOSP0] == 0x00
    assert mem[SDMCTL] == 0x22 and mem[DMACTL] == 0x22
    assert mem[GPRIOR] == 0x00 and mem[PRIOR] == 0x00
    _assert_no_trails(mem, labels["PMG_P0"], 0, None)


def test_hero_falling_landing_narrow_ledges_trails_and_step8_no_tunnelling(tmp_path: Path) -> None:
    """Verify exact fall steps, narrow left/right ledge landings, step=8 no-tunnelling, and zero trails."""
    raw_sprite = json.loads(HERO_JSON.read_text(encoding="utf-8"))

    def _frame_bytes_for(set_id: int, f_idx: int) -> list[int]:
        s_obj = next(s for s in raw_sprite["sprites"] if int(s["id"]) == set_id)
        return [int(r, 2) for r in s_obj["frames"][f_idx]["pixels"]]

    # 1. Fall from y=1 onto floor at row 6; check left-edge (col 5) and right-edge (col 6) narrow 1-cell ledges
    for idx, ledge_col in enumerate((5, 6)):
        sub = tmp_path / f"ledge_{idx}"
        mpu, mem, labels = _build_synthetic_hero_env(
            sub,
            placed=[{"object": 1, "x": ledge_col, "y": 6}],
            start_x=5,
            start_y=1,
        )
        steps_tbl = list(mem[labels["HERO_FALL_STEPS"] : labels["HERO_FALL_STEPS"] + labels["HERO_FALL_STEP_COUNT"]])
        ref_trace, ref_row = _ref_fall_trace(steps_tbl, 1, {6})
        assert ref_row == 6

        mpu.x = 1
        _run_subroutine(mpu, labels["ROOM_DRAW"])
        mpu.x = labels["START_X"]
        mpu.y = labels["START_Y"]
        _run_subroutine(mpu, labels["HERO_INIT"])
        assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_FALLING"]

        stand_bytes = _frame_bytes_for(1, 0)
        fall_bytes = _frame_bytes_for(8, 0)
        observed_trace: list[int] = []
        for fnum in range(len(ref_trace)):
            _run_subroutine(mpu, labels["HERO_UPDATE"])
            cur_y = mem[labels["ZP_HERO_Y"]]
            observed_trace.append(cur_y)
            is_last = fnum == len(ref_trace) - 1
            if is_last:
                assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_STANDING"]
                _assert_no_trails(mem, labels["PMG_P0"], cur_y, stand_bytes)
            else:
                assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_FALLING"]
                _assert_no_trails(mem, labels["PMG_P0"], cur_y, fall_bytes)

        assert observed_trace == ref_trace

    # 2. Extreme step=8 across two consecutive row boundaries onto a 1-row-thick ledge (no tunnelling!)
    sub8 = tmp_path / "step8"
    mpu8, mem8, labels8 = _build_synthetic_hero_env(
        sub8,
        placed=[{"object": 1, "x": 10, "y": 12}],  # 1-row-thick ledge at row 12 only
        start_x=10,
        start_y=8,
    )
    # Patch step table in RAM to [8, 8, ...] before falling
    step_cnt = labels8["HERO_FALL_STEP_COUNT"]
    for i in range(step_cnt):
        mem8[labels8["HERO_FALL_STEPS"] + i] = 8

    mpu8.x = 1
    _run_subroutine(mpu8, labels8["ROOM_DRAW"])
    mpu8.x = labels8["START_X"]
    mpu8.y = labels8["START_Y"]
    _run_subroutine(mpu8, labels8["HERO_INIT"])

    ref8, row8 = _ref_fall_trace([8] * step_cnt, 8, {12})
    assert row8 == 12
    stand_bytes = _frame_bytes_for(1, 0)
    fall_bytes = _frame_bytes_for(8, 0)
    obs8: list[int] = []
    for fnum in range(len(ref8)):
        _run_subroutine(mpu8, labels8["HERO_UPDATE"])
        cy = mem8[labels8["ZP_HERO_Y"]]
        obs8.append(cy)
        _assert_no_trails(
            mem8,
            labels8["PMG_P0"],
            cy,
            stand_bytes if fnum == len(ref8) - 1 else fall_bytes,
        )
    assert obs8 == ref8
    assert mem8[labels8["ZP_HERO_STATE"]] == labels8["HERO_STATE_STANDING"]


def test_hero_fall_animation_multiframe_cycling_and_upward_delta_clear(tmp_path: Path) -> None:
    """Multi-frame set 8 cycles frames according to frame_duration and hero_pmg_draw clears UP deltas without trails."""
    raw = json.loads(HERO_JSON.read_text(encoding="utf-8"))
    s8 = next(s for s in raw["sprites"] if s["id"] == 8)
    f_a = ["11111111" if r % 2 == 0 else "00000000" for r in range(18)]
    f_b = ["01010101" for _ in range(18)]
    f_c = ["10101010" for _ in range(18)]
    s8["animation"]["frame_duration"] = 2
    s8["frames"] = [{"pixels": f_a}, {"pixels": f_b}, {"pixels": f_c}]
    fb_list = [[int(row, 2) for row in f["pixels"]] for f in s8["frames"]]

    mpu, mem, labels = _build_synthetic_hero_env(
        tmp_path,
        placed=[],
        start_x=2,
        start_y=2,
        sprite_doc_override=raw,
    )
    mpu.x = 1
    _run_subroutine(mpu, labels["ROOM_DRAW"])
    mpu.x = labels["START_X"]
    mpu.y = labels["START_Y"]
    _run_subroutine(mpu, labels["HERO_INIT"])
    _assert_no_trails(mem, labels["PMG_P0"], mem[labels["ZP_HERO_Y"]], fb_list[0])

    expected_frames = [0, 1, 1, 2, 2, 0, 0]
    for exp_f in expected_frames:
        _run_subroutine(mpu, labels["HERO_UPDATE"])
        assert mem[labels["ZP_HERO_ANIM_FRAME"]] == exp_f
        _assert_no_trails(mem, labels["PMG_P0"], mem[labels["ZP_HERO_Y"]], fb_list[exp_f])

    # Also test moving UP cleanly clears only vacated bottom scanlines without trails
    mem[labels["ZP_HERO_Y"]] = mem[labels["ZP_HERO_DRAW_Y"]] - 5
    mem[labels["ZP_HERO_DIRTY"]] = 1
    _run_subroutine(mpu, labels["HERO_PMG_DRAW"])
    _assert_no_trails(mem, labels["PMG_P0"], mem[labels["ZP_HERO_Y"]], fb_list[expected_frames[-1]])


def test_hero_bottom_row_y23_fall_triggers_game_over_no_overflow(tmp_path: Path) -> None:
    """Starting at y=23 in an unblocked column falls cleanly out the bottom and triggers STATE_GAME_OVER_FAILURE."""
    mem = bytearray(65536)
    _load_xex(XEX_PATH, mem)
    labels = _parse_labels(LAB_PATH)
    mpu = MPU(memory=mem)
    mpu.reset()

    # Run Room 1 up to state machine entering STATE_GAME, then inspect START_Y / patch START_Y test in harness?
    # Verify via full state machine with synthetic bottom-fall check:
    steps_tbl = list(mem[labels["HERO_FALL_STEPS"] : labels["HERO_FALL_STEPS"] + labels["HERO_FALL_STEP_COUNT"]])
    ref_trace, landed = _ref_fall_trace(steps_tbl, 23, set())
    assert landed is None and len(ref_trace) >= 1

    # Enter Room 1 cleanly via state machine
    mem[PORTA] = 0x0F
    mem[TRIG0] = 0x01
    _run_subroutine(mpu, labels["STATE_MACHINE_INIT"])
    mem[TRIG0] = 0x00
    _run_subroutine(mpu, labels["STATE_MACHINE_STEP"])  # -> INTRO
    mem[TRIG0] = 0x01
    _run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    mem[TRIG0] = 0x00
    _run_subroutine(mpu, labels["STATE_MACHINE_STEP"])  # skip intro
    mem[TRIG0] = 0x01
    _run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    mem[TRIG0] = 0x00
    _run_subroutine(mpu, labels["STATE_MACHINE_STEP"])  # -> GAME
    mem[TRIG0] = 0x01
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]

    # Place hero cleanly at y=23 over an unblocked column in Room 1 (clear col 35..36 in row 24 is already free)
    # Re-init hero via hero_init(X=35, Y=23) after clearing blocking bits? Wait row 24+ is ALWAYS unblocked!
    mpu.x = 35
    mpu.y = 23
    _run_subroutine(mpu, labels["HERO_INIT"])
    assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_FALLING"]
    assert mem[labels["ZP_HERO_FELL_OUT"]] == 0

    prev_y = mem[labels["ZP_HERO_Y"]]
    for expected_y in ref_trace:
        _run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
        assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME"]
        cur_y = mem[labels["ZP_HERO_Y"]]
        assert cur_y == expected_y
        assert cur_y > prev_y  # Strict monotonic increase, never 8-bit overflow!
        assert mem[labels["ZP_HERO_FELL_OUT"]] == 0
        prev_y = cur_y

    # Next frame reaches PLAYFIELD_BOTTOM_PMG_Y (224) -> transitions cleanly to STATE_GAME_OVER_FAILURE & disables PMG
    _run_subroutine(mpu, labels["STATE_MACHINE_STEP"])
    assert mem[labels["ZP_HERO_FELL_OUT"]] == 1
    assert mem[labels["ZP_HERO_Y"]] >= labels["PLAYFIELD_BOTTOM_PMG_Y"]
    assert mem[labels["ZP_HERO_Y"]] <= 255
    assert mem[labels["ZP_CURRENT_STATE"]] == labels["STATE_GAME_OVER_FAILURE"]
    assert mem[GRACTL] == 0x00
    assert mem[HPOSP0] == 0x00
    assert mem[SDMCTL] == 0x22
    _assert_no_trails(mem, labels["PMG_P0"], 0, None)


def test_real_game_start_room_hero_falls_and_lands_in_py65() -> None:
    """In production rooms.yaml START_ROOM, hero spawns at START_X/Y and obeys physics & blocking map."""
    mem = bytearray(65536)
    _load_xex(XEX_PATH, mem)
    labels = _parse_labels(LAB_PATH)
    mpu = MPU(memory=mem)
    mpu.reset()

    proj = load_project(ROOMS_YAML).project
    assert proj.start is not None
    expected_grid = _ref_blocking_grid(ROOMS_YAML, proj.start.room_id)
    steps_tbl = list(mem[labels["HERO_FALL_STEPS"] : labels["HERO_FALL_STEPS"] + labels["HERO_FALL_STEP_COUNT"]])

    col_l = proj.start.x
    col_r = min(ROOM_WIDTH - 1, (proj.start.x * 4 + HERO_SPRITE_WIDTH_CC - 1) // 4)
    blocked_rows = {
        r
        for r in range(ROOM_HEIGHT)
        if any(expected_grid[r][c] for c in range(col_l, col_r + 1))
    }

    _run_subroutine(mpu, labels["GAME_ENTER"])
    assert mem[labels["CUR_ROOM_ID"]] == proj.start.room_id
    assert mem[HPOSP0] == 48 + 4 * proj.start.x
    assert mem[PCOLR0] == labels["HERO_COLOR"] and mem[COLPM0] == labels["HERO_COLOR"]
    assert mem[SIZEP0] == 0

    if (proj.start.y + 1) in blocked_rows:
        assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_STANDING"]
    else:
        assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_FALLING"]
        ref_trace, landed_row = _ref_fall_trace(steps_tbl, proj.start.y, {r for r in blocked_rows if r > proj.start.y})
        obs = []
        for _ in range(len(ref_trace)):
            _run_subroutine(mpu, labels["HERO_UPDATE"])
            obs.append(mem[labels["ZP_HERO_Y"]])
        assert obs == ref_trace
        if landed_row is not None:
            assert mem[labels["ZP_HERO_STATE"]] == labels["HERO_STATE_STANDING"]
        else:
            _run_subroutine(mpu, labels["HERO_UPDATE"])
            assert mem[labels["ZP_HERO_FELL_OUT"]] == 1
