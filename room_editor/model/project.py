"""Core project dataclasses for the Atari 8-bit Room Editor (no Qt imports)."""

from __future__ import annotations

from dataclasses import dataclass, field

from room_editor.model.charset import CharsetData
from room_editor.model.palette import Palette

PROJECT_VERSION = 1
ROOM_WIDTH = 40
ROOM_HEIGHT = 20
MAX_ROOMS = 255
MAX_OBJECTS = 255
MAX_OBJECT_CELLS = 255


@dataclass
class Settings:
    """Global project settings."""

    default_palette: Palette = field(default_factory=Palette)


@dataclass
class ObjectGroup:
    """Named object group pairing a 1024-byte charset with an ANTIC 4 palette."""

    name: str
    charset_path: str = ""
    palette: Palette = field(default_factory=Palette)
    charset: CharsetData | None = field(default=None, repr=False, compare=False)


@dataclass
class GameObject:
    """Reusable multi-character stamp belonging to a single object group."""

    id: int
    name: str
    group: str
    tags: list[str] = field(default_factory=list)
    non_blockable: bool = False
    w: int = 1
    h: int = 1
    chars: list[list[int]] = field(default_factory=lambda: [[0]])

    def __post_init__(self) -> None:
        self.id = int(self.id)
        self.w = int(self.w)
        self.h = int(self.h)
        if not self.chars and self.w > 0 and self.h > 0:
            self.chars = [[0] * self.w for _ in range(self.h)]

    @property
    def cell_count(self) -> int:
        """Total number of cells (w * h)."""
        return self.w * self.h

    def occupied_offsets(self) -> list[tuple[int, int]]:
        """Return (dx, dy) offsets of non-empty (non-zero) character cells."""
        offsets: list[tuple[int, int]] = []
        for dy in range(min(self.h, len(self.chars))):
            row = self.chars[dy]
            for dx in range(min(self.w, len(row))):
                if row[dx] != 0:
                    offsets.append((dx, dy))
        return offsets

    def resize(self, new_w: int, new_h: int) -> None:
        """Resize the character grid, preserving existing cells and zero-filling new ones."""
        new_w = int(new_w)
        new_h = int(new_h)
        if new_w < 1 or new_h < 1:
            raise ValueError(f"Object dimensions must be >= 1; got {new_w}x{new_h}.")
        if new_w * new_h > MAX_OBJECT_CELLS:
            raise ValueError(
                f"Object cell count {new_w * new_h} exceeds limit of {MAX_OBJECT_CELLS}."
            )
        new_chars: list[list[int]] = []
        for dy in range(new_h):
            row: list[int] = []
            for dx in range(new_w):
                if dy < len(self.chars) and dx < len(self.chars[dy]):
                    row.append(int(self.chars[dy][dx]) & 0xFF)
                else:
                    row.append(0)
            new_chars.append(row)
        self.w = new_w
        self.h = new_h
        self.chars = new_chars


@dataclass
class ObjectInstance:
    """Placement of a GameObject inside a Room."""

    object_id: int
    x: int
    y: int

    def __post_init__(self) -> None:
        self.object_id = int(self.object_id)
        self.x = int(self.x)
        self.y = int(self.y)


@dataclass
class Room:
    """A 40x20 ANTIC 4 room storing row groups and object instances."""

    id: int
    name: str
    pos: tuple[int, int] = (0, 0)
    row_groups: list[str] = field(default_factory=lambda: [""] * ROOM_HEIGHT)
    instances: list[ObjectInstance] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.id = int(self.id)
        self.pos = (int(self.pos[0]), int(self.pos[1]))
        if len(self.row_groups) == 1 and ROOM_HEIGHT > 1:
            self.row_groups = [self.row_groups[0]] * ROOM_HEIGHT
        elif len(self.row_groups) != ROOM_HEIGHT:
            padded = list(self.row_groups[:ROOM_HEIGHT])
            fill = padded[-1] if padded else ""
            while len(padded) < ROOM_HEIGHT:
                padded.append(fill)
            self.row_groups = padded

    def set_all_row_groups(self, group_name: str) -> None:
        """Assign the same object group to all 20 rows."""
        self.row_groups = [group_name] * ROOM_HEIGHT

    def set_row_group(self, row: int, group_name: str) -> None:
        """Assign an object group to a single row (0..19)."""
        if not (0 <= row < ROOM_HEIGHT):
            raise ValueError(f"Row index out of range 0..{ROOM_HEIGHT - 1}: {row}.")
        self.row_groups[row] = group_name

    def set_row_range_group(self, start_row: int, end_row: int, group_name: str) -> None:
        """Assign an object group to an inclusive range of rows."""
        lo = max(0, min(start_row, end_row))
        hi = min(ROOM_HEIGHT - 1, max(start_row, end_row))
        for r in range(lo, hi + 1):
            self.row_groups[r] = group_name


