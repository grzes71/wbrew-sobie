"""T-5, T-6, T-8, T-9: compression, round-trip YAML, versioning, relative .fnt paths, row groups."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from room_editor.io.yaml_io import (
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
from room_editor.model.palette import Palette
from room_editor.model.project import (
    ROOM_HEIGHT,
    ROOM_WIDTH,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    Settings,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)


def _sample_fnt(seed: int = 1) -> bytes:
    return bytes(((i + seed) & 0xFF) for i in range(1024))


def _build_full_project(font_rel_a: str = "fonts/walls.fnt", font_rel_b: str = "fonts/deco.fnt") -> Project:
    proj = Project(
        settings=Settings(default_palette=Palette(colbk=0, colpf0=40, colpf1=202, colpf2=148, colpf3=15)),
        tags=["ladder", "teleport", "wall"],
        object_groups=[
            ObjectGroup(
                name="walls",
                charset_path=font_rel_a,
                palette=Palette(colbk=0, colpf0=40, colpf1=202, colpf2=148, colpf3=15),
            ),
            ObjectGroup(
                name="deco",
                charset_path=font_rel_b,
                palette=Palette(colbk=0, colpf0=50, colpf1=180, colpf2=132, colpf3=14),
            ),
        ],
        objects=[
            GameObject(id=1, name="ladder", group="walls", tags=["ladder"], non_blockable=True, w=1, h=3, chars=[[34], [34], [34]]),
            GameObject(id=2, name="brick", group="walls", tags=["wall"], non_blockable=False, w=1, h=1, chars=[[12]]),
            GameObject(id=3, name="floor", group="walls", tags=["wall"], non_blockable=False, w=1, h=1, chars=[[15]]),
            GameObject(id=4, name="pillar", group="deco", tags=[], non_blockable=False, w=2, h=2, chars=[[10, 11], [12, 13]]),
        ],
        rooms=[
            Room(
                id=1,
                name="K1",
                pos=(0, 0),
                row_groups=["walls"] * 10 + ["deco"] * 10,
                instances=[
                    *[ObjectInstance(2, x, 0) for x in range(ROOM_WIDTH)],  # repeat-x: 40
                    *[ObjectInstance(3, x, y) for y in (18, 19) for x in range(ROOM_WIDTH)],  # repeat-xy: [40, 2]
                    ObjectInstance(1, 20, 10),  # single 1x3
                    ObjectInstance(4, 2, 12),
                    ObjectInstance(4, 4, 12),
                    ObjectInstance(4, 2, 14),
                    ObjectInstance(4, 4, 14),  # 2x2 object tiled 2x2 -> repeat-xy: [2, 2]
                ],
            ),
            Room(
                id=2,
                name="K2",
                pos=(1, 0),
                row_groups=["walls"] * ROOM_HEIGHT,
                instances=[ObjectInstance(2, 0, y) for y in range(5)],  # repeat-y: 5
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
    obj_1x1 = GameObject(id=1, name="dot", group="g", w=1, h=1, chars=[[1]])
    obj_2x3 = GameObject(id=2, name="block", group="g", w=2, h=3, chars=[[1, 2], [3, 4], [5, 6]])
    objs = {1: obj_1x1, 2: obj_2x3}

    # Empty room
    empty_room = Room(id=1, name="Empty")
    assert compress_room_instances(empty_room, objs) == []

    # Full 40x20 room filled with 1x1
    full_room = Room(
        id=2,
        name="Full",
        instances=[ObjectInstance(1, x, y) for y in range(ROOM_HEIGHT) for x in range(ROOM_WIDTH)],
    )
    comp_full = compress_room_instances(full_room, objs)
    assert comp_full == [CompressedPlacement(object_id=1, x=0, y=0, repeat_x=40, repeat_y=20)]
    assert len(decompress_placements(comp_full, objs)) == 800

    # Checkerboard (no adjacent pairs) -> every instance stays single
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

    # Larger object 2x3 tiled in 3x2 grid (step = 2, 3) + horizontal repeat-x
    multi_room = Room(
        id=4,
        name="Multi",
        instances=[
            ObjectInstance(2, x * 2, y * 3) for y in range(2) for x in range(3)
        ]
        + [ObjectInstance(1, x, 10) for x in range(10)],
    )
    comp_multi = compress_room_instances(multi_room, objs)
    assert CompressedPlacement(object_id=2, x=0, y=0, repeat_x=3, repeat_y=2) in comp_multi
    assert CompressedPlacement(object_id=1, x=0, y=10, repeat_x=10, repeat_y=1) in comp_multi
    expanded = decompress_placements(comp_multi, objs)
    assert sorted((i.object_id, i.x, i.y) for i in expanded) == sorted(
        (i.object_id, i.x, i.y) for i in multi_room.instances
    )

    # Determinism regardless of input instance ordering
    reversed_room = Room(id=4, name="Multi", instances=list(reversed(multi_room.instances)))
    assert compress_room_instances(reversed_room, objs) == comp_multi


def test_t6_yaml_round_trip_and_keywords(tmp_path: Path) -> None:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    (fonts_dir / "walls.fnt").write_bytes(_sample_fnt(1))
    (fonts_dir / "deco.fnt").write_bytes(_sample_fnt(2))

    proj = _build_full_project()
    yaml_path = tmp_path / "world.yaml"
    save_project(proj, yaml_path)
    first_bytes = yaml_path.read_text(encoding="utf-8")

    assert "repeat-x:" in first_bytes
    assert "repeat-y:" in first_bytes
    assert "repeat-xy:" in first_bytes

    loaded = load_project(yaml_path)
    assert loaded.missing_charsets == []
    assert loaded.project == proj

    yaml_path_2 = tmp_path / "world_resaved.yaml"
    save_project(loaded.project, yaml_path_2)
    second_bytes = yaml_path_2.read_text(encoding="utf-8")
    assert first_bytes == second_bytes


def test_t8_version_rejection_and_relocatable_relative_fnt_paths(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedVersionError, match="version"):
        deserialize_project_from_yaml("version: 99\nrooms: []\n")

    with pytest.raises(UnsupportedVersionError, match="missing"):
        deserialize_project_from_yaml("rooms: []\n")

    # Save project + fonts inside dir_a, then move whole directory to dir_b
    dir_a = tmp_path / "proj_a"
    (dir_a / "fonts").mkdir(parents=True)
    (dir_a / "fonts" / "walls.fnt").write_bytes(_sample_fnt(7))
    (dir_a / "fonts" / "deco.fnt").write_bytes(_sample_fnt(8))

    proj = _build_full_project()
    save_project(proj, dir_a / "game.yaml")

    dir_b = tmp_path / "moved_location" / "proj_b"
    shutil.move(str(dir_a), str(dir_b))

    res = load_project(dir_b / "game.yaml")
    assert res.missing_charsets == []
    assert res.project.get_group("walls").charset is not None
    assert res.project.get_group("deco").charset is not None
    assert res.project.get_group("walls").charset.raw == _sample_fnt(7)


def test_t9_row_groups_default_individual_and_group_deletion() -> None:
    proj = _build_full_project()
    r = Room(id=10, name="R10", pos=(3, 3))
    r.set_all_row_groups("walls")
    assert r.row_groups == ["walls"] * ROOM_HEIGHT

    r.set_row_group(5, "deco")
    assert r.row_groups[5] == "deco"
    assert r.row_groups[4] == "walls"

    r.set_row_range_group(12, 14, "deco")
    assert r.row_groups[12:15] == ["deco", "deco", "deco"]

    proj.rooms.append(r)

    # Round-trip preserves single-group compression ([walls]) and 20-element mixed list
    yaml_text = serialize_project_to_yaml(proj)
    assert "row_groups: [walls]" in yaml_text
    loaded = deserialize_project_from_yaml(yaml_text)
    assert loaded.project.get_room(10).row_groups == r.row_groups

    # Deleting group "deco" updates room rows & objects cleanly and restores on undo
    cmd = DeleteGroupCommand(proj, "deco", fallback_group="walls")
    cmd.execute()
    assert proj.get_group("deco") is None
    assert "deco" not in proj.get_room(10).row_groups
    assert proj.get_object(4).group == "walls"

    cmd.undo()
    assert proj.get_group("deco") is not None
    assert proj.get_room(10).row_groups[5] == "deco"
    assert proj.get_object(4).group == "deco"


def test_non_blockable_z_order_compression_and_yaml_round_trip(tmp_path: Path) -> None:
    fonts_dir = tmp_path / "fonts"
    fonts_dir.mkdir()
    (fonts_dir / "w.fnt").write_bytes(_sample_fnt(3))

    proj = Project(
        object_groups=[ObjectGroup(name="w", charset_path="fonts/w.fnt")],
        objects=[
            GameObject(id=1, name="wall", group="w", non_blockable=False, w=1, h=1, chars=[[1]]),
            GameObject(id=2, name="bg_a", group="w", non_blockable=True, w=1, h=1, chars=[[20]]),
            GameObject(id=3, name="bg_b", group="w", non_blockable=True, w=1, h=1, chars=[[30]]),
        ],
        rooms=[
            Room(
                id=1,
                name="K1",
                pos=(0, 0),
                row_groups=["w"] * ROOM_HEIGHT,
                instances=[
                    # Interleaved z-order for non-blockables + blockable wall
                    ObjectInstance(2, 5, 5),
                    ObjectInstance(2, 6, 5),
                    ObjectInstance(2, 7, 5),  # consecutive run -> repeat-x: 3
                    ObjectInstance(3, 6, 5),  # overlaps middle of bg_a run!
                    ObjectInstance(1, 0, 0),  # blockable (emitted first)
                    ObjectInstance(2, 6, 5),  # bg_a again AFTER bg_b at (6, 5) -> on top of bg_b!
                ],
            )
        ],
        start=StartPosition(room_id=1, x=1, y=1),
    )

    yaml_path = tmp_path / "zorder.yaml"
    save_project(proj, yaml_path)
    text_1 = yaml_path.read_text(encoding="utf-8")

    # Blockable entry precedes non-blockable entries; non-blockable repeat-x: 3 is preserved
    assert text_1.index("object: 1") < text_1.index("object: 2")
    assert "repeat-x: 3" in text_1

    loaded = load_project(yaml_path)
    assert loaded.project == proj
    assert loaded.project.compose_room(loaded.project.rooms[0])[5][6] == 20

    # Save -> load -> save produces byte-for-byte identical YAML
    yaml_path_2 = tmp_path / "zorder_2.yaml"
    save_project(loaded.project, yaml_path_2)
    assert yaml_path_2.read_text(encoding="utf-8") == text_1

    # Changing z-order of overlapping non-blockables makes projects unequal and YAML differ
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
                    ObjectInstance(3, 6, 5),  # now bg_b is on top of bg_a!
                ],
            )
        ],
        start=StartPosition(room_id=1, x=1, y=1),
    )
    assert proj_swapped != proj
    assert serialize_project_to_yaml(proj_swapped) != text_1

    # Regular 2x2 tiling of non-blockable 1x1 instances compresses to repeat-xy: [2, 2]
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
