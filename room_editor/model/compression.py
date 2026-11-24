"""Deterministic lossless instance compression and decompression (F-25, F-26).

Two-layer compression strategy:
1. Blockable instances (`non_blockable == False`, plus unknown object IDs):
   Since blockable instances never overlap, draw order among them is irrelevant.
   They are compressed using the deterministic greedy largest-rectangle algorithm
   (largest area, then smallest y, then smallest x, then greatest width) and
   emitted first, sorted by `(y, x, object_id)`.
2. Non-blockable instances (`non_blockable == True`):
   List order is the z-order within Layer 1 and MUST be preserved across save/load.
   Only consecutive runs in z-order of the same object that form a gapless
   row-major tiling (`repeat-x`, `repeat-y`, or `repeat-xy` with step `(w, h)`)
   are merged into a single entry, emitted after blockable entries in exact z-order.
"""

from __future__ import annotations

from dataclasses import dataclass

from room_editor.model.project import GameObject, ObjectInstance, Room


@dataclass(frozen=True)
class CompressedPlacement:
    """Compressed placement entry representing a WxH tiled block of an object."""

    object_id: int
    x: int
    y: int
    repeat_x: int = 1
    repeat_y: int = 1


def _compress_blockable(
    instances: list[ObjectInstance],
    objects_by_id: dict[int, GameObject],
) -> list[CompressedPlacement]:
    """Compress blockable instances using greedy largest-rectangle tiling."""
    by_object: dict[int, set[tuple[int, int]]] = {}
    for inst in instances:
        by_object.setdefault(inst.object_id, set()).add((inst.x, inst.y))

    entries: list[CompressedPlacement] = []

    for obj_id in sorted(by_object.keys()):
        remaining = set(by_object[obj_id])
        obj = objects_by_id.get(obj_id)
        step_x = obj.w if obj and obj.w > 0 else 1
        step_y = obj.h if obj and obj.h > 0 else 1

        while remaining:
            best_score: tuple[int, int, int, int] | None = None
            best_rect: tuple[int, int, int, int] | None = None

            for x0, y0 in sorted(remaining, key=lambda p: (p[1], p[0])):
                curr_rw = 0
                while (x0 + curr_rw * step_x, y0) in remaining:
                    curr_rw += 1

                rh = 1
                while True:
                    row_y = y0 + (rh - 1) * step_y
                    row_rw = 0
                    while row_rw < curr_rw and (x0 + row_rw * step_x, row_y) in remaining:
                        row_rw += 1
                    if row_rw == 0:
                        break
                    curr_rw = min(curr_rw, row_rw)
                    area = curr_rw * rh
                    score = (area, -y0, -x0, curr_rw)
                    if best_score is None or score > best_score:
                        best_score = score
                        best_rect = (x0, y0, curr_rw, rh)
                    rh += 1

            assert best_rect is not None
            bx, by, brw, brh = best_rect
            for iy in range(brh):
                for ix in range(brw):
                    remaining.remove((bx + ix * step_x, by + iy * step_y))

            entries.append(
                CompressedPlacement(
                    object_id=obj_id,
                    x=bx,
                    y=by,
                    repeat_x=brw,
                    repeat_y=brh,
                )
            )

    entries.sort(key=lambda e: (e.y, e.x, e.object_id))
    return entries


def _compress_non_blockable_ordered(
    instances: list[ObjectInstance],
    objects_by_id: dict[int, GameObject],
) -> list[CompressedPlacement]:
    """Compress consecutive runs of non-blockable instances without altering z-order.

    A slice `instances[idx : idx + rw * rh]` is merged into a single entry only
    if every element matches row-major expansion from `instances[idx]` with step
    `(obj.w, obj.h)`. Expanding the output reproduces the exact input sequence.
    """
    entries: list[CompressedPlacement] = []
    n = len(instances)
    idx = 0

    while idx < n:
        first = instances[idx]
        obj_id = first.object_id
        obj = objects_by_id.get(obj_id)
        step_x = obj.w if obj and obj.w > 0 else 1
        step_y = obj.h if obj and obj.h > 0 else 1

        max_rw = 1
        while (
            idx + max_rw < n
            and instances[idx + max_rw].object_id == obj_id
            and instances[idx + max_rw].x == first.x + max_rw * step_x
            and instances[idx + max_rw].y == first.y
        ):
            max_rw += 1

        best_rw = 1
        best_rh = 1
        best_score = (1, 1)

        for rw in range(max_rw, 0, -1):
            rh = 1
            while idx + (rh + 1) * rw <= n:
                next_row_start = idx + rh * rw
                target_y = first.y + rh * step_y
                row_matches = True
                for ix in range(rw):
                    cand = instances[next_row_start + ix]
                    if (
                        cand.object_id != obj_id
                        or cand.x != first.x + ix * step_x
                        or cand.y != target_y
                    ):
                        row_matches = False
                        break
                if not row_matches:
                    break
                rh += 1

            score = (rw * rh, rw)
            if score > best_score:
                best_score = score
                best_rw = rw
                best_rh = rh

        entries.append(
            CompressedPlacement(
                object_id=obj_id,
                x=first.x,
                y=first.y,
                repeat_x=best_rw,
                repeat_y=best_rh,
            )
        )
        idx += best_rw * best_rh

    return entries


def compress_room_instances(
    room: Room,
    objects_by_id: dict[int, GameObject],
) -> list[CompressedPlacement]:
    """Compress room instances: blockable first (sorted), then non-blockable (z-order)."""
    blockable: list[ObjectInstance] = []
    non_blockable: list[ObjectInstance] = []
    for inst in room.instances:
        obj = objects_by_id.get(inst.object_id)
        if obj is not None and obj.non_blockable:
            non_blockable.append(inst)
        else:
            blockable.append(inst)

    return _compress_blockable(blockable, objects_by_id) + _compress_non_blockable_ordered(
        non_blockable, objects_by_id
    )


def decompress_placements(
    entries: list[CompressedPlacement],
    objects_by_id: dict[int, GameObject],
) -> list[ObjectInstance]:
    """Expand compressed placement entries in exact file order (preserving z-order)."""
    instances: list[ObjectInstance] = []
    for entry in entries:
        obj = objects_by_id.get(entry.object_id)
        step_x = obj.w if obj and obj.w > 0 else 1
        step_y = obj.h if obj and obj.h > 0 else 1
        for iy in range(entry.repeat_y):
            for ix in range(entry.repeat_x):
                instances.append(
                    ObjectInstance(
                        object_id=entry.object_id,
                        x=entry.x + ix * step_x,
                        y=entry.y + iy * step_y,
                    )
                )
    return instances
