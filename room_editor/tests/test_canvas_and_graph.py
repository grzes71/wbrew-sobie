"""T-2, T-3, T-4, T-10: grid snapping, adjacency, room groups, teleports, passages, w*h <= 255."""

from __future__ import annotations

import pytest

from room_editor.model.commands import DeleteRoomCommand, UndoStack
from room_editor.model.glyphs import IndexedImage, StampRegion
from room_editor.model.graph import (
    can_move_rooms,
    can_place_room_at,
    compute_edge_passages,
    compute_room_groups,
    get_adjacent_rooms,
    merge_passage_segments,
    snap_to_grid,
)
from room_editor.model.project import (
    MAX_OBJECT_CELLS,
    ROOM_HEIGHT,
    ROOM_WIDTH,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)


def _base_project() -> Project:
    w, h = 12, 16  # 3x2 glyphs
    buf = bytearray(w * h)
    # Mark (0,0), (2,0), (0,1), (1,1) non-empty; leave (1,0) empty for 2x2 arch hole!
    for gy in range(2):
        for gx in range(3):
            if (gx, gy) == (1, 0):
                continue
            for py in range(8):
                for px in range(4):
                    buf[(gy * 8 + py) * w + (gx * 4 + px)] = (gx + gy) % 3 + 1
    img = IndexedImage(width=w, height=h, pixels=bytes(buf))
    return Project(object_groups=[ObjectGroup(name="walls", image_path="w.png", image=img)])


def test_t2_grid_snapping_and_adjacency() -> None:
    assert snap_to_grid(155.0, 90.0, 160.0, 96.0) == (1, 1)
    assert snap_to_grid(-10.0, 10.0, 160.0, 96.0) == (0, 0)

    proj = _base_project()
    r1 = Room(id=1, name="R1", pos=(0, 0))
    r2 = Room(id=2, name="R2", pos=(1, 0))
    r3 = Room(id=3, name="R3", pos=(0, 1))
    proj.rooms.extend([r1, r2, r3])

    adj1 = get_adjacent_rooms(proj, r1)
    assert set(adj1.keys()) == {"right", "bottom"}
    assert adj1["right"].id == 2
    assert adj1["bottom"].id == 3

    assert not can_place_room_at(proj, 1, 0)
    assert can_place_room_at(proj, 1, 0, ignore_room_ids={2})
    assert not can_move_rooms(proj, {1}, 1, 0)
    assert can_move_rooms(proj, {1}, -1, 0)


def test_t3_room_group_computation_and_move_recomputation() -> None:
    proj = _base_project()
    r1 = Room(id=1, name="R1", pos=(0, 0))
    r2 = Room(id=2, name="R2", pos=(1, 0))
    r3 = Room(id=3, name="R3", pos=(5, 5))
    r4 = Room(id=4, name="R4", pos=(10, 10))
    proj.rooms.extend([r1, r2, r3, r4])

    groups = compute_room_groups(proj)
    assert groups == [[1, 2], [3], [4]]

    r3.pos = (2, 0)
    assert compute_room_groups(proj) == [[1, 2, 3], [4]]

    r1.pos = (-2, 0)
    assert compute_room_groups(proj) == [[1], [2, 3], [4]]


def test_t4_teleports_bidirectional_same_group_same_room_and_delete_room() -> None:
    proj = _base_project()
    r1 = Room(id=1, name="R1", pos=(0, 0))
    r2 = Room(id=2, name="R2", pos=(1, 0))
    r3 = Room(id=3, name="R3", pos=(5, 0))
    proj.rooms.extend([r1, r2, r3])
    proj.start = StartPosition(room_id=1, x=2, y=2)

    tp_same_room = Teleport(
        a=TeleportEndpoint(room_id=1, x=3, y=4),
        b=TeleportEndpoint(room_id=1, x=30, y=15),
    )
    tp_same_group = Teleport(
        a=TeleportEndpoint(room_id=1, x=5, y=5),
        b=TeleportEndpoint(room_id=2, x=10, y=10),
    )
    tp_cross_group = Teleport(
        a=TeleportEndpoint(room_id=2, x=8, y=8),
        b=TeleportEndpoint(room_id=3, x=9, y=9),
    )
    proj.teleports.extend([tp_same_room, tp_same_group, tp_cross_group])

    stack = UndoStack()
    stack.push_and_execute(DeleteRoomCommand(proj, 1))
    assert proj.get_room(1) is None
    assert proj.teleports == [tp_cross_group]
    assert proj.start is None

    stack.undo()
    assert proj.get_room(1) is not None
    assert proj.teleports == [tp_same_room, tp_same_group, tp_cross_group]
    assert proj.start == StartPosition(room_id=1, x=2, y=2)


