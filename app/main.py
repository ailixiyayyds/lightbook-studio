from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.storage.database import initialize_database


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    initialize_database()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
