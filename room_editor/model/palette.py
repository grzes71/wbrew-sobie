"""Atari PAL palette model and RGB lookup table."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_PAL_PALETTE_PATH = Path(__file__).resolve().parent.parent / "data" / "pal_palette.json"


def clamp_atari_color(value: int) -> int:
    """Clamp an Atari color register byte to 0..255."""
    return max(0, min(255, int(value)))


@dataclass
class Palette:
    """ANTIC 4 / GTIA 5-color palette for an object group or project default."""

    colbk: int = 0
    colpf0: int = 40
    colpf1: int = 202
    colpf2: int = 148
    colpf3: int = 15

    def __post_init__(self) -> None:
        self.colbk = clamp_atari_color(self.colbk)
        self.colpf0 = clamp_atari_color(self.colpf0)
        self.colpf1 = clamp_atari_color(self.colpf1)
        self.colpf2 = clamp_atari_color(self.colpf2)
        self.colpf3 = clamp_atari_color(self.colpf3)

    def copy(self) -> Palette:
        """Return an independent copy of this palette."""
        return Palette(
            colbk=self.colbk,
            colpf0=self.colpf0,
            colpf1=self.colpf1,
            colpf2=self.colpf2,
            colpf3=self.colpf3,
        )

    def to_dict(self) -> dict[str, int]:
        """Serialize palette to a plain dictionary with stable key order."""
        return {
            "colbk": int(self.colbk),
            "colpf0": int(self.colpf0),
            "colpf1": int(self.colpf1),
            "colpf2": int(self.colpf2),
            "colpf3": int(self.colpf3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Palette:
        """Construct a Palette from a dictionary, applying defaults for missing keys."""
        if not data:
            return cls()
        return cls(
            colbk=int(data.get("colbk", 0)),
            colpf0=int(data.get("colpf0", 40)),
            colpf1=int(data.get("colpf1", 202)),
            colpf2=int(data.get("colpf2", 148)),
            colpf3=int(data.get("colpf3", 15)),
        )

    def color_for_slot(self, slot: int) -> int:
        """Return the Atari color byte for slot 0..4 (COLBK, COLPF0..COLPF3)."""
        if slot == 0:
            return self.colbk
        if slot == 1:
            return self.colpf0
        if slot == 2:
            return self.colpf1
        if slot == 3:
            return self.colpf2
        if slot == 4:
            return self.colpf3
        raise ValueError(f"Invalid palette slot {slot}; expected 0..4.")


class PalPaletteTable:
    """256-entry Atari PAL RGB color table (luminance bit 0 ignored)."""

    def __init__(self, colors: list[tuple[int, int, int]]) -> None:
        if len(colors) != 256:
            raise ValueError(f"PAL palette must have exactly 256 entries; got {len(colors)}.")
        validated: list[tuple[int, int, int]] = []
        for idx, entry in enumerate(colors):
            if len(entry) != 3:
                raise ValueError(f"Color {idx} must be an RGB 3-tuple; got {entry!r}.")
            r, g, b = int(entry[0]), int(entry[1]), int(entry[2])
            if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
                raise ValueError(f"Color {idx} RGB out of range 0..255: {(r, g, b)}.")
            validated.append((r, g, b))
        self._colors: tuple[tuple[int, int, int], ...] = tuple(validated)

    @classmethod
    def from_json_file(cls, path: Path) -> PalPaletteTable:
        """Load a PAL palette table from a JSON file."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw.get("colors") if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            raise ValueError(f"Invalid PAL palette JSON structure in {path}.")
        colors = [(int(c[0]), int(c[1]), int(c[2])) for c in entries]
        return cls(colors)

    def rgb(self, color_byte: int) -> tuple[int, int, int]:
        """Return the (R, G, B) tuple for an Atari color byte (bit 0 ignored)."""
        masked = int(color_byte) & 0xFE
        return self._colors[masked]

    def all_colors(self) -> tuple[tuple[int, int, int], ...]:
        """Return all 256 RGB entries."""
        return self._colors


@lru_cache(maxsize=1)
def load_default_pal_palette() -> PalPaletteTable:
    """Load and cache the shipped Atari PAL RGB lookup table."""
    return PalPaletteTable.from_json_file(DEFAULT_PAL_PALETTE_PATH)
