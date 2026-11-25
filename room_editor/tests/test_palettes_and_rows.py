"""Tests for multi-palette object groups, per-row (group, palette) assignments, YAML v4, validation, and rendering."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image

from room_editor.io.png import load_png
from room_editor.io.yaml_io import (
    ProjectIOError,
    UnsupportedVersionError,
    deserialize_project_from_yaml,
    load_project,
    save_project,
    serialize_project_to_yaml,
)
from room_editor.model.commands import (
    AddGroupPaletteCommand,
    DeleteGroupCommand,
    DeleteGroupPaletteCommand,
    RenameGroupPaletteCommand,
    ReorderGroupPaletteCommand,
    SetRoomRowGroupsCommand,
    UndoStack,
    UpdateGroupPaletteColorsCommand,
)
from room_editor.model.glyphs import IndexedImage, StampRegion
from room_editor.model.palette import (
    DEFAULT_PALETTE_NAME,
    NamedPalette,
    Palette,
    load_default_pal_palette,
)
from room_editor.model.project import (
    PROJECT_VERSION,
    ROOM_HEIGHT,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    RowAssignment,
    Settings,
    StartPosition,
    render_room_row_rgb,
)
from room_editor.model.validation import validate_project


def _make_sample_png(path: Path) -> Path:
    """Create a 16x8 indexed PNG using pixel values 0..3 across 4 glyph cells."""
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 16, 8
    img = Image.new("P", (w, h))
    img.putpalette([0, 0, 0, 200, 100, 50, 50, 200, 100, 50, 100, 200] + [0] * (768 - 12))
    pixels = [0] * (w * h)
    # Glyph (0,0): colpf0 (1), (1,0): colpf1 (2), (2,0): colpf2/colpf3 (3), (3,0): mixed
    for py in range(8):
        for px in range(4):
            pixels[py * w + px] = 1
            pixels[py * w + 4 + px] = 2
            pixels[py * w + 8 + px] = 3
            pixels[py * w + 12 + px] = (px + py) % 4
    img.putdata(pixels)
    img.save(path, format="PNG")
    return path


def _make_project(tmp_path: Path) -> Project:
    png_a = _make_sample_png(tmp_path / "images" / "grp_a.png")
    png_b = _make_sample_png(tmp_path / "images" / "grp_b.png")
    pal_day = NamedPalette("day", Palette(colbk=0x00, colpf0=0x28, colpf1=0xCA, colpf2=0x94, colpf3=0x0E))
    pal_night = NamedPalette("night", Palette(colbk=0x00, colpf0=0x74, colpf1=0x88, colpf2=0x92, colpf3=0x0A))
    pal_cave = NamedPalette("cave", Palette(colbk=0x10, colpf0=0x34, colpf1=0x48, colpf2=0x5C, colpf3=0x1E))

    grp_a = ObjectGroup(
        name="grp_a",
        image_path="images/grp_a.png",
        palettes=[pal_day, pal_night],
        image=load_png(png_a),
    )
    grp_b = ObjectGroup(
        name="grp_b",
        image_path="images/grp_b.png",
        palettes=[pal_cave],
        image=load_png(png_b),
    )
    objs = [
        GameObject(id=1, name="pf0_tile", group="grp_a", region=StampRegion(0, 0, 1, 1)),
        GameObject(id=2, name="pf2_tile", group="grp_a", colpf3=False, region=StampRegion(2, 0, 1, 1)),
        GameObject(id=3, name="pf3_tile", group="grp_a", colpf3=True, region=StampRegion(2, 0, 1, 1)),
        GameObject(id=4, name="b_tile", group="grp_b", region=StampRegion(1, 0, 1, 1)),
    ]
    r1 = Room(
        id=1,
        name="R1",
        pos=(0, 0),
        row_groups=[RowAssignment("grp_a", "day")] * 12 + [RowAssignment("grp_a", "night")] * 12,
        instances=[
            ObjectInstance(1, 0, 0),
            ObjectInstance(2, 1, 0),
            ObjectInstance(3, 2, 0),
            ObjectInstance(1, 0, 12),
            ObjectInstance(2, 1, 12),
            ObjectInstance(3, 2, 12),
        ],
    )
    r2 = Room(
        id=2,
        name="R2",
        pos=(1, 0),
        row_groups=[RowAssignment("grp_b", "cave")] * ROOM_HEIGHT,
        instances=[ObjectInstance(4, 3, 3)],
    )
    return Project(
        settings=Settings(default_palette=Palette(colbk=0x00, colpf0=0x28, colpf1=0xCA, colpf2=0x94, colpf3=0x0F)),
        object_groups=[grp_a, grp_b],
        objects=objs,
        rooms=[r1, r2],
        start=StartPosition(room_id=1, x=5, y=5),
    )


def test_group_palette_crud_and_undo_redo(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    grp_a = proj.get_group("grp_a")
    assert grp_a is not None
    assert grp_a.palette_names() == ["day", "night"]
    assert grp_a.default_palette_name == "day"

    stack = UndoStack()

    # Add palette initialized with unique name
    new_name = grp_a.next_free_palette_name("sunset")
    stack.push_and_execute(
        AddGroupPaletteCommand(grp_a, NamedPalette(new_name, Palette(colbk=0, colpf0=44, colpf1=55, colpf2=66, colpf3=77)))
    )
    assert grp_a.palette_names() == ["day", "night", "sunset"]

    # Edit colors + undo/redo
    stack.push_and_execute(
        UpdateGroupPaletteColorsCommand(grp_a, "sunset", Palette(colbk=2, colpf0=88, colpf1=99, colpf2=110, colpf3=120))
    )
    assert grp_a.get_palette("sunset").colpf0 == 88
    stack.undo()
    assert grp_a.get_palette("sunset").colpf0 == 44
    stack.redo()
    assert grp_a.get_palette("sunset").colpf0 == 88

    # Rename updates room references + undo/redo
    stack.push_and_execute(RenameGroupPaletteCommand(proj, grp_a, "night", "midnight"))
    assert grp_a.palette_names() == ["day", "midnight", "sunset"]
    assert all(ra == RowAssignment("grp_a", "midnight") for ra in proj.get_room(1).row_groups[12:])
    stack.undo()
    assert grp_a.palette_names() == ["day", "night", "sunset"]
    assert all(ra == RowAssignment("grp_a", "night") for ra in proj.get_room(1).row_groups[12:])
    stack.redo()
    assert all(ra == RowAssignment("grp_a", "midnight") for ra in proj.get_room(1).row_groups[12:])

    # Reorder preserves explicit room RowAssignment palette names + undo/redo
    stack.push_and_execute(ReorderGroupPaletteCommand(grp_a, 1, 0))  # midnight becomes index 0
    assert grp_a.palette_names() == ["midnight", "day", "sunset"]
    assert grp_a.default_palette_name == "midnight"
    assert proj.get_room(1).row_groups[0] == RowAssignment("grp_a", "day")
    assert proj.get_room(1).row_groups[12] == RowAssignment("grp_a", "midnight")
    stack.undo()
    assert grp_a.palette_names() == ["day", "midnight", "sunset"]

    # Usage tracking & delete with fallback + undo/redo
    usage = proj.find_palette_usage("grp_a", "midnight")
    assert usage == [(1, "R1", list(range(12, 24)))]
    stack.push_and_execute(DeleteGroupPaletteCommand(proj, grp_a, "midnight"))
    assert grp_a.palette_names() == ["day", "sunset"]
    # Rows using deleted palette fall back to group's first palette ("day")
    assert all(ra == RowAssignment("grp_a", "day") for ra in proj.get_room(1).row_groups)
    stack.undo()
    assert grp_a.palette_names() == ["day", "midnight", "sunset"]
    assert all(ra == RowAssignment("grp_a", "midnight") for ra in proj.get_room(1).row_groups[12:])

    # Deleting last remaining palette of grp_b is refused
    grp_b = proj.get_group("grp_b")
    assert grp_b is not None
    with pytest.raises(ValueError, match="last palette"):
        DeleteGroupPaletteCommand(proj, grp_b, "cave").execute()


def test_row_assignments_default_single_range_and_group_ops(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    r = Room(id=3, name="R3", pos=(2, 0))
    r.set_all_row_groups("grp_a", "night")
    assert len(r.row_groups) == ROOM_HEIGHT
    assert r.row_groups == [RowAssignment("grp_a", "night")] * ROOM_HEIGHT

    proj.rooms.append(r)
    stack = UndoStack()

    new_rows = list(r.row_groups)
    new_rows[4] = RowAssignment("grp_a", "day")
    for y in range(10, 14):
        new_rows[y] = RowAssignment("grp_b", "cave")

    stack.push_and_execute(SetRoomRowGroupsCommand(r, new_rows))
    assert r.row_groups[4] == RowAssignment("grp_a", "day")
    assert r.row_groups[10:14] == [RowAssignment("grp_b", "cave")] * 4
    stack.undo()
    assert r.row_groups == [RowAssignment("grp_a", "night")] * ROOM_HEIGHT
    stack.redo()
    assert r.row_groups[12] == RowAssignment("grp_b", "cave")

    # Deleting grp_b falls back affected rows to (grp_a, day)
    stack.push_and_execute(DeleteGroupCommand(proj, "grp_b", fallback_group="grp_a", fallback_palette="day"))
    assert all(ra.group != "grp_b" for ra in r.row_groups)
    assert r.row_groups[10:14] == [RowAssignment("grp_a", "day")] * 4
    stack.undo()
    assert r.row_groups[10:14] == [RowAssignment("grp_b", "cave")] * 4


def test_yaml_v4_round_trip_compact_rows_and_errors(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    # R1 rows 0..11 use first palette ("day") -> serialized as compact string "grp_a"
    # R1 rows 12..23 use second palette ("night") -> serialized as {group: grp_a, palette: night}
    # R2 uses single (grp_b, cave) for all 24 rows -> compact [grp_b]
    yaml_path = tmp_path / "project_v4.yaml"
    save_project(proj, yaml_path)
    text1 = yaml_path.read_text(encoding="utf-8")

    assert f"version: {PROJECT_VERSION}" in text1
    doc = yaml.safe_load(text1)
    assert doc["version"] == 4
    assert [p["name"] for p in doc["object_groups"][0]["palettes"]] == ["day", "night"]
    r1_rows = doc["rooms"][0]["row_groups"]
    assert len(r1_rows) == ROOM_HEIGHT
    assert r1_rows[0] == "grp_a"
    assert r1_rows[12] == {"group": "grp_a", "palette": "night"}
    assert doc["rooms"][1]["row_groups"] == ["grp_b"]

    # Round-trip equality + byte-for-byte determinism
    loaded = load_project(yaml_path)
    assert loaded.missing_images == []
    assert loaded.invalid_images == []
    assert loaded.project == proj
    yaml_path2 = tmp_path / "project_v4_again.yaml"
    save_project(loaded.project, yaml_path2)
    assert yaml_path2.read_text(encoding="utf-8") == text1

    # Explicit mapping form also loads when targeting the first palette (and normalizes on save)
    explicit_doc = yaml.safe_load(text1)
    explicit_doc["rooms"][0]["row_groups"][0] = {"group": "grp_a", "palette": "day"}
    explicit_doc["rooms"][1]["row_groups"] = [{"group": "grp_b", "palette": "cave"}]
    reloaded_explicit = deserialize_project_from_yaml(
        yaml.safe_dump(explicit_doc, sort_keys=False), base_dir=tmp_path
    )
    assert reloaded_explicit.project == proj
    assert serialize_project_to_yaml(reloaded_explicit.project) == text1

    # Older versions (1, 2, 3) are rejected
    for old_ver in (1, 2, 3):
        with pytest.raises(UnsupportedVersionError, match="version"):
            deserialize_project_from_yaml(f"version: {old_ver}\nrooms: []\n")

    # Unknown group / palette / wrong row count in row_groups are rejected cleanly
    bad_pal_doc = yaml.safe_load(text1)
    bad_pal_doc["rooms"][0]["row_groups"][0] = {"group": "grp_a", "palette": "nonexistent"}
    with pytest.raises(ProjectIOError, match="unknown palette"):
        deserialize_project_from_yaml(yaml.safe_dump(bad_pal_doc, sort_keys=False), base_dir=tmp_path)

    bad_grp_doc = yaml.safe_load(text1)
    bad_grp_doc["rooms"][1]["row_groups"] = ["no_such_group"]
    with pytest.raises(ProjectIOError, match="unknown object group"):
        deserialize_project_from_yaml(yaml.safe_dump(bad_grp_doc, sort_keys=False), base_dir=tmp_path)

    for bad_len in (20, 25):
        bad_len_doc = yaml.safe_load(text1)
        bad_len_doc["rooms"][0]["row_groups"] = ["grp_a"] * bad_len
        with pytest.raises(ProjectIOError, match="row_groups"):
            deserialize_project_from_yaml(yaml.safe_dump(bad_len_doc, sort_keys=False), base_dir=tmp_path)


def test_render_room_row_rgb_uses_row_palette_and_group(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    pal_table = load_default_pal_palette()
    r1 = proj.get_room(1)
    assert r1 is not None

    # Row 0 uses (grp_a, day); Row 12 uses (grp_a, night) for identical objects
    row0 = render_room_row_rgb(proj, r1, 0, pal_table)
    row12 = render_room_row_rgb(proj, r1, 12, pal_table)

    # Cell x=0 is pf0_tile (COLPF0), x=1 is pf2_tile (COLPF2), x=2 is pf3_tile (COLPF3), x=3 is empty (COLBK)
    assert row0[0][0] == pal_table.rgb(0x28)
    assert row0[0][4] == pal_table.rgb(0x94)
    assert row0[0][8] == pal_table.rgb(0x0E)
    assert row0[0][12] == pal_table.rgb(0x00)

    assert row12[0][0] == pal_table.rgb(0x74)
    assert row12[0][4] == pal_table.rgb(0x92)
    assert row12[0][8] == pal_table.rgb(0x0A)
    assert row12[0][12] == pal_table.rgb(0x00)

    # Row 13 switched to grp_b / cave -> Object 1 emits code 1, which in grp_b's glyph
    # table is b_tile (pixel 2 = COLPF1), rendered with cave palette's COLPF1 (0x48) & COLBK (0x10)
    r1.instances.append(ObjectInstance(1, 0, 13))
    r1.set_row_group(13, "grp_b", "cave")
    row13 = render_room_row_rgb(proj, r1, 13, pal_table)
    assert row13[0][0] == pal_table.rgb(0x48)  # grp_b glyph 1 (COLPF1) with cave palette
    assert row13[0][12] == pal_table.rgb(0x10)  # grp_b cave COLBK


def test_validation_palette_errors_and_unused_palette_warning(tmp_path: Path) -> None:
    proj = _make_project(tmp_path)
    assert validate_project(proj) == []

    # Unused palette produces warning UNUSED_PALETTE
    grp_a = proj.get_group("grp_a")
    assert grp_a is not None
    grp_a.palettes.append(NamedPalette("spare", Palette()))
    codes = {m.code for m in validate_project(proj)}
    assert codes == {"UNUSED_PALETTE"}

    # Duplicate / empty palette name and missing palettes list
    grp_a.palettes.append(NamedPalette("", Palette()))
    grp_a.palettes.append(NamedPalette("day", Palette()))
    codes = {m.code for m in validate_project(proj)}
    assert "EMPTY_PALETTE_NAME" in codes
    assert "DUPLICATE_PALETTE_NAME" in codes

    grp_b = proj.get_group("grp_b")
    assert grp_b is not None
    grp_b.palettes.clear()
    codes = {m.code for m in validate_project(proj)}
    assert "GROUP_NO_PALETTES" in codes

    # Invalid room row group & invalid room row palette
    proj2 = _make_project(tmp_path)
    r1 = proj2.get_room(1)
    assert r1 is not None
    r1.row_groups[0] = RowAssignment("grp_a", "missing_pal")
    r1.row_groups[1] = RowAssignment("missing_grp", "day")
    codes2 = {m.code for m in validate_project(proj2)}
    assert "ROOM_INVALID_ROW_PALETTE" in codes2
    assert "ROOM_INVALID_ROW_GROUP" in codes2
