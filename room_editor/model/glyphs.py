"""Pure ANTIC 4 glyph, indexed image, stamp region, and glyph table models."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from room_editor.model.palette import PalPaletteTable, Palette

GLYPH_WIDTH = 4
GLYPH_HEIGHT = 8
MAX_GLYPHS_PER_GROUP = 127
MAX_OBJECT_FRAMES = 16
MAX_ANIMATION_SPEED = 255
EMPTY_GLYPH_BYTES = b"\x00" * GLYPH_HEIGHT
DEFAULT_PIXEL_MAPPING: tuple[int, int, int, int] = (0, 1, 2, 3)


def is_valid_pixel_mapping(mapping: Sequence[int]) -> bool:
    """Return True iff mapping is a permutation of (0, 1, 2, 3)."""
    if len(mapping) != 4:
        return False
    for val in mapping:
        if isinstance(val, bool) or not isinstance(val, int):
            return False
    return set(mapping) == {0, 1, 2, 3}


def validate_pixel_mapping(mapping: Sequence[int]) -> tuple[int, int, int, int]:
    """Validate and return a 4-tuple permutation of (0, 1, 2, 3), or raise ValueError."""
    if len(mapping) != 4:
        raise ValueError(
            f"Pixel mapping must contain exactly 4 entries; got {len(mapping)}."
        )
    cleaned: list[int] = []
    for idx, val in enumerate(mapping):
        if isinstance(val, bool) or not isinstance(val, int):
            raise ValueError(
                f"Pixel mapping entry {idx} must be an integer 0..3; got {val!r}."
            )
        cleaned.append(int(val))
    if set(cleaned) != {0, 1, 2, 3}:
        raise ValueError(
            f"Pixel mapping must be a permutation of (0, 1, 2, 3); got {tuple(cleaned)}."
        )
    return (cleaned[0], cleaned[1], cleaned[2], cleaned[3])


@dataclass(frozen=True)
class IndexedImage:
    """Validated indexed image (values 0..3) with dimensions divisible by 4x8."""

    width: int
    height: int
    pixels: bytes
    file_palette: tuple[tuple[int, int, int], ...] = (
        (0, 0, 0),
        (85, 85, 85),
        (170, 170, 170),
        (255, 255, 255),
    )

    def __post_init__(self) -> None:
        w = int(self.width)
        h = int(self.height)
        if w <= 0 or w % GLYPH_WIDTH != 0:
            raise ValueError(
                f"Image width must be a positive multiple of {GLYPH_WIDTH}; got {w}."
            )
        if h <= 0 or h % GLYPH_HEIGHT != 0:
            raise ValueError(
                f"Image height must be a positive multiple of {GLYPH_HEIGHT}; got {h}."
            )
        raw_pixels = bytes(self.pixels) if isinstance(self.pixels, bytearray) else self.pixels
        if not isinstance(raw_pixels, bytes):
            raise TypeError("IndexedImage.pixels must be bytes.")
        if len(raw_pixels) != w * h:
            raise ValueError(
                f"IndexedImage.pixels length {len(raw_pixels)} does not match {w}x{h}."
            )
        if raw_pixels and max(raw_pixels) > 3:
            raise ValueError(
                f"IndexedImage pixels must only use palette indexes 0..3; found {max(raw_pixels)}."
            )
        pal = tuple((int(r), int(g), int(b)) for r, g, b in self.file_palette)
        if len(pal) < 4:
            raise ValueError(
                f"IndexedImage.file_palette must have at least 4 RGB colors; got {len(pal)}."
            )
        object.__setattr__(self, "width", w)
        object.__setattr__(self, "height", h)
        object.__setattr__(self, "pixels", raw_pixels)
        object.__setattr__(self, "file_palette", pal)

    @property
    def glyph_cols(self) -> int:
        """Image width in 4-pixel glyph units."""
        return self.width // GLYPH_WIDTH

    @property
    def glyph_rows(self) -> int:
        """Image height in 8-pixel glyph units."""
        return self.height // GLYPH_HEIGHT

    def extract_glyph_bytes(
        self,
        gx: int,
        gy: int,
        pixel_mapping: Sequence[int],
    ) -> bytes:
        """Extract and encode the 4x8 glyph at (gx, gy) in glyph units into 8 ANTIC 4 bytes."""
        if not (0 <= gx < self.glyph_cols and 0 <= gy < self.glyph_rows):
            raise ValueError(
                f"Glyph coordinate ({gx}, {gy}) out of bounds for {self.glyph_cols}x{self.glyph_rows} image."
            )
        mapping = validate_pixel_mapping(pixel_mapping)
        px0 = gx * GLYPH_WIDTH
        py0 = gy * GLYPH_HEIGHT
        out = bytearray(GLYPH_HEIGHT)
        w = self.width
        pixels = self.pixels
        for row in range(GLYPH_HEIGHT):
            base = (py0 + row) * w + px0
            p0 = mapping[pixels[base]]
            p1 = mapping[pixels[base + 1]]
            p2 = mapping[pixels[base + 2]]
            p3 = mapping[pixels[base + 3]]
            out[row] = (p0 << 6) | (p1 << 4) | (p2 << 2) | p3
        return bytes(out)

    def render_rgba_2x1(
        self,
        palette: Palette,
        pal_table: PalPaletteTable,
        pixel_mapping: Sequence[int],
        *,
        colpf3: bool = False,
        use_file_palette: bool = False,
    ) -> bytes:
        """Render the full image as (width * 2) x height RGBA8888 bytes (2:1 ANTIC 4 aspect)."""
        if use_file_palette:
            idx_rgb = [self.file_palette[i] for i in range(4)]
        else:
            mapping = validate_pixel_mapping(pixel_mapping)
            high_slot = 4 if colpf3 else 3
            slot_rgb = [pal_table.rgb(palette.color_for_slot(s)) for s in range(5)]
            idx_rgb = [
                slot_rgb[high_slot if mapping[i] == 3 else mapping[i]]
                for i in range(4)
            ]

        idx_bytes = [
            bytes((r, g, b, 255, r, g, b, 255)) for (r, g, b) in idx_rgb
        ]
        out = bytearray(self.width * 2 * self.height * 4)
        pos = 0
        for px in self.pixels:
            out[pos : pos + 8] = idx_bytes[px]
            pos += 8
        return bytes(out)


@dataclass(frozen=True)
class StampRegion:
    """Rectangular stamp region in glyph units (1 unit = 4x8 pixels)."""

    x: int
    y: int
    w: int
    h: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", int(self.x))
        object.__setattr__(self, "y", int(self.y))
        object.__setattr__(self, "w", int(self.w))
        object.__setattr__(self, "h", int(self.h))

    @property
    def cell_count(self) -> int:
        """Total number of character cells (w * h)."""
        return self.w * self.h

    def is_within_image(self, image: IndexedImage) -> bool:
        """Return True iff the region has positive dimensions and lies inside image."""
        return (
            self.x >= 0
            and self.y >= 0
            and self.w >= 1
            and self.h >= 1
            and self.x + self.w <= image.glyph_cols
            and self.y + self.h <= image.glyph_rows
        )

    def to_dict(self) -> dict[str, int]:
        """Serialize region to a plain dict with stable key order."""
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, data: Any) -> StampRegion:
        """Construct a StampRegion from a mapping."""
        if not isinstance(data, dict):
            raise ValueError(f"Expected region mapping, got {data!r}.")
        return cls(
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            w=int(data.get("w", 1)),
            h=int(data.get("h", 1)),
        )


def glyph_has_value_11(data: bytes) -> bool:
    """Return True if any pixel pair in the 8 glyph bitmap bytes equals 3 (%11)."""
    if len(data) != GLYPH_HEIGHT:
        raise ValueError(f"Glyph data must be {GLYPH_HEIGHT} bytes; got {len(data)}.")
    for b in data:
        if (
            (b & 0xC0) == 0xC0
            or (b & 0x30) == 0x30
            or (b & 0x0C) == 0x0C
            or (b & 0x03) == 0x03
        ):
            return True
    return False


def decode_glyph_bytes_slots(data: bytes, *, colpf3: bool = False) -> list[list[int]]:
    """Decode 8 ANTIC 4 bitmap bytes into an 8x4 grid of palette slot indices (0..4)."""
    if len(data) != GLYPH_HEIGHT:
        raise ValueError(f"Glyph data must be {GLYPH_HEIGHT} bytes; got {len(data)}.")
    high_slot = 4 if colpf3 else 3
    rows: list[list[int]] = []
    for byte_val in data:
        row: list[int] = []
        for shift in (6, 4, 2, 0):
            pair = (byte_val >> shift) & 0x03
            row.append(high_slot if pair == 3 else pair)
        rows.append(row)
    return rows


def render_glyph_bytes_rgb(
    data: bytes,
    palette: Palette,
    pal_table: PalPaletteTable,
    *,
    colpf3: bool = False,
) -> list[list[tuple[int, int, int]]]:
    """Render 8 glyph bitmap bytes into an 8x4 grid of (R, G, B) pixels."""
    slots = decode_glyph_bytes_slots(data, colpf3=colpf3)
    slot_rgb = [pal_table.rgb(palette.color_for_slot(s)) for s in range(5)]
    return [[slot_rgb[s] for s in row] for row in slots]


def render_glyph_bytes_rgba_2x1(
    data: bytes,
    palette: Palette,
    pal_table: PalPaletteTable,
    *,
    colpf3: bool = False,
) -> bytes:
    """Render 8 glyph bitmap bytes as 8x8 RGBA8888 bytes (2:1 ANTIC 4 pixel aspect)."""
    slots = decode_glyph_bytes_slots(data, colpf3=colpf3)
    slot_rgb = [pal_table.rgb(palette.color_for_slot(s)) for s in range(5)]
    out = bytearray(8 * 8 * 4)
    idx = 0
    for row in slots:
        for slot in row:
            r, g, b = slot_rgb[slot]
            out[idx : idx + 8] = bytes((r, g, b, 255, r, g, b, 255))
            idx += 8
    return bytes(out)


@dataclass(frozen=True)
class GlyphEntry:
    """Single entry in an object group's derived glyph table (codes 1..127)."""

    code: int
    data: bytes
    src: tuple[int, int] | None = None
    object_id: int | None = None
    cells: tuple[tuple[int, int], ...] = ()
    frames: tuple[bytes, ...] = ()

    @property
    def is_dedicated(self) -> bool:
        """Return True iff this entry is a dedicated animation slot owned by an object."""
        return self.object_id is not None

    def __post_init__(self) -> None:
        code = int(self.code)
        if not (1 <= code <= MAX_GLYPHS_PER_GROUP):
            raise ValueError(f"Glyph code must be in 1..{MAX_GLYPHS_PER_GROUP}; got {code}.")
        raw = bytes(self.data) if isinstance(self.data, bytearray) else self.data
        if len(raw) != GLYPH_HEIGHT:
            raise ValueError(f"Glyph data must be {GLYPH_HEIGHT} bytes; got {len(raw)}.")
        if self.object_id is None:
            if raw == EMPTY_GLYPH_BYTES:
                raise ValueError("Static glyph entry cannot store the empty (all-00) glyph.")
            if self.src is None:
                raise ValueError("Static glyph entry requires a 2-element 'src' coordinate.")
            object.__setattr__(self, "src", (int(self.src[0]), int(self.src[1])))
            object.__setattr__(self, "object_id", None)
            object.__setattr__(self, "cells", ())
            object.__setattr__(self, "frames", ())
        else:
            if not self.cells:
                raise ValueError("Dedicated glyph entry requires at least one (cx, cy) cell.")
            norm_cells = tuple((int(cx), int(cy)) for cx, cy in self.cells)
            norm_frames = tuple(bytes(f) for f in self.frames)
            if len(norm_frames) < 2:
                raise ValueError("Dedicated glyph entry requires at least 2 frame byte blocks.")
            for f_idx, f_bytes in enumerate(norm_frames):
                if len(f_bytes) != GLYPH_HEIGHT:
                    raise ValueError(
                        f"Dedicated glyph frame {f_idx} must be {GLYPH_HEIGHT} bytes; got {len(f_bytes)}."
                    )
            if norm_frames[0] != raw:
                raise ValueError("Dedicated glyph entry 'data' must equal frames[0].")
            if len(set(norm_frames)) < 2:
                raise ValueError("Dedicated glyph entry must vary across at least two frames.")
            object.__setattr__(self, "object_id", int(self.object_id))
            object.__setattr__(self, "cells", norm_cells)
            object.__setattr__(self, "frames", norm_frames)
            if self.src is not None:
                object.__setattr__(self, "src", (int(self.src[0]), int(self.src[1])))
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "data", raw)

    @property
    def data_hex(self) -> str:
        """16-character uppercase hex representation of the 8 glyph bytes."""
        return self.data.hex().upper()

    @property
    def frames_hex(self) -> tuple[str, ...]:
        """Tuple of 16-character uppercase hex strings for every frame of a dedicated slot."""
        return tuple(f.hex().upper() for f in self.frames)

    @property
    def has_value_11(self) -> bool:
        """Return True if any pixel uses value 11 (COLPF2/COLPF3)."""
        return glyph_has_value_11(self.data)


