"""Application entry point for V's Qt desktop interface."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from v import __version__
from v.desktop.window import DesktopWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("V")
    app.setApplicationDisplayName("V — Local AI Companion")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")

    window = DesktopWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
