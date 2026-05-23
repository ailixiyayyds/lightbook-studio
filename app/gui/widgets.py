from __future__ import annotations

from PySide6.QtWidgets import QPushButton


def set_comfortable_button_size(button: QPushButton, *, min_width: int = 88) -> None:
    button.setMinimumHeight(34)
    button.setMinimumWidth(max(min_width, min(180, len(button.text()) * 14)))
