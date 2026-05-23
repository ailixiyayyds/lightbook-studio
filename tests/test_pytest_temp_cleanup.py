from __future__ import annotations

from pathlib import Path


def test_gitignore_covers_pytest_and_test_temp_directories() -> None:
    text = Path(".gitignore").read_text(encoding="utf-8")

    assert ".pytest_*/" in text
    assert ".test_*/" in text
    assert ".tmp_tests/" in text
    assert ".pytest_cache/" in text
    assert "__pycache__/" in text
    assert "*.py[cod]" in text


def test_pytest_cache_dir_is_configured() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'cache_dir = ".pytest_cache"' in text


def test_root_has_no_fixed_pytest_or_test_temp_directories() -> None:
    root = Path(".")
    offenders = [
        path.name
        for path in root.iterdir()
        if path.is_dir()
        and (path.name.startswith(".pytest_") or path.name.startswith(".test_"))
        and path.name not in {".pytest_cache", ".tmp_tests"}
    ]

    assert offenders == []