@dataclass
class TeleportEndpoint:
    """One end of a bidirectional teleport link."""

    room_id: int
    x: int
    y: int

    def __post_init__(self) -> None:
        self.room_id = int(self.room_id)
        self.x = int(self.x)
        self.y = int(self.y)


@dataclass
class Teleport:
    """Bidirectional teleport link between two endpoints."""

    a: TeleportEndpoint
    b: TeleportEndpoint


@dataclass
class StartPosition:
    """Unique hero starting room and cell coordinate."""

    room_id: int
    x: int
    y: int

    def __post_init__(self) -> None:
        self.room_id = int(self.room_id)
        self.x = int(self.x)
        self.y = int(self.y)


@dataclass
class Project:
    """Top-level room editor project model."""

    version: int = PROJECT_VERSION
    settings: Settings = field(default_factory=Settings)
    tags: list[str] = field(default_factory=list)
    object_groups: list[ObjectGroup] = field(default_factory=list)
    objects: list[GameObject] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    teleports: list[Teleport] = field(default_factory=list)
    start: StartPosition | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Project):
            return NotImplemented
        if (
            self.version != other.version
            or self.settings != other.settings
            or self.tags != other.tags
            or self.object_groups != other.object_groups
            or self.objects != other.objects
            or self.teleports != other.teleports
            or self.start != other.start
            or len(self.rooms) != len(other.rooms)
        ):
            return False

        objs_self = {o.id: o for o in self.objects}
        objs_other = {o.id: o for o in other.objects}
        for ra, rb in zip(self.rooms, other.rooms):
            if (
                ra.id != rb.id
                or ra.name != rb.name
                or ra.pos != rb.pos
                or ra.row_groups != rb.row_groups
            ):
                return False
            block_a: list[ObjectInstance] = []
            non_a: list[ObjectInstance] = []
            for inst in ra.instances:
                obj = objs_self.get(inst.object_id)
                if obj is not None and obj.non_blockable:
                    non_a.append(inst)
                else:
                    block_a.append(inst)

            block_b: list[ObjectInstance] = []
            non_b: list[ObjectInstance] = []
            for inst in rb.instances:
                obj = objs_other.get(inst.object_id)
                if obj is not None and obj.non_blockable:
                    non_b.append(inst)
                else:
                    block_b.append(inst)

            if sorted(block_a, key=lambda i: (i.y, i.x, i.object_id)) != sorted(
                block_b, key=lambda i: (i.y, i.x, i.object_id)
            ):
                return False
            if non_a != non_b:
                return False
        return True

    def get_group(self, name: str) -> ObjectGroup | None:
        """Look up an ObjectGroup by exact name."""
        for grp in self.object_groups:
            if grp.name == name:
                return grp
        return None

    def get_object(self, obj_id: int) -> GameObject | None:
        """Look up a GameObject by numeric ID."""
        for obj in self.objects:
            if obj.id == obj_id:
                return obj
        return None

    def get_room(self, room_id: int) -> Room | None:
        """Look up a Room by numeric ID."""
        for room in self.rooms:
            if room.id == room_id:
                return room
        return None

    def get_room_at(self, gx: int, gy: int) -> Room | None:
        """Look up the Room occupying canvas grid coordinate (gx, gy)."""
        for room in self.rooms:
            if room.pos == (gx, gy):
                return room
        return None

    def next_free_room_id(self) -> int | None:
        """Return the lowest unused room ID in 1..255, or None if full."""
        used = {r.id for r in self.rooms}
        for candidate in range(1, MAX_ROOMS + 1):
            if candidate not in used:
                return candidate
        return None

    def next_free_object_id(self) -> int | None:
        """Return the lowest unused object ID in 1..255, or None if full."""
        used = {o.id for o in self.objects}
        for candidate in range(1, MAX_OBJECTS + 1):
            if candidate not in used:
                return candidate
        return None

    def next_free_room_name(self, prefix: str = "K") -> str:
        """Return a unique default room name such as K1, K2, ..."""
        used = {r.name for r in self.rooms}
        idx = 1
        while f"{prefix}{idx}" in used:
            idx += 1
        return f"{prefix}{idx}"

    def room_occupied_cells(
        self,
        room: Room,
        ignore_indices: set[int] | None = None,
    ) -> dict[tuple[int, int], tuple[int, ObjectInstance, int]]:
        """Map (x, y) -> (instance_idx, instance, char_code) for non-zero cells in a room."""
        objects_by_id = {o.id: o for o in self.objects}
        occupied: dict[tuple[int, int], tuple[int, ObjectInstance, int]] = {}
        ignored = ignore_indices or set()
        for inst_idx, inst in enumerate(room.instances):
            if inst_idx in ignored:
                continue
            obj = objects_by_id.get(inst.object_id)
            if obj is None:
                continue
            for dx, dy in obj.occupied_offsets():
                cx = inst.x + dx
                cy = inst.y + dy
                if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                    occupied[(cx, cy)] = (inst_idx, inst, obj.chars[dy][dx])
        return occupied

    def room_blockable_cells(
        self,
        room: Room,
        ignore_indices: set[int] | None = None,
    ) -> dict[tuple[int, int], tuple[int, ObjectInstance, int]]:
        """Map (x, y) -> (instance_idx, instance, char_code) for blockable non-zero cells."""
        objects_by_id = {o.id: o for o in self.objects}
        occupied: dict[tuple[int, int], tuple[int, ObjectInstance, int]] = {}
        ignored = ignore_indices or set()
        for inst_idx, inst in enumerate(room.instances):
            if inst_idx in ignored:
                continue
            obj = objects_by_id.get(inst.object_id)
            if obj is None or obj.non_blockable:
                continue
            for dx, dy in obj.occupied_offsets():
                cx = inst.x + dx
                cy = inst.y + dy
                if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                    occupied[(cx, cy)] = (inst_idx, inst, obj.chars[dy][dx])
        return occupied

    def can_place_instance(
        self,
        room: Room,
        obj_id: int,
        x: int,
        y: int,
        ignore_indices: set[int] | None = None,
    ) -> tuple[bool, str]:
        """Check whether placing obj_id at (x, y) is in-bounds and obeys overlap rules.

        Non-blockable objects may overlap anything freely (bounds-checked only).
        Blockable objects may not overlap other blockable objects on non-zero cells.
        """
        obj = self.get_object(obj_id)
        if obj is None:
            return False, f"Unknown object ID {obj_id}."
        if x < 0 or y < 0 or x + obj.w > ROOM_WIDTH or y + obj.h > ROOM_HEIGHT:
            return False, "Object extends outside the 40x20 room bounds."

        if obj.non_blockable:
            return True, ""

        ignored = ignore_indices or set()
        offsets = obj.occupied_offsets()
        if not offsets:
            for idx, existing in enumerate(room.instances):
                if idx in ignored:
                    continue
                if existing.object_id == obj_id and existing.x == x and existing.y == y:
                    return False, "An identical instance already exists at that position."
            return True, ""

        occupied = self.room_blockable_cells(room, ignore_indices=ignore_indices)
        for dx, dy in offsets:
            if (x + dx, y + dy) in occupied:
                return False, f"Cell ({x + dx}, {y + dy}) is already occupied by a blockable object."
        return True, ""

    def compose_room_with_sources(
        self,
        room: Room,
    ) -> tuple[list[list[int]], list[list[int | None]]]:
        """Compose the 20x40 room character grid and topmost contributing instance index.

        Draw order:
          1. Layer 1: non-blockable instances in list (z) order.
          2. Layer 2: blockable instances (always drawn on top of Layer 1).
        Code 0 cells are transparent and never overwrite cells underneath.
        """
        grid = [[0] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
        sources: list[list[int | None]] = [[None] * ROOM_WIDTH for _ in range(ROOM_HEIGHT)]
        objects_by_id = {o.id: o for o in self.objects}

        for layer_non_blockable in (True, False):
            for inst_idx, inst in enumerate(room.instances):
                obj = objects_by_id.get(inst.object_id)
                if obj is None or obj.non_blockable != layer_non_blockable:
                    continue
                for dx, dy in obj.occupied_offsets():
                    cx = inst.x + dx
                    cy = inst.y + dy
                    if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                        grid[cy][cx] = obj.chars[dy][dx]
                        sources[cy][cx] = inst_idx

        return grid, sources

    def compose_room(self, room: Room) -> list[list[int]]:
        """Compose the 20x40 character grid for a room following layered draw order."""
        grid, _ = self.compose_room_with_sources(room)
        return grid

    def find_instance_at(self, room: Room, x: int, y: int) -> int | None:
        """Return index of topmost instance with a non-zero char at (x, y), or anchor fallback."""
        if not (0 <= x < ROOM_WIDTH and 0 <= y < ROOM_HEIGHT):
            return None
        _, sources = self.compose_room_with_sources(room)
        if sources[y][x] is not None:
            return sources[y][x]
        # Fallback: match anchor in reverse z-order for an all-zero object.
        for idx in range(len(room.instances) - 1, -1, -1):
            inst = room.instances[idx]
            if inst.x == x and inst.y == y:
                return idx
        return None

    def find_blockable_overlaps_for_object(
        self,
        obj_id: int,
        *,
        new_w: int | None = None,
        new_h: int | None = None,
        new_chars: list[list[int]] | None = None,
    ) -> list[tuple[int, str, int, int, int]]:
        """Find all blockable overlaps if obj_id has non_blockable=False across all rooms.

        Returns list of (room_id, room_name, x, y, conflicting_object_id).
        """
        objects_by_id = {o.id: o for o in self.objects}
        target = objects_by_id.get(obj_id)
        if target is None:
            return []

        probe_w = target.w if new_w is None else int(new_w)
        probe_h = target.h if new_h is None else int(new_h)
        probe_chars = target.chars if new_chars is None else new_chars
        probe_obj = GameObject(
            id=target.id,
            name=target.name,
            group=target.group,
            tags=list(target.tags),
            non_blockable=False,
            w=probe_w,
            h=probe_h,
            chars=[list(r) for r in probe_chars],
        )
        test_objects = dict(objects_by_id)
        test_objects[obj_id] = probe_obj

        conflicts: list[tuple[int, str, int, int, int]] = []
        for room in self.rooms:
            occupied: dict[tuple[int, int], int] = {}
            for inst in room.instances:
                obj = test_objects.get(inst.object_id)
                if obj is None or obj.non_blockable:
                    continue
                for dx, dy in obj.occupied_offsets():
                    cx = inst.x + dx
                    cy = inst.y + dy
                    if 0 <= cx < ROOM_WIDTH and 0 <= cy < ROOM_HEIGHT:
                        prev = occupied.get((cx, cy))
                        if prev is not None:
                            if obj.id == obj_id or prev == obj_id:
                                other = prev if obj.id == obj_id else obj.id
                                conflicts.append((room.id, room.name, cx, cy, other))
                        else:
                            occupied[(cx, cy)] = obj.id
        return conflicts


def compose_room_with_sources(
    project: Project,
    room: Room,
) -> tuple[list[list[int]], list[list[int | None]]]:
    """Module-level wrapper for Project.compose_room_with_sources."""
    return project.compose_room_with_sources(room)


def compose_room(project: Project, room: Room) -> list[list[int]]:
    """Module-level wrapper for Project.compose_room."""
    return project.compose_room(room)
