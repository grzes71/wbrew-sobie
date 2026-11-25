"""Dialog for choosing and previewing PNG-index -> ANTIC 4 pixel mapping."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.glyphs import (
    DEFAULT_PIXEL_MAPPING,
    IndexedImage,
    MAX_GLYPHS_PER_GROUP,
)
from room_editor.model.palette import Palette
from room_editor.model.project import Project
from room_editor.ui.rendering_qt import QtRenderer

_ANTIC_LABELS = (
    (0, "00 — COLBK (Empty / Transparent)"),
    (1, "01 — COLPF0"),
    (2, "10 — COLPF1"),
    (3, "11 — COLPF2 / COLPF3"),
)


class PngImportDialog(QDialog):
    """Modal dialog for configuring pixel mapping with a live 2:1 ANTIC 4 preview."""

    def __init__(
        self,
        image: IndexedImage,
        palette: Palette,
        renderer: QtRenderer,
        initial_mapping: tuple[int, int, int, int] = DEFAULT_PIXEL_MAPPING,
        *,
        project: Project | None = None,
        group_name: str | None = None,
        title: str = "PNG Import & Pixel Mapping",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)

        self._image = image
        self._palette = palette
        self._renderer = renderer
        self._project = project
        self._group_name = group_name
        self._mapping = list(initial_mapping)
        self._block_combos = False

        layout = QVBoxLayout(self)

        info = QLabel(
            f"Image: {image.width}×{image.height} px  "
            f"({image.glyph_cols}×{image.glyph_rows} glyphs of 4×8 px). "
            "Assign each PNG palette index (0..3) to a unique ANTIC 4 pixel value."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Mapping controls
        form = QFormLayout()
        self._combos: list[QComboBox] = []
        for idx in range(4):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            r, g, b = image.file_palette[idx]
            swatch = QLabel()
            swatch.setFixedSize(28, 20)
            swatch.setStyleSheet(
                f"background-color: rgb({r}, {g}, {b}); border: 1px solid #777;"
            )
            swatch.setToolTip(f"PNG palette index {idx}: RGB({r}, {g}, {b})")
            row_layout.addWidget(swatch)

            combo = QComboBox()
            for val, text in _ANTIC_LABELS:
                combo.addItem(text, val)
            pos = combo.findData(self._mapping[idx])
            combo.setCurrentIndex(pos if pos >= 0 else idx)
            combo.currentIndexChanged.connect(
                lambda _cidx, i=idx: self._on_combo_changed(i)
            )
            self._combos.append(combo)
            row_layout.addWidget(combo, 1)

            form.addRow(f"PNG Index {idx}:", row_widget)
        layout.addLayout(form)

        # Preview controls bar
        ctrl_bar = QHBoxLayout()
        btn_reset = QPushButton("Reset Identity (0→00, 1→01, 2→10, 3→11)")
        btn_reset.clicked.connect(self._on_reset_identity)
        ctrl_bar.addWidget(btn_reset)

        self._chk_file_palette = QCheckBox("As in file (PNG palette)")
        self._chk_file_palette.toggled.connect(self._update_preview)
        ctrl_bar.addWidget(self._chk_file_palette)

        self._chk_colpf3 = QCheckBox("Preview with COLPF3")
        self._chk_colpf3.toggled.connect(self._update_preview)
        ctrl_bar.addWidget(self._chk_colpf3)

        ctrl_bar.addWidget(QLabel("Zoom:"))
        self._spin_zoom = QSpinBox()
        self._spin_zoom.setRange(1, 6)
        self._spin_zoom.setValue(3)
        self._spin_zoom.valueChanged.connect(self._update_preview)
        ctrl_bar.addWidget(self._spin_zoom)
        ctrl_bar.addStretch()
        layout.addLayout(ctrl_bar)

        # Live preview
        self._preview_label = QLabel()
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(self._preview_label)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 1)

        # Impact / validation status for existing group
        self._lbl_status = QLabel()
        self._lbl_status.setWordWrap(True)
        layout.addWidget(self._lbl_status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    def selected_mapping(self) -> tuple[int, int, int, int]:
        return (self._mapping[0], self._mapping[1], self._mapping[2], self._mapping[3])

    def _on_combo_changed(self, changed_idx: int) -> None:
        if self._block_combos:
            return
        new_val = int(self._combos[changed_idx].currentData())
        old_val = self._mapping[changed_idx]
        if new_val == old_val:
            return

        # Keep mapping a valid permutation by swapping with whichever index held new_val
        self._block_combos = True
        try:
            for other_idx in range(4):
                if other_idx != changed_idx and self._mapping[other_idx] == new_val:
                    self._mapping[other_idx] = old_val
                    pos = self._combos[other_idx].findData(old_val)
                    if pos >= 0:
                        self._combos[other_idx].setCurrentIndex(pos)
                    break
            self._mapping[changed_idx] = new_val
        finally:
            self._block_combos = False

        self._update_preview()

    def _on_reset_identity(self) -> None:
        self._block_combos = True
        try:
            self._mapping = list(DEFAULT_PIXEL_MAPPING)
            for idx in range(4):
                pos = self._combos[idx].findData(self._mapping[idx])
                if pos >= 0:
                    self._combos[idx].setCurrentIndex(pos)
        finally:
            self._block_combos = False
        self._update_preview()

    def _update_preview(self) -> None:
        use_file = self._chk_file_palette.isChecked()
        self._chk_colpf3.setEnabled(not use_file)
        colpf3 = self._chk_colpf3.isChecked() and not use_file
        zoom = self._spin_zoom.value()

        qimg = self._renderer.indexed_image_qimage(
            self._image,
            self._palette,
            self.selected_mapping(),
            colpf3=colpf3,
            use_file_palette=use_file,
        )
        pix = QPixmap.fromImage(qimg).scaled(
            qimg.width() * zoom,
            qimg.height() * zoom,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self._preview_label.setPixmap(pix)

        if self._project is not None and self._group_name is not None:
            check = self._project.check_mapping_change(
                self._group_name, self.selected_mapping()
            )
            if check.ok:
                self._lbl_status.setStyleSheet("color: #7ee081;")
                self._lbl_status.setText(
                    f"Valid mapping: {check.total_unique}/{MAX_GLYPHS_PER_GROUP} unique glyphs "
                    f"({check.free_slots} free slot(s))."
                )
            else:
                self._lbl_status.setStyleSheet("color: #ff6b6b;")
                self._lbl_status.setText("Cannot apply:\n• " + "\n• ".join(check.problems[:4]))
        else:
            self._lbl_status.setStyleSheet("color: #aaa;")
            self._lbl_status.setText("Pixel 00 (COLBK) cells count as empty / transparent.")

    def _on_accept(self) -> None:
        if self._project is not None and self._group_name is not None:
            check = self._project.check_mapping_change(
                self._group_name, self.selected_mapping()
            )
            if not check.ok:
                QMessageBox.warning(
                    self,
                    "Mapping Change Rejected",
                    "The new pixel mapping cannot be applied because it breaks existing objects:\n\n"
                    + "\n".join(f"• {p}" for p in check.problems),
                )
                return
        self.accept()
