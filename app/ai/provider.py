from __future__ import annotations

from abc import ABC, abstractmethod

from app.ai.types import AiMetadataRequest, AiMetadataResponse


class BaseAiProvider(ABC):
    name: str

    @abstractmethod
    def suggest_metadata(self, request: AiMetadataRequest) -> AiMetadataResponse:
        """Return metadata suggestions without mutating project data."""
