"""Settings tab: global default palette and global tag management (F-10, F-15)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.commands import (
    AddTagCommand,
    DeleteTagCommand,
    RenameTagCommand,
    UndoStack,
    UpdateDefaultPaletteCommand,
)
from room_editor.model.palette import PalPaletteTable, Palette
from room_editor.model.project import Project
from room_editor.ui.color_picker import PaletteEditorWidget


class SettingsView(QWidget):
    """Tab widget for global default palette and global tag list."""

    model_changed = Signal()

    def __init__(self, pal_table: PalPaletteTable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pal_table = pal_table
        self._project = Project()
        self._undo_stack = UndoStack()
        self._block_signals = False

        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QHBoxLayout(self)

        # Global default palette
        pal_box = QGroupBox("Default Palette (copied to new Object Groups)")
        pal_layout = QVBoxLayout(pal_box)
        self._palette_editor = PaletteEditorWidget(self._pal_table, self)
        self._palette_editor.palette_changed.connect(self._on_default_palette_changed)
        pal_layout.addWidget(self._palette_editor)
        pal_layout.addStretch()
        root.addWidget(pal_box, 1)

        # Global tags
        tag_box = QGroupBox("Global Tags")
        tag_layout = QVBoxLayout(tag_box)
        self._tag_list = QListWidget()
        tag_layout.addWidget(self._tag_list, 1)

        btns = QHBoxLayout()
        btn_add = QPushButton("Add Tag...")
        btn_add.clicked.connect(self._on_add_tag)
        btn_rename = QPushButton("Rename Tag...")
        btn_rename.clicked.connect(self._on_rename_tag)
        btn_del = QPushButton("Delete Tag")
        btn_del.clicked.connect(self._on_delete_tag)
        btns.addWidget(btn_add)
        btns.addWidget(btn_rename)
        btns.addWidget(btn_del)
        tag_layout.addLayout(btns)
        root.addWidget(tag_box, 1)

    def set_context(self, project: Project, undo_stack: UndoStack) -> None:
        self._project = project
        self._undo_stack = undo_stack
        self.refresh()

    def refresh(self) -> None:
        self._block_signals = True
        try:
            self._palette_editor.set_palette(self._project.settings.default_palette)
            cur = self._tag_list.currentItem().text() if self._tag_list.currentItem() else None
            self._tag_list.clear()
            for tag in self._project.tags:
                self._tag_list.addItem(tag)
            if cur is not None:
                for i in range(self._tag_list.count()):
                    if self._tag_list.item(i).text() == cur:
                        self._tag_list.setCurrentRow(i)
                        break
        finally:
            self._block_signals = False

    def _on_default_palette_changed(self, palette: Palette) -> None:
        if self._block_signals:
            return
        self._undo_stack.push_and_execute(
            UpdateDefaultPaletteCommand(self._project, palette)
        )
        self.model_changed.emit()

    def _on_add_tag(self) -> None:
        text, ok = QInputDialog.getText(self, "Add Tag", "Tag name:")
        if not ok:
            return
        tag = text.strip()
        if not tag:
            QMessageBox.warning(self, "Invalid Tag", "Tag name cannot be empty.")
            return
        if tag in self._project.tags:
            QMessageBox.warning(self, "Duplicate Tag", f"Tag '{tag}' already exists.")
            return
        self._undo_stack.push_and_execute(AddTagCommand(self._project, tag))
        self.model_changed.emit()

    def _on_rename_tag(self) -> None:
        item = self._tag_list.currentItem()
        if item is None:
            return
        old_tag = item.text()
        text, ok = QInputDialog.getText(self, "Rename Tag", "New tag name:", text=old_tag)
        if not ok:
            return
        new_tag = text.strip()
        if not new_tag:
            QMessageBox.warning(self, "Invalid Tag", "Tag name cannot be empty.")
            return
        if new_tag == old_tag:
            return
        if new_tag in self._project.tags:
            QMessageBox.warning(self, "Duplicate Tag", f"Tag '{new_tag}' already exists.")
            return
        self._undo_stack.push_and_execute(RenameTagCommand(self._project, old_tag, new_tag))
        self.model_changed.emit()

    def _on_delete_tag(self) -> None:
        item = self._tag_list.currentItem()
        if item is None:
            return
        tag = item.text()
        used_count = sum(1 for o in self._project.objects if tag in o.tags)
        msg = (
            f"Delete tag '{tag}'? It is assigned to {used_count} object(s) and will be removed from them."
            if used_count
            else f"Delete tag '{tag}'?"
        )
        if QMessageBox.question(self, "Delete Tag", msg) != QMessageBox.StandardButton.Yes:
            return
        self._undo_stack.push_and_execute(DeleteTagCommand(self._project, tag))
        self.model_changed.emit()
