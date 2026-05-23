from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SECRETS_PATH = Path("data") / "local_secrets.json"


def get_secret(key: str, *, secrets_path: Path = SECRETS_PATH) -> str:
    data = _load(secrets_path)
    value = data.get(key, "")
    return str(value) if value else ""


def set_secret(key: str, value: str, *, secrets_path: Path = SECRETS_PATH) -> None:
    data = _load(secrets_path)
    if value:
        data[key] = value
    else:
        data.pop(key, None)
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def has_secret(key: str, *, secrets_path: Path = SECRETS_PATH) -> bool:
    return bool(get_secret(key, secrets_path=secrets_path))


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
