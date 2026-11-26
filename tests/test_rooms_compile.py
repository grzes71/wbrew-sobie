"""Verification tests for scripts/rooms_compile.py, generated ASM decoding, and MADS assembly."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml
from PIL import Image

from room_editor.io.yaml_io import load_project
from room_editor.model.project import compose_room
from scripts.rooms_compile import (
    EXPECTED_YAML_VERSION,
    ROOM_HEIGHT,
    ROOM_WIDTH,
    RoomCompileError,
    compile_rooms,
    main as compiler_main,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MADS = Path("c:/Apps/Mad-Assembler-2.1.6/bin/windows_x86_64/mads.exe")


# ---------------------------------------------------------------------------
# Independent ASM parser and reference room player (no shared compiler code)
# ---------------------------------------------------------------------------


@dataclass
class ParsedAsmImage:
    """Flat virtual address space and symbol table parsed purely from generated .asm files."""

    memory: bytearray = field(default_factory=bytearray)
    symbols: dict[str, int] = field(default_factory=dict)
    equates: dict[str, int] = field(default_factory=dict)

    def read_id_byte(self, table_name: str, entity_id: int) -> int:
        addr = self.symbols[table_name] + entity_id
        return self.memory[addr]

    def read_id_ptr(self, lo_name: str, hi_name: str, entity_id: int) -> int:
        lo = self.read_id_byte(lo_name, entity_id)
        hi = self.read_id_byte(hi_name, entity_id)
        return lo | (hi << 8)


def _eval_atom(token: str, equates: dict[str, int]) -> int:
    tok = token.strip()
    if tok.startswith("$"):
        return int(tok[1:], 16)
    if tok.startswith("%"):
        return int(tok[1:], 2)
    if tok.isdigit() or (tok.startswith("-") and tok[1:].isdigit()):
        return int(tok, 10)
    if tok in equates:
        return equates[tok]
    raise ValueError(f"Cannot evaluate expression '{token}'")


def parse_generated_asm(asm_dir: Path) -> ParsedAsmImage:
    """Two-pass mini-parser for the generated MADS assembly files.

    Starts virtual PC at $2000, respects `.align $400`, resolves `<label`/`>label`
    and `<label> = <other> - 1` equates, and populates `memory` and `symbols`.
    """
    order = [
        "rooms_defs.asm",
        "charsets.asm",
        "styles.asm",
        "objects.asm",
        "rooms.asm",
        "teleports.asm",
        "animations.asm",
    ]
    texts = [
        (fname, (asm_dir / fname).read_text(encoding="utf-8"))
        for fname in order
    ]

    # Collect cleaned instruction lines
    raw_lines: list[str] = []
    for _fname, text in texts:
        for line in text.splitlines():
            code = line.split(";", 1)[0].strip()
            if not code:
                continue
            raw_lines.append(code)

    def _run_pass(pass_symbols: dict[str, int], pass_equates: dict[str, int], *, populate_mem: bool) -> tuple[bytearray, dict[str, int], dict[str, int]]:
        pc = 0x2000
        mem = bytearray(0x10000)
        syms: dict[str, int] = {}
        eqs: dict[str, int] = dict(pass_equates)
        if_stack: list[bool] = []

        def active() -> bool:
            return all(if_stack)

        for code in raw_lines:
            low = code.lower()
            if low.startswith(".ifdef "):
                sym = code.split(None, 1)[1].strip()
                if_stack.append(sym in eqs)
                continue
            if low == ".endif":
                if_stack.pop()
                continue
            if not active():
                continue

            if low.startswith(".align "):
                align_val = _eval_atom(code.split(None, 1)[1], eqs)
                rem = pc % align_val
                if rem:
                    pc += align_val - rem
                continue

            if low.startswith(".byte "):
                items_str = code.split(None, 1)[1]
                for item in items_str.split(","):
                    expr = item.strip()
                    val = 0
                    if expr.startswith("<(") and expr.endswith(")"):
                        inner = expr[2:-1].strip()
                        lbl, off_s = (p.strip() for p in inner.split("+", 1))
                        val = (pass_symbols.get(lbl, 0) + _eval_atom(off_s, eqs)) & 0xFF
                    elif expr.startswith(">(") and expr.endswith(")"):
                        inner = expr[2:-1].strip()
                        lbl, off_s = (p.strip() for p in inner.split("+", 1))
                        val = ((pass_symbols.get(lbl, 0) + _eval_atom(off_s, eqs)) >> 8) & 0xFF
                    elif expr.startswith("<"):
                        target = expr[1:].strip()
                        val = pass_symbols.get(target, 0) & 0xFF
                    elif expr.startswith(">"):
                        target = expr[1:].strip()
                        val = (pass_symbols.get(target, 0) >> 8) & 0xFF
                    else:
                        val = _eval_atom(expr, eqs) & 0xFF
                    if populate_mem:
                        mem[pc] = val
                    pc += 1
                continue

            # Equate: `NAME = expr` (possibly `base - 1`)
            if "=" in code:
                lhs, rhs = (p.strip() for p in code.split("=", 1))
                m_sub = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*-\s*1", rhs)
                if m_sub:
                    base = syms.get(m_sub.group(1), pass_symbols.get(m_sub.group(1), 0))
                    syms[lhs] = base - 1
                    eqs[lhs] = base - 1
                else:
                    val = _eval_atom(rhs, eqs)
                    eqs[lhs] = val
                continue

            # Label definition
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", code):
                syms[code] = pc
                continue

            raise AssertionError(f"Unrecognized ASM line in test parser: {code!r}")

        return mem, syms, eqs

    _, pass1_syms, pass1_eqs = _run_pass({}, {}, populate_mem=False)
    mem, pass2_syms, pass2_eqs = _run_pass(pass1_syms, pass1_eqs, populate_mem=True)
    return ParsedAsmImage(memory=mem, symbols=pass2_syms, equates=pass2_eqs)


def play_room_from_asm(asm_img: ParsedAsmImage, room_id: int) -> tuple[list[list[int]], list[int]]:
    """Decode one room purely from the parsed .asm byte tables.

    Returns (screen_grid[24][40], row_style_ids[24]).
    """
    screen = [[0] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]

    inst_count = asm_img.read_id_byte("room_inst_count", room_id)
    if inst_count > 0:
        base_ptr = asm_img.read_id_ptr("room_inst_lo", "room_inst_hi", room_id)
        p_obj = base_ptr
        p_x = base_ptr + inst_count
        p_yf = base_ptr + 2 * inst_count
        p_rw = base_ptr + 3 * inst_count
        rep_count = asm_img.read_id_byte("room_rep_count", room_id)
        p_rh = p_rw + rep_count

        rep_cursor = 0
        for i in range(inst_count):
            oid = asm_img.memory[p_obj + i]
            ix = asm_img.memory[p_x + i]
            yf = asm_img.memory[p_yf + i]
            iy = yf & 0x1F
            if yf & 0x80:
                rw = asm_img.memory[p_rw + rep_cursor]
                rh = asm_img.memory[p_rh + rep_cursor]
                rep_cursor += 1
            else:
                rw, rh = 1, 1

            ow = asm_img.read_id_byte("obj_w", oid)
            oh = asm_img.read_id_byte("obj_h", oid)
            optr = asm_img.read_id_ptr("obj_data_lo", "obj_data_hi", oid)

            for ry in range(rh):
                for rx in range(rw):
                    bx = ix + rx * ow
                    by = iy + ry * oh
                    for dy in range(oh):
                        for dx in range(ow):
                            code = asm_img.memory[optr + dy * ow + dx]
                            if code != 0:
                                screen[by + dy][bx + dx] = code

        assert rep_cursor == rep_count

    rflags = asm_img.read_id_byte("room_flags", room_id)
    if rflags & 0x01:
        sid = asm_img.read_id_byte("room_rowstyle_lo", room_id)
        row_styles = [sid] * ROOM_HEIGHT
    else:
        rs_ptr = asm_img.read_id_ptr("room_rowstyle_lo", "room_rowstyle_hi", room_id)
        row_styles = [asm_img.memory[rs_ptr + r] for r in range(ROOM_HEIGHT)]

    return screen, row_styles


def reference_compose_from_yaml(yaml_path: Path) -> dict[int, list[list[int]]]:
    """Straightforward specification reference composer directly from YAML + PNG."""
    doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert doc["version"] == EXPECTED_YAML_VERSION

    # Build group PNG + glyph tables
    png_data: dict[str, tuple[int, bytes, tuple[int, ...]]] = {}
    for g in doc["object_groups"]:
        img_path = yaml_path.parent / g["image"]
        if img_path.exists():
            with Image.open(img_path) as im:
                w, _h = im.size
                data_fn = getattr(im, "get_flattened_data", im.getdata)
                px = bytes(data_fn())
            png_data[g["name"]] = (w, px, tuple(g["pixel_mapping"]))

    def _tile_bytes(gname: str, tx: int, ty: int) -> bytes:
        w_px, px, mapping = png_data[gname]
        gb = bytearray(8)
        for py in range(8):
            row_off = (ty * 8 + py) * w_px + tx * 4
            gb[py] = (
                (mapping[px[row_off]] << 6)
                | (mapping[px[row_off + 1]] << 4)
                | (mapping[px[row_off + 2]] << 2)
                | mapping[px[row_off + 3]]
            )
        return bytes(gb)

    objs_by_id = {int(o["id"]): o for o in doc["objects"]}
    static_pools: dict[str, dict[bytes, int]] = {g["name"]: {} for g in doc["object_groups"]}
    group_next_code: dict[str, int] = {g["name"]: 1 for g in doc["object_groups"]}
    obj_matrices: dict[int, tuple[int, int, list[int], bool]] = {}

    for oid in sorted(objs_by_id):
        o = objs_by_id[oid]
        gname = o["group"]
        frames = o["frames"]
        speed = int(o.get("animation_speed", 0))
        is_anim = len(frames) >= 2 and speed > 0
        f0 = frames[0]
        rw, rh = int(f0["w"]), int(f0["h"])
        pf3 = bool(o.get("colpf3", False))
        nb = bool(o.get("non-blockable", False))
        sp = static_pools[gname]
        mat: list[int] = []
        if not is_anim:
            for dy in range(rh):
                for dx in range(rw):
                    gb = _tile_bytes(gname, int(f0["x"]) + dx, int(f0["y"]) + dy)
                    if gb == b"\x00" * 8:
                        mat.append(0)
                    else:
                        code = sp.get(gb)
                        if code is None:
                            code = group_next_code[gname]
                            group_next_code[gname] += 1
                            sp[gb] = code
                        mat.append(code + 128 if pf3 else code)
        else:
            seq_code: dict[tuple[bytes, ...], int] = {}
            for dy in range(rh):
                for dx in range(rw):
                    seq = tuple(
                        _tile_bytes(gname, int(fr["x"]) + dx, int(fr["y"]) + dy) for fr in frames
                    )
                    if len(set(seq)) == 1:
                        gb = seq[0]
                        if gb == b"\x00" * 8:
                            mat.append(0)
                        else:
                            code = sp.get(gb)
                            if code is None:
                                code = group_next_code[gname]
                                group_next_code[gname] += 1
                                sp[gb] = code
                            mat.append(code + 128 if pf3 else code)
                    else:
                        code = seq_code.get(seq)
                        if code is None:
                            code = group_next_code[gname]
                            group_next_code[gname] += 1
                            seq_code[seq] = code
                        mat.append(code + 128 if pf3 else code)
        obj_matrices[oid] = (rw, rh, mat, nb)

    result: dict[int, list[list[int]]] = {}
    for r in doc["rooms"]:
        rid = int(r["id"])
        screen = [[0] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
        placed = list(r.get("placed") or [])
        nb_entries = [p for p in placed if obj_matrices[int(p["object"])][3]]
        bl_entries = [p for p in placed if not obj_matrices[int(p["object"])][3]]
        for p in nb_entries + bl_entries:
            oid = int(p["object"])
            ow, oh, mat, _nb = obj_matrices[oid]
            ix, iy = int(p["x"]), int(p["y"])
            if "repeat-xy" in p:
                rep_w, rep_h = int(p["repeat-xy"][0]), int(p["repeat-xy"][1])
            elif "repeat-x" in p:
                rep_w, rep_h = int(p["repeat-x"]), 1
            elif "repeat-y" in p:
                rep_w, rep_h = 1, int(p["repeat-y"])
            else:
                rep_w, rep_h = 1, 1
            for ryi in range(rep_h):
                for rxi in range(rep_w):
                    bx = ix + rxi * ow
                    by = iy + ryi * oh
                    for dy in range(oh):
                        for dx in range(ow):
                            c = mat[dy * ow + dx]
                            if c != 0:
                                screen[by + dy][bx + dx] = c
        result[rid] = screen
    return result


# ---------------------------------------------------------------------------
# Test PNG / fixture helpers
# ---------------------------------------------------------------------------


def _write_png(path: Path, cols: int, rows: int, tile_fn: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = cols * 4, rows * 8
    buf = bytearray(w * h)
    for gy in range(rows):
        for gx in range(cols):
            mat = tile_fn(gx, gy)
            for py in range(8):
                for px in range(4):
                    buf[(gy * 8 + py) * w + (gx * 4 + px)] = mat[py][px]
    im = Image.new("P", (w, h))
    im.putpalette([0, 0, 0, 200, 100, 50, 50, 200, 100, 50, 100, 200] + [0] * (768 - 12))
    im.putdata(buf)
    im.save(path, format="PNG")
    return path


def _unique_tile(index: int) -> list[list[int]]:
    """Deterministic non-empty 4x8 tile pattern using palette indexes 0..3 for 0 <= index < 256."""
    # Ensure index 0 is distinguishable and row 7 col 3 is non-zero (1..3) so all tiles are non-empty.
    n = index + 1
    rows = [[0, 0, 0, 0] for _ in range(8)]
    rows[0] = [(n >> 6) & 3, (n >> 4) & 3, (n >> 2) & 3, n & 3]
    rows[7] = [1, 2, 3, (n % 3) + 1]
    return rows


def _find_mads() -> Path | None:
    if DEFAULT_MADS.exists():
        return DEFAULT_MADS
    found = shutil.which("mads") or shutil.which("mads.exe")
    return Path(found) if found else None


# ---------------------------------------------------------------------------
# Verification tests
# ---------------------------------------------------------------------------


def test_all_in_one_fixture_player_crosscheck_and_features(tmp_path: Path) -> None:
    """Comprehensive fixture testing draw order, repeats, transparency, colpf3, styles, gaps, teleports, diacritics."""
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()

    # Group 1 PNG: 8 cols x 2 rows
    # (0,0)=solid idx 1, (1,0)=all 0 (empty!), (2,0)=uses idx 3 (%11 for colpf3),
    # (3,0)=solid idx 2, (4,0)+(5,0) form 2x1 stamp, (6,0)=mixed
    def fn_a(gx: int, gy: int) -> list[list[int]]:
        if (gx, gy) == (1, 0):
            return [[0, 0, 0, 0] for _ in range(8)]
        if (gx, gy) == (0, 0):
            return [[1, 1, 1, 1] for _ in range(8)]
        if (gx, gy) == (2, 0):
            return [[3, 3, 2, 1] for _ in range(8)]
        if (gx, gy) == (3, 0):
            return [[2, 2, 2, 2] for _ in range(8)]
        return _unique_tile(gy * 8 + gx)

    _write_png(proj_dir / "gfx" / "zamek.png", 8, 2, fn_a)
    _write_png(proj_dir / "gfx" / "jaskinia.png", 4, 2, lambda gx, gy: _unique_tile(100 + gy * 4 + gx))

    # Intentionally include Polish diacritics, ID gaps (objects 1,2,4,5,7,8; rooms 1,3,5),
    # cross-group usage in Room 5 (produces warning unless strict), and same-room + cross-room teleports.
    yaml_doc = {
        "version": 5,
        "settings": {
            "default_palette": {"colbk": 0, "colpf0": 40, "colpf1": 202, "colpf2": 148, "colpf3": 15}
        },
        "tags": ["Drabina", "Ściana", "Złoto"],
        "object_groups": [
            {
                "name": "Zamek Główny",
                "image": "gfx/zamek.png",
                "pixel_mapping": [0, 1, 2, 3],
                "palettes": [
                    {"name": "dzień", "colbk": 0, "colpf0": 0x28, "colpf1": 0xCA, "colpf2": 0x94, "colpf3": 0x0E},
                    {"name": "noc", "colbk": 0x02, "colpf0": 0x74, "colpf1": 0x88, "colpf2": 0x92, "colpf3": 0x0A},
                ],
            },
            {
                "name": "Jaskinia",
                "image": "gfx/jaskinia.png",
                "pixel_mapping": [0, 3, 1, 2],
                "palettes": [
                    {"name": "default", "colbk": 0x10, "colpf0": 0x34, "colpf1": 0x48, "colpf2": 0x5C, "colpf3": 0x1E},
                ],
            },
        ],
        "objects": [
            # id 1: 2x1 where left cell is solid, right cell (1,0) is ALL-0 transparent!
            {
                "id": 1,
                "name": "Okno Pół",
                "group": "Zamek Główny",
                "tags": ["Ściana"],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 0,
                "frames": [{"x": 0, "y": 0, "w": 2, "h": 1}],
            },
            # id 2: 1x1 blockable solid
            {
                "id": 2,
                "name": "Cegła",
                "group": "Zamek Główny",
                "tags": ["Ściana"],
                "non-blockable": False,
                "colpf3": False,
                "animation_speed": 0,
                "frames": [{"x": 3, "y": 0, "w": 1, "h": 1}],
            },
            # id 3 skipped -> ID gap
            # id 4: colpf3 non-blockable 1x1 (same glyph at (0,0) as Okno Pół's left cell? No, uses (2,0))
            {
                "id": 4,
                "name": "Pochodnia",
                "group": "Zamek Główny",
                "tags": ["Złoto"],
                "non-blockable": True,
                "pickable": True,
                "colpf3": True,
                "animation_speed": 0,
                "frames": [{"x": 2, "y": 0, "w": 1, "h": 1}],
            },
            # id 5: duplicate cell matrix as id 2 (deduplicated cell block!)
            {
                "id": 5,
                "name": "Cegła Kopia",
                "group": "Zamek Główny",
                "tags": ["Drabina", "Ściana"],
                "non-blockable": False,
                "colpf3": False,
                "animation_speed": 0,
                "frames": [{"x": 3, "y": 0, "w": 1, "h": 1}],
            },
            # id 6 skipped -> ID gap
            # id 7: Jaskinia 2x2 block
            {
                "id": 7,
                "name": "Skała",
                "group": "Jaskinia",
                "tags": [],
                "non-blockable": False,
                "colpf3": False,
                "animation_speed": 0,
                "frames": [{"x": 0, "y": 0, "w": 2, "h": 2}],
            },
        ],
        "rooms": [
            {
                "id": 1,
                "name": "SalaStart",
                "pos": [0, 0],
                "row_groups": ["Zamek Główny"],  # uniform style
                # Deliberately store blockable BEFORE overlapping non-blockable to prove compiler reorders to NB->BL!
                "placed": [
                    # Blockable ceiling repeat-x and wall repeat-y and corner repeat-xy
                    {"object": 2, "x": 0, "y": 0, "repeat-x": 5},
                    {"object": 5, "x": 10, "y": 5, "repeat-y": 3},
                    {"object": 2, "x": 20, "y": 10, "repeat-xy": [3, 2]},
                    # Blockable Cegła at (1, 2): covered at (0..1, 2) by Okno Pół whose right cell (1,2) is transparent!
                    {"object": 2, "x": 1, "y": 2},
                    # Overlapping non-blockable z-order:
                    # 1st drawn NB: Pochodnia (id 4, code +128) at (1, 2) -> overwritten by Cegła (blockable)!
                    {"object": 4, "x": 1, "y": 2},
                    # At (5, 5): first Pochodnia (4), then Okno Pół at (4, 5) (right cell transparent -> leaves Pochodnia visible at (5, 5)!),
                    # and Pochodnia (4) AFTER Okno Pół at (4, 5) -> overwrites Okno Pół's opaque left cell!
                    {"object": 4, "x": 5, "y": 5},
                    {"object": 1, "x": 4, "y": 5},
                    {"object": 4, "x": 4, "y": 5},
                ],
            },
            # Room id 2 skipped -> room ID gap!
            {
                "id": 3,
                "name": "Komnata Wschód",
                "pos": [1, 0],
                # Mixed row styles (rows 0..11 noc, rows 12..23 dzień)
                "row_groups": [
                    {"group": "Zamek Główny", "palette": "noc"} if r < 12 else "Zamek Główny"
                    for r in range(ROOM_HEIGHT)
                ],
                "placed": [
                    {"object": 1, "x": 2, "y": 3, "repeat-xy": [2, 2]},  # 2x1 repeated 2x2 -> step (2,1)
                ],
            },
            # Room id 4 skipped -> room ID gap!
            {
                "id": 5,
                "name": "Pieczara",
                "pos": [4, 4],  # No neighbours (isolated, reachable only via teleport!)
                # Exact same 24-row mixed style table as Room 3 to test deduplication, PLUS cross-group Jaskinia object!
                "row_groups": [
                    {"group": "Zamek Główny", "palette": "noc"} if r < 12 else "Zamek Główny"
                    for r in range(ROOM_HEIGHT)
                ],
                "placed": [
                    {"object": 7, "x": 4, "y": 14},  # 2x2 placed in Jaskinia row? Wait: Zamek Główny row -> emits mismatch warning
                ],
            },
        ],
        "teleports": [
            {"a": {"room": 1, "x": 2, "y": 2}, "b": {"room": 5, "x": 10, "y": 10}},
            {"a": {"room": 3, "x": 5, "y": 5}, "b": {"room": 3, "x": 30, "y": 20}},  # same-room teleport
        ],
        "start": {"room": 1, "x": 3, "y": 3},
    }

    yaml_path = proj_dir / "project.yaml"
    yaml_path.write_text(yaml.safe_dump(yaml_doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # --strict must fail because Room 5 has cross-group warning & Jaskinia palette is unused
    strict_dir = tmp_path / "strict_out"
    with pytest.raises(RoomCompileError, match="Strict mode"):
        compile_rooms(yaml_path, out_dir=strict_dir, strict=True)
    assert not strict_dir.exists()

    out_dir = tmp_path / "out"
    res = compile_rooms(yaml_path, out_dir=out_dir)

    # Report checks
    rep = res.report
    assert rep.object_id_gaps == 2  # max_id 7 - 5 objects
    assert rep.room_id_gaps == 2  # max_id 5 - 3 rooms
    assert rep.id_gap_wasted_bytes > 0
    assert rep.object_cell_raw_bytes > rep.object_cell_dedup_bytes  # id 5 deduplicated with id 2
    assert "GLYPH_TABLE_MISMATCH" not in {w.code for w in rep.warnings}
    assert "OBJECT_ROW_GROUP_MISMATCH" in {w.code for w in rep.warnings}

    # Verify independent ASM player against BOTH spec reference AND editor compose_room!
    asm_img = parse_generated_asm(out_dir)
    spec_screens = reference_compose_from_yaml(yaml_path)
    editor_proj = load_project(yaml_path).project

    # Check sanitized Polish identifiers
    assert asm_img.equates["OBJ_OKNO_POL"] == 1
    assert asm_img.equates["OBJ_CEGLA"] == 2
    assert asm_img.equates["TAG_ZLOTO_IDX"] == 2
    assert asm_img.equates["ROOM_KOMNATA_WSCHOD"] == 3
    assert asm_img.equates["STYLE_ZAMEK_GLOWNY_DZIEN"] == 0
    assert asm_img.equates["STYLE_ZAMEK_GLOWNY_NOC"] == 1
    assert "charset_zamek_glowny" in asm_img.symbols
    assert "charset_jaskinia" in asm_img.symbols

    # Tag bitmasks on ID 5 (Drabina bit 0 + Sciana bit 1 = $03) and gap ID 3 ($00)
    assert asm_img.read_id_byte("obj_tags0", 5) == 0x03
    assert asm_img.read_id_byte("obj_tags0", 3) == 0x00
    assert asm_img.read_id_byte("obj_w", 3) == 0x00
    assert asm_img.equates["OBJ_FLAG_PICKABLE"] == 0x04
    assert asm_img.read_id_byte("obj_flags", 4) == 0x07  # NB | COLPF3 | PICKABLE
    assert asm_img.read_id_byte("obj_flags", 2) == 0x00

    # Neighbours & gaps
    assert asm_img.read_id_byte("room_right", 1) == 3
    assert asm_img.read_id_byte("room_left", 3) == 1
    assert asm_img.read_id_byte("room_left", 5) == 0
    assert asm_img.read_id_byte("room_right", 5) == 0
    assert asm_img.read_id_byte("room_up", 5) == 0
    assert asm_img.read_id_byte("room_down", 5) == 0
    assert asm_img.read_id_byte("room_inst_count", 2) == 0  # gap ID 2

    # Deduplicated 24-row style table shared by Room 3 and Room 5
    assert asm_img.read_id_ptr("room_rowstyle_lo", "room_rowstyle_hi", 3) == asm_img.read_id_ptr(
        "room_rowstyle_lo", "room_rowstyle_hi", 5
    )

    for room_id in (1, 3, 5):
        played_grid, played_styles = play_room_from_asm(asm_img, room_id)
        assert played_grid == spec_screens[room_id]
        room_obj = editor_proj.get_room(room_id)
        assert room_obj is not None
        assert played_grid == compose_room(editor_proj, room_obj)
        if room_id == 1:
            assert played_styles == [0] * ROOM_HEIGHT
        else:
            assert played_styles == [1] * 12 + [0] * 12

    # Verify bidirectional teleport tables in ASM
    assert asm_img.equates["TELEPORT_COUNT"] == 2
    assert asm_img.memory[asm_img.symbols["tp_a_room"]] == 1
    assert asm_img.memory[asm_img.symbols["tp_a_x"]] == 2
    assert asm_img.memory[asm_img.symbols["tp_a_y"]] == 2
    assert asm_img.memory[asm_img.symbols["tp_b_room"]] == 5
    assert asm_img.memory[asm_img.symbols["tp_a_room"] + 1] == 3
    assert asm_img.memory[asm_img.symbols["tp_b_room"] + 1] == 3
    assert asm_img.memory[asm_img.symbols["tp_b_x"] + 1] == 30
    assert asm_img.memory[asm_img.symbols["tp_b_y"] + 1] == 20

    # Spot-check Room 1 semantics:
    r1 = spec_screens[1]
    # (1, 2): Blockable Cegła overrides non-blockable Pochodnia even though Cegła came first in YAML!
    assert r1[2][1] != 0 and r1[2][1] < 128
    # (5, 5): Okno Pół placed at (4, 5) has code 0 in cell (5, 5), so Pochodnia underneath (+128) shines through!
    assert r1[5][5] >= 128
    # (4, 5): Pochodnia placed after Okno Pół overwrites Okno Pół's cell (4, 5) with +128 code!
    assert r1[5][4] >= 128

    # Determinism check: compile again into another directory -> identical bytes
    out_dir_2 = tmp_path / "out2"
    compile_rooms(yaml_path, out_dir=out_dir_2)
    for fname in res.files:
        assert (out_dir / fname).read_text(encoding="utf-8") == (out_dir_2 / fname).read_text(
            encoding="utf-8"
        )


def test_limits_255_objects_127_glyphs_and_255_instances(tmp_path: Path) -> None:
    """Boundary tests: 255 objects OK / 256 error; 127 glyphs OK / 128 error; 255 instances OK / 256 error."""
    base = tmp_path / "lim"
    base.mkdir()
    _write_png(base / "g.png", 16, 16, lambda gx, gy: _unique_tile(gy * 16 + gx))

    def _base_doc(n_objs: int, n_inst: int, obj_regions: int) -> dict[str, Any]:
        # Up to `obj_regions` distinct tiles across objects, others reuse tile (0,0)
        objs = [
            {
                "id": i,
                "name": f"o_{i}",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 0,
                "frames": [
                    {
                        "x": ((i - 1) % 16) if i <= obj_regions else 0,
                        "y": ((i - 1) // 16) if i <= obj_regions else 0,
                        "w": 1,
                        "h": 1,
                    }
                ],
            }
            for i in range(1, n_objs + 1)
        ]
        placed = [{"object": 1, "x": i % ROOM_WIDTH, "y": (i // ROOM_WIDTH) % ROOM_HEIGHT} for i in range(n_inst)]
        return {
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
            "rooms": [{"id": 1, "name": "r1", "pos": [0, 0], "row_groups": ["g"], "placed": placed}],
            "teleports": [],
            "start": {"room": 1, "x": 0, "y": 0},
        }

    p = base / "p.yaml"
    # 255 objects, 127 unique glyphs, 255 instances -> MUST PASS
    p.write_text(yaml.safe_dump(_base_doc(255, 255, 127), sort_keys=False), encoding="utf-8")
    res = compile_rooms(p, out_dir=tmp_path / "ok")
    assert res.report.object_count == 255
    assert res.report.group_glyph_usage == [("g", 127)]

    # 128 unique glyphs -> FAIL
    p.write_text(yaml.safe_dump(_base_doc(128, 1, 128), sort_keys=False), encoding="utf-8")
    with pytest.raises(RoomCompileError, match="127 unique glyphs"):
        compile_rooms(p)

    # 256 objects -> FAIL
    p.write_text(yaml.safe_dump(_base_doc(256, 1, 1), sort_keys=False), encoding="utf-8")
    with pytest.raises(RoomCompileError, match="255"):
        compile_rooms(p)

    # 256 instances in one room -> FAIL
    p.write_text(yaml.safe_dump(_base_doc(1, 256, 1), sort_keys=False), encoding="utf-8")
    with pytest.raises(RoomCompileError, match="255"):
        compile_rooms(p)


def test_error_cases_write_no_files(tmp_path: Path) -> None:
    """Validation/IO errors return non-zero exit code and leave --out completely untouched."""
    p_dir = tmp_path / "err"
    p_dir.mkdir()
    _write_png(p_dir / "g.png", 4, 2, lambda gx, gy: _unique_tile(gy * 4 + gx))

    valid_doc: dict[str, Any] = {
        "version": 5,
        "object_groups": [
            {
                "name": "g",
                "image": "g.png",
                "pixel_mapping": [0, 1, 2, 3],
                "palettes": [{"name": "default", "colbk": 0, "colpf0": 10, "colpf1": 20, "colpf2": 30, "colpf3": 40}],
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
                "frames": [{"x": 0, "y": 0, "w": 2, "h": 2}],
            }
        ],
        "rooms": [
            {
                "id": 1,
                "name": "K1",
                "pos": [0, 0],
                "row_groups": ["g"],
                "placed": [{"object": 1, "x": 0, "y": 0}],
            }
        ],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }

    out_dir = tmp_path / "never_created"

    def _run_bad(mutator: Any) -> str:
        import copy

        doc = copy.deepcopy(valid_doc)
        mutator(doc)
        yfile = p_dir / "bad.yaml"
        yfile.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        # Capture CLI execution & ensure no files created
        rc = compiler_main([str(yfile), "--out", str(out_dir)])
        assert rc != 0
        assert not out_dir.exists()
        with pytest.raises(RoomCompileError) as exc_info:
            compile_rooms(yfile, out_dir=out_dir)
        assert not out_dir.exists()
        return str(exc_info.value)

    assert "version" in _run_bad(lambda d: d.__setitem__("version", 3)).lower()
    assert "unknown object" in _run_bad(lambda d: d["rooms"][0]["placed"].append({"object": 99, "x": 5, "y": 5})).lower()
    assert "outside" in _run_bad(lambda d: d["rooms"][0]["placed"].append({"object": 1, "x": 39, "y": 23})).lower()
    assert "overlap" in _run_bad(lambda d: d["rooms"][0]["placed"].append({"object": 1, "x": 1, "y": 1})).lower()
    assert "unknown palette" in _run_bad(
        lambda d: d["rooms"][0].__setitem__("row_groups", [{"group": "g", "palette": "missing"}])
    ).lower()
    assert "start" in _run_bad(lambda d: d.pop("start")).lower()
    assert "sanitized" in _run_bad(
        lambda d: d["objects"].append(
            {
                "id": 2,
                "name": "WALL!",
                "group": "g",
                "tags": [],
                "animation_speed": 0,
                "frames": [{"x": 1, "y": 0, "w": 1, "h": 1}],
            }
        )
    ).lower()

    # Non-indexed RGBA PNG rejected without writing output
    bad_png = Image.new("RGBA", (4, 8), (255, 0, 0, 255))
    bad_png.save(p_dir / "rgba.png", format="PNG")
    assert "indexed" in _run_bad(lambda d: d["object_groups"][0].__setitem__("image", "rgba.png")).lower()


def test_real_rooms_yaml_compile_player_and_mads(tmp_path: Path) -> None:
    """Compile repo's rooms.yaml, verify all rooms via ASM player + editor model, and assemble with MADS."""
    real_yaml = REPO_ROOT / "rooms.yaml"
    if not real_yaml.exists():
        pytest.skip("rooms.yaml not found at repository root")

    out_dir = tmp_path / "gen_real"
    res = compile_rooms(real_yaml, out_dir=out_dir)
    asm_img = parse_generated_asm(out_dir)
    spec_screens = reference_compose_from_yaml(real_yaml)
    editor_proj = load_project(real_yaml).project

    for room in editor_proj.rooms:
        played_grid, _styles = play_room_from_asm(asm_img, room.id)
        assert played_grid == spec_screens[room.id]
        assert played_grid == compose_room(editor_proj, room)

    # Assemble with MADS (if installed) in both conditional and aligned modes
    mads_bin = _find_mads()
    if mads_bin is None:
        pytest.skip("MADS assembler binary not installed")

    harness = tmp_path / "mads_harness.asm"
    harness.write_text(
        "\n".join(
            [
                f"    icl '{(out_dir / 'rooms_defs.asm').as_posix()}'",
                "    org $2000",
                f"    icl '{(out_dir / 'objects.asm').as_posix()}'",
                f"    icl '{(out_dir / 'rooms.asm').as_posix()}'",
                f"    icl '{(out_dir / 'teleports.asm').as_posix()}'",
                f"    icl '{(out_dir / 'animations.asm').as_posix()}'",
                "    org $4000",
                f"    icl '{(out_dir / 'charsets.asm').as_posix()}'",
                f"    icl '{(out_dir / 'styles.asm').as_posix()}'",
                "    org $02E0",
                "    .word $2000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    xex_out = tmp_path / "test_rooms.xex"
    lab_out = tmp_path / "test_rooms.lab"
    proc = subprocess.run(
        [
            str(mads_bin),
            str(harness),
            "-d:ROOMS_ALIGN_CHARSETS=1",
            f"-o:{xex_out}",
            f"-t:{lab_out}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"MADS failed:\n{proc.stdout}\n{proc.stderr}"
    assert xex_out.exists()
    lab_text = lab_out.read_text(encoding="utf-8")

    # Verify essential labels & equates in MADS symbol table and 1KB charset alignment
    labels: dict[str, int] = {}
    for line in lab_text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            # MADS .lab line format: `00 <ADDR> <SYMBOL>`
            try:
                labels[parts[2]] = int(parts[1], 16)
            except ValueError:
                pass

    for expected_sym in (
        "ROOM_WIDTH",
        "ROOM_HEIGHT",
        "ROOM_K1",
        "OBJ_BRICKS",
        "STYLE_CASTLE_DEFAULT",
        "TAG_LADDER",
        "CHARSET_CASTLE",
        "STYLE_CHBASE",
        "OBJ_W",
        "OBJ_W_BASE",
        "ROOM_LEFT",
        "ROOM_INST_LO",
        "TP_A_ROOM",
    ):
        assert expected_sym in labels, f"Missing MADS symbol {expected_sym}"

    assert labels["CHARSET_CASTLE"] % 0x400 == 0
    assert labels["OBJ_W"] == labels["OBJ_W_BASE"] - 1
    assert labels["ROOM_LEFT"] == labels["ROOM_LEFT_BASE"] - 1

    # Also verify `--align-charsets` mode assembles cleanly at non-aligned org
    aligned_dir = tmp_path / "gen_aligned"
    compile_rooms(real_yaml, out_dir=aligned_dir, align_charsets=True)
    harness2 = tmp_path / "mads_aligned.asm"
    harness2.write_text(
        "\n".join(
            [
                f"    icl '{(aligned_dir / 'rooms_defs.asm').as_posix()}'",
                "    org $2003",
                f"    icl '{(aligned_dir / 'charsets.asm').as_posix()}'",
                f"    icl '{(aligned_dir / 'styles.asm').as_posix()}'",
                f"    icl '{(aligned_dir / 'objects.asm').as_posix()}'",
                f"    icl '{(aligned_dir / 'rooms.asm').as_posix()}'",
                f"    icl '{(aligned_dir / 'teleports.asm').as_posix()}'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    lab2 = tmp_path / "test_aligned.lab"
    proc2 = subprocess.run(
        [str(mads_bin), str(harness2), f"-o:{tmp_path / 'a.xex'}", f"-t:{lab2}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc2.returncode == 0, f"MADS --align-charsets failed:\n{proc2.stdout}\n{proc2.stderr}"
    for line in lab2.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == "CHARSET_CASTLE":
            assert int(parts[1], 16) % 0x400 == 0


def test_build_deps_list_and_make_clean_convention() -> None:
    """Verify --list-deps CLI prints referenced PNG paths cleanly."""
    from io import StringIO
    from unittest.mock import patch

    buf = StringIO()
    with patch("sys.stdout", buf):
        rc = compiler_main([str(REPO_ROOT / "rooms.yaml"), "--list-deps"])
    assert rc == 0
    assert "castle.png" in buf.getvalue()


def simulate_room_animations_from_asm(
    asm_img: ParsedAsmImage, room_id: int, ticks: int
) -> list[dict[int, list[bytes]]]:
    """Simulate per-tick dedicated slot pattern bytes directly from Form 1/Form 2 ASM + pool."""
    rcount = asm_img.read_id_byte("room_anim_count", room_id)
    if rcount == 0:
        return [{} for _ in range(ticks + 1)]
    rptr = asm_img.read_id_ptr("room_anim_lo", "room_anim_hi", room_id)
    anim_ids = [asm_img.memory[rptr + i] for i in range(rcount)]
    pool_count = asm_img.equates["ANIM_POOL_COUNT"]

    def _read_u8(lbl: str, idx: int) -> int:
        return asm_img.memory[asm_img.symbols[lbl] + idx]

    def _read_u16(lbl_lo: str, lbl_hi: str, idx: int) -> int:
        return asm_img.memory[asm_img.symbols[lbl_lo] + idx] | (
            asm_img.memory[asm_img.symbols[lbl_hi] + idx] << 8
        )

    def _pattern_bytes(bank: int, pat_idx: int) -> bytes:
        if pool_count <= 1:
            return bytes(asm_img.memory[asm_img.symbols[f"anim_pool0_b{r}"] + pat_idx] for r in range(8))
        out = bytearray(8)
        for r in range(8):
            ptr = _read_u16("anim_pb_lo", "anim_pb_hi", bank * 8 + r)
            out[r] = asm_img.memory[ptr + pat_idx]
        return bytes(out)

    def _frame_patterns(aid: int) -> list[list[bytes]]:
        nframes = _read_u8("anim_frames", aid)
        nslots = _read_u8("anim_slots", aid)
        flags = _read_u8("anim_flags", aid)
        bank = flags & 0x7F
        use_f2 = bool(flags & 0x80)
        dptr = _read_u16("anim_data_lo", "anim_data_hi", aid)
        if not use_f2:
            return [
                [_pattern_bytes(bank, asm_img.memory[dptr + f * nslots + s]) for s in range(nslots)]
                for f in range(nframes)
            ]
        # Form 2: reconstruct per-frame slots cleanly starting from frame 0 and applying cyclic deltas
        cur_pats = list(asm_img.memory[dptr : dptr + nslots])
        frames_out: list[list[bytes]] = [[_pattern_bytes(bank, p) for p in cur_pats]]
        dtbl = dptr + nslots
        for k in range(1, nframes):
            dp = asm_img.memory[dtbl + k] | (asm_img.memory[dtbl + nframes + k] << 8)
            cnt = asm_img.memory[dp]
            for pi in range(cnt):
                cur_pats[asm_img.memory[dp + 1 + 2 * pi]] = asm_img.memory[dp + 2 + 2 * pi]
            frames_out.append([_pattern_bytes(bank, p) for p in cur_pats])
        # Verify cyclic delta 0 returns back cleanly to frame 0!
        dp0 = asm_img.memory[dtbl] | (asm_img.memory[dtbl + nframes] << 8)
        for pi in range(asm_img.memory[dp0]):
            cur_pats[asm_img.memory[dp0 + 1 + 2 * pi]] = asm_img.memory[dp0 + 2 + 2 * pi]
        assert [_pattern_bytes(bank, p) for p in cur_pats] == frames_out[0]
        return frames_out

    all_frames = {aid: _frame_patterns(aid) for aid in anim_ids}
    counters = [_read_u8("anim_speed", aid) for aid in anim_ids]
    frames = [0] * rcount
    snapshots: list[dict[int, list[bytes]]] = [{aid: all_frames[aid][0] for aid in anim_ids}]

    for _t in range(ticks):
        for i, aid in enumerate(anim_ids):
            counters[i] -= 1
            if counters[i] == 0:
                counters[i] = _read_u8("anim_speed", aid)
                frames[i] = (frames[i] + 1) % _read_u8("anim_frames", aid)
        snapshots.append({aid: all_frames[aid][frames[i]] for i, aid in enumerate(anim_ids)})
    return snapshots


def test_animation_compilation_forms_pooling_and_simulation(tmp_path: Path) -> None:
    """Test constant-cell deduplication, within-object sharing, cross-object pool, and Form 1 vs Form 2."""
    proj_dir = tmp_path / "anim_proj"
    proj_dir.mkdir()

    # Palette/tiles on a 20x4 sheet:
    # Tile (0,0) = 0xAA [constant brick], Tile (1,0) = 0x00 [constant empty]
    # Object 2 ('torch', 3x1, 3 frames, speed=2):
    #   cell 0: const (0,0)=0xAA (shares static wall!)
    #   cells 1 & 2: IDENTICAL varying seq -> shares 1 dedicated slot! (Form 1: S=1, F=3 -> 3B <= Form 2: 1+6+3*3=16B)
    # Object 3 ('beacon', 4x1, 8 frames, speed=3):
    #   cell 0: const 0xAA
    #   cells 1..3: vary only 1 slot on each transition -> Form 2 (3 + 16 + 8*3 = 43B vs Form 1: 24B? Wait: make 6x1, 6 slots, 8 frames!)
    #   6 slots x 8 frames: Form 1 = 48B; Form 2 with 1 change/frame = 6 + 16 + 8*3 = 46B < 48B -> FORM 2!
    # Object 4 ('echo', 1x1, 2 frames, speed=2):
    #   reuses exact same pattern bytes as torch frame 0/1 -> tests cross-object pattern pooling!
    tiles: dict[tuple[int, int], int] = {(0, 0): 0xAA, (1, 0): 0x00}
    # torch frames (y=0, width=3 at x=2,5,8): col 0 is 0xAA, cols 1&2 equal
    for f, fx in enumerate((2, 5, 8)):
        tiles[(fx, 0)] = 0xAA
        tiles[(fx + 1, 0)] = 0x20 + f + 1
        tiles[(fx + 2, 0)] = 0x20 + f + 1
    # echo at y=0, x=11 (f0) and x=12 (f1) matching torch's varying pattern 0x21 and 0x22
    tiles[(11, 0)] = 0x21
    tiles[(12, 0)] = 0x22
    # Clean 1-change cyclic walk over 7 slots in 14 frames:
    # f=1..7 flip slots 0..6 ON; f=8..13 flip slots 0..5 OFF; f=0 flips slot 6 OFF -> 1 change/frame!
    # F1 = 7 * 14 = 98 B; F2 = 7 + 28 + 14 * 3 = 77 B < 98 B!
    cur = [0x40 + i * 2 for i in range(7)]
    for f in range(14):
        if f == 0:
            cur = [0x40 + i * 2 for i in range(7)]
        elif 1 <= f <= 7:
            cur[f - 1] ^= 0x80
        else:
            cur[f - 8] ^= 0x80
        for dx in range(7):
            tiles[(dx, 1 + f)] = cur[dx]

    def tile_fn(gx: int, gy: int) -> list[list[int]]:
        v = tiles.get((gx, gy), 0)
        return [[v & 3, (v >> 2) & 3, (v >> 4) & 3, (v >> 6) & 3] for _ in range(8)]

    _write_png(proj_dir / "g.png", 16, 16, tile_fn)
    doc: dict[str, Any] = {
        "version": 5,
        "object_groups": [
            {
                "name": "grp",
                "image": "g.png",
                "pixel_mapping": [0, 1, 2, 3],
                "palettes": [{"name": "default", "colbk": 0, "colpf0": 10, "colpf1": 20, "colpf2": 30, "colpf3": 40}],
            }
        ],
        "objects": [
            {
                "id": 1,
                "name": "wall",
                "group": "grp",
                "tags": [],
                "non-blockable": False,
                "colpf3": False,
                "animation_speed": 0,
                "frames": [{"x": 0, "y": 0, "w": 1, "h": 1}],
            },
            {
                "id": 2,
                "name": "torch",
                "group": "grp",
                "tags": [],
                "non-blockable": True,
                "colpf3": True,
                "animation_speed": 2,
                "frames": [{"x": fx, "y": 0, "w": 3, "h": 1} for fx in (2, 5, 8)],
            },
            {
                "id": 3,
                "name": "beacon",
                "group": "grp",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 3,
                "frames": [{"x": 0, "y": 1 + f, "w": 7, "h": 1} for f in range(14)],
            },
            {
                "id": 4,
                "name": "echo",
                "group": "grp",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 2,
                "frames": [{"x": 11, "y": 0, "w": 1, "h": 1}, {"x": 12, "y": 0, "w": 1, "h": 1}],
            },
        ],
        "rooms": [
            {
                "id": 1,
                "name": "R_Static",
                "pos": [0, 0],
                "row_groups": ["grp"],
                "placed": [{"object": 1, "x": 0, "y": 0}],
            },
            {
                "id": 2,
                "name": "R_Anim",
                "pos": [1, 0],
                "row_groups": ["grp"],
                "placed": [
                    {"object": 2, "x": 2, "y": 2},
                    {"object": 2, "x": 10, "y": 6},
                    {"object": 3, "x": 0, "y": 10},
                    {"object": 4, "x": 30, "y": 10},
                ],
            },
        ],
        "teleports": [],
        "start": {"room": 2, "x": 1, "y": 1},
    }
    yfile = proj_dir / "rooms.yaml"
    yfile.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    out_dir = tmp_path / "out_anim"
    res = compile_rooms(yfile, out_dir=out_dir)

    rep = res.report
    assert rep.anim_count == 3
    assert rep.anim_pool_count == 1
    assert rep.max_room_anims == 3
    # grp: 1 static (0xAA) + 1 (torch shared) + 7 (beacon) + 1 (echo) = 10 total!
    assert rep.group_glyph_breakdown == [("grp", 10, 1, 9)]
    # torch = Form 1, beacon = Form 2 (77 B < 98 B), echo = Form 1
    assert rep.anim_stats[0].form == "form1"
    assert rep.anim_stats[1].form == "form2"
    assert rep.anim_stats[1].encoded_bytes == 77
    assert rep.anim_stats[1].naive_bytes == 784
    assert rep.anim_frame_dedup_bytes < rep.anim_frame_raw_bytes
    # Cross-object pooling: torch(3 distinct) + beacon(14 distinct) + echo(0 extra because reused from torch!) = 17 patterns!
    assert rep.anim_pattern_count == 17

    asm_img = parse_generated_asm(out_dir)
    assert asm_img.equates["ANIM_COUNT"] == 3
    assert asm_img.equates["ANIM_POOL_COUNT"] == 1
    assert asm_img.equates["MAX_ROOM_FORM1_SLOTS"] == 2  # torch(1) + echo(1), Form 2 uses 0!

    # Constant cell of torch uses static code 1 (+128 colpf3 -> $81); varying cells 1 & 2 share code 2 (+128 -> $82)
    t_ptr = asm_img.read_id_ptr("obj_data_lo", "obj_data_hi", 2)
    assert list(asm_img.memory[t_ptr : t_ptr + 3]) == [0x81, 0x82, 0x82]
    assert asm_img.read_id_byte("anim_slots", 0) if "anim_slots" in asm_img.equates else asm_img.memory[asm_img.symbols["anim_slots"]] == 1

    # Simulate both Form 1 and Form 2 from ASM and verify exact charset slot progression
    snaps = simulate_room_animations_from_asm(asm_img, 2, 12)
    ch_base = asm_img.symbols["charset_grp"]
    # Initial charset at dedicated codes 2 (torch), 3..9 (beacon), 10 (echo) matches tick 0!
    assert [bytes(asm_img.memory[ch_base + 2 * 8 : ch_base + 3 * 8])] == snaps[0][0]
    assert [bytes(asm_img.memory[ch_base + c * 8 : ch_base + (c + 1) * 8]) for c in range(3, 10)] == snaps[0][1]
    assert snaps[2][0] != snaps[0][0]
    assert snaps[6][0] == snaps[0][0]  # torch wraps after 3 * 2 = 6 ticks
    assert snaps[3][1] != snaps[0][1]  # beacon steps every 3 ticks


def test_animation_only_group_without_png_and_pool_split(tmp_path: Path) -> None:
    """Verify missing-PNG YAML dedicated glyphs compilation AND >256-pattern deterministic pool split."""
    proj_dir = tmp_path / "nopng"
    proj_dir.mkdir()
    f0 = "1122334455667788"
    f1 = "8877665544332211"
    doc: dict[str, Any] = {
        "version": 5,
        "object_groups": [
            {
                "name": "fx",
                "image": "missing_ok.png",
                "pixel_mapping": [0, 1, 2, 3],
                "palettes": [{"name": "default", "colbk": 0, "colpf0": 1, "colpf1": 2, "colpf2": 3, "colpf3": 4}],
                "glyphs": [
                    {"code": 1, "data": f0, "object": 1, "cells": [[0, 0]], "frames": [f0, f1]}
                ],
            }
        ],
        "objects": [
            {
                "id": 1,
                "name": "spark",
                "group": "fx",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 4,
                "frames": [{"x": 0, "y": 0, "w": 1, "h": 1}, {"x": 1, "y": 0, "w": 1, "h": 1}],
            }
        ],
        "rooms": [{"id": 1, "name": "r", "pos": [0, 0], "row_groups": ["fx"], "placed": [{"object": 1, "x": 1, "y": 1}]}],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }
    yfile = proj_dir / "rooms.yaml"
    yfile.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    out_dir = tmp_path / "out_nopng"
    res = compile_rooms(yfile, out_dir=out_dir)
    assert res.report.anim_count == 1
    asm_img = parse_generated_asm(out_dir)
    snaps = simulate_room_animations_from_asm(asm_img, 1, 4)
    assert snaps[0][0] == [bytes.fromhex(f0)]
    assert snaps[4][0] == [bytes.fromhex(f1)]

    # Now test deterministic pool split (> 256 distinct patterns across animated objects -> ANIM_POOL_COUNT >= 2)
    split_dir = tmp_path / "split"
    split_dir.mkdir()
    # Build 20x16 tile PNG where every tile (gx, gy) produces a unique 8-byte pattern: [1+gx, 1+gy, ...]
    def _pat_tile(gx: int, gy: int) -> list[list[int]]:
        v = gy * 20 + gx + 1
        rows = []
        for py in range(8):
            val = ((v >> 8) + 1) if py == 7 else ((v + py * 31) & 0xFF or 1)
            rows.append([val & 3, (val >> 2) & 3, (val >> 4) & 3, (val >> 6) & 3])
        return rows

    _write_png(split_dir / "big.png", 20, 16, _pat_tile)
    # Two animated objects: obj 1 has 1x10 (10 slots) x 16 frames = 160 distinct patterns;
    # obj 2 has 1x8 (8 slots) x 16 frames = 128 distinct patterns -> 160 + 128 = 288 > 256 -> split into 2 banks!
    # Total dedicated glyphs in 'g' = 18 <= 127!
    big_doc = {
        "version": 5,
        "object_groups": [
            {
                "name": "g",
                "image": "big.png",
                "pixel_mapping": [0, 1, 2, 3],
                "palettes": [{"name": "default", "colbk": 0, "colpf0": 1, "colpf1": 2, "colpf2": 3, "colpf3": 4}],
            }
        ],
        "objects": [
            {
                "id": 1,
                "name": "big_a",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 2,
                "frames": [{"x": f, "y": 0, "w": 1, "h": 10} for f in range(16)],
            },
            {
                "id": 2,
                "name": "big_b",
                "group": "g",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 3,
                "frames": [{"x": f, "y": 10, "w": 1, "h": 6} for f in range(16)],
            },
        ],
        "rooms": [
            {
                "id": 1,
                "name": "rs",
                "pos": [0, 0],
                "row_groups": ["g"],
                "placed": [{"object": 1, "x": 0, "y": 0}, {"object": 2, "x": 5, "y": 0}],
            }
        ],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }
    # 10*16 = 160 patterns (obj 1) + 6*16 = 96 -> total 256! Wait add 1 frame or make big_b h=6 + obj 3 -> make frames count = 16 on h=6? Make big_a y=0 h=10 (x=0..15 -> 160), big_b x=0..15 y=10 h=6 -> make big_a x=0..16 or 17 -> png width=20, max f=16, so add obj 3 (id=3, x=16, y=0..1, 1x2x2=4 -> 260 > 256)!
    big_doc["objects"].append(
        {
            "id": 3,
            "name": "big_c",
            "group": "g",
            "tags": [],
            "non-blockable": True,
            "colpf3": False,
            "animation_speed": 4,
            "frames": [{"x": 17, "y": 0, "w": 1, "h": 1}, {"x": 18, "y": 0, "w": 1, "h": 1}],
        }
    )
    big_doc["rooms"][0]["placed"].append({"object": 3, "x": 10, "y": 0})
    ysplit = split_dir / "rooms.yaml"
    ysplit.write_text(yaml.safe_dump(big_doc, sort_keys=False), encoding="utf-8")
    out_split = tmp_path / "out_split"
    res_split = compile_rooms(ysplit, out_dir=out_split)
    assert res_split.report.anim_pool_count == 2
    assert res_split.report.anim_pattern_count > 256
    asm_split = parse_generated_asm(out_split)
    assert "anim_pb_lo" in asm_split.symbols
    snaps_split = simulate_room_animations_from_asm(asm_split, 1, 4)
    assert snaps_split[2][0] != snaps_split[0][0]
    assert snaps_split[3][1] != snaps_split[0][1]
    assert snaps_split[4][2] != snaps_split[0][2]


def test_animation_compile_errors_and_mads(tmp_path: Path) -> None:
    """Reject >16 frames, size mismatches, foreign-group animated placement, and assemble animations.asm."""
    proj_dir = tmp_path / "aerr"
    proj_dir.mkdir()
    tile_a_fn = lambda gx, gy: _unique_tile(1 + gy * 8 + gx)
    _write_png(proj_dir / "a.png", 8, 2, tile_a_fn)
    _write_png(proj_dir / "b.png", 4, 1, lambda gx, _gy: _unique_tile(50 + gx))
    base: dict[str, Any] = {
        "version": 5,
        "object_groups": [
            {
                "name": "ga",
                "image": "a.png",
                "pixel_mapping": [0, 1, 2, 3],
                "palettes": [{"name": "default", "colbk": 0, "colpf0": 1, "colpf1": 2, "colpf2": 3, "colpf3": 4}],
            },
            {
                "name": "gb",
                "image": "b.png",
                "pixel_mapping": [0, 1, 2, 3],
                "palettes": [{"name": "default", "colbk": 0, "colpf0": 5, "colpf1": 6, "colpf2": 7, "colpf3": 8}],
            },
        ],
        "objects": [
            {
                "id": 1,
                "name": "torch",
                "group": "ga",
                "tags": [],
                "non-blockable": True,
                "colpf3": False,
                "animation_speed": 5,
                "frames": [{"x": 0, "y": 0, "w": 1, "h": 1}, {"x": 1, "y": 0, "w": 1, "h": 1}],
            }
        ],
        "rooms": [
            {
                "id": 1,
                "name": "r1",
                "pos": [0, 0],
                "row_groups": ["ga"] * 12 + ["gb"] * 12,
                "placed": [{"object": 1, "x": 2, "y": 2}],
            }
        ],
        "teleports": [],
        "start": {"room": 1, "x": 0, "y": 0},
    }
    import copy

    def _expect_err(mut, substr: str) -> None:
        d = copy.deepcopy(base)
        mut(d)
        yf = proj_dir / "err.yaml"
        yf.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
        out_bad = tmp_path / "never_anim_out"
        with pytest.raises(RoomCompileError) as ei:
            compile_rooms(yf, out_dir=out_bad)
        assert substr in str(ei.value).lower()
        assert not out_bad.exists()

    _expect_err(
        lambda d: d["objects"][0].__setitem__("frames", [{"x": 0, "y": 0, "w": 1, "h": 1}] * 17),
        "16",
    )
    _expect_err(
        lambda d: d["objects"][0]["frames"][1].__setitem__("w", 2),
        "differs",
    )
    _expect_err(
        lambda d: d["rooms"][0]["placed"].__setitem__(0, {"object": 1, "x": 2, "y": 15}),
        "animated",
    )

    # Valid case assembles cleanly with MADS
    mads_bin = _find_mads()
    if mads_bin is None:
        pytest.skip("MADS not installed")
    yf_ok = proj_dir / "ok.yaml"
    yf_ok.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")
    out_ok = tmp_path / "ok_out"
    compile_rooms(yf_ok, out_dir=out_ok)
    h = tmp_path / "anim_mads.asm"
    h.write_text(
        "\n".join(
            [
                f"    icl '{(out_ok / 'rooms_defs.asm').as_posix()}'",
                "    org $2000",
                f"    icl '{(out_ok / 'objects.asm').as_posix()}'",
                f"    icl '{(out_ok / 'rooms.asm').as_posix()}'",
                f"    icl '{(out_ok / 'animations.asm').as_posix()}'",
                "    org $4000",
                f"    icl '{(out_ok / 'charsets.asm').as_posix()}'",
                f"    icl '{(out_ok / 'styles.asm').as_posix()}'",
                "    org $02E0",
                "    .word $2000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(mads_bin), str(h), "-d:ROOMS_ALIGN_CHARSETS=1", f"-o:{tmp_path / 'anim.xex'}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"MADS failed:\n{proc.stdout}\n{proc.stderr}"