def test_t10_passage_visualization_and_object_size_limit() -> None:
    proj = _base_project()
    wall = GameObject(id=1, name="wall", group="walls", non_blockable=False, region=StampRegion(0, 0, 1, 1))
    ladder = GameObject(id=2, name="ladder", group="walls", non_blockable=True, region=StampRegion(2, 0, 1, 1))
    arch = GameObject(id=3, name="arch", group="walls", non_blockable=False, region=StampRegion(0, 0, 2, 2))
    proj.objects.extend([wall, ladder, arch])
    proj.rebuild_glyph_tables()

    assert arch.chars[0][1] == 0

    r1 = Room(id=1, name="R1", pos=(0, 0))
    r2 = Room(id=2, name="R2", pos=(1, 0))
    proj.rooms.extend([r1, r2])

    assert compute_edge_passages(proj, r1, r2) == list(range(24))

    for y in range(5):
        r1.instances.append(ObjectInstance(object_id=1, x=ROOM_WIDTH - 1, y=y))
    r2.instances.append(ObjectInstance(object_id=2, x=0, y=2))
    r2.instances.append(ObjectInstance(object_id=1, x=0, y=10))
    r1.instances.append(ObjectInstance(object_id=3, x=ROOM_WIDTH - 2, y=12))

    open_rows = compute_edge_passages(proj, r1, r2)
    assert 0 not in open_rows
    assert 4 not in open_rows
    assert 2 not in open_rows
    assert 10 not in open_rows
    assert 12 in open_rows
    assert 13 not in open_rows
    assert 23 in open_rows
    assert merge_passage_segments(open_rows) == [(5, 9), (11, 12), (14, 23)]

    # Blocking row 23 (bottom-most row of 24-cell edge) closes row 23 passage
    r1.instances.append(ObjectInstance(object_id=1, x=ROOM_WIDTH - 1, y=ROOM_HEIGHT - 1))
    open_rows_2 = compute_edge_passages(proj, r1, r2)
    assert 23 not in open_rows_2
    assert merge_passage_segments(open_rows_2) == [(5, 9), (11, 12), (14, 22)]
    r1.instances.pop()  # clear bottom-right corner before checking r1-r3 bottom edge

    r3 = Room(id=3, name="R3", pos=(0, 1))
    proj.rooms.append(r3)
    r1.instances.append(ObjectInstance(object_id=2, x=15, y=ROOM_HEIGHT - 1))
    r1.instances.append(ObjectInstance(object_id=2, x=15, y=ROOM_HEIGHT - 1))
    assert compute_edge_passages(proj, r1, r3) == list(range(ROOM_WIDTH))

    r1.instances.append(ObjectInstance(object_id=1, x=15, y=ROOM_HEIGHT - 1))
    passages_1_3 = compute_edge_passages(proj, r1, r3)
    assert 15 not in passages_1_3
    assert len(passages_1_3) == ROOM_WIDTH - 1

    # w * h <= 255 limit enforcement via check_region_glyph_budget
    big_img = IndexedImage(width=20 * 4, height=20 * 8, pixels=bytes([1] * (20 * 4 * 20 * 8)))
    proj.object_groups.append(ObjectGroup(name="big", image_path="b.png", image=big_img))
    assert proj.check_region_glyph_budget("big", StampRegion(0, 0, 15, 17)).cell_count_valid
    assert proj.check_region_glyph_budget("big", StampRegion(0, 0, 15, 17)).ok
    assert MAX_OBJECT_CELLS == 255
    assert not proj.check_region_glyph_budget("big", StampRegion(0, 0, 16, 16)).ok
