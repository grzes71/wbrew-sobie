"""Validation problem list dialog allowing click-to-jump navigation."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from room_editor.model.validation import ValidationIssue


class ValidationDialog(QDialog):
    """Displays validation errors and warnings; clicking a row navigates to the issue."""

    issue_activated = Signal(object)  # ValidationIssue

    def __init__(
        self,
        issues: list[ValidationIssue],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project Validation")
        self.resize(760, 420)
        self._issues = list(issues)

        layout = QVBoxLayout(self)

        err_count = sum(1 for i in issues if i.severity == "error")
        warn_count = sum(1 for i in issues if i.severity == "warning")
        summary = QLabel(
            f"Validation results: {err_count} error(s), {warn_count} warning(s). "
            "Click an item to jump to its location."
        )
        layout.addWidget(summary)

        self._table = QTableWidget(len(issues), 3)
        self._table.setHorizontalHeaderLabels(["Level", "Code", "Message"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        for row, issue in enumerate(issues):
            lvl_item = QTableWidgetItem(issue.severity.upper())
            if issue.severity == "error":
                lvl_item.setForeground(QColor(220, 60, 60))
            else:
                lvl_item.setForeground(QColor(210, 155, 30))
            code_item = QTableWidgetItem(issue.code)
            msg_item = QTableWidgetItem(issue.message)
            self._table.setItem(row, 0, lvl_item)
            self._table.setItem(row, 1, code_item)
            self._table.setItem(row, 2, msg_item)

        self._table.cellClicked.connect(self._on_row_clicked)
        self._table.cellDoubleClicked.connect(self._on_row_clicked)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

    def _on_row_clicked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._issues):
            self.issue_activated.emit(self._issues[row])
