from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.core.logging_config import setup_logging
from app.gui.main_window import MainWindow
from app.storage.database import initialize_database


def main() -> int:
    setup_logging()
    initialize_database()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
