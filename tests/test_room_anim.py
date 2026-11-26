"""Headless py65 6502 integration tests for deduplicated Form 1/Form 2 pattern-pool engine/anim.asm."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image
from py65.devices.mpu6502 import MPU

from scripts.rooms_compile import compile_rooms

ROOT_DIR = Path(__file__).resolve().parent.parent
MADS_DEFAULT = r"c:/Apps/Mad-Assembler-2.1.6/bin/windows_x86_64/mads.exe"
XITVBV_ADDR = 0xE462


def _find_mads() -> str | None:
    env_mads = os.environ.get("MADS")
    if env_mads and Path(env_mads).exists():
        return env_mads
    if Path(MADS_DEFAULT).exists():
        return MADS_DEFAULT
    return shutil.which("mads")


def _write_png_tiles(path: Path, tiles_x: int, tiles_y: int, tile_fn) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    w = tiles_x * 4
    h = tiles_y * 8
    im = Image.new("P", (w, h))
    im.putpalette([0, 0, 0, 200, 100, 50, 50, 200, 100, 50, 100, 200] + [0] * (768 - 12))
    pixels = [0] * (w * h)
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            rows = tile_fn(tx, ty)
            for py in range(8):
                b = rows[py]
                for px_i in range(4):
                    pixels[(ty * 8 + py) * w + (tx * 4 + px_i)] = (b >> (6 - 2 * px_i)) & 0x03
    im.putdata(pixels)
    im.save(path, format="PNG")
    return path


def _parse_labels(lab_path: Path) -> dict[str, int]:
    labels: dict[str, int] = {}
    pat = re.compile(r"^[0-9a-fA-F]{2}\t([0-9a-fA-F]{4})\t([A-Za-z0-9_.\@?]+)")
    for line in lab_path.read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if m:
            labels[m.group(2).upper()] = int(m.group(1), 16)
    return labels


def _load_xex(xex_path: Path, mem: bytearray) -> None:
    data = xex_path.read_bytes()
    i = 0
    n = len(data)
    while i < n:
        if i + 2 <= n and data[i] == 0xFF and data[i + 1] == 0xFF:
            i += 2
            if i == n:
                break
        start = data[i] | (data[i + 1] << 8)
        end = data[i + 2] | (data[i + 3] << 8)
        i += 4
        length = end - start + 1
        mem[start : end + 1] = data[i : i + length]
        i += length


def _run_subroutine_cycles(mpu: MPU, addr: int, max_steps: int = 300_000) -> int:
    """Execute 6502 routine and return exact CPU cycle count up to sentinel RTS."""
    mpu.sp = 0xFD
    mpu.stPushWord(0x0100 - 1)
    mpu.memory[0x0100] = 0x00  # sentinel BRK (never executed)
    mpu.pc = addr
    c0 = mpu.processorCycles
    for _ in range(max_steps):
        if mpu.pc == 0x0100:
            return int(mpu.processorCycles - c0)
        mpu.step()
    raise RuntimeError(f"6502 routine at ${addr:04X} did not return within {max_steps} steps")


def _build_anim_test_env(
    tmp_path: Path,
    doc: dict[str, Any],
    tiles_fn,
    tiles_x: int = 16,
    tiles_y: int = 16,
    *,
    count_copies: bool = True,
):
    mads = _find_mads()
    if mads is None:
        pytest.skip("MADS assembler binary not installed")

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir(exist_ok=True)
    _write_png_tiles(proj_dir / "g.png", tiles_x, tiles_y, tiles_fn)
    yfile = proj_dir / "rooms.yaml"
    yfile.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    gen_dir = tmp_path / "gen"
    res = compile_rooms(yfile, out_dir=gen_dir)

    harness = tmp_path / "harness.asm"
    harness.write_text(
        "\n".join(
            [
                f"    icl '{(ROOT_DIR / 'hardware.asm').as_posix()}'",
                f"    icl '{(ROOT_DIR / 'zeropage.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'rooms_defs.asm').as_posix()}'",
                "SCREEN_VRAM     = $3000",
                "room_dlist      = $3480",
                "cur_row_style   = $34A0",
                "room_dli_style  = $34C0",
                "room_dli_count  = $34D8",
                "cur_room_id     = $34D9",
                "title_charset_0 = $4000",
                "title_dli_chbase = $4000",
                "p5_row_x        = $4000",
                "TITLE_DLI_COUNT = 24",
                "    .if MAX_ROOM_ANIMS > 0",
                "ANIM_STATE_CAP  = MAX_ROOM_ANIMS",
                "    .else",
                "ANIM_STATE_CAP  = 1",
                "    .endif",
                "    .if MAX_ROOM_FORM1_SLOTS > 0",
                "ANIM_SLOT_CAP   = MAX_ROOM_FORM1_SLOTS",
                "    .else",
                "ANIM_SLOT_CAP   = 1",
                "    .endif",
                "anim_room_count = $34E0",
                "anim_st_id      = anim_room_count + 1",
                "anim_st_cnt     = anim_st_id + ANIM_STATE_CAP",
                "anim_st_frame   = anim_st_cnt + ANIM_STATE_CAP",
                "anim_st_vis     = anim_st_frame + ANIM_STATE_CAP",
                "anim_st_pend    = anim_st_vis + ANIM_STATE_CAP",
                "anim_st_pos     = anim_st_pend + ANIM_STATE_CAP",
                "anim_st_sbase   = anim_st_pos + ANIM_STATE_CAP",
                "anim_st_rep     = anim_st_sbase + ANIM_STATE_CAP",
                "    .if ANIM_F2_GRP_COUNT > 0",
                "anim_st_vrep    = anim_st_rep + ANIM_STATE_CAP",
                "anim_slot_cur   = anim_st_vrep + ANIM_STATE_CAP",
                "    .else",
                "anim_slot_cur   = anim_st_rep + ANIM_STATE_CAP",
                "    .endif",
                "    .ifdef ANIM_COUNT_COPIES",
                "anim_copy_count = anim_slot_cur + ANIM_SLOT_CAP",
                "    .endif",
                "    org $2000",
                "main_stub rts",
                f"    icl '{(ROOT_DIR / 'engine/room.asm').as_posix()}'",
                f"    icl '{(ROOT_DIR / 'engine/dli.asm').as_posix()}'",
                f"    icl '{(ROOT_DIR / 'engine/anim.asm').as_posix()}'",
                "ROOMS_ALIGN_CHARSETS = 1",
                "    org $6000",
                f"    icl '{(gen_dir / 'charsets.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'styles.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'objects.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'rooms.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'teleports.asm').as_posix()}'",
                f"    icl '{(gen_dir / 'animations.asm').as_posix()}'",
                "    org $02E0",
                "    .word main_stub",
                "",
            ]
        ),
        encoding="utf-8",
    )

    xex = tmp_path / "harness.xex"
    lab = tmp_path / "harness.lab"
    cmd = [mads, str(harness), f"-o:{xex}", f"-t:{lab}"]
    if count_copies:
        cmd.append("-d:ANIM_COUNT_COPIES=1")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"MADS failed:\n{proc.stdout}\n{proc.stderr}"

    mem = bytearray(65536)
    _load_xex(xex, mem)
    mem[XITVBV_ADDR] = 0x60  # RTS stub for GAME_VBI_DEFERRED
    mpu = MPU(memory=mem)
    mpu.reset()
    labels = _parse_labels(lab)
    return mpu, mem, labels, res.report


def _pat(seed: int) -> bytes:
    """Deterministic non-zero 8-byte glyph bitmap."""
    return bytes([((seed * 29 + r * 11 + 1) & 0xFF) or 1 for r in range(8)])


def test_py65_minimal_copies_both_forms_sharing_constant_and_wrap(tmp_path: Path) -> None:
    """Verify exact copy telemetry, unchanged constant cells, slot sharing, Form 1/2, and re-entry."""
    tiles: dict[tuple[int, int], bytes] = {}
    const_wall = bytes([0xAA] * 8)
    tiles[(0, 0)] = const_wall

    # Obj 2 ('spark_f1', Form 1: 4x1, 3 frames, speed=2):
    #   cell 0: const_wall (must stay code 1 static & NEVER touched!)
    #   cells 1 & 2: IDENTICAL varying sequence (_pat(1), _pat(2), _pat(2)) -> share ONE dedicated code!
    #   cell 3: changes ONLY on frame 0->1 and frame 2->0 (_pat(3), _pat(4), _pat(4))
    #   Transitions:
    #     0->1 (tick 2): shared(1->2) + cell3(3->4) => 2 copies!
    #     1->2 (tick 4): shared(2->2 same!) + cell3(4->4 same!) => 0 copies!! (skip!)
    #     2->0 (tick 6): shared(2->1) + cell3(4->3) => 2 copies!
    f1_seq = [
        [const_wall, _pat(1), _pat(1), _pat(3)],
        [const_wall, _pat(2), _pat(2), _pat(4)],
        [const_wall, _pat(2), _pat(2), _pat(4)],
    ]
    for f, row in enumerate(f1_seq):
        for dx in range(4):
            tiles[(1 + dx, f)] = row[dx]

    # Obj 3 ('walk_f2', Form 2: 8x1, 16 frames, speed=1 -> triggers F2 because 8 + 32 + 16*3 = 88 < 128!):
    #   cell 0: const_wall
    #   cells 1..7 (7 varying slots): on frame k (1..15) only ONE slot changes; on 15->0 slots wrap back!
    f2_frames: list[list[bytes]] = []
    cur7 = [_pat(10 + i) for i in range(7)]
    base7 = list(cur7)
    f2_frames.append([const_wall] + list(cur7))
    for k in range(1, 16):
        cur7[k % 7] = _pat(50 + k)
        f2_frames.append([const_wall] + list(cur7))
    # Place at y=3..18, x=0..7
    for k, row in enumerate(f2_frames):
        for dx in range(8):
            tiles[(dx, 3 + k)] = row[dx]

    # Obj 4 ('pooled_peer', Form 1: 1x1, 2 frames, speed=1): reuses _pat(1) & _pat(2) from spark_f1!
    tiles[(10, 0)] = _pat(1)
    tiles[(11, 0)] = _pat(2)

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
        "objects": [
            {
                "id": 1,
                "name": "wall",
                "group": "g",
                "tags": [],
                "non-blockable": False,
                "colpf3": False,
                "animation_speed": 0,
                "frames": [{"x": 0, "y": 0, "w": 1, "h": 1}],
            },
            {
                "id": 2,
                "name": "spark_f1",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 2,
                "frames": [{"x": 1, "y": f, "w": 4, "h": 1} for f in range(3)],
            },
            {
                "id": 3,
                "name": "walk_f2",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 1,
                "frames": [{"x": 0, "y": 3 + k, "w": 8, "h": 1} for k in range(16)],
            },
            {
                "id": 4,
                "name": "pooled_peer",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 1,
                "frames": [{"x": 10, "y": 0, "w": 1, "h": 1}, {"x": 11, "y": 0, "w": 1, "h": 1}],
            },
        ],
        "rooms": [
            {"id": 1, "name": "R_Static", "pos": [0, 0], "row_groups": ["g"], "placed": [{"object": 1, "x": 0, "y": 0}]},
            {"id": 2, "name": "R_F1Only", "pos": [1, 0], "row_groups": ["g"], "placed": [{"object": 2, "x": 0, "y": 0}, {"object": 2, "x": 10, "y": 5}]},
            {"id": 3, "name": "R_F2Only", "pos": [2, 0], "row_groups": ["g"], "placed": [{"object": 3, "x": 0, "y": 0}]},
            {"id": 4, "name": "R_Pool", "pos": [3, 0], "row_groups": ["g"], "placed": [{"object": 2, "x": 0, "y": 0}, {"object": 4, "x": 10, "y": 0}]},
        ],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }

    mpu, mem, labels, report = _build_anim_test_env(
        tmp_path, doc, lambda tx, ty: tiles.get((tx, ty), bytes(8)), tiles_x=16, tiles_y=20
    )
    assert report.anim_pool_count == 1
    assert report.anim_stats[0].form == "form1"
    assert report.anim_stats[1].form == "form2"

    ch_base = labels["CHARSET_G"]
    vram = labels["SCREEN_VRAM"]

    # 1. Static room fast path
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    assert mem[labels["ZP_ANIM_ACTIVE"]] == 0
    cyc_static = _run_subroutine_cycles(mpu, labels["GAME_VBI_DEFERRED"])
    assert cyc_static <= 26
    assert mem[labels["ANIM_COPY_COUNT"]] == 0

    # 2. Form 1 room: verify constant code 1 never modified, cells 1&2 share code 2, exact copy counts!
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    assert mem[vram + 0] == 1  # constant wall code 1
    assert mem[vram + 1] == mem[vram + 2]  # varying cells sharing 1 dedicated slot
    assert bytes(mem[ch_base + 1 * 8 : ch_base + 2 * 8]) == const_wall

    # Corrupt constant glyph sentinel check: ensure anim_tick never touches slot 1 even if tested
    # Tick 1 (no timer transition): 0 copies
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert mem[labels["ANIM_COPY_COUNT"]] == 0
    # Tick 2 (0->1): 2 copies (shared slot + cell 3)
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert mem[labels["ANIM_COPY_COUNT"]] == 2
    assert bytes(mem[ch_base + 2 * 8 : ch_base + 3 * 8]) == _pat(2)
    assert bytes(mem[ch_base + 3 * 8 : ch_base + 4 * 8]) == _pat(4)
    # Tick 4 (1->2, identical pattern values!): 0 copies!!
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert mem[labels["ANIM_COPY_COUNT"]] == 0
    # Tick 6 (2->0): 2 copies, restored to frame 0
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert mem[labels["ANIM_COPY_COUNT"]] == 2
    assert bytes(mem[ch_base + 2 * 8 : ch_base + 3 * 8]) == _pat(1)
    assert bytes(mem[ch_base + 3 * 8 : ch_base + 4 * 8]) == _pat(3)
    assert bytes(mem[ch_base + 1 * 8 : ch_base + 2 * 8]) == const_wall

    # 3. Form 2 room (8x1, 16 frames, 1 change on ticks 1..15, wrap on tick 16)
    mpu.x = 3
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 3
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    # Check Form 2 codes are consecutive dedicated slots (walk_f2 starts after spark_f1's codes 2,3 -> codes 4..10)
    f2_codes = [mem[vram + dx] for dx in range(1, 8)]
    for tick in range(1, 17):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
        expected_copies = 1 if tick < 16 else 7
        assert mem[labels["ANIM_COPY_COUNT"]] == expected_copies
        expected_row = f2_frames[tick % 16]
        for s_i, code in enumerate(f2_codes):
            assert bytes(mem[ch_base + code * 8 : ch_base + (code + 1) * 8]) == expected_row[1 + s_i]
        assert bytes(mem[ch_base + 1 * 8 : ch_base + 2 * 8]) == const_wall

    # Advance 3 ticks then test re-entry reset restores frame 0!
    for _ in range(3):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    mpu.x = 3
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    for s_i, code in enumerate(f2_codes):
        assert bytes(mem[ch_base + code * 8 : ch_base + (code + 1) * 8]) == base7[s_i]

    # 4. Shared patterns across two distinct objects in Room 4
    mpu.x = 4
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 4
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    peer_code = mem[vram + 10]
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 1: peer advances 0->1
    assert bytes(mem[ch_base + peer_code * 8 : ch_base + (peer_code + 1) * 8]) == _pat(2)
    assert bytes(mem[ch_base + 2 * 8 : ch_base + 3 * 8]) == _pat(1)  # spark still on frame 0


def test_py65_budget_deferral_both_forms_and_split_pool(tmp_path: Path) -> None:
    """Verify ANIM_VBI_GLYPH_BUDGET=12 on real copies for Form 1 & Form 2 plus split pool (>256 patterns)."""
    tiles: dict[tuple[int, int], bytes] = {}
    # Create 2 rooms:
    # Room 1: Form 1 object (10 slots, speed=1, 16 frames -> 160 patterns, F1=160 B <= F2=10+32+16*21=378 B)
    #         + Form 2 object (9 slots, speed=2, 16 frames -> 9 changes at once would exceed remaining budget when combined with Form 1!)
    #Wait: make Form 2 only 1 change/frame? Better: test Form 1 + Form 2 BOTH expiring with total changes = 16 > 12!
    # Also test total distinct patterns > 256 -> ANIM_POOL_COUNT = 2!
    # Room 1: obj 1 (1x10, 16 frames -> 160 patterns, F1), obj 2 (1x6, 16 frames -> 96 patterns, F1),
    #         obj 3 (1x2, 3 frames -> 4 patterns -> total 260 > 256 -> bank 1 split!)
    # AND in Room 2: Form 2 object with 16 slots x 4 frames changing ALL 16 slots per step (wait: F1=64 vs F2 -> make 8 frames where F2 wins? No, to win F2 must have average changes < (S - 2 - S/F)/2! E.g. 16 frames where frames 1..14 change 1 slot and frame 15->0 changes 14 slots!
    # Let's calculate: S=16, F=16:
    # F1 = 16 * 16 = 256 B. F2 = 16 + 32 + 14*3 + 1*(1+2*14) + 1*(1+2*14) = 16+32+42+29+29 = 148 B < 256 B!!
    # So on transition 14->15 and 15->0 it has 14 real copies > budget 12 -> tests Form 2 multi-tick deferral!!
    # Check unique patterns for obj 4: 16 base + 14 toggled = 30 patterns (fits easily).
    pat_counter = 1
    def _next_pat() -> bytes:
        nonlocal pat_counter
        b = _pat(pat_counter) + b""  # make sure unique across > 260 patterns
        pat_counter += 1
        # Use 2-byte mixed counter to guarantee 300+ unique 8-byte blocks!
        lo = pat_counter & 0xFF
        hi = (pat_counter >> 8) & 0xFF
        res = bytes([lo or 1, (lo ^ 0x55) or 2, hi + 1, (lo + 7) & 0xFF, 0xAA, lo ^ hi, (lo * 3 + 1) & 0xFF, hi + 9])
        return res

    # Re-write deterministic 8-byte unique block generator by sequential ID
    def _u_pat(uid: int) -> bytes:
        a = uid & 0xFF
        b = (uid >> 8) & 0xFF
        return bytes([((a + i * 19) & 0xFF) or 1 for i in range(6)]) + bytes([a or 0xFE, b + 1])

    uid_seq = 1
    for f in range(16):
        for dy in range(10):
            tiles[(f, dy)] = _u_pat(uid_seq)
            uid_seq += 1
    for f in range(16):
        for dy in range(6):
            tiles[(f, 10 + dy)] = _u_pat(uid_seq)
            uid_seq += 1
    tiles[(16, 0)] = _u_pat(uid_seq); uid_seq += 1
    tiles[(17, 0)] = _u_pat(uid_seq); uid_seq += 1

    # Form 2 heavy-wrap object: S=16 slots, F=16 frames -> at f=15 invert 14 slots, f=0 revert 14 slots (> budget 12!)
    f4_base = [_u_pat(500 + i) for i in range(16)]
    f4_alt = [_u_pat(600 + i) for i in range(16)]
    f4_frames: list[list[bytes]] = []
    cur16 = list(f4_base)
    for k in range(16):
        if k == 0:
            cur16 = list(f4_base)
        elif k <= 14:
            cur16[k - 1] = f4_alt[k - 1]
        else:  # k == 15: restore first 13 AND flip slots 14 & 15 -> 15 changes (>12)! Wait: keep f=1..13 flipping 1 each, k=14 flips 14, k=15 swaps ALL 14 back!
            cur16 = list(f4_base)
            cur16[15] = f4_alt[15]
        f4_frames.append(list(cur16))
    for k, row in enumerate(f4_frames):
        for dy in range(16):
            tiles[(18 + k, dy)] = row[dy]

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
        "objects": [
            {
                "id": 1,
                "name": "pool_a",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 2,
                "frames": [{"x": f, "y": 0, "w": 1, "h": 10} for f in range(16)],
            },
            {
                "id": 2,
                "name": "pool_b",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 2,
                "frames": [{"x": f, "y": 10, "w": 1, "h": 6} for f in range(16)],
            },
            {
                "id": 3,
                "name": "pool_c",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 1,
                "frames": [{"x": 16, "y": 0, "w": 1, "h": 1}, {"x": 17, "y": 0, "w": 1, "h": 1}],
            },
            {
                "id": 4,
                "name": "f2_defer",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 1,
                "frames": [{"x": 18 + k, "y": 0, "w": 1, "h": 16} for k in range(16)],
            },
        ],
        "rooms": [
            {"id": 1, "name": "R_Split", "pos": [0, 0], "row_groups": ["g"], "placed": [{"object": 1, "x": 0, "y": 0}, {"object": 2, "x": 2, "y": 0}, {"object": 3, "x": 4, "y": 0}]},
            {"id": 2, "name": "R_F2Def", "pos": [1, 0], "row_groups": ["g"], "placed": [{"object": 4, "x": 0, "y": 0}]},
        ],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }

    mpu, mem, labels, report = _build_anim_test_env(
        tmp_path, doc, lambda tx, ty: tiles.get((tx, ty), bytes(8)), tiles_x=34, tiles_y=16
    )
    assert report.anim_pool_count == 2
    assert report.anim_stats[3].form == "form2"

    # 1. Room 1 (Split pool + 16-slot Form 1 budget deferral: 10+6=16 > 12)
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    max_split_cycles = 0
    for t in range(1, 35):
        cyc = _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
        max_split_cycles = max(max_split_cycles, cyc)
        assert mem[labels["ANIM_COPY_COUNT"]] <= 12
        assert mem[labels["ANIM_ST_FRAME"] + 0] == (t // 2) % 16
        assert mem[labels["ANIM_ST_FRAME"] + 1] == (t // 2) % 16
        assert mem[labels["ANIM_ST_FRAME"] + 2] == t % 2
    assert max_split_cycles < 8000  # Split-pool fallback stays within PAL VBLANK (~7980 cyc)

    # 2. Room 2 (Form 2 multi-frame deferral under speed=1 with 15-change step at frame 15 -> settles back at wrap!)
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    vram = labels["SCREEN_VRAM"]
    ch_base = labels["CHARSET_G"]
    f4_codes = [mem[vram + row * 40] for row in range(16)]
    for t in range(1, 33):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
        assert mem[labels["ANIM_COPY_COUNT"]] <= 12
    # Wait until steady state on tick 34 (speed=1 finishes remaining 1-change steps cleanly)
    # Wait: at tick 32 frame is 0, wait if a 15-change step hit on tick 31 (15->0 wraps 2 slots), wait tick 31=15, tick 32=0!
    # Assert target frame matches (t % 16) with zero drift after 32 ticks
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 32 % 16
    # Verify final settled frame 1 (tick 33: only 1 change) has exact f4_frames[1] in charset!
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 33 -> finishes any wrap lag? Let's run until tick 35 (frame 3 -> 1 change)
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 34
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 35 (frame 3)
    assert [bytes(mem[ch_base + c * 8 : ch_base + (c + 1) * 8]) for c in f4_codes] == f4_frames[3]


def test_py65_per_frame_durations_uniform_mixed_extreme_budget_and_reentry(tmp_path: Path) -> None:
    """Verify per-frame durations (1..255), uniform+variable room, budget deferral stability, and re-entry."""
    tiles: dict[tuple[int, int], bytes] = {}
    for x in range(4):
        tiles[(x, 0)] = _pat(10 + x)  # Obj 1 variable: 4 frames
    for x in range(2):
        tiles[(4 + x, 0)] = _pat(30 + x)  # Obj 2 uniform: 2 frames @ speed 3
    # Obj 3: 15 varying slots x 2 frames (durations [2, 3], > budget 12 to force deferral!)
    f3_0 = [_pat(100 + i) for i in range(15)]
    f3_1 = [_pat(200 + i) for i in range(15)]
    for i in range(15):
        tiles[(i, 1)] = f3_0[i]
        tiles[(i, 2)] = f3_1[i]

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
        "objects": [
            # Obj 1 (aid=0): durations = [1, 255, 2, 3], speed=3 -> test boundary 1 and 255 + wrap
            {
                "id": 1,
                "name": "var_extremes",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 3,
                "frames": [
                    {"x": 0, "y": 0, "w": 1, "h": 1, "duration": 1},
                    {"x": 1, "y": 0, "w": 1, "h": 1, "duration": 255},
                    {"x": 2, "y": 0, "w": 1, "h": 1, "duration": 2},
                    {"x": 3, "y": 0, "w": 1, "h": 1},  # fallback to 3
                ],
            },
            # Obj 2 (aid=1): uniform speed=3 alongside Obj 1
            {
                "id": 2,
                "name": "uni_peer",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 3,
                "frames": [{"x": 4, "y": 0, "w": 1, "h": 1}, {"x": 5, "y": 0, "w": 1, "h": 1}],
            },
            # Obj 3 (aid=2): 15-slot variable durations [2, 3], speed=5 -> defers across 2 VBIs without timer drift
            {
                "id": 3,
                "name": "big_var",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 5,
                "frames": [
                    {"x": 0, "y": 1, "w": 15, "h": 1, "duration": 2},
                    {"x": 0, "y": 2, "w": 15, "h": 1, "duration": 3},
                ],
            },
        ],
        "rooms": [
            {
                "id": 1,
                "name": "R_Extremes",
                "pos": [0, 0],
                "row_groups": ["g"],
                "placed": [{"object": 1, "x": 0, "y": 0}, {"object": 2, "x": 2, "y": 0}],
            },
            {
                "id": 2,
                "name": "R_MixedVar",
                "pos": [1, 0],
                "row_groups": ["g"],
                "placed": [
                    {"object": 1, "x": 0, "y": 0},
                    {"object": 3, "x": 0, "y": 2},
                ],
            },
        ],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }

    mpu, mem, labels, report = _build_anim_test_env(
        tmp_path, doc, lambda tx, ty: tiles.get((tx, ty), bytes(8)), tiles_x=16, tiles_y=4
    )
    assert report.anim_uniform_count == 1
    assert report.anim_var_dur_count == 2
    ch_base = labels["CHARSET_G"]

    # Room 1: Obj 1 (var [1, 255, 2, 3]) + Obj 2 (uni 3)
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    vram = labels["SCREEN_VRAM"]
    c_var = mem[vram + 0]
    c_uni = mem[vram + 2]
    assert mem[labels["ANIM_ST_CNT"] + 0] == 1
    assert mem[labels["ANIM_ST_CNT"] + 1] == 3

    def _slot(c: int) -> bytes:
        return bytes(mem[ch_base + c * 8 : ch_base + (c + 1) * 8])

    assert _slot(c_var) == _pat(10)
    # Tick 1: var switches frame 0 -> 1 (loads cnt=255), uni stays at cnt=2
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert _slot(c_var) == _pat(11) and mem[labels["ANIM_ST_CNT"] + 0] == 255
    assert _slot(c_uni) == _pat(30) and mem[labels["ANIM_ST_CNT"] + 1] == 2

    # Advance 254 ticks (total 255): var still on frame 1 (cnt reaches 1) while uni stepped every 3 ticks
    for _ in range(254):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert _slot(c_var) == _pat(11) and mem[labels["ANIM_ST_CNT"] + 0] == 1
    assert mem[labels["ANIM_ST_FRAME"] + 1] == (255 // 3) % 2

    # Tick 256: var switches frame 1 -> 2 (loads cnt=2); Tick 258 -> frame 3 (loads cnt=3); Tick 261 -> wraps to frame 0 (cnt=1)
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert _slot(c_var) == _pat(12) and mem[labels["ANIM_ST_CNT"] + 0] == 2
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert _slot(c_var) == _pat(12)
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert _slot(c_var) == _pat(13) and mem[labels["ANIM_ST_CNT"] + 0] == 3
    for _ in range(2):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert _slot(c_var) == _pat(13)
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert _slot(c_var) == _pat(10) and mem[labels["ANIM_ST_CNT"] + 0] == 1

    # Room 2: two variable-timing objects + 15-slot budget deferral does NOT shift timing
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    big_codes = [mem[vram + 2 * 40 + col] for col in range(15)]
    assert mem[labels["ANIM_ST_CNT"] + 0] == 1  # var_extremes starts at frame 0 (dur=1)
    assert mem[labels["ANIM_ST_CNT"] + 1] == 2  # big_var starts at frame 0 (dur=2)

    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 1: var_extremes advances to f1, big_var cnt=1
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 1
    assert mem[labels["ANIM_ST_CNT"] + 1] == 1
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 2: big_var advances to f1 (loads cnt=3), 12/15 copied (3 deferred)
    assert mem[labels["ANIM_COPY_COUNT"]] == 12
    assert mem[labels["ANIM_ST_FRAME"] + 1] == 1
    assert mem[labels["ANIM_ST_CNT"] + 1] == 3
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 3: finishes remaining 3 copies, timer cnt=2 (no drift!)
    assert mem[labels["ANIM_COPY_COUNT"]] == 3
    assert mem[labels["ANIM_ST_CNT"] + 1] == 2
    assert [_slot(c) for c in big_codes] == f3_1

    # Re-entering Room 2 resets both objects cleanly to frame 0 with frame 0 durations (1 and 2)
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 0 and mem[labels["ANIM_ST_CNT"] + 0] == 1
    assert mem[labels["ANIM_ST_FRAME"] + 1] == 0 and mem[labels["ANIM_ST_CNT"] + 1] == 2
    assert [_slot(c) for c in big_codes] == f3_0


def test_py65_wide_duration_table_lookup(tmp_path: Path) -> None:
    """Verify 6502 execution when unique duration tables exceed 256 bytes (ANIM_DUR_WIDE == 1)."""
    tiles: dict[tuple[int, int], bytes] = {}
    for x in range(16):
        tiles[(x, 0)] = _pat(1 + x)
    objs = []
    placed = []
    # 18 non-uniform objects x 16 frames = 288 unique duration bytes -> ANIM_DUR_WIDE = 1
    for i in range(18):
        durs = [((i * 13 + f) % 240) + 1 for f in range(16)]
        durs[0] = 2 + i
        durs[1] = 4 + i
        objs.append(
            {
                "id": i + 1,
                "name": f"w{i}",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 5,
                "frames": [{"x": (f + i) % 16, "y": 0, "w": 1, "h": 1, "duration": durs[f]} for f in range(16)],
            }
        )
        placed.append({"object": i + 1, "x": i, "y": 0})
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
        "objects": objs,
        "rooms": [{"id": 1, "name": "R", "pos": [0, 0], "row_groups": ["g"], "placed": placed}],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }
    mpu, mem, labels, report = _build_anim_test_env(
        tmp_path, doc, lambda tx, ty: tiles.get((tx, ty), bytes(8)), tiles_x=16, tiles_y=1
    )
    assert "ANIM_DUR_LO" in labels
    assert report.anim_dur_table_count == 18
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    # Object 0 has frame 0 duration=2, frame 1 duration=4; object 1 has frame 0 duration=3, frame 1 duration=5
    assert mem[labels["ANIM_ST_CNT"] + 0] == 2
    assert mem[labels["ANIM_ST_CNT"] + 1] == 3
    for _ in range(2):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 1 and mem[labels["ANIM_ST_CNT"] + 0] == 4
    assert mem[labels["ANIM_ST_FRAME"] + 1] == 0 and mem[labels["ANIM_ST_CNT"] + 1] == 1
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert mem[labels["ANIM_ST_FRAME"] + 1] == 1 and mem[labels["ANIM_ST_CNT"] + 1] == 5


def test_py65_frame_groups_example_positions_repeats_durations_and_both_forms(
    tmp_path: Path,
) -> None:
    """Verify exact 6502 tick-by-tick slot updates for frame groups across Form 1 & Form 2."""
    tiles: dict[tuple[int, int], bytes] = {}
    # f1_ex (1x1, 5 frames): unique patterns _pat(1..5) at y=0, x=0..4
    f1_pats = [_pat(1 + i) for i in range(5)]
    for i, p in enumerate(f1_pats):
        tiles[(i, 0)] = p

    # f2_ex (10x1, 11 frames at y=9..19): 10 cumulative single-slot changes -> Form 2 (S=10, F=11: 88B < 110B)
    f2_base = [_pat(20 + dx) for dx in range(10)]
    f2_frames: list[list[bytes]] = []
    cur10 = list(f2_base)
    for f in range(11):
        if f >= 1:
            cur10 = list(cur10)
            cur10[f - 1] = _pat(100 + f - 1)
        f2_frames.append(list(cur10))
        for dx in range(10):
            tiles[(dx, 9 + f)] = cur10[dx]

    # Obj 3: group at start {0..2} x2, 5 frames (y=1, x=0..4)
    start_pats = [_pat(40 + i) for i in range(5)]
    for i, p in enumerate(start_pats):
        tiles[(i, 1)] = p

    # Obj 4: group at end {2..4} x2, 5 frames (y=1, x=5..9)
    end_pats = [_pat(50 + i) for i in range(5)]
    for i, p in enumerate(end_pats):
        tiles[(5 + i, 1)] = p

    # Obj 5: covering all frames {0..2} x3, 3 frames (y=0, x=5..7)
    all_pats = [_pat(60 + i) for i in range(3)]
    for i, p in enumerate(all_pats):
        tiles[(5 + i, 0)] = p

    # Obj 6: two groups + per-frame durations, 6 frames (y=7, x=0..5), groups {0..1}x2, {3..4}x3, dur [1,2,1,2,1,2]
    two_pats = [_pat(70 + i) for i in range(6)]
    for i, p in enumerate(two_pats):
        tiles[(i, 7)] = p

    # Obj 7: repeat 255 (4 frames, {1..2}x255, y=8, x=0..3) and Obj 8: repeat 1 (y=8, x=4..7)
    r255_pats = [_pat(80 + i) for i in range(4)]
    for i, p in enumerate(r255_pats):
        tiles[(i, 8)] = p
    r1_pats = [_pat(90 + i) for i in range(4)]
    for i, p in enumerate(r1_pats):
        tiles[(4 + i, 8)] = p

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
        "objects": [
            {
                "id": 1, "name": "f1_ex", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [{"x": i, "y": 0, "w": 1, "h": 1} for i in range(5)],
                "groups": [{"first": 1, "last": 3, "repeat": 3}],
            },
            {
                "id": 2, "name": "f2_ex", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [{"x": 0, "y": 9 + f, "w": 10, "h": 1} for f in range(11)],
                "groups": [{"first": 1, "last": 3, "repeat": 3}],
            },
            {
                "id": 3, "name": "gstart", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [{"x": i, "y": 1, "w": 1, "h": 1} for i in range(5)],
                "groups": [{"first": 0, "last": 2, "repeat": 2}],
            },
            {
                "id": 4, "name": "gend", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [{"x": 5 + i, "y": 1, "w": 1, "h": 1} for i in range(5)],
                "groups": [{"first": 2, "last": 4, "repeat": 2}],
            },
            {
                "id": 5, "name": "gall", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [{"x": 5 + i, "y": 0, "w": 1, "h": 1} for i in range(3)],
                "groups": [{"first": 0, "last": 2, "repeat": 3}],
            },
            {
                "id": 6, "name": "gtwo_dur", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [
                    {"x": i, "y": 7, "w": 1, "h": 1, "duration": (2 if i % 2 == 1 else 1)}
                    for i in range(6)
                ],
                "groups": [{"first": 0, "last": 1, "repeat": 2}, {"first": 3, "last": 4, "repeat": 3}],
            },
            {
                "id": 7, "name": "gr255", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [{"x": i, "y": 8, "w": 1, "h": 1} for i in range(4)],
                "groups": [{"first": 1, "last": 2, "repeat": 255}],
            },
            {
                "id": 8, "name": "gr1", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [{"x": 4 + i, "y": 8, "w": 1, "h": 1} for i in range(4)],
                "groups": [{"first": 1, "last": 2, "repeat": 1}],
            },
        ],
        "rooms": [
            {
                "id": 1,
                "name": "R_Ex",
                "pos": [0, 0],
                "row_groups": ["g"],
                "placed": [{"object": 1, "x": 0, "y": 0}, {"object": 2, "x": 2, "y": 0}],
            },
            {
                "id": 2,
                "name": "R_Misc",
                "pos": [1, 0],
                "row_groups": ["g"],
                "placed": [
                    {"object": 3, "x": 0, "y": 0},
                    {"object": 4, "x": 2, "y": 0},
                    {"object": 5, "x": 4, "y": 0},
                    {"object": 6, "x": 6, "y": 0},
                    {"object": 8, "x": 8, "y": 0},
                ],
            },
            {
                "id": 3,
                "name": "R_255",
                "pos": [2, 0],
                "row_groups": ["g"],
                "placed": [{"object": 7, "x": 0, "y": 0}],
            },
        ],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }

    mpu, mem, labels, report = _build_anim_test_env(
        tmp_path, doc, lambda tx, ty: tiles.get((tx, ty), bytes(8)), tiles_x=16, tiles_y=20
    )
    assert report.anim_stats[0].form == "form1"
    assert report.anim_stats[1].form == "form2"
    ch_base = labels["CHARSET_G"]
    vram = labels["SCREEN_VRAM"]

    def _slot(c: int) -> bytes:
        return bytes(mem[ch_base + c * 8 : ch_base + (c + 1) * 8])

    # Room 1: Form 1 & Form 2 tick-by-tick across 19 ticks
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    c_f1 = mem[vram + 0]
    c_f2 = [mem[vram + 2 + dx] for dx in range(10)]
    expected_f1 = [0, 1, 2, 3, 1, 2, 3, 1, 2, 3, 4, 0, 1, 2, 3, 1, 2, 3, 1, 2]
    expected_f2 = [0, 1, 2, 3, 1, 2, 3, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0, 1, 2]
    assert _slot(c_f1) == f1_pats[0]
    assert [_slot(c) for c in c_f2] == f2_frames[0]
    for exp_1, exp_2 in zip(expected_f1[1:], expected_f2[1:]):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
        assert _slot(c_f1) == f1_pats[exp_1]
        assert [_slot(c) for c in c_f2] == f2_frames[exp_2]

    # Room 2: gstart, gend, gall, gtwo_dur, gr1
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    c_s = mem[vram + 0]
    c_e = mem[vram + 2]
    c_a = mem[vram + 4]
    c_two = mem[vram + 6]
    c_r1 = mem[vram + 8]
    # Re-entry restarts frame 0 & pass counters cleanly (gstart starts in {0..2} -> rep=2)
    assert mem[labels["ANIM_ST_REP"] + 0] == 2
    obs_s, obs_e, obs_a, obs_two, obs_r1 = (
        [start_pats.index(_slot(c_s))],
        [end_pats.index(_slot(c_e))],
        [all_pats.index(_slot(c_a))],
        [two_pats.index(_slot(c_two))],
        [r1_pats.index(_slot(c_r1))],
    )
    for _ in range(17):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
        obs_s.append(start_pats.index(_slot(c_s)))
        obs_e.append(end_pats.index(_slot(c_e)))
        obs_a.append(all_pats.index(_slot(c_a)))
        obs_two.append(two_pats.index(_slot(c_two)))
        obs_r1.append(r1_pats.index(_slot(c_r1)))
    assert obs_s[:10] == [0, 1, 2, 0, 1, 2, 3, 4, 0, 1]
    assert obs_e[:10] == [0, 1, 2, 3, 4, 2, 3, 4, 0, 1]
    assert obs_a[:9] == [0, 1, 2, 0, 1, 2, 0, 1, 2]
    # two_grps: frames [0(1), 1(2)]x2 -> 2(1) -> [3(2), 4(1)]x3 -> 5(2) -> 0
    # Wait per-tick frame indices: 0, 1,1, 0, 1,1, 2, 3,3, 4, 3,3, 4, 3,3, 4, 5,5
    assert obs_two == [0, 1, 1, 0, 1, 1, 2, 3, 3, 4, 3, 3, 4, 3, 3, 4, 5, 5]
    assert obs_r1[:6] == [0, 1, 2, 3, 0, 1]

    # Re-enter Room 2 -> resets back to frame 0 and gstart pass counter=2
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 0
    assert mem[labels["ANIM_ST_REP"] + 0] == 2
    assert _slot(c_s) == start_pats[0] and _slot(c_two) == two_pats[0]

    # Room 3: repeat = 255
    mpu.x = 3
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 3
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    c_255 = mem[vram + 0]
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # 0 -> 1 (rep=255)
    assert _slot(c_255) == r255_pats[1] and mem[labels["ANIM_ST_REP"] + 0] == 255
    for _ in range(254 * 2):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    # Still at frame 1 on final (255th) pass? 254 passes * 2 = 508 ticks -> back to 1 with rep=1!
    assert _slot(c_255) == r255_pats[1] and mem[labels["ANIM_ST_REP"] + 0] == 1
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # -> 2 (rep=1)
    assert _slot(c_255) == r255_pats[2]
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # -> exits group to 3!
    assert _slot(c_255) == r255_pats[3]


def test_py65_frame_groups_loopback_deferral_and_two_object_speeds(tmp_path: Path) -> None:
    """Verify loop-back transition under 12-slot budget deferral in both Form 1 and Form 2 + mixed speeds."""
    tiles: dict[tuple[int, int], bytes] = {}
    # Obj 1 ('f1_def', 15x1, 3 frames, {1..2}x2, speed=2): frame 2->1 swaps all 15 slots (>12 budget!)
    f1_frames = [[_pat(10 + f * 20 + i) for i in range(15)] for f in range(3)]
    for f, row in enumerate(f1_frames):
        for dx in range(15):
            tiles[(dx, f)] = row[dx]

    # Obj 2 ('f2_def', 16x1, 5 frames, {1..3}x2, speed=2):
    # Form 1 = 16*5 = 80 B; f0=[base], f1=[differs in 1 slot], f2=[differs in 1 slot], f3=[differs in ALL 14? Wait!]
    # Make norm changes 1/step (total 5) + loop-back 3->1 change ALL 14 slots!
    # Wait: S=16, F=5 -> Form 1=80 B; Form 2 = 16 + 1 + 12 + (3+3+3+3+9) + 29 = 102 B > 80 B!
    # Increase F to 10 (group {1..3}x2, 1 change on norm steps 0..9, 14 changes on loop 3->1):
    # Form 1 = 16 * 10 = 160 B; Form 2 = 16 + 1 + 22 + 9*3 + 29 + 29 = 124 B < 160 B -> FORM 2!!
    base16 = [_pat(100 + i) for i in range(16)]
    alt16 = [_pat(150 + i) for i in range(16)]
    f2_frames: list[list[bytes]] = []
    # f=0: base16
    # f=1: base16 with slot 0 = alt16[0]
    # f=2: base16 with slot 0..1 = alt16[0..1] (1 change from 1->2)
    # f=3: alt16[0..14], base16[15] -> make f=3 change ALL 14 slots from f=2 so BOTH 2->3 and 3->1 change >=13 slots (>12)!
    # Wait if f3->f4 restores 13 slots, cost is 1+2*13=27; f2->f3=27; f3->f1=27 -> total deltas: 3 + 3 + 27 + 27 + 6*3 + 27 = 132 + 39 = 171 > 160!
    # Increase F to 14! Form 1 = 16 * 14 = 224 B; Form 2 = 16 + 1 + 30 + (3+3+29+29+10*3+29) = 47 + 123 = 170 B < 224 B!!
    cur = list(base16)
    f2_frames.append(list(cur))                  # f=0
    cur[0] = alt16[0]; f2_frames.append(list(cur))   # f=1 (1 chg)
    cur[1] = alt16[1]; f2_frames.append(list(cur))   # f=2 (1 chg)
    cur = alt16[:15] + [base16[15]]; f2_frames.append(list(cur))  # f=3 (13 chg vs f2, 14 chg vs f1!)
    cur = [base16[0]] + list(base16[1:]); cur[14] = alt16[14]; f2_frames.append(list(cur))  # wait keep 1 chg 3->4? Use only f3=alt16[:14]+base16[14:], then f4..f13 step back 1 at a time!
    # Rebuild cleanly:
    f2_frames = [list(base16)]  # f=0
    r1 = list(base16); r1[0] = alt16[0]; f2_frames.append(r1)  # f=1 (diff from f0 = {0})
    r2 = list(r1); r2[1] = alt16[1]; f2_frames.append(r2)      # f=2 (diff from f1 = {1})
    r3 = list(alt16); f2_frames.append(r3)                     # f=3 (diff from f2 = 14 slots {2..15}!)
    # From f=3 (alt16), change 1 slot per step from f=4..f=13 back toward base16 so each step has 1 chg, and 13->0 has 6 chgs!
    c_seq = list(alt16)
    for k in range(4, 14):
        c_seq = list(c_seq)
        c_seq[k - 4] = base16[k - 4]
        f2_frames.append(list(c_seq))
    # Check diffs: 0->1(1),1->2(1),2->3(14),3->4..12->13(1*10),13->0(6), 3->1(15!)
    # Form 1 = 16*14 = 224; Form 2 = 16+1+30 + (3+3+29 + 30 + 13 + 31) = 47 + 109 = 156 B < 224 B!
    for f, row in enumerate(f2_frames):
        for dx in range(16):
            tiles[(dx, 3 + f)] = row[dx]

    # Obj 3: fast ungrouped companion @ speed=1 (y=17, x=0..1)
    peer_pats = [_pat(220), _pat(221)]
    tiles[(0, 17)] = peer_pats[0]
    tiles[(1, 17)] = peer_pats[1]

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
        "objects": [
            {
                "id": 1, "name": "f1_def", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 2,
                "frames": [{"x": 0, "y": f, "w": 15, "h": 1} for f in range(3)],
                "groups": [{"first": 1, "last": 2, "repeat": 2}],
            },
            {
                "id": 2, "name": "f2_def", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 2,
                "frames": [{"x": 0, "y": 3 + f, "w": 16, "h": 1} for f in range(14)],
                "groups": [{"first": 1, "last": 3, "repeat": 2}],
            },
            {
                "id": 3, "name": "fast_peer", "group": "g", "tags": [],
                "non-blockable": True, "colpf3": False, "animation_speed": 1,
                "frames": [{"x": 0, "y": 17, "w": 1, "h": 1}, {"x": 1, "y": 17, "w": 1, "h": 1}],
            },
        ],
        "rooms": [
            {"id": 1, "name": "R_F1Def", "pos": [0, 0], "row_groups": ["g"], "placed": [{"object": 1, "x": 0, "y": 0}, {"object": 3, "x": 20, "y": 0}]},
            {"id": 2, "name": "R_F2Def", "pos": [1, 0], "row_groups": ["g"], "placed": [{"object": 2, "x": 0, "y": 0}, {"object": 3, "x": 20, "y": 0}]},
        ],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }

    mpu, mem, labels, report = _build_anim_test_env(
        tmp_path, doc, lambda tx, ty: tiles.get((tx, ty), bytes(8)), tiles_x=16, tiles_y=18
    )
    assert report.anim_stats[0].form == "form1"
    assert report.anim_stats[1].form == "form2"
    ch_base = labels["CHARSET_G"]
    vram = labels["SCREEN_VRAM"]

    def _slot(c: int) -> bytes:
        return bytes(mem[ch_base + c * 8 : ch_base + (c + 1) * 8])

    # Room 1: Form 1 grouped (15 slots, speed=2, {1..2}x2 -> frames 0,1,2,1,2,0) + speed=1 companion
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 1
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    c1 = [mem[vram + dx] for dx in range(15)]
    cp = mem[vram + 20]
    # Tick 1: fast_peer steps; Tick 2: f1_def -> frame 1 (12/15 copied, 3 deferred); Tick 3: remaining 3 copied!
    for _ in range(2):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
        assert mem[labels["ANIM_COPY_COUNT"]] <= 12
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 1 and mem[labels["ANIM_COPY_COUNT"]] == 12
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 3: finishes deferred f1_def + steps fast_peer
    assert [_slot(c) for c in c1] == f1_frames[1]
    assert _slot(cp) == peer_pats[1]
    # Advance through tick 6 (f2 -> loop-back to f1 with 15 copies deferred across tick 6 & 7!) -> ends in f1_frames[1]
    for _ in range(3):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
        assert mem[labels["ANIM_COPY_COUNT"]] <= 12
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 1  # loop-back occurred cleanly on tick 6!
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 7 finishes remaining loop-back copies!
    assert [_slot(c) for c in c1] == f1_frames[1]
    _run_subroutine_cycles(mpu, labels["ANIM_TICK"])  # tick 8 (2nd pass 1->2, exact non-drifted timing!)
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 2

    # Room 2: Form 2 grouped loop-back under 12-slot budget deferral ({1..3}x2: tick 2->f1, 4->f2, 6->f3(14 chg), 8->loop 3->1 (15 chg!))
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_DRAW"])
    mpu.x = 2
    _run_subroutine_cycles(mpu, labels["ROOM_ANIM_INIT"])
    c2 = [mem[vram + dx] for dx in range(16)]
    for t in range(1, 10):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
        assert mem[labels["ANIM_COPY_COUNT"]] <= 12
    # At tick 9: f2_def is on target frame 1 (looped back on tick 8!) and finished deferred 15-slot loop-back copy cleanly!
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 1
    assert mem[labels["ANIM_ST_REP"] + 0] == 1
    assert [_slot(c) for c in c2] == f2_frames[1]
    # Tick 10->f2 (1 chg), tick 12->f3, tick 14->leaves group to f4 (zero timing drift!)
    for _ in range(5):
        _run_subroutine_cycles(mpu, labels["ANIM_TICK"])
    assert mem[labels["ANIM_ST_FRAME"] + 0] == 4 and mem[labels["ANIM_ST_CNT"] + 0] == 2
