"""T-7: Positive and negative tests for every error and warning in Section 3.6."""

from __future__ import annotations

from room_editor.model.glyphs import IndexedImage, StampRegion
from room_editor.model.project import (
    MAX_OBJECTS,
    MAX_ROOMS,
    ROOM_HEIGHT,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    RowAssignment,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)
from room_editor.model.validation import validate_project


def _sample_image(cols: int = 8, rows: int = 4) -> IndexedImage:
    """Create a valid indexed image where each tile (gx, gy) is distinct and uses values 1..3."""
    w = cols * 4
    h = rows * 8
    buf = bytearray(w * h)
    for gy in range(rows):
        for gx in range(cols):
            idx = gy * cols + gx + 1
            for py in range(8):
                for px in range(4):
                    if py == 0:
                        val = (idx >> (6 - px * 2)) & 3
                        if val == 0:
                            val = 1
                    elif py == 1 and px == 0:
                        val = 3  # ensure value 11 present for COLPF3 tests
                    else:
                        val = 1
                    buf[(gy * 8 + py) * w + (gx * 4 + px)] = val
    return IndexedImage(width=w, height=h, pixels=bytes(buf))


def _valid_project() -> Project:
    img = _sample_image(8, 4)
    proj = Project(
        object_groups=[ObjectGroup(name="walls", image_path="walls.png", image=img)],
        objects=[
            GameObject(
                id=1,
                name="brick",
                group="walls",
                non_blockable=False,
                region=StampRegion(0, 0, 1, 1),
            )
        ],
        rooms=[
            Room(
                id=1,
                name="K1",
                pos=(0, 0),
                row_groups=["walls"] * ROOM_HEIGHT,
                instances=[ObjectInstance(object_id=1, x=0, y=0)],
            )
        ],
        start=StartPosition(room_id=1, x=5, y=5),
    )
    return proj


def _codes(proj: Project) -> set[str]:
    return {i.code for i in validate_project(proj)}


def test_valid_project_has_no_issues() -> None:
    proj = _valid_project()
    assert validate_project(proj) == []


def test_error_no_start_and_start_out_of_bounds() -> None:
    proj = _valid_project()
    proj.start = None
    assert "NO_START_ROOM" in _codes(proj)

    proj.start = StartPosition(room_id=99, x=0, y=0)
    assert "NO_START_ROOM" in _codes(proj)

    proj.start = StartPosition(room_id=1, x=0, y=23)
    assert "START_OUT_OF_BOUNDS" not in _codes(proj)

    proj.start = StartPosition(room_id=1, x=0, y=24)
    assert "START_OUT_OF_BOUNDS" in _codes(proj)

    proj.start = StartPosition(room_id=1, x=40, y=0)
    assert "START_OUT_OF_BOUNDS" in _codes(proj)


