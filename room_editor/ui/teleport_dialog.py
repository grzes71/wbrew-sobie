"""Dialogs for editing bidirectional teleports and hero start position."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.project import (
    ROOM_HEIGHT,
    ROOM_WIDTH,
    Room,
    StartPosition,
    Teleport,
    TeleportEndpoint,
)


class TeleportDialog(QDialog):
    """Create or edit a bidirectional teleport between two (room, x, y) endpoints."""

    def __init__(
        self,
        rooms: list[Room],
        teleport: Teleport | None = None,
        initial_room_a: int | None = None,
        initial_room_b: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Teleport Endpoints")
        self._rooms = sorted(rooms, key=lambda r: r.id)

        layout = QVBoxLayout(self)
        row = QHBoxLayout()

        self._a_room, self._a_x, self._a_y = self._build_endpoint_box("Endpoint A", row)
        self._b_room, self._b_x, self._b_y = self._build_endpoint_box("Endpoint B", row)
        layout.addLayout(row)

        if teleport is not None:
            self._set_combo_room(self._a_room, teleport.a.room_id)
            self._a_x.setValue(teleport.a.x)
            self._a_y.setValue(teleport.a.y)
            self._set_combo_room(self._b_room, teleport.b.room_id)
            self._b_x.setValue(teleport.b.x)
            self._b_y.setValue(teleport.b.y)
        else:
            if initial_room_a is not None:
                self._set_combo_room(self._a_room, initial_room_a)
            if initial_room_b is not None:
                self._set_combo_room(self._b_room, initial_room_b)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_endpoint_box(
        self,
        title: str,
        parent_layout: QHBoxLayout,
    ) -> tuple[QComboBox, QSpinBox, QSpinBox]:
        box = QGroupBox(title)
        form = QFormLayout(box)

        combo = QComboBox()
        for r in self._rooms:
            combo.addItem(f"{r.id}: {r.name}", r.id)

        sx = QSpinBox()
        sx.setRange(0, ROOM_WIDTH - 1)
        sx.setValue(5)

        sy = QSpinBox()
        sy.setRange(0, ROOM_HEIGHT - 1)
        sy.setValue(10)

        form.addRow("Room:", combo)
        form.addRow(f"X (0..{ROOM_WIDTH - 1}):", sx)
        form.addRow(f"Y (0..{ROOM_HEIGHT - 1}):", sy)
        parent_layout.addWidget(box)
        return combo, sx, sy

    @staticmethod
    def _set_combo_room(combo: QComboBox, room_id: int) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == room_id:
                combo.setCurrentIndex(i)
                return

    def build_teleport(self) -> Teleport:
        return Teleport(
            a=TeleportEndpoint(
                room_id=int(self._a_room.currentData()),
                x=self._a_x.value(),
                y=self._a_y.value(),
            ),
            b=TeleportEndpoint(
                room_id=int(self._b_room.currentData()),
                x=self._b_x.value(),
                y=self._b_y.value(),
            ),
        )


class StartPositionDialog(QDialog):
    """Choose the unique hero start room and (x, y) coordinates."""

    def __init__(
        self,
        rooms: list[Room],
        current: StartPosition | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hero Start Position")
        self._rooms = sorted(rooms, key=lambda r: r.id)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._room_combo = QComboBox()
        for r in self._rooms:
            self._room_combo.addItem(f"{r.id}: {r.name}", r.id)

        self._sx = QSpinBox()
        self._sx.setRange(0, ROOM_WIDTH - 1)
        self._sy = QSpinBox()
        self._sy.setRange(0, ROOM_HEIGHT - 1)

        if current is not None:
            TeleportDialog._set_combo_room(self._room_combo, current.room_id)
            self._sx.setValue(current.x)
            self._sy.setValue(current.y)
        else:
            self._sx.setValue(2)
            self._sy.setValue(17)

        form.addRow("Room:", self._room_combo)
        form.addRow(f"X (0..{ROOM_WIDTH - 1}):", self._sx)
        form.addRow(f"Y (0..{ROOM_HEIGHT - 1}):", self._sy)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_start_position(self) -> StartPosition:
        return StartPosition(
            room_id=int(self._room_combo.currentData()),
            x=self._sx.value(),
            y=self._sy.value(),
        )
