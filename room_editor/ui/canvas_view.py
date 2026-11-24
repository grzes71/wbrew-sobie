"""Room Canvas tab: grid-snapped room layout, room groups, passages, teleports, and start marker."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.commands import (
    AddRoomCommand,
    AddTeleportCommand,
    DeleteRoomCommand,
    DeleteTeleportCommand,
    MoveRoomsCommand,
    SetStartPositionCommand,
    UndoStack,
    UpdateRoomMetaCommand,
)
from room_editor.model.graph import (
    can_move_rooms,
    can_place_room_at,
    compute_edge_passages,
    compute_room_groups,
    get_adjacent_rooms,
    merge_passage_segments,
    room_group_map,
    snap_to_grid,
)
from room_editor.model.project import (
    MAX_ROOMS,
    ROOM_HEIGHT,
    ROOM_WIDTH,
    Project,
    Room,
)
from room_editor.ui.rendering_qt import QtRenderer
from room_editor.ui.teleport_dialog import StartPositionDialog, TeleportDialog

_GROUP_COLORS = [
    QColor(80, 190, 255),
    QColor(255, 175, 75),
    QColor(135, 225, 110),
    QColor(225, 120, 240),
    QColor(255, 110, 120),
    QColor(245, 225, 95),
    QColor(100, 225, 205),
    QColor(170, 155, 255),
]


class RoomCanvasScene(QWidget):
    """Interactive grid canvas showing all rooms, groups, passages, teleports, and start."""

    room_selected = Signal(int)
    room_double_clicked = Signal(int)
    teleport_rooms_picked = Signal(int, int)
    zoom_changed = Signal(float)

    BASE_CELL_W = 160
    BASE_CELL_H = 80

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._project = Project()
        self._undo_stack: UndoStack | None = None
        self._zoom = 1.0
        self._show_grid = True
        self._move_group_mode = False
        self._teleport_mode = False
        self._teleport_first_room: int | None = None
        self._selected_room_id: int | None = None

        # Canvas origin offset in grid units so negative coordinates stay visible
        self._origin_gx = -3
        self._origin_gy = -3
        self._grid_cols = 14
        self._grid_rows = 12

        # Drag state
        self._dragging_ids: set[int] = set()
        self._drag_start_px = QPoint()
        self._drag_dx_cells = 0
        self._drag_dy_cells = 0
        self._drag_valid = True

        self.setMouseTracking(True)
        self._update_widget_size()

    def set_context(self, project: Project, undo_stack: UndoStack) -> None:
        self._project = project
        self._undo_stack = undo_stack
        self._recompute_bounds()
        self.update()

    def set_selected_room(self, room_id: int | None) -> None:
        self._selected_room_id = room_id
        self.update()

    def set_show_grid(self, show: bool) -> None:
        self._show_grid = show
        self.update()

    def set_move_group_mode(self, enabled: bool) -> None:
        self._move_group_mode = enabled

    def set_teleport_mode(self, enabled: bool) -> None:
        self._teleport_mode = enabled
        self._teleport_first_room = None
        self.setCursor(
            Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.4, min(3.0, zoom))
        self._update_widget_size()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def _cell_w(self) -> float:
        return self.BASE_CELL_W * self._zoom

    def _cell_h(self) -> float:
        return self.BASE_CELL_H * self._zoom

    def _recompute_bounds(self) -> None:
        if not self._project.rooms:
            self._origin_gx, self._origin_gy = -3, -3
            self._grid_cols, self._grid_rows = 12, 10
        else:
            xs = [r.pos[0] for r in self._project.rooms]
            ys = [r.pos[1] for r in self._project.rooms]
            min_x, max_x = min(xs) - 3, max(xs) + 4
            min_y, max_y = min(ys) - 3, max(ys) + 4
            self._origin_gx = min(min_x, -2)
            self._origin_gy = min(min_y, -2)
            self._grid_cols = max(12, max_x - self._origin_gx + 1)
            self._grid_rows = max(10, max_y - self._origin_gy + 1)
        self._update_widget_size()

    def _update_widget_size(self) -> None:
        w = int(self._grid_cols * self._cell_w())
        h = int(self._grid_rows * self._cell_h())
        self.setMinimumSize(max(400, w), max(300, h))
        self.resize(max(400, w), max(300, h))

    def _grid_to_rect(self, gx: int, gy: int) -> QRectF:
        cw = self._cell_w()
        ch = self._cell_h()
        return QRectF((gx - self._origin_gx) * cw, (gy - self._origin_gy) * ch, cw, ch)

    def _room_at_point(self, pos: QPointF) -> Room | None:
        cw = self._cell_w()
        ch = self._cell_h()
        gx = int(pos.x() // cw) + self._origin_gx
        gy = int(pos.y() // ch) + self._origin_gy
        return self._project.get_room_at(gx, gy)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(28, 30, 36))

        cw = self._cell_w()
        ch = self._cell_h()

        # Grid
        if self._show_grid:
            painter.setPen(QPen(QColor(48, 52, 62), 1))
            for c in range(self._grid_cols + 1):
                x = c * cw
                painter.drawLine(QPointF(x, 0), QPointF(x, self._grid_rows * ch))
            for r in range(self._grid_rows + 1):
                y = r * ch
                painter.drawLine(QPointF(0, y), QPointF(self._grid_cols * cw, y))

        group_lookup = room_group_map(self._project)

        # Draw rooms
        for room in self._project.rooms:
            gx, gy = room.pos
            if room.id in self._dragging_ids:
                gx += self._drag_dx_cells
                gy += self._drag_dy_cells
            rect = self._grid_to_rect(gx, gy)

            thumb = self._renderer.render_room_image(self._project, room)
            painter.drawImage(rect, thumb)

            # Group color border (F-5)
            grp_idx = group_lookup.get(room.id, 0)
            border_color = _GROUP_COLORS[grp_idx % len(_GROUP_COLORS)]
            if room.id in self._dragging_ids and not self._drag_valid:
                border_color = QColor(240, 60, 60)
            pen_w = 3 if room.id == self._selected_room_id or room.id == self._teleport_first_room else 2
            painter.setPen(QPen(border_color, pen_w))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

            # Label badge
            label_rect = QRectF(rect.left() + 3, rect.top() + 3, rect.width() - 6, 18)
            painter.fillRect(label_rect, QColor(0, 0, 0, 165))
            painter.setPen(QColor(240, 240, 240))
            font = painter.font()
            font.setPointSize(8)
            font.setBold(room.id == self._selected_room_id)
            painter.setFont(font)
            painter.drawText(
                label_rect.adjusted(4, 0, -4, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"#{room.id} {room.name} [G{grp_idx + 1}]",
            )

        # Draw passage visualizations on shared edges (F-4, 3.6)
        drawn_edges: set[tuple[int, int]] = set()
        for room in self._project.rooms:
            if room.id in self._dragging_ids:
                continue
            for direction, nb in get_adjacent_rooms(self._project, room).items():
                if nb.id in self._dragging_ids:
                    continue
                pair = (min(room.id, nb.id), max(room.id, nb.id))
                if pair in drawn_edges:
                    continue
                drawn_edges.add(pair)
                passages = compute_edge_passages(self._project, room, nb)
                segments = merge_passage_segments(passages)
                rect = self._grid_to_rect(room.pos[0], room.pos[1])
                painter.setPen(QPen(QColor(70, 245, 110), max(3.0, 4.0 * self._zoom)))
                for start_i, end_i in segments:
                    if direction == "right":
                        x = rect.right()
                        y0 = rect.top() + (start_i / ROOM_HEIGHT) * ch
                        y1 = rect.top() + ((end_i + 1) / ROOM_HEIGHT) * ch
                        painter.drawLine(QPointF(x, y0), QPointF(x, y1))
                    elif direction == "left":
                        x = rect.left()
                        y0 = rect.top() + (start_i / ROOM_HEIGHT) * ch
                        y1 = rect.top() + ((end_i + 1) / ROOM_HEIGHT) * ch
                        painter.drawLine(QPointF(x, y0), QPointF(x, y1))
                    elif direction == "bottom":
                        y = rect.bottom()
                        x0 = rect.left() + (start_i / ROOM_WIDTH) * cw
                        x1 = rect.left() + ((end_i + 1) / ROOM_WIDTH) * cw
                        painter.drawLine(QPointF(x0, y), QPointF(x1, y))
                    elif direction == "top":
                        y = rect.top()
                        x0 = rect.left() + (start_i / ROOM_WIDTH) * cw
                        x1 = rect.left() + ((end_i + 1) / ROOM_WIDTH) * cw
                        painter.drawLine(QPointF(x0, y), QPointF(x1, y))

        # Draw bidirectional teleports (F-6)
        tp_pen = QPen(QColor(255, 95, 220), 2, Qt.PenStyle.DashLine)
        for tp in self._project.teleports:
            ra = self._project.get_room(tp.a.room_id)
            rb = self._project.get_room(tp.b.room_id)
            if ra is None or rb is None:
                continue
            pa = self._endpoint_pixel(ra, tp.a.x, tp.a.y)
            pb = self._endpoint_pixel(rb, tp.b.x, tp.b.y)
            painter.setPen(tp_pen)
            if ra.id == rb.id:
                # Self-loop arc inside/above room
                loop_rect = QRectF(
                    min(pa.x(), pb.x()) - 8,
                    min(pa.y(), pb.y()) - 18,
                    max(20.0, abs(pa.x() - pb.x()) + 16),
                    24.0,
                )
                painter.drawArc(loop_rect, 0, 180 * 16)
            else:
                painter.drawLine(pa, pb)
                self._draw_arrowhead(painter, pb, pa, QColor(255, 95, 220))
                self._draw_arrowhead(painter, pa, pb, QColor(255, 95, 220))
            painter.setBrush(QBrush(QColor(255, 95, 220)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(pa, 4, 4)
            painter.drawEllipse(pb, 4, 4)

        # Draw start icon (F-7)
        if self._project.start is not None:
            sr = self._project.get_room(self._project.start.room_id)
            if sr is not None:
                sp = self._endpoint_pixel(sr, self._project.start.x, self._project.start.y)
                painter.setBrush(QBrush(QColor(255, 220, 40)))
                painter.setPen(QPen(QColor(20, 20, 20), 1.5))
                painter.drawEllipse(sp, 7, 7)
                painter.drawText(
                    QRectF(sp.x() - 7, sp.y() - 7, 14, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    "S",
                )

        painter.end()

    def _endpoint_pixel(self, room: Room, x: int, y: int) -> QPointF:
        gx, gy = room.pos
        if room.id in self._dragging_ids:
            gx += self._drag_dx_cells
            gy += self._drag_dy_cells
        rect = self._grid_to_rect(gx, gy)
        return QPointF(
            rect.left() + ((x + 0.5) / ROOM_WIDTH) * rect.width(),
            rect.top() + ((y + 0.5) / ROOM_HEIGHT) * rect.height(),
        )

    @staticmethod
    def _draw_arrowhead(
        painter: QPainter,
        start: QPointF,
        end: QPointF,
        color: QColor,
    ) -> None:
        line_vec = end - start
        length = (line_vec.x() ** 2 + line_vec.y() ** 2) ** 0.5
        if length < 1e-3:
            return
        ux, uy = line_vec.x() / length, line_vec.y() / length
        px, py = -uy, ux
        size = 8.0
        p1 = end - QPointF(ux * size + px * size * 0.45, uy * size + py * size * 0.45)
        p2 = end - QPointF(ux * size - px * size * 0.45, uy * size - py * size * 0.45)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([end, p1, p2]))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        room = self._room_at_point(event.position())
        if room is None:
            return

        if self._teleport_mode:
            if self._teleport_first_room is None:
                self._teleport_first_room = room.id
                self._selected_room_id = room.id
                self.room_selected.emit(room.id)
                self.update()
            else:
                first = self._teleport_first_room
                second = room.id
                self.set_teleport_mode(False)
                self.teleport_rooms_picked.emit(first, second)
            return

        self._selected_room_id = room.id
        self.room_selected.emit(room.id)

        move_group = self._move_group_mode or bool(
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        if move_group:
            groups = compute_room_groups(self._project)
            grp = next((g for g in groups if room.id in g), [room.id])
            self._dragging_ids = set(grp)
        else:
            self._dragging_ids = {room.id}

        self._drag_start_px = event.position().toPoint()
        self._drag_dx_cells = 0
        self._drag_dy_cells = 0
        self._drag_valid = True
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._dragging_ids:
            return
        delta = event.position().toPoint() - self._drag_start_px
        dx_cells, dy_cells = snap_to_grid(delta.x(), delta.y(), self._cell_w(), self._cell_h())
        if dx_cells != self._drag_dx_cells or dy_cells != self._drag_dy_cells:
            self._drag_dx_cells = dx_cells
            self._drag_dy_cells = dy_cells
            self._drag_valid = can_move_rooms(
                self._project, self._dragging_ids, dx_cells, dy_cells
            )
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging_ids:
            return
        dx, dy = self._drag_dx_cells, self._drag_dy_cells
        moving = set(self._dragging_ids)
        self._dragging_ids.clear()
        self._drag_dx_cells = 0
        self._drag_dy_cells = 0

        if (dx != 0 or dy != 0) and self._undo_stack is not None:
            if can_move_rooms(self._project, moving, dx, dy):
                self._undo_stack.push_and_execute(
                    MoveRoomsCommand(self._project, moving, dx, dy)
                )
                self._recompute_bounds()
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            room = self._room_at_point(event.position())
            if room is not None:
                self.room_double_clicked.emit(room.id)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 1 / 1.15
            self.set_zoom(self._zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)


class RoomCanvasView(QWidget):
    """Tab widget pairing the interactive RoomCanvasScene with room/teleport controls."""

    open_room_requested = Signal(int)
    model_changed = Signal()

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._project = Project()
        self._undo_stack = UndoStack()
        self._selected_room_id: int | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)

        # Left: canvas + top bar
        left_col = QVBoxLayout()
        bar = QHBoxLayout()

        self._btn_add_room = QPushButton("+ Add Room")
        self._btn_add_room.clicked.connect(self._on_add_room)
        bar.addWidget(self._btn_add_room)

        self._btn_del_room = QPushButton("Delete Room")
        self._btn_del_room.clicked.connect(self._on_delete_room)
        bar.addWidget(self._btn_del_room)

        self._chk_move_group = QCheckBox("Move Whole Group (or Shift+Drag)")
        self._chk_move_group.toggled.connect(self._on_toggle_move_group)
        bar.addWidget(self._chk_move_group)

        self._btn_add_tp_mode = QPushButton("Add Teleport (Click 2 Rooms)")
        self._btn_add_tp_mode.setCheckable(True)
        self._btn_add_tp_mode.toggled.connect(self._on_toggle_teleport_mode)
        bar.addWidget(self._btn_add_tp_mode)

        self._btn_set_start = QPushButton("Set Hero Start...")
        self._btn_set_start.clicked.connect(self._on_set_start)
        bar.addWidget(self._btn_set_start)

        self._chk_grid = QCheckBox("Grid")
        self._chk_grid.setChecked(True)
        self._chk_grid.toggled.connect(self._on_toggle_grid)
        bar.addWidget(self._chk_grid)

        bar.addStretch()
        self._lbl_zoom = QLabel("100%")
        bar.addWidget(self._lbl_zoom)
        left_col.addLayout(bar)

        self._scene = RoomCanvasScene(self._renderer, self)
        self._scene.room_selected.connect(self._on_room_selected)
        self._scene.room_double_clicked.connect(self.open_room_requested)
        self._scene.teleport_rooms_picked.connect(self._on_teleport_rooms_picked)
        self._scene.zoom_changed.connect(lambda z: self._lbl_zoom.setText(f"{int(round(z * 100))}%"))

        scroll = QScrollArea()
        scroll.setWidget(self._scene)
        scroll.setWidgetResizable(False)
        left_col.addWidget(scroll, 1)
        root.addLayout(left_col, 3)

        # Right sidebar: selected room metadata + rooms list + teleports list
        side = QWidget()
        side.setMaximumWidth(310)
        side_layout = QVBoxLayout(side)

        room_box = QGroupBox("Selected Room")
        room_form = QFormLayout(room_box)
        self._spin_room_id = QSpinBox()
        self._spin_room_id.setRange(1, MAX_ROOMS)
        self._edit_room_name = QLineEdit()
        self._btn_apply_room = QPushButton("Apply Room Changes")
        self._btn_apply_room.clicked.connect(self._on_apply_room_meta)
        self._btn_open_room = QPushButton("Open in Room Editor")
        self._btn_open_room.clicked.connect(self._on_open_selected_room)
        room_form.addRow("ID (1..255):", self._spin_room_id)
        room_form.addRow("Name:", self._edit_room_name)
        room_form.addRow(self._btn_apply_room)
        room_form.addRow(self._btn_open_room)
        side_layout.addWidget(room_box)

        rooms_box = QGroupBox("Rooms & Groups")
        rooms_layout = QVBoxLayout(rooms_box)
        self._rooms_list = QListWidget()
        self._rooms_list.currentRowChanged.connect(self._on_rooms_list_changed)
        self._rooms_list.itemDoubleClicked.connect(self._on_open_selected_room)
        rooms_layout.addWidget(self._rooms_list)
        side_layout.addWidget(rooms_box, 1)

        tp_box = QGroupBox("Teleports")
        tp_layout = QVBoxLayout(tp_box)
        self._tp_list = QListWidget()
        tp_layout.addWidget(self._tp_list)
        tp_btns = QHBoxLayout()
        btn_tp_add = QPushButton("Add...")
        btn_tp_add.clicked.connect(self._on_add_teleport_dialog)
        btn_tp_edit = QPushButton("Edit...")
        btn_tp_edit.clicked.connect(self._on_edit_teleport)
        btn_tp_del = QPushButton("Delete")
        btn_tp_del.clicked.connect(self._on_delete_teleport)
        tp_btns.addWidget(btn_tp_add)
        tp_btns.addWidget(btn_tp_edit)
        tp_btns.addWidget(btn_tp_del)
        tp_layout.addLayout(tp_btns)
        side_layout.addWidget(tp_box, 1)

        root.addWidget(side, 1)

    def set_context(self, project: Project, undo_stack: UndoStack) -> None:
        self._project = project
        self._undo_stack = undo_stack
        self._scene.set_context(project, undo_stack)
        self.refresh()

    def set_grid_visible(self, visible: bool) -> None:
        self._chk_grid.setChecked(visible)

    def select_room(self, room_id: int) -> None:
        self._selected_room_id = room_id
        self._scene.set_selected_room(room_id)
        self._sync_room_fields()

    def refresh(self) -> None:
        self._scene.set_context(self._project, self._undo_stack)
        if self._selected_room_id is None or self._project.get_room(self._selected_room_id) is None:
            self._selected_room_id = self._project.rooms[0].id if self._project.rooms else None
        self._scene.set_selected_room(self._selected_room_id)

        groups = room_group_map(self._project)
        self._rooms_list.blockSignals(True)
        self._rooms_list.clear()
        for room in sorted(self._project.rooms, key=lambda r: r.id):
            grp_num = groups.get(room.id, 0) + 1
            item = QListWidgetItem(
                f"#{room.id} {room.name}  ({room.pos[0]}, {room.pos[1]})  [Group {grp_num}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, room.id)
            self._rooms_list.addItem(item)
            if room.id == self._selected_room_id:
                self._rooms_list.setCurrentItem(item)
        self._rooms_list.blockSignals(False)

        self._tp_list.clear()
        for idx, tp in enumerate(self._project.teleports):
            ra = self._project.get_room(tp.a.room_id)
            rb = self._project.get_room(tp.b.room_id)
            name_a = ra.name if ra else f"#{tp.a.room_id}"
            name_b = rb.name if rb else f"#{tp.b.room_id}"
            self._tp_list.addItem(
                f"{idx + 1}. {name_a}({tp.a.x},{tp.a.y}) <-> {name_b}({tp.b.x},{tp.b.y})"
            )

        self._sync_room_fields()

    def _sync_room_fields(self) -> None:
        room = self._project.get_room(self._selected_room_id) if self._selected_room_id is not None else None
        enabled = room is not None
        self._spin_room_id.setEnabled(enabled)
        self._edit_room_name.setEnabled(enabled)
        self._btn_apply_room.setEnabled(enabled)
        self._btn_open_room.setEnabled(enabled)
        self._btn_del_room.setEnabled(enabled)
        if room is not None:
            self._spin_room_id.setValue(room.id)
            self._edit_room_name.setText(room.name)
        else:
            self._edit_room_name.clear()

    def _on_room_selected(self, room_id: int) -> None:
        self._selected_room_id = room_id
        for i in range(self._rooms_list.count()):
            if self._rooms_list.item(i).data(Qt.ItemDataRole.UserRole) == room_id:
                self._rooms_list.blockSignals(True)
                self._rooms_list.setCurrentRow(i)
                self._rooms_list.blockSignals(False)
                break
        self._sync_room_fields()

    def _on_rooms_list_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self._rooms_list.item(row)
        room_id = item.data(Qt.ItemDataRole.UserRole)
        self._selected_room_id = room_id
        self._scene.set_selected_room(room_id)
        self._sync_room_fields()

    def _find_free_grid_cell(self) -> tuple[int, int]:
        # Spiral search around (0, 0)
        for radius in range(0, 30):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if can_place_room_at(self._project, dx, dy):
                        return dx, dy
        return len(self._project.rooms), 0

    def _on_add_room(self) -> None:
        new_id = self._project.next_free_room_id()
        if new_id is None:
            QMessageBox.warning(self, "Room Limit", f"Cannot exceed {MAX_ROOMS} rooms.")
            return
        gx, gy = self._find_free_grid_cell()
        default_group = self._project.object_groups[0].name if self._project.object_groups else ""
        room = Room(
            id=new_id,
            name=self._project.next_free_room_name(),
            pos=(gx, gy),
        )
        room.set_all_row_groups(default_group)
        self._undo_stack.push_and_execute(AddRoomCommand(self._project, room))
        self._selected_room_id = room.id
        self.model_changed.emit()

    def _on_delete_room(self) -> None:
        if self._selected_room_id is None:
            return
        room = self._project.get_room(self._selected_room_id)
        if room is None:
            return
        linked_tps = [
            tp
            for tp in self._project.teleports
            if tp.a.room_id == room.id or tp.b.room_id == room.id
        ]
        if linked_tps:
            ans = QMessageBox.question(
                self,
                "Delete Room",
                f"Room '{room.name}' has {len(linked_tps)} linked teleport(s). "
                "Deleting it will also remove those teleports. Continue?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._undo_stack.push_and_execute(DeleteRoomCommand(self._project, room.id))
        self._selected_room_id = None
        self.model_changed.emit()

    def _on_apply_room_meta(self) -> None:
        if self._selected_room_id is None:
            return
        room = self._project.get_room(self._selected_room_id)
        if room is None:
            return
        new_id = self._spin_room_id.value()
        new_name = self._edit_room_name.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Room name cannot be empty.")
            return
        for other in self._project.rooms:
            if other is not room:
                if other.id == new_id:
                    QMessageBox.warning(self, "Duplicate ID", f"Room ID {new_id} is already in use.")
                    return
                if other.name == new_name:
                    QMessageBox.warning(self, "Duplicate Name", f"Room name '{new_name}' is already in use.")
                    return
        if new_id == room.id and new_name == room.name:
            return
        self._undo_stack.push_and_execute(
            UpdateRoomMetaCommand(self._project, room, new_id, new_name)
        )
        self._selected_room_id = new_id
        self.model_changed.emit()

    def _on_open_selected_room(self) -> None:
        if self._selected_room_id is not None:
            self.open_room_requested.emit(self._selected_room_id)

    def _on_toggle_move_group(self, checked: bool) -> None:
        self._scene.set_move_group_mode(checked)

    def _on_toggle_grid(self, checked: bool) -> None:
        self._scene.set_show_grid(checked)

    def _on_toggle_teleport_mode(self, checked: bool) -> None:
        if checked and not self._project.rooms:
            self._btn_add_tp_mode.setChecked(False)
            QMessageBox.information(self, "Teleports", "Add at least one room first.")
            return
        self._scene.set_teleport_mode(checked)

    def _on_teleport_rooms_picked(self, room_a: int, room_b: int) -> None:
        self._btn_add_tp_mode.setChecked(False)
        dlg = TeleportDialog(
            self._project.rooms,
            initial_room_a=room_a,
            initial_room_b=room_b,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            tp = dlg.build_teleport()
            self._undo_stack.push_and_execute(AddTeleportCommand(self._project, tp))
            self.model_changed.emit()

    def _on_add_teleport_dialog(self) -> None:
        if not self._project.rooms:
            QMessageBox.information(self, "Teleports", "Create at least one room first.")
            return
        dlg = TeleportDialog(self._project.rooms, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._undo_stack.push_and_execute(
                AddTeleportCommand(self._project, dlg.build_teleport())
            )
            self.model_changed.emit()

    def _on_edit_teleport(self) -> None:
        row = self._tp_list.currentRow()
        if not (0 <= row < len(self._project.teleports)):
            return
        tp = self._project.teleports[row]
        dlg = TeleportDialog(self._project.rooms, teleport=tp, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            updated = dlg.build_teleport()
            from room_editor.model.commands import UpdateTeleportCommand

            self._undo_stack.push_and_execute(
                UpdateTeleportCommand(tp, updated.a, updated.b)
            )
            self.model_changed.emit()

    def _on_delete_teleport(self) -> None:
        row = self._tp_list.currentRow()
        if not (0 <= row < len(self._project.teleports)):
            return
        self._undo_stack.push_and_execute(DeleteTeleportCommand(self._project, row))
        self.model_changed.emit()

    def _on_set_start(self) -> None:
        if not self._project.rooms:
            QMessageBox.information(self, "Hero Start", "Create at least one room first.")
            return
        dlg = StartPositionDialog(self._project.rooms, self._project.start, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._undo_stack.push_and_execute(
                SetStartPositionCommand(self._project, dlg.build_start_position())
            )
            self.model_changed.emit()
