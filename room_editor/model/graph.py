"""Room grid snapping, adjacency, connected room groups, passages, and reachability."""

from __future__ import annotations

from collections import deque

from room_editor.model.project import ROOM_HEIGHT, ROOM_WIDTH, Project, Room

DIRECTIONS: dict[str, tuple[int, int]] = {
    "left": (-1, 0),
    "right": (1, 0),
    "top": (0, -1),
    "bottom": (0, 1),
}


def snap_to_grid(px: float, py: float, cell_w: float, cell_h: float) -> tuple[int, int]:
    """Snap pixel coordinates to the nearest integer canvas grid cell."""
    if cell_w <= 0 or cell_h <= 0:
        raise ValueError("Grid cell dimensions must be positive.")
    return round(px / cell_w), round(py / cell_h)


def get_adjacent_rooms(project: Project, room: Room) -> dict[str, Room]:
    """Return mapping of direction ('left', 'right', 'top', 'bottom') to neighboring Room."""
    pos_map: dict[tuple[int, int], Room] = {}
    for candidate in project.rooms:
        if candidate.pos not in pos_map:
            pos_map[candidate.pos] = candidate

    rx, ry = room.pos
    neighbors: dict[str, Room] = {}
    for direction, (dx, dy) in DIRECTIONS.items():
        neighbor = pos_map.get((rx + dx, ry + dy))
        if neighbor is not None and neighbor is not room:
            neighbors[direction] = neighbor
    return neighbors


def can_place_room_at(
    project: Project,
    gx: int,
    gy: int,
    ignore_room_ids: set[int] | None = None,
) -> bool:
    """Return True if grid cell (gx, gy) is free (ignoring specified room IDs)."""
    ignored = ignore_room_ids or set()
    for room in project.rooms:
        if room.id in ignored:
            continue
        if room.pos == (gx, gy):
            return False
    return True


def can_move_rooms(
    project: Project,
    room_ids: set[int],
    dx: int,
    dy: int,
) -> bool:
    """Return True if all selected rooms can shift by (dx, dy) without overlapping others."""
    moving_rooms = [r for r in project.rooms if r.id in room_ids]
    if not moving_rooms:
        return False
    occupied_by_static = {
        r.pos for r in project.rooms if r.id not in room_ids
    }
    target_positions: set[tuple[int, int]] = set()
    for r in moving_rooms:
        new_pos = (r.pos[0] + dx, r.pos[1] + dy)
        if new_pos in occupied_by_static or new_pos in target_positions:
            return False
        target_positions.add(new_pos)
    return True


def compute_room_groups(project: Project) -> list[list[int]]:
    """Compute connected components of rooms by 4-neighbor grid adjacency.

    Returns a deterministic list of groups (each a sorted list of room IDs),
    sorted by the smallest room ID in each group.
    """
    pos_to_ids: dict[tuple[int, int], list[int]] = {}
    id_to_pos: dict[int, tuple[int, int]] = {}
    for room in project.rooms:
        pos_to_ids.setdefault(room.pos, []).append(room.id)
        id_to_pos[room.id] = room.pos

    visited: set[int] = set()
    groups: list[list[int]] = []

    for room in sorted(project.rooms, key=lambda r: r.id):
        if room.id in visited:
            continue
        component: list[int] = []
        queue: deque[int] = deque([room.id])
        visited.add(room.id)

        while queue:
            cur_id = queue.popleft()
            component.append(cur_id)
            cx, cy = id_to_pos[cur_id]
            for dx, dy in DIRECTIONS.values():
                for nb_id in pos_to_ids.get((cx + dx, cy + dy), ()):
                    if nb_id not in visited:
                        visited.add(nb_id)
                        queue.append(nb_id)

        component.sort()
        groups.append(component)

    groups.sort(key=lambda g: g[0])
    return groups


def room_group_map(project: Project) -> dict[int, int]:
    """Return mapping from room_id to 0-based computed group index."""
    mapping: dict[int, int] = {}
    for group_idx, room_ids in enumerate(compute_room_groups(project)):
        for room_id in room_ids:
            mapping[room_id] = group_idx
    return mapping


