"""Tests for layered overlap rules, composition, transparency, z-order, and tools."""

from __future__ import annotations

from room_editor.model.commands import (
    BringToFrontCommand,
    MoveInstanceDownCommand,
    MoveInstanceUpCommand,
    SendToBackCommand,
    UndoStack,
)
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
    proj = Project()
    proj.object_groups.append(ObjectGroup(name="g"))
    # ID 1: blockable 1x1 (char 10)
    # ID 2: blockable 2x2 with code 0 at top-right (0,1)->22, (1,0)->0
    # ID 3: non-blockable 2x2 with code 0 at bottom-left
    # ID 4: non-blockable 1x1 (char 40)
    # ID 5: non-blockable 2x1 with code 0 at (1,0)
    proj.objects.extend(
        [
            GameObject(id=1, name="b1", group="g", non_blockable=False, w=1, h=1, chars=[[10]]),
            GameObject(
                id=2,
                name="b_hole",
                group="g",
                non_blockable=False,
                w=2,
                h=2,
                chars=[[20, 0], [22, 23]],
            ),
            GameObject(
                id=3,
                name="nb_hole",
                group="g",
                non_blockable=True,
                w=2,
                h=2,
                chars=[[30, 31], [0, 33]],
            ),
            GameObject(id=4, name="nb1", group="g", non_blockable=True, w=1, h=1, chars=[[40]]),
            GameObject(id=5, name="nb2x1", group="g", non_blockable=True, w=2, h=1, chars=[[50, 0]]),
        ]
    )
    room = Room(id=1, name="R1", pos=(0, 0), row_groups=["g"] * ROOM_HEIGHT)
    proj.rooms.append(room)
    return proj, room


def test_overlap_rules_by_non_blockable_flag() -> None:
    proj, room = _setup_project()

    # Place blockable b_hole at (4, 4): occupies (4,4), (4,5), (5,5); (5,4) is code 0
    assert proj.can_place_instance(room, 2, 4, 4)[0]
    room.instances.append(ObjectInstance(2, 4, 4))

    # Blockable + blockable overlap on non-zero cell (4,4) -> rejected
    ok, _ = proj.can_place_instance(room, 1, 4, 4)
    assert not ok

    # Blockable + blockable touching or overlapping ONLY through code 0 cell (5,4) -> accepted
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
    # Non-blockable layer:
    # idx 0: nb1 (char 40) at (5, 5)
    # idx 1: nb_hole ([[30, 31], [0, 33]]) at (5, 6)? Wait: put nb_hole at (5, 4) so (5, 5) is code 0!
    # Also put nb1 (char 40) at (5, 4) and (5, 5) below nb_hole:
    # idx 0: nb1 at (5, 4) -> char 40
    # idx 1: nb1 at (5, 5) -> char 40
    # idx 2: nb_hole at (5, 4) -> (5,4)=30 overwrites 40, (6,4)=31, (5,5)=0 MUST NOT overwrite 40!, (6,5)=33
    room.instances.extend(
        [
            ObjectInstance(4, 5, 4),  # idx 0
            ObjectInstance(4, 5, 5),  # idx 1
            ObjectInstance(3, 5, 4),  # idx 2 (above idx 0 and 1 in non-blockable z-order)
        ]
    )

    grid, sources = compose_room_with_sources(proj, room)
    assert grid[4][5] == 30 and sources[4][5] == 2
    assert grid[4][6] == 31 and sources[4][6] == 2
    # Code 0 in nb_hole at (5,5) is transparent, preserving underlying nb1 (40, idx 1)
    assert grid[5][5] == 40 and sources[5][5] == 1
    assert grid[5][6] == 33 and sources[5][6] == 2

    # Now add a blockable object b_hole ([[20, 0], [22, 23]]) at (4, 4), placed BEFORE/AFTER:
    # Even if inserted at index 0 in room.instances, Layer 2 (blockable) MUST draw on top of Layer 1!
    room.instances.insert(0, ObjectInstance(2, 4, 4))
    # Indices shifted by +1: b_hole is 0; nb1(5,4)=1; nb1(5,5)=2; nb_hole(5,4)=3
    # b_hole covers (4,4)=20, (5,4)=0 (transparent -> lets nb_hole's 30 show through!), (4,5)=22, (5,5)=23 (overwrites nb1's 40)
    grid2, sources2 = compose_room_with_sources(proj, room)
    assert grid2[4][4] == 20 and sources2[4][4] == 0
    assert grid2[4][5] == 30 and sources2[4][5] == 3  # blockable code 0 transparent over non-blockable!
    assert grid2[5][4] == 22 and sources2[5][4] == 0
    assert grid2[5][5] == 23 and sources2[5][5] == 0  # blockable overwrites non-blockable!

    # Eraser target (find_instance_at) matches topmost visible instance
    assert proj.find_instance_at(room, 5, 5) == 0  # blockable b_hole
    assert proj.find_instance_at(room, 5, 4) == 3  # non-blockable nb_hole visible through b_hole's code 0
    assert compose_room(proj, room) == grid2


