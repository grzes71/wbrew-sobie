"""Pure model geometry helpers for room drawing tools (line, rectangle, fill)."""

from __future__ import annotations

from collections import deque

from room_editor.model.project import (
    ROOM_HEIGHT,
    ROOM_WIDTH,
    GameObject,
    ObjectInstance,
    Project,
    Room,
)


def _bresenham_points(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Return integer grid points along a Bresenham line from (x0, y0) to (x1, y1)."""
    points: list[tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    cx, cy = x0, y0
    while True:
        points.append((cx, cy))
        if cx == x1 and cy == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            cx += sx
        if e2 <= dx:
            err += dx
            cy += sy
    return points


def _can_add_against_occupied(
    obj: GameObject,
    x: int,
    y: int,
    occupied: set[tuple[int, int]],
    placed_anchors: set[tuple[int, int]],
) -> bool:
    if (x, y) in placed_anchors:
        return False
    if x < 0 or y < 0 or x + obj.w > ROOM_WIDTH or y + obj.h > ROOM_HEIGHT:
        return False
    for dx, dy in obj.occupied_offsets():
        if (x + dx, y + dy) in occupied:
            return False
    return True


def _mark_occupied(
    obj: GameObject,
    x: int,
    y: int,
    occupied: set[tuple[int, int]],
    placed_anchors: set[tuple[int, int]],
) -> None:
    placed_anchors.add((x, y))
    for dx, dy in obj.occupied_offsets():
        occupied.add((x + dx, y + dy))


def compute_line_placements(
    project: Project,
    room: Room,
    obj: GameObject,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> list[ObjectInstance]:
    """Compute ObjectInstances along a line from (x0, y0) to (x1, y1).

    Blockable objects respect existing blockable cells; non-blockable objects skip
    room overlap checks and avoid only self-overlap within the same stroke.
    """
    if obj.non_blockable:
        occupied: set[tuple[int, int]] = set()
        placed_anchors: set[tuple[int, int]] = set()
    else:
        occupied = set(project.room_blockable_cells(room).keys())
        placed_anchors = {(i.x, i.y) for i in room.instances if i.object_id == obj.id}

    result: list[ObjectInstance] = []
    for px, py in _bresenham_points(x0, y0, x1, y1):
        if _can_add_against_occupied(obj, px, py, occupied, placed_anchors):
            result.append(ObjectInstance(object_id=obj.id, x=px, y=py))
            _mark_occupied(obj, px, py, occupied, placed_anchors)
    return result


def compute_rect_placements(
    project: Project,
    room: Room,
    obj: GameObject,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> list[ObjectInstance]:
    """Compute tiled ObjectInstances inside a rectangle.

    Blockable objects respect existing blockable cells; non-blockable objects
    ignore existing room overlaps.
    """
    rx0 = max(0, min(x0, x1))
    ry0 = max(0, min(y0, y1))
    rx1 = min(ROOM_WIDTH - 1, max(x0, x1))
    ry1 = min(ROOM_HEIGHT - 1, max(y0, y1))

    step_x = max(1, obj.w)
    step_y = max(1, obj.h)
    if obj.non_blockable:
        occupied: set[tuple[int, int]] = set()
        placed_anchors: set[tuple[int, int]] = set()
    else:
        occupied = set(project.room_blockable_cells(room).keys())
        placed_anchors = {(i.x, i.y) for i in room.instances if i.object_id == obj.id}

    result: list[ObjectInstance] = []
    y = ry0
    while y + obj.h - 1 <= ry1:
        x = rx0
        while x + obj.w - 1 <= rx1:
            if _can_add_against_occupied(obj, x, y, occupied, placed_anchors):
                result.append(ObjectInstance(object_id=obj.id, x=x, y=y))
                _mark_occupied(obj, x, y, occupied, placed_anchors)
            x += step_x
        y += step_y
    return result


def compute_fill_placements(
    project: Project,
    room: Room,
    obj: GameObject,
    start_x: int,
    start_y: int,
) -> list[ObjectInstance]:
    """Flood-fill contiguous space starting at (start_x, start_y) in object steps.

    For blockable objects, stops at existing blockable cells.
    For non-blockable objects, ignores non-blockable overlaps; if started outside
    blockable cells, stops at blockable walls (so interior fills work naturally),
    and if started on a blockable cell, fills across matching cells without error.
    """
    blockable_cells = set(project.room_blockable_cells(room).keys())
    if obj.non_blockable:
        start_on_blockable = any(
            (start_x + dx, start_y + dy) in blockable_cells
            for dx, dy in obj.occupied_offsets()
        )
        occupied: set[tuple[int, int]] = set() if start_on_blockable else set(blockable_cells)
        placed_anchors = {(i.x, i.y) for i in room.instances if i.object_id == obj.id}
    else:
        occupied = set(blockable_cells)
        placed_anchors = {(i.x, i.y) for i in room.instances if i.object_id == obj.id}

    if not _can_add_against_occupied(obj, start_x, start_y, occupied, placed_anchors):
        return []

    step_x = max(1, obj.w)
    step_y = max(1, obj.h)
    visited: set[tuple[int, int]] = {(start_x, start_y)}
    queue: deque[tuple[int, int]] = deque([(start_x, start_y)])
    result: list[ObjectInstance] = []

    while queue:
        cx, cy = queue.popleft()
        if not _can_add_against_occupied(obj, cx, cy, occupied, placed_anchors):
            continue
        result.append(ObjectInstance(object_id=obj.id, x=cx, y=cy))
        _mark_occupied(obj, cx, cy, occupied, placed_anchors)

        for nx, ny in (
            (cx - step_x, cy),
            (cx + step_x, cy),
            (cx, cy - step_y),
            (cx, cy + step_y),
        ):
            if (
                (nx, ny) not in visited
                and 0 <= nx <= ROOM_WIDTH - obj.w
                and 0 <= ny <= ROOM_HEIGHT - obj.h
            ):
                visited.add((nx, ny))
                queue.append((nx, ny))

    return result
