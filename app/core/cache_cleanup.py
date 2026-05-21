from __future__ import annotations

from pathlib import Path


def cleanup_unreferenced_cover_cache(
    covers_root: Path,
    referenced_paths: set[Path],
) -> int:
    """Delete files under covers_root that are not referenced by the library."""
    if not covers_root.exists():
        return 0

    normalized_refs = {
        path.resolve(strict=False)
        for path in referenced_paths
        if str(path).strip()
    }
    removed = 0
    for path in covers_root.rglob("*"):
        if not path.is_file():
            continue
        if path.resolve(strict=False) in normalized_refs:
            continue
        path.unlink()
        removed += 1
    return removed


def cleanup_old_log_files(log_dir: Path, current_log_file: Path) -> int:
    """Delete rotated lightbook.log.* files, keeping the active log file."""
    if not log_dir.exists():
        return 0

    current = current_log_file.resolve(strict=False)
    removed = 0
    for path in log_dir.glob("lightbook.log.*"):
        if not path.is_file():
            continue
        if path.resolve(strict=False) == current:
            continue
        path.unlink()
        removed += 1
    return removed
