"""Objects & Object Groups tab: PNG loading, pixel mapping, named palettes, and Stamp Image."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from room_editor.io.png import (
    PngLoadError,
    PngMissingError,
    load_png,
    resolve_image_path,
    to_relative_posix_path,
)
from room_editor.model.commands import (
    AddGroupCommand,
    AddGroupPaletteCommand,
    AddObjectCommand,
    DeleteGroupCommand,
    DeleteGroupPaletteCommand,
    DeleteObjectCommand,
    RenameGroupPaletteCommand,
    ReorderGroupPaletteCommand,
    UndoStack,
    UpdateGroupCommand,
    UpdateGroupPaletteColorsCommand,
    UpdateObjectCommand,
)
from room_editor.model.glyphs import (
    MAX_GLYPHS_PER_GROUP,
    StampRegion,
)
from room_editor.model.palette import (
    DEFAULT_PALETTE_NAME,
    NamedPalette,
    PalPaletteTable,
    Palette,
)
from room_editor.model.project import (
    MAX_OBJECT_CELLS,
    MAX_OBJECTS,
    GameObject,
    ObjectGroup,
    Project,
)
from room_editor.ui.color_picker import PaletteEditorWidget
from room_editor.ui.png_import_dialog import PngImportDialog
from room_editor.ui.rendering_qt import QtRenderer
from room_editor.ui.stamp_image_widget import StampImageWidget

_VALUE_NAMES = ("00", "01", "10", "11")


def _format_mapping(mapping: tuple[int, int, int, int]) -> str:
    if len(mapping) != 4:
        return repr(mapping)
    return ", ".join(
        f"{i}→{_VALUE_NAMES[v] if 0 <= v < 4 else '?'}" for i, v in enumerate(mapping)
    )


class ObjectsView(QWidget):
    """Tab widget for managing Object Groups, indexed PNGs, Palettes, and GameObjects."""

    model_changed = Signal()
    preview_palette_changed = Signal(str, str)  # (group_name, palette_name)

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
        self._project_file_provider = lambda: None

        self._selected_group_name: str | None = None
        self._selected_palette_name: str | None = None
        self._preview_palette_by_group: dict[str, str] = {}
        self._selected_object_id: int | None = None
        self._tag_checkboxes: dict[str, QCheckBox] = {}
        self._block_signals = False

        self._setup_ui()

    def set_project_file_provider(self, provider) -> None:
        self._project_file_provider = provider

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)

        # Column 1: Object Groups & Named Palettes
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

        self._lbl_png_path = QLabel("(none)")
        self._lbl_png_path.setWordWrap(True)

        png_btns = QHBoxLayout()
        self._btn_load_png = QPushButton("Load PNG...")
        self._btn_load_png.clicked.connect(self._on_load_png)
        self._btn_reload_png = QPushButton("Reload Image")
        self._btn_reload_png.clicked.connect(self._on_reload_png)
        png_btns.addWidget(self._btn_load_png)
        png_btns.addWidget(self._btn_reload_png)

        self._lbl_mapping = QLabel("0→00, 1→01, 2→10, 3→11")
        self._btn_edit_mapping = QPushButton("Pixel Mapping...")
        self._btn_edit_mapping.clicked.connect(self._on_edit_mapping)
        self._lbl_grp_glyphs = QLabel("0 / 127")

        grp_form.addRow("Name:", self._edit_grp_name)
        grp_form.addRow(btn_rename_grp)
        grp_form.addRow("PNG Image:", self._lbl_png_path)
        grp_form.addRow(png_btns)
        grp_form.addRow("Mapping:", self._lbl_mapping)
        grp_form.addRow(self._btn_edit_mapping)
        grp_form.addRow("Unique Glyphs:", self._lbl_grp_glyphs)
        grp_layout.addLayout(grp_form)

        # Named Palettes management box
        pal_box = QGroupBox("Group Palettes (Preview & Editing)")
        pal_layout = QVBoxLayout(pal_box)

        self._palette_list = QListWidget()
        self._palette_list.setMaximumHeight(110)
        self._palette_list.currentRowChanged.connect(self._on_palette_list_changed)
        pal_layout.addWidget(self._palette_list)

        pal_btns_1 = QHBoxLayout()
        self._btn_pal_add = QPushButton("+ Add")
        self._btn_pal_add.clicked.connect(self._on_add_palette)
        self._btn_pal_dup = QPushButton("Duplicate")
        self._btn_pal_dup.clicked.connect(self._on_duplicate_palette)
        self._btn_pal_rename = QPushButton("Rename")
        self._btn_pal_rename.clicked.connect(self._on_rename_palette)
        pal_btns_1.addWidget(self._btn_pal_add)
        pal_btns_1.addWidget(self._btn_pal_dup)
        pal_btns_1.addWidget(self._btn_pal_rename)
        pal_layout.addLayout(pal_btns_1)

        pal_btns_2 = QHBoxLayout()
        self._btn_pal_del = QPushButton("Delete")
        self._btn_pal_del.clicked.connect(self._on_delete_palette)
        self._btn_pal_up = QPushButton("Move Up")
        self._btn_pal_up.clicked.connect(lambda: self._on_reorder_palette(-1))
        self._btn_pal_down = QPushButton("Move Down")
        self._btn_pal_down.clicked.connect(lambda: self._on_reorder_palette(1))
        pal_btns_2.addWidget(self._btn_pal_del)
        pal_btns_2.addWidget(self._btn_pal_up)
        pal_btns_2.addWidget(self._btn_pal_down)
        pal_layout.addLayout(pal_btns_2)

        self._palette_editor = PaletteEditorWidget(self._pal_table, self)
        self._palette_editor.palette_changed.connect(self._on_group_palette_changed)
        pal_layout.addWidget(self._palette_editor)
        grp_layout.addWidget(pal_box)

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

        reg_row = QHBoxLayout()
        self._spin_reg_x = QSpinBox()
        self._spin_reg_x.setRange(0, 512)
        self._spin_reg_y = QSpinBox()
        self._spin_reg_y.setRange(0, 512)
        self._spin_reg_w = QSpinBox()
        self._spin_reg_w.setRange(1, MAX_OBJECT_CELLS)
        self._spin_reg_h = QSpinBox()
        self._spin_reg_h.setRange(1, MAX_OBJECT_CELLS)
        for lbl_txt, sp in (
            ("x:", self._spin_reg_x),
            ("y:", self._spin_reg_y),
            ("w:", self._spin_reg_w),
            ("h:", self._spin_reg_h),
        ):
            reg_row.addWidget(QLabel(lbl_txt))
            reg_row.addWidget(sp)

        self._chk_non_blockable = QCheckBox("Non-blockable (hero can pass)")
        self._chk_colpf3 = QCheckBox("COLPF3 (codes +128: 129..255)")
        btn_apply_obj = QPushButton("Apply Object Properties")
        btn_apply_obj.clicked.connect(self._on_apply_object_props)

        obj_form.addRow("ID (1..255):", self._spin_obj_id)
        obj_form.addRow("Name:", self._edit_obj_name)
        obj_form.addRow("Group:", self._combo_obj_group)
        obj_form.addRow("Region (glyphs):", reg_row)
        obj_form.addRow(self._chk_non_blockable)
        obj_form.addRow(self._chk_colpf3)
        obj_form.addRow(btn_apply_obj)
        obj_layout.addLayout(obj_form)

        tags_box = QGroupBox("Tags")
        self._tags_layout = QVBoxLayout(tags_box)
        obj_layout.addWidget(tags_box)

        root.addWidget(obj_col, 1)

        # Column 3: Stamp Image Window
        stamp_col = QGroupBox("Stamp Image")
        stamp_layout = QVBoxLayout(stamp_col)
        self._stamp_widget = StampImageWidget(self._renderer, self)
        self._stamp_widget.create_object_requested.connect(self._on_create_from_selection)
        self._stamp_widget.apply_region_requested.connect(self._on_apply_selection_region)
        self._stamp_widget.selection_changed.connect(self._on_stamp_selection_changed)
        self._stamp_widget.preview_palette_changed.connect(self._on_stamp_preview_palette_changed)
        stamp_layout.addWidget(self._stamp_widget, 1)

        root.addWidget(stamp_col, 2)

    def set_context(self, project: Project, undo_stack: UndoStack) -> None:
        self._project = project
        self._undo_stack = undo_stack
        self._preview_palette_by_group.clear()
        self._selected_palette_name = None
        self.refresh()

    def select_group(self, group_name: str) -> None:
        self._selected_group_name = group_name
        self.refresh()

    def select_object(self, obj_id: int) -> None:
        self._selected_object_id = obj_id
        self.refresh()

    def _active_preview_palette_name(self, grp: ObjectGroup | None) -> str:
        if grp is None or not grp.palettes:
            return ""
        chosen = self._preview_palette_by_group.get(grp.name, "")
        if chosen and grp.get_named_palette(chosen) is not None:
            return chosen
        return grp.default_palette_name

    def _rebuild_object_list_items(self) -> None:
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
            preview_pal = None
            if grp is not None:
                pal_name = self._active_preview_palette_name(grp)
                preview_pal = grp.get_palette(pal_name)
            pix = self._renderer.render_object_pixmap(
                obj, grp, scale=2, project=self._project, palette=preview_pal
            )
            err = self._project.object_placement_error(obj)
            tags = []
            if obj.non_blockable:
                tags.append("NB")
            if obj.colpf3:
                tags.append("COLPF3")
            if err:
                tags.append("ERR")
            suffix = f" [{' | '.join(tags)}]" if tags else ""
            item = QListWidgetItem(
                pix,
                f"#{obj.id} {obj.name} ({obj.w}×{obj.h} @ {obj.region.x},{obj.region.y}){suffix}",
            )
            item.setData(Qt.ItemDataRole.UserRole, obj.id)
            self._obj_list.addItem(item)
            if obj.id == self._selected_object_id:
                self._obj_list.setCurrentItem(item)

    def refresh(self) -> None:
        self._block_signals = True
        try:
            self._group_list.clear()
            if (
                self._selected_group_name is None
                or self._project.get_group(self._selected_group_name) is None
            ):
                self._selected_group_name = (
                    self._project.object_groups[0].name if self._project.object_groups else None
                )
            for grp in self._project.object_groups:
                if grp.image is not None:
                    status = "OK"
                elif grp.image_status == "missing":
                    status = "MISSING"
                elif grp.image_status == "invalid":
                    status = "INVALID"
                else:
                    status = "NO PNG"
                used = grp.glyph_table.used_count
                item = QListWidgetItem(
                    f"{grp.name} [{status}] ({used}/{MAX_GLYPHS_PER_GROUP}, {len(grp.palettes)} pal)"
                )
                item.setData(Qt.ItemDataRole.UserRole, grp.name)
                self._group_list.addItem(item)
                if grp.name == self._selected_group_name:
                    self._group_list.setCurrentItem(item)

            self._combo_obj_group.clear()
            for grp in self._project.object_groups:
                self._combo_obj_group.addItem(grp.name, grp.name)

            self._rebuild_object_list_items()

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
        self._btn_del_grp.setEnabled(enabled)
        self._btn_load_png.setEnabled(enabled)
        self._btn_reload_png.setEnabled(enabled and bool(grp and grp.image_path))
        self._btn_edit_mapping.setEnabled(enabled and grp is not None and grp.image is not None)

        self._palette_list.clear()
        self._btn_pal_add.setEnabled(enabled)
        self._btn_pal_dup.setEnabled(enabled and bool(grp and grp.palettes))
        self._btn_pal_rename.setEnabled(enabled and bool(grp and grp.palettes))
        self._btn_pal_del.setEnabled(enabled and bool(grp and len(grp.palettes) > 1))

        if grp is not None:
            self._edit_grp_name.setText(grp.name)
            self._lbl_png_path.setText(grp.image_path or "(none loaded)")
            self._lbl_mapping.setText(_format_mapping(grp.pixel_mapping))
            self._lbl_grp_glyphs.setText(
                f"{grp.glyph_table.used_count} / {MAX_GLYPHS_PER_GROUP} "
                f"({grp.glyph_table.free_slots} free)"
            )

            preferred = self._active_preview_palette_name(grp)
            self._selected_palette_name = preferred or None
            sel_idx = -1
            for idx, pal in enumerate(grp.palettes):
                label = f"{pal.name} [default]" if idx == 0 else pal.name
                pitem = QListWidgetItem(label)
                pitem.setData(Qt.ItemDataRole.UserRole, pal.name)
                self._palette_list.addItem(pitem)
                if pal.name == self._selected_palette_name:
                    self._palette_list.setCurrentItem(pitem)
                    sel_idx = idx

            self._btn_pal_up.setEnabled(sel_idx > 0)
            self._btn_pal_down.setEnabled(0 <= sel_idx < len(grp.palettes) - 1)

            pal_obj = grp.get_palette(self._selected_palette_name)
            self._palette_editor.setEnabled(pal_obj is not None)
            if pal_obj is not None:
                self._palette_editor.set_palette(pal_obj)
        else:
            self._selected_palette_name = None
            self._edit_grp_name.clear()
            self._lbl_png_path.setText("(none)")
            self._lbl_mapping.setText("-")
            self._lbl_grp_glyphs.setText(f"0 / {MAX_GLYPHS_PER_GROUP}")
            self._palette_editor.setEnabled(False)
            self._btn_pal_up.setEnabled(False)
            self._btn_pal_down.setEnabled(False)

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
        self._spin_reg_x.setEnabled(enabled)
        self._spin_reg_y.setEnabled(enabled)
        self._spin_reg_w.setEnabled(enabled)
        self._spin_reg_h.setEnabled(enabled)
        self._chk_non_blockable.setEnabled(enabled)
        self._chk_colpf3.setEnabled(enabled)
        self._btn_del_obj.setEnabled(enabled)
        for cb in self._tag_checkboxes.values():
            cb.setEnabled(enabled)

        if obj is not None:
            self._spin_obj_id.setValue(obj.id)
            self._edit_obj_name.setText(obj.name)
            idx = self._combo_obj_group.findData(obj.group)
            if idx >= 0:
                self._combo_obj_group.setCurrentIndex(idx)
            self._spin_reg_x.setValue(obj.region.x)
            self._spin_reg_y.setValue(obj.region.y)
            self._spin_reg_w.setValue(obj.region.w)
            self._spin_reg_h.setValue(obj.region.h)
            self._chk_non_blockable.setChecked(obj.non_blockable)
            self._chk_colpf3.setChecked(obj.colpf3)
            for tag, cb in self._tag_checkboxes.items():
                cb.setChecked(tag in obj.tags)

            display_grp = self._project.get_group(
                self._selected_group_name if self._selected_group_name else obj.group
            )
            if display_grp is None:
                display_grp = self._project.get_group(obj.group)
            pal_name = self._active_preview_palette_name(display_grp)
            self._stamp_widget.set_data(self._project, display_grp, obj, pal_name)
        else:
            self._edit_obj_name.clear()
            self._chk_non_blockable.setChecked(False)
            self._chk_colpf3.setChecked(False)
            grp = (
                self._project.get_group(self._selected_group_name)
                if self._selected_group_name is not None
                else None
            )
            pal_name = self._active_preview_palette_name(grp)
            self._stamp_widget.set_data(self._project, grp, None, pal_name)

    def _on_group_list_changed(self, row: int) -> None:
        if self._block_signals or row < 0:
            return
        self._selected_group_name = self._group_list.item(row).data(Qt.ItemDataRole.UserRole)
        self._block_signals = True
        try:
            self._sync_group_panel()
            grp = (
                self._project.get_group(self._selected_group_name)
                if self._selected_group_name
                else None
            )
            obj = (
                self._project.get_object(self._selected_object_id)
                if self._selected_object_id is not None
                else None
            )
            pal_name = self._active_preview_palette_name(grp)
            self._stamp_widget.set_data(self._project, grp, obj, pal_name)
        finally:
            self._block_signals = False

    def _on_palette_list_changed(self, row: int) -> None:
        if self._block_signals or row < 0 or not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None:
            return
        pal_name = str(self._palette_list.item(row).data(Qt.ItemDataRole.UserRole))
        self._selected_palette_name = pal_name
        self._preview_palette_by_group[grp.name] = pal_name

        self._block_signals = True
        try:
            pal_obj = grp.get_palette(pal_name)
            if pal_obj is not None:
                self._palette_editor.set_palette(pal_obj)
            self._btn_pal_up.setEnabled(row > 0)
            self._btn_pal_down.setEnabled(row < len(grp.palettes) - 1)
            self._stamp_widget.set_preview_palette(pal_name)
            self._rebuild_object_list_items()
        finally:
            self._block_signals = False
        self.preview_palette_changed.emit(grp.name, pal_name)

    def _on_stamp_preview_palette_changed(self, pal_name: str) -> None:
        if self._block_signals or not self._selected_group_name or not pal_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None or grp.get_named_palette(pal_name) is None:
            return
        self._preview_palette_by_group[grp.name] = pal_name
        self._selected_palette_name = pal_name

        self._block_signals = True
        try:
            for idx in range(self._palette_list.count()):
                if self._palette_list.item(idx).data(Qt.ItemDataRole.UserRole) == pal_name:
                    self._palette_list.setCurrentRow(idx)
                    self._btn_pal_up.setEnabled(idx > 0)
                    self._btn_pal_down.setEnabled(idx < len(grp.palettes) - 1)
                    break
            pal_obj = grp.get_palette(pal_name)
            if pal_obj is not None:
                self._palette_editor.set_palette(pal_obj)
            self._rebuild_object_list_items()
        finally:
            self._block_signals = False
        self.preview_palette_changed.emit(grp.name, pal_name)

    def _on_object_list_changed(self, row: int) -> None:
        if self._block_signals or row < 0:
            return
        self._selected_object_id = int(self._obj_list.item(row).data(Qt.ItemDataRole.UserRole))
        obj = self._project.get_object(self._selected_object_id)
        if obj is not None and self._project.get_group(obj.group) is not None:
            self._selected_group_name = obj.group
        self._block_signals = True
        try:
            self._sync_group_panel()
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
            image_path="",
            palettes=[
                NamedPalette(
                    name=DEFAULT_PALETTE_NAME,
                    colors=self._project.settings.default_palette.copy(),
                )
            ],
            image=None,
            image_status="none",
        )
        self._undo_stack.push_and_execute(AddGroupCommand(self._project, grp))
        self._selected_group_name = name
        self._preview_palette_by_group[name] = DEFAULT_PALETTE_NAME
        self.model_changed.emit()

    def _on_delete_group(self) -> None:
        if not self._selected_group_name:
            return
        used_objs = [o for o in self._project.objects if o.group == self._selected_group_name]
        used_rows = sum(
            1
            for r in self._project.rooms
            if any(ra.group == self._selected_group_name for ra in r.row_groups)
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
            g for g in self._project.object_groups if g.name != self._selected_group_name
        ]
        fallback_group = remaining[0].name if remaining else ""
        fallback_palette = remaining[0].default_palette_name if remaining else ""
        self._undo_stack.push_and_execute(
            DeleteGroupCommand(
                self._project,
                self._selected_group_name,
                fallback_group=fallback_group,
                fallback_palette=fallback_palette,
            )
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
        if grp.name in self._preview_palette_by_group:
            self._preview_palette_by_group[new_name] = self._preview_palette_by_group.pop(grp.name)
        self._undo_stack.push_and_execute(
            UpdateGroupCommand(self._project, grp, name=new_name)
        )
        self._selected_group_name = new_name
        self.model_changed.emit()

    def _on_add_palette(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None:
            return
        src_pal = (
            grp.get_palette(self._selected_palette_name)
            or self._project.settings.default_palette
        )
        new_name = grp.next_free_palette_name("palette")
        new_np = NamedPalette(name=new_name, colors=src_pal.copy())
        self._undo_stack.push_and_execute(AddGroupPaletteCommand(grp, new_np))
        self._preview_palette_by_group[grp.name] = new_name
        self._selected_palette_name = new_name
        self.model_changed.emit()

    def _on_duplicate_palette(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None or not grp.palettes:
            return
        src_name = self._active_preview_palette_name(grp)
        src_pal = grp.get_palette(src_name) or grp.default_palette
        new_name = grp.next_free_palette_name(f"{src_name}_copy")
        new_np = NamedPalette(name=new_name, colors=src_pal.copy())
        self._undo_stack.push_and_execute(
            AddGroupPaletteCommand(
                grp,
                new_np,
                description=f"Duplicate palette '{src_name}' in '{grp.name}'",
            )
        )
        self._preview_palette_by_group[grp.name] = new_name
        self._selected_palette_name = new_name
        self.model_changed.emit()

    def _on_rename_palette(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None or not grp.palettes:
            return
        old_name = self._active_preview_palette_name(grp)
        new_name, ok = QInputDialog.getText(
            self, "Rename Palette", "New palette name:", text=old_name
        )
        if not ok:
            return
        cleaned = new_name.strip()
        if not cleaned:
            QMessageBox.warning(self, "Invalid Name", "Palette name cannot be empty.")
            return
        if cleaned == old_name:
            return
        if grp.get_named_palette(cleaned) is not None:
            QMessageBox.warning(
                self, "Duplicate Name", f"Palette '{cleaned}' already exists in '{grp.name}'."
            )
            return
        self._undo_stack.push_and_execute(
            RenameGroupPaletteCommand(self._project, grp, old_name, cleaned)
        )
        self._preview_palette_by_group[grp.name] = cleaned
        self._selected_palette_name = cleaned
        self.model_changed.emit()

    def _on_delete_palette(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None:
            return
        if len(grp.palettes) <= 1:
            QMessageBox.warning(
                self,
                "Cannot Delete Palette",
                "An object group must keep at least one palette.",
            )
            return
        pal_name = self._active_preview_palette_name(grp)
        usage = self._project.find_palette_usage(grp.name, pal_name)
        if usage:
            fallback_name = next(
                (p.name for p in grp.palettes if p.name != pal_name),
                grp.default_palette_name,
            )
            details = "\n".join(
                f"• Room #{rid} '{rname}': row(s) {', '.join(str(r) for r in rows)}"
                for rid, rname, rows in usage[:10]
            )
            if len(usage) > 10:
                details += f"\n... and {len(usage) - 10} more room(s)."
            ans = QMessageBox.question(
                self,
                "Delete Palette",
                f"Palette '{pal_name}' is used in room rows:\n\n{details}\n\n"
                f"Deleting it will reset those rows to '{fallback_name}'. Continue?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._undo_stack.push_and_execute(
            DeleteGroupPaletteCommand(self._project, grp, pal_name)
        )
        self._preview_palette_by_group[grp.name] = grp.default_palette_name
        self._selected_palette_name = grp.default_palette_name
        self.model_changed.emit()

    def _on_reorder_palette(self, delta: int) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None or len(grp.palettes) <= 1:
            return
        cur_row = self._palette_list.currentRow()
        target_row = cur_row + delta
        if not (0 <= cur_row < len(grp.palettes) and 0 <= target_row < len(grp.palettes)):
            return
        pal_name = grp.palettes[cur_row].name
        self._undo_stack.push_and_execute(
            ReorderGroupPaletteCommand(grp, cur_row, target_row)
        )
        self._preview_palette_by_group[grp.name] = pal_name
        self._selected_palette_name = pal_name
        self.model_changed.emit()

    def _on_group_palette_changed(self, new_palette: Palette) -> None:
        if self._block_signals or not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None or not grp.palettes:
            return
        pal_name = self._active_preview_palette_name(grp)
        if not pal_name:
            return
        self._undo_stack.push_and_execute(
            UpdateGroupPaletteColorsCommand(grp, pal_name, new_palette)
        )
        self.model_changed.emit()

    def _format_stored_path(self, file_path: Path) -> str:
        project_file = self._project_file_provider()
        if project_file is not None:
            return to_relative_posix_path(file_path, project_file)
        return file_path.as_posix()

    def _on_load_png(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None:
            return
        start_dir = (
            str(self._project_file_provider().parent)
            if self._project_file_provider() is not None
            else ""
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Indexed PNG Image", start_dir, "PNG Images (*.png);;All Files (*)"
        )
        if not path:
            return
        png_path = Path(path)
        try:
            img = load_png(png_path)
        except PngLoadError as exc:
            QMessageBox.critical(self, "Invalid PNG Image", str(exc))
            return

        pal = grp.get_palette(self._active_preview_palette_name(grp)) or grp.default_palette
        dlg = PngImportDialog(
            img,
            pal,
            self._renderer,
            initial_mapping=grp.pixel_mapping,
            title=f"Import PNG — Group '{grp.name}'",
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        mapping = dlg.selected_mapping()
        stored_path = self._format_stored_path(png_path)

        self._undo_stack.push_and_execute(
            UpdateGroupCommand(
                self._project,
                grp,
                image_path=stored_path,
                image=img,
                update_image=True,
                image_status="ok",
                image_error="",
                pixel_mapping=mapping,
            )
        )
        self._warn_post_image_load(grp)
        self.model_changed.emit()

    def _on_reload_png(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None:
            return
        if not grp.image_path:
            self._on_load_png()
            return

        project_file = self._project_file_provider()
        base_dir = project_file.resolve().parent if project_file is not None else Path.cwd()
        resolved = resolve_image_path(grp.image_path, base_dir)
        try:
            img = load_png(resolved)
        except PngMissingError:
            self._undo_stack.push_and_execute(
                UpdateGroupCommand(
                    self._project,
                    grp,
                    image=None,
                    update_image=True,
                    image_status="missing",
                    image_error="",
                )
            )
            ans = QMessageBox.warning(
                self,
                "Missing PNG File",
                f"PNG file not found:\n{resolved}\n\n"
                "Would you like to locate a replacement PNG file?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            self.model_changed.emit()
            if ans == QMessageBox.StandardButton.Yes:
                self._on_load_png()
            return
        except PngLoadError as exc:
            self._undo_stack.push_and_execute(
                UpdateGroupCommand(
                    self._project,
                    grp,
                    image=None,
                    update_image=True,
                    image_status="invalid",
                    image_error=str(exc),
                )
            )
            QMessageBox.critical(
                self,
                "Invalid PNG After Reload",
                f"Reloading PNG failed validation (objects preserved as errors):\n\n{exc}",
            )
            self.model_changed.emit()
            return

        self._undo_stack.push_and_execute(
            UpdateGroupCommand(
                self._project,
                grp,
                image=img,
                update_image=True,
                image_status="ok",
                image_error="",
            )
        )
        self._warn_post_image_load(grp)
        self.model_changed.emit()

    def _warn_post_image_load(self, grp: ObjectGroup) -> None:
        analysis = grp.glyph_analysis
        if analysis is None:
            return
        problems: list[str] = []
        if analysis.invalid_region_object_ids:
            problems.append(
                "Out-of-image region on object ID(s): "
                + ", ".join(str(i) for i in sorted(analysis.invalid_region_object_ids))
            )
        if analysis.empty_object_ids:
            problems.append(
                "All-empty glyphs on object ID(s): "
                + ", ".join(str(i) for i in sorted(analysis.empty_object_ids))
            )
        if analysis.overflow_object_ids:
            problems.append(
                f"Exceeds {MAX_GLYPHS_PER_GROUP} glyph limit on object ID(s): "
                + ", ".join(str(i) for i in sorted(analysis.overflow_object_ids))
            )
        if problems:
            QMessageBox.warning(
                self,
                "Group Image Issues",
                f"Reloaded PNG for group '{grp.name}', but some objects now have errors "
                "(no data was deleted; fix before placing):\n\n• "
                + "\n• ".join(problems),
            )

    def _on_edit_mapping(self) -> None:
        if not self._selected_group_name:
            return
        grp = self._project.get_group(self._selected_group_name)
        if grp is None or grp.image is None:
            return
        pal = grp.get_palette(self._active_preview_palette_name(grp)) or grp.default_palette
        dlg = PngImportDialog(
            grp.image,
            pal,
            self._renderer,
            initial_mapping=grp.pixel_mapping,
            project=self._project,
            group_name=grp.name,
            title=f"Edit Pixel Mapping — Group '{grp.name}'",
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_mapping = dlg.selected_mapping()
        if new_mapping != grp.pixel_mapping:
            self._undo_stack.push_and_execute(
                UpdateGroupCommand(self._project, grp, pixel_mapping=new_mapping)
            )
            self.model_changed.emit()

    def _on_add_object(self) -> None:
        sel = self._stamp_widget.current_selection()
        if sel is None:
            sel = StampRegion(0, 0, 1, 1)
        self._on_create_from_selection(sel)

    def _on_create_from_selection(self, region: StampRegion) -> None:
        new_id = self._project.next_free_object_id()
        if new_id is None:
            QMessageBox.warning(self, "Object Limit", f"Cannot exceed {MAX_OBJECTS} objects.")
            return
        if not self._project.object_groups:
            QMessageBox.warning(self, "No Group", "Create an object group before creating objects.")
            return
        grp_name = self._selected_group_name or self._project.object_groups[0].name
        grp = self._project.get_group(grp_name)
        if grp is None or grp.image is None:
            QMessageBox.warning(
                self,
                "No PNG Image",
                f"Load a valid indexed PNG image for group '{grp_name}' before creating objects.",
            )
            return

        check = self._project.check_region_glyph_budget(grp_name, region)
        if not check.ok:
            QMessageBox.warning(self, "Cannot Create Object", check.error_message)
            return

        existing_names = {o.name for o in self._project.objects}
        idx = new_id
        while f"obj_{idx}" in existing_names:
            idx += 1
        obj = GameObject(
            id=new_id,
            name=f"obj_{idx}",
            group=grp_name,
            region=region,
        )
        self._undo_stack.push_and_execute(AddObjectCommand(self._project, obj))
        self._selected_object_id = obj.id
        self.model_changed.emit()

    def _on_stamp_selection_changed(self, region: StampRegion) -> None:
        if self._block_signals:
            return
        self._block_signals = True
        try:
            self._spin_reg_x.setValue(region.x)
            self._spin_reg_y.setValue(region.y)
            self._spin_reg_w.setValue(region.w)
            self._spin_reg_h.setValue(region.h)
        finally:
            self._block_signals = False

    def _on_apply_selection_region(self, region: StampRegion) -> None:
        if self._selected_object_id is None:
            return
        self._spin_reg_x.setValue(region.x)
        self._spin_reg_y.setValue(region.y)
        self._spin_reg_w.setValue(region.w)
        self._spin_reg_h.setValue(region.h)
        self._on_apply_object_props()

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
        new_region = StampRegion(
            x=self._spin_reg_x.value(),
            y=self._spin_reg_y.value(),
            w=self._spin_reg_w.value(),
            h=self._spin_reg_h.value(),
        )
        new_nb = self._chk_non_blockable.isChecked()
        new_colpf3 = self._chk_colpf3.isChecked()

        if not new_name:
            QMessageBox.warning(self, "Invalid Name", "Object name cannot be empty.")
            return
        if new_region.cell_count > MAX_OBJECT_CELLS:
            QMessageBox.warning(
                self,
                "Size Limit Exceeded",
                f"Object size {new_region.w}×{new_region.h} = {new_region.cell_count} cells "
                f"exceeds the {MAX_OBJECT_CELLS}-cell limit.",
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

        target_grp = self._project.get_group(new_group)
        if target_grp is not None and target_grp.image is not None:
            exclude_id = obj.id if new_group == obj.group else None
            check = self._project.check_region_glyph_budget(
                new_group,
                new_region,
                exclude_object_id=exclude_id,
            )
            if not check.ok:
                QMessageBox.warning(self, "Invalid Object Region / Glyph Limit", check.error_message)
                return

        if not new_nb:
            conflicts = self._project.find_blockable_overlaps_for_object(
                obj.id,
                new_region=new_region,
                new_group=new_group,
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
                    "Cannot apply change because placed blockable instances would "
                    f"overlap other blockable instances:\n\n{preview}",
                )
                self._sync_object_panel()
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
                colpf3=new_colpf3,
                region=new_region,
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
