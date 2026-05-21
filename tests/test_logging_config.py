from __future__ import annotations

import logging
import os
import shutil

import pytest

from app.core.logging_config import SecretMaskingFilter, mask_secret, setup_logging


def test_setup_logging_creates_log_file(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("app.core.logging_config.LOG_DIR", log_dir)
    monkeypatch.setattr("app.core.logging_config.LOG_FILE", log_dir / "lightbook.log")
    monkeypatch.setattr("app.core.logging_config._logging_initialized", False)
    monkeypatch.setattr("app.core.logging_config._sensitive_values", [])

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    setup_logging()

    assert (log_dir / "lightbook.log").exists()
    assert (log_dir / "lightbook.log").stat().st_size > 0


def test_setup_logging_does_not_add_duplicate_handlers(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    monkeypatch.setattr("app.core.logging_config.LOG_DIR", log_dir)
    monkeypatch.setattr("app.core.logging_config.LOG_FILE", log_dir / "lightbook.log")

    # Force re-init for test isolation
    monkeypatch.setattr("app.core.logging_config._logging_initialized", False)
    monkeypatch.setattr("app.core.logging_config._sensitive_values", [])

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    setup_logging()
    count_after_first = len(root.handlers)
    setup_logging()
    count_after_second = len(root.handlers)

    assert count_after_first == count_after_second
    assert count_after_first >= 2  # file + console


def test_mask_secret_hides_api_keys():
    assert mask_secret("") == ""
    assert mask_secret("short") == "***"
    assert mask_secret("1234567890") == "***"
    assert mask_secret("sk-abcdefghijklmnop") == "sk-abc***mnop"
    assert mask_secret("very-long-api-key-12345") == "very-l***2345"


def test_secret_masking_filter_masks_known_keys(monkeypatch):
    monkeypatch.setattr("app.core.logging_config._sensitive_values", [])
    monkeypatch.setenv("TEST_API_KEY", "sk-this-is-a-secret-key-for-testing")
    monkeypatch.setenv("OTHER_VAR", "not-sensitive")

    from app.core.logging_config import _cache_sensitive_values

    _cache_sensitive_values()
    filter_obj = SecretMaskingFilter()

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Using key sk-this-is-a-secret-key-for-testing for auth",
        args=(),
        exc_info=None,
    )
    result = filter_obj.filter(record)
    assert result is True
    assert "sk-this-is-a-secret-key-for-testing" not in record.msg
    assert "sk-thi***ting" in record.msg


def test_secret_masking_filter_handles_args(monkeypatch):
    monkeypatch.setattr("app.core.logging_config._sensitive_values", [])
    monkeypatch.setenv("MY_API_KEY", "abcdefghijklmnopqrstuv")

    from app.core.logging_config import _cache_sensitive_values

    _cache_sensitive_values()
    filter_obj = SecretMaskingFilter()

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="auth with %s",
        args=("abcdefghijklmnopqrstuv",),
        exc_info=None,
    )
    filter_obj.filter(record)
    assert "abcdefghijklmnopqrstuv" not in str(record.args)
    assert "abcdef***stuv" in str(record.args)