def test_error_instance_bounds_and_overlap() -> None:
    proj = _valid_project()
    proj.objects.append(
        GameObject(id=2, name="wide", group="walls", region=StampRegion(1, 0, 2, 2))
    )
    proj.rebuild_glyph_tables()
    proj.rooms[0].instances.append(ObjectInstance(object_id=2, x=0, y=0))
    assert "INSTANCE_OVERLAP" in _codes(proj)

    # Overlapping only through empty (00) cell -> NO error
    w, h = 8, 8
    hole_pixels = bytearray(w * h)
    # gx=0 all 0 (empty), gx=1 non-empty (value 1)
    for py in range(8):
        for px in range(4):
            hole_pixels[py * w + (4 + px)] = 1
    hole_img = IndexedImage(width=w, height=h, pixels=bytes(hole_pixels))
    proj_zero = Project(
        object_groups=[ObjectGroup(name="walls", image_path="w.png", image=hole_img)],
        objects=[
            GameObject(id=1, name="brick", group="walls", region=StampRegion(1, 0, 1, 1)),
            GameObject(id=2, name="hole", group="walls", region=StampRegion(0, 0, 2, 1)),
        ],
        rooms=[
            Room(
                id=1,
                name="K1",
                row_groups=["walls"] * ROOM_HEIGHT,
                instances=[ObjectInstance(1, 0, 0), ObjectInstance(2, 0, 0)],
            )
        ],
        start=StartPosition(1, 5, 5),
    )
    assert "INSTANCE_OVERLAP" not in _codes(proj_zero)

    # Non-blockable overlaps + hidden warning
    proj_nb = _valid_project()
    proj_nb.objects.extend(
        [
            GameObject(id=2, name="nb_a", group="walls", non_blockable=True, region=StampRegion(1, 0, 1, 1)),
            GameObject(id=3, name="nb_b", group="walls", non_blockable=True, region=StampRegion(2, 0, 1, 1)),
        ]
    )
    proj_nb.rebuild_glyph_tables()
    proj_nb.rooms[0].instances.extend(
        [
            ObjectInstance(object_id=2, x=0, y=0),
            ObjectInstance(object_id=3, x=4, y=4),
            ObjectInstance(object_id=2, x=4, y=4),
        ]
    )
    assert "INSTANCE_OVERLAP" not in _codes(proj_nb)
    assert "HIDDEN_NON_BLOCKABLE_INSTANCE" in _codes(proj_nb)

    # Bottom edge bounds: 1x1 at y=23 and 2x2 at y=22 (ending at row 24) accepted
    proj2 = _valid_project()
    proj2.objects.append(
        GameObject(id=2, name="wide", group="walls", region=StampRegion(1, 0, 2, 2))
    )
    proj2.rebuild_glyph_tables()
    assert proj2.can_place_instance(proj2.rooms[0], 1, 10, 23)[0]
    assert not proj2.can_place_instance(proj2.rooms[0], 1, 10, 24)[0]
    assert proj2.can_place_instance(proj2.rooms[0], 2, 10, 22)[0]
    assert not proj2.can_place_instance(proj2.rooms[0], 2, 10, 23)[0]

    proj2.rooms[0].instances.append(ObjectInstance(object_id=2, x=10, y=22))
    assert "INSTANCE_OUT_OF_BOUNDS" not in _codes(proj2)

    # One row further (y=23 for 2x2) or past right edge (x=39 for 2x2) -> error
    proj2.rooms[0].instances.append(ObjectInstance(object_id=2, x=10, y=23))
    assert "INSTANCE_OUT_OF_BOUNDS" in _codes(proj2)

    proj3 = _valid_project()
    proj3.objects.append(
        GameObject(id=2, name="wide", group="walls", region=StampRegion(1, 0, 2, 2))
    )
    proj3.rebuild_glyph_tables()
    proj3.rooms[0].instances.append(ObjectInstance(object_id=2, x=39, y=0))
    assert "INSTANCE_OUT_OF_BOUNDS" in _codes(proj3)


