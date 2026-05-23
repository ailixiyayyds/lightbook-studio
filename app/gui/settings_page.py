from __future__ import annotations

"""Settings page helpers for AI, search, cache, and log configuration."""

from app.core.local_secrets import get_secret, has_secret, set_secret

__all__ = ["get_secret", "has_secret", "set_secret"]
