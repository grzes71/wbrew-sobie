"""Unit tests for scripts/png_to_charset.py (reserved empty glyph at index 0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.png_to_charset import (
    DEFAULT_COLOR_MAP,
    EMPTY_GLYPH,
    CharsetError,
    extract_all_charsets,
    extract_and_build_charset,
    main,
    parse_color_map,
)


def _make_indexed_image(width: int, height: int, fill: int = 0) -> Image.Image:
    img = Image.new("P", (width, height), color=fill)
    palette = [0, 0, 0, 85, 85, 85, 170, 170, 170, 255, 255, 255] + [0] * (252 * 3)
    img.putpalette(palette)
    return img


def _set_tile_solid(img: Image.Image, col: int, row: int, color_idx: int) -> None:
    for dy in range(8):
        for dx in range(4):
            img.putpixel((col * 4 + dx, row * 8 + dy), color_idx)


def _set_tile_pattern(img: Image.Image, col: int, row: int, pattern_id: int) -> None:
    """Write a distinct non-empty 4x8 tile pattern for pattern_id >= 1."""
    assert pattern_id >= 1
    for dy in range(8):
        for dx in range(4):
            bit = (pattern_id >> (dy * 2 + (dx % 2))) & 0x01
            # Ensure at least pixel (0, 0) is non-zero so tile is never EMPTY_GLYPH
            val = 3 if (dx == 0 and dy == 0) else (1 + bit)
            img.putpixel((col * 4 + dx, row * 8 + dy), val)


def test_glyph_zero_reserved_when_no_empty_tiles() -> None:
    # 2x1 tiles, both non-empty (solid color 1 and solid color 2)
    img = _make_indexed_image(8, 8, fill=1)
    _set_tile_solid(img, 1, 0, 2)

    font_data, seg, unique_count = extract_and_build_charset(img)
    assert len(font_data) == 1024
    assert font_data[:8] == EMPTY_GLYPH
    assert unique_count == 3  # slot 0 (reserved empty) + 2 distinct tiles
    assert seg["glifs"] == [1, 2]


def test_non_empty_first_tile_maps_to_1_and_later_empty_tile_reuses_0() -> None:
    # Tile 0: solid color 3 (non-empty); Tile 1: all zeros (empty)
    img = _make_indexed_image(8, 8, fill=0)
    _set_tile_solid(img, 0, 0, 3)

    font_data, seg, unique_count = extract_and_build_charset(img)
    assert font_data[:8] == EMPTY_GLYPH
    assert unique_count == 2
    assert seg["glifs"] == [1, 0]


def test_multi_band_splitting_reserves_glyph_zero_in_every_band(tmp_path: Path) -> None:
    # 64 distinct non-empty tiles per row across 3 rows:
    # Each band starts with reserved glyph 0 (1 + 64 = 65 <= 128, but + 64 = 129 > 128),
    # so each row splits into its own band (3 bands total).
    img2 = _make_indexed_image(64 * 4, 24, fill=0)
    for row in range(3):
        for col in range(64):
            tile_num = row * 64 + col + 1
            for dy in range(8):
                for dx in range(4):
                    if dy == 0 and dx == 0:
                        px = 3
                    elif dy == 1:
                        px = (tile_num >> (dx * 2)) & 0x03
                    else:
                        px = 1
                    img2.putpixel((col * 4 + dx, row * 8 + dy), px)

    files, meta = extract_all_charsets(img2, base_font_path=tmp_path / "band.fnt")
    assert len(files) == 3
    for (_, data), cs_meta in zip(files, meta["charsets"]):
        assert data[:8] == EMPTY_GLYPH
        assert cs_meta["unique_characters"] <= 128
        assert 0 not in cs_meta["glifs"]


def test_fill_font_preserves_reserved_glyph_zero(tmp_path: Path) -> None:
    fill_path = tmp_path / "fill.fnt"
    fill_bytes = bytes((0xAA if i % 8 == 0 else 0x55) for i in range(1024))
    fill_path.write_bytes(fill_bytes)

    img = _make_indexed_image(8, 8, fill=2)  # 1 non-empty tile (at index 1), slot 0 reserved empty
    files, meta = extract_all_charsets(
        img,
        base_font_path=tmp_path / "out.fnt",
        fill_font_path=fill_path,
    )
    assert len(files) == 1
    _, font_data = files[0]
    cs_meta = meta["charsets"][0]
    assert cs_meta["unique_characters"] == 2
    assert cs_meta["filled_glyphs"] == 126
    assert font_data[:8] == EMPTY_GLYPH
    assert font_data[8:16] == b"\xAA" * 8  # 4 pixels of color 2 = 0b10_10_10_10 = 0xAA
    assert font_data[16:] == fill_bytes[: 126 * 8]


def test_parse_color_map_positional_aliases_and_explicit() -> None:
    assert parse_color_map(None) == DEFAULT_COLOR_MAP
    assert parse_color_map("00,10,11,01") == {0: 0, 1: 2, 2: 3, 3: 1}
    assert parse_color_map("bk,pf2,pf0,pf1") == {0: 0, 1: 3, 2: 1, 3: 2}
    assert parse_color_map("COLBK, COLPF1, COLPF3, COLPF0") == {0: 0, 1: 2, 2: 3, 3: 1}
    assert parse_color_map("0=00,5=10,9=11,12=01") == {0: 0, 5: 2, 9: 3, 12: 1}
    assert parse_color_map("4:pf0,8:bk") == {4: 1, 8: 0}


@pytest.mark.parametrize(
    "bad_spec",
    [
        "",
        "   ",
        "00,01,10",  # wrong positional length
        "00,01,10,11,00",
        "00,00,10,11",  # duplicate target in positional
        "0=00,1=00",  # duplicate target in explicit
        "0=00,0=01",  # duplicate source in explicit
        "0=00,10,11,01",  # mixed syntax
        "0,1,2,3",  # ambiguous decimal targets rejected
        "00,01,10,xyz",
        "256=00",  # out-of-range source index
        "abc=00",
        "00,,10,11",
    ],
)
def test_parse_color_map_rejects_invalid_specs(bad_spec: str) -> None:
    with pytest.raises(CharsetError):
        parse_color_map(bad_spec)


def test_color_mapping_remaps_pixels_and_reserves_empty_glyph(tmp_path: Path) -> None:
    # Tile 0: pixels [0, 1, 2, 3] on every row
    # Tile 1: solid PNG index 2 (mapped to 00 -> EMPTY_GLYPH at index 0)
    img = _make_indexed_image(8, 8, fill=2)
    for dy in range(8):
        for dx in range(4):
            img.putpixel((dx, dy), dx)

    cmap = parse_color_map("11,01,00,10")  # 0->11(3), 1->01(1), 2->00(0), 3->10(2)
    font_data, seg, unique_count = extract_and_build_charset(img, color_map=cmap)
    assert font_data[:8] == EMPTY_GLYPH
    # Row pattern for [3, 1, 0, 2] = 0b11_01_00_10 = 0xD2
    assert font_data[8:16] == b"\xD2" * 8
    assert unique_count == 2
    assert seg["glifs"] == [1, 0]

    # Explicit mapping with palette indices > 3 and JSON color_map metadata
    img_high = _make_indexed_image(4, 8, fill=5)
    for dy in range(8):
        img_high.putpixel((0, dy), 0)
        img_high.putpixel((1, dy), 5)
        img_high.putpixel((2, dy), 9)
        img_high.putpixel((3, dy), 12)
    png_path = tmp_path / "high.png"
    img_high.save(png_path)

    fnt_out = tmp_path / "out.fnt"
    json_out = tmp_path / "out.json"
    rc = main(
        [
            str(png_path),
            "--colors",
            "0=00,5=10,9=11,12=01",
            "--font-output",
            str(fnt_out),
            "--json-output",
            str(json_out),
        ]
    )
    assert rc == 0
    meta = json.loads(json_out.read_text(encoding="utf-8"))
    assert meta["color_map"] == {"0": "00", "5": "10", "9": "11", "12": "01"}
    out_bytes = (tmp_path / "out_0.fnt").read_bytes()
    # [00, 10, 11, 01] -> 0b00_10_11_01 = 0x2D
    assert out_bytes[8:16] == b"\x2D" * 8


def test_unmapped_image_palette_index_raises_error() -> None:
    img = _make_indexed_image(4, 8, fill=7)
    with pytest.raises(CharsetError, match="unmapped palette index"):
        extract_and_build_charset(img)

