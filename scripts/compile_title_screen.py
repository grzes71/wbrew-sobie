#!/usr/bin/env python3
"""Compile title screen JSON metadata and charsets into MADS assembly (RLE + DLIST + DLI tables)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class TitleCompileError(Exception):
    """Raised when title screen validation or compilation fails."""


@dataclass(frozen=True)
class CharsetSegment:
    """Single non-overlapping character set band on the title screen."""

    index: int
    charset_file: str
    start_line: int
    end_line: int
    unique_characters: int
    glifs: list[int]
    filled_glyphs: int = 0
    fill_font: str = ""


def rle_compress(data: Sequence[int]) -> bytes:
    """Compress byte sequence using Tebe/MadTeam RLE format.

    Format:
      - 0x00: End of stream
      - LSB == 0: Repeat run of ((ctrl >> 1) + 1) copies of following byte (for runs >= 3)
      - LSB == 1: Literal run of ((ctrl >> 1) + 1) raw bytes (1..128 bytes)
    """
    out = bytearray()
    n = len(data)
    i = 0

    while i < n:
        run_len = 1
        while i + run_len < n and data[i + run_len] == data[i] and run_len < 128:
            run_len += 1

        if run_len >= 3:
            out.append((run_len - 1) << 1)
            out.append(data[i] & 0xFF)
            i += run_len
        else:
            lit_start = i
            lit_len = 0
            while i < n and lit_len < 128:
                r = 1
                while i + r < n and data[i + r] == data[i] and r < 128:
                    r += 1
                if r >= 3:
                    break
                i += 1
                lit_len += 1
            out.append(((lit_len - 1) << 1) | 1)
            out.extend(b & 0xFF for b in data[lit_start : lit_start + lit_len])

    out.append(0x00)
    return bytes(out)


def rle_decompress(encoded: bytes | Sequence[int]) -> list[int]:
    """Decompress Tebe/MadTeam RLE byte stream (reference model for verification)."""
    out: list[int] = []
    i = 0
    n = len(encoded)

    while i < n:
        ctrl = encoded[i]
        i += 1
        if ctrl == 0:
            return out
        count = (ctrl >> 1) + 1
        if ctrl & 1:
            if i + count > n:
                raise TitleCompileError("RLE literal run truncated before end of stream.")
            out.extend(encoded[i : i + count])
            i += count
        else:
            if i >= n:
                raise TitleCompileError("RLE repeat run missing value byte.")
            val = encoded[i]
            i += 1
            out.extend([val] * count)

    raise TitleCompileError("RLE stream missing terminating 0x00 byte.")


def parse_and_validate_json(json_path: Path) -> list[CharsetSegment]:
    """Load and validate charset segments from the JSON file."""
    if not json_path.exists():
        raise TitleCompileError(f"ERROR: JSON file not found: {json_path}")

    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise TitleCompileError(f"ERROR: Cannot parse JSON '{json_path}': {exc}") from exc

    if not isinstance(raw, dict) or "charsets" not in raw or not isinstance(raw["charsets"], list):
        raise TitleCompileError("ERROR: JSON must contain a 'charsets' list.")

    segments: list[CharsetSegment] = []
    expected_start = 0

    for idx, item in enumerate(raw["charsets"]):
        try:
            seg = CharsetSegment(
                index=int(item["index"]),
                charset_file=str(item["charset_file"]),
                start_line=int(item["start_line"]),
                end_line=int(item["end_line"]),
                unique_characters=int(item["unique_characters"]),
                glifs=[int(g) for g in item["glifs"]],
                filled_glyphs=int(item.get("filled_glyphs", 0)),
                fill_font=str(item.get("fill_font", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TitleCompileError(f"ERROR: Invalid segment entry at index {idx}: {exc}") from exc

        if seg.index != idx:
            raise TitleCompileError(f"ERROR: Expected charset index {idx}, got {seg.index}.")
        if seg.start_line != expected_start:
            raise TitleCompileError(
                f"ERROR: Non-contiguous start_line at charset {idx}: expected {expected_start}, got {seg.start_line}."
            )
        if seg.end_line <= seg.start_line or seg.end_line % 8 != 0:
            raise TitleCompileError(
                f"ERROR: Invalid end_line {seg.end_line} for charset {idx} (start_line={seg.start_line})."
            )
        rows = (seg.end_line - seg.start_line) // 8
        expected_glifs = rows * 40
        if len(seg.glifs) != expected_glifs:
            raise TitleCompileError(
                f"ERROR: Charset {idx} covers {rows} rows (expected {expected_glifs} glifs, got {len(seg.glifs)})."
            )
        if any(g < 0 or g > 127 for g in seg.glifs):
            raise TitleCompileError(f"ERROR: Charset {idx} contains glyph index outside 0..127.")

        segments.append(seg)
        expected_start = seg.end_line

    if not segments:
        raise TitleCompileError("ERROR: 'charsets' list is empty.")
    if expected_start != 192:
        raise TitleCompileError(f"ERROR: Expected total height of 192 lines; got {expected_start}.")

    return segments


def format_dta_bytes(data: Sequence[int], per_line: int = 16) -> str:
    """Format byte sequence as MADS `dta` lines."""
    lines: list[str] = []
    for i in range(0, len(data), per_line):
        chunk = data[i : i + per_line]
        hex_vals = ", ".join(f"${b:02X}" for b in chunk)
        lines.append(f"    dta {hex_vals}")
    return "\n".join(lines)


def generate_asm(segments: Sequence[CharsetSegment], gen_dir: Path) -> str:
    """Generate MADS assembly containing RLE tile map, DLI tables, Display List, and charsets."""
    all_glifs: list[int] = []
    for seg in segments:
        all_glifs.extend(seg.glifs)

    compressed = rle_compress(all_glifs)
    if rle_decompress(compressed) != all_glifs:
        raise TitleCompileError("ERROR: RLE round-trip verification failed.")

    # Rows where DLI must fire: the LAST character row of each segment except the final segment
    dli_rows = {(seg.end_line // 8) - 1 for seg in segments[:-1]}
    dli_count = len(segments) - 1

    lines: list[str] = [
        "; ==============================================================================",
        "; GEN/TITLE_SCREEN_DATA.ASM — Auto-generated Title Screen Data (DO NOT EDIT)",
        f"; Raw size: {len(all_glifs)} bytes | RLE compressed size: {len(compressed)} bytes",
        f"; Charsets: {len(segments)} | DLI switches: {dli_count} (at rows: {sorted(dli_rows)})",
        "; ==============================================================================",
        "",
        f"TITLE_CHARSET_COUNT = {len(segments)}",
        f"TITLE_DLI_COUNT     = {dli_count}",
        f"GAME_FONT_GLYPH_OFFSET = {segments[-1].unique_characters}",
        f"GAME_FONT_GLYPH_COUNT  = {segments[-1].filled_glyphs}",
        "",
        "; --- Table of CHBASE high bytes for each DLI zone transition ---",
        "title_dli_chbase",
    ]

    if dli_count > 0:
        chbase_refs = ", ".join(f">title_charset_{seg.index}" for seg in segments[1:])
        lines.append(f"    dta {chbase_refs}")
    else:
        lines.append("    dta >title_charset_0")

    lines.extend(
        [
            "",
            "; --- RLE-compressed 40x24 Antic 4 screen codes (960 bytes uncompressed) ---",
            "title_screen_rle",
            format_dta_bytes(compressed),
            "",
        ]
    )

    # Display list rows helper macro/block (to be placed inside 1KB-aligned DLIST segment)
    dlist_lines: list[str] = [
        "title_dlist",
        "    dta DL_BLANK8, DL_BLANK8, DL_BLANK8",
    ]
    for row in range(24):
        mods: list[str] = ["DL_MODE_4"]
        if row == 0:
            mods.append("DL_LMS")
        if row in dli_rows:
            mods.append("DL_DLI")
        mode_expr = " | ".join(mods)
        if row == 0:
            dlist_lines.append(f"    dta {mode_expr}, a(SCREEN_VRAM)")
        else:
            dlist_lines.append(f"    dta {mode_expr}")
    dlist_lines.append("    dta DL_JVB, a(title_dlist)")

    # Charset binary includes (to be placed at 1KB-aligned $4000+)
    charset_lines: list[str] = []
    for seg in segments:
        fnt_rel_path = (gen_dir / seg.charset_file).as_posix()
        charset_lines.append(f"title_charset_{seg.index}")
        charset_lines.append(f"    ins '{fnt_rel_path}'")

    lines.extend(
        [
            "; --- Display Lists (1 KB aligned at $3400) ---",
            "    org $3400",
            *dlist_lines,
            "",
            "; --- Placeholder Display Lists for GAME and GAME_OVER states ---",
            "game_dlist",
            "    dta DL_BLANK8, DL_BLANK8, DL_BLANK8",
            "    dta DL_MODE_2 | DL_LMS, a(SCREEN_VRAM)",
            "    :23 dta DL_MODE_2",
            "    dta DL_JVB, a(game_dlist)",
            "",
            "; --- Title Screen Character Sets (1 KB aligned at $4000) ---",
            "    org $4000",
            *charset_lines,
            "",
        ]
    )

    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Compile title screen JSON metadata and .fnt files into MADS assembly."
    )
    parser.add_argument(
        "--json-input",
        type=Path,
        required=True,
        help="Path to the input JSON generated by png_to_charset.py.",
    )
    parser.add_argument(
        "--gen-dir",
        type=Path,
        default=Path("gen"),
        help="Directory containing generated .fnt files (default: gen).",
    )
    parser.add_argument(
        "--asm-output",
        type=Path,
        required=True,
        help="Path to the output .asm file (e.g. gen/title_screen_data.asm).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        segments = parse_and_validate_json(args.json_input)
        asm_text = generate_asm(segments, args.gen_dir)
        args.asm_output.parent.mkdir(parents=True, exist_ok=True)
        args.asm_output.write_text(asm_text, encoding="utf-8")
    except TitleCompileError as err:
        sys.stderr.write(f"{err}\n")
        return 1

    print(
        f"Compiled title screen data to {args.asm_output} "
        f"({len(segments)} charsets, {len(segments) - 1} DLI transitions)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

