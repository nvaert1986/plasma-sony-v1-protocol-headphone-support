"""Application entry point."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

from .gui import MainWindow, app_icon


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("Plasma Sony Headphone Support")
    app.setApplicationDisplayName("Sony Headphone Support")
    app.setDesktopFileName("plasma-sony-v1-protocol-headphone-support")
    app.setWindowIcon(app_icon())
    # keep running in the tray when the window is closed
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
