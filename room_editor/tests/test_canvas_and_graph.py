"""T-2, T-3, T-4, T-10: grid snapping, adjacency, room groups, teleports, passages, w*h <= 255."""

from __future__ import annotations

import pytest

from room_editor.model.commands import DeleteRoomCommand, UndoStack
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
    proj = Project()
    proj.object_groups.append(ObjectGroup(name="walls"))
    return proj


def test_t2_grid_snapping_and_adjacency() -> None:
    assert snap_to_grid(155.0, 75.0, 160.0, 80.0) == (1, 1)
    assert snap_to_grid(-10.0, 10.0, 160.0, 80.0) == (0, 0)

    proj = _base_project()
    r1 = Room(id=1, name="R1", pos=(0, 0))
    r2 = Room(id=2, name="R2", pos=(1, 0))
    r3 = Room(id=3, name="R3", pos=(0, 1))
    proj.rooms.extend([r1, r2, r3])

    adj1 = get_adjacent_rooms(proj, r1)
    assert set(adj1.keys()) == {"right", "bottom"}
    assert adj1["right"].id == 2
    assert adj1["bottom"].id == 3

    # Each edge has at most one neighbor and overlap is forbidden
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

    # Move r3 next to r2 -> merges into [1, 2, 3]
    r3.pos = (2, 0)
    assert compute_room_groups(proj) == [[1, 2, 3], [4]]

    # Move r1 away -> [1], [2, 3], [4]
    r1.pos = (-2, 0)
    assert compute_room_groups(proj) == [[1], [2, 3], [4]]


def test_t4_teleports_bidirectional_same_group_same_room_and_delete_room() -> None:
    proj = _base_project()
    r1 = Room(id=1, name="R1", pos=(0, 0))
    r2 = Room(id=2, name="R2", pos=(1, 0))  # same group as R1
    r3 = Room(id=3, name="R3", pos=(5, 0))  # separate group
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
    # Both teleports touching room 1 must be removed; tp_cross_group stays
    assert proj.teleports == [tp_cross_group]
    assert proj.start is None

    # Undo restores room 1, its teleports, and start position
    stack.undo()
    assert proj.get_room(1) is not None
    assert proj.teleports == [tp_same_room, tp_same_group, tp_cross_group]
    assert proj.start == StartPosition(room_id=1, x=2, y=2)


def test_t10_passage_visualization_and_object_size_limit() -> None:
    proj = _base_project()
    wall = GameObject(id=1, name="wall", group="walls", non_blockable=False, w=1, h=1, chars=[[5]])
    ladder = GameObject(id=2, name="ladder", group="walls", non_blockable=True, w=1, h=1, chars=[[6]])
    # Blocking 2x2 object with code 0 at (1, 0) -> transparent cell does NOT block!
    arch = GameObject(
        id=3,
        name="arch",
        group="walls",
        non_blockable=False,
        w=2,
        h=2,
        chars=[[7, 0], [8, 9]],
    )
    proj.objects.extend([wall, ladder, arch])

    r1 = Room(id=1, name="R1", pos=(0, 0))
    r2 = Room(id=2, name="R2", pos=(1, 0))
    proj.rooms.extend([r1, r2])

    # Empty edges -> all 20 rows open
    assert compute_edge_passages(proj, r1, r2) == list(range(ROOM_HEIGHT))

    # Block rows 0..4 on right edge of R1, place non-blockable ladder at row 2 on R2,
    # block row 10 on left edge of R2, place arch at (38, 12) in R1 so row 12 col 39 is code 0!
    for y in range(5):
        r1.instances.append(ObjectInstance(object_id=1, x=ROOM_WIDTH - 1, y=y))
    r2.instances.append(ObjectInstance(object_id=2, x=0, y=2))
    r2.instances.append(ObjectInstance(object_id=1, x=0, y=10))
    r1.instances.append(ObjectInstance(object_id=3, x=ROOM_WIDTH - 2, y=12))

    # Blocked rows: 0,1,2,3,4 (by wall in r1), 10 (by wall in r2), 13 (by arch bottom-right in r1).
    # Row 12 col 39 has arch char 0, so row 12 remains open!
    open_rows = compute_edge_passages(proj, r1, r2)
    assert 0 not in open_rows
    assert 4 not in open_rows
    assert 2 not in open_rows
    assert 10 not in open_rows
    assert 12 in open_rows
    assert 13 not in open_rows
    assert merge_passage_segments(open_rows) == [(5, 9), (11, 12), (14, 19)]

    # Placing non-blockable ladder on free edge leaves passage open, even with two overlapping non-blockables
    r3 = Room(id=3, name="R3", pos=(0, 1))
    proj.rooms.append(r3)
    r1.instances.append(ObjectInstance(object_id=2, x=15, y=ROOM_HEIGHT - 1))
    r1.instances.append(ObjectInstance(object_id=2, x=15, y=ROOM_HEIGHT - 1))
    assert compute_edge_passages(proj, r1, r3) == list(range(ROOM_WIDTH))

    # Placing a blockable wall on the same cell as a non-blockable ladder closes that passage cell
    r1.instances.append(ObjectInstance(object_id=1, x=15, y=ROOM_HEIGHT - 1))
    passages_1_3 = compute_edge_passages(proj, r1, r3)
    assert 15 not in passages_1_3
    assert len(passages_1_3) == ROOM_WIDTH - 1

    # w * h <= 255 limit enforcement
    obj = GameObject(id=4, name="big", group="walls", w=1, h=1, chars=[[1]])
    obj.resize(15, 17)  # 15 * 17 = 255 (max allowed)
    assert obj.cell_count == MAX_OBJECT_CELLS
    with pytest.raises(ValueError):
        obj.resize(16, 16)  # 256 > 255
