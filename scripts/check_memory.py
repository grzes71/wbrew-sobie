#!/usr/bin/env python3
"""Validate Atari 8-bit XEX binary memory map and segment boundaries."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class XexSegment:
    """Single DOS binary load segment."""

    start: int
    end: int
    size: int


def parse_xex_segments(xex_path: Path) -> list[XexSegment]:
    """Parse Atari DOS .xex file into segments."""
    data = xex_path.read_bytes()
    if len(data) < 6 or data[0] != 0xFF or data[1] != 0xFF:
        raise ValueError(f"ERROR: '{xex_path}' is missing valid $FFFF XEX header.")

    idx = 2
    n = len(data)
    segments: list[XexSegment] = []

    while idx < n:
        if idx + 2 <= n and data[idx] == 0xFF and data[idx + 1] == 0xFF:
            idx += 2
            if idx == n:
                break

        if idx + 4 > n:
            raise ValueError(f"ERROR: Truncated segment header at offset {idx}.")

        start = data[idx] | (data[idx + 1] << 8)
        end = data[idx + 2] | (data[idx + 3] << 8)
        idx += 4

        if end < start:
            raise ValueError(f"ERROR: Invalid segment bounds ${start:04X}..${end:04X}.")

        size = end - start + 1
        if idx + size > n:
            raise ValueError(
                f"ERROR: Segment ${start:04X}..${end:04X} extends past EOF."
            )

        idx += size
        segments.append(XexSegment(start=start, end=end, size=size))

    return segments


def validate_memory_map(segments: Sequence[XexSegment]) -> None:
    """Validate OS ROM boundary ($BFFF), ascending order, and overlaps."""
    user_segments = [
        seg for seg in segments if not (0x02E0 <= seg.start <= 0x02E3 and seg.end <= 0x02E3)
    ]

    if not user_segments:
        raise ValueError("ERROR: No user code/data segments found in XEX.")

    prev_end = -1
    for seg in user_segments:
        if seg.start < 0x0400:
            raise ValueError(
                f"ERROR: Segment ${seg.start:04X}..${seg.end:04X} overlaps reserved low memory (< $0400)."
            )
        if seg.end >= 0xC000:
            raise ValueError(
                f"ERROR: Segment ${seg.start:04X}..${seg.end:04X} crosses OS ROM boundary ($C000)."
            )
        if seg.start <= prev_end:
            raise ValueError(
                f"ERROR: Non-ascending or overlapping segment ${seg.start:04X}..${seg.end:04X} "
                f"(previous ended at ${prev_end:04X})."
            )
        prev_end = seg.end


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Validate Atari XEX memory map.")
    parser.add_argument("xex", type=Path, help="Path to the .xex binary.")
    args = parser.parse_args(argv)

    if not args.xex.exists():
        sys.stderr.write(f"ERROR: File not found: {args.xex}\n")
        return 1

    try:
        segments = parse_xex_segments(args.xex)
        validate_memory_map(segments)
    except ValueError as err:
        sys.stderr.write(f"{err}\n")
        return 1

    print(f"Memory Map Check: {args.xex.name} (OK)")
    max_addr = 0
    for seg in segments:
        tag = "RUNAD/INITAD" if 0x02E0 <= seg.start <= 0x02E3 else "USER SEGMENT"
        print(f"  ${seg.start:04X}..${seg.end:04X} ({seg.size:5d} bytes) [{tag}]")
        if tag == "USER SEGMENT" and seg.end > max_addr:
            max_addr = seg.end

    headroom = 0xBFFF - max_addr
    print(f"  Highest user address: ${max_addr:04X} (headroom below $C000: {headroom} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

