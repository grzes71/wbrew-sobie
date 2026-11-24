"""Atari PAL 256-color palette picker dialog and 5-register palette editor."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.palette import PalPaletteTable, Palette


class AtariColorPickerDialog(QDialog):
    """Modal dialog showing the 16x8 Atari PAL palette grid (luminance bit 0 ignored)."""

    def __init__(
        self,
        pal_table: PalPaletteTable,
        initial_color: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Atari PAL Color Picker")
        self._pal_table = pal_table
        self._selected_color = int(initial_color) & 0xFE
        self._buttons: dict[int, QPushButton] = {}

        layout = QVBoxLayout(self)

        self._info_label = QLabel()
        layout.addWidget(self._info_label)

        grid = QGridLayout()
        grid.setSpacing(2)
        for hue in range(16):
            lbl_hue = QLabel(f"${hue:X}x")
            lbl_hue.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(lbl_hue, hue, 0)
            for lum_step in range(8):
                color_val = (hue << 4) | (lum_step << 1)
                r, g, b = self._pal_table.rgb(color_val)
                btn = QPushButton()
                btn.setFixedSize(34, 24)
                btn.setToolTip(f"${color_val:02X} ({color_val})  RGB({r}, {g}, {b})")
                btn.clicked.connect(lambda checked=False, c=color_val: self._select(c))
                self._buttons[color_val] = btn
                grid.addWidget(btn, hue, lum_step + 1)

        layout.addLayout(grid)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_styles()

    @property
    def selected_color(self) -> int:
        return self._selected_color

    def _select(self, color_val: int) -> None:
        self._selected_color = color_val
        self._refresh_styles()

    def _refresh_styles(self) -> None:
        r, g, b = self._pal_table.rgb(self._selected_color)
        self._info_label.setText(
            f"Selected: ${self._selected_color:02X} ({self._selected_color})  RGB({r}, {g}, {b})"
        )
        for c, btn in self._buttons.items():
            cr, cg, cb = self._pal_table.rgb(c)
            border = "3px solid #ffffff" if c == self._selected_color else "1px solid #333333"
            btn.setStyleSheet(
                f"background-color: rgb({cr}, {cg}, {cb}); border: {border};"
            )


class ColorSwatchButton(QPushButton):
    """Button displaying an Atari color byte and opening AtariColorPickerDialog."""

    color_changed = Signal(int)

    def __init__(
        self,
        pal_table: PalPaletteTable,
        color_value: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pal_table = pal_table
        self._color_value = int(color_value) & 0xFE
        self.setMinimumWidth(140)
        self.clicked.connect(self._open_picker)
        self._update_appearance()

    @property
    def color_value(self) -> int:
        return self._color_value

    def set_color_value(self, value: int) -> None:
        self._color_value = int(value) & 0xFF
        self._update_appearance()

    def _update_appearance(self) -> None:
        r, g, b = self._pal_table.rgb(self._color_value)
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        fg = "#000000" if luma > 130 else "#ffffff"
        self.setText(f"${self._color_value:02X} ({self._color_value})")
        self.setStyleSheet(
            f"background-color: rgb({r}, {g}, {b}); color: {fg}; "
            "border: 1px solid #555; padding: 4px 8px; font-weight: bold;"
        )

    def _open_picker(self) -> None:
        dlg = AtariColorPickerDialog(self._pal_table, self._color_value, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.set_color_value(dlg.selected_color)
            self.color_changed.emit(dlg.selected_color)


class PaletteEditorWidget(QWidget):
    """Editor for the 5 Atari ANTIC 4 palette registers (COLBK, COLPF0..COLPF3)."""

    palette_changed = Signal(Palette)

    _SLOTS = (
        ("colbk", "COLBK (00 - Background):"),
        ("colpf0", "COLPF0 (01):"),
        ("colpf1", "COLPF1 (10):"),
        ("colpf2", "COLPF2 (11, codes 0-127):"),
        ("colpf3", "COLPF3 (11, codes 128-255):"),
    )

    def __init__(self, pal_table: PalPaletteTable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pal_table = pal_table
        self._palette = Palette()
        self._buttons: dict[str, ColorSwatchButton] = {}

        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        for attr, label in self._SLOTS:
            btn = ColorSwatchButton(pal_table, getattr(self._palette, attr), self)
            btn.color_changed.connect(lambda val, a=attr: self._on_slot_changed(a, val))
            self._buttons[attr] = btn
            layout.addRow(label, btn)

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette.copy()
        for attr, btn in self._buttons.items():
            btn.set_color_value(getattr(self._palette, attr))

    def palette(self) -> Palette:
        return self._palette.copy()

    def _on_slot_changed(self, attr: str, value: int) -> None:
        setattr(self._palette, attr, value)
        self.palette_changed.emit(self._palette.copy())
