"""Command pattern and Undo/Redo stack for all Project mutations."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Literal

from room_editor.model.charset import CharsetData
from room_editor.model.palette import Palette
from room_editor.model.project import (
    GameObject,
    ObjectGroup,
    ObjectInstance,
    Project,
    Room,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)


class Command(ABC):
    """Base class for reversible project mutations."""

    description: str = ""

    @abstractmethod
    def execute(self) -> None:
        """Apply the command to the model."""

    @abstractmethod
    def undo(self) -> None:
        """Revert the command on the model."""


class UndoStack:
    """Bounded undo/redo command history with clean-state tracking."""

    def __init__(self, max_depth: int = 250) -> None:
        self.max_depth = max_depth
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._clean_index: int = 0
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked whenever stack state changes."""
        self._listeners.append(callback)

    def _notify(self) -> None:
        for cb in self._listeners:
            cb()

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    @property
    def is_dirty(self) -> bool:
        return len(self._undo_stack) != self._clean_index

    def mark_clean(self) -> None:
        """Record the current stack depth as saved/clean."""
        self._clean_index = len(self._undo_stack)
        self._notify()

    def clear(self) -> None:
        """Reset both stacks and mark clean."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._clean_index = 0
        self._notify()

    def push_and_execute(self, cmd: Command) -> None:
        """Execute a command and push it onto the undo stack."""
        cmd.execute()
        self._undo_stack.append(cmd)
        if len(self._undo_stack) > self.max_depth:
            self._undo_stack.pop(0)
            self._clean_index -= 1
        self._redo_stack.clear()
        self._notify()

    def undo(self) -> Command | None:
        """Undo the most recent command, returning it if one existed."""
        if not self._undo_stack:
            return None
        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)
        self._notify()
        return cmd

    def redo(self) -> Command | None:
        """Redo the most recently undone command, returning it if one existed."""
        if not self._redo_stack:
            return None
        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)
        self._notify()
        return cmd


# ---------------------------------------------------------------------------
# Room commands
# ---------------------------------------------------------------------------


class AddRoomCommand(Command):
    def __init__(self, project: Project, room: Room) -> None:
        self.description = f"Add room '{room.name}'"
        self._project = project
        self._room = room
        self._old_start: StartPosition | None = None

    def execute(self) -> None:
        self._project.rooms.append(self._room)
        if self._project.start is None:
            self._old_start = None
            self._project.start = StartPosition(room_id=self._room.id, x=1, y=1)
        else:
            self._old_start = copy.deepcopy(self._project.start)

    def undo(self) -> None:
        if self._room in self._project.rooms:
            self._project.rooms.remove(self._room)
        self._project.start = copy.deepcopy(self._old_start)


class DeleteRoomCommand(Command):
    def __init__(self, project: Project, room_id: int) -> None:
        self.description = f"Delete room {room_id}"
        self._project = project
        self._room_id = room_id
        self._removed_room: Room | None = None
        self._removed_index: int = -1
        self._old_teleports: list[Teleport] = []
        self._old_start: StartPosition | None = None

    def execute(self) -> None:
        self._old_teleports = list(self._project.teleports)
        self._old_start = copy.deepcopy(self._project.start)
        for idx, r in enumerate(self._project.rooms):
            if r.id == self._room_id:
                self._removed_room = r
                self._removed_index = idx
                self._project.rooms.pop(idx)
                break
        self._project.teleports = [
            tp
            for tp in self._project.teleports
            if tp.a.room_id != self._room_id and tp.b.room_id != self._room_id
        ]
        if self._project.start and self._project.start.room_id == self._room_id:
            self._project.start = None

    def undo(self) -> None:
        if self._removed_room is not None and self._removed_room not in self._project.rooms:
            idx = max(0, min(self._removed_index, len(self._project.rooms)))
            self._project.rooms.insert(idx, self._removed_room)
        self._project.teleports = list(self._old_teleports)
        self._project.start = copy.deepcopy(self._old_start)


class MoveRoomsCommand(Command):
    def __init__(self, project: Project, room_ids: set[int], dx: int, dy: int) -> None:
        self.description = "Move room(s)"
        self._project = project
        self._room_ids = set(room_ids)
        self._dx = int(dx)
        self._dy = int(dy)

    def execute(self) -> None:
        for room in self._project.rooms:
            if room.id in self._room_ids:
                room.pos = (room.pos[0] + self._dx, room.pos[1] + self._dy)

    def undo(self) -> None:
        for room in self._project.rooms:
            if room.id in self._room_ids:
                room.pos = (room.pos[0] - self._dx, room.pos[1] - self._dy)


class UpdateRoomMetaCommand(Command):
    def __init__(self, project: Project, room: Room, new_id: int, new_name: str) -> None:
        self.description = f"Update room '{room.name}'"
        self._project = project
        self._room = room
        self._old_id = room.id
        self._old_name = room.name
        self._new_id = int(new_id)
        self._new_name = new_name

    def _apply_id(self, from_id: int, to_id: int) -> None:
        self._room.id = to_id
        if from_id != to_id:
            for tp in self._project.teleports:
                if tp.a.room_id == from_id:
                    tp.a.room_id = to_id
                if tp.b.room_id == from_id:
                    tp.b.room_id = to_id
            if self._project.start and self._project.start.room_id == from_id:
                self._project.start.room_id = to_id

    def execute(self) -> None:
        self._room.name = self._new_name
        self._apply_id(self._old_id, self._new_id)

    def undo(self) -> None:
        self._room.name = self._old_name
        self._apply_id(self._new_id, self._old_id)


class SetRoomRowGroupsCommand(Command):
    def __init__(self, room: Room, new_row_groups: list[str]) -> None:
        self.description = f"Update row groups for '{room.name}'"
        self._room = room
        self._old_row_groups = list(room.row_groups)
        self._new_row_groups = list(new_row_groups)

    def execute(self) -> None:
        self._room.row_groups = list(self._new_row_groups)

    def undo(self) -> None:
        self._room.row_groups = list(self._old_row_groups)


# ---------------------------------------------------------------------------
# Room instance commands
# ---------------------------------------------------------------------------


class AddInstancesCommand(Command):
    def __init__(
        self,
        room: Room,
        instances: list[ObjectInstance],
        description: str = "Place object(s)",
    ) -> None:
        self.description = description
        self._room = room
        self._instances = [copy.deepcopy(i) for i in instances]

    def execute(self) -> None:
        self._room.instances.extend(copy.deepcopy(i) for i in self._instances)

    def undo(self) -> None:
        count = len(self._instances)
        if count > 0:
            del self._room.instances[-count:]


class RemoveInstancesCommand(Command):
    def __init__(
        self,
        room: Room,
        indices: list[int],
        description: str = "Remove object(s)",
    ) -> None:
        self.description = description
        self._room = room
        self._old_instances = [copy.deepcopy(i) for i in room.instances]
        remove_set = set(indices)
        self._new_instances = [
            copy.deepcopy(inst)
            for idx, inst in enumerate(room.instances)
            if idx not in remove_set
        ]

    def execute(self) -> None:
        self._room.instances = [copy.deepcopy(i) for i in self._new_instances]

    def undo(self) -> None:
        self._room.instances = [copy.deepcopy(i) for i in self._old_instances]


class ReplaceRoomInstancesCommand(Command):
    def __init__(
        self,
        room: Room,
        new_instances: list[ObjectInstance],
        description: str = "Edit room layout",
    ) -> None:
        self.description = description
        self._room = room
        self._old_instances = [copy.deepcopy(i) for i in room.instances]
        self._new_instances = [copy.deepcopy(i) for i in new_instances]

    def execute(self) -> None:
        self._room.instances = [copy.deepcopy(i) for i in self._new_instances]

    def undo(self) -> None:
        self._room.instances = [copy.deepcopy(i) for i in self._old_instances]


ZOrderAction = Literal["bring_to_front", "send_to_back", "move_up", "move_down"]


class ReorderNonBlockableCommand(Command):
    """Reorder selected non-blockable instances within the non-blockable z-order."""

    def __init__(
        self,
        project: Project,
        room: Room,
        indices: set[int],
        action: ZOrderAction,
    ) -> None:
        self.description = f"Z-order: {action.replace('_', ' ')}"
        self._room = room
        self._old_instances = [copy.deepcopy(i) for i in room.instances]

        objects_by_id = {o.id: o for o in project.objects}
        nb_slots = [
            idx
            for idx, inst in enumerate(room.instances)
            if (obj := objects_by_id.get(inst.object_id)) is not None and obj.non_blockable
        ]
        selected_nb_slots = [idx for idx in nb_slots if idx in indices]

        if not selected_nb_slots or len(nb_slots) <= 1:
            self._new_instances = [copy.deepcopy(i) for i in room.instances]
            self.result_indices: set[int] = set(indices)
            self.has_change = False
            return

        selected_positions = [nb_slots.index(idx) for idx in selected_nb_slots]
        nb_items = [copy.deepcopy(room.instances[idx]) for idx in nb_slots]
        tagged = [(pos, pos in selected_positions, item) for pos, item in enumerate(nb_items)]

        if action == "bring_to_front":
            reordered = [t for t in tagged if not t[1]] + [t for t in tagged if t[1]]
        elif action == "send_to_back":
            reordered = [t for t in tagged if t[1]] + [t for t in tagged if not t[1]]
        elif action == "move_up":
            reordered = list(tagged)
            for pos in range(len(reordered) - 2, -1, -1):
                if reordered[pos][1] and not reordered[pos + 1][1]:
                    reordered[pos], reordered[pos + 1] = reordered[pos + 1], reordered[pos]
        elif action == "move_down":
            reordered = list(tagged)
            for pos in range(1, len(reordered)):
                if reordered[pos][1] and not reordered[pos - 1][1]:
                    reordered[pos - 1], reordered[pos] = reordered[pos], reordered[pos - 1]
        else:
            raise ValueError(f"Unknown z-order action: {action!r}")

        new_list = [copy.deepcopy(i) for i in room.instances]
        new_selected_indices: set[int] = set()
        for slot_pos, (_orig_pos, is_sel, item) in zip(nb_slots, reordered):
            new_list[slot_pos] = item
            if is_sel:
                new_selected_indices.add(slot_pos)

        # Preserve any non-nb selected indices unchanged
        for idx in indices:
            if idx not in nb_slots and 0 <= idx < len(new_list):
                new_selected_indices.add(idx)

        self._new_instances = new_list
        self.result_indices = new_selected_indices
        self.has_change = [t[0] for t in reordered] != list(range(len(nb_items)))

    def execute(self) -> None:
        self._room.instances = [copy.deepcopy(i) for i in self._new_instances]

    def undo(self) -> None:
        self._room.instances = [copy.deepcopy(i) for i in self._old_instances]


class BringToFrontCommand(ReorderNonBlockableCommand):
    def __init__(self, project: Project, room: Room, indices: set[int]) -> None:
        super().__init__(project, room, indices, "bring_to_front")


class SendToBackCommand(ReorderNonBlockableCommand):
    def __init__(self, project: Project, room: Room, indices: set[int]) -> None:
        super().__init__(project, room, indices, "send_to_back")


class MoveInstanceUpCommand(ReorderNonBlockableCommand):
    def __init__(self, project: Project, room: Room, indices: set[int]) -> None:
        super().__init__(project, room, indices, "move_up")


class MoveInstanceDownCommand(ReorderNonBlockableCommand):
    def __init__(self, project: Project, room: Room, indices: set[int]) -> None:
        super().__init__(project, room, indices, "move_down")


# ---------------------------------------------------------------------------
# Object Group commands
# ---------------------------------------------------------------------------


class AddGroupCommand(Command):
    def __init__(self, project: Project, group: ObjectGroup) -> None:
        self.description = f"Add group '{group.name}'"
        self._project = project
        self._group = group

    def execute(self) -> None:
        self._project.object_groups.append(self._group)

    def undo(self) -> None:
        if self._group in self._project.object_groups:
            self._project.object_groups.remove(self._group)


class DeleteGroupCommand(Command):
    def __init__(
        self,
        project: Project,
        group_name: str,
        fallback_group: str = "",
    ) -> None:
        self.description = f"Delete group '{group_name}'"
        self._project = project
        self._group_name = group_name
        self._fallback_group = fallback_group
        self._removed_group: ObjectGroup | None = None
        self._removed_index: int = -1
        self._old_object_groups: dict[int, str] = {}
        self._old_room_rows: dict[int, list[str]] = {}

    def execute(self) -> None:
        for idx, g in enumerate(self._project.object_groups):
            if g.name == self._group_name:
                self._removed_group = g
                self._removed_index = idx
                self._project.object_groups.pop(idx)
                break
        self._old_object_groups = {}
        for obj in self._project.objects:
            if obj.group == self._group_name:
                self._old_object_groups[obj.id] = obj.group
                obj.group = self._fallback_group
        self._old_room_rows = {}
        for room in self._project.rooms:
            if self._group_name in room.row_groups:
                self._old_room_rows[room.id] = list(room.row_groups)
                room.row_groups = [
                    self._fallback_group if rg == self._group_name else rg
                    for rg in room.row_groups
                ]

    def undo(self) -> None:
        if self._removed_group is not None and self._removed_group not in self._project.object_groups:
            idx = max(0, min(self._removed_index, len(self._project.object_groups)))
            self._project.object_groups.insert(idx, self._removed_group)
        for obj in self._project.objects:
            if obj.id in self._old_object_groups:
                obj.group = self._old_object_groups[obj.id]
        for room in self._project.rooms:
            if room.id in self._old_room_rows:
                room.row_groups = list(self._old_room_rows[room.id])


class UpdateGroupCommand(Command):
    def __init__(
        self,
        project: Project,
        group: ObjectGroup,
        *,
        name: str | None = None,
        charset_path: str | None = None,
        charset: CharsetData | None = None,
        update_charset: bool = False,
        palette: Palette | None = None,
    ) -> None:
        self.description = f"Update group '{group.name}'"
        self._project = project
        self._group = group
        self._old_name = group.name
        self._new_name = name if name is not None else group.name
        self._old_charset_path = group.charset_path
        self._new_charset_path = charset_path if charset_path is not None else group.charset_path
        self._old_charset = group.charset
        self._new_charset = charset if update_charset else group.charset
        self._old_palette = group.palette.copy()
        self._new_palette = palette.copy() if palette is not None else group.palette.copy()

    def _rename_references(self, from_name: str, to_name: str) -> None:
        if from_name == to_name:
            return
        for obj in self._project.objects:
            if obj.group == from_name:
                obj.group = to_name
        for room in self._project.rooms:
            room.row_groups = [
                to_name if rg == from_name else rg for rg in room.row_groups
            ]

    def execute(self) -> None:
        self._group.name = self._new_name
        self._group.charset_path = self._new_charset_path
        self._group.charset = self._new_charset
        self._group.palette = self._new_palette.copy()
        self._rename_references(self._old_name, self._new_name)

    def undo(self) -> None:
        self._group.name = self._old_name
        self._group.charset_path = self._old_charset_path
        self._group.charset = self._old_charset
        self._group.palette = self._old_palette.copy()
        self._rename_references(self._new_name, self._old_name)


# ---------------------------------------------------------------------------
# Object commands
# ---------------------------------------------------------------------------


class AddObjectCommand(Command):
    def __init__(self, project: Project, obj: GameObject) -> None:
        self.description = f"Add object '{obj.name}'"
        self._project = project
        self._obj = obj

    def execute(self) -> None:
        self._project.objects.append(self._obj)

    def undo(self) -> None:
        if self._obj in self._project.objects:
            self._project.objects.remove(self._obj)


class DeleteObjectCommand(Command):
    def __init__(self, project: Project, obj_id: int) -> None:
        self.description = f"Delete object {obj_id}"
        self._project = project
        self._obj_id = obj_id
        self._removed_obj: GameObject | None = None
        self._removed_index: int = -1
        self._old_room_instances: dict[int, list[ObjectInstance]] = {}

    def execute(self) -> None:
        for idx, obj in enumerate(self._project.objects):
            if obj.id == self._obj_id:
                self._removed_obj = obj
                self._removed_index = idx
                self._project.objects.pop(idx)
                break
        self._old_room_instances = {}
        for room in self._project.rooms:
            if any(inst.object_id == self._obj_id for inst in room.instances):
                self._old_room_instances[room.id] = [copy.deepcopy(i) for i in room.instances]
                room.instances = [
                    inst for inst in room.instances if inst.object_id != self._obj_id
                ]

    def undo(self) -> None:
        if self._removed_obj is not None and self._removed_obj not in self._project.objects:
            idx = max(0, min(self._removed_index, len(self._project.objects)))
            self._project.objects.insert(idx, self._removed_obj)
        for room in self._project.rooms:
            if room.id in self._old_room_instances:
                room.instances = [copy.deepcopy(i) for i in self._old_room_instances[room.id]]


class UpdateObjectCommand(Command):
    def __init__(
        self,
        project: Project,
        obj: GameObject,
        *,
        id: int | None = None,
        name: str | None = None,
        group: str | None = None,
        tags: list[str] | None = None,
        non_blockable: bool | None = None,
        w: int | None = None,
        h: int | None = None,
        chars: list[list[int]] | None = None,
    ) -> None:
        self.description = f"Update object '{obj.name}'"
        self._project = project
        self._obj = obj
        self._old_state = (
            obj.id,
            obj.name,
            obj.group,
            list(obj.tags),
            obj.non_blockable,
            obj.w,
            obj.h,
            [list(row) for row in obj.chars],
        )
        new_w = obj.w if w is None else int(w)
        new_h = obj.h if h is None else int(h)
        new_chars = (
            [list(row) for row in obj.chars]
            if chars is None
            else [list(row) for row in chars]
        )
        self._new_state = (
            obj.id if id is None else int(id),
            obj.name if name is None else name,
            obj.group if group is None else group,
            list(obj.tags) if tags is None else list(tags),
            obj.non_blockable if non_blockable is None else bool(non_blockable),
            new_w,
            new_h,
            new_chars,
        )

    def _apply(
        self,
        state: tuple[int, str, str, list[str], bool, int, int, list[list[int]]],
        prev_id: int,
    ) -> None:
        nid, nname, ngroup, ntags, nnb, nw, nh, nchars = state
        self._obj.id = nid
        self._obj.name = nname
        self._obj.group = ngroup
        self._obj.tags = list(ntags)
        self._obj.non_blockable = nnb
        self._obj.w = nw
        self._obj.h = nh
        self._obj.chars = [list(row) for row in nchars]
        if prev_id != nid:
            for room in self._project.rooms:
                for inst in room.instances:
                    if inst.object_id == prev_id:
                        inst.object_id = nid

    def execute(self) -> None:
        self._apply(self._new_state, self._old_state[0])

    def undo(self) -> None:
        self._apply(self._old_state, self._new_state[0])


# ---------------------------------------------------------------------------
# Tag commands
# ---------------------------------------------------------------------------


class AddTagCommand(Command):
    def __init__(self, project: Project, tag: str) -> None:
        self.description = f"Add tag '{tag}'"
        self._project = project
        self._tag = tag

    def execute(self) -> None:
        if self._tag not in self._project.tags:
            self._project.tags.append(self._tag)

    def undo(self) -> None:
        if self._tag in self._project.tags:
            self._project.tags.remove(self._tag)


class RenameTagCommand(Command):
    def __init__(self, project: Project, old_tag: str, new_tag: str) -> None:
        self.description = f"Rename tag '{old_tag}' -> '{new_tag}'"
        self._project = project
        self._old_tag = old_tag
        self._new_tag = new_tag
        self._old_tags = list(project.tags)
        self._old_obj_tags: dict[int, list[str]] = {}

    def execute(self) -> None:
        self._old_tags = list(self._project.tags)
        self._old_obj_tags = {o.id: list(o.tags) for o in self._project.objects}
        self._project.tags = [
            self._new_tag if t == self._old_tag else t for t in self._project.tags
        ]
        # Deduplicate while preserving order
        dedup: list[str] = []
        for t in self._project.tags:
            if t not in dedup:
                dedup.append(t)
        self._project.tags = dedup
        for obj in self._project.objects:
            if self._old_tag in obj.tags:
                updated = [self._new_tag if t == self._old_tag else t for t in obj.tags]
                obj.tags = list(dict.fromkeys(updated))

    def undo(self) -> None:
        self._project.tags = list(self._old_tags)
        for obj in self._project.objects:
            if obj.id in self._old_obj_tags:
                obj.tags = list(self._old_obj_tags[obj.id])


class DeleteTagCommand(Command):
    def __init__(self, project: Project, tag: str) -> None:
        self.description = f"Delete tag '{tag}'"
        self._project = project
        self._tag = tag
        self._old_tags: list[str] = []
        self._old_obj_tags: dict[int, list[str]] = {}

    def execute(self) -> None:
        self._old_tags = list(self._project.tags)
        self._old_obj_tags = {o.id: list(o.tags) for o in self._project.objects}
        self._project.tags = [t for t in self._project.tags if t != self._tag]
        for obj in self._project.objects:
            if self._tag in obj.tags:
                obj.tags = [t for t in obj.tags if t != self._tag]

    def undo(self) -> None:
        self._project.tags = list(self._old_tags)
        for obj in self._project.objects:
            if obj.id in self._old_obj_tags:
                obj.tags = list(self._old_obj_tags[obj.id])


# ---------------------------------------------------------------------------
# Teleport, Start, Settings commands
# ---------------------------------------------------------------------------


class AddTeleportCommand(Command):
    def __init__(self, project: Project, teleport: Teleport) -> None:
        self.description = "Add teleport"
        self._project = project
        self._teleport = teleport

    def execute(self) -> None:
        self._project.teleports.append(self._teleport)

    def undo(self) -> None:
        if self._teleport in self._project.teleports:
            self._project.teleports.remove(self._teleport)


class UpdateTeleportCommand(Command):
    def __init__(
        self,
        teleport: Teleport,
        new_a: TeleportEndpoint,
        new_b: TeleportEndpoint,
    ) -> None:
        self.description = "Edit teleport"
        self._teleport = teleport
        self._old_a = copy.deepcopy(teleport.a)
        self._old_b = copy.deepcopy(teleport.b)
        self._new_a = copy.deepcopy(new_a)
        self._new_b = copy.deepcopy(new_b)

    def execute(self) -> None:
        self._teleport.a = copy.deepcopy(self._new_a)
        self._teleport.b = copy.deepcopy(self._new_b)

    def undo(self) -> None:
        self._teleport.a = copy.deepcopy(self._old_a)
        self._teleport.b = copy.deepcopy(self._old_b)


class DeleteTeleportCommand(Command):
    def __init__(self, project: Project, index: int) -> None:
        self.description = "Delete teleport"
        self._project = project
        self._index = index
        self._removed: Teleport | None = None

    def execute(self) -> None:
        if 0 <= self._index < len(self._project.teleports):
            self._removed = self._project.teleports.pop(self._index)

    def undo(self) -> None:
        if self._removed is not None:
            idx = max(0, min(self._index, len(self._project.teleports)))
            self._project.teleports.insert(idx, self._removed)


class SetStartPositionCommand(Command):
    def __init__(self, project: Project, new_start: StartPosition | None) -> None:
        self.description = "Set start position"
        self._project = project
        self._old_start = copy.deepcopy(project.start)
        self._new_start = copy.deepcopy(new_start)

    def execute(self) -> None:
        self._project.start = copy.deepcopy(self._new_start)

    def undo(self) -> None:
        self._project.start = copy.deepcopy(self._old_start)


class UpdateDefaultPaletteCommand(Command):
    def __init__(self, project: Project, new_palette: Palette) -> None:
        self.description = "Update default palette"
        self._project = project
        self._old_palette = project.settings.default_palette.copy()
        self._new_palette = new_palette.copy()

    def execute(self) -> None:
        self._project.settings.default_palette = self._new_palette.copy()

    def undo(self) -> None:
        self._project.settings.default_palette = self._old_palette.copy()
