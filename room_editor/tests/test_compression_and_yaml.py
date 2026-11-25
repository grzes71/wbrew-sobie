"""T-5, T-6, T-8, T-9: compression, YAML v4 round-trip, versioning, relative PNG paths, row groups."""

from __future__ import annotations

import shutil
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
from room_editor.model.commands import DeleteGroupCommand
from room_editor.model.compression import (
    CompressedPlacement,
    compress_room_instances,
    decompress_placements,
)
from room_editor.model.glyphs import StampRegion
from room_editor.model.palette import NamedPalette, Palette
from room_editor.model.project import (
    ROOM_HEIGHT,
    ROOM_WIDTH,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    RowAssignment,
    Settings,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)


def _create_test_png(path: Path, seed: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 16, 16  # 4x2 glyphs
    img = Image.new("P", (w, h))
    img.putpalette([0, 0, 0, 200, 100, 50, 50, 200, 100, 50, 100, 200] + [0] * (768 - 12))
    pixels = []
    for y in range(h):
        for x in range(w):
            gx = x // 4
            gy = y // 8
            val = ((gx + gy * 4 + seed) % 3) + 1
            pixels.append(val if (x + y) % 2 == 0 else 0)
    img.putdata(pixels)
    img.save(path, format="PNG")
    return path


def _build_full_project(tmp_path: Path) -> Project:
    png_a = _create_test_png(tmp_path / "images" / "walls.png", seed=1)
    png_b = _create_test_png(tmp_path / "images" / "deco.png", seed=2)

    proj = Project(
        settings=Settings(
            default_palette=Palette(colbk=0, colpf0=40, colpf1=202, colpf2=148, colpf3=15)
        ),
        tags=["ladder", "teleport", "wall"],
        object_groups=[
            ObjectGroup(
                name="walls",
                image_path="images/walls.png",
                pixel_mapping=(0, 1, 2, 3),
                palettes=[NamedPalette("default", Palette(colbk=0, colpf0=40, colpf1=202, colpf2=148, colpf3=15))],
                image=load_png(png_a),
            ),
            ObjectGroup(
                name="deco",
                image_path="images/deco.png",
                pixel_mapping=(0, 2, 1, 3),
                palettes=[NamedPalette("default", Palette(colbk=0, colpf0=50, colpf1=180, colpf2=132, colpf3=14))],
                image=load_png(png_b),
            ),
        ],
        objects=[
            GameObject(
                id=1,
                name="ladder",
                group="walls",
                tags=["ladder"],
                non_blockable=True,
                pickable=True,
                colpf3=True,
                region=StampRegion(0, 0, 1, 2),
            ),
            GameObject(
                id=2,
                name="brick",
                group="walls",
                tags=["wall"],
                non_blockable=False,
                region=StampRegion(1, 0, 1, 1),
            ),
            GameObject(
                id=3,
                name="floor",
                group="walls",
                tags=["wall"],
                non_blockable=False,
                region=StampRegion(2, 0, 1, 1),
            ),
            GameObject(
                id=4,
                name="pillar",
                group="deco",
                tags=[],
                non_blockable=False,
                region=StampRegion(0, 0, 2, 2),
            ),
        ],
        rooms=[
            Room(
                id=1,
                name="K1",
                pos=(0, 0),
                row_groups=["walls"] * 12 + ["deco"] * 12,
                instances=[
                    *[ObjectInstance(2, x, 0) for x in range(ROOM_WIDTH)],
                    *[ObjectInstance(3, x, y) for y in (22, 23) for x in range(ROOM_WIDTH)],
                    ObjectInstance(1, 20, 10),
                    ObjectInstance(4, 2, 12),
                    ObjectInstance(4, 4, 12),
                    ObjectInstance(4, 2, 14),
                    ObjectInstance(4, 4, 14),
                ],
            ),
            Room(
                id=2,
                name="K2",
                pos=(1, 0),
                row_groups=["walls"] * ROOM_HEIGHT,
                instances=[ObjectInstance(2, 0, y) for y in range(ROOM_HEIGHT)],
            ),
        ],
        teleports=[
            Teleport(
                a=TeleportEndpoint(room_id=1, x=5, y=10),
                b=TeleportEndpoint(room_id=2, x=30, y=10),
            )
        ],
        start=StartPosition(room_id=1, x=3, y=17),
    )
    return proj


def test_t5_compression_patterns_determinism_and_edge_cases() -> None:
    obj_1x1 = GameObject(id=1, name="dot", group="g", region=StampRegion(0, 0, 1, 1), chars=[[1]])
    obj_2x3 = GameObject(
        id=2,
        name="block",
        group="g",
        region=StampRegion(1, 0, 2, 3),
        chars=[[1, 2], [3, 4], [5, 6]],
    )
    objs = {1: obj_1x1, 2: obj_2x3}

    empty_room = Room(id=1, name="Empty")
    assert compress_room_instances(empty_room, objs) == []

    full_room = Room(
        id=2,
        name="Full",
        instances=[ObjectInstance(1, x, y) for y in range(ROOM_HEIGHT) for x in range(ROOM_WIDTH)],
    )
    comp_full = compress_room_instances(full_room, objs)
    assert comp_full == [CompressedPlacement(object_id=1, x=0, y=0, repeat_x=40, repeat_y=24)]
    assert len(decompress_placements(comp_full, objs)) == 40 * 24

    # Vertical run of full room height (24)
    vert_room = Room(
        id=5,
        name="Vert24",
        instances=[ObjectInstance(1, 0, y) for y in range(ROOM_HEIGHT)],
    )
    assert compress_room_instances(vert_room, objs) == [
        CompressedPlacement(object_id=1, x=0, y=0, repeat_x=1, repeat_y=24)
    ]

    checker_room = Room(
        id=3,
        name="Checker",
        instances=[
            ObjectInstance(1, x, y)
            for y in range(6)
            for x in range(6)
            if (x + y) % 2 == 0
        ],
    )
    comp_checker = compress_room_instances(checker_room, objs)
    assert len(comp_checker) == 18
    assert all(e.repeat_x == 1 and e.repeat_y == 1 for e in comp_checker)

    multi_room = Room(
        id=4,
        name="Multi",
        instances=[ObjectInstance(2, x * 2, y * 3) for y in range(2) for x in range(3)]
        + [ObjectInstance(1, x, 10) for x in range(10)],
    )
    comp_multi = compress_room_instances(multi_room, objs)
    assert CompressedPlacement(object_id=2, x=0, y=0, repeat_x=3, repeat_y=2) in comp_multi
    assert CompressedPlacement(object_id=1, x=0, y=10, repeat_x=10, repeat_y=1) in comp_multi
    expanded = decompress_placements(comp_multi, objs)
    assert sorted((i.object_id, i.x, i.y) for i in expanded) == sorted(
        (i.object_id, i.x, i.y) for i in multi_room.instances
    )

    reversed_room = Room(id=4, name="Multi", instances=list(reversed(multi_room.instances)))
    assert compress_room_instances(reversed_room, objs) == comp_multi


def test_t6_yaml_v3_round_trip_and_keywords(tmp_path: Path) -> None:
    proj = _build_full_project(tmp_path)
    proj.rooms.append(
        Room(
            id=3,
            name="Full40x24",
            pos=(2, 0),
            row_groups=["walls"] * ROOM_HEIGHT,
            instances=[ObjectInstance(2, x, y) for y in range(ROOM_HEIGHT) for x in range(ROOM_WIDTH)],
        )
    )
    yaml_path = tmp_path / "world.yaml"
    save_project(proj, yaml_path)
    first_text = yaml_path.read_text(encoding="utf-8")

    assert "version: 4" in first_text
    assert "repeat-x:" in first_text
    assert "repeat-y: 24" in first_text
    assert "repeat-xy: [40, 24]" in first_text
    assert "glyphs:" in first_text
    assert "pixel_mapping:" in first_text

    loaded = load_project(yaml_path)
    assert loaded.missing_images == []
    assert loaded.invalid_images == []
    assert loaded.glyph_table_mismatches == []
    assert loaded.project == proj
    for grp in proj.object_groups:
        assert loaded.project.get_group(grp.name).glyph_table == grp.glyph_table

    yaml_path_2 = tmp_path / "world_resaved.yaml"
    save_project(loaded.project, yaml_path_2)
    second_text = yaml_path_2.read_text(encoding="utf-8")
    assert first_text == second_text


def test_t8_version_rejection_relative_png_paths_and_glyph_consistency(tmp_path: Path) -> None:
    # Version 1, 2, 3, 99, and missing version are all rejected
    for bad_ver in (1, 2, 3, 99):
        with pytest.raises(UnsupportedVersionError, match="version"):
            deserialize_project_from_yaml(f"version: {bad_ver}\nrooms: []\n")

    with pytest.raises(UnsupportedVersionError, match="missing"):
        deserialize_project_from_yaml("rooms: []\n")

    # Save project + PNGs inside dir_a, then move directory to dir_b
    dir_a = tmp_path / "proj_a"
    dir_a.mkdir()
    proj = _build_full_project(dir_a)
    save_project(proj, dir_a / "game.yaml")

    dir_b = tmp_path / "moved_location" / "proj_b"
    shutil.move(str(dir_a), str(dir_b))

    res = load_project(dir_b / "game.yaml")
    assert res.missing_images == []
    assert res.invalid_images == []
    assert res.glyph_table_mismatches == []
    assert res.project.get_group("walls").image is not None
    assert res.project.get_group("deco").image is not None
    assert res.project.get_group("walls").glyph_table.used_count > 0

    # Mutate stored glyphs in YAML -> consistency check flags mismatch and recomputes from PNG
    raw_doc = yaml.safe_load((dir_b / "game.yaml").read_text(encoding="utf-8"))
    raw_doc["object_groups"][0]["glyphs"][0]["data"] = "FFFFFFFFFFFFFFFF"
    mutated_yaml = yaml.safe_dump(raw_doc, sort_keys=False)
    mismatch_res = deserialize_project_from_yaml(mutated_yaml, base_dir=dir_b)
    assert len(mismatch_res.glyph_table_mismatches) == 1
    assert mismatch_res.glyph_table_mismatches[0][0] == "walls"
    assert (
        mismatch_res.project.get_group("walls").glyph_table
        == res.project.get_group("walls").glyph_table
    )


def test_t9_row_groups_default_individual_and_group_deletion(tmp_path: Path) -> None:
    proj = _build_full_project(tmp_path)
    r = Room(id=10, name="R10", pos=(3, 3))
    r.set_all_row_groups("walls", "default")
    assert len(r.row_groups) == 24
    assert r.row_groups == [RowAssignment("walls", "default")] * ROOM_HEIGHT

    r.set_row_group(5, "deco", "default")
    r.set_row_group(23, "deco", "default")
    assert r.row_groups[5] == RowAssignment("deco", "default")
    assert r.row_groups[23] == RowAssignment("deco", "default")
    assert r.row_groups[4] == RowAssignment("walls", "default")

    r.set_row_range_group(12, 14, "deco", "default")
    assert r.row_groups[12:15] == [RowAssignment("deco", "default")] * 3

    proj.rooms.append(r)

    yaml_text = serialize_project_to_yaml(proj)
    assert "row_groups: [walls]" in yaml_text
    loaded = deserialize_project_from_yaml(yaml_text, base_dir=tmp_path)
    assert len(loaded.project.get_room(10).row_groups) == 24
    assert loaded.project.get_room(10).row_groups == r.row_groups

    # Reject row_groups lists of wrong lengths (20 or 25)
    for bad_len in (20, 25):
        bad_doc = yaml.safe_load(yaml_text)
        bad_doc["rooms"][0]["row_groups"] = ["walls"] * bad_len
        with pytest.raises(ProjectIOError, match="row_groups"):
            deserialize_project_from_yaml(yaml.safe_dump(bad_doc, sort_keys=False), base_dir=tmp_path)

    cmd = DeleteGroupCommand(proj, "deco", fallback_group="walls", fallback_palette="default")
    cmd.execute()
    assert proj.get_group("deco") is None
    assert all(rg.group != "deco" for rg in proj.get_room(10).row_groups)
    assert proj.get_object(4).group == "walls"

    cmd.undo()
    assert proj.get_group("deco") is not None
    assert proj.get_room(10).row_groups[5] == RowAssignment("deco", "default")
    assert proj.get_object(4).group == "deco"


def test_non_blockable_z_order_compression_and_yaml_round_trip(tmp_path: Path) -> None:
    png_w = _create_test_png(tmp_path / "images" / "w.png", seed=3)

    proj = Project(
        object_groups=[ObjectGroup(name="w", image_path="images/w.png", image=load_png(png_w))],
        objects=[
            GameObject(id=1, name="wall", group="w", non_blockable=False, region=StampRegion(0, 0, 1, 1)),
            GameObject(id=2, name="bg_a", group="w", non_blockable=True, region=StampRegion(1, 0, 1, 1)),
            GameObject(id=3, name="bg_b", group="w", non_blockable=True, region=StampRegion(2, 0, 1, 1)),
        ],
        rooms=[
            Room(
                id=1,
                name="K1",
                pos=(0, 0),
                row_groups=["w"] * ROOM_HEIGHT,
                instances=[
                    ObjectInstance(2, 5, 5),
                    ObjectInstance(2, 6, 5),
                    ObjectInstance(2, 7, 5),
                    ObjectInstance(3, 6, 5),
                    ObjectInstance(1, 0, 0),
                    ObjectInstance(2, 6, 5),
                ],
            )
        ],
        start=StartPosition(room_id=1, x=1, y=1),
    )

    yaml_path = tmp_path / "zorder.yaml"
    save_project(proj, yaml_path)
    text_1 = yaml_path.read_text(encoding="utf-8")

    # Section 'rooms:' should emit blockable object 1 before non-blockable 2/3
    rooms_section = text_1[text_1.index("rooms:"):]
    assert rooms_section.index("object: 1") < rooms_section.index("object: 2")
    assert "repeat-x: 3" in rooms_section

    loaded = load_project(yaml_path)
    assert loaded.project == proj
    assert loaded.project.compose_room(loaded.project.rooms[0])[5][6] == proj.get_object(2).chars[0][0]

    yaml_path_2 = tmp_path / "zorder_2.yaml"
    save_project(loaded.project, yaml_path_2)
    assert yaml_path_2.read_text(encoding="utf-8") == text_1

    proj_swapped = Project(
        object_groups=list(proj.object_groups),
        objects=list(proj.objects),
        rooms=[
            Room(
                id=1,
                name="K1",
                pos=(0, 0),
                row_groups=["w"] * ROOM_HEIGHT,
                instances=[
                    ObjectInstance(1, 0, 0),
                    ObjectInstance(2, 5, 5),
                    ObjectInstance(2, 6, 5),
                    ObjectInstance(2, 7, 5),
                    ObjectInstance(2, 6, 5),
                    ObjectInstance(3, 6, 5),
                ],
            )
        ],
        start=StartPosition(room_id=1, x=1, y=1),
    )
    assert proj_swapped != proj
    assert serialize_project_to_yaml(proj_swapped) != text_1

    tiled_room = Room(
        id=2,
        name="Tiled",
        row_groups=["w"] * ROOM_HEIGHT,
        instances=[
            ObjectInstance(2, 0, 0),
            ObjectInstance(2, 1, 0),
            ObjectInstance(2, 0, 1),
            ObjectInstance(2, 1, 1),
        ],
    )
    comp = compress_room_instances(tiled_room, {o.id: o for o in proj.objects})
    assert comp == [CompressedPlacement(object_id=2, x=0, y=0, repeat_x=2, repeat_y=2)]
    assert decompress_placements(comp, {o.id: o for o in proj.objects}) == tiled_room.instances
