"""Stamp Image widget: 2:1 PNG view, 4x8 grid, drag selection, COLPF3 & palette preview."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.glyphs import (
    MAX_GLYPHS_PER_GROUP,
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
        self._selection = region
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
            r = obj.region
            rect = QRect(r.x * cw, r.y * ch, r.w * cw, r.h * ch)
            if self._selected_object is not None and obj.id == self._selected_object.id:
                painter.setPen(QPen(QColor(255, 215, 65), 2, Qt.PenStyle.DashLine))
            else:
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
    """Stamp Image panel with zoom, 4x8 grid, COLPF3 preview, and preview palette selector."""

    create_object_requested = Signal(object)  # StampRegion
    apply_region_requested = Signal(object)  # StampRegion
    selection_changed = Signal(object)  # StampRegion
    preview_palette_changed = Signal(str)  # palette name (UI-only preview choice)

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._project = Project()
        self._group: ObjectGroup | None = None
        self._selected_object: GameObject | None = None
        self._block_pal_signal = False

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
        self._btn_create.clicked.connect(self._on_create_clicked)
        self._btn_apply_region = QPushButton("Update Selected Object Region")
        self._btn_apply_region.clicked.connect(self._on_apply_region_clicked)
        actions.addWidget(self._btn_create)
        actions.addWidget(self._btn_apply_region)
        layout.addLayout(actions)

    def set_data(
        self,
        project: Project,
        group: ObjectGroup | None,
        selected_object: GameObject | None,
        preview_palette_name: str = "",
    ) -> None:
        self._project = project
        self._group = group
        self._selected_object = selected_object

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
        self._refresh_counters()

    def set_preview_palette(self, name: str) -> None:
        self._block_pal_signal = True
        try:
            idx = self._combo_preview_pal.findData(name)
            if idx >= 0:
                self._combo_preview_pal.setCurrentIndex(idx)
                self._canvas.set_preview_palette_name(name)
        finally:
            self._block_pal_signal = False

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
        self.preview_palette_changed.emit(name)

    def _on_colpf3_toggled(self, checked: bool) -> None:
        self._canvas.set_preview_colpf3(checked)

    def _on_file_pal_toggled(self, checked: bool) -> None:
        self._chk_colpf3.setEnabled(not checked)
        self._combo_preview_pal.setEnabled(not checked and self._combo_preview_pal.count() > 0)
        self._canvas.set_use_file_palette(checked)

    def _on_canvas_selection_changed(self, region: StampRegion) -> None:
        self._refresh_counters()
        self.selection_changed.emit(region)

    def _refresh_counters(self) -> None:
        if self._group is None or self._group.image is None:
            self._lbl_group_counter.setText("Group glyphs: 0/127 (no PNG loaded)")
            self._lbl_sel_counter.setStyleSheet("color: #aaa;")
            self._lbl_sel_counter.setText("Load an indexed PNG to select stamp regions.")
            self._btn_create.setEnabled(False)
            self._btn_apply_region.setEnabled(False)
            return

        used = self._group.glyph_table.used_count
        free = self._group.glyph_table.free_slots
        self._lbl_group_counter.setText(
            f"Group '{self._group.name}' glyphs: {used}/{MAX_GLYPHS_PER_GROUP} ({free} free)"
        )

        sel = self._canvas.selection()
        if sel is None:
            self._lbl_sel_counter.setStyleSheet("color: #aaa;")
            self._lbl_sel_counter.setText("Drag on the image to select a stamp region.")
            self._btn_create.setEnabled(False)
            self._btn_apply_region.setEnabled(False)
            return

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

        self._btn_create.setEnabled(True)
        self._btn_apply_region.setEnabled(
            self._selected_object is not None
            and self._selected_object.group == self._group.name
        )

    def _on_create_clicked(self) -> None:
        sel = self._canvas.selection()
        if sel is not None:
            self.create_object_requested.emit(sel)

    def _on_apply_region_clicked(self) -> None:
        sel = self._canvas.selection()
        if sel is not None:
            self.apply_region_requested.emit(sel)