@dataclass(frozen=True)
class GlyphTable:
    """Derived unique non-empty glyph table for an object group (codes 1..127)."""

    entries: tuple[GlyphEntry, ...] = ()

    @property
    def used_count(self) -> int:
        return len(self.entries)

    @property
    def free_slots(self) -> int:
        return MAX_GLYPHS_PER_GROUP - len(self.entries)

    def get_entry(self, char_code: int) -> GlyphEntry | None:
        """Return the GlyphEntry for char_code (masking bit 7 for 128..255), or None."""
        base = int(char_code) & 0x7F
        if base == 0:
            return None
        for entry in self.entries:
            if entry.code == base:
                return entry
        return None

    def glyph_bytes(self, char_code: int) -> bytes | None:
        """Return 8 bitmap bytes for char_code (0..255), or None if not in table.

        Code 0 always returns EMPTY_GLYPH_BYTES. Code 128 is invalid/not in table.
        Codes 129..255 share the glyph shape of (code - 128).
        """
        code = int(char_code)
        if not (0 <= code <= 255):
            raise ValueError(f"Character code must be in 0..255; got {code}.")
        if code == 0:
            return EMPTY_GLYPH_BYTES
        if code == 128:
            return None
        entry = self.get_entry(code & 0x7F)
        return entry.data if entry is not None else None

    def decode_glyph_slots(self, char_code: int) -> list[list[int]] | None:
        """Decode char_code 0..255 into 8x4 slot indices, or None if missing from table."""
        data = self.glyph_bytes(char_code)
        if data is None:
            return None
        return decode_glyph_bytes_slots(data, colpf3=bool(char_code & 0x80))

    def render_glyph_rgb(
        self,
        char_code: int,
        palette: Palette,
        pal_table: PalPaletteTable,
    ) -> list[list[tuple[int, int, int]]] | None:
        """Render char_code 0..255 to an 8x4 RGB grid, or None if missing from table."""
        data = self.glyph_bytes(char_code)
        if data is None:
            return None
        return render_glyph_bytes_rgb(
            data, palette, pal_table, colpf3=bool(char_code & 0x80)
        )

    def render_glyph_rgba_2x1(
        self,
        char_code: int,
        palette: Palette,
        pal_table: PalPaletteTable,
    ) -> bytes | None:
        """Render char_code 0..255 as 8x8 RGBA8888 bytes, or None if missing from table."""
        data = self.glyph_bytes(char_code)
        if data is None:
            return None
        return render_glyph_bytes_rgba_2x1(
            data, palette, pal_table, colpf3=bool(char_code & 0x80)
        )


