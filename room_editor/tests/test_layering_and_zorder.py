"""Tests for layered overlap rules, composition, transparency, z-order, and tools."""

from __future__ import annotations

from room_editor.model.commands import (
    BringToFrontCommand,
    MoveInstanceDownCommand,
    MoveInstanceUpCommand,
    SendToBackCommand,
    UndoStack,
)
from room_editor.model.glyphs import IndexedImage, StampRegion
from room_editor.model.project import (
    ROOM_HEIGHT,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    compose_room,
    compose_room_with_sources,
)
from room_editor.model.tools import (
    compute_fill_placements,
    compute_line_placements,
    compute_rect_placements,
)


def _setup_project() -> tuple[Project, Room]:
    # 10x4 glyph image (40x32 px) with explicit hole cells at (1,0) and (0,1)
    # Row 0: gx=0 non-empty, gx=1 EMPTY, gx=2..9 distinct non-empty
    # Row 1: gx=0..9 distinct non-empty (so a 2x2 at (0,0) has empty top-right (1,0)!)
    # Row 2: gx=0 EMPTY, gx=1 non-empty, gx=2 non-empty, gx=3..9 distinct non-empty
    # Row 3: gx=0..9 non-empty (so a 2x2 at (0,2) has empty top-left? Wait: we need bottom-left empty at (1,2)!)
    # Let's make:
    # (0,0)=val1, (1,0)=EMPTY, (0,1)=val2, (1,1)=val3  -> 2x2 at (0,0) has hole at (1,0) [top-right]!
    # (2,0)=val4, (3,0)=val5, (2,1)=EMPTY, (3,1)=val6  -> 2x2 at (2,0) has hole at (0,1) [bottom-left]!
    # (4,0)=val7, (5,0)=val8, (6,0)=val9, (7,0)=val10, (8,0)=val11, (9,0)=val12
    # (4,1)=EMPTY (so 2x1 at (3,1) is [(3,1)=val6, (4,1)=EMPTY])
    w, h = 10 * 4, 2 * 8
    buf = bytearray(w * h)
    empty_coords = {(1, 0), (2, 1), (4, 1)}
    tile_id = 1
    for gy in range(2):
        for gx in range(10):
            if (gx, gy) in empty_coords:
                continue
            val = ((tile_id - 1) % 3) + 1
            for py in range(8):
                for px in range(4):
                    buf[(gy * 8 + py) * w + (gx * 4 + px)] = val if py != 0 else ((tile_id % 3) + 1)
            buf[(gy * 8) * w + gx * 4] = 1 + (tile_id % 3)
            buf[(gy * 8 + 1) * w + gx * 4] = 1 + ((tile_id // 3) % 3)
            tile_id += 1

    img = IndexedImage(width=w, height=h, pixels=bytes(buf))
    proj = Project(
        object_groups=[ObjectGroup(name="g", image_path="g.png", image=img)],
        objects=[
            GameObject(id=1, name="b1", group="g", non_blockable=False, region=StampRegion(4, 0, 1, 1)),
            GameObject(id=2, name="b_hole", group="g", non_blockable=False, region=StampRegion(0, 0, 2, 2)),
            GameObject(id=3, name="nb_hole", group="g", non_blockable=True, region=StampRegion(2, 0, 2, 2)),
            GameObject(id=4, name="nb1", group="g", non_blockable=True, region=StampRegion(5, 0, 1, 1)),
            GameObject(id=5, name="nb2x1", group="g", non_blockable=True, region=StampRegion(3, 1, 2, 1)),
        ],
        rooms=[Room(id=1, name="R1", pos=(0, 0), row_groups=["g"] * ROOM_HEIGHT)],
    )
    return proj, proj.rooms[0]


def test_overlap_rules_by_non_blockable_flag() -> None:
    proj, room = _setup_project()

    # b_hole (id=2) has hole (0) at (1, 0)
    assert proj.get_object(2).chars[0][1] == 0
    assert proj.can_place_instance(room, 2, 4, 4)[0]
    room.instances.append(ObjectInstance(2, 4, 4))

    # Blockable + blockable overlap on non-zero cell (4,4) -> rejected
    ok, _ = proj.can_place_instance(room, 1, 4, 4)
    assert not ok

    # Blockable + blockable overlapping ONLY through code 0 cell (5,4) -> accepted
    assert proj.can_place_instance(room, 1, 5, 4)[0]
    assert proj.can_place_instance(room, 1, 6, 4)[0]

    # Non-blockable + blockable overlap -> accepted
    assert proj.can_place_instance(room, 4, 4, 4)[0]
    room.instances.append(ObjectInstance(4, 4, 4))

    # Non-blockable + non-blockable overlap -> accepted
    assert proj.can_place_instance(room, 3, 4, 4)[0]
    room.instances.append(ObjectInstance(3, 4, 4))

    # Placing blockable over existing non-blockable (not over another blockable) -> accepted
    assert proj.can_place_instance(room, 1, 5, 4)[0]


def test_compose_room_layers_z_order_and_code0_transparency() -> None:
    proj, room = _setup_project()
    b_hole = proj.get_object(2)
    nb_hole = proj.get_object(3)
    nb1 = proj.get_object(4)
    assert b_hole is not None and nb_hole is not None and nb1 is not None

    nb1_code = nb1.chars[0][0]
    assert nb1_code != 0
    assert nb_hole.chars[1][0] == 0

    room.instances.extend(
        [
            ObjectInstance(4, 5, 4),  # idx 0
            ObjectInstance(4, 5, 5),  # idx 1
            ObjectInstance(3, 5, 4),  # idx 2 (above idx 0 and 1 in non-blockable z-order)
        ]
    )

    grid, sources = compose_room_with_sources(proj, room)
    assert grid[4][5] == nb_hole.chars[0][0] and sources[4][5] == 2
    assert grid[4][6] == nb_hole.chars[0][1] and sources[4][6] == 2
    # Code 0 in nb_hole at (5,5) is transparent, preserving underlying nb1
    assert grid[5][5] == nb1_code and sources[5][5] == 1
    assert grid[5][6] == nb_hole.chars[1][1] and sources[5][6] == 2

    # Insert blockable b_hole at index 0: Layer 2 (blockable) MUST still draw on top of Layer 1
    room.instances.insert(0, ObjectInstance(2, 4, 4))
    grid2, sources2 = compose_room_with_sources(proj, room)
    assert grid2[4][4] == b_hole.chars[0][0] and sources2[4][4] == 0
    # blockable code 0 at (5,4) is transparent over non-blockable!
    assert grid2[4][5] == nb_hole.chars[0][0] and sources2[4][5] == 3
    assert grid2[5][4] == b_hole.chars[1][0] and sources2[5][4] == 0
    assert grid2[5][5] == b_hole.chars[1][1] and sources2[5][5] == 0

    assert proj.find_instance_at(room, 5, 5) == 0
    assert proj.find_instance_at(room, 5, 4) == 3
    assert compose_room(proj, room) == grid2


def test_z_order_commands_and_undo_redo() -> None:
    proj, room = _setup_project()
    proj.objects.append(GameObject(id=6, name="nb_a", group="g", non_blockable=True, region=StampRegion(6, 0, 1, 1)))
    proj.objects.append(GameObject(id=7, name="nb_b", group="g", non_blockable=True, region=StampRegion(7, 0, 1, 1)))
    proj.objects.append(GameObject(id=8, name="nb_c", group="g", non_blockable=True, region=StampRegion(8, 0, 1, 1)))
    proj.rebuild_glyph_tables()

    c6 = proj.get_object(6).chars[0][0]
    c7 = proj.get_object(7).chars[0][0]
    c8 = proj.get_object(8).chars[0][0]

    room.instances = [
        ObjectInstance(6, 2, 2),
        ObjectInstance(1, 9, 9),
        ObjectInstance(7, 2, 2),
        ObjectInstance(8, 2, 2),
    ]
    assert compose_room(proj, room)[2][2] == c8

    stack = UndoStack()

    cmd_front = BringToFrontCommand(proj, room, {0})
    assert cmd_front.has_change
    stack.push_and_execute(cmd_front)
    assert [i.object_id for i in room.instances] == [7, 1, 8, 6]
    assert cmd_front.result_indices == {3}
    assert compose_room(proj, room)[2][2] == c6

    cmd_down = MoveInstanceDownCommand(proj, room, {3})
    stack.push_and_execute(cmd_down)
    assert [i.object_id for i in room.instances] == [7, 1, 6, 8]
    assert cmd_down.result_indices == {2}
    assert compose_room(proj, room)[2][2] == c8

    cmd_up = MoveInstanceUpCommand(proj, room, {0})
    stack.push_and_execute(cmd_up)
    assert [i.object_id for i in room.instances] == [6, 1, 7, 8]
    assert cmd_up.result_indices == {2}

    cmd_back = SendToBackCommand(proj, room, {3})
    stack.push_and_execute(cmd_back)
    assert [i.object_id for i in room.instances] == [8, 1, 6, 7]
    assert cmd_back.result_indices == {0}
    assert compose_room(proj, room)[2][2] == c7

    for _ in range(4):
        stack.undo()
    assert [i.object_id for i in room.instances] == [6, 1, 7, 8]
    assert compose_room(proj, room)[2][2] == c8

    for _ in range(4):
        stack.redo()
    assert [i.object_id for i in room.instances] == [8, 1, 6, 7]


def test_flag_change_blockable_conflict_detection() -> None:
    proj, room = _setup_project()
    room.instances = [
        ObjectInstance(1, 10, 10),
        ObjectInstance(4, 10, 10),
        ObjectInstance(4, 12, 12),
    ]
    conflicts = proj.find_blockable_overlaps_for_object(4)
    assert conflicts == [(1, "R1", 10, 10, 1)]

    room.instances.pop(1)
    assert proj.find_blockable_overlaps_for_object(4) == []


def test_tools_respect_non_blockable_overlap_rules() -> None:
    proj, room = _setup_project()
    b1 = proj.get_object(1)
    nb1 = proj.get_object(4)
    assert b1 is not None and nb1 is not None

    room.instances.append(ObjectInstance(1, 2, 1))
    room.instances.append(ObjectInstance(4, 1, 1))

    b_line = compute_line_placements(proj, room, b1, 0, 1, 3, 1)
    assert [(i.x, i.y) for i in b_line] == [(0, 1), (1, 1), (3, 1)]

    nb_line = compute_line_placements(proj, room, nb1, 0, 1, 3, 1)
    assert [(i.x, i.y) for i in nb_line] == [(0, 1), (1, 1), (2, 1), (3, 1)]

    nb_rect = compute_rect_placements(proj, room, nb1, 1, 1, 2, 2)
    assert len(nb_rect) == 4

    room2 = Room(id=2, name="Box", pos=(1, 0), row_groups=["g"] * ROOM_HEIGHT)
    for x in range(5):
        room2.instances.append(ObjectInstance(1, x, 0))
        room2.instances.append(ObjectInstance(1, x, 4))
    for y in range(1, 4):
        room2.instances.append(ObjectInstance(1, 0, y))
        room2.instances.append(ObjectInstance(1, 4, y))
    room2.instances.append(ObjectInstance(4, 2, 2))
    proj.rooms.append(room2)

    fill_items = compute_fill_placements(proj, room2, nb1, 1, 1)
    assert len(fill_items) == 8
