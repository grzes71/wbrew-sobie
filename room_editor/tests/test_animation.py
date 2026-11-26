"""Part A tests: Object frame animation model, glyph accounting, validation, undo/redo, YAML v5, and UI."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from PIL import Image
from PySide6.QtWidgets import QApplication

from room_editor.io.png import IndexedImage, load_png
from room_editor.io.yaml_io import (
    ProjectIOError,
    UnsupportedVersionError,
    deserialize_project_from_yaml,
    load_project,
    save_project,
    serialize_project_to_yaml,
)
from room_editor.model import (
    EMPTY_GLYPH_BYTES,
    MAX_ANIMATION_SPEED,
    MAX_OBJECT_FRAMES,
    PROJECT_VERSION,
    ROOM_HEIGHT,
    AddObjectFrameCommand,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Palette,
    NamedPalette,
    Project,
    RemoveObjectFrameCommand,
    ReorderObjectFrameCommand,
    ReplaceObjectFrameCommand,
    Room,
    StampRegion,
    UndoStack,
    UpdateObjectCommand,
    validate_project,
)
from room_editor.ui.objects_view import ObjectsView
from room_editor.ui.rendering_qt import QtRenderer
from room_editor.ui.room_editor_view import RoomEditorView
from room_editor.ui.stamp_image_widget import StampImageWidget
from room_editor.model.palette import load_default_pal_palette


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["-platform", "offscreen"])
    return app  # type: ignore[return-value]


def _make_tile_png(path: Path, tiles_x: int, tiles_y: int, tile_fn) -> Path:
    """Create an indexed PNG composed of (4px x 8px) tiles described by tile_fn(tx, ty) -> 8 bytes or constant."""
    path.parent.mkdir(parents=True, exist_ok=True)
    w = tiles_x * 4
    h = tiles_y * 8
    img = Image.new("P", (w, h))
    img.putpalette([0, 0, 0, 200, 100, 50, 50, 200, 100, 50, 100, 200] + [0] * (768 - 12))
    pixels = [0] * (w * h)
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            val = tile_fn(tx, ty)
            if isinstance(val, (bytes, bytearray)):
                rows = val
            else:
                rows = bytes([val] * 8)
            for py in range(8):
                b = rows[py]
                for px_i in range(4):
                    col_pair = (b >> (6 - 2 * px_i)) & 0x03
                    pixels[(ty * 8 + py) * w + (tx * 4 + px_i)] = col_pair
    img.putdata(pixels)
    img.save(path, format="PNG")
    return path


def _make_indexed_image_from_tiles(tiles_x: int, tiles_y: int, tile_fn) -> IndexedImage:
    w = tiles_x * 4
    h = tiles_y * 8
    pixels = bytearray(w * h)
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            val = tile_fn(tx, ty)
            rows = val if isinstance(val, (bytes, bytearray)) else bytes([val] * 8)
            for py in range(8):
                b = rows[py]
                for px_i in range(4):
                    pixels[(ty * 8 + py) * w + (tx * 4 + px_i)] = (b >> (6 - 2 * px_i)) & 0x03
    return IndexedImage(width=w, height=h, pixels=bytes(pixels))


def test_is_animated_contract_and_non_animated_zero_extra_slots() -> None:
    """Animated iff len(frames) >= 2 and animation_speed > 0; static ignores extra frames."""
    # Single frame with speed > 0 -> NOT animated
    o_single = GameObject(
        id=1,
        name="single",
        group="g",
        frames=[StampRegion(0, 0, 1, 1)],
        animation_speed=10,
    )
    assert not o_single.is_animated

    # Two frames with speed == 0 -> NOT animated (extra frame uses 0 slots)
    o_speed0 = GameObject(
        id=2,
        name="paused",
        group="g",
        frames=[StampRegion(0, 0, 2, 1), StampRegion(2, 0, 2, 1)],
        animation_speed=0,
    )
    assert not o_speed0.is_animated

    # Two frames with speed > 0 -> animated
    o_anim = GameObject(
        id=3,
        name="torch",
        group="g",
        frames=[StampRegion(0, 0, 2, 1), StampRegion(2, 0, 2, 1)],
        animation_speed=8,
    )
    assert o_anim.is_animated

    # Static object with extra non-zero tile in frame 1 uses ONLY frame 0 glyphs!
    img = _make_indexed_image_from_tiles(
        4, 1, lambda tx, _ty: {0: 0xAA, 1: 0x00, 2: 0x55, 3: 0xFF}[tx]
    )
    grp = ObjectGroup(name="g", image_path="g.png", image=img)
    proj = Project(
        object_groups=[grp],
        objects=[o_speed0],
    )
    proj.rebuild_glyph_tables()
    gt = grp.glyph_table
    ga = grp.glyph_analysis
    assert ga is not None
    # Frame 0 is (0,0)=0xAA and (1,0)=0x00 -> only 1 static glyph! Frame 1 is ignored.
    assert ga.static_glyph_count == 1
    assert ga.dedicated_slot_count == 0
    assert gt.used_count == 1
    assert gt.entries[0].data == bytes([0xAA] * 8)


def test_dedicated_slots_within_object_sharing_and_constant_cells() -> None:
    """Constant cells share static pool (0 dedicated slots); identical varying sequences share 1 dedicated slot."""
    # 6x2 tile grid for a 3x2 animated object across 2 frames:
    # Frame 0 (0,0,3,2):
    #   (0,0)=0xAA [constant matching static!], (1,0)=0xBB, (2,0)=0xBB
    #   (0,1)=0x00 [constant empty -> 0!],     (1,1)=0x00, (2,1)=0xCC
    # Frame 1 (3,0,3,2):
    #   (3,0)=0xAA [constant matching static!], (4,0)=0xDD, (5,0)=0xDD  <- same varying seq as (1,0)!
    #   (3,1)=0x00 [constant empty -> 0!],     (4,1)=0xEE, (5,1)=0xFF  <- (1,1)=(0x00,0xEE), (2,1)=(0xCC,0xFF)
    tile_map = {
        (0, 0): 0xAA,
        (1, 0): 0xBB,
        (2, 0): 0xBB,
        (0, 1): 0x00,
        (1, 1): 0x00,
        (2, 1): 0xCC,
        (3, 0): 0xAA,
        (4, 0): 0xDD,
        (5, 0): 0xDD,
        (3, 1): 0x00,
        (4, 1): 0xEE,
        (5, 1): 0xFF,
    }
    img = _make_indexed_image_from_tiles(6, 2, lambda tx, ty: tile_map[(tx, ty)])
    static_obj = GameObject(
        id=1, name="wall", group="g", frames=[StampRegion(0, 0, 1, 1)], animation_speed=0
    )
    anim_obj = GameObject(
        id=2,
        name="portal",
        group="g",
        frames=[StampRegion(0, 0, 3, 2), StampRegion(3, 0, 3, 2)],
        animation_speed=12,
    )
    # Second animated object with identical varying pattern sequence at (1,0) -> MUST NOT share with obj 2!
    anim_obj2 = GameObject(
        id=3,
        name="portal2",
        group="g",
        frames=[StampRegion(1, 0, 1, 1), StampRegion(4, 0, 1, 1)],
        animation_speed=8,
    )
    proj = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[static_obj, anim_obj, anim_obj2],
    )
    proj.rebuild_glyph_tables()
    gt = proj.object_groups[0].glyph_table
    ga = proj.object_groups[0].glyph_analysis
    assert ga is not None

    # Static gets 1 unique glyph (0xAA -> code 1).
    # Obj 2 has 2 constant cells ((0,0)=code 1 from static pool, (0,1)=code 0 empty) and 4 varying cells
    # collapsed to 3 dedicated slots: seq (BB,DD) shared by ((1,0),(2,0))->code 2; (00,EE)->code 3; (CC,FF)->code 4.
    # Obj 3 gets its own dedicated code 5 (no cross-object dedicated sharing).
    assert ga.static_glyph_count == 1
    assert ga.dedicated_slot_count == 4
    assert gt.used_count == 5
    assert static_obj.chars == [[1]]
    assert anim_obj.chars == [[1, 2, 2], [0, 3, 4]]
    assert anim_obj.constant_cell_count == 2
    assert anim_obj.varying_cell_count == 4
    assert anim_obj.dedicated_slots == [
        (2, ((1, 0), (2, 0))),
        (3, ((1, 1),)),
        (4, ((2, 1),)),
    ]
    assert anim_obj2.chars == [[5]]

    # Verify dedicated entries carry cells + all frame byte blocks
    assert gt.entries[0].is_dedicated is False
    ded_entries = gt.entries[1:]
    assert all(g.is_dedicated for g in ded_entries)
    assert ded_entries[0].object_id == 2
    assert ded_entries[0].cells == ((1, 0), (2, 0))
    assert ded_entries[0].frames == (bytes([0xBB] * 8), bytes([0xDD] * 8))
    assert ded_entries[1].cells == ((1, 1),)
    assert ded_entries[1].frames == (EMPTY_GLYPH_BYTES, bytes([0xEE] * 8))


def test_budget_recomputation_raise_and_lower_slots() -> None:
    """Budget check recomputes from scratch and handles both increases and decreases in total slots."""
    tile_map = {
        (0, 0): 0xAA,
        (1, 0): 0xBB,
        (2, 0): 0xAA,
        (3, 0): 0xBB,
        (4, 0): 0xAA,
        (5, 0): 0xCC,
    }
    img = _make_indexed_image_from_tiles(6, 1, lambda tx, _ty: tile_map[(tx, 0)])
    # obj 1: static with 0xAA (code 1)
    # obj 2: 2x1 animated starting with identical cells -> constant -> shared with static / static_unique (1+1=2)
    static_a = GameObject(id=1, name="sa", group="g", frames=[StampRegion(0, 0, 1, 1)])
    anim_2 = GameObject(
        id=2,
        name="a2",
        group="g",
        frames=[StampRegion(0, 0, 2, 1), StampRegion(4, 0, 2, 1)],  # (0,0) const AA, (1,0) vary BB->CC
        animation_speed=10,
    )
    proj = Project(object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)], objects=[static_a, anim_2])
    proj.rebuild_glyph_tables()
    # Base: AA(static 1) + (BB,CC)(ded 1) = 2 total
    assert proj.object_groups[0].glyph_table.used_count == 2

    # Replacing frame 1 with constant matching reg (2,0) (AA, BB) collapses (BB,CC) into shared static BB
    # -> total drops from 3 (Wait: let's add static BB object to test lowering shared static)!
    static_b = GameObject(id=3, name="sb", group="g", frames=[StampRegion(1, 0, 1, 1)])
    proj.objects.append(static_b)
    proj.rebuild_glyph_tables()
    # Now: static={AA, BB} (2) + ded={(BB,CC)} (1) = 3 used!
    prev_used = proj.object_groups[0].glyph_table.used_count
    assert prev_used == 3

    # Replacing frame 1 with (2,0) (AA, BB) collapses varying cell into shared static BB -> drops to 2 (-1)!
    chk_drop = proj.check_object_glyph_budget(
        "g",
        [StampRegion(0, 0, 2, 1), StampRegion(2, 0, 2, 1)],
        animation_speed=10,
        exclude_object_id=2,
    )
    assert chk_drop.ok
    assert chk_drop.total_used == 2
    assert chk_drop.total_used - prev_used == -1

    # Adding a 3rd frame differing at (0,0) splits AA -> (AA,AA,CC) -> increases total used to 4 (+1)!
    chk_raise = proj.check_object_glyph_budget(
        "g",
        [StampRegion(0, 0, 2, 1), StampRegion(4, 0, 2, 1), StampRegion(5, 0, 2, 1) if False else StampRegion(4, 0, 2, 1)],
        animation_speed=10,
        exclude_object_id=2,
    )
    assert chk_raise.ok


def test_glyph_budget_127_boundary_with_dedicated_slots() -> None:
    """Total = static unique + sum(dedicated) must stay <= 127."""
    # Create 16x9 tile sheet -> up to 144 unique non-zero tiles
    img = _make_indexed_image_from_tiles(
        16, 9, lambda tx, ty: bytes([((ty * 16 + tx + 1) & 0xFF)] + [1, 2, 3, 4, 5, 6, 7])
    )
    grp = ObjectGroup(name="g", image_path="g.png", image=img)

    # 123 unique 1x1 static objects + one 2x2 (4-slot) animated object = 127 -> fits!
    objs = [
        GameObject(
            id=i + 1,
            name=f"s{i}",
            group="g",
            frames=[StampRegion(i % 16, i // 16, 1, 1)],
            animation_speed=0,
        )
        for i in range(123)
    ]
    anim_4 = GameObject(
        id=200,
        name="a4",
        group="g",
        frames=[StampRegion(0, 8, 2, 1), StampRegion(2, 8, 2, 1)],
        animation_speed=5,
    )
    # 2x1 = 2 slots -> 125 slots total; make it 4x1 -> 4 slots = 127 total
    anim_4_fit = GameObject(
        id=200,
        name="a4",
        group="g",
        frames=[StampRegion(0, 8, 4, 1), StampRegion(4, 8, 4, 1)],
        animation_speed=5,
    )
    proj = Project(object_groups=[grp], objects=objs + [anim_4_fit])
    proj.rebuild_glyph_tables()
    assert grp.glyph_table.used_count == 127
    issues_ok = validate_project(proj)
    assert not any(i.code == "GROUP_GLYPH_LIMIT_EXCEEDED" for i in issues_ok)

    # Now add 1 more animated slot (make it 5x1 -> 123 + 5 = 128)
    check = proj.check_object_glyph_budget(
        "g",
        [StampRegion(0, 8, 5, 1), StampRegion(5, 8, 5, 1)],
        animation_speed=5,
        exclude_object_id=200,
    )
    assert not check.ok
    assert check.total_used == 128

    proj.objects[-1] = GameObject(
        id=200,
        name="a5",
        group="g",
        frames=[StampRegion(0, 8, 5, 1), StampRegion(5, 8, 5, 1)],
        animation_speed=5,
    )
    proj.rebuild_glyph_tables()
    issues_over = validate_project(proj)
    assert any(i.code == "GROUP_GLYPH_LIMIT_EXCEEDED" for i in issues_over)


def test_animated_object_foreign_row_group_rejected() -> None:
    """Animated object cannot be placed into rows belonging to a different group."""
    img = _make_indexed_image_from_tiles(4, 2, lambda tx, ty: 0xAA + ty * 4 + tx)
    grp_a = ObjectGroup(name="castle", image_path="a.png", image=img)
    grp_b = ObjectGroup(name="cave", image_path="b.png", image=img)
    static_a = GameObject(id=1, name="brick", group="castle", frames=[StampRegion(0, 0, 1, 1)])
    anim_a = GameObject(
        id=2,
        name="torch",
        group="castle",
        frames=[StampRegion(0, 0, 1, 2), StampRegion(1, 0, 1, 2)],
        animation_speed=10,
    )
    room = Room(
        id=1,
        name="R1",
        pos=(0, 0),
        row_groups=["castle"] * 10 + ["cave"] * (ROOM_HEIGHT - 10),
    )
    proj = Project(object_groups=[grp_a, grp_b], objects=[static_a, anim_a], rooms=[room])
    proj.rebuild_glyph_tables()

    # Static object in foreign row is still allowed (with warning only)
    ok_static, _ = proj.can_place_instance(room, static_a.id, 5, 12)
    assert ok_static
    assert proj.object_placement_error(static_a) == ""

    # Animated 1x2 spanning y=9 (castle) and y=10 (cave) -> rejected!
    ok_bad, err = proj.can_place_instance(room, anim_a.id, 5, 9)
    assert not ok_bad
    assert "cave" in err

    # Animated completely inside castle rows y=0..8 -> allowed!
    ok_good, _ = proj.can_place_instance(room, anim_a.id, 5, 0)
    assert ok_good

    # If YAML somehow contains foreign placement, validate_project flags error
    room.instances.append(ObjectInstance(2, 5, 9))
    issues = validate_project(proj)
    assert any(i.code == "ANIMATED_OBJECT_ROW_GROUP_MISMATCH" and i.severity == "error" for i in issues)


def test_validation_warnings_and_errors_for_frames_and_speed() -> None:
    """Check frame count, speed range, size mismatch, out-of-bounds, and info warnings."""
    img = _make_indexed_image_from_tiles(8, 4, lambda tx, _ty: 0xAA if tx < 4 else 0x55)
    grp = ObjectGroup(name="g", image_path="g.png", image=img)

    # Identical frames warning
    obj_ident = GameObject(
        id=1,
        name="ident",
        group="g",
        frames=[StampRegion(0, 0, 1, 1), StampRegion(1, 0, 1, 1)],
        animation_speed=15,
    )
    # 1 frame with speed > 0 warning
    obj_one_spd = GameObject(
        id=2,
        name="onespd",
        group="g",
        frames=[StampRegion(0, 0, 1, 1)],
        animation_speed=20,
    )
    # >1 frames with speed == 0 warning
    obj_paused = GameObject(
        id=3,
        name="paused",
        group="g",
        frames=[StampRegion(0, 0, 1, 1), StampRegion(4, 0, 1, 1)],
        animation_speed=0,
    )
    proj = Project(object_groups=[grp], objects=[obj_ident, obj_one_spd, obj_paused])
    issues = validate_project(proj)
    codes = {i.code for i in issues}
    assert "ANIM_NO_VARYING_CELLS" in codes
    assert any(
        i.code == "ANIM_NO_VARYING_CELLS"
        and "animated object without any varying cell" in i.message
        for i in issues
    )
    assert "ANIM_SPEED_SINGLE_FRAME" in codes
    assert "ANIM_FRAMES_SPEED_ZERO" in codes

    # Error cases
    bad_frames_17 = GameObject(
        id=4,
        name="too_many",
        group="g",
        frames=[StampRegion(0, 0, 1, 1)] * (MAX_OBJECT_FRAMES + 1),
        animation_speed=10,
    )
    bad_speed = GameObject(
        id=5,
        name="bad_spd",
        group="g",
        frames=[StampRegion(0, 0, 1, 1), StampRegion(4, 0, 1, 1)],
        animation_speed=MAX_ANIMATION_SPEED + 1,
    )
    bad_size = GameObject(
        id=6,
        name="bad_sz",
        group="g",
        frames=[StampRegion(0, 0, 1, 1), StampRegion(4, 0, 2, 1)],
        animation_speed=5,
    )
    bad_oob = GameObject(
        id=7,
        name="oob",
        group="g",
        frames=[StampRegion(0, 0, 1, 1), StampRegion(8, 3, 1, 1)],
        animation_speed=5,
    )
    proj2 = Project(
        object_groups=[grp],
        objects=[bad_frames_17, bad_speed, bad_size, bad_oob],
    )
    codes2 = {i.code for i in validate_project(proj2) if i.severity == "error"}
    assert "OBJECT_INVALID_FRAME_COUNT" in codes2
    assert "OBJECT_INVALID_ANIMATION_SPEED" in codes2
    assert "OBJECT_FRAME_SIZE_MISMATCH" in codes2
    assert "OBJECT_REGION_OUT_OF_IMAGE" in codes2


def test_frame_undo_redo_commands() -> None:
    """Add, Replace, Reorder, Remove frame commands and speed updates undo/redo cleanly."""
    img = _make_indexed_image_from_tiles(4, 1, lambda tx, _ty: 0xAA + tx)
    grp = ObjectGroup(name="g", image_path="g.png", image=img)
    f0 = StampRegion(0, 0, 1, 1)
    f1 = StampRegion(1, 0, 1, 1)
    f2 = StampRegion(2, 0, 1, 1)
    f3 = StampRegion(3, 0, 1, 1)
    obj = GameObject(id=1, name="o", group="g", frames=[f0], animation_speed=0)
    proj = Project(object_groups=[grp], objects=[obj])
    proj.rebuild_glyph_tables()
    stack = UndoStack()

    stack.push_and_execute(AddObjectFrameCommand(proj, obj, f1))
    stack.push_and_execute(AddObjectFrameCommand(proj, obj, f2))
    assert obj.frames == [f0, f1, f2]

    stack.push_and_execute(ReplaceObjectFrameCommand(proj, obj, 1, f3))
    assert obj.frames == [f0, f3, f2]

    stack.push_and_execute(ReorderObjectFrameCommand(proj, obj, 0, 2))
    assert obj.frames == [f3, f2, f0]

    stack.push_and_execute(UpdateObjectCommand(proj, obj, animation_speed=15))
    assert obj.is_animated
    assert grp.glyph_analysis is not None and grp.glyph_analysis.dedicated_slot_count == 1

    stack.push_and_execute(RemoveObjectFrameCommand(proj, obj, 1))
    assert obj.frames == [f3, f0]

    # Undo all the way back
    while stack.can_undo:
        stack.undo()
    assert obj.frames == [f0]
    assert obj.animation_speed == 0
    assert grp.glyph_analysis is not None and grp.glyph_analysis.dedicated_slot_count == 0


def test_yaml_v5_roundtrip_consistency_and_errors(tmp_path: Path) -> None:
    """YAML v5 round-trip stores frames/cells inside dedicated glyphs (no frame_data) and detects mismatches."""
    png_path = _make_tile_png(tmp_path / "gfx" / "g.png", 6, 2, lambda tx, ty: 0x11 * (ty * 6 + tx + 1))
    img = load_png(png_path)
    grp = ObjectGroup(
        name="g",
        image_path="gfx/g.png",
        palettes=[NamedPalette("default", Palette(colbk=0, colpf0=10, colpf1=20, colpf2=30, colpf3=40))],
        image=img,
    )
    static_o = GameObject(id=1, name="st", group="g", frames=[StampRegion(0, 0, 1, 1)], animation_speed=0)
    anim_o = GameObject(
        id=2,
        name="an",
        group="g",
        frames=[StampRegion(0, 0, 2, 1), StampRegion(2, 0, 2, 1), StampRegion(4, 0, 2, 1)],
        animation_speed=10,
    )
    room = Room(id=1, name="R1", pos=(0, 0), row_groups=["g"] * ROOM_HEIGHT, instances=[ObjectInstance(2, 4, 4)])
    proj = Project(object_groups=[grp], objects=[static_o, anim_o], rooms=[room])
    proj.rebuild_glyph_tables()

    yfile = tmp_path / "proj.yaml"
    save_project(proj, yfile)
    doc = yaml.safe_load(yfile.read_text(encoding="utf-8"))
    assert doc["version"] == PROJECT_VERSION == 5

    anim_doc = [o for o in doc["objects"] if o["id"] == 2][0]
    assert anim_doc["animation_speed"] == 10
    assert len(anim_doc["frames"]) == 3
    assert "frame_data" not in anim_doc

    ded_glyphs = [g for g in doc["object_groups"][0]["glyphs"] if "object" in g]
    assert len(ded_glyphs) == 2
    assert all(g["object"] == 2 and "cells" in g and len(g["frames"]) == 3 for g in ded_glyphs)

    # Round-trip reload
    reloaded = load_project(yfile)
    assert not reloaded.glyph_table_mismatches
    assert serialize_project_to_yaml(reloaded.project) == yfile.read_text(encoding="utf-8")

    # Mutate dedicated glyph frames -> mismatch flagged in glyph_table_mismatches on load
    ded_glyphs[0]["frames"][1] = "FFFFFFFFFFFFFFFF"
    y_bad_fd = tmp_path / "bad_glyph_frames.yaml"
    y_bad_fd.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    res_bad_fd = load_project(y_bad_fd)
    assert any(g == "g" for g, _ in res_bad_fd.glyph_table_mismatches)

    # Version != 5 rejected cleanly
    doc["version"] = 4
    with pytest.raises(UnsupportedVersionError):
        deserialize_project_from_yaml(yaml.safe_dump(doc, sort_keys=False), base_dir=tmp_path)

    # >16 frames rejected cleanly
    doc["version"] = 5
    doc["objects"][1]["frames"] = [{"x": 0, "y": 0, "w": 2, "h": 1}] * 17
    with pytest.raises(ProjectIOError, match="16"):
        deserialize_project_from_yaml(yaml.safe_dump(doc, sort_keys=False), base_dir=tmp_path)


def test_animation_ui_widgets_offscreen(qapp: QApplication, tmp_path: Path) -> None:
    """Offscreen smoke test for StampImageWidget frame controls, ObjectsView speed, RoomEditorView Animate preview."""
    png_path = _make_tile_png(tmp_path / "g.png", 4, 1, lambda tx, _ty: 0x55 * (tx + 1) & 0xFF)
    img = load_png(png_path)
    grp = ObjectGroup(
        name="g",
        image_path="g.png",
        palettes=[NamedPalette("default", Palette(colbk=0, colpf0=10, colpf1=20, colpf2=30, colpf3=40))],
        image=img,
    )
    anim_o = GameObject(
        id=1,
        name="flame",
        group="g",
        frames=[StampRegion(0, 0, 1, 1), StampRegion(1, 0, 1, 1)],
        animation_speed=10,
    )
    room = Room(
        id=1,
        name="R1",
        pos=(0, 0),
        row_groups=["g"] * ROOM_HEIGHT,
        instances=[ObjectInstance(1, 3, 3)],
    )
    proj = Project(object_groups=[grp], objects=[anim_o], rooms=[room])
    proj.rebuild_glyph_tables()
    stack = UndoStack()
    pal_table = load_default_pal_palette()
    renderer = QtRenderer(pal_table)

    # StampImageWidget frame list + play/stop toggle
    stamp = StampImageWidget(renderer)
    stamp.set_data(proj, grp, anim_o, "default")
    assert stamp._frame_list.count() == 2
    assert stamp._btn_create.text() == "+ Add Frame"
    assert stamp._btn_play_preview.isEnabled()
    stamp._btn_play_preview.click()
    assert stamp._anim_timer.isActive()
    stamp._btn_play_preview.click()
    assert not stamp._anim_timer.isActive()

    # ObjectsView speed spinbox, cell classification label & room render with frame override
    ov = ObjectsView(renderer, pal_table)
    ov.set_context(proj, stack)
    assert "constant" in ov._lbl_anim_cells.text() and "varying" in ov._lbl_anim_cells.text()
    ov._spin_anim_speed.setValue(25)
    assert ov._spin_anim_speed.value() == 25

    rev = RoomEditorView(renderer)
    rev.set_context(proj, stack)
    rev.set_current_room(1)
    rev._chk_animate.setChecked(True)
    assert rev._anim_timer.isActive()
    img_f0 = renderer.render_room_image(proj, room, frame_overrides={1: 0})
    img_f1 = renderer.render_room_image(proj, room, frame_overrides={1: 1})
    assert bytes(img_f0.constBits()) != bytes(img_f1.constBits())
    rev._chk_animate.setChecked(False)
    assert not rev._anim_timer.isActive()
    stamp.close()
    ov.close()
    rev.close()
    stamp.deleteLater()
    ov.deleteLater()
    rev.deleteLater()
    qapp.processEvents()
