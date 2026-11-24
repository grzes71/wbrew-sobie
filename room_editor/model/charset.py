"""ANTIC 4 charset model and glyph decoding/rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass

from room_editor.model.palette import PalPaletteTable, Palette

CHARSET_BYTE_SIZE = 1024
GLYPH_COUNT = 128
GLYPH_HEIGHT = 8
GLYPH_WIDTH = 4


@dataclass(frozen=True)
class CharsetData:
    """Raw 1024-byte Atari charset (128 glyphs x 8 bytes)."""

    raw: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.raw, (bytes, bytearray)):
            raise TypeError("CharsetData.raw must be bytes.")
        if len(self.raw) != CHARSET_BYTE_SIZE:
            raise ValueError(
                f"Charset must be exactly {CHARSET_BYTE_SIZE} bytes; got {len(self.raw)}."
            )
        if isinstance(self.raw, bytearray):
            object.__setattr__(self, "raw", bytes(self.raw))

    def glyph_bytes(self, char_code: int) -> bytes:
        """Return the 8 glyph bitmap bytes for character code 0..255."""
        if not (0 <= char_code <= 255):
            raise ValueError(f"Character code must be in 0..255; got {char_code}.")
        base = (char_code & 0x7F) * GLYPH_HEIGHT
        return self.raw[base : base + GLYPH_HEIGHT]

    def decode_glyph_slots(self, char_code: int) -> list[list[int]]:
        """Decode character code 0..255 into an 8x4 grid of palette slot indices.

        Slot mapping per ANTIC 4:
          00 -> 0 (COLBK)
          01 -> 1 (COLPF0)
          10 -> 2 (COLPF1)
          11 -> 3 (COLPF2) for codes 0..127, or 4 (COLPF3) for codes 128..255.
        """
        high_slot = 4 if (char_code & 0x80) else 3
        rows: list[list[int]] = []
        for byte_val in self.glyph_bytes(char_code):
            row: list[int] = []
            for shift in (6, 4, 2, 0):
                pair = (byte_val >> shift) & 0x03
                if pair == 3:
                    row.append(high_slot)
                else:
                    row.append(pair)
            rows.append(row)
        return rows

    def render_glyph_rgb(
        self,
        char_code: int,
        palette: Palette,
        pal_table: PalPaletteTable,
    ) -> list[list[tuple[int, int, int]]]:
        """Render character code 0..255 to an 8x4 grid of (R, G, B) pixels."""
        slots = self.decode_glyph_slots(char_code)
        slot_rgb = [
            pal_table.rgb(palette.color_for_slot(s)) for s in range(5)
        ]
        return [[slot_rgb[s] for s in row] for row in slots]

    def render_glyph_rgba_2x1(
        self,
        char_code: int,
        palette: Palette,
        pal_table: PalPaletteTable,
    ) -> bytes:
        """Render character code 0..255 as 8x8 RGBA8888 bytes (2:1 ANTIC 4 pixel aspect)."""
        slots = self.decode_glyph_slots(char_code)
        slot_rgb = [
            pal_table.rgb(palette.color_for_slot(s)) for s in range(5)
        ]
        out = bytearray(8 * 8 * 4)
        idx = 0
        for row in slots:
            for slot in row:
                r, g, b = slot_rgb[slot]
                # Expand each 2-bit ANTIC 4 pixel horizontally by 2 for 2:1 aspect ratio.
                out[idx : idx + 8] = bytes((r, g, b, 255, r, g, b, 255))
                idx += 8
        return bytes(out)


def decode_glyph_slots(charset: CharsetData, char_code: int) -> list[list[int]]:
    """Module-level convenience wrapper for CharsetData.decode_glyph_slots."""
    return charset.decode_glyph_slots(char_code)


def render_glyph_rgb(
    charset: CharsetData,
    char_code: int,
    palette: Palette,
    pal_table: PalPaletteTable,
) -> list[list[tuple[int, int, int]]]:
    """Module-level convenience wrapper for CharsetData.render_glyph_rgb."""
    return charset.render_glyph_rgb(char_code, palette, pal_table)


def render_glyph_rgba_2x1(
    charset: CharsetData,
    char_code: int,
    palette: Palette,
    pal_table: PalPaletteTable,
) -> bytes:
    """Module-level convenience wrapper for CharsetData.render_glyph_rgba_2x1."""
    return charset.render_glyph_rgba_2x1(char_code, palette, pal_table)
