"""Objects & Object Groups tab: .fnt loading, palettes, object grid, and charset picker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
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

from room_editor.io.fnt import FontLoadError, load_fnt, to_relative_posix_path
from room_editor.model.commands import (
    AddGroupCommand,
    AddObjectCommand,
    DeleteGroupCommand,
    DeleteObjectCommand,
    UndoStack,
    UpdateGroupCommand,
    UpdateObjectCommand,
)
from room_editor.model.palette import PalPaletteTable, Palette
from room_editor.model.project import (
    MAX_OBJECT_CELLS,
    MAX_OBJECTS,
    GameObject,
    ObjectGroup,
    Project,
)
from room_editor.ui.color_picker import PaletteEditorWidget
from room_editor.ui.rendering_qt import CHAR_PX_H, CHAR_PX_W, QtRenderer


class ObjectGridWidget(QWidget):
    """Interactive w x h character grid for editing a GameObject's stamp."""

    cell_edited = Signal(int, int, int)  # (x, y, char_code)

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._obj: GameObject | None = None
        self._group: ObjectGroup | None = None
        self._active_code = 1
        self._cell_px = 28
        self._update_size()

    def set_data(self, obj: GameObject | None, group: ObjectGroup | None) -> None:
        self._obj = obj
        self._group = group
        self._update_size()
        self.update()

    def set_active_code(self, code: int) -> None:
        self._active_code = max(0, min(255, int(code)))

    def _update_size(self) -> None:
        if self._obj is None:
            self.setFixedSize(160, 120)
        else:
            self.setFixedSize(
                max(1, self._obj.w) * self._cell_px,
                max(1, self._obj.h) * self._cell_px,
            )

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(28, 28, 32))
        if self._obj is None:
            painter.setPen(QColor(160, 160, 170))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No object")
            painter.end()
            return

        for dy in range(self._obj.h):
            for dx in range(self._obj.w):
                rx = dx * self._cell_px
                ry = dy * self._cell_px
                code = (
                    self._obj.chars[dy][dx]
                    if dy < len(self._obj.chars) and dx < len(self._obj.chars[dy])
                    else 0
                )
                if code == 0:
                    painter.fillRect(rx, ry, self._cell_px, self._cell_px, QColor(42, 42, 48))
                    painter.setPen(QColor(95, 95, 105))
                    painter.drawText(
                        rx,
                        ry,
                        self._cell_px,
                        self._cell_px,
                        Qt.AlignmentFlag.AlignCenter,
                        "0",
                    )
                elif self._group is not None and self._group.charset is not None:
                    g_img = self._renderer.glyph_image(
                        self._group.charset, code, self._group.palette
                    )
                    painter.drawImage(
                        rx,
                        ry,
                        g_img.scaled(
                            self._cell_px,
                            self._cell_px,
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.FastTransformation,
                        ),
                    )
                else:
                    painter.fillRect(rx, ry, self._cell_px, self._cell_px, QColor(120, 70, 70))
                    painter.setPen(QColor(235, 235, 235))
                    painter.drawText(
                        rx,
                        ry,
                        self._cell_px,
                        self._cell_px,
                        Qt.AlignmentFlag.AlignCenter,
                        str(code),
                    )
                painter.setPen(QPen(QColor(90, 95, 110), 1))
                painter.drawRect(rx, ry, self._cell_px - 1, self._cell_px - 1)
        painter.end()

    def _apply_at_pos(self, pos, code: int) -> None:
        if self._obj is None:
            return
        dx = int(pos.x() // self._cell_px)
        dy = int(pos.y() // self._cell_px)
        if 0 <= dx < self._obj.w and 0 <= dy < self._obj.h:
            if self._obj.chars[dy][dx] != code:
                self.cell_edited.emit(dx, dy, code)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._apply_at_pos(event.position(), self._active_code)
        elif event.button() == Qt.MouseButton.RightButton:
            self._apply_at_pos(event.position(), 0)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._apply_at_pos(event.position(), self._active_code)
        elif event.buttons() & Qt.MouseButton.RightButton:
            self._apply_at_pos(event.position(), 0)


class CharsetPickerWidget(QWidget):
    """256-code ANTIC 4 charset grid picker (0=empty, 1..127=COLPF2, 128..255=COLPF3)."""

    code_selected = Signal(int)

    COLS = 16
    CELL_PX = 20

    def __init__(self, renderer: QtRenderer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._group: ObjectGroup | None = None
        self._selected_code = 1
        self.setFixedSize(self.COLS * self.CELL_PX, 16 * self.CELL_PX)

    def set_group(self, group: ObjectGroup | None) -> None:
        self._group = group
        self.update()

    def set_selected_code(self, code: int) -> None:
        self._selected_code = max(0, min(255, int(code)))
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        pix = self._renderer.render_charset_grid_pixmap(
            self._group, cols=self.COLS, cell_px=self.CELL_PX
        )
        painter.drawPixmap(0, 0, pix)

        # Grid + divider between 0..127 and 128..255
        painter.setPen(QPen(QColor(70, 70, 80, 140), 1))
        for c in range(1, self.COLS):
            painter.drawLine(c * self.CELL_PX, 0, c * self.CELL_PX, self.height())
        for r in range(1, 16):
            pen = QPen(QColor(255, 200, 60), 2) if r == 8 else QPen(QColor(70, 70, 80, 140), 1)
            painter.setPen(pen)
            painter.drawLine(0, r * self.CELL_PX, self.width(), r * self.CELL_PX)

        # Selected code highlight
        sx = (self._selected_code % self.COLS) * self.CELL_PX
        sy = (self._selected_code // self.COLS) * self.CELL_PX
        painter.setPen(QPen(QColor(80, 220, 255), 2))
        painter.drawRect(sx + 1, sy + 1, self.CELL_PX - 2, self.CELL_PX - 2)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            cx = max(0, min(self.COLS - 1, int(event.position().x() // self.CELL_PX)))
            cy = max(0, min(15, int(event.position().y() // self.CELL_PX)))
            code = cy * self.COLS + cx
            self._selected_code = code
            self.code_selected.emit(code)
            self.update()


class ObjectsView(QWidget):
    """Tab widget for managing Object Groups, Charsets, Palettes, and GameObjects."""

    model_changed = Signal()

    def __init__(
        self,
        renderer: QtRenderer,
        pal_table: PalPaletteTable,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._renderer = renderer
        self._pal_table = pal_table
        self._project = Project()
        self._undo_stack = UndoStack()
        self._project_file_provider = lambda: None  # callable returning Path | None

        self._selected_group_name: str | None = None
        self._selected_object_id: int | None = None
        self._tag_checkboxes: dict[str, QCheckBox] = {}
        self._block_signals = False

        self._setup_ui()

    def set_project_file_provider(self, provider) -> None:
        self._project_file_provider = provider

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)

        # Column 1: Object Groups
        grp_col = QGroupBox("Object Groups")
        grp_layout = QVBoxLayout(grp_col)

        grp_btns = QHBoxLayout()
        btn_add_grp = QPushButton("+ Add Group")
        btn_add_grp.clicked.connect(self._on_add_group)
        self._btn_del_grp = QPushButton("Delete Group")
        self._btn_del_grp.clicked.connect(self._on_delete_group)
        grp_btns.addWidget(btn_add_grp)
        grp_btns.addWidget(self._btn_del_grp)
        grp_layout.addLayout(grp_btns)

        self._group_list = QListWidget()
        self._group_list.currentRowChanged.connect(self._on_group_list_changed)
        grp_layout.addWidget(self._group_list, 1)

        grp_form = QFormLayout()
        self._edit_grp_name = QLineEdit()
        btn_rename_grp = QPushButton("Rename Group")
        btn_rename_grp.clicked.connect(self._on_rename_group)
        self._lbl_fnt_path = QLabel("(none)")
        self._lbl_fnt_path.setWordWrap(True)
        btn_load_fnt = QPushButton("Load .fnt (1024 B)...")
        btn_load_fnt.clicked.connect(self._on_load_fnt)
        grp_form.addRow("Name:", self._edit_grp_name)
        grp_form.addRow(btn_rename_grp)
        grp_form.addRow("Charset:", self._lbl_fnt_path)
        grp_form.addRow(btn_load_fnt)
        grp_layout.addLayout(grp_form)

        self._palette_editor = PaletteEditorWidget(self._pal_table, self)
        self._palette_editor.palette_changed.connect(self._on_group_palette_changed)
        grp_layout.addWidget(self._palette_editor)

        root.addWidget(grp_col, 1)

        # Column 2: Objects List & Properties
        obj_col = QGroupBox("Objects")
        obj_layout = QVBoxLayout(obj_col)

        obj_btns = QHBoxLayout()
        btn_add_obj = QPushButton("+ Add Object")
        btn_add_obj.clicked.connect(self._on_add_object)
        self._btn_del_obj = QPushButton("Delete Object")
        self._btn_del_obj.clicked.connect(self._on_delete_object)
        obj_btns.addWidget(btn_add_obj)
        obj_btns.addWidget(self._btn_del_obj)
        obj_layout.addLayout(obj_btns)

        self._obj_list = QListWidget()
        self._obj_list.currentRowChanged.connect(self._on_object_list_changed)
        obj_layout.addWidget(self._obj_list, 1)

        obj_form = QFormLayout()
        self._spin_obj_id = QSpinBox()
        self._spin_obj_id.setRange(1, MAX_OBJECTS)
        self._edit_obj_name = QLineEdit()
        self._combo_obj_group = QComboBox()
        self._spin_obj_w = QSpinBox()
        self._spin_obj_w.setRange(1, 40)
        self._spin_obj_h = QSpinBox()
        self._spin_obj_h.setRange(1, 20)
        self._chk_non_blockable = QCheckBox("Non-blockable (hero can pass)")
        btn_apply_obj = QPushButton("Apply Object Properties")
        btn_apply_obj.clicked.connect(self._on_apply_object_props)

        obj_form.addRow("ID (1..255):", self._spin_obj_id)
        obj_form.addRow("Name:", self._edit_obj_name)
        obj_form.addRow("Group:", self._combo_obj_group)
        obj_form.addRow("Width:", self._spin_obj_w)
        obj_form.addRow("Height:", self._spin_obj_h)
        obj_form.addRow(self._chk_non_blockable)
        obj_form.addRow(btn_apply_obj)
        obj_layout.addLayout(obj_form)

        tags_box = QGroupBox("Tags")
        self._tags_layout = QVBoxLayout(tags_box)
        obj_layout.addWidget(tags_box)

        root.addWidget(obj_col, 1)

        # Column 3: Object Character Grid Editor + Charset Picker
        edit_col = QGroupBox("Object Stamp & Charset")
        edit_layout = QVBoxLayout(edit_col)

        edit_layout.addWidget(QLabel("Stamp Grid (Left-click: paint, Right-click: 0 / transparent):"))
        self._obj_grid = ObjectGridWidget(self._renderer, self)
        self._obj_grid.cell_edited.connect(self._on_object_cell_edited)
        grid_scroll = QScrollArea()
        grid_scroll.setWidget(self._obj_grid)
        grid_scroll.setWidgetResizable(False)
        edit_layout.addWidget(grid_scroll, 1)

        self._lbl_selected_code = QLabel("Active Character: 1 ($01) [COLPF2]")
        edit_layout.addWidget(self._lbl_selected_code)

        self._charset_picker = CharsetPickerWidget(self._renderer, self)
        self._charset_picker.code_selected.connect(self._on_char_code_selected)
        edit_layout.addWidget(self._charset_picker)

        root.addWidget(edit_col, 1)

    def set_context(self, project: Project, undo_stack: UndoStack) -> None:
        self._project = project
        self._undo_stack = undo_stack
        self.refresh()

    def select_group(self, group_name: str) -> None:
        self._selected_group_name = group_name
        self.refresh()

    def select_object(self, obj_id: int) -> None:
        self._selected_object_id = obj_id
        self.refresh()

    def refresh(self) -> None:
        self._block_signals = True
        try:
            # Groups list
            self._group_list.clear()
            if (
                self._selected_group_name is None
                or self._project.get_group(self._selected_group_name) is None
            ):
                self._selected_group_name = (
                    self._project.object_groups[0].name if self._project.object_groups else None
                )
            for grp in self._project.object_groups:
                status = "OK" if grp.charset is not None else "NO FNT"
                item = QListWidgetItem(f"{grp.name} [{status}]")
                item.setData(Qt.ItemDataRole.UserRole, grp.name)
                self._group_list.addItem(item)
                if grp.name == self._selected_group_name:
                    self._group_list.setCurrentItem(item)

            # Group combo on object properties
            self._combo_obj_group.clear()
            for grp in self._project.object_groups:
                self._combo_obj_group.addItem(grp.name, grp.name)

            # Objects list
            self._obj_list.clear()
            if (
                self._selected_object_id is None
                or self._project.get_object(self._selected_object_id) is None
            ):
                self._selected_object_id = (
                    self._project.objects[0].id if self._project.objects else None
                )
            for obj in sorted(self._project.objects, key=lambda o: o.id):
                grp = self._project.get_group(obj.group)
                pix = self._renderer.render_object_pixmap(obj, grp, scale=2)
                item = QListWidgetItem(pix, f"#{obj.id} {obj.name} ({obj.w}x{obj.h})")
                item.setData(Qt.ItemDataRole.UserRole, obj.id)
                self._obj_list.addItem(item)
                if obj.id == self._selected_object_id:
                    self._obj_list.setCurrentItem(item)

            # Rebuild tag checkboxes
            for cb in self._tag_checkboxes.values():
                self._tags_layout.removeWidget(cb)
                cb.deleteLater()
            self._tag_checkboxes.clear()
            for tag in self._project.tags:
                cb = QCheckBox(tag)
                cb.toggled.connect(self._on_tag_toggled)
                self._tags_layout.addWidget(cb)
                self._tag_checkboxes[tag] = cb

            self._sync_group_panel()
            self._sync_object_panel()
        finally:
            self._block_signals = False

    def _sync_group_panel(self) -> None:
        grp = (
            self._project.get_group(self._selected_group_name)
            if self._selected_group_name is not None
            else None
        )
        enabled = grp is not None
        self._edit_grp_name.setEnabled(enabled)
        self._palette_editor.setEnabled(enabled)
        self._btn_del_grp.setEnabled(enabled)
        if grp is not None:
            self._edit_grp_name.setText(grp.name)
            self._lbl_fnt_path.setText(grp.charset_path or "(none loaded)")
            self._palette_editor.set_palette(grp.palette)
        else:
            self._edit_grp_name.clear()
            self._lbl_fnt_path.setText("(none)")

    def _sync_object_panel(self) -> None:
        obj = (
            self._project.get_object(self._selected_object_id)
            if self._selected_object_id is not None
            else None
        )
        enabled = obj is not None
        self._spin_obj_id.setEnabled(enabled)
        self._edit_obj_name.setEnabled(enabled)
        self._combo_obj_group.setEnabled(enabled)
        self._spin_obj_w.setEnabled(enabled)
        self._spin_obj_h.setEnabled(enabled)
        self._chk_non_blockable.setEnabled(enabled)
        self._btn_del_obj.setEnabled(enabled)
        for cb in self._tag_checkboxes.values():
            cb.setEnabled(enabled)

        if obj is not None:
            self._spin_obj_id.setValue(obj.id)
            self._edit_obj_name.setText(obj.name)
            idx = self._combo_obj_group.findData(obj.group)
            if idx >= 0:
                self._combo_obj_group.setCurrentIndex(idx)
            self._spin_obj_w.setValue(obj.w)
            self._spin_obj_h.setValue(obj.h)
            self._chk_non_blockable.setChecked(obj.non_blockable)
            for tag, cb in self._tag_checkboxes.items():
                cb.setChecked(tag in obj.tags)
            grp = self._project.get_group(obj.group)
            self._obj_grid.set_data(obj, grp)
            self._charset_picker.set_group(grp)
        else:
            self._edit_obj_name.clear()
            grp = (
                self._project.get_group(self._selected_group_name)
                if self._selected_group_name is not None
                else None
            )
            self._obj_grid.set_data(None, grp)
            self._charset_picker.set_group(grp)

    def _on_group_list_changed(self, row: int) -> None:
        if self._block_signals or row < 0:
            return
        self._selected_group_name = self._group_list.item(row).data(Qt.ItemDataRole.UserRole)
        self._block_signals = True
        try:
            self._sync_group_panel()
            if self._selected_object_id is None:
                grp = (
                    self._project.get_group(self._selected_group_name)
                    if self._selected_group_name
                    else None
                )
                self._charset_picker.set_group(grp)
        finally:
            self._block_signals = False

    def _on_object_list_changed(self, row: int) -> None:
        if self._block_signals or row < 0:
            return
        self._selected_object_id = int(self._obj_list.item(row).data(Qt.ItemDataRole.UserRole))
        self._block_signals = True
        try:
            self._sync_object_panel()
        finally:
            self._block_signals = False

    def _on_add_group(self) -> None:
        base = "group"
        idx = 1
        existing = {g.name for g in self._project.object_groups}
        while f"{base}_{idx}" in existing:
            idx += 1
        name = f"{base}_{idx}"
        grp = ObjectGroup(
            name=name,
            charset_path="",
            palette=self._project.settings.default_palette.copy(),
            charset=None,
        )
        self._undo_stack.push_and_execute(AddGroupCommand(self._project, grp))
        self._selected_group_name = name
        self.model_changed.emit()

    def _on_delete_group(self) -> None:
        if not self._selected_group_name:
            return
        used_objs = [o for o in self._project.objects if o.group == self._selected_group_name]
        used_rows = sum(
            1 for r in self._project.rooms if self._selected_group_name in r.row_groups
        )
        if used_objs or used_rows:
            ans = QMessageBox.question(
                self,
                "Delete Object Group",
                f"Group '{self._selected_group_name}' is used by {len(used_objs)} object(s) "
                f"and {used_rows} room(s). Delete it?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        remaining = [
            g.name for g in self._project.object_groups if g.name != self._selected_group_name
        ]
        fallback = remaining[0] if remaining else ""
        self._undo_stack.push_and_execute(
            DeleteGroupCommand(self._project, self._selected_group_name, fallback_group=fallback)
        )
        self._selected_group_name = None
        self.model_changed.emit()

    def _on_rename_group(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None:
            return
        new_name = self._edit_grp_name.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Group name cannot be empty.")
            return
        if new_name == grp.name:
            return
        if self._project.get_group(new_name) is not None:
            QMessageBox.warning(self, "Duplicate Name", f"Group '{new_name}' already exists.")
            return
        self._undo_stack.push_and_execute(
            UpdateGroupCommand(self._project, grp, name=new_name)
        )
        self._selected_group_name = new_name
        self.model_changed.emit()

    def _on_load_fnt(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Atari Charset (.fnt)", "", "Atari Font (*.fnt);;All Files (*)"
        )
        if not path:
            return
        fnt_path = Path(path)
        try:
            charset = load_fnt(fnt_path)
        except FontLoadError as exc:
            QMessageBox.critical(self, "Invalid Charset", str(exc))
            return

        project_file = self._project_file_provider()
        if project_file is not None:
            stored_path = to_relative_posix_path(fnt_path, project_file)
        else:
            stored_path = fnt_path.as_posix()

        self._undo_stack.push_and_execute(
            UpdateGroupCommand(
                self._project,
                grp,
                charset_path=stored_path,
                charset=charset,
                update_charset=True,
            )
        )
        self.model_changed.emit()

    def _on_group_palette_changed(self, new_palette: Palette) -> None:
        if self._block_signals or not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None:
            return
        self._undo_stack.push_and_execute(
            UpdateGroupCommand(self._project, grp, palette=new_palette)
        )
        self.model_changed.emit()

    def _on_add_object(self) -> None:
        new_id = self._project.next_free_object_id()
        if new_id is None:
            QMessageBox.warning(self, "Object Limit", f"Cannot exceed {MAX_OBJECTS} objects.")
            return
        if not self._project.object_groups:
            QMessageBox.warning(self, "No Group", "Create an object group before creating objects.")
            return
        grp_name = self._selected_group_name or self._project.object_groups[0].name
        existing_names = {o.name for o in self._project.objects}
        idx = new_id
        while f"obj_{idx}" in existing_names:
            idx += 1
        obj = GameObject(
            id=new_id,
            name=f"obj_{idx}",
            group=grp_name,
            w=1,
            h=1,
            chars=[[1]],
        )
        self._undo_stack.push_and_execute(AddObjectCommand(self._project, obj))
        self._selected_object_id = obj.id
        self.model_changed.emit()

    def _on_delete_object(self) -> None:
        if self._selected_object_id is None:
            return
        obj = self._project.get_object(self._selected_object_id)
        if obj is None:
            return
        usage_count = sum(
            1
            for r in self._project.rooms
            for inst in r.instances
            if inst.object_id == obj.id
        )
        if usage_count > 0:
            ans = QMessageBox.question(
                self,
                "Delete Object",
                f"Object '{obj.name}' is placed {usage_count} time(s) in rooms. "
                "Deleting it will remove all of its instances. Continue?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._undo_stack.push_and_execute(DeleteObjectCommand(self._project, obj.id))
        self._selected_object_id = None
        self.model_changed.emit()

    def _on_apply_object_props(self) -> None:
        if self._selected_object_id is None:
            return
        obj = self._project.get_object(self._selected_object_id)
        if obj is None:
            return
        new_id = self._spin_obj_id.value()
        new_name = self._edit_obj_name.text().strip()
        new_group = self._combo_obj_group.currentData() or ""
        new_w = self._spin_obj_w.value()
        new_h = self._spin_obj_h.value()
        new_nb = self._chk_non_blockable.isChecked()

        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Object name cannot be empty.")
            return
        if new_w * new_h > MAX_OBJECT_CELLS:
            QMessageBox.warning(
                self,
                "Size Limit Exceeded",
                f"Object size {new_w}x{new_h} = {new_w * new_h} cells exceeds the {MAX_OBJECT_CELLS}-cell limit.",
            )
            return
        for other in self._project.objects:
            if other is not obj:
                if other.id == new_id:
                    QMessageBox.warning(self, "Duplicate ID", f"Object ID {new_id} is already in use.")
                    return
                if other.name == new_name:
                    QMessageBox.warning(self, "Duplicate Name", f"Object name '{new_name}' is already in use.")
                    return

        temp = GameObject(
            id=obj.id,
            name=obj.name,
            group=obj.group,
            w=obj.w,
            h=obj.h,
            chars=[list(r) for r in obj.chars],
        )
        temp.resize(new_w, new_h)

        # If turning non-blockable OFF (or updating a blockable object), refuse if blockable overlaps result
        if not new_nb:
            conflicts = self._project.find_blockable_overlaps_for_object(
                obj.id,
                new_w=new_w,
                new_h=new_h,
                new_chars=temp.chars,
            )
            if conflicts:
                preview = "\n".join(
                    f"• Room #{rid} '{rname}' at ({cx}, {cy}) with object #{other_id}"
                    for rid, rname, cx, cy, other_id in conflicts[:10]
                )
                if len(conflicts) > 10:
                    preview += f"\n... and {len(conflicts) - 10} more conflict(s)."
                QMessageBox.warning(
                    self,
                    "Blockable Overlap Conflict",
                    "Cannot mark this object as blockable because its placed instances would "
                    f"overlap other blockable instances:\n\n{preview}",
                )
                self._block_signals = True
                try:
                    self._chk_non_blockable.setChecked(obj.non_blockable)
                    self._spin_obj_w.setValue(obj.w)
                    self._spin_obj_h.setValue(obj.h)
                finally:
                    self._block_signals = False
                return

        tags = [t for t, cb in self._tag_checkboxes.items() if cb.isChecked()]
        self._undo_stack.push_and_execute(
            UpdateObjectCommand(
                self._project,
                obj,
                id=new_id,
                name=new_name,
                group=new_group,
                tags=tags,
                non_blockable=new_nb,
                w=new_w,
                h=new_h,
                chars=temp.chars,
            )
        )
        self._selected_object_id = new_id
        self.model_changed.emit()

    def _on_tag_toggled(self, _checked: bool) -> None:
        if self._block_signals or self._selected_object_id is None:
            return
        obj = self._project.get_object(self._selected_object_id)
        if obj is None:
            return
        tags = [t for t, cb in self._tag_checkboxes.items() if cb.isChecked()]
        if tags != obj.tags:
            self._undo_stack.push_and_execute(
                UpdateObjectCommand(self._project, obj, tags=tags)
            )
            self.model_changed.emit()

    def _on_char_code_selected(self, code: int) -> None:
        self._obj_grid.set_active_code(code)
        if code == 0:
            self._lbl_selected_code.setText("Active Character: 0 ($00) [Transparent / Empty]")
        elif code < 128:
            self._lbl_selected_code.setText(f"Active Character: {code} (${code:02X}) [COLPF2]")
        else:
            self._lbl_selected_code.setText(f"Active Character: {code} (${code:02X}) [COLPF3]")

    def _on_object_cell_edited(self, x: int, y: int, code: int) -> None:
        if self._selected_object_id is None:
            return
        obj = self._project.get_object(self._selected_object_id)
        if obj is None:
            return
        new_chars = [list(r) for r in obj.chars]
        new_chars[y][x] = code
        self._undo_stack.push_and_execute(
            UpdateObjectCommand(self._project, obj, chars=new_chars)
        )
        self.model_changed.emit()