def is_cell_blocking(project: Project, room: Room, x: int, y: int) -> bool:
    """Return True if cell (x, y) contains a blocking object (non_blockable == False)."""
    if not (0 <= x < ROOM_WIDTH and 0 <= y < ROOM_HEIGHT):
        return True
    objects_by_id = {o.id: o for o in project.objects}
    for inst in room.instances:
        obj = objects_by_id.get(inst.object_id)
        if obj is None or obj.non_blockable:
            continue
        dx = x - inst.x
        dy = y - inst.y
        if 0 <= dx < obj.w and 0 <= dy < obj.h:
            if dy < len(obj.chars) and dx < len(obj.chars[dy]) and obj.chars[dy][dx] != 0:
                return True
    return False


def compute_edge_passages(project: Project, room_a: Room, room_b: Room) -> list[int]:
    """Return sorted cell indices along the shared edge where both rooms are non-blocking.

    For left/right adjacency, returns row indices in 0..19.
    For top/bottom adjacency, returns column indices in 0..39.
    Returns [] if rooms are not adjacent.
    """
    dx = room_b.pos[0] - room_a.pos[0]
    dy = room_b.pos[1] - room_a.pos[1]

    if (dx, dy) == (1, 0):  # room_b is to the right of room_a
        return [
            y
            for y in range(ROOM_HEIGHT)
            if not is_cell_blocking(project, room_a, ROOM_WIDTH - 1, y)
            and not is_cell_blocking(project, room_b, 0, y)
        ]
    if (dx, dy) == (-1, 0):  # room_b is to the left of room_a
        return [
            y
            for y in range(ROOM_HEIGHT)
            if not is_cell_blocking(project, room_a, 0, y)
            and not is_cell_blocking(project, room_b, ROOM_WIDTH - 1, y)
        ]
    if (dx, dy) == (0, 1):  # room_b is below room_a
        return [
            x
            for x in range(ROOM_WIDTH)
            if not is_cell_blocking(project, room_a, x, ROOM_HEIGHT - 1)
            and not is_cell_blocking(project, room_b, x, 0)
        ]
    if (dx, dy) == (0, -1):  # room_b is above room_a
        return [
            x
            for x in range(ROOM_WIDTH)
            if not is_cell_blocking(project, room_a, x, 0)
            and not is_cell_blocking(project, room_b, x, ROOM_HEIGHT - 1)
        ]
    return []


def merge_passage_segments(indices: list[int]) -> list[tuple[int, int]]:
    """Collapse sorted contiguous cell indices into inclusive (start, end) intervals."""
    if not indices:
        return []
    sorted_idx = sorted(set(indices))
    segments: list[tuple[int, int]] = []
    start = sorted_idx[0]
    prev = sorted_idx[0]
    for val in sorted_idx[1:]:
        if val == prev + 1:
            prev = val
        else:
            segments.append((start, prev))
            start = val
            prev = val
    segments.append((start, prev))
    return segments


def compute_reachable_rooms(project: Project) -> set[int]:
    """Return IDs of rooms reachable from project.start via adjacency or teleports."""
    if project.start is None:
        return set()
    start_room = project.get_room(project.start.room_id)
    if start_room is None:
        return set()

    rooms_by_id = {r.id: r for r in project.rooms}
    teleport_adj: dict[int, set[int]] = {}
    for tp in project.teleports:
        if tp.a.room_id in rooms_by_id and tp.b.room_id in rooms_by_id:
            teleport_adj.setdefault(tp.a.room_id, set()).add(tp.b.room_id)
            teleport_adj.setdefault(tp.b.room_id, set()).add(tp.a.room_id)

    visited: set[int] = {start_room.id}
    queue: deque[int] = deque([start_room.id])

    while queue:
        cur_id = queue.popleft()
        cur_room = rooms_by_id[cur_id]
        for nb in get_adjacent_rooms(project, cur_room).values():
            if nb.id not in visited:
                visited.add(nb.id)
                queue.append(nb.id)
        for tp_nb in teleport_adj.get(cur_id, ()):
            if tp_nb not in visited:
                visited.add(tp_nb)
                queue.append(tp_nb)

    return visited
