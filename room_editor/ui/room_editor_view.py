"""Room Editor tab: 40x24 layout editing, per-row groups, tools, and selection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.commands import (
    AddInstancesCommand,
    RemoveInstancesCommand,
    ReorderNonBlockableCommand,
    SetRoomRowGroupsCommand,
    UndoStack,
    ZOrderAction,
)
from room_editor.model.graph import compute_edge_passages, get_adjacent_rooms
from room_editor.model.palette import PalPaletteTable
from room_editor.model.project import (
    ROOM_HEIGHT,
    ROOM_WIDTH,
    GameObject,
    ObjectInstance,
    Project,
    Room,
    RowAssignment,
)
from room_editor.model.tools import (
    compute_fill_placements,
    compute_line_placements,
    compute_rect_placements,
)
from room_editor.ui.rendering_qt import CHAR_PX_H, CHAR_PX_W, QtRenderer

ToolName = Literal["stamp", "eraser", "fill", "line", "rect", "select"]


class RowGroupGutter(QWidget):
    """24-row interactive gutter showing each row's (group, palette) and color chip."""

    row_clicked = Signal(int, bool)  # (row_index, shift_held)

    def __init__(self, pal_table: PalPaletteTable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pal_table = pal_table
        self._project: Project | None = None
        self._room: Room | None = None
        self._zoom = 2
        self._selected_row: int | None = None
        self.setFixedWidth(196)
        self._update_height()

    def set_context(self, project: Project | None, room: Room | None) -> None:
        self._project = project
        self._room = room
        self.update()

    def set_zoom(self, zoom: int) -> None:
        self._zoom = zoom
        self._update_height()
        self.update()

    def set_selected_row(self, row: int | None) -> None:
        self._selected_row = row
        self.update()

    def _update_height(self) -> None:
        self.setFixedHeight(ROOM_HEIGHT * CHAR_PX_H * self._zoom)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(34, 36, 42))
        row_h = CHAR_PX_H * self._zoom
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)

        chip_w = 24
        for r in range(ROOM_HEIGHT):
            y = r * row_h
            rect = QRect(0, y, self.width() - 1, row_h)
            if r == self._selected_row:
                painter.fillRect(rect, QColor(65, 95, 145))
            elif r % 2 == 1:
                painter.fillRect(rect, QColor(40, 42, 50))
            painter.setPen(QColor(70, 74, 86))
            painter.drawRect(rect)

            ra = self._room.row_groups[r] if self._room else RowAssignment()
            grp = (
                self._project.get_group(ra.group)
                if self._project is not None and ra.group
                else None
            )
            pal = grp.get_palette(ra.palette) if grp is not None else None
            valid = grp is not None and pal is not None

            # Palette swatch chip (COLBK + 4 PF bars)
            chip_rect = QRect(3, y + 2, chip_w, max(4, row_h - 4))
            if valid and pal is not None:
                bg_rgb = self._pal_table.rgb(pal.colbk)
                painter.fillRect(chip_rect, QColor(*bg_rgb))
                sub_w = max(1, (chip_rect.width() - 2) // 4)
                for slot in range(1, 5):
                    s_rgb = self._pal_table.rgb(pal.color_for_slot(slot))
                    painter.fillRect(
                        chip_rect.left() + 1 + (slot - 1) * sub_w,
                        chip_rect.top() + 2,
                        sub_w,
                        max(2, chip_rect.height() - 4),
                        QColor(*s_rgb),
                    )
                painter.setPen(QColor(110, 115, 130))
                painter.drawRect(chip_rect)
            else:
                painter.fillRect(chip_rect, QColor(125, 50, 50))

            if not ra.group:
                label = f"{r:02d}: (none)"
            elif grp is not None and (not ra.palette or ra.palette == grp.default_palette_name):
                label = f"{r:02d}: {ra.group}"
            else:
                label = f"{r:02d}: {ra.group}/{ra.palette}"

            painter.setPen(QColor(225, 225, 230) if valid else QColor(235, 95, 95))
            painter.drawText(
                rect.adjusted(chip_w + 8, 0, -4, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            row = int(event.position().y() // (CHAR_PX_H * self._zoom))
            if 0 <= row < ROOM_HEIGHT:
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                self.row_clicked.emit(row, shift)


class RoomGridCanvas(QWidget):
    """40x24 interactive ANTIC 4 room layout canvas with tool previews and selection."""

    cursor_moved = Signal(int, int, int, str, str)  # (x, y, char_code, row_group, row_palette)
    zoom_changed = Signal(int)
    model_changed = Signal()

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._project = Project()
        self._undo_stack = UndoStack()
        self._room: Room | None = None
        self._active_object: GameObject | None = None
        self._tool: ToolName = "stamp"
        self._zoom = 2
        self._show_grid = True

        self._hover_cell: tuple[int, int] | None = None
        self._last_stamp_cell: tuple[int, int] | None = None
        self._drag_start_cell: tuple[int, int] | None = None
        self._drag_current_cell: tuple[int, int] | None = None
        self._selected_indices: set[int] = set()
        self._clipboard: list[tuple[int, int, int]] = []  # (object_id, dx, dy)
        self._frame_overrides: dict[int, int] = {}

        self.setMouseTracking(True)
        self._update_size()

    def set_frame_overrides(self, overrides: Mapping[int, int] | None) -> None:
        self._frame_overrides = dict(overrides) if overrides else {}
        self.update()

    def set_context(self, project: Project, undo_stack: UndoStack, room: Room | None) -> None:
        self._project = project
        self._undo_stack = undo_stack
        if self._room is not room:
            self._selected_indices.clear()
        self._room = room
        self.update()

    def set_active_object(self, obj: GameObject | None) -> None:
        self._active_object = obj
        self.update()

    def set_tool(self, tool: ToolName) -> None:
        self._tool = tool
        self._drag_start_cell = None
        self._drag_current_cell = None
        self.update()

    def set_show_grid(self, show: bool) -> None:
        self._show_grid = show
        self.update()

    def set_zoom(self, zoom: int) -> None:
        self._zoom = max(1, min(6, int(zoom)))
        self._update_size()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def selected_indices(self) -> set[int]:
        return set(self._selected_indices)

    def _cell_w(self) -> int:
        return CHAR_PX_W * self._zoom

    def _cell_h(self) -> int:
        return CHAR_PX_H * self._zoom

    def _update_size(self) -> None:
        self.setFixedSize(ROOM_WIDTH * self._cell_w(), ROOM_HEIGHT * self._cell_h())

    def _point_to_cell(self, pos) -> tuple[int, int]:
        cx = max(0, min(ROOM_WIDTH - 1, int(pos.x() // self._cell_w())))
        cy = max(0, min(ROOM_HEIGHT - 1, int(pos.y() // self._cell_h())))
        return cx, cy

    def _preview_instances(self) -> list[ObjectInstance]:
        if self._room is None or self._active_object is None:
            return []
        if self._tool == "stamp" and self._hover_cell is not None:
            return [ObjectInstance(self._active_object.id, self._hover_cell[0], self._hover_cell[1])]
        if self._tool == "line" and self._drag_start_cell and self._drag_current_cell:
            return compute_line_placements(
                self._project,
                self._room,
                self._active_object,
                self._drag_start_cell[0],
                self._drag_start_cell[1],
                self._drag_current_cell[0],
                self._drag_current_cell[1],
            )
        if self._tool == "rect" and self._drag_start_cell and self._drag_current_cell:
            return compute_rect_placements(
                self._project,
                self._room,
                self._active_object,
                self._drag_start_cell[0],
                self._drag_start_cell[1],
                self._drag_current_cell[0],
                self._drag_current_cell[1],
            )
        return []

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 24, 28))
        if self._room is None:
            painter.setPen(QColor(170, 170, 180))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No room selected.")
            painter.end()
            return

        cw = self._cell_w()
        ch = self._cell_h()

        # Render faithful ANTIC 4 room image (with optional UI-only animation frame overrides)
        room_img = self._renderer.render_room_image(
            self._project, self._room, frame_overrides=self._frame_overrides or None
        )
        painter.drawImage(self.rect(), room_img)

        # Grid overlay
        if self._show_grid:
            painter.setPen(QPen(QColor(255, 255, 255, 38), 1))
            for x in range(1, ROOM_WIDTH):
                painter.drawLine(x * cw, 0, x * cw, self.height())
            for y in range(1, ROOM_HEIGHT):
                painter.drawLine(0, y * ch, self.width(), y * ch)

        # Edge passage markers against adjacent rooms (F-4, 3.6)
        neighbors = get_adjacent_rooms(self._project, self._room)
        for direction, nb in neighbors.items():
            open_set = set(compute_edge_passages(self._project, self._room, nb))
            if direction in ("left", "right"):
                px = 0 if direction == "left" else self.width() - 4
                for y in range(ROOM_HEIGHT):
                    color = QColor(70, 240, 110, 200) if y in open_set else QColor(220, 60, 60, 150)
                    painter.fillRect(px, y * ch + 1, 4, ch - 2, color)
            else:
                py = 0 if direction == "top" else self.height() - 4
                for x in range(ROOM_WIDTH):
                    color = QColor(70, 240, 110, 200) if x in open_set else QColor(220, 60, 60, 150)
                    painter.fillRect(x * cw + 1, py, cw - 2, 4, color)

        # Teleport and Start overlays
        for tp in self._project.teleports:
            for ep in (tp.a, tp.b):
                if ep.room_id == self._room.id:
                    r = QRect(ep.x * cw + 2, ep.y * ch + 2, cw - 4, ch - 4)
                    painter.setPen(QPen(QColor(255, 95, 220), 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(r)

        if self._project.start and self._project.start.room_id == self._room.id:
            sx, sy = self._project.start.x, self._project.start.y
            r = QRect(sx * cw + 1, sy * ch + 1, cw - 2, ch - 2)
            painter.setPen(QPen(QColor(255, 225, 40), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(r)

        # Selected instances highlight
        objects_by_id = {o.id: o for o in self._project.objects}
        for idx in self._selected_indices:
            if 0 <= idx < len(self._room.instances):
                inst = self._room.instances[idx]
                obj = objects_by_id.get(inst.object_id)
                w_cells = obj.w if obj else 1
                h_cells = obj.h if obj else 1
                painter.setPen(QPen(QColor(90, 200, 255), 2))
                painter.setBrush(QBrush(QColor(90, 200, 255, 50)))
                painter.drawRect(inst.x * cw, inst.y * ch, w_cells * cw, h_cells * ch)

        # Select marquee
        if self._tool == "select" and self._drag_start_cell and self._drag_current_cell:
            x0 = min(self._drag_start_cell[0], self._drag_current_cell[0])
            y0 = min(self._drag_start_cell[1], self._drag_current_cell[1])
            x1 = max(self._drag_start_cell[0], self._drag_current_cell[0])
            y1 = max(self._drag_start_cell[1], self._drag_current_cell[1])
            painter.setPen(QPen(QColor(120, 210, 255), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(120, 210, 255, 40)))
            painter.drawRect(x0 * cw, y0 * ch, (x1 - x0 + 1) * cw, (y1 - y0 + 1) * ch)

        # Stamp / line / rect hover preview
        if self._active_object is not None:
            for inst in self._preview_instances():
                ok, _ = self._project.can_place_instance(
                    self._room, inst.object_id, inst.x, inst.y
                )
                color = QColor(80, 235, 120) if ok else QColor(245, 70, 70)
                painter.setPen(QPen(color, 2))
                painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
                painter.drawRect(
                    inst.x * cw,
                    inst.y * ch,
                    self._active_object.w * cw,
                    self._active_object.h * ch,
                )

        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._room is None:
            return
        cx, cy = self._point_to_cell(event.position())

        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint(), cx, cy)
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self._tool == "stamp" and self._active_object is not None:
            self._last_stamp_cell = (cx, cy)
            ok, _ = self._project.can_place_instance(self._room, self._active_object.id, cx, cy)
            if ok:
                self._undo_stack.push_and_execute(
                    AddInstancesCommand(
                        self._room,
                        [ObjectInstance(self._active_object.id, cx, cy)],
                        f"Stamp '{self._active_object.name}'",
                    )
                )
                self.model_changed.emit()
        elif self._tool == "eraser":
            idx = self._project.find_instance_at(self._room, cx, cy)
            if idx is not None:
                self._undo_stack.push_and_execute(
                    RemoveInstancesCommand(self._room, [idx], "Erase object")
                )
                self._selected_indices.clear()
                self.model_changed.emit()
        elif self._tool == "fill" and self._active_object is not None:
            items = compute_fill_placements(self._project, self._room, self._active_object, cx, cy)
            if items:
                self._undo_stack.push_and_execute(
                    AddInstancesCommand(
                        self._room,
                        items,
                        f"Fill '{self._active_object.name}' ({len(items)})",
                    )
                )
                self.model_changed.emit()
        elif self._tool in ("line", "rect", "select"):
            self._drag_start_cell = (cx, cy)
            self._drag_current_cell = (cx, cy)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._room is None:
            return
        cx, cy = self._point_to_cell(event.position())
        self._hover_cell = (cx, cy)
        if self._drag_start_cell is not None:
            self._drag_current_cell = (cx, cy)

        # Continuous drag stamping (once per cell entered) or erasing
        if event.buttons() & Qt.MouseButton.LeftButton:
            if self._tool == "stamp" and self._active_object is not None:
                if (cx, cy) != self._last_stamp_cell:
                    self._last_stamp_cell = (cx, cy)
                    ok, _ = self._project.can_place_instance(
                        self._room, self._active_object.id, cx, cy
                    )
                    if ok:
                        self._undo_stack.push_and_execute(
                            AddInstancesCommand(
                                self._room,
                                [ObjectInstance(self._active_object.id, cx, cy)],
                                f"Stamp '{self._active_object.name}'",
                            )
                        )
                        self.model_changed.emit()
            elif self._tool == "eraser":
                idx = self._project.find_instance_at(self._room, cx, cy)
                if idx is not None:
                    self._undo_stack.push_and_execute(
                        RemoveInstancesCommand(self._room, [idx], "Erase object")
                    )
                    self._selected_indices.clear()
                    self.model_changed.emit()

        grid = self._project.compose_room(self._room)
        char_code = grid[cy][cx]
        ra = self._room.row_groups[cy] if 0 <= cy < ROOM_HEIGHT else RowAssignment()
        self.cursor_moved.emit(cx, cy, char_code, ra.group, ra.palette)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._room is None:
            return
        self._last_stamp_cell = None
        if not (self._drag_start_cell and self._drag_current_cell):
            return

        x0, y0 = self._drag_start_cell
        x1, y1 = self._drag_current_cell
        self._drag_start_cell = None
        self._drag_current_cell = None

        if self._tool == "line" and self._active_object is not None:
            items = compute_line_placements(self._project, self._room, self._active_object, x0, y0, x1, y1)
            if items:
                self._undo_stack.push_and_execute(
                    AddInstancesCommand(self._room, items, f"Line '{self._active_object.name}'")
                )
                self.model_changed.emit()
        elif self._tool == "rect" and self._active_object is not None:
            items = compute_rect_placements(self._project, self._room, self._active_object, x0, y0, x1, y1)
            if items:
                self._undo_stack.push_and_execute(
                    AddInstancesCommand(self._room, items, f"Rectangle '{self._active_object.name}'")
                )
                self.model_changed.emit()
        elif self._tool == "select":
            if x0 == x1 and y0 == y1:
                top_idx = self._project.find_instance_at(self._room, x0, y0)
                self._selected_indices = {top_idx} if top_idx is not None else set()
                self.update()
                return
            rx0, rx1 = min(x0, x1), max(x0, x1)
            ry0, ry1 = min(y0, y1), max(y0, y1)
            selected: set[int] = set()
            objects_by_id = {o.id: o for o in self._project.objects}
            for idx, inst in enumerate(self._room.instances):
                obj = objects_by_id.get(inst.object_id)
                ow = obj.w if obj else 1
                oh = obj.h if obj else 1
                if (
                    inst.x + ow - 1 >= rx0
                    and inst.x <= rx1
                    and inst.y + oh - 1 >= ry0
                    and inst.y <= ry1
                ):
                    selected.add(idx)
            self._selected_indices = selected
            self.update()

    def _has_non_blockable(self, indices: set[int]) -> bool:
        if self._room is None:
            return False
        for idx in indices:
            if 0 <= idx < len(self._room.instances):
                obj = self._project.get_object(self._room.instances[idx].object_id)
                if obj is not None and obj.non_blockable:
                    return True
        return False

    def _show_context_menu(self, global_pos: QPoint, cx: int, cy: int) -> None:
        if self._room is None:
            return
        top_idx = self._project.find_instance_at(self._room, cx, cy)
        target_indices = (
            set(self._selected_indices)
            if self._has_non_blockable(self._selected_indices)
            else ({top_idx} if top_idx is not None else set())
        )
        can_reorder = self._has_non_blockable(target_indices)

        menu = QMenu(self)
        act_front = menu.addAction("Bring to Front\tCtrl+Shift+]")
        act_up = menu.addAction("Move Up\tCtrl+]")
        act_down = menu.addAction("Move Down\tCtrl+[")
        act_back = menu.addAction("Send to Back\tCtrl+Shift+[")
        for act in (act_front, act_up, act_down, act_back):
            act.setEnabled(can_reorder)

        menu.addSeparator()
        act_select = menu.addAction("Select Topmost Instance")
        act_erase = menu.addAction("Erase Topmost Instance")
        act_select.setEnabled(top_idx is not None)
        act_erase.setEnabled(top_idx is not None)

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen == act_front:
            self.reorder_selection("bring_to_front", target_indices)
        elif chosen == act_up:
            self.reorder_selection("move_up", target_indices)
        elif chosen == act_down:
            self.reorder_selection("move_down", target_indices)
        elif chosen == act_back:
            self.reorder_selection("send_to_back", target_indices)
        elif chosen == act_select and top_idx is not None:
            self._selected_indices = {top_idx}
            self.update()
        elif chosen == act_erase and top_idx is not None:
            self._undo_stack.push_and_execute(
                RemoveInstancesCommand(self._room, [top_idx], "Erase object")
            )
            self._selected_indices.clear()
            self.model_changed.emit()

    def reorder_selection(
        self,
        action: ZOrderAction,
        target_indices: set[int] | None = None,
    ) -> None:
        if self._room is None:
            return
        indices = set(self._selected_indices if target_indices is None else target_indices)
        if not indices:
            return
        cmd = ReorderNonBlockableCommand(self._project, self._room, indices, action)
        if cmd.has_change:
            self._undo_stack.push_and_execute(cmd)
            self._selected_indices = set(cmd.result_indices)
            self.model_changed.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            self.set_zoom(self._zoom + (1 if delta > 0 else -1))
            event.accept()
            return
        super().wheelEvent(event)

    def copy_selection(self) -> None:
        if self._room is None or not self._selected_indices:
            return
        chosen = [self._room.instances[i] for i in sorted(self._selected_indices) if i < len(self._room.instances)]
        if not chosen:
            return
        min_x = min(i.x for i in chosen)
        min_y = min(i.y for i in chosen)
        self._clipboard = [(i.object_id, i.x - min_x, i.y - min_y) for i in chosen]

    def cut_selection(self) -> None:
        if self._room is None or not self._selected_indices:
            return
        self.copy_selection()
        self.delete_selection()

    def paste_clipboard(self) -> None:
        if self._room is None or not self._clipboard:
            return
        ax, ay = self._hover_cell if self._hover_cell is not None else (0, 0)
        to_add: list[ObjectInstance] = []
        # Ensure pasted objects don't collide with existing room or each other
        temp_room = Room(
            id=self._room.id,
            name=self._room.name,
            pos=self._room.pos,
            row_groups=list(self._room.row_groups),
            instances=list(self._room.instances),
        )
        for obj_id, dx, dy in self._clipboard:
            px, py = ax + dx, ay + dy
            ok, _ = self._project.can_place_instance(temp_room, obj_id, px, py)
            if ok:
                inst = ObjectInstance(obj_id, px, py)
                to_add.append(inst)
                temp_room.instances.append(inst)
        if to_add:
            start_idx = len(self._room.instances)
            self._undo_stack.push_and_execute(
                AddInstancesCommand(self._room, to_add, f"Paste {len(to_add)} instance(s)")
            )
            self._selected_indices = set(range(start_idx, start_idx + len(to_add)))
            self.model_changed.emit()

    def delete_selection(self) -> None:
        if self._room is None or not self._selected_indices:
            return
        self._undo_stack.push_and_execute(
            RemoveInstancesCommand(self._room, sorted(self._selected_indices), "Delete selection")
        )
        self._selected_indices.clear()
        self.model_changed.emit()


class RoomEditorView(QWidget):
    """Tab widget for editing a single 40x24 room's layout and per-row (group, palette)."""

    cursor_status = Signal(int, int, int, str, str)
    model_changed = Signal()

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._project = Project()
        self._undo_stack = UndoStack()
        self._current_room_id: int | None = None
        self._last_clicked_row: int | None = None
        self._preview_palette_by_group: dict[str, str] = {}
        self._anim_counters: dict[int, int] = {}
        self._anim_frames: dict[int, int] = {}
        self._anim_passes: dict[int, int] = {}
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._on_anim_tick)

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)

        # Left Panel: Room selector, row-group/palette controls, filterable object palette
        left = QWidget()
        left.setMaximumWidth(330)
        left_layout = QVBoxLayout(left)

        left_layout.addWidget(QLabel("Active Room:"))
        self._room_combo = QComboBox()
        self._room_combo.currentIndexChanged.connect(self._on_room_combo_changed)
        left_layout.addWidget(self._room_combo)

        left_layout.addWidget(QLabel("Group & Palette for Row Assignment:"))
        self._row_group_combo = QComboBox()
        self._row_group_combo.currentIndexChanged.connect(self._on_row_group_combo_changed)
        self._row_palette_combo = QComboBox()
        row_grp_bar = QHBoxLayout()
        row_grp_bar.addWidget(self._row_group_combo, 1)
        row_grp_bar.addWidget(self._row_palette_combo, 1)
        left_layout.addLayout(row_grp_bar)

        btn_all_rows = QPushButton(f"Set All {ROOM_HEIGHT} Rows")
        btn_all_rows.clicked.connect(self._on_set_all_rows)
        left_layout.addWidget(btn_all_rows)

        hint_lbl = QLabel("Tip: Click a row in the left gutter to assign its (group, palette); Shift+Click for a range.")
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        left_layout.addWidget(hint_lbl)

        # Filters (F-20)
        filter_row = QHBoxLayout()
        self._filter_group = QComboBox()
        self._filter_group.currentIndexChanged.connect(self._on_filter_or_preview_changed)
        self._filter_tag = QComboBox()
        self._filter_tag.currentIndexChanged.connect(self._refresh_object_list)
        filter_row.addWidget(self._filter_group)
        filter_row.addWidget(self._filter_tag)
        left_layout.addLayout(filter_row)

        prev_row = QHBoxLayout()
        prev_row.addWidget(QLabel("Preview Palette:"))
        self._preview_pal_combo = QComboBox()
        self._preview_pal_combo.currentIndexChanged.connect(self._on_preview_pal_combo_changed)
        prev_row.addWidget(self._preview_pal_combo, 1)
        left_layout.addLayout(prev_row)

        left_layout.addWidget(QLabel("Objects:"))
        self._object_list = QListWidget()
        self._object_list.currentRowChanged.connect(self._on_object_selected)
        left_layout.addWidget(self._object_list, 1)

        root.addWidget(left, 1)

        # Center Panel: Tools bar + Gutter + 40x24 Canvas
        center = QVBoxLayout()
        tools_bar = QHBoxLayout()
        self._tool_group = QButtonGroup(self)
        self._tool_buttons: dict[ToolName, QPushButton] = {}
        for tool_id, label in (
            ("stamp", "Stamp (S)"),
            ("eraser", "Eraser (E)"),
            ("fill", "Fill (F)"),
            ("line", "Line (L)"),
            ("rect", "Rect (R)"),
            ("select", "Select (V)"),
        ):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, t=tool_id: self.set_tool(t))  # type: ignore[arg-type]
            self._tool_group.addButton(btn)
            self._tool_buttons[tool_id] = btn  # type: ignore[index]
            tools_bar.addWidget(btn)
        self._tool_buttons["stamp"].setChecked(True)

        self._chk_grid = QCheckBox("Grid (G)")
        self._chk_grid.setChecked(True)
        self._chk_grid.toggled.connect(self._on_toggle_grid)
        tools_bar.addWidget(self._chk_grid)

        self._chk_animate = QCheckBox("Animate preview")
        self._chk_animate.setChecked(False)
        self._chk_animate.setToolTip(
            "Play animated objects in this room at their PAL (50 Hz) animation speed (preview only)"
        )
        self._chk_animate.toggled.connect(self._on_toggle_animate_preview)
        tools_bar.addWidget(self._chk_animate)

        btn_zoom_out = QPushButton("-")
        btn_zoom_out.setFixedWidth(26)
        btn_zoom_out.clicked.connect(lambda: self._set_zoom(self._canvas._zoom - 1))
        btn_zoom_in = QPushButton("+")
        btn_zoom_in.setFixedWidth(26)
        btn_zoom_in.clicked.connect(lambda: self._set_zoom(self._canvas._zoom + 1))
        self._lbl_zoom = QLabel("2x")
        tools_bar.addWidget(btn_zoom_out)
        tools_bar.addWidget(self._lbl_zoom)
        tools_bar.addWidget(btn_zoom_in)
        tools_bar.addStretch()
        center.addLayout(tools_bar)

        editor_body = QHBoxLayout()
        editor_body.setSpacing(2)
        self._gutter = RowGroupGutter(self._renderer.pal_table, self)
        self._gutter.row_clicked.connect(self._on_gutter_row_clicked)
        self._canvas = RoomGridCanvas(self._renderer, self)
        self._canvas.cursor_moved.connect(self.cursor_status)
        self._canvas.zoom_changed.connect(self._on_canvas_zoom_changed)
        self._canvas.model_changed.connect(self.model_changed)

        editor_container = QWidget()
        container_layout = QHBoxLayout(editor_container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(4)
        container_layout.addWidget(self._gutter, 0, Qt.AlignmentFlag.AlignTop)
        container_layout.addWidget(self._canvas, 0, Qt.AlignmentFlag.AlignTop)
        container_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(editor_container)
        scroll.setWidgetResizable(True)
        editor_body.addWidget(scroll)
        center.addLayout(editor_body, 1)

        root.addLayout(center, 3)

    def set_context(self, project: Project, undo_stack: UndoStack) -> None:
        self._project = project
        self._undo_stack = undo_stack
        self.refresh()

    def set_current_room(self, room_id: int) -> None:
        self._current_room_id = room_id
        self.refresh()

    def set_tool(self, tool: ToolName) -> None:
        if tool in self._tool_buttons:
            self._tool_buttons[tool].setChecked(True)
        self._canvas.set_tool(tool)

    def set_grid_visible(self, visible: bool) -> None:
        self._chk_grid.setChecked(visible)

    def copy_selection(self) -> None:
        self._canvas.copy_selection()

    def cut_selection(self) -> None:
        self._canvas.cut_selection()

    def paste_clipboard(self) -> None:
        self._canvas.paste_clipboard()

    def delete_selection(self) -> None:
        self._canvas.delete_selection()

    def reorder_selection(self, action: ZOrderAction) -> None:
        self._canvas.reorder_selection(action)

    def refresh(self) -> None:
        # Rooms combo
        self._room_combo.blockSignals(True)
        self._room_combo.clear()
        for r in sorted(self._project.rooms, key=lambda rm: rm.id):
            self._room_combo.addItem(f"#{r.id}: {r.name}", r.id)
        if self._current_room_id is not None:
            for i in range(self._room_combo.count()):
                if self._room_combo.itemData(i) == self._current_room_id:
                    self._room_combo.setCurrentIndex(i)
                    break
        if self._room_combo.count() > 0 and self._room_combo.currentIndex() < 0:
            self._room_combo.setCurrentIndex(0)
        self._current_room_id = (
            int(self._room_combo.currentData()) if self._room_combo.count() > 0 else None
        )
        self._room_combo.blockSignals(False)

        # Row group & palette combos
        prev_row_grp = self._row_group_combo.currentData()
        prev_row_pal = self._row_palette_combo.currentData()
        self._row_group_combo.blockSignals(True)
        self._row_group_combo.clear()
        for grp in self._project.object_groups:
            self._row_group_combo.addItem(grp.name, grp.name)
        if prev_row_grp is not None:
            idx = self._row_group_combo.findData(prev_row_grp)
            if idx >= 0:
                self._row_group_combo.setCurrentIndex(idx)
        self._row_group_combo.blockSignals(False)
        self._populate_row_palette_combo(preferred=prev_row_pal)

        # Filter combos
        prev_fg = self._filter_group.currentData()
        self._filter_group.blockSignals(True)
        self._filter_group.clear()
        self._filter_group.addItem("All Groups", "")
        for grp in self._project.object_groups:
            self._filter_group.addItem(grp.name, grp.name)
        if prev_fg:
            idx = self._filter_group.findData(prev_fg)
            if idx >= 0:
                self._filter_group.setCurrentIndex(idx)
        self._filter_group.blockSignals(False)

        prev_ft = self._filter_tag.currentData()
        self._filter_tag.blockSignals(True)
        self._filter_tag.clear()
        self._filter_tag.addItem("All Tags", "")
        for tag in self._project.tags:
            self._filter_tag.addItem(tag, tag)
        if prev_ft:
            idx = self._filter_tag.findData(prev_ft)
            if idx >= 0:
                self._filter_tag.setCurrentIndex(idx)
        self._filter_tag.blockSignals(False)

        room = (
            self._project.get_room(self._current_room_id)
            if self._current_room_id is not None
            else None
        )
        self._gutter.set_context(self._project, room)
        self._canvas.set_context(self._project, self._undo_stack, room)
        self._reset_anim_preview_state()
        self._sync_animate_timer()
        self._sync_preview_pal_combo()
        self._refresh_object_list()
        self._sync_animate_timer()

    def set_preview_palette(self, group_name: str, palette_name: str) -> None:
        if group_name and palette_name:
            self._preview_palette_by_group[group_name] = palette_name
            self._sync_preview_pal_combo()
            self._refresh_object_list()

    def _populate_row_palette_combo(self, preferred: str | None = None) -> None:
        grp_name = self._row_group_combo.currentData()
        grp = self._project.get_group(grp_name) if grp_name else None
        self._row_palette_combo.blockSignals(True)
        self._row_palette_combo.clear()
        if grp is not None and grp.palettes:
            for pal in grp.palettes:
                self._row_palette_combo.addItem(pal.name, pal.name)
            idx = self._row_palette_combo.findData(preferred) if preferred else -1
            self._row_palette_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._row_palette_combo.setEnabled(True)
        else:
            self._row_palette_combo.setEnabled(False)
        self._row_palette_combo.blockSignals(False)

    def _on_row_group_combo_changed(self, _idx: int) -> None:
        # Preserve same-named palette if the newly selected group also defines it; else first palette
        prev_pal = self._row_palette_combo.currentData()
        self._populate_row_palette_combo(preferred=prev_pal)

    def _preview_target_group_name(self) -> str:
        fg = self._filter_group.currentData() or ""
        if fg:
            return str(fg)
        cur_item = self._object_list.currentItem()
        if cur_item is not None:
            obj = self._project.get_object(int(cur_item.data(Qt.ItemDataRole.UserRole)))
            if obj is not None:
                return obj.group
        return self._project.object_groups[0].name if self._project.object_groups else ""

    def _sync_preview_pal_combo(self) -> None:
        grp_name = self._preview_target_group_name()
        grp = self._project.get_group(grp_name) if grp_name else None
        self._preview_pal_combo.blockSignals(True)
        self._preview_pal_combo.clear()
        if grp is not None and grp.palettes:
            for p in grp.palettes:
                self._preview_pal_combo.addItem(p.name, p.name)
            pref = self._preview_palette_by_group.get(grp.name, grp.default_palette_name)
            idx = self._preview_pal_combo.findData(pref)
            self._preview_pal_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self._preview_pal_combo.setEnabled(True)
        else:
            self._preview_pal_combo.setEnabled(False)
        self._preview_pal_combo.blockSignals(False)

    def _on_filter_or_preview_changed(self, _idx: int) -> None:
        self._sync_preview_pal_combo()
        self._refresh_object_list()

    def _on_preview_pal_combo_changed(self, _idx: int) -> None:
        grp_name = self._preview_target_group_name()
        pal_name = self._preview_pal_combo.currentData() or ""
        if grp_name and pal_name:
            self._preview_palette_by_group[grp_name] = str(pal_name)
            self._refresh_object_list()

    def _refresh_object_list(self) -> None:
        selected_id = (
            self._object_list.currentItem().data(Qt.ItemDataRole.UserRole)
            if self._object_list.currentItem()
            else None
        )
        grp_filter = self._filter_group.currentData() or ""
        tag_filter = self._filter_tag.currentData() or ""

        self._object_list.blockSignals(True)
        self._object_list.clear()
        for obj in sorted(self._project.objects, key=lambda o: o.id):
            if grp_filter and obj.group != grp_filter:
                continue
            if tag_filter and tag_filter not in obj.tags:
                continue
            grp = self._project.get_group(obj.group)
            preview_pal = None
            if grp is not None:
                pal_name = self._preview_palette_by_group.get(grp.name, grp.default_palette_name)
                preview_pal = grp.get_palette(pal_name)
            pix = self._renderer.render_object_pixmap(
                obj, grp, scale=2, project=self._project, palette=preview_pal
            )
            flags = []
            if obj.non_blockable:
                flags.append("non-block")
            if obj.colpf3:
                flags.append("COLPF3")
            if self._project.object_placement_error(obj):
                flags.append("ERR")
            flag_str = f" [{' | '.join(flags)}]" if flags else ""
            item = QListWidgetItem(
                pix,
                f"#{obj.id} {obj.name} ({obj.w}x{obj.h}){flag_str}",
            )
            item.setData(Qt.ItemDataRole.UserRole, obj.id)
            self._object_list.addItem(item)
            if obj.id == selected_id:
                self._object_list.setCurrentItem(item)

        if self._object_list.currentRow() < 0 and self._object_list.count() > 0:
            self._object_list.setCurrentRow(0)
        self._object_list.blockSignals(False)
        self._on_object_selected(self._object_list.currentRow())

    def _on_room_combo_changed(self, _idx: int) -> None:
        data = self._room_combo.currentData()
        self._current_room_id = int(data) if data is not None else None
        room = (
            self._project.get_room(self._current_room_id)
            if self._current_room_id is not None
            else None
        )
        self._gutter.set_context(self._project, room)
        self._canvas.set_context(self._project, self._undo_stack, room)
        self._reset_anim_preview_state()
        self._sync_animate_timer()

    def _on_object_selected(self, row: int) -> None:
        if row < 0:
            self._canvas.set_active_object(None)
            return
        item = self._object_list.item(row)
        obj_id = int(item.data(Qt.ItemDataRole.UserRole))
        self._canvas.set_active_object(self._project.get_object(obj_id))
        if not (self._filter_group.currentData() or ""):
            self._sync_preview_pal_combo()

    def _on_gutter_row_clicked(self, row: int, shift_held: bool) -> None:
        room = (
            self._project.get_room(self._current_room_id)
            if self._current_room_id is not None
            else None
        )
        grp_name = self._row_group_combo.currentData()
        pal_name = self._row_palette_combo.currentData() or ""
        if room is None or not grp_name:
            return
        entry = RowAssignment(str(grp_name), str(pal_name))
        new_rows = list(room.row_groups)
        if shift_held and self._last_clicked_row is not None:
            lo = min(self._last_clicked_row, row)
            hi = max(self._last_clicked_row, row)
            for r in range(lo, hi + 1):
                new_rows[r] = entry
        else:
            new_rows[row] = entry
        self._last_clicked_row = row
        self._gutter.set_selected_row(row)
        if new_rows != room.row_groups:
            self._undo_stack.push_and_execute(SetRoomRowGroupsCommand(room, new_rows))
            self.model_changed.emit()

    def _on_set_all_rows(self) -> None:
        room = (
            self._project.get_room(self._current_room_id)
            if self._current_room_id is not None
            else None
        )
        grp_name = self._row_group_combo.currentData()
        pal_name = self._row_palette_combo.currentData() or ""
        if room is None or not grp_name:
            return
        new_rows = [RowAssignment(str(grp_name), str(pal_name))] * ROOM_HEIGHT
        if new_rows != room.row_groups:
            self._undo_stack.push_and_execute(SetRoomRowGroupsCommand(room, new_rows))
            self.model_changed.emit()

    def _on_toggle_grid(self, checked: bool) -> None:
        self._canvas.set_show_grid(checked)

    def _reset_anim_preview_state(self) -> None:
        self._anim_counters.clear()
        self._anim_frames.clear()
        self._anim_passes.clear()
        self._canvas.set_frame_overrides(None)

    def _active_room_anim_objects(self) -> list[GameObject]:
        if self._current_room_id is None:
            return []
        room = self._project.get_room(self._current_room_id)
        if room is None:
            return []
        obj_ids = sorted({inst.object_id for inst in room.instances})
        res: list[GameObject] = []
        for oid in obj_ids:
            obj = self._project.get_object(oid)
            if obj is not None and obj.is_animated:
                res.append(obj)
        return res

    def _sync_animate_timer(self) -> None:
        if not self._chk_animate.isChecked():
            self._anim_timer.stop()
            self._reset_anim_preview_state()
            return
        anim_objs = self._active_room_anim_objects()
        if not anim_objs:
            self._anim_timer.stop()
            self._canvas.set_frame_overrides(None)
            return
        active_ids = {o.id for o in anim_objs}
        for stale in [oid for oid in self._anim_counters if oid not in active_ids]:
            self._anim_counters.pop(stale, None)
            self._anim_frames.pop(stale, None)
            self._anim_passes.pop(stale, None)
        for obj in anim_objs:
            if obj.id not in self._anim_counters:
                self._anim_counters[obj.id] = obj.effective_frame_duration(0)
                self._anim_frames[obj.id] = 0
                self._anim_passes[obj.id] = obj.initial_pass_counter()
        self._canvas.set_frame_overrides(self._anim_frames)
        if not self._anim_timer.isActive():
            self._anim_timer.start(20)  # PAL 50 Hz ticks

    def _on_toggle_animate_preview(self, _checked: bool) -> None:
        self._reset_anim_preview_state()
        self._sync_animate_timer()

    def _on_anim_tick(self) -> None:
        anim_objs = self._active_room_anim_objects()
        if not anim_objs or not self._chk_animate.isChecked():
            self._sync_animate_timer()
            return
        changed = False
        for obj in anim_objs:
            cur_f = self._anim_frames.get(obj.id, 0)
            cur_p = self._anim_passes.get(obj.id, 0)
            cnt = self._anim_counters.get(obj.id, obj.effective_frame_duration(cur_f)) - 1
            if cnt <= 0:
                next_f, next_p = obj.step_animation_frame(cur_f, cur_p)
                self._anim_frames[obj.id] = next_f
                self._anim_passes[obj.id] = next_p
                cnt = obj.effective_frame_duration(next_f)
                changed = True
            self._anim_counters[obj.id] = cnt
        if changed:
            self._canvas.set_frame_overrides(self._anim_frames)

    def _set_zoom(self, zoom: int) -> None:
        self._canvas.set_zoom(zoom)

    def _on_canvas_zoom_changed(self, zoom: int) -> None:
        self._gutter.set_zoom(zoom)
        self._lbl_zoom.setText(f"{zoom}x")
