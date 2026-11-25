#!/usr/bin/env python3
"""Compile texts/intro.txt into MADS 6502 assembly data for STATE_INTRO."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Sequence

INTRO_COLS = 40
INTRO_LINES = 10
INTRO_VRAM_SIZE = INTRO_COLS * INTRO_LINES
INTRO_SPACE_CODE = 46

# Polish uppercase characters mapped to title_charset_2 glyph indices (fonts/font.fnt offset 46)
POLISH_CHAR_MAP: dict[str, int] = {
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

# Typography normalization for characters absent from standard 7-bit font range
TYPOGRAPHY_CHAR_MAP: dict[str, int] = {
    "—": 59,  # em dash -> '-' (46 + 13)
    "–": 59,  # en dash -> '-' (46 + 13)
}


class IntroCompileError(Exception):
    """Raised when intro.txt validation or encoding fails."""


def encode_intro_char(ch: str) -> int:
    """Encode a single character (converted to uppercase) into a title_charset_2 glyph code."""
    upper = ch.upper()
    if upper in POLISH_CHAR_MAP:
        return POLISH_CHAR_MAP[upper]
    if upper in TYPOGRAPHY_CHAR_MAP:
        return TYPOGRAPHY_CHAR_MAP[upper]
    code_point = ord(upper)
    if 32 <= code_point <= 95:
        return INTRO_SPACE_CODE + (code_point - 32)
    raise IntroCompileError(f"Unsupported character {ch!r} (U+{ord(ch):04X}) in intro text.")


def compile_intro_text(text: str) -> tuple[list[int], list[int], list[int]]:
    """Validate, center, and encode intro text into (start_cols[10], end_cols[10], data[400])."""
    lines = text.splitlines()
    if not lines:
        raise IntroCompileError("Intro text is empty; expected 1..10 lines.")
    if len(lines) > INTRO_LINES:
        raise IntroCompileError(
            f"Intro text has {len(lines)} lines; maximum allowed is {INTRO_LINES}."
        )

    line_starts: list[int] = []
    line_ends: list[int] = []
    screen_bytes: list[int] = []

    for row_idx in range(INTRO_LINES):
        raw_line = lines[row_idx] if row_idx < len(lines) else ""
        if len(raw_line) > INTRO_COLS:
            raise IntroCompileError(
                f"Intro line {row_idx + 1} is {len(raw_line)} chars; exceeds max {INTRO_COLS} columns: {raw_line!r}"
            )

        trimmed = raw_line.strip(" ")
        if not trimmed:
            line_starts.append(0)
            line_ends.append(0)
            screen_bytes.extend([INTRO_SPACE_CODE] * INTRO_COLS)
            continue

        left_pad = (INTRO_COLS - len(trimmed)) // 2
        end_col = left_pad + len(trimmed)
        line_starts.append(left_pad)
        line_ends.append(end_col)

        row_codes: list[int] = [INTRO_SPACE_CODE] * left_pad
        for col_idx, ch in enumerate(trimmed):
            try:
                row_codes.append(encode_intro_char(ch))
            except IntroCompileError as exc:
                raise IntroCompileError(
                    f"Line {row_idx + 1}, col {col_idx + 1}: {exc}"
                ) from exc

        row_codes.extend([INTRO_SPACE_CODE] * (INTRO_COLS - end_col))
        screen_bytes.extend(row_codes)

    assert len(line_starts) == INTRO_LINES
    assert len(line_ends) == INTRO_LINES
    assert len(screen_bytes) == INTRO_VRAM_SIZE
    return line_starts, line_ends, screen_bytes


def format_byte_rows(data: Sequence[int], width: int) -> str:
    """Format byte sequence into `.byte` lines of `width` bytes."""
    out: list[str] = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        out.append("    .byte " + ", ".join(f"${b:02X}" for b in chunk))
    return "\n".join(out)


def generate_intro_asm(source_path: Path, text: str) -> str:
    """Compile text and return deterministic MADS assembly content."""
    line_starts, line_ends, screen_bytes = compile_intro_text(text)
    sha = hashlib.sha256(source_path.read_bytes()).hexdigest()[:16]

    asm_lines = [
        "; ==============================================================================",
        "; GEN/INTRO_TEXT.ASM -- GENERATED - DO NOT EDIT",
        f"; Source: {source_path.as_posix()} (sha256: {sha})",
        "; Compiler: scripts/compile_intro.py",
        "; Charset: title_charset_2 (offset 46=SPACE, Polish uppercase 111..119)",
        "; ==============================================================================",
        "",
        f"INTRO_COLS              = {INTRO_COLS}",
        f"INTRO_LINES             = {INTRO_LINES}",
        f"INTRO_VRAM_SIZE         = {INTRO_VRAM_SIZE}",
        f"INTRO_SPACE_CODE        = {INTRO_SPACE_CODE}",
        "",
        "; Centered first visible column per line (0..39; 0 for blank lines)",
        "intro_line_start",
        format_byte_rows(line_starts, INTRO_LINES),
        "",
        "; Exclusive end column per line (0..40; 0 for blank lines)",
        "intro_line_end",
        format_byte_rows(line_ends, INTRO_LINES),
        "",
        "; 10x40 centered pre-encoded uppercase ANTIC 2 intro text (400 bytes)",
        "intro_screen_data",
        format_byte_rows(screen_bytes, 16),
        "",
    ]
    return "\n".join(asm_lines)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Compile texts/intro.txt into MADS assembly for STATE_INTRO."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("texts/intro.txt"),
        help="Input UTF-8 intro text file (default: texts/intro.txt).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("gen/intro_text.asm"),
        help="Output MADS assembly path (default: gen/intro_text.asm).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if not args.input.exists():
        sys.stderr.write(f"ERROR: Intro text file not found: {args.input}\n")
        return 1

    try:
        text = args.input.read_text(encoding="utf-8-sig")
        asm = generate_intro_asm(args.input, text)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = args.output.with_suffix(".asm.tmp")
        tmp_path.write_text(asm, encoding="utf-8")
        tmp_path.replace(args.output)
    except IntroCompileError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    print(f"Compiled {args.input} -> {args.output} ({INTRO_VRAM_SIZE} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