def test_errors_and_warnings_for_png_regions_mapping_and_glyph_limit() -> None:
    # No image assigned -> error
    proj_no_img = _valid_project()
    proj_no_img.object_groups[0].image = None
    proj_no_img.object_groups[0].image_path = ""
    proj_no_img.object_groups[0].image_status = "none"
    assert "GROUP_NO_IMAGE" in _codes(proj_no_img)

    # Invalid PNG -> error
    proj_inv = _valid_project()
    proj_inv.object_groups[0].image = None
    proj_inv.object_groups[0].image_status = "invalid"
    proj_inv.object_groups[0].image_error = "Bad PNG"
    assert "GROUP_INVALID_IMAGE" in _codes(proj_inv)

    # Missing PNG on disk -> warning (not error)
    proj_miss = _valid_project()
    proj_miss.object_groups[0].image = None
    proj_miss.object_groups[0].image_status = "missing"
    issues_miss = validate_project(proj_miss)
    miss = [i for i in issues_miss if i.code == "GROUP_IMAGE_MISSING"]
    assert len(miss) == 1 and miss[0].severity == "warning"

    # Invalid pixel mapping -> error
    proj_pm = _valid_project()
    proj_pm.object_groups[0].pixel_mapping = (0, 0, 1, 2)
    assert "GROUP_INVALID_PIXEL_MAPPING" in _codes(proj_pm)

    # Object cell limit (>255) & region out of image
    proj_cells = _valid_project()
    proj_cells.objects[0].region = StampRegion(0, 0, 16, 16)
    assert "OBJECT_TOO_MANY_CELLS" in _codes(proj_cells)

    proj_oob = _valid_project()
    proj_oob.objects[0].region = StampRegion(7, 0, 2, 1)
    assert "OBJECT_REGION_OUT_OF_IMAGE" in _codes(proj_oob)

    # Object missing group
    proj_mg = _valid_project()
    proj_mg.objects[0].group = "nonexistent"
    assert "OBJECT_MISSING_GROUP" in _codes(proj_mg)

    # Empty object (only 00 glyphs)
    empty_img = IndexedImage(width=8, height=8, pixels=bytes([0] * 64))
    proj_empty = _valid_project()
    proj_empty.object_groups[0].image = empty_img
    assert "OBJECT_EMPTY" in _codes(proj_empty)

    # COLPF3 flag on object whose glyphs have no pixel value 11 -> warning
    no_11_pixels = bytes([1] * (4 * 8))  # only value 01, never 11
    no_11_img = IndexedImage(width=4, height=8, pixels=no_11_pixels)
    proj_pf3_warn = Project(
        object_groups=[ObjectGroup(name="walls", image_path="w.png", image=no_11_img)],
        objects=[
            GameObject(
                id=1,
                name="brick",
                group="walls",
                colpf3=True,
                region=StampRegion(0, 0, 1, 1),
            )
        ],
        rooms=[
            Room(
                id=1,
                name="K1",
                row_groups=["walls"] * ROOM_HEIGHT,
                instances=[ObjectInstance(1, 0, 0)],
            )
        ],
        start=StartPosition(1, 5, 5),
    )
    codes_pf3 = _codes(proj_pf3_warn)
    assert "OBJECT_COLPF3_NO_EFFECT" in codes_pf3
    assert validate_project(proj_pf3_warn)[0].severity == "warning"

    # Negative check: clearing colpf3 clears warning
    proj_pf3_warn.objects[0].colpf3 = False
    assert _codes(proj_pf3_warn) == set()

    # > 127 glyphs -> GROUP_GLYPH_LIMIT_EXCEEDED + OBJECT_EXCEEDS_GLYPH_LIMIT
    w = 130 * 4
    h = 8
    buf = bytearray(w * h)
    for gx in range(130):
        n = gx + 1
        row0 = [1 + ((n >> 7) & 1), 1 + ((n >> 6) & 1), 1 + ((n >> 5) & 1), 1 + ((n >> 4) & 1)]
        row1 = [1 + ((n >> 3) & 1), 1 + ((n >> 2) & 1), 1 + ((n >> 1) & 1), 1 + (n & 1)]
        for px in range(4):
            buf[0 * w + gx * 4 + px] = row0[px]
            buf[1 * w + gx * 4 + px] = row1[px]
    big_img = IndexedImage(width=w, height=h, pixels=bytes(buf))
    proj_over = Project(
        object_groups=[ObjectGroup(name="walls", image_path="big.png", image=big_img)],
        objects=[
            GameObject(id=1, name="part1", group="walls", region=StampRegion(0, 0, 100, 1)),
            GameObject(id=2, name="part2", group="walls", region=StampRegion(100, 0, 30, 1)),
        ],
        rooms=[
            Room(id=1, name="K1", row_groups=["walls"] * ROOM_HEIGHT)
        ],
        start=StartPosition(1, 5, 5),
    )
    codes_over = _codes(proj_over)
    assert "GROUP_GLYPH_LIMIT_EXCEEDED" in codes_over
    assert "OBJECT_EXCEEDS_GLYPH_LIMIT" in codes_over


