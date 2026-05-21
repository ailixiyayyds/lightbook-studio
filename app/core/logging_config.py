from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "lightbook.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 10

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_logging_initialized = False
_sensitive_values: list[tuple[str, str]] = []


def setup_logging() -> None:
    global _logging_initialized
    if _logging_initialized:
        return
    _logging_initialized = True

    _cache_sensitive_values()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        str(LOG_FILE),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    file_handler.addFilter(SecretMaskingFilter())
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    console_handler.addFilter(SecretMaskingFilter())
    root.addHandler(console_handler)

    logger = logging.getLogger(__name__)
    logger.info("LightBook Studio 启动，日志文件：%s", LOG_FILE.resolve())


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "***"
    return f"{value[:6]}***{value[-4:]}"


def _cache_sensitive_values() -> None:
    global _sensitive_values
    _sensitive_values.clear()
    for name, value in os.environ.items():
        if not value or len(value) < 10:
            continue
        upper = name.upper()
        if any(kw in upper for kw in ("API_KEY", "SECRET", "TOKEN", "KEY")):
            _sensitive_values.append((value, mask_secret(value)))


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._mask_text(record.msg)
        if record.args:
            record.args = tuple(
                self._mask_text(str(a)) if isinstance(a, str) else a
                for a in record.args
            )
        return True

    @staticmethod
    def _mask_text(text: str) -> str:
        for value, masked in _sensitive_values:
            if value in text:
                text = text.replace(value, masked)
        return text
