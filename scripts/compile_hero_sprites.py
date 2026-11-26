#!/usr/bin/env python3
"""Compile hero Sprite Studio JSON (sprites/project.sprite.json) into MADS SoA assembly."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

REQUIRED_HERO_SETS: dict[int, tuple[str, str]] = {
    1: ("walk-right", "HERO_WALK_RIGHT"),
    2: ("walk-left", "HERO_WALK_LEFT"),
    3: ("squat-left", "HERO_SQUAT_LEFT"),
    4: ("squat-right", "HERO_SQUAT_RIGHT"),
    5: ("jump-right", "HERO_JUMP_RIGHT"),
    6: ("jump-left", "HERO_JUMP_LEFT"),
    7: ("up-down", "HERO_UP_DOWN"),
    8: ("fall", "HERO_FALL"),
}

HERO_SPRITE_WIDTH_CC = 8
HERO_SPRITE_HEIGHT = 18
HERO_DEFAULT_FRAME_TICKS = 4


class HeroCompileError(ValueError):
    """Raised when hero sprite JSON validation fails."""


@dataclass(frozen=True)
class CompiledHeroSet:
    """Validated metadata and frame bytes for a single hero animation set."""

    set_id: int
    name: str
    const_name: str
    frame_duration: int
    frames: tuple[bytes, ...]


@dataclass(frozen=True)
class HeroCompileReport:
    """Build metrics produced by compile_hero_sprites."""

    source_json: Path
    input_sha256: str
    set_count: int
    total_frames: int
    unique_frames: int
    meta_bytes: int
    frame_bytes: int
    total_bytes: int
    sets: tuple[CompiledHeroSet, ...]


def _parse_frame_pixels(raw_frame: Any, set_id: int, frame_idx: int) -> bytes:
    """Convert one 8x18 pixel grid frame into 18 MSB-first bytes."""
    if not isinstance(raw_frame, Mapping):
        raise HeroCompileError(f"Set {set_id} frame {frame_idx} must be a mapping.")
    pixels = raw_frame.get("pixels")
    if not isinstance(pixels, list) or len(pixels) != HERO_SPRITE_HEIGHT:
        got = len(pixels) if isinstance(pixels, list) else type(pixels).__name__
        raise HeroCompileError(
            f"Set {set_id} frame {frame_idx}: expected {HERO_SPRITE_HEIGHT} pixel rows, got {got}."
        )
    out = bytearray(HERO_SPRITE_HEIGHT)
    for row_idx, row in enumerate(pixels):
        if not isinstance(row, str) or len(row) != HERO_SPRITE_WIDTH_CC:
            raise HeroCompileError(
                f"Set {set_id} frame {frame_idx} row {row_idx}: expected {HERO_SPRITE_WIDTH_CC}-char bitstring, got {row!r}."
            )
        byte_val = 0
        for ch in row:
            if ch not in ("0", "1"):
                raise HeroCompileError(
                    f"Set {set_id} frame {frame_idx} row {row_idx}: invalid pixel char {ch!r} (expected '0' or '1')."
                )
            byte_val = (byte_val << 1) | (1 if ch == "1" else 0)
        out[row_idx] = byte_val
    return bytes(out)


def _validate_and_load_hero_sets(raw_doc: Any) -> list[CompiledHeroSet]:
    """Validate Sprite Studio JSON and return sets sorted 1..8."""
    if not isinstance(raw_doc, Mapping):
        raise HeroCompileError("Hero sprite JSON root must be an object.")
    raw_sprites = raw_doc.get("sprites")
    if not isinstance(raw_sprites, list):
        raise HeroCompileError("Hero sprite JSON must contain a 'sprites' list.")

    by_id: dict[int, Mapping[str, Any]] = {}
    for idx, entry in enumerate(raw_sprites):
        if not isinstance(entry, Mapping):
            raise HeroCompileError(f"sprites[{idx}] must be an object.")
        raw_id = entry.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, int):
            raise HeroCompileError(f"sprites[{idx}].id must be an integer, got {raw_id!r}.")
        if raw_id in REQUIRED_HERO_SETS:
            if raw_id in by_id:
                raise HeroCompileError(f"Duplicate hero sprite id {raw_id}.")
            by_id[raw_id] = entry

    missing = [sid for sid in sorted(REQUIRED_HERO_SETS) if sid not in by_id]
    if missing:
        raise HeroCompileError(f"Missing required hero sprite id(s): {missing}.")

    compiled: list[CompiledHeroSet] = []
    for sid in sorted(REQUIRED_HERO_SETS):
        expected_name, const_name = REQUIRED_HERO_SETS[sid]
        entry = by_id[sid]

        desc = entry.get("description")
        if desc != expected_name:
            raise HeroCompileError(
                f"Hero sprite id {sid}: expected description {expected_name!r}, got {desc!r}."
            )

        width = entry.get("width")
        height = entry.get("height")
        if width != HERO_SPRITE_WIDTH_CC or height != HERO_SPRITE_HEIGHT:
            raise HeroCompileError(
                f"Hero sprite id {sid} ('{expected_name}'): expected size "
                f"{HERO_SPRITE_WIDTH_CC}x{HERO_SPRITE_HEIGHT}, got {width!r}x{height!r}."
            )

        anim = entry.get("animation")
        frame_dur = HERO_DEFAULT_FRAME_TICKS
        if anim is not None:
            if not isinstance(anim, Mapping):
                raise HeroCompileError(f"Hero sprite id {sid}: 'animation' must be an object.")
            raw_dur = anim.get("frame_duration")
            if raw_dur is not None:
                if isinstance(raw_dur, bool) or not isinstance(raw_dur, int) or not (1 <= raw_dur <= 255):
                    raise HeroCompileError(
                        f"Hero sprite id {sid}: animation.frame_duration must be 1..255, got {raw_dur!r}."
                    )
                frame_dur = raw_dur

        raw_frames = entry.get("frames")
        if not isinstance(raw_frames, list) or len(raw_frames) == 0:
            raise HeroCompileError(f"Hero sprite id {sid} ('{expected_name}'): must contain at least 1 frame.")
        frames = tuple(_parse_frame_pixels(rf, sid, fi) for fi, rf in enumerate(raw_frames))
        compiled.append(
            CompiledHeroSet(
                set_id=sid,
                name=expected_name,
                const_name=const_name,
                frame_duration=frame_dur,
                frames=frames,
            )
        )
    return compiled


def compile_hero_sprites(input_path: Path, out_dir: Path) -> HeroCompileReport:
    """Validate input JSON and deterministically emit hero_defs.asm & hero_sprites.asm."""
    if not input_path.exists():
        raise HeroCompileError(f"Hero sprite file not found: {input_path}")
    raw_bytes = input_path.read_bytes()
    input_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    try:
        raw_doc = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HeroCompileError(f"Invalid JSON in {input_path}: {exc}") from exc

    sets = _validate_and_load_hero_sets(raw_doc)

    # Deduplicate 18-byte frames deterministically in ascending (set_id 1..8, frame_idx) order
    unique_map: dict[bytes, str] = {}
    unique_blocks: list[tuple[str, bytes]] = []
    frame_refs: list[str] = []
    set_bases: list[int] = []
    total_frames = 0

    for hset in sets:
        set_bases.append(total_frames)
        for frame_bytes in hset.frames:
            lbl = unique_map.get(frame_bytes)
            if lbl is None:
                lbl = f"hero_frame_{len(unique_blocks)}"
                unique_map[frame_bytes] = lbl
                unique_blocks.append((lbl, frame_bytes))
            frame_refs.append(lbl)
            total_frames += 1

    if total_frames > 255:
        raise HeroCompileError(f"Total hero frame pointers ({total_frames}) exceed 255.")

    source_label = input_path.as_posix()
    defs_lines = [
        "; ==============================================================================",
        "; HERO_DEFS.ASM -- GENERATED - DO NOT EDIT",
        f"; Source: {source_label} (sha256: {input_sha256})",
        "; Compiler: scripts/compile_hero_sprites.py",
        "; Equates only (0 emitted bytes).",
        "; ==============================================================================",
        "",
        "; --- Hero Animation Set IDs (1..HERO_SET_COUNT) ---",
    ]
    for hset in sets:
        defs_lines.append(f"{hset.const_name:<24}= {hset.set_id} ; '{hset.name}'")
    defs_lines.extend(
        [
            "",
            "; --- Hero Geometry & Timing Constants ---",
            f"HERO_NUM_SETS           = {len(sets)}",
            f"HERO_SPRITE_HEIGHT      = {HERO_SPRITE_HEIGHT}",
            f"HERO_SPRITE_WIDTH_CC    = {HERO_SPRITE_WIDTH_CC}",
            f"HERO_DEFAULT_FRAME_TICKS = {HERO_DEFAULT_FRAME_TICKS}",
            f"HERO_TOTAL_FRAMES       = {total_frames}",
            f"HERO_UNIQUE_FRAMES      = {len(unique_blocks)}",
            "",
        ]
    )

    sprites_lines = [
        "; ==============================================================================",
        "; HERO_SPRITES.ASM -- GENERATED - DO NOT EDIT",
        f"; Source: {source_label} (sha256: {input_sha256})",
        f"; Sets: {len(sets)} | Total frames: {total_frames} | Unique deduplicated frames: {len(unique_blocks)}",
        "; ==============================================================================",
        "",
        "; --- Per-Set SoA Metadata (1-based indexed by set ID 1..HERO_NUM_SETS) ---",
        "hero_set_count_base",
        f"    dta {', '.join(str(len(s.frames)) for s in sets)}",
        "hero_set_count          = hero_set_count_base - 1",
        "",
        "hero_set_dur_base",
        f"    dta {', '.join(str(s.frame_duration) for s in sets)}",
        "hero_set_dur            = hero_set_dur_base - 1",
        "",
        "hero_set_base_base",
        f"    dta {', '.join(str(b) for b in set_bases)}",
        "hero_set_base           = hero_set_base_base - 1",
        "",
        "; --- Flat Frame Pointer Planes (SoA: low bytes, then high bytes) ---",
        "hero_frame_lo",
    ]
    for hset, base in zip(sets, set_bases):
        refs = frame_refs[base : base + len(hset.frames)]
        sprites_lines.append(
            f"    dta {', '.join(f'<{r}' for r in refs)} ; id {hset.set_id} ({hset.name})"
        )
    sprites_lines.extend(["", "hero_frame_hi"])
    for hset, base in zip(sets, set_bases):
        refs = frame_refs[base : base + len(hset.frames)]
        sprites_lines.append(
            f"    dta {', '.join(f'>{r}' for r in refs)} ; id {hset.set_id} ({hset.name})"
        )

    sprites_lines.extend(["", "; --- Per-Set Frame Pointer Table Aliases (0 bytes) ---"])
    for hset, base in zip(sets, set_bases):
        sprites_lines.append(f"hero_set_{hset.set_id}_lo          = hero_frame_lo + {base}")
        sprites_lines.append(f"hero_set_{hset.set_id}_hi          = hero_frame_hi + {base}")

    sprites_lines.extend(["", "; --- Deduplicated Frame Bitmaps (18 bytes each, MSB-first) ---"])
    for lbl, fbytes in unique_blocks:
        sprites_lines.append(lbl)
        hex_str = ", ".join(f"${b:02X}" for b in fbytes)
        sprites_lines.append(f"    dta {hex_str}")
    sprites_lines.append("")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hero_defs.asm").write_text("\n".join(defs_lines), encoding="utf-8")
    (out_dir / "hero_sprites.asm").write_text("\n".join(sprites_lines), encoding="utf-8")

    meta_bytes = len(sets) * 3 + total_frames * 2
    frame_bytes = len(unique_blocks) * HERO_SPRITE_HEIGHT
    return HeroCompileReport(
        source_json=input_path,
        input_sha256=input_sha256,
        set_count=len(sets),
        total_frames=total_frames,
        unique_frames=len(unique_blocks),
        meta_bytes=meta_bytes,
        frame_bytes=frame_bytes,
        total_bytes=meta_bytes + frame_bytes,
        sets=tuple(sets),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile hero sprite JSON to MADS assembly.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("sprites/project.sprite.json"),
        help="Input Sprite Studio JSON file.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("gen"),
        help="Output directory for generated .asm files.",
    )
    args = parser.parse_args(argv)

    try:
        report = compile_hero_sprites(args.input, args.out_dir)
    except HeroCompileError as err:
        sys.stderr.write(f"ERROR: {err}\n")
        return 1

    print(
        f"Compiled {report.source_json.as_posix()} (sha256: {report.input_sha256[:16]}): "
        f"{report.set_count} sets, {report.total_frames} total frames -> "
        f"{report.unique_frames} unique frames | "
        f"meta={report.meta_bytes} B, frames={report.frame_bytes} B, total={report.total_bytes} B"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