def test_error_duplicates_and_limits() -> None:
    proj = _valid_project()
    proj.rooms.append(Room(id=1, name="K1", pos=(0, 0), row_groups=["walls"] * ROOM_HEIGHT))
    codes = _codes(proj)
    assert "DUPLICATE_ROOM_ID" in codes
    assert "DUPLICATE_ROOM_NAME" in codes
    assert "DUPLICATE_ROOM_POS" in codes

    proj2 = _valid_project()
    proj2.objects.append(GameObject(id=1, name="brick", group="walls", region=StampRegion(1, 0, 1, 1)))
    codes2 = _codes(proj2)
    assert "DUPLICATE_OBJECT_ID" in codes2
    assert "DUPLICATE_OBJECT_NAME" in codes2

    proj3 = _valid_project()
    proj3.object_groups.append(ObjectGroup(name="walls", image_path="w.png", image=_sample_image()))
    assert "DUPLICATE_GROUP_NAME" in _codes(proj3)

    proj4 = _valid_project()
    proj4.rooms = [
        Room(id=(i % MAX_ROOMS) + 1, name=f"R{i}", pos=(i, 0), row_groups=["walls"] * ROOM_HEIGHT)
        for i in range(MAX_ROOMS + 1)
    ]
    assert "TOO_MANY_ROOMS" in _codes(proj4)

    proj5 = _valid_project()
    proj5.objects = [
        GameObject(id=(i % MAX_OBJECTS) + 1, name=f"O{i}", group="walls", region=StampRegion(0, 0, 1, 1))
        for i in range(MAX_OBJECTS + 1)
    ]
    assert "TOO_MANY_OBJECTS" in _codes(proj5)


def test_error_teleports() -> None:
    proj = _valid_project()
    proj.teleports.append(
        Teleport(
            a=TeleportEndpoint(room_id=1, x=39, y=23),
            b=TeleportEndpoint(room_id=1, x=0, y=23),
        )
    )
    assert "TELEPORT_OUT_OF_BOUNDS" not in _codes(proj)

    proj.teleports.append(
        Teleport(
            a=TeleportEndpoint(room_id=99, x=0, y=0),
            b=TeleportEndpoint(room_id=1, x=0, y=24),
        )
    )
    codes = _codes(proj)
    assert "TELEPORT_INVALID_ROOM" in codes
    assert "TELEPORT_OUT_OF_BOUNDS" in codes


def test_warnings_all_types_positive_and_negative() -> None:
    proj = _valid_project()
    img2 = _sample_image(4, 2)
    proj.object_groups.append(ObjectGroup(name="alt", image_path="alt.png", image=img2))
    proj.object_groups.append(ObjectGroup(name="unused_grp", image_path="u.png", image=img2))
    proj.objects.append(GameObject(id=2, name="unused_obj", group="walls", region=StampRegion(1, 0, 1, 1)))
    proj.rebuild_glyph_tables()

    r2 = Room(
        id=2,
        name="K2",
        pos=(1, 0),
        row_groups=["alt"] + ["walls"] * (ROOM_HEIGHT - 1),
        instances=[ObjectInstance(object_id=1, x=0, y=y) for y in range(ROOM_HEIGHT)],
    )
    r3 = Room(
        id=3,
        name="K3",
        pos=(5, 5),
        row_groups=["walls"] * ROOM_HEIGHT,
    )
    proj.rooms.extend([r2, r3])

    codes = _codes(proj)
    assert "UNREACHABLE_ROOM" in codes
    assert "OBJECT_ROW_GROUP_MISMATCH" in codes
    assert "ADJACENT_NO_PASSAGE" in codes
    assert "UNUSED_OBJECT" in codes
    assert "UNUSED_GROUP" in codes

    proj.teleports.append(Teleport(a=TeleportEndpoint(1, 1, 1), b=TeleportEndpoint(3, 1, 1)))
    r2.instances.pop(0)
    r2.row_groups[0] = RowAssignment("walls", "default")
    proj.objects[1].group = "alt"
    r3.row_groups[2] = RowAssignment("alt", "default")
    r3.instances.append(ObjectInstance(2, 2, 2))
    proj.object_groups.pop()
    proj.rebuild_glyph_tables()
    assert _codes(proj) == set()
