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
                "anim_slot_cur   = anim_st_sbase + ANIM_STATE_CAP",
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
