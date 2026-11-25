#!/usr/bin/env python3
"""Render a compiled room from gen/*.asm to an ANTIC Mode 4 PNG image."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from PIL import Image

ANTIC4_ASPECT_X = 2
CELL_PIXEL_W = 4
CELL_PIXEL_H = 8


class RenderRoomError(Exception):
    """Raised when generated room data or arguments cannot be rendered."""


@dataclass
class CompiledRoomImage:
    """Virtual 64 KB memory, symbols, equates, and room metadata parsed from gen/*.asm."""

    memory: bytearray = field(default_factory=bytearray)
    symbols: dict[str, int] = field(default_factory=dict)
    equates: dict[str, int] = field(default_factory=dict)
    room_names: dict[str, int] = field(default_factory=dict)

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
    raise RenderRoomError(f"Cannot evaluate expression token '{token}'.")


def load_compiled_rooms(gen_dir: Path, *, base_org: int = 0x6000) -> CompiledRoomImage:
    """Parse generated gen/*.asm files (two-pass MADS subset) into virtual memory."""
    order = [
        "rooms_defs.asm",
        "charsets.asm",
        "styles.asm",
        "objects.asm",
        "rooms.asm",
        "teleports.asm",
    ]
    missing = [name for name in order if not (gen_dir / name).exists()]
    if missing:
        raise RenderRoomError(f"Missing generated file(s) in {gen_dir}: {', '.join(missing)}")

    raw_lines: list[str] = []
    room_names: dict[str, int] = {}
    room_comment_re = re.compile(r"^(ROOM_[A-Z0-9_]+)\s*=\s*(\d+)\s*;\s*'([^']+)'")

    for fname in order:
        text = (gen_dir / fname).read_text(encoding="utf-8")
        for line in text.splitlines():
            if fname == "rooms_defs.asm":
                m_room = room_comment_re.match(line.strip())
                if m_room:
                    rid = int(m_room.group(2))
                    room_names[m_room.group(1).upper()] = rid
                    room_names[m_room.group(3).upper()] = rid
            code = line.split(";", 1)[0].strip()
            if code:
                raw_lines.append(code)

    def _run_pass(
        pass_symbols: dict[str, int],
        pass_equates: dict[str, int],
        *,
        populate_mem: bool,
    ) -> tuple[bytearray, dict[str, int], dict[str, int]]:
        pc = base_org
        mem = bytearray(0x10000)
        syms: dict[str, int] = {}
        eqs: dict[str, int] = dict(pass_equates)
        eqs["ROOMS_ALIGN_CHARSETS"] = 1
        if_stack: list[bool] = []

        for code in raw_lines:
            low = code.lower()
            if low.startswith(".ifdef "):
                sym = code.split(None, 1)[1].strip()
                if_stack.append(sym in eqs)
                continue
            if low == ".endif":
                if_stack.pop()
                continue
            if not all(if_stack):
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
                    if expr.startswith("<"):
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

            if "=" in code:
                lhs, rhs = (p.strip() for p in code.split("=", 1))
                m_sub = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*-\s*1", rhs)
                if m_sub:
                    base = syms.get(m_sub.group(1), pass_symbols.get(m_sub.group(1), 0))
                    syms[lhs] = base - 1
                    eqs[lhs] = base - 1
                else:
                    eqs[lhs] = _eval_atom(rhs, eqs)
                continue

            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", code):
                syms[code] = pc
                continue

            raise RenderRoomError(f"Unrecognized generated ASM line: {code!r}")

        return mem, syms, eqs

    _, pass1_syms, pass1_eqs = _run_pass({}, {}, populate_mem=False)
    mem, pass2_syms, pass2_eqs = _run_pass(pass1_syms, pass1_eqs, populate_mem=True)
    return CompiledRoomImage(
        memory=mem,
        symbols=pass2_syms,
        equates=pass2_eqs,
        room_names=room_names,
    )


def resolve_room_id(img: CompiledRoomImage, spec: str) -> int:
    """Resolve room specification ('start', room ID, or room name) to 1-based ID."""
    trimmed = spec.strip()
    if not trimmed:
        raise RenderRoomError("Empty room specifier.")
    if trimmed.lower() == "start":
        return img.equates["START_ROOM"]

    max_id = img.equates["ROOM_MAX_ID"]
    if trimmed.isdigit():
        rid = int(trimmed, 10)
    else:
        key = trimmed.upper()
        if key in img.room_names:
            rid = img.room_names[key]
        elif f"ROOM_{key}" in img.equates:
            rid = img.equates[f"ROOM_{key}"]
        else:
            raise RenderRoomError(f"Unknown room '{spec}'.")

    if not (1 <= rid <= max_id):
        raise RenderRoomError(f"Room ID {rid} out of range 1..{max_id}.")
    return rid


def load_pal_rgb_table(palette_path: Path) -> list[tuple[int, int, int]]:
    """Load 256-entry Atari PAL RGB table from JSON."""
    if not palette_path.exists():
        raise RenderRoomError(f"PAL palette file not found: {palette_path}")
    raw = json.loads(palette_path.read_text(encoding="utf-8"))
    entries = raw.get("colors") if isinstance(raw, dict) else raw
    if not isinstance(entries, list) or len(entries) != 256:
        raise RenderRoomError(f"Invalid 256-color PAL palette in {palette_path}")
    return [(int(c[0]), int(c[1]), int(c[2])) for c in entries]


def compose_room_screen(
    img: CompiledRoomImage,
    room_id: int,
) -> tuple[list[list[int]], list[int]]:
    """Decode screen cells (24x40) and per-row style IDs (24) from compiled tables."""
    width = img.equates["ROOM_WIDTH"]
    height = img.equates["ROOM_HEIGHT"]
    y_coord_mask = img.equates["INST_Y_COORD_MASK"]
    y_rep_mask = img.equates["INST_Y_REPEAT_MASK"]
    uniform_mask = img.equates["ROOM_FLAG_UNIFORM_STYLE"]

    screen = [[0] * width for _ in range(height)]
    inst_count = img.read_id_byte("room_inst_count", room_id)
    if inst_count > 0:
        base_ptr = img.read_id_ptr("room_inst_lo", "room_inst_hi", room_id)
        rep_count = img.read_id_byte("room_rep_count", room_id)
        p_obj = base_ptr
        p_x = base_ptr + inst_count
        p_yf = base_ptr + 2 * inst_count
        p_rw = base_ptr + 3 * inst_count
        p_rh = p_rw + rep_count

        rep_cursor = 0
        for i in range(inst_count):
            oid = img.memory[p_obj + i]
            ix = img.memory[p_x + i]
            yf = img.memory[p_yf + i]
            iy = yf & y_coord_mask
            if yf & y_rep_mask:
                rw = img.memory[p_rw + rep_cursor]
                rh = img.memory[p_rh + rep_cursor]
                rep_cursor += 1
            else:
                rw, rh = 1, 1

            ow = img.read_id_byte("obj_w", oid)
            oh = img.read_id_byte("obj_h", oid)
            optr = img.read_id_ptr("obj_data_lo", "obj_data_hi", oid)

            for ry in range(rh):
                for rx in range(rw):
                    bx = ix + rx * ow
                    by = iy + ry * oh
                    for dy in range(oh):
                        for dx in range(ow):
                            code = img.memory[optr + dy * ow + dx]
                            if code != 0:
                                screen[by + dy][bx + dx] = code

    rflags = img.read_id_byte("room_flags", room_id)
    if rflags & uniform_mask:
        sid = img.read_id_byte("room_rowstyle_lo", room_id)
        row_styles = [sid] * height
    else:
        rs_ptr = img.read_id_ptr("room_rowstyle_lo", "room_rowstyle_hi", room_id)
        row_styles = [img.memory[rs_ptr + r] for r in range(height)]

    return screen, row_styles


def render_room_image(
    img: CompiledRoomImage,
    room_id: int,
    pal_rgb: Sequence[tuple[int, int, int]],
    *,
    scale: int = 1,
) -> Image.Image:
    """Render a compiled room into an ANTIC Mode 4 RGB Pillow Image."""
    if scale < 1:
        raise RenderRoomError(f"Scale must be >= 1; got {scale}.")

    width_cells = img.equates["ROOM_WIDTH"]
    height_cells = img.equates["ROOM_HEIGHT"]
    screen, row_styles = compose_room_screen(img, room_id)

    style_chbase_addr = img.symbols["style_chbase"]
    style_colbk_addr = img.symbols["style_colbk"]
    style_colpf0_addr = img.symbols["style_colpf0"]
    style_colpf1_addr = img.symbols["style_colpf1"]
    style_colpf2_addr = img.symbols["style_colpf2"]
    style_colpf3_addr = img.symbols["style_colpf3"]

    disp_w = width_cells * CELL_PIXEL_W * ANTIC4_ASPECT_X
    disp_h = height_cells * CELL_PIXEL_H
    rgb_buf = bytearray(disp_w * disp_h * 3)

    for row in range(height_cells):
        sid = row_styles[row]
        chbase_addr = img.memory[style_chbase_addr + sid] << 8
        c_bk = pal_rgb[img.memory[style_colbk_addr + sid] & 0xFE]
        c_pf0 = pal_rgb[img.memory[style_colpf0_addr + sid] & 0xFE]
        c_pf1 = pal_rgb[img.memory[style_colpf1_addr + sid] & 0xFE]
        c_pf2 = pal_rgb[img.memory[style_colpf2_addr + sid] & 0xFE]
        c_pf3 = pal_rgb[img.memory[style_colpf3_addr + sid] & 0xFE]

        row_cells = screen[row]
        for col in range(width_cells):
            code = row_cells[col]
            glyph_idx = code & 0x7F
            alt_col = c_pf3 if (code & 0x80) else c_pf2
            glyph_addr = chbase_addr + glyph_idx * CELL_PIXEL_H
            colors = (c_bk, c_pf0, c_pf1, alt_col)

            for py in range(CELL_PIXEL_H):
                gbyte = img.memory[glyph_addr + py]
                y_px = row * CELL_PIXEL_H + py
                base_out = (y_px * disp_w + col * CELL_PIXEL_W * ANTIC4_ASPECT_X) * 3
                for px in range(CELL_PIXEL_W):
                    pair = (gbyte >> (6 - px * 2)) & 0x03
                    r, g, b = colors[pair]
                    off = base_out + px * ANTIC4_ASPECT_X * 3
                    rgb_buf[off] = r
                    rgb_buf[off + 1] = g
                    rgb_buf[off + 2] = b
                    rgb_buf[off + 3] = r
                    rgb_buf[off + 4] = g
                    rgb_buf[off + 5] = b

    pil_img = Image.frombytes("RGB", (disp_w, disp_h), bytes(rgb_buf))
    if scale > 1:
        pil_img = pil_img.resize(
            (disp_w * scale, disp_h * scale),
            resample=Image.Resampling.NEAREST,
        )
    return pil_img


def build_arg_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    repo_root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="Render a compiled room from gen/*.asm to an ANTIC Mode 4 PNG."
    )
    parser.add_argument(
        "--room",
        default="start",
        help="Room to render: 'start' (default), 1-based room ID, or room name (e.g. K1).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output PNG file path.",
    )
    parser.add_argument(
        "--gen-dir",
        type=Path,
        default=repo_root / "gen",
        help="Directory containing generated rooms*.asm files (default: gen).",
    )
    parser.add_argument(
        "--palette",
        type=Path,
        default=repo_root / "room_editor" / "data" / "pal_palette.json",
        help="Path to 256-entry PAL RGB palette JSON.",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=1,
        help="Integer nearest-neighbor output scaling factor (default: 1 -> 320x192).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        img = load_compiled_rooms(args.gen_dir)
        room_id = resolve_room_id(img, args.room)
        pal_rgb = load_pal_rgb_table(args.palette)
        rendered = render_room_image(img, room_id, pal_rgb, scale=args.scale)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        rendered.save(args.out, format="PNG")
    except RenderRoomError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    print(f"Rendered room {room_id} -> {args.out} ({rendered.width}x{rendered.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
