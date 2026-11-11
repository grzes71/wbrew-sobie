#!/usr/bin/env python3
"""Convert indexed 4-color PNG images into Atari 8-bit charset binaries and JSON tile maps."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from PIL import Image


class CharsetError(Exception):
    """Raised when validation, conversion, or file operations fail."""


def encode_row_to_byte(pixels: Sequence[int]) -> int:
    """Encode a sequence of 4 2-bit color index pixels into a single byte.

    Pixel 0 occupies bits 7-6, pixel 1 bits 5-4, pixel 2 bits 3-2, pixel 3 bits 1-0.
    """
    if len(pixels) != 4:
        raise ValueError(f"Expected exactly 4 pixels per row; got {len(pixels)}.")
    p0, p1, p2, p3 = pixels
    return (
        ((p0 & 0x03) << 6)
        | ((p1 & 0x03) << 4)
        | ((p2 & 0x03) << 2)
        | (p3 & 0x03)
    )


def encode_tile_to_bytes(tile_rows: Sequence[Sequence[int]]) -> bytes:
    """Encode an 8-row by 4-pixel tile into 8 bytes."""
    if len(tile_rows) != 8:
        raise ValueError(f"Expected exactly 8 rows in tile; got {len(tile_rows)}.")
    return bytes(encode_row_to_byte(row) for row in tile_rows)


def validate_image(img: Image.Image, start_line: int = 0) -> None:
    """Validate that the image and start_line satisfy Atari 4-color charset requirements."""
    if img.mode != "P":
        raise CharsetError("ERROR: Input image must be an indexed PNG (palette mode P).")

    width, height = img.size
    if width <= 0 or height <= 0:
        raise CharsetError(f"ERROR: Image dimensions must be positive; got {width}x{height}.")
    if width % 4 != 0:
        raise CharsetError(f"ERROR: Image width must be divisible by 4; got {width}.")
    if height % 8 != 0:
        raise CharsetError(f"ERROR: Image height must be divisible by 8; got {height}.")

    if start_line < 0 or start_line >= height:
        raise CharsetError(
            f"ERROR: start_line ({start_line}) must be within image height range [0, {height - 1}]."
        )
    if start_line % 8 != 0:
        raise CharsetError(
            f"ERROR: start_line must be divisible by 8; got {start_line}."
        )

    if hasattr(img, "get_flattened_data"):
        used_colors = set(img.get_flattened_data())
    else:
        used_colors = set(img.getdata())
    if len(used_colors) > 4:
        raise CharsetError(f"ERROR: Expected at most 4 used colors; found {len(used_colors)}.")
    if not used_colors.issubset({0, 1, 2, 3}):
        raise CharsetError("ERROR: Used palette indices must be within 0, 1, 2, and 3.")


def build_charset_filename(base_font_path: Path, index: int) -> Path:
    """Build indexed .fnt path from base font path (e.g. charset.fnt -> charset_0.fnt)."""
    stem = base_font_path.stem or "charset"
    suffix = base_font_path.suffix or ".fnt"
    return base_font_path.with_name(f"{stem}_{index}{suffix}")


def extract_and_build_charset(
    img: Image.Image, start_line: int = 0
) -> tuple[bytes, dict, int]:
    """Extract tiles from the image starting at start_line up to 128 unique glyphs.

    Processes full character rows (8 pixel lines per row) until the image ends
    or adding the next row would exceed 128 unique characters.
    """
    validate_image(img, start_line)

    width, height = img.size
    cols = width // 4
    total_rows = height // 8
    start_row = start_line // 8

    if hasattr(img, "get_flattened_data"):
        pixel_data = list(img.get_flattened_data())
    else:
        pixel_data = list(img.getdata())

    unique_patterns: dict[bytes, int] = {}
    glifs: list[int] = []
    end_line = start_line

    for row_idx in range(start_row, total_rows):
        y_start = row_idx * 8
        row_patterns: dict[bytes, int] = dict(unique_patterns)
        row_glifs: list[int] = []
        exceeded_in_row = False

        for col_idx in range(cols):
            x_start = col_idx * 4

            tile_rows: list[list[int]] = []
            for r in range(8):
                y = y_start + r
                row_offset = y * width + x_start
                tile_rows.append(pixel_data[row_offset : row_offset + 4])

            tile_bytes = encode_tile_to_bytes(tile_rows)

            if tile_bytes not in row_patterns:
                if len(row_patterns) >= 128:
                    exceeded_in_row = True
                    break
                row_patterns[tile_bytes] = len(row_patterns)

            row_glifs.append(row_patterns[tile_bytes])

        if exceeded_in_row:
            break

        unique_patterns = row_patterns
        glifs.extend(row_glifs)
        end_line = y_start + 8

    if end_line == start_line:
        raise CharsetError(
            "ERROR: Cannot fit even a single character row within the 128-glyph limit."
        )

    # Build 1024-byte font binary (128 glyphs * 8 bytes)
    font_data = bytearray(1024)
    for pattern, idx in unique_patterns.items():
        font_data[idx * 8 : (idx + 1) * 8] = pattern

    if len(font_data) != 1024:
        raise CharsetError(
            f"ERROR: Charset font size is {len(font_data)} bytes; expected 1024."
        )

    unique_count = len(unique_patterns)
    segment_data = {
        "start_line": start_line,
        "end_line": end_line,
        "unique_characters": unique_count,
        "glifs": glifs,
    }

    return bytes(font_data), segment_data, unique_count


def extract_all_charsets(
    img: Image.Image,
    base_font_path: Path = Path("charset.fnt"),
    start_line: int = 0,
    fill_font_path: Path | None = None,
) -> tuple[list[tuple[Path, bytes]], dict]:
    """Split image from start_line into non-overlapping row-aligned charsets (max 128 glyphs each)."""
    validate_image(img, start_line)

    _, height = img.size
    current_line = start_line
    charset_files: list[tuple[Path, bytes]] = []
    charsets_metadata: list[dict] = []
    charset_idx = 0

    fill_font_data: bytes | None = None
    if fill_font_path is not None:
        if not fill_font_path.exists():
            raise CharsetError(f"ERROR: Fill font file does not exist: {fill_font_path}")
        fill_font_data = fill_font_path.read_bytes()
        if len(fill_font_data) < 1024:
            raise CharsetError(
                f"ERROR: Fill font must be at least 1024 bytes; got {len(fill_font_data)}."
            )

    while current_line < height:
        font_data, segment_data, unique_count = extract_and_build_charset(
            img, start_line=current_line
        )

        # If this is the final segment and fill_font was provided, fill free glyph slots
        next_line = segment_data["end_line"]
        is_last = next_line >= height
        filled_count = 0
        if is_last and fill_font_data is not None:
            font_bytearray = bytearray(font_data)
            free_slots = 128 - unique_count
            if free_slots > 0:
                font_bytearray[unique_count * 8 : 1024] = fill_font_data[: free_slots * 8]
                font_data = bytes(font_bytearray)
                filled_count = free_slots

        fnt_path = build_charset_filename(base_font_path, charset_idx)
        charset_files.append((fnt_path, font_data))

        meta = {
            "index": charset_idx,
            "charset_file": fnt_path.name,
            "start_line": segment_data["start_line"],
            "end_line": segment_data["end_line"],
            "unique_characters": unique_count,
            "glifs": segment_data["glifs"],
        }
        if filled_count > 0:
            meta["filled_glyphs"] = filled_count
            meta["fill_font"] = fill_font_path.name if fill_font_path else ""

        charsets_metadata.append(meta)

        current_line = next_line
        charset_idx += 1

    json_data = {
        "charsets": charsets_metadata,
    }
    return charset_files, json_data


def save_outputs(
    charset_files: Sequence[tuple[Path, bytes]],
    json_data: dict,
    json_path: Path,
    input_path: Path,
) -> None:
    """Safely write all charset .fnt files and the JSON metadata file."""
    try:
        json_resolved = json_path.resolve()
        input_resolved = input_path.resolve()
        font_resolved_list = [fp.resolve() for fp, _ in charset_files]
    except Exception as exc:
        raise CharsetError(f"ERROR: Cannot resolve file paths: {exc}") from exc

    if json_resolved == input_resolved or input_resolved in font_resolved_list:
        raise CharsetError("ERROR: Output file cannot overwrite the input image.")

    if json_resolved in font_resolved_list:
        raise CharsetError(
            "ERROR: Font output and JSON output cannot point to the same file."
        )

    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        for fp, _ in charset_files:
            fp.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CharsetError(f"ERROR: Cannot create output directories: {exc}") from exc

    pid = os.getpid()
    tmp_fonts: list[tuple[Path, Path, bytes]] = [
        (fp.with_name(f"{fp.name}.tmp_{pid}"), fp, data)
        for fp, data in charset_files
    ]
    tmp_json = json_path.with_name(f"{json_path.name}.tmp_{pid}")
    replaced_files: list[Path] = []

    try:
        for tmp_fp, _, data in tmp_fonts:
            tmp_fp.write_bytes(data)
            if tmp_fp.stat().st_size != 1024:
                raise CharsetError(
                    f"ERROR: Generated font size is {tmp_fp.stat().st_size} bytes; expected 1024."
                )

        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
            f.write("\n")

        for tmp_fp, final_fp, _ in tmp_fonts:
            tmp_fp.replace(final_fp)
            replaced_files.append(final_fp)

        tmp_json.replace(json_path)
    except Exception as exc:
        for tmp_fp, _, _ in tmp_fonts:
            if tmp_fp.exists():
                try:
                    tmp_fp.unlink()
                except OSError:
                    pass
        if tmp_json.exists():
            try:
                tmp_json.unlink()
            except OSError:
                pass
        for final_fp in replaced_files:
            if final_fp.exists():
                try:
                    final_fp.unlink()
                except OSError:
                    pass
        raise CharsetError(f"ERROR: Failed to write output files: {exc}") from exc


def process_image_to_charset(
    input_path: Path,
    font_path: Path,
    json_path: Path,
    start_line: int = 0,
    fill_font_path: Path | None = None,
) -> tuple[int, int, list[dict]]:
    """Execute complete workflow from loading image to saving all charset outputs and JSON."""
    if not input_path.exists():
        raise CharsetError(f"ERROR: Input file does not exist: {input_path}")
    if not input_path.is_file():
        raise CharsetError(f"ERROR: Input path is not a file: {input_path}")

    try:
        with Image.open(input_path) as img:
            charset_files, json_data = extract_all_charsets(
                img,
                base_font_path=font_path,
                start_line=start_line,
                fill_font_path=fill_font_path,
            )
            width, height = img.size
    except (OSError, Image.DecompressionBombError) as exc:
        raise CharsetError(f"ERROR: Failed to read image '{input_path}': {exc}") from exc

    save_outputs(charset_files, json_data, json_path, input_path)

    return width, height, json_data["charsets"]


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Convert an indexed 4-color PNG into Atari 8-bit Antic 4/5 charsets (.fnt) and a JSON metadata file."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the input indexed 4-color PNG image.",
    )
    parser.add_argument(
        "--start-line",
        "--start_line",
        dest="start_line",
        type=int,
        default=0,
        help="Starting graphic line (pixel Y, multiple of 8, default: 0).",
    )
    parser.add_argument(
        "--font-output",
        type=Path,
        default=Path("charset.fnt"),
        help="Base path for output .fnt files (generates <stem>_0.fnt, <stem>_1.fnt, ...; default: charset.fnt).",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=Path("charset.json"),
        help="Path to the output JSON metadata file (default: charset.json).",
    )
    parser.add_argument(
        "--fill-font",
        type=Path,
        default=None,
        help="Optional path to a .fnt file whose first glyphs will fill remaining free slots in the last charset.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        width, height, charsets = process_image_to_charset(
            args.input,
            args.font_output,
            args.json_output,
            start_line=args.start_line,
            fill_font_path=args.fill_font,
        )
    except CharsetError as err:
        sys.stderr.write(f"{err}\n")
        return 1

    lines = [
        f"Input image: {args.input.name}",
        f"Image size: {width}x{height}",
        f"Charsets generated: {len(charsets)}",
    ]
    for cs in charsets:
        filled_info = (
            f", filled={cs['filled_glyphs']} from {cs['fill_font']}"
            if "filled_glyphs" in cs
            else ""
        )
        lines.append(
            f"  [{cs['index']}] {cs['charset_file']}: lines {cs['start_line']}..{cs['end_line']}, "
            f"unique={cs['unique_characters']}/128, tiles={len(cs['glifs'])}{filled_info}"
        )
    lines.append(f"JSON mapping: {args.json_output}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
