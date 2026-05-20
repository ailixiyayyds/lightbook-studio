from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

_NUMBER_RE = re.compile(r"(\d+)")


def natural_key(value: str | Path) -> list[int | str]:
    text = str(value)
    parts = _NUMBER_RE.split(text)
    key: list[int | str] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part.casefold())
    return key


def natural_sorted(
    items: Iterable[T],
    key: Callable[[T], str | Path] | None = None,
) -> list[T]:
    if key is None:
        return sorted(items, key=lambda item: natural_key(str(item)))
    return sorted(items, key=lambda item: natural_key(key(item)))