@dataclass
class GroupGlyphAnalysis:
    """Result of deterministically building a group's glyph table and deriving object chars."""

    table: GlyphTable
    total_unique_needed: int = 0
    static_glyph_count: int = 0
    dedicated_slot_count: int = 0
    object_chars: dict[int, list[list[int]]] = field(default_factory=dict)
    object_dedicated_slots: dict[int, list[tuple[int, tuple[tuple[int, int], ...]]]] = field(
        default_factory=dict
    )
    object_cell_stats: dict[int, tuple[int, int, int]] = field(default_factory=dict)
    invalid_region_object_ids: set[int] = field(default_factory=set)
    invalid_frame_size_object_ids: set[int] = field(default_factory=set)
    too_many_frames_object_ids: set[int] = field(default_factory=set)
    empty_object_ids: set[int] = field(default_factory=set)
    overflow_object_ids: set[int] = field(default_factory=set)
    colpf3_no_effect_object_ids: set[int] = field(default_factory=set)
    no_varying_cells_object_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class GlyphBudgetCheck:
    """Result of checking a stamp region or animated object against the 127-glyph group limit."""

    existing_used: int
    new_glyphs: int
    total_used: int
    free_slots: int
    is_all_empty: bool
    region_in_bounds: bool
    cell_count_valid: bool
    ok: bool
    error_message: str = ""
    missing_slots: int = 0


@dataclass(frozen=True)
class MappingChangeCheck:
    """Result of validating a proposed pixel mapping change for an object group."""

    ok: bool
    total_unique: int
    free_slots: int
    overflow_count: int
    empty_object_ids: list[int] = field(default_factory=list)
    overflow_object_ids: list[int] = field(default_factory=list)
    blockable_conflicts: list[tuple[int, str, int, int, int]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
