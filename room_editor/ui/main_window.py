"""MainWindow for the Atari 8-bit Room Editor (PySide6)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QTextEdit,
)

from room_editor.io.png import PngLoadError, load_png, to_relative_posix_path
from room_editor.io.yaml_io import ProjectIOError, load_project, save_project
from room_editor.model.commands import UndoStack, ZOrderAction
from room_editor.model.palette import load_default_pal_palette
from room_editor.model.project import Project
from room_editor.model.validation import ValidationIssue, validate_project
from room_editor.ui.canvas_view import RoomCanvasView
from room_editor.ui.objects_view import ObjectsView
from room_editor.ui.rendering_qt import QtRenderer
from room_editor.ui.room_editor_view import RoomEditorView, ToolName
from room_editor.ui.settings_view import SettingsView
from room_editor.ui.validation_dialog import ValidationDialog


class MainWindow(QMainWindow):
    """Top-level window coordinating tabs, menus, shortcuts, status bar, and persistence."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(1360, 860)

        self.pal_table = load_default_pal_palette()
        self.renderer = QtRenderer(self.pal_table)
        self.project = Project()
        self.project_path: Path | None = None
        self.undo_stack = UndoStack(max_depth=250)
        self.undo_stack.add_listener(self._update_window_title)

        self._grid_visible = True
        self._validation_dialog: ValidationDialog | None = None

        self._setup_ui()
        self._setup_menus()
        self._setup_shortcuts()
        self._setup_statusbar()

        self._bind_context()
        self._update_window_title()

    def _setup_ui(self) -> None:
        self.tabs = QTabWidget(self)
        self.setCentralWidget(self.tabs)

        self.canvas_view = RoomCanvasView(self.renderer, self)
        self.canvas_view.open_room_requested.connect(self._open_room_in_editor)
        self.canvas_view.model_changed.connect(self._on_model_changed)

        self.room_editor_view = RoomEditorView(self.renderer, self)
        self.room_editor_view.cursor_status.connect(self._on_cursor_status)
        self.room_editor_view.model_changed.connect(self._on_model_changed)

        self.objects_view = ObjectsView(self.renderer, self.pal_table, self)
        self.objects_view.set_project_file_provider(lambda: self.project_path)
        self.objects_view.model_changed.connect(self._on_model_changed)
        self.objects_view.preview_palette_changed.connect(
            self.room_editor_view.set_preview_palette
        )

        self.settings_view = SettingsView(self.pal_table, self)
        self.settings_view.model_changed.connect(self._on_model_changed)

        self.tabs.addTab(self.canvas_view, "Room Canvas")
        self.tabs.addTab(self.room_editor_view, "Room Editor")
        self.tabs.addTab(self.objects_view, "Objects & Groups")
        self.tabs.addTab(self.settings_view, "Settings")

    def _setup_menus(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")
        act_new = QAction("&New Project", self)
        act_new.setShortcut(QKeySequence.StandardKey.New)
        act_new.triggered.connect(self.action_new)
        file_menu.addAction(act_new)

        act_open = QAction("&Open...", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.action_open)
        file_menu.addAction(act_open)

        act_save = QAction("&Save", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self.action_save)
        file_menu.addAction(act_save)

        act_save_as = QAction("Save &As...", self)
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_save_as.triggered.connect(self.action_save_as)
        file_menu.addAction(act_save_as)

        file_menu.addSeparator()
        act_exit = QAction("E&xit", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")
        self._act_undo = QAction("&Undo", self)
        self._act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        self._act_undo.triggered.connect(self.action_undo)
        edit_menu.addAction(self._act_undo)

        self._act_redo = QAction("&Redo", self)
        self._act_redo.setShortcut(QKeySequence("Ctrl+Y"))
        self._act_redo.triggered.connect(self.action_redo)
        edit_menu.addAction(self._act_redo)

        edit_menu.addSeparator()
        act_copy = QAction("&Copy", self)
        act_copy.setShortcut(QKeySequence("Ctrl+C"))
        act_copy.triggered.connect(self._on_copy)
        edit_menu.addAction(act_copy)

        act_cut = QAction("Cu&t", self)
        act_cut.setShortcut(QKeySequence("Ctrl+X"))
        act_cut.triggered.connect(self._on_cut)
        edit_menu.addAction(act_cut)

        act_paste = QAction("&Paste", self)
        act_paste.setShortcut(QKeySequence("Ctrl+V"))
        act_paste.triggered.connect(self._on_paste)
        edit_menu.addAction(act_paste)

        act_delete = QAction("&Delete", self)
        act_delete.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        act_delete.triggered.connect(self._on_delete)
        edit_menu.addAction(act_delete)

        arrange_menu = edit_menu.addMenu("Arrange (&Z-Order)")
        for label, shortcut, action_name in (
            ("Bring to &Front", "Ctrl+Shift+]", "bring_to_front"),
            ("Move &Up", "Ctrl+]", "move_up"),
            ("Move &Down", "Ctrl+[", "move_down"),
            ("Send to &Back", "Ctrl+Shift+[", "send_to_back"),
        ):
            act = QAction(label, self)
            act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(
                lambda checked=False, a=action_name: self._on_reorder(a)  # type: ignore[arg-type]
            )
            arrange_menu.addAction(act)

        # Project menu
        proj_menu = menubar.addMenu("&Project")
        act_validate = QAction("&Validate Project", self)
        act_validate.setShortcut(QKeySequence("F7"))
        act_validate.triggered.connect(self.action_validate)
        proj_menu.addAction(act_validate)

    def _setup_shortcuts(self) -> None:
        # Single-key shortcuts for grid and tools (ignored when typing in text/spin controls)
        self._key_shortcuts: list[QShortcut] = []
        sc_grid = QShortcut(QKeySequence("G"), self)
        sc_grid.activated.connect(self._toggle_grid)
        self._key_shortcuts.append(sc_grid)

        for key, tool in (
            ("S", "stamp"),
            ("E", "eraser"),
            ("F", "fill"),
            ("L", "line"),
            ("R", "rect"),
            ("V", "select"),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda t=tool: self._select_tool(t))  # type: ignore[arg-type]
            self._key_shortcuts.append(sc)

    def _setup_statusbar(self) -> None:
        self._lbl_pos = QLabel("Pos: (-, -)")
        self._lbl_char = QLabel("Char: -")
        self._lbl_group = QLabel("Group: -")
        sb = self.statusBar()
        sb.addPermanentWidget(self._lbl_pos)
        sb.addPermanentWidget(self._lbl_char)
        sb.addPermanentWidget(self._lbl_group)

    def _text_input_focused(self) -> bool:
        w = self.focusWidget()
        return isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox))

    def _bind_context(self) -> None:
        self.canvas_view.set_context(self.project, self.undo_stack)
        self.room_editor_view.set_context(self.project, self.undo_stack)
        self.objects_view.set_context(self.project, self.undo_stack)
        self.settings_view.set_context(self.project, self.undo_stack)

    def _refresh_all_views(self) -> None:
        self.canvas_view.refresh()
        self.room_editor_view.refresh()
        self.objects_view.refresh()
        self.settings_view.refresh()
        self._update_window_title()

    def _update_window_title(self) -> None:
        name = self.project_path.name if self.project_path else "Untitled"
        dirty = "*" if self.undo_stack.is_dirty else ""
        self.setWindowTitle(f"Atari Room Editor — {name}{dirty}")
        if hasattr(self, "_act_undo"):
            self._act_undo.setEnabled(self.undo_stack.can_undo)
            self._act_redo.setEnabled(self.undo_stack.can_redo)

    def _on_model_changed(self) -> None:
        self._refresh_all_views()

    def _open_room_in_editor(self, room_id: int) -> None:
        self.room_editor_view.set_current_room(room_id)
        self.tabs.setCurrentWidget(self.room_editor_view)

    def _on_cursor_status(
        self,
        x: int,
        y: int,
        char_code: int,
        row_group: str,
        row_palette: str,
    ) -> None:
        self._lbl_pos.setText(f"Pos: ({x}, {y})")
        self._lbl_char.setText(
            f"Char: ${char_code:02X} ({char_code})" if char_code else "Char: 0 (empty)"
        )
        if row_group:
            pal_disp = row_palette or "(default)"
            self._lbl_group.setText(f"Row: {row_group} / {pal_disp}")
        else:
            self._lbl_group.setText("Row: (none)")

    def _toggle_grid(self) -> None:
        if self._text_input_focused():
            return
        self._grid_visible = not self._grid_visible
        self.canvas_view.set_grid_visible(self._grid_visible)
        self.room_editor_view.set_grid_visible(self._grid_visible)

    def _select_tool(self, tool: ToolName) -> None:
        if self._text_input_focused():
            return
        self.room_editor_view.set_tool(tool)

    def _on_copy(self) -> None:
        focus = self.focusWidget()
        if isinstance(focus, QLineEdit) and focus.hasSelectedText():
            focus.copy()
            return
        if self.tabs.currentWidget() is self.room_editor_view:
            self.room_editor_view.copy_selection()

    def _on_cut(self) -> None:
        focus = self.focusWidget()
        if isinstance(focus, QLineEdit) and focus.hasSelectedText():
            focus.cut()
            return
        if self.tabs.currentWidget() is self.room_editor_view:
            self.room_editor_view.cut_selection()

    def _on_paste(self) -> None:
        focus = self.focusWidget()
        if isinstance(focus, QLineEdit):
            focus.paste()
            return
        if self.tabs.currentWidget() is self.room_editor_view:
            self.room_editor_view.paste_clipboard()

    def _on_delete(self) -> None:
        if self._text_input_focused():
            return
        if self.tabs.currentWidget() is self.room_editor_view:
            self.room_editor_view.delete_selection()

    def _on_reorder(self, action: ZOrderAction) -> None:
        if self._text_input_focused():
            return
        if self.tabs.currentWidget() is self.room_editor_view:
            self.room_editor_view.reorder_selection(action)

    def action_undo(self) -> None:
        if self.undo_stack.undo() is not None:
            self._refresh_all_views()

    def action_redo(self) -> None:
        if self.undo_stack.redo() is not None:
            self._refresh_all_views()

    def _confirm_discard_changes(self) -> bool:
        if not self.undo_stack.is_dirty:
            return True
        ans = QMessageBox.warning(
            self,
            "Unsaved Changes",
            "The current project has unsaved changes. Do you want to save before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Save:
            return self.action_save()
        return ans == QMessageBox.StandardButton.Discard

    def action_new(self) -> None:
        if not self._confirm_discard_changes():
            return
        self.project = Project()
        self.project_path = None
        self.undo_stack.clear()
        self.renderer.clear_cache()
        self._bind_context()
        self._update_window_title()

    def action_open(self) -> None:
        if not self._confirm_discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Room Project", "", "YAML Project (*.yaml *.yml);;All Files (*)"
        )
        if not path:
            return
        proj_path = Path(path)
        try:
            result = load_project(proj_path)
        except ProjectIOError as exc:
            QMessageBox.critical(self, "Open Failed", str(exc))
            return

        self.project = result.project
        self.project_path = proj_path
        self.undo_stack.clear()
        self.renderer.clear_cache()

        if result.invalid_images:
            inv_details = "\n".join(
                f"• Group '{g}' ({p}): {err}" for g, p, err in result.invalid_images
            )
            QMessageBox.warning(
                self,
                "Invalid PNG Images",
                f"Some PNG images failed validation:\n{inv_details}",
            )

        if result.missing_images:
            self._handle_missing_images(result.missing_images, proj_path)

        if result.glyph_table_mismatches:
            lines = [
                f"• Group '{g}': {msg}" for g, msg in result.glyph_table_mismatches
            ]
            QMessageBox.warning(
                self,
                "Glyph Tables Regenerated",
                "Stored glyph tables in the YAML did not match the PNG images and were recomputed:\n\n"
                + "\n".join(lines),
            )

        self._bind_context()
        self._update_window_title()

    def _handle_missing_images(
        self,
        missing: list[tuple[str, str]],
        proj_path: Path,
    ) -> None:
        details = "\n".join(f"• Group '{g}': {p or '(empty path)'}" for g, p in missing)
        ans = QMessageBox.warning(
            self,
            "Missing PNG Files",
            f"Some PNG files could not be found:\n{details}\n\n"
            "Would you like to locate replacement PNG files now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        changed = False
        for grp_name, old_path in missing:
            grp = self.project.get_group(grp_name)
            if grp is None:
                continue
            new_path, _ = QFileDialog.getOpenFileName(
                self,
                f"Locate PNG for group '{grp_name}' (was: {old_path})",
                str(proj_path.parent),
                "PNG Images (*.png);;All Files (*)",
            )
            if not new_path:
                continue
            try:
                png_path = Path(new_path)
                grp.image = load_png(png_path)
                grp.image_path = to_relative_posix_path(png_path, proj_path)
                grp.image_status = "ok"
                grp.image_error = ""
                changed = True
            except PngLoadError as exc:
                QMessageBox.critical(self, "Invalid PNG Image", str(exc))
        if changed:
            self.project.rebuild_glyph_tables()

    def action_save(self) -> bool:
        if self.project_path is None:
            return self.action_save_as()
        return self._save_to(self.project_path)

    def action_save_as(self) -> bool:
        default_name = str(self.project_path) if self.project_path else "rooms.yaml"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Room Project", default_name, "YAML Project (*.yaml);;All Files (*)"
        )
        if not path:
            return False
        if not path.lower().endswith((".yaml", ".yml")):
            path = f"{path}.yaml"
        return self._save_to(Path(path))

    def _save_to(self, path: Path) -> bool:
        issues = validate_project(self.project)
        if issues:
            self._show_validation_dialog(issues)
            errors = [i for i in issues if i.severity == "error"]
            if errors:
                ans = QMessageBox.question(
                    self,
                    "Validation Errors",
                    f"Project has {len(errors)} validation error(s). Save anyway?",
                )
                if ans != QMessageBox.StandardButton.Yes:
                    return False

        try:
            save_project(self.project, path)
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", f"Failed to save project:\n{exc}")
            return False

        self.project_path = path
        self.undo_stack.mark_clean()
        self._refresh_all_views()
        self.statusBar().showMessage(f"Saved: {path.name}", 3000)
        return True

    def action_validate(self) -> None:
        issues = validate_project(self.project)
        if not issues:
            QMessageBox.information(self, "Validation", "No errors or warnings found.")
            return
        self._show_validation_dialog(issues)

    def _show_validation_dialog(self, issues: list[ValidationIssue]) -> None:
        if self._validation_dialog is not None:
            self._validation_dialog.close()
        dlg = ValidationDialog(issues, self)
        dlg.issue_activated.connect(self._navigate_to_issue)
        dlg.show()
        self._validation_dialog = dlg

    def _navigate_to_issue(self, issue: ValidationIssue) -> None:
        if issue.target_type == "room" and isinstance(issue.target_id, int):
            if issue.x is not None or issue.y is not None:
                self._open_room_in_editor(issue.target_id)
            else:
                self.canvas_view.select_room(issue.target_id)
                self.tabs.setCurrentWidget(self.canvas_view)
        elif issue.target_type == "object" and isinstance(issue.target_id, int):
            self.objects_view.select_object(issue.target_id)
            self.tabs.setCurrentWidget(self.objects_view)
        elif issue.target_type == "group" and isinstance(issue.target_id, str):
            self.objects_view.select_group(issue.target_id)
            self.tabs.setCurrentWidget(self.objects_view)
        elif issue.target_type in ("teleport", "start"):
            if isinstance(issue.target_id, int) and issue.target_type == "start":
                self.canvas_view.select_room(issue.target_id)
            self.tabs.setCurrentWidget(self.canvas_view)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard_changes():
            event.accept()
        else:
            event.ignore()
