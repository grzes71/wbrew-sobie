"""Tests for indexed PNG loading, pixel mapping, glyph splitting, 127 limit, COLPF3, and PAL palette."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from room_editor.io.png import PngLoadError, PngMissingError, load_png
from room_editor.model.commands import DeleteObjectCommand
from room_editor.model.glyphs import (
    EMPTY_GLYPH_BYTES,
    MAX_GLYPHS_PER_GROUP,
    IndexedImage,
    StampRegion,
    is_valid_pixel_mapping,
    render_glyph_bytes_rgb,
    render_glyph_bytes_rgba_2x1,
    validate_pixel_mapping,
)
from room_editor.model.palette import NamedPalette, Palette, load_default_pal_palette
from room_editor.model.project import (
    ANTIC4_PIXEL_ASPECT_X,
    ROOM_DISPLAY_HEIGHT,
    ROOM_DISPLAY_WIDTH,
    ROOM_HEIGHT,
    ROOM_PIXEL_HEIGHT,
    ROOM_PIXEL_WIDTH,
    ROOM_WIDTH,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
)


def _write_indexed_png(
    path: Path,
    width: int,
    height: int,
    pixels: list[int],
    palette_rgb: list[tuple[int, int, int]] | None = None,
) -> Path:
    img = Image.new("P", (width, height))
    pal = palette_rgb or [
        (0, 0, 0),
        (200, 100, 50),
        (50, 200, 100),
        (50, 100, 220),
    ]
    flat_pal: list[int] = []
    for r, g, b in pal:
        flat_pal.extend((r, g, b))
    flat_pal.extend([0] * (768 - len(flat_pal)))
    img.putpalette(flat_pal)
    img.putdata(pixels)
    img.save(path, format="PNG")
    return path


def _make_tile_pattern_image(cols: int, rows: int, tile_fn) -> IndexedImage:
    w = cols * 4
    h = rows * 8
    buf = bytearray(w * h)
    for gy in range(rows):
        for gx in range(cols):
            tile = tile_fn(gx, gy)  # 8 rows of 4 ints
            for py in range(8):
                for px in range(4):
                    buf[(gy * 8 + py) * w + (gx * 4 + px)] = tile[py][px]
    return IndexedImage(width=w, height=h, pixels=bytes(buf))


def test_png_loading_valid_and_rejections(tmp_path: Path) -> None:
    # Valid 8x16 (2x2 glyphs) indexed PNG with indexes 0..3
    pixels = [(x + y) % 4 for y in range(16) for x in range(8)]
    valid_path = _write_indexed_png(tmp_path / "valid.png", 8, 16, pixels)
    loaded = load_png(valid_path)
    assert loaded.width == 8
    assert loaded.height == 16
    assert loaded.glyph_cols == 2
    assert loaded.glyph_rows == 2

    # Missing file
    with pytest.raises(PngMissingError):
        load_png(tmp_path / "missing.png")

    # Non-indexed (RGB) PNG rejected
    rgb_path = tmp_path / "rgb.png"
    Image.new("RGB", (8, 16), (10, 20, 30)).save(rgb_path, format="PNG")
    with pytest.raises(PngLoadError, match="indexed"):
        load_png(rgb_path)

    # Palette index > 3 rejected
    bad_idx_path = _write_indexed_png(
        tmp_path / "bad_idx.png",
        4,
        8,
        [0] * 31 + [4],
        palette_rgb=[(i * 40, 0, 0) for i in range(5)],
    )
    with pytest.raises(PngLoadError, match="0..3"):
        load_png(bad_idx_path)

    # Bad width (not multiple of 4)
    bad_w_path = _write_indexed_png(tmp_path / "bad_w.png", 6, 8, [0] * 48)
    with pytest.raises(PngLoadError, match="4x8"):
        load_png(bad_w_path)

    # Bad height (not multiple of 8)
    bad_h_path = _write_indexed_png(tmp_path / "bad_h.png", 4, 12, [0] * 48)
    with pytest.raises(PngLoadError, match="4x8"):
        load_png(bad_h_path)


def test_pixel_mapping_permutation_empty_semantics_and_rejection() -> None:
    # Single 4x8 tile: row 0 = [0, 1, 2, 3], rows 1..7 = [0, 0, 0, 0]
    def tile_fn(gx: int, gy: int) -> list[list[int]]:
        if gx == 0:
            return [[0, 1, 2, 3]] + [[0, 0, 0, 0] for _ in range(7)]
        return [[2, 2, 2, 2] for _ in range(8)]

    img = _make_tile_pattern_image(2, 1, tile_fn)

    # Identity mapping (0->00, 1->01, 2->10, 3->11)
    assert img.extract_glyph_bytes(0, 0, (0, 1, 2, 3)) == bytes([0b00_01_10_11] + [0] * 7)
    # Index 2 tile is NOT empty under identity
    assert img.extract_glyph_bytes(1, 0, (0, 1, 2, 3)) != EMPTY_GLYPH_BYTES

    # Non-trivial permutation: 0->11(3), 1->01(1), 2->00(0), 3->10(2)
    perm = (3, 1, 0, 2)
    assert img.extract_glyph_bytes(0, 0, perm) == bytes(
        [0b11_01_00_10] + [0xFF] * 7
    )
    # Now index 2 maps to 00, so tile (1, 0) becomes EMPTY (code 0)!
    assert img.extract_glyph_bytes(1, 0, perm) == EMPTY_GLYPH_BYTES

    # Invalid mappings rejected
    assert is_valid_pixel_mapping((0, 1, 2, 3))
    assert not is_valid_pixel_mapping((0, 0, 1, 2))
    assert not is_valid_pixel_mapping((0, 1, 2))
    assert not is_valid_pixel_mapping((0, 1, 2, 4))
    assert not is_valid_pixel_mapping((True, 1, 2, 3))
    with pytest.raises(ValueError):
        validate_pixel_mapping((0, 0, 2, 3))


def test_glyph_splitting_dedup_mirror_and_empty_cells() -> None:
    # 4 glyphs side-by-side:
    # gx=0: [1, 0, 0, 0] (identical to gx=1)
    # gx=1: [1, 0, 0, 0] (shared with gx=0 -> deduplicated)
    # gx=2: [0, 0, 0, 1] (horizontally mirrored -> MUST be distinct!)
    # gx=3: [0, 0, 0, 0] (pure 00 -> code 0, not counted)
    def tile_fn(gx: int, gy: int) -> list[list[int]]:
        if gx in (0, 1):
            return [[1, 0, 0, 0] for _ in range(8)]
        if gx == 2:
            return [[0, 0, 0, 1] for _ in range(8)]
        return [[0, 0, 0, 0] for _ in range(8)]

    img = _make_tile_pattern_image(4, 1, tile_fn)
    proj = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[
            GameObject(id=1, name="strip", group="g", region=StampRegion(0, 0, 4, 1)),
        ],
    )
    grp = proj.get_group("g")
    assert grp is not None
    assert grp.glyph_table.used_count == 2  # gx=0/1 share code 1; gx=2 is code 2; gx=3 is 0
    obj = proj.get_object(1)
    assert obj is not None
    assert obj.chars == [[1, 1, 2, 0]]


def test_deterministic_glyph_table_and_code_shift_after_delete() -> None:
    # 3 distinct non-empty glyphs at gx=0, 1, 2 + shared at gx=3 (same as gx=0)
    def tile_fn(gx: int, gy: int) -> list[list[int]]:
        val = (gx % 3) + 1
        return [[val, 0, 0, 0] for _ in range(8)]

    img = _make_tile_pattern_image(4, 1, tile_fn)
    # Insert objects in out-of-ID order to verify ascending ID determinism
    proj = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[
            GameObject(id=10, name="ten", group="g", region=StampRegion(1, 0, 2, 1)),
            GameObject(id=2, name="two", group="g", region=StampRegion(0, 0, 1, 1)),
            GameObject(id=20, name="twenty", group="g", region=StampRegion(3, 0, 1, 1)),
        ],
    )
    grp = proj.get_group("g")
    assert grp is not None
    assert [e.code for e in grp.glyph_table.entries] == [1, 2, 3]
    assert [e.src for e in grp.glyph_table.entries] == [(0, 0), (1, 0), (2, 0)]
    assert proj.get_object(2).chars == [[1]]
    assert proj.get_object(10).chars == [[2, 3]]
    # Shared glyph is NOT double counted and gets code 1
    assert proj.get_object(20).chars == [[1]]
    assert grp.glyph_table.used_count == 3

    # Deleting object 2 drops glyph (0,0)? Wait: object 20 still uses it, so still 3;
    # deleting object 10 frees glyphs (1,0) and (2,0)!
    cmd = DeleteObjectCommand(proj, 10)
    cmd.execute()
    assert grp.glyph_table.used_count == 1
    assert [e.src for e in grp.glyph_table.entries] == [(0, 0)]

    # Undo restores object 10 and codes 1, 2, 3
    cmd.undo()
    assert grp.glyph_table.used_count == 3
    assert proj.get_object(10).chars == [[2, 3]]

    # Now delete object 2 AND 20? Better: if we delete object 2 while object 20 shares (0,0),
    # (0,0) stays, whereas if we had an object using only unique glyph at id=1, deleting id=1 shifts id=10 down:
    proj2 = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[
            GameObject(id=1, name="first", group="g", region=StampRegion(0, 0, 1, 1)),
            GameObject(id=2, name="second", group="g", region=StampRegion(1, 0, 2, 1)),
        ],
    )
    assert proj2.get_object(2).chars == [[2, 3]]
    DeleteObjectCommand(proj2, 1).execute()
    assert proj2.get_object(2).chars == [[1, 2]]
    assert [e.code for e in proj2.get_group("g").glyph_table.entries] == [1, 2]


def _make_unique_glyphs_image(num_glyphs: int) -> IndexedImage:
    """Build a single-row image where each tile gx has a unique non-zero bitmap."""
    def tile_fn(gx: int, gy: int) -> list[list[int]]:
        n = gx + 1  # >= 1 so never all-zero
        row0 = [(n >> 6) & 3, (n >> 4) & 3, (n >> 2) & 3, n & 3]
        row1 = [((n >> 8) & 3), 1, 2, 3]
        return [row0, row1] + [[0, 0, 0, 0] for _ in range(6)]

    return _make_tile_pattern_image(num_glyphs, 1, tile_fn)


def test_127_glyph_limit_and_mapping_change_rejection() -> None:
    # Image with 130 unique non-empty glyphs
    img = _make_unique_glyphs_image(130)
    proj = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[
            GameObject(id=1, name="bulk", group="g", region=StampRegion(0, 0, 125, 1)),
        ],
    )
    assert proj.get_group("g").glyph_table.used_count == 125
    assert proj.get_group("g").glyph_table.free_slots == 2

    # Adding 2 more (total 127) succeeds
    check_ok = proj.check_region_glyph_budget("g", StampRegion(125, 0, 2, 1))
    assert check_ok.ok
    assert check_ok.new_glyphs == 2
    assert check_ok.total_used == 127
    assert check_ok.free_slots == 0

    # Adding 3 more (total 128) is rejected with counts in message
    check_fail = proj.check_region_glyph_budget("g", StampRegion(125, 0, 3, 1))
    assert not check_fail.ok
    assert check_fail.new_glyphs == 3
    assert check_fail.free_slots == 2
    assert "3 new" in check_fail.error_message
    assert "2 free" in check_fail.error_message

    # Shared glyphs with object 1 do not double-count
    check_shared = proj.check_region_glyph_budget("g", StampRegion(0, 0, 5, 1))
    assert check_shared.ok
    assert check_shared.new_glyphs == 0

    # Mapping change that would exceed 127 limit (or turn an object empty) is rejected
    # Build image where tile 0 is all index 0 (empty under identity, non-empty under swap)
    # and tiles 1..127 are unique non-empty under BOTH mappings:
    def mixed_fn(gx: int, gy: int) -> list[list[int]]:
        if gx == 0:
            return [[0, 0, 0, 0] for _ in range(8)]  # all index 0
        # Uses index 1..3 in bit patterns, never index 0 in row1 -> non-empty under BOTH!
        n = gx
        row0 = [1 + ((n >> 4) & 1), 1 + ((n >> 2) & 1), 1 + (n & 1), 3]
        row1 = [1 + ((n >> 6) & 1), 2, 3, 1 + ((n >> 5) & 1)]
        row2 = [1 + ((n >> 7) & 1), 1 + ((n >> 3) & 1), 1 + ((n >> 1) & 1), 2]
        return [row0, row1, row2] + [[1, 1, 1, 1] for _ in range(5)]

    img2 = _make_tile_pattern_image(128, 1, mixed_fn)
    proj2 = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img2)],
        objects=[
            # Covers gx=0 (empty under identity -> doesn't count!) + gx=1..127 -> 127 unique
            GameObject(id=1, name="all", group="g", region=StampRegion(0, 0, 128, 1)),
        ],
    )
    assert proj2.get_group("g").glyph_table.used_count == MAX_GLYPHS_PER_GROUP

    # Swapping 0<->1 makes gx=0 become non-empty -> 128 unique glyphs -> MUST reject!
    res = proj2.check_mapping_change("g", (1, 0, 2, 3))
    assert not res.ok
    assert res.total_unique == 128
    assert res.overflow_count == 1
    assert 1 in res.overflow_object_ids


def test_colpf3_codes_empty_preservation_and_rendering() -> None:
    # Glyph 0: all 00 (empty), Glyph 1: [0, 1, 2, 3]
    def tile_fn(gx: int, gy: int) -> list[list[int]]:
        if gx == 0:
            return [[0, 0, 0, 0] for _ in range(8)]
        return [[0, 1, 2, 3]] + [[0, 0, 0, 0] for _ in range(7)]

    img = _make_tile_pattern_image(2, 1, tile_fn)
    pal_table = load_default_pal_palette()
    palette = Palette(colbk=0x00, colpf0=0x28, colpf1=0xCA, colpf2=0x94, colpf3=0x0E)

    proj = Project(
        object_groups=[
            ObjectGroup(name="g", image_path="g.png", image=img, palettes=[NamedPalette(colors=palette)]),
            ObjectGroup(name="alt", image_path="alt.png", image=img, palettes=[NamedPalette(colors=palette)]),
        ],
        objects=[
            GameObject(id=1, name="normal", group="g", colpf3=False, region=StampRegion(0, 0, 2, 1)),
            GameObject(id=2, name="pf3", group="g", colpf3=True, region=StampRegion(0, 0, 2, 1)),
        ],
    )
    grp = proj.get_group("g")
    assert grp is not None
    # COLPF3 does NOT create new glyphs or change used count (still 1!)
    assert grp.glyph_table.used_count == 1
    assert proj.get_object(1).chars == [[0, 1]]
    # Empty cell stays 0 (NEVER 128), non-empty cell gets code + 128 = 129!
    assert proj.get_object(2).chars == [[0, 129]]

    # Rendering code 1 uses COLPF2; code 129 uses COLPF3
    rgb_normal = grp.glyph_table.render_glyph_rgb(1, palette, pal_table)
    rgb_pf3 = grp.glyph_table.render_glyph_rgb(129, palette, pal_table)
    assert rgb_normal is not None and rgb_pf3 is not None
    assert rgb_normal[0] == [
        pal_table.rgb(0x00),
        pal_table.rgb(0x28),
        pal_table.rgb(0xCA),
        pal_table.rgb(0x94),
    ]
    assert rgb_pf3[0] == [
        pal_table.rgb(0x00),
        pal_table.rgb(0x28),
        pal_table.rgb(0xCA),
        pal_table.rgb(0x0E),
    ]

    # A code absent from a group's glyph table returns None (drawn as empty in cross-group rows)
    assert grp.glyph_table.glyph_bytes(5) is None
    assert grp.glyph_table.glyph_bytes(133) is None
    assert grp.glyph_table.glyph_bytes(128) is None
    assert grp.glyph_table.glyph_bytes(0) == EMPTY_GLYPH_BYTES


def test_region_validation_and_pal_2x1_aspect() -> None:
    img = _make_tile_pattern_image(
        20,
        20,
        lambda gx, gy: [[1, 2, 3, 0] for _ in range(8)],
    )
    proj = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[
            GameObject(id=1, name="ok_2x1", group="g", region=StampRegion(0, 0, 2, 1)),
            GameObject(id=2, name="ok_1x2", group="g", region=StampRegion(2, 0, 1, 2)),
        ],
    )
    assert proj.object_placement_error(proj.get_object(1)) == ""
    assert proj.object_placement_error(proj.get_object(2)) == ""

    # 15 * 17 = 255 cells is allowed
    assert proj.check_region_glyph_budget("g", StampRegion(0, 0, 15, 17)).ok
    # 16 * 16 = 256 cells rejected
    bad_size = proj.check_region_glyph_budget("g", StampRegion(0, 0, 16, 16))
    assert not bad_size.ok
    assert not bad_size.cell_count_valid

    # Out of image rejected
    oob = proj.check_region_glyph_budget("g", StampRegion(19, 19, 2, 1))
    assert not oob.ok
    assert not oob.region_in_bounds

    # PAL palette table properties + 2:1 RGBA aspect check
    pal_table = load_default_pal_palette()
    assert len(pal_table.all_colors()) == 256
    for i in range(128):
        assert pal_table.rgb(2 * i) == pal_table.rgb(2 * i + 1)

    palette = Palette(colbk=0x00, colpf0=0x32, colpf1=0x86, colpf2=0xA6, colpf3=0x0E)
    rgba = render_glyph_bytes_rgba_2x1(
        bytes([0b00_01_10_11] + [0] * 7),
        palette,
        pal_table,
        colpf3=False,
    )
    assert len(rgba) == 8 * 8 * 4
    assert tuple(rgba[0:4]) == (*pal_table.rgb(0x00), 255)
    assert tuple(rgba[4:8]) == (*pal_table.rgb(0x00), 255)
    assert tuple(rgba[24:28]) == (*pal_table.rgb(0xA6), 255)
    assert tuple(rgba[28:32]) == (*pal_table.rgb(0xA6), 255)


def test_room_size_constants_and_derived_pixel_dimensions() -> None:
    assert ROOM_WIDTH == 40
    assert ROOM_HEIGHT == 24
    assert ANTIC4_PIXEL_ASPECT_X == 2
    assert ROOM_PIXEL_WIDTH == 160
    assert ROOM_PIXEL_HEIGHT == 192
    assert ROOM_DISPLAY_WIDTH == 320
    assert ROOM_DISPLAY_HEIGHT == 192
