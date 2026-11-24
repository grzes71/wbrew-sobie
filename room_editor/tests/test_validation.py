"""T-7: Positive and negative tests for every error and warning in Section 3.6."""

from __future__ import annotations

from room_editor.model.charset import CharsetData
from room_editor.model.project import (
    MAX_OBJECTS,
    MAX_ROOMS,
    ROOM_HEIGHT,
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)
from room_editor.model.validation import validate_project


def _valid_project() -> Project:
    cs = CharsetData(b"\x01" * 1024)
    proj = Project()
    proj.object_groups.append(ObjectGroup(name="walls", charset_path="walls.fnt", charset=cs))
    proj.objects.append(
        GameObject(id=1, name="brick", group="walls", non_blockable=False, w=1, h=1, chars=[[1]])
    )
    r1 = Room(
        id=1,
        name="K1",
        pos=(0, 0),
        row_groups=["walls"] * ROOM_HEIGHT,
        instances=[ObjectInstance(object_id=1, x=0, y=0)],
    )
    proj.rooms.append(r1)
    proj.start = StartPosition(room_id=1, x=5, y=5)
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

    proj.start = StartPosition(room_id=1, x=40, y=0)
    assert "START_OUT_OF_BOUNDS" in _codes(proj)


def test_error_instance_bounds_and_overlap() -> None:
    proj = _valid_project()
    proj.objects.append(
        GameObject(id=2, name="wide", group="walls", w=2, h=2, chars=[[1, 1], [1, 1]])
    )
    # Blockable + blockable overlap with (0, 0) brick -> error
    proj.rooms[0].instances.append(ObjectInstance(object_id=2, x=0, y=0))
    assert "INSTANCE_OVERLAP" in _codes(proj)

    # Overlapping only through code 0 cell -> NO error
    proj_zero = _valid_project()
    proj_zero.objects.append(
        GameObject(id=2, name="hole", group="walls", w=2, h=2, chars=[[0, 1], [1, 1]])
    )
    proj_zero.rooms[0].instances.append(ObjectInstance(object_id=2, x=0, y=0))
    assert "INSTANCE_OVERLAP" not in _codes(proj_zero)

    # Non-blockable + blockable and non-blockable + non-blockable overlap -> NO error
    proj_nb = _valid_project()
    proj_nb.objects.extend(
        [
            GameObject(id=2, name="nb_a", group="walls", non_blockable=True, w=1, h=1, chars=[[2]]),
            GameObject(id=3, name="nb_b", group="walls", non_blockable=True, w=1, h=1, chars=[[3]]),
        ]
    )
    proj_nb.rooms[0].instances.extend(
        [
            ObjectInstance(object_id=2, x=0, y=0),
            ObjectInstance(object_id=3, x=0, y=0),
            ObjectInstance(object_id=2, x=4, y=4),
            ObjectInstance(object_id=3, x=4, y=4),
        ]
    )
    assert "INSTANCE_OVERLAP" not in _codes(proj_nb)
    # nb_a at (0,0) is completely hidden by blockable brick at (0,0); nb_a at (4,4) is hidden by nb_b at (4,4)
    assert "HIDDEN_NON_BLOCKABLE_INSTANCE" in _codes(proj_nb)

    # Non-blockable visible at (6, 6) has no hidden warning
    proj_vis = _valid_project()
    proj_vis.objects.append(
        GameObject(id=2, name="nb_vis", group="walls", non_blockable=True, w=1, h=1, chars=[[2]])
    )
    proj_vis.rooms[0].instances.append(ObjectInstance(object_id=2, x=6, y=6))
    assert "HIDDEN_NON_BLOCKABLE_INSTANCE" not in _codes(proj_vis)

    # Out of bounds at x=39 with w=2
    proj2 = _valid_project()
    proj2.objects.append(
        GameObject(id=2, name="wide", group="walls", w=2, h=2, chars=[[1, 1], [1, 1]])
    )
    proj2.rooms[0].instances.append(ObjectInstance(object_id=2, x=39, y=0))
    assert "INSTANCE_OUT_OF_BOUNDS" in _codes(proj2)