def test_z_order_commands_and_undo_redo() -> None:
    proj, room = _setup_project()
    proj.objects.append(GameObject(id=6, name="nb_a", group="g", non_blockable=True, w=1, h=1, chars=[[61]]))
    proj.objects.append(GameObject(id=7, name="nb_b", group="g", non_blockable=True, w=1, h=1, chars=[[71]]))
    proj.objects.append(GameObject(id=8, name="nb_c", group="g", non_blockable=True, w=1, h=1, chars=[[81]]))

    # Interleave a blockable instance at index 1 to ensure z-order skips across blockables
    room.instances = [
        ObjectInstance(6, 2, 2),  # nb slot 0 -> index 0
        ObjectInstance(1, 9, 9),  # blockable -> index 1
        ObjectInstance(7, 2, 2),  # nb slot 1 -> index 2
        ObjectInstance(8, 2, 2),  # nb slot 2 -> index 3
    ]
    assert compose_room(proj, room)[2][2] == 81

    stack = UndoStack()

    # Bring idx 0 (obj 6) to front -> moves to index 3; others shift down
    cmd_front = BringToFrontCommand(proj, room, {0})
    assert cmd_front.has_change
    stack.push_and_execute(cmd_front)
    assert [i.object_id for i in room.instances] == [7, 1, 8, 6]
    assert cmd_front.result_indices == {3}
    assert compose_room(proj, room)[2][2] == 61

    # Move idx 3 (obj 6) down one step -> swaps with nb slot at index 2 (obj 8)
    cmd_down = MoveInstanceDownCommand(proj, room, {3})
    stack.push_and_execute(cmd_down)
    assert [i.object_id for i in room.instances] == [7, 1, 6, 8]
    assert cmd_down.result_indices == {2}
    assert compose_room(proj, room)[2][2] == 81

    # Move idx 0 (obj 7) up one step -> skips blockable at index 1, swaps with idx 2 (obj 6)
    cmd_up = MoveInstanceUpCommand(proj, room, {0})
    stack.push_and_execute(cmd_up)
    assert [i.object_id for i in room.instances] == [6, 1, 7, 8]
    assert cmd_up.result_indices == {2}

    # Send idx 3 (obj 8) to back -> index 0
    cmd_back = SendToBackCommand(proj, room, {3})
    stack.push_and_execute(cmd_back)
    assert [i.object_id for i in room.instances] == [8, 1, 6, 7]
    assert cmd_back.result_indices == {0}
    assert compose_room(proj, room)[2][2] == 71

    # Undo all 4 steps and redo them
    for _ in range(4):
        stack.undo()
    assert [i.object_id for i in room.instances] == [6, 1, 7, 8]
    assert compose_room(proj, room)[2][2] == 81

    for _ in range(4):
        stack.redo()
    assert [i.object_id for i in room.instances] == [8, 1, 6, 7]


def test_flag_change_blockable_conflict_detection() -> None:
    proj, room = _setup_project()
    # Place blockable obj 1 at (10, 10) and non-blockable obj 4 at (10, 10) and (12, 12)
    room.instances = [
        ObjectInstance(1, 10, 10),
        ObjectInstance(4, 10, 10),
        ObjectInstance(4, 12, 12),
    ]
    conflicts = proj.find_blockable_overlaps_for_object(4)
    assert conflicts == [(1, "R1", 10, 10, 1)]

    # Removing the overlapping instance clears the conflict
    room.instances.pop(1)
    assert proj.find_blockable_overlaps_for_object(4) == []


def test_tools_respect_non_blockable_overlap_rules() -> None:
    proj, room = _setup_project()
    b1 = proj.get_object(1)
    nb1 = proj.get_object(4)
    assert b1 is not None and nb1 is not None

    # Pre-place a blockable wall at (2, 1) and a non-blockable decal at (1, 1)
    room.instances.append(ObjectInstance(1, 2, 1))
    room.instances.append(ObjectInstance(4, 1, 1))

    # Blockable line across (0,1)..(3,1) skips (2,1) blockable wall, DOES overwrite (1,1) non-blockable
    b_line = compute_line_placements(proj, room, b1, 0, 1, 3, 1)
    assert [(i.x, i.y) for i in b_line] == [(0, 1), (1, 1), (3, 1)]

    # Non-blockable line across (0,1)..(3,1) places at ALL 4 cells including over blockable & non-blockable
    nb_line = compute_line_placements(proj, room, nb1, 0, 1, 3, 1)
    assert [(i.x, i.y) for i in nb_line] == [(0, 1), (1, 1), (2, 1), (3, 1)]

    # Non-blockable rect 2x2 at (1,1)..(2,2) places all 4 cells
    nb_rect = compute_rect_placements(proj, room, nb1, 1, 1, 2, 2)
    assert len(nb_rect) == 4

    # Non-blockable fill inside a closed 3x3 blockable box fills 9 cells even over existing nb decals
    room2 = Room(id=2, name="Box", pos=(1, 0), row_groups=["g"] * ROOM_HEIGHT)
    for x in range(5):
        room2.instances.append(ObjectInstance(1, x, 0))
        room2.instances.append(ObjectInstance(1, x, 4))
    for y in range(1, 4):
        room2.instances.append(ObjectInstance(1, 0, y))
        room2.instances.append(ObjectInstance(1, 4, y))
    room2.instances.append(ObjectInstance(4, 2, 2))  # existing nb decal at (2,2)
    proj.rooms.append(room2)

    fill_items = compute_fill_placements(proj, room2, nb1, 1, 1)
    # Places 8 free interior cells (skipping (2,2) which already has nb1 at same anchor)
    assert len(fill_items) == 8
