from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config.json")


@dataclass
class AppConfig:
    recent_input_dir: str = ""
    recent_output_dir: str = ""


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    if not config_path.exists():
        return AppConfig()

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load config from %s: %s", config_path, exc)
        return AppConfig()

    if not isinstance(raw, dict):
        return AppConfig()

    return AppConfig(
        recent_input_dir=str(raw.get("recent_input_dir", "") or ""),
        recent_output_dir=str(raw.get("recent_output_dir", "") or ""),
    )


def save_config(config: AppConfig, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    data: dict[str, Any] = asdict(config)
    try:
        config_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Failed to save config to %s: %s", config_path, exc)