def test_error_object_cell_limit_and_missing_group_and_no_charset() -> None:
    proj = _valid_project()
    proj.objects[0].w = 16
    proj.objects[0].h = 16
    assert "OBJECT_TOO_MANY_CELLS" in _codes(proj)

    proj2 = _valid_project()
    proj2.objects[0].group = "nonexistent"
    assert "OBJECT_MISSING_GROUP" in _codes(proj2)

    proj3 = _valid_project()
    proj3.object_groups[0].charset = None
    assert "GROUP_NO_CHARSET" in _codes(proj3)


def test_error_duplicates_and_limits() -> None:
    proj = _valid_project()
    proj.rooms.append(Room(id=1, name="K1", pos=(0, 0), row_groups=["walls"] * ROOM_HEIGHT))
    codes = _codes(proj)
    assert "DUPLICATE_ROOM_ID" in codes
    assert "DUPLICATE_ROOM_NAME" in codes
    assert "DUPLICATE_ROOM_POS" in codes

    proj2 = _valid_project()
    proj2.objects.append(GameObject(id=1, name="brick", group="walls", w=1, h=1, chars=[[1]]))
    codes2 = _codes(proj2)
    assert "DUPLICATE_OBJECT_ID" in codes2
    assert "DUPLICATE_OBJECT_NAME" in codes2

    proj3 = _valid_project()
    proj3.object_groups.append(ObjectGroup(name="walls", charset=CharsetData(b"\x01" * 1024)))
    assert "DUPLICATE_GROUP_NAME" in _codes(proj3)

    # Exceeding 255 rooms / 255 objects
    proj4 = _valid_project()
    proj4.rooms = [
        Room(id=(i % MAX_ROOMS) + 1, name=f"R{i}", pos=(i, 0), row_groups=["walls"] * ROOM_HEIGHT)
        for i in range(MAX_ROOMS + 1)
    ]
    assert "TOO_MANY_ROOMS" in _codes(proj4)

    proj5 = _valid_project()
    proj5.objects = [
        GameObject(id=(i % MAX_OBJECTS) + 1, name=f"O{i}", group="walls", w=1, h=1, chars=[[1]])
        for i in range(MAX_OBJECTS + 1)
    ]
    assert "TOO_MANY_OBJECTS" in _codes(proj5)


def test_error_teleports() -> None:
    proj = _valid_project()
    proj.teleports.append(
        Teleport(
            a=TeleportEndpoint(room_id=99, x=0, y=0),
            b=TeleportEndpoint(room_id=1, x=0, y=20),
        )
    )
    codes = _codes(proj)
    assert "TELEPORT_INVALID_ROOM" in codes
    assert "TELEPORT_OUT_OF_BOUNDS" in codes


def test_warnings_all_four_types_positive_and_negative() -> None:
    proj = _valid_project()
    cs = CharsetData(b"\x02" * 1024)
    proj.object_groups.append(ObjectGroup(name="alt", charset_path="alt.fnt", charset=cs))
    proj.object_groups.append(ObjectGroup(name="unused_grp", charset_path="u.fnt", charset=cs))
    proj.objects.append(GameObject(id=2, name="unused_obj", group="walls", w=1, h=1, chars=[[1]]))

    # Room 2 adjacent to Room 1, blocked along whole shared edge; Room 3 unreachable
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
    assert "OBJECT_ROW_GROUP_MISMATCH" in codes  # brick (walls) at r2 row 0 (alt)
    assert "ADJACENT_NO_PASSAGE" in codes
    assert "UNUSED_OBJECT" in codes
    assert "UNUSED_GROUP" in codes

    # Negative check: connect r3 via teleport, open r1-r2 edge, use all objects/groups
    proj.teleports.append(
        Teleport(a=TeleportEndpoint(1, 1, 1), b=TeleportEndpoint(3, 1, 1))
    )
    r2.instances.pop(0)  # open row 0 edge & remove mismatch on row 0
    r2.row_groups[0] = "walls"
    proj.objects[1].group = "alt"
    r3.row_groups[2] = "alt"
    r3.instances.append(ObjectInstance(2, 2, 2))
    proj.object_groups.pop()  # remove unused_grp
    assert _codes(proj) == set()
