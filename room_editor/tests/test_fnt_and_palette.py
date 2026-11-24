"""T-1: .fnt loading, ANTIC 4 128-255 COLPF2/COLPF3 swap, 2:1 rendering, and PAL palette."""

from __future__ import annotations

from pathlib import Path

import pytest

from room_editor.io.fnt import FontLoadError, load_fnt
from room_editor.model.charset import CHARSET_BYTE_SIZE, CharsetData
from room_editor.model.palette import Palette, load_default_pal_palette


def _make_sample_fnt_bytes() -> bytes:
    data = bytearray(CHARSET_BYTE_SIZE)
    # Character 1: rows with %00 %01 %10 %11 -> 0x1B = 0b00_01_10_11
    for r in range(8):
        data[1 * 8 + r] = 0x1B
    return bytes(data)


def test_load_valid_fnt(tmp_path: Path) -> None:
    fnt_file = tmp_path / "valid.fnt"
    raw = _make_sample_fnt_bytes()
    fnt_file.write_bytes(raw)

    cs = load_fnt(fnt_file)
    assert isinstance(cs, CharsetData)
    assert cs.raw == raw


@pytest.mark.parametrize("size", [0, 1, 1023, 1025, 2048])
def test_load_fnt_rejects_invalid_sizes(tmp_path: Path, size: int) -> None:
    fnt_file = tmp_path / f"bad_{size}.fnt"
    fnt_file.write_bytes(b"\x00" * size)

    with pytest.raises(FontLoadError):
        load_fnt(fnt_file)


def test_load_fnt_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FontLoadError):
        load_fnt(tmp_path / "does_not_exist.fnt")


def test_antic4_colpf2_colpf3_swap_for_codes_128_to_255() -> None:
    cs = CharsetData(_make_sample_fnt_bytes())
    pal_table = load_default_pal_palette()
    palette = Palette(colbk=0x00, colpf0=0x28, colpf1=0xCA, colpf2=0x94, colpf3=0x0E)

    # Code 1 uses COLPF2 (slot 3) for pixel pair %11
    slots_low = cs.decode_glyph_slots(1)
    assert slots_low[0] == [0, 1, 2, 3]
    rgb_low = cs.render_glyph_rgb(1, palette, pal_table)
    assert rgb_low[0] == [
        pal_table.rgb(0x00),
        pal_table.rgb(0x28),
        pal_table.rgb(0xCA),
        pal_table.rgb(0x94),
    ]

    # Code 129 (1 + 128) uses same shape but swaps COLPF2 -> COLPF3 (slot 4)
    slots_high = cs.decode_glyph_slots(129)
    assert slots_high[0] == [0, 1, 2, 4]
    rgb_high = cs.render_glyph_rgb(129, palette, pal_table)
    assert rgb_high[0] == [
        pal_table.rgb(0x00),
        pal_table.rgb(0x28),
        pal_table.rgb(0xCA),
        pal_table.rgb(0x0E),
    ]


def test_render_2x1_aspect_and_pal_bit0_ignored() -> None:
    pal_table = load_default_pal_palette()
    assert len(pal_table.all_colors()) == 256
    for i in range(128):
        assert pal_table.rgb(2 * i) == pal_table.rgb(2 * i + 1)

    cs = CharsetData(_make_sample_fnt_bytes())
    palette = Palette(colbk=0x00, colpf0=0x32, colpf1=0x86, colpf2=0xA6, colpf3=0x0E)
    rgba = cs.render_glyph_rgba_2x1(1, palette, pal_table)
    # 8 rows x 8 expanded pixels x 4 bytes (RGBA)
    assert len(rgba) == 8 * 8 * 4
    # First row pixel 0 & pixel 1 are both COLBK (doubled horizontally)
    assert tuple(rgba[0:4]) == (*pal_table.rgb(0x00), 255)
    assert tuple(rgba[4:8]) == (*pal_table.rgb(0x00), 255)
    # Pixel 6 & pixel 7 (4th 2-bit pixel) are both COLPF2
    assert tuple(rgba[24:28]) == (*pal_table.rgb(0xA6), 255)
    assert tuple(rgba[28:32]) == (*pal_table.rgb(0xA6), 255)
