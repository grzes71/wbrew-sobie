"""Stamp Image widget: 2:1 PNG view, 4x8 grid, drag selection, COLPF3 & palette preview."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.glyphs import (
    MAX_FRAME_DURATION,
    MAX_GLYPHS_PER_GROUP,
    MAX_GROUP_REPEAT,
    MAX_OBJECT_FRAMES,
    StampRegion,
)
from room_editor.model.palette import Palette
from room_editor.model.project import GameObject, ObjectGroup, Project
from room_editor.ui.rendering_qt import CHAR_PX_H, CHAR_PX_W, QtRenderer


class StampImageCanvas(QWidget):
    """Interactive 2:1 ANTIC 4 PNG canvas with 4x8 grid overlay and snapped region selection."""

    selection_changed = Signal(object)  # StampRegion
    zoom_changed = Signal(int)

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._project = Project()
        self._group: ObjectGroup | None = None
        self._selected_object: GameObject | None = None
        self._selection: StampRegion | None = None
        self._preview_palette_name: str = ""
        self._zoom = 3
        self._show_grid = True
        self._preview_colpf3 = False
        self._use_file_palette = False
        self._drag_anchor: tuple[int, int] | None = None
        self._update_size()

    def set_data(
        self,
        project: Project,
        group: ObjectGroup | None,
        selected_object: GameObject | None,
        preview_palette_name: str = "",
    ) -> None:
        self._project = project
        group_changed = self._group is not group
        self._group = group
        self._selected_object = selected_object
        self._preview_palette_name = preview_palette_name
        if selected_object is not None and group is not None and selected_object.group == group.name:
            self._selection = selected_object.region
        elif group_changed or self._selection is None:
            if group is not None and group.image is not None:
                self._selection = StampRegion(0, 0, 1, 1)
            else:
                self._selection = None
        self._update_size()
        self.update()

    def set_preview_palette_name(self, name: str) -> None:
        self._preview_palette_name = name
        self.update()

    def set_selection(self, region: StampRegion | None) -> None:
        self._selection = (
            StampRegion(region.x, region.y, region.w, region.h) if region is not None else None
        )
        self.update()

    def selection(self) -> StampRegion | None:
        return self._selection

    def set_zoom(self, zoom: int) -> None:
        self._zoom = max(1, min(6, int(zoom)))
        self._update_size()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def set_show_grid(self, visible: bool) -> None:
        self._show_grid = bool(visible)
        self.update()

    def set_preview_colpf3(self, enabled: bool) -> None:
        self._preview_colpf3 = bool(enabled)
        self.update()

    def set_use_file_palette(self, enabled: bool) -> None:
        self._use_file_palette = bool(enabled)
        self.update()

    def _cell_w(self) -> int:
        return CHAR_PX_W * self._zoom

    def _cell_h(self) -> int:
        return CHAR_PX_H * self._zoom

    def _update_size(self) -> None:
        if self._group is None or self._group.image is None:
            self.setFixedSize(260, 180)
        else:
            img = self._group.image
            self.setFixedSize(img.glyph_cols * self._cell_w(), img.glyph_rows * self._cell_h())

    def _point_to_glyph(self, pos) -> tuple[int, int] | None:
        if self._group is None or self._group.image is None:
            return None
        img = self._group.image
        gx = max(0, min(img.glyph_cols - 1, int(pos.x() // self._cell_w())))
        gy = max(0, min(img.glyph_rows - 1, int(pos.y() // self._cell_h())))
        return gx, gy

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(28, 28, 32))
        if self._group is None or self._group.image is None:
            msg = "No PNG loaded for this group"
            if self._group is not None and self._group.image_status == "missing":
                msg = f"Missing PNG:\n{self._group.image_path}"
            elif self._group is not None and self._group.image_status == "invalid":
                msg = f"Invalid PNG:\n{self._group.image_error}"
            painter.setPen(QColor(180, 160, 160))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, msg)
            painter.end()
            return

        img = self._group.image
        pal = (
            self._group.get_palette(self._preview_palette_name)
            or self._group.default_palette
            or Palette()
        )
        qimg = self._renderer.indexed_image_qimage(
            img,
            pal,
            self._group.pixel_mapping,
            colpf3=self._preview_colpf3,
            use_file_palette=self._use_file_palette,
        )
        painter.drawImage(self.rect(), qimg)

        cw = self._cell_w()
        ch = self._cell_h()

        if self._show_grid:
            painter.setPen(QPen(QColor(255, 255, 255, 55), 1))
            for c in range(1, img.glyph_cols):
                painter.drawLine(c * cw, 0, c * cw, self.height())
            for r in range(1, img.glyph_rows):
                painter.drawLine(0, r * ch, self.width(), r * ch)

        for obj in self._project.objects:
            if obj.group != self._group.name:
                continue
            if self._selected_object is not None and obj.id == self._selected_object.id:
                for f_idx, r in enumerate(obj.frames):
                    rect = QRect(r.x * cw, r.y * ch, r.w * cw, r.h * ch)
                    color = QColor(255, 215, 65) if f_idx == 0 else QColor(255, 145, 50)
                    painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(rect.adjusted(1, 1, -1, -1))
                    if obj.frame_count > 1:
                        badge = QRect(r.x * cw + 2, r.y * ch + 2, 18, 12)
                        painter.fillRect(badge, QColor(0, 0, 0, 175))
                        painter.setPen(color)
                        font = painter.font()
                        font.setPointSize(7)
                        painter.setFont(font)
                        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"F{f_idx}")
            else:
                r = obj.region
                rect = QRect(r.x * cw, r.y * ch, r.w * cw, r.h * ch)
                painter.setPen(QPen(QColor(160, 180, 210, 150), 1, Qt.PenStyle.DotLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect.adjusted(1, 1, -1, -1))

        if self._selection is not None:
            s = self._selection
            rect = QRect(s.x * cw, s.y * ch, s.w * cw, s.h * ch)
            painter.setPen(QPen(QColor(70, 225, 255), 2))
            painter.setBrush(QBrush(QColor(70, 225, 255, 45)))
            painter.drawRect(rect.adjusted(1, 1, -1, -1))

        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pt = self._point_to_glyph(event.position())
        if pt is None:
            return
        self._drag_anchor = pt
        self._selection = StampRegion(pt[0], pt[1], 1, 1)
        self.selection_changed.emit(self._selection)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_anchor is None:
            return
        pt = self._point_to_glyph(event.position())
        if pt is None:
            return
        x0 = min(self._drag_anchor[0], pt[0])
        y0 = min(self._drag_anchor[1], pt[1])
        x1 = max(self._drag_anchor[0], pt[0])
        y1 = max(self._drag_anchor[1], pt[1])
        new_sel = StampRegion(x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        if new_sel != self._selection:
            self._selection = new_sel
            self.selection_changed.emit(new_sel)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_anchor = None

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            self.set_zoom(self._zoom + (1 if delta > 0 else -1))
            event.accept()
            return
        super().wheelEvent(event)


class StampImageWidget(QWidget):
    """Stamp Image panel with zoom, 4x8 grid, COLPF3/palette preview, and animation frames."""

    create_object_requested = Signal(object)  # StampRegion
    apply_region_requested = Signal(object)  # StampRegion
    add_frame_requested = Signal(object)  # StampRegion
    replace_frame_requested = Signal(int, object)  # (frame_idx, StampRegion)
    remove_frame_requested = Signal(int)  # frame_idx
    reorder_frame_requested = Signal(int, int)  # (from_idx, to_idx)
    frame_duration_changed = Signal(int, int)  # (frame_idx, duration)
    group_frames_requested = Signal(int, int, int)  # (first, last, repeat)
    ungroup_frames_requested = Signal(int)  # group_index
    group_repeat_changed = Signal(int, int)  # (group_index, repeat)
    move_group_requested = Signal(int, int)  # (group_index, direction)
    selection_changed = Signal(object)  # StampRegion
    preview_palette_changed = Signal(str)  # palette name (UI-only preview choice)

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._project = Project()
        self._group: ObjectGroup | None = None
        self._selected_object: GameObject | None = None
        self._selected_frame_idx: int = 0
        self._block_pal_signal = False
        self._block_frame_signal = False
        self._preview_playing = False
        self._preview_frame_idx = 0
        self._preview_pass_counter = 0

        self._anim_timer = QTimer(self)
        self._anim_timer.setSingleShot(True)
        self._anim_timer.timeout.connect(self._on_anim_timer_tick)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        bar = QHBoxLayout()
        btn_out = QPushButton("-")
        btn_out.setFixedWidth(26)
        btn_out.clicked.connect(lambda: self._canvas.set_zoom(self._canvas._zoom - 1))
        self._lbl_zoom = QLabel("3x")
        btn_in = QPushButton("+")
        btn_in.setFixedWidth(26)
        btn_in.clicked.connect(lambda: self._canvas.set_zoom(self._canvas._zoom + 1))

        self._chk_grid = QCheckBox("4×8 Grid")
        self._chk_grid.setChecked(True)
        self._chk_colpf3 = QCheckBox("Preview with COLPF3")
        self._chk_file_pal = QCheckBox("As in file")

        bar.addWidget(QLabel("Zoom:"))
        bar.addWidget(btn_out)
        bar.addWidget(self._lbl_zoom)
        bar.addWidget(btn_in)
        bar.addWidget(self._chk_grid)
        bar.addWidget(self._chk_colpf3)
        bar.addWidget(self._chk_file_pal)
        bar.addWidget(QLabel("Preview Palette:"))
        self._combo_preview_pal = QComboBox()
        self._combo_preview_pal.currentIndexChanged.connect(self._on_preview_pal_changed)
        bar.addWidget(self._combo_preview_pal)
        bar.addStretch()
        layout.addLayout(bar)

        self._lbl_group_counter = QLabel("Group glyphs: 0/127")
        layout.addWidget(self._lbl_group_counter)

        self._lbl_sel_counter = QLabel("Selection: (none)")
        self._lbl_sel_counter.setWordWrap(True)
        layout.addWidget(self._lbl_sel_counter)

        self._canvas = StampImageCanvas(self._renderer, self)
        self._canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self._canvas.zoom_changed.connect(lambda z: self._lbl_zoom.setText(f"{z}x"))

        self._chk_grid.toggled.connect(self._canvas.set_show_grid)
        self._chk_colpf3.toggled.connect(self._on_colpf3_toggled)
        self._chk_file_pal.toggled.connect(self._on_file_pal_toggled)

        scroll = QScrollArea()
        scroll.setWidget(self._canvas)
        scroll.setWidgetResizable(False)
        layout.addWidget(scroll, 1)

        actions = QHBoxLayout()
        self._btn_create = QPushButton("+ Create Object from Selection")
        self._btn_create.clicked.connect(self._on_primary_action_clicked)
        self._btn_apply_region = QPushButton("Update Selected Object Region")
        self._btn_apply_region.clicked.connect(self._on_apply_region_clicked)
        actions.addWidget(self._btn_create)
        actions.addWidget(self._btn_apply_region)
        layout.addLayout(actions)

        # Animation Frames panel
        self._frames_box = QGroupBox("Object Frames")
        frames_layout = QVBoxLayout(self._frames_box)

        top_frames_bar = QHBoxLayout()
        self._lbl_frame_counter = QLabel("0/16")
        top_frames_bar.addWidget(self._lbl_frame_counter)
        self._lbl_loop_total = QLabel("Loop: off")
        self._lbl_loop_total.setStyleSheet("color: #aaa;")
        top_frames_bar.addWidget(self._lbl_loop_total)
        top_frames_bar.addStretch()
        self._btn_play_preview = QPushButton("▶ Play Preview")
        self._btn_play_preview.clicked.connect(self._on_toggle_play_preview)
        top_frames_bar.addWidget(self._btn_play_preview)
        self._lbl_anim_preview = QLabel()
        self._lbl_anim_preview.setMinimumSize(32, 32)
        self._lbl_anim_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_anim_preview.setStyleSheet("border: 1px solid #444; background: #1c1c20;")
        top_frames_bar.addWidget(self._lbl_anim_preview)
        frames_layout.addLayout(top_frames_bar)

        self._frame_list = QListWidget()
        self._frame_list.setFlow(QListView.Flow.LeftToRight)
        self._frame_list.setWrapping(False)
        self._frame_list.setIconSize(QSize(48, 48))
        self._frame_list.setMaximumHeight(92)
        self._frame_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._frame_list.currentRowChanged.connect(self._on_frame_list_row_changed)
        self._frame_list.itemSelectionChanged.connect(self._on_frame_selection_changed)
        frames_layout.addWidget(self._frame_list)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Frame time:"))
        self._spin_frame_duration = QSpinBox()
        self._spin_frame_duration.setRange(0, MAX_FRAME_DURATION)
        self._spin_frame_duration.setValue(0)
        self._spin_frame_duration.setToolTip(
            "ticks of 1/50 s this frame stays visible; 0 = use the object's animation speed"
        )
        self._spin_frame_duration.valueChanged.connect(self._on_frame_duration_spin_changed)
        dur_row.addWidget(self._spin_frame_duration)
        self._lbl_frame_effective_time = QLabel("")
        self._lbl_frame_effective_time.setStyleSheet("color: #bbb;")
        dur_row.addWidget(self._lbl_frame_effective_time, 1)
        frames_layout.addLayout(dur_row)

        grp_row = QHBoxLayout()
        self._btn_group_frames = QPushButton("Group frames")
        self._btn_group_frames.setToolTip("Group >= 2 selected consecutive ungrouped frames")
        self._btn_group_frames.clicked.connect(self._on_group_frames_clicked)
        grp_row.addWidget(self._btn_group_frames)
        grp_row.addWidget(QLabel("Loop repeat:"))
        self._spin_group_repeat = QSpinBox()
        self._spin_group_repeat.setRange(1, MAX_GROUP_REPEAT)
        self._spin_group_repeat.setValue(1)
        self._spin_group_repeat.setToolTip(
            "number of passes through this group before continuing; 1 = once"
        )
        self._spin_group_repeat.valueChanged.connect(self._on_group_repeat_spin_changed)
        grp_row.addWidget(self._spin_group_repeat)
        self._btn_select_group = QPushButton("Select Group")
        self._btn_select_group.clicked.connect(self._on_select_group_clicked)
        grp_row.addWidget(self._btn_select_group)
        self._btn_ungroup = QPushButton("Ungroup")
        self._btn_ungroup.clicked.connect(self._on_ungroup_clicked)
        grp_row.addWidget(self._btn_ungroup)
        frames_layout.addLayout(grp_row)

        frame_btns = QHBoxLayout()
        self._btn_replace_frame = QPushButton("Replace Frame")
        self._btn_replace_frame.clicked.connect(self._on_replace_frame_clicked)
        self._btn_move_frame_left = QPushButton("Move Left")
        self._btn_move_frame_left.clicked.connect(lambda: self._on_reorder_frame(-1))
        self._btn_move_frame_right = QPushButton("Move Right")
        self._btn_move_frame_right.clicked.connect(lambda: self._on_reorder_frame(1))
        self._btn_remove_frame = QPushButton("Remove Frame")
        self._btn_remove_frame.clicked.connect(self._on_remove_frame_clicked)
        frame_btns.addWidget(self._btn_replace_frame)
        frame_btns.addWidget(self._btn_move_frame_left)
        frame_btns.addWidget(self._btn_move_frame_right)
        frame_btns.addWidget(self._btn_remove_frame)
        frames_layout.addLayout(frame_btns)

        layout.addWidget(self._frames_box)

    def set_data(
        self,
        project: Project,
        group: ObjectGroup | None,
        selected_object: GameObject | None,
        preview_palette_name: str = "",
    ) -> None:
        prev_obj_id = self._selected_object.id if self._selected_object is not None else None
        self._project = project
        self._group = group
        self._selected_object = selected_object

        if selected_object is None or selected_object.id != prev_obj_id:
            self._selected_frame_idx = 0
            self._stop_preview()
        elif selected_object.frames:
            self._selected_frame_idx = max(
                0, min(self._selected_frame_idx, len(selected_object.frames) - 1)
            )

        self._block_pal_signal = True
        try:
            self._combo_preview_pal.clear()
            if group is not None and group.palettes:
                for p in group.palettes:
                    self._combo_preview_pal.addItem(p.name, p.name)
                idx = self._combo_preview_pal.findData(preview_palette_name)
                if idx >= 0:
                    self._combo_preview_pal.setCurrentIndex(idx)
                elif self._combo_preview_pal.count() > 0:
                    self._combo_preview_pal.setCurrentIndex(0)
                self._combo_preview_pal.setEnabled(not self._chk_file_pal.isChecked())
            else:
                self._combo_preview_pal.setEnabled(False)
            active_pal = self._combo_preview_pal.currentData() or ""
        finally:
            self._block_pal_signal = False

        self._canvas.set_data(project, group, selected_object, active_pal)
        self._refresh_frames_panel()
        self._refresh_counters()

    def set_selected_frame_index(self, index: int) -> None:
        if self._selected_object is None or not self._selected_object.frames:
            self._selected_frame_idx = 0
            return
        self._selected_frame_idx = max(
            0, min(int(index), len(self._selected_object.frames) - 1)
        )
        self._refresh_frames_panel()

    def set_preview_palette(self, name: str) -> None:
        self._block_pal_signal = True
        try:
            idx = self._combo_preview_pal.findData(name)
            if idx >= 0:
                self._combo_preview_pal.setCurrentIndex(idx)
                self._canvas.set_preview_palette_name(name)
        finally:
            self._block_pal_signal = False
        self._refresh_frames_panel()

    def preview_palette_name(self) -> str:
        return str(self._combo_preview_pal.currentData() or "")

    def set_selection(self, region: StampRegion | None) -> None:
        self._canvas.set_selection(region)
        self._refresh_counters()

    def current_selection(self) -> StampRegion | None:
        return self._canvas.selection()

    def _on_preview_pal_changed(self, _idx: int) -> None:
        if self._block_pal_signal:
            return
        name = self.preview_palette_name()
        self._canvas.set_preview_palette_name(name)
        self._refresh_frames_panel()
        self.preview_palette_changed.emit(name)

    def _on_colpf3_toggled(self, checked: bool) -> None:
        self._canvas.set_preview_colpf3(checked)
        self._refresh_frames_panel()

    def _on_file_pal_toggled(self, checked: bool) -> None:
        self._chk_colpf3.setEnabled(not checked)
        self._combo_preview_pal.setEnabled(not checked and self._combo_preview_pal.count() > 0)
        self._canvas.set_use_file_palette(checked)
        self._refresh_frames_panel()

    def _on_canvas_selection_changed(self, region: StampRegion) -> None:
        self._refresh_counters()
        self.selection_changed.emit(region)

    def _has_selected_obj_in_group(self) -> bool:
        return (
            self._selected_object is not None
            and self._group is not None
            and self._selected_object.group == self._group.name
        )

    def _refresh_counters(self) -> None:
        if self._group is None or self._group.image is None:
            self._lbl_group_counter.setText("Group glyphs: 0/127 (no PNG loaded)")
            self._lbl_sel_counter.setStyleSheet("color: #aaa;")
            self._lbl_sel_counter.setText("Load an indexed PNG to select stamp regions.")
            self._btn_create.setEnabled(False)
            self._btn_apply_region.setEnabled(False)
            self._update_frame_buttons()
            return

        used = self._group.glyph_table.used_count
        free = self._group.glyph_table.free_slots
        analysis = self._group.glyph_analysis
        if analysis is not None and analysis.dedicated_slot_count > 0:
            self._lbl_group_counter.setText(
                f"Group '{self._group.name}' glyphs: {used}/{MAX_GLYPHS_PER_GROUP} "
                f"(static: {analysis.static_glyph_count}, anim: {analysis.dedicated_slot_count}, {free} free)"
            )
        else:
            self._lbl_group_counter.setText(
                f"Group '{self._group.name}' glyphs: {used}/{MAX_GLYPHS_PER_GROUP} ({free} free)"
            )

        sel = self._canvas.selection()
        in_group = self._has_selected_obj_in_group()

        if in_group:
            assert self._selected_object is not None
            obj = self._selected_object
            self._btn_create.setText("+ Add Frame")
            if obj.frame_count >= MAX_OBJECT_FRAMES:
                self._btn_create.setEnabled(False)
                self._btn_create.setToolTip("maximum 16 frames")
            elif sel is None or (sel.w, sel.h) != (obj.w, obj.h):
                self._btn_create.setEnabled(False)
                sel_desc = f"{sel.w}×{sel.h}" if sel is not None else "none"
                self._btn_create.setToolTip(
                    f"Selection size ({sel_desc}) must match object size ({obj.w}×{obj.h})"
                )
            else:
                self._btn_create.setEnabled(True)
                self._btn_create.setToolTip("Add current selection as a new animation frame")
        else:
            self._btn_create.setText("+ Create Object from Selection")
            self._btn_create.setToolTip("Create a new object from the selected PNG region")
            self._btn_create.setEnabled(sel is not None)

        self._btn_apply_region.setEnabled(in_group and sel is not None)

        if sel is None:
            self._lbl_sel_counter.setStyleSheet("color: #aaa;")
            self._lbl_sel_counter.setText("Drag on the image to select a stamp region.")
            self._update_frame_buttons()
            return

        if in_group and self._selected_object is not None and (sel.w, sel.h) == (
            self._selected_object.w,
            self._selected_object.h,
        ):
            obj = self._selected_object
            check_add = self._project.check_object_glyph_budget(
                self._group.name,
                list(obj.frames) + [sel],
                obj.animation_speed,
                exclude_object_id=obj.id,
            )
            delta = check_add.total_used - used if obj.frame_count < MAX_OBJECT_FRAMES else 0
            delta_txt = f"{delta:+d}" if delta != 0 else "0"
            status_color = "#7ee081" if check_add.ok else "#ff6b6b"
            self._lbl_sel_counter.setStyleSheet(f"color: {status_color};")
            if check_add.ok:
                self._lbl_sel_counter.setText(
                    f"Add Frame selection: ({sel.x}, {sel.y}) {sel.w}×{sel.h} | "
                    f"{delta_txt} slot(s) ({check_add.total_used}/{MAX_GLYPHS_PER_GROUP}, "
                    f"free: {check_add.free_slots})"
                )
            else:
                self._lbl_sel_counter.setText(
                    f"Add Frame selection: ({sel.x}, {sel.y}) {sel.w}×{sel.h} — {check_add.error_message}"
                )
        else:
            check_new = self._project.check_region_glyph_budget(self._group.name, sel)
            status_color = "#7ee081" if check_new.ok else "#ff6b6b"
            self._lbl_sel_counter.setStyleSheet(f"color: {status_color};")
            if check_new.ok:
                self._lbl_sel_counter.setText(
                    f"Selection: ({sel.x}, {sel.y}) {sel.w}×{sel.h} ({sel.cell_count} cells) | "
                    f"+{check_new.new_glyphs} new glyph(s) (free: {check_new.free_slots})"
                )
            else:
                self._lbl_sel_counter.setText(
                    f"Selection: ({sel.x}, {sel.y}) {sel.w}×{sel.h} ({sel.cell_count} cells) — {check_new.error_message}"
                )

        self._update_frame_buttons()

    _GROUP_COLORS = (
        QColor(75, 165, 255, 55),
        QColor(135, 225, 115, 55),
        QColor(245, 185, 75, 55),
        QColor(215, 125, 245, 55),
        QColor(95, 220, 210, 55),
    )

    def select_frame_range(self, first: int, last: int) -> None:
        if self._selected_object is None or not self._selected_object.frames:
            return
        lo = max(0, int(first))
        hi = min(len(self._selected_object.frames) - 1, int(last))
        if lo > hi:
            return
        self._selected_frame_idx = lo
        self._refresh_frames_panel()
        self._block_frame_signal = True
        try:
            self._frame_list.setCurrentRow(lo)
            self._frame_list.clearSelection()
            for r in range(lo, hi + 1):
                item = self._frame_list.item(r)
                if item is not None:
                    item.setSelected(True)
            self._selected_frame_idx = lo
        finally:
            self._block_frame_signal = False
        self._sync_frame_duration_controls()
        self._sync_frame_group_controls()
        self._update_anim_preview_pixmap()
        self._update_frame_buttons()

    def _selected_frame_rows(self) -> list[int]:
        return sorted(idx.row() for idx in self._frame_list.selectedIndexes())

    def _active_group_index_for_selection(self) -> int | None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None or not obj.groups:
            return None
        rows = self._selected_frame_rows()
        if rows:
            matches = {
                gi
                for r in rows
                for gi, g in enumerate(obj.groups)
                if g.contains(r)
            }
            if len(matches) == 1 and all(obj.groups[next(iter(matches))].contains(r) for r in rows):
                return next(iter(matches))
            return None
        for gi, g in enumerate(obj.groups):
            if g.contains(self._selected_frame_idx):
                return gi
        return None

    def _refresh_frames_panel(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        self._frames_box.setEnabled(obj is not None)
        self._block_frame_signal = True
        try:
            self._frame_list.clear()
            if obj is None or self._group is None:
                self._lbl_frame_counter.setText("0/16")
                self._lbl_loop_total.setText("Loop: off")
                self._lbl_anim_preview.clear()
                self._stop_preview()
                self._sync_frame_duration_controls()
                self._sync_frame_group_controls()
                return

            pal = self._group.get_palette(self.preview_palette_name()) or self._group.default_palette
            use_colpf3 = obj.colpf3 or self._chk_colpf3.isChecked()
            self._lbl_frame_counter.setText(f"{obj.frame_count}/{MAX_OBJECT_FRAMES}")
            if obj.is_animated:
                total_ticks = obj.total_loop_ticks()
                self._lbl_loop_total.setText(f"Loop: {total_ticks} ticks ({total_ticks / 50.0:.2f} s)")
            else:
                self._lbl_loop_total.setText("Loop: off")
            grp_by_frame = {
                fi: (gi, g)
                for gi, g in enumerate(obj.groups)
                for fi in range(g.first, g.last + 1)
            }
            for f_idx, freg in enumerate(obj.frames):
                pix = self._renderer.render_region_pixmap(
                    self._group,
                    freg,
                    colpf3=use_colpf3,
                    scale=2,
                    palette=pal,
                )
                dur_part = f" ({freg.duration}t)" if freg.duration != 0 else ""
                g_info = grp_by_frame.get(f_idx)
                if g_info is not None:
                    gi, g = g_info
                    if f_idx == g.first and f_idx == g.last:
                        label_txt = f"[F{f_idx}{dur_part}]×{g.repeat}"
                    elif f_idx == g.first:
                        label_txt = f"[F{f_idx}{dur_part}"
                    elif f_idx == g.last:
                        label_txt = f"F{f_idx}{dur_part}]×{g.repeat}"
                    else:
                        label_txt = f"─F{f_idx}{dur_part}"
                else:
                    label_txt = f"F{f_idx}{dur_part}"
                eff_dur = obj.effective_frame_duration(f_idx)
                eff_desc = (
                    f"{eff_dur / 50.0:.2f} s"
                    if obj.animation_speed > 0
                    else "ignored (speed=0)"
                )
                grp_tip = (
                    f" | group {g_info[1].first}..{g_info[1].last} ×{g_info[1].repeat}"
                    if g_info is not None
                    else ""
                )
                item = QListWidgetItem(pix, label_txt)
                if g_info is not None:
                    item.setBackground(self._GROUP_COLORS[g_info[0] % len(self._GROUP_COLORS)])
                item.setToolTip(
                    f"Frame {f_idx}: ({freg.x}, {freg.y}) {freg.w}×{freg.h} | time: {freg.duration} ({eff_desc}){grp_tip}"
                )
                self._frame_list.addItem(item)

            if 0 <= self._selected_frame_idx < self._frame_list.count():
                self._frame_list.setCurrentRow(self._selected_frame_idx)
        finally:
            self._block_frame_signal = False

        self._sync_frame_duration_controls()
        self._sync_frame_group_controls()
        self._update_anim_preview_pixmap()
        self._update_frame_buttons()

    def _sync_frame_duration_controls(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        self._spin_frame_duration.blockSignals(True)
        try:
            if obj is None or not (0 <= self._selected_frame_idx < len(obj.frames)):
                self._spin_frame_duration.setEnabled(False)
                self._spin_frame_duration.setValue(0)
                self._lbl_frame_effective_time.setText("")
                return
            dur = obj.frames[self._selected_frame_idx].duration
            self._spin_frame_duration.setEnabled(True)
            self._spin_frame_duration.setValue(dur)
            if obj.animation_speed <= 0:
                self._lbl_frame_effective_time.setText(
                    "(ignored; object speed is 0)" if dur > 0 else "= off (object speed is 0)"
                )
            elif dur > 0:
                self._lbl_frame_effective_time.setText(f"= {dur / 50.0:.2f} s")
            else:
                self._lbl_frame_effective_time.setText(
                    f"= object's {obj.animation_speed / 50.0:.2f} s"
                )
        finally:
            self._spin_frame_duration.blockSignals(False)

    def _on_frame_duration_spin_changed(self, value: int) -> None:
        if self._block_frame_signal:
            return
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None or not (0 <= self._selected_frame_idx < len(obj.frames)):
            return
        self.frame_duration_changed.emit(self._selected_frame_idx, int(value))

    @staticmethod
    def _preview_frame_delay_ms(obj: GameObject, frame_idx: int) -> int:
        return max(1, int(obj.effective_frame_duration(frame_idx))) * 20

    def _update_frame_buttons(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        sel = self._canvas.selection()
        has_obj = obj is not None
        cnt = obj.frame_count if obj is not None else 0
        idx = self._selected_frame_idx if has_obj else -1

        self._btn_remove_frame.setEnabled(has_obj and cnt > 1 and 0 <= idx < cnt)
        full_grp_idx = self._selected_full_group_index()
        if full_grp_idx is not None and obj is not None:
            fg = obj.groups[full_grp_idx]
            self._btn_move_frame_left.setEnabled(fg.first > 0)
            self._btn_move_frame_right.setEnabled(fg.last < cnt - 1)
        else:
            self._btn_move_frame_left.setEnabled(has_obj and idx > 0)
            self._btn_move_frame_right.setEnabled(has_obj and 0 <= idx < cnt - 1)
        matching_sel = (
            obj is not None
            and sel is not None
            and (sel.w, sel.h) == (obj.w, obj.h)
            and self._group is not None
            and self._group.image is not None
        )
        self._btn_replace_frame.setEnabled(matching_sel and 0 <= idx < cnt)
        if not matching_sel and obj is not None and sel is not None:
            self._btn_replace_frame.setToolTip(
                f"Selection size ({sel.w}×{sel.h}) must match object size ({obj.w}×{obj.h})"
            )
        else:
            self._btn_replace_frame.setToolTip("Replace selected frame's region with current selection")

        can_play = obj is not None and obj.is_animated and self._group is not None and self._group.image is not None
        self._btn_play_preview.setEnabled(can_play)
        if not can_play:
            self._stop_preview()
            self._btn_play_preview.setToolTip("Requires >= 2 frames and animation speed > 0")
        else:
            self._btn_play_preview.setToolTip("Play/Stop object animation at configured PAL speed")

    def _update_anim_preview_pixmap(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None or self._group is None or not obj.frames:
            self._lbl_anim_preview.clear()
            return
        idx = self._preview_frame_idx if self._preview_playing else self._selected_frame_idx
        idx = max(0, min(idx, len(obj.frames) - 1))
        pal = self._group.get_palette(self.preview_palette_name()) or self._group.default_palette
        use_colpf3 = obj.colpf3 or self._chk_colpf3.isChecked()
        pix = self._renderer.render_region_pixmap(
            self._group,
            obj.frames[idx],
            colpf3=use_colpf3,
            scale=2,
            palette=pal,
        )
        self._lbl_anim_preview.setPixmap(pix)

    def _stop_preview(self) -> None:
        self._preview_playing = False
        self._anim_timer.stop()
        if hasattr(self, "_btn_play_preview"):
            self._btn_play_preview.setText("▶ Play Preview")
        if hasattr(self, "_lbl_anim_preview"):
            self._update_anim_preview_pixmap()

    def _on_toggle_play_preview(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None or not obj.is_animated:
            self._stop_preview()
            return
        if self._preview_playing:
            self._stop_preview()
        else:
            self._preview_playing = True
            self._preview_frame_idx = 0
            self._preview_pass_counter = obj.initial_pass_counter()
            self._btn_play_preview.setText("■ Stop Preview")
            self._update_anim_preview_pixmap()
            self._anim_timer.start(self._preview_frame_delay_ms(obj, 0))

    def _on_anim_timer_tick(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None or not obj.is_animated:
            self._stop_preview()
            return
        self._preview_frame_idx, self._preview_pass_counter = obj.step_animation_frame(
            self._preview_frame_idx, self._preview_pass_counter
        )
        self._update_anim_preview_pixmap()
        self._anim_timer.start(self._preview_frame_delay_ms(obj, self._preview_frame_idx))

    def _selected_full_group_index(self) -> int | None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None or not obj.groups:
            return None
        rows = self._selected_frame_rows()
        if not rows:
            return None
        for gi, g in enumerate(obj.groups):
            if rows == list(range(g.first, g.last + 1)):
                return gi
        return None

    def _sync_frame_group_controls(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        self._spin_group_repeat.blockSignals(True)
        try:
            if obj is None or not obj.frames:
                self._btn_group_frames.setEnabled(False)
                self._spin_group_repeat.setEnabled(False)
                self._spin_group_repeat.setValue(1)
                self._btn_select_group.setEnabled(False)
                self._btn_ungroup.setEnabled(False)
                return

            rows = self._selected_frame_rows()
            can_create = (
                len(rows) >= 2
                and rows == list(range(rows[0], rows[-1] + 1))
                and all(obj.group_for_frame(r) is None for r in rows)
            )
            self._btn_group_frames.setEnabled(can_create)

            active_gi = self._active_group_index_for_selection()
            if active_gi is not None:
                g = obj.groups[active_gi]
                self._spin_group_repeat.setEnabled(True)
                self._spin_group_repeat.setValue(g.repeat)
                self._btn_select_group.setEnabled(True)
                self._btn_ungroup.setEnabled(True)
            else:
                self._spin_group_repeat.setEnabled(can_create)
                if not can_create:
                    self._spin_group_repeat.setValue(1)
                self._btn_select_group.setEnabled(False)
                self._btn_ungroup.setEnabled(False)
        finally:
            self._spin_group_repeat.blockSignals(False)

    def _on_frame_selection_changed(self) -> None:
        if self._block_frame_signal:
            return
        self._sync_frame_group_controls()
        self._update_frame_buttons()

    def _on_group_frames_clicked(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None:
            return
        rows = self._selected_frame_rows()
        if (
            len(rows) >= 2
            and rows == list(range(rows[0], rows[-1] + 1))
            and all(obj.group_for_frame(r) is None for r in rows)
        ):
            self.group_frames_requested.emit(rows[0], rows[-1], self._spin_group_repeat.value())

    def _on_ungroup_clicked(self) -> None:
        active_gi = self._active_group_index_for_selection()
        if active_gi is not None:
            self.ungroup_frames_requested.emit(active_gi)

    def _on_select_group_clicked(self) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        active_gi = self._active_group_index_for_selection()
        if obj is not None and active_gi is not None:
            g = obj.groups[active_gi]
            self.select_frame_range(g.first, g.last)

    def _on_group_repeat_spin_changed(self, value: int) -> None:
        if self._block_frame_signal:
            return
        active_gi = self._active_group_index_for_selection()
        if active_gi is not None:
            self.group_repeat_changed.emit(active_gi, int(value))

    def _on_frame_list_row_changed(self, row: int) -> None:
        if self._block_frame_signal or row < 0:
            return
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None or not (0 <= row < len(obj.frames)):
            return
        self._selected_frame_idx = row
        self._sync_frame_duration_controls()
        self._sync_frame_group_controls()
        self._update_anim_preview_pixmap()
        self._update_frame_buttons()
        self.set_selection(obj.frames[row])
        self.selection_changed.emit(obj.frames[row])

    def _on_primary_action_clicked(self) -> None:
        sel = self._canvas.selection()
        if sel is None:
            return
        if self._has_selected_obj_in_group():
            self.add_frame_requested.emit(sel)
        else:
            self.create_object_requested.emit(sel)

    def _on_apply_region_clicked(self) -> None:
        sel = self._canvas.selection()
        if sel is not None:
            self.apply_region_requested.emit(sel)

    def _on_replace_frame_clicked(self) -> None:
        sel = self._canvas.selection()
        if sel is not None and self._has_selected_obj_in_group():
            self.replace_frame_requested.emit(self._selected_frame_idx, sel)

    def _on_remove_frame_clicked(self) -> None:
        if self._has_selected_obj_in_group():
            self.remove_frame_requested.emit(self._selected_frame_idx)

    def _on_reorder_frame(self, delta: int) -> None:
        obj = self._selected_object if self._has_selected_obj_in_group() else None
        if obj is None:
            return
        full_grp_idx = self._selected_full_group_index()
        if full_grp_idx is not None:
            g = obj.groups[full_grp_idx]
            if (delta == -1 and g.first > 0) or (delta == 1 and g.last < obj.frame_count - 1):
                self.move_group_requested.emit(full_grp_idx, delta)
            return
        target = self._selected_frame_idx + delta
        if 0 <= target < obj.frame_count:
            self.reorder_frame_requested.emit(self._selected_frame_idx, target)
