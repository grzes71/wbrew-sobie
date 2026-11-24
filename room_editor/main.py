"""Entry point for launching the Atari 8-bit Room Editor GUI."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from room_editor.ui.main_window import MainWindow


def main() -> int:
    """Launch the Room Editor desktop application."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
