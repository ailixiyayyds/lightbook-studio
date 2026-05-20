from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ai.provider import BaseAiProvider
from app.ai.types import AiMetadataRequest, AiMetadataResponse
from app.core.models import LightBookError


class AiProviderConfigurationError(LightBookError):
    """Raised when a real AI provider is selected without required settings."""


class AiProviderRequestError(LightBookError):
    """Raised when an OpenAI-compatible provider request fails."""


@dataclass(frozen=True)
class OpenAiCompatibleConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: float = 60.0


class OpenAiCompatibleProvider(BaseAiProvider):
    name = "openai_compatible"

    def __init__(self, config: OpenAiCompatibleConfig) -> None:
        self.config = config

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str = "https://api.openai.com/v1",
        model: str = "",
    ) -> OpenAiCompatibleProvider:
        return cls(
            OpenAiCompatibleConfig(
                base_url=base_url,
                model=model,
                api_key=os.environ.get("LIGHTBOOK_AI_API_KEY"),
            )
        )

    def suggest_metadata(self, request: AiMetadataRequest) -> AiMetadataResponse:
        self._ensure_configured()
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a metadata assistant for local comics and light novels. "
                        "Return strict JSON only. Do not include Markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(_request_payload(request), ensure_ascii=False, sort_keys=True),
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        response_data = self._post_json(_chat_completions_url(self.config.base_url), payload)
        raw_text = _extract_message_content(response_data)
        parsed = _parse_json_object(raw_text)
        return AiMetadataResponse(
            raw_text=raw_text,
            parsed=parsed,
            provider=self.name,
            confidence=_confidence(parsed),
        )

    def _ensure_configured(self) -> None:
        if not str(self.config.base_url or "").strip():
            raise AiProviderConfigurationError("AI provider base_url 未配置。")
        if not str(self.config.model or "").strip():
            raise AiProviderConfigurationError("AI provider model 未配置。")
        if not str(self.config.api_key or "").strip():
            raise AiProviderConfigurationError(
                "AI API key 未配置。请设置环境变量 LIGHTBOOK_AI_API_KEY。"
            )

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:  # noqa: S310
                response_body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise AiProviderRequestError(f"AI provider HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise AiProviderRequestError(f"AI provider 请求失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise AiProviderRequestError("AI provider 请求超时。") from exc

        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise AiProviderRequestError("AI provider 返回的不是合法 JSON。") from exc
        if not isinstance(parsed, dict):
            raise AiProviderRequestError("AI provider 返回必须是 JSON object。")
        return parsed


def _request_payload(request: AiMetadataRequest) -> dict[str, Any]:
    return {
        "task": "suggest_lightbook_metadata",
        "required_fields": [
            "clean_title",
            "original_title",
            "aliases",
            "book_title",
            "volume_number",
            "authors",
            "illustrators",
            "translators",
            "language_iso",
            "summary",
            "genres",
            "tags",
            "content_warnings",
            "manga_direction",
            "series_status",
            "confidence",
            "field_confidence",
            "notes",
        ],
        "book_id": request.book_id,
        "media_type": request.media_type,
        "current_metadata": request.current_metadata,
        "source_info": request.source_info,
        "chapter_titles": request.chapter_titles[:80],
        "page_count": request.page_count,
        "text_sample": request.text_sample[:5000],
        "cover_path": request.cover_path,
    }


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _extract_message_content(response_data: dict[str, Any]) -> str:
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiProviderRequestError("AI provider 响应缺少 choices[0].message.content。") from exc
    if not isinstance(content, str):
        raise AiProviderRequestError("AI provider message.content 必须是字符串。")
    return content


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AiProviderRequestError("AI provider message.content 必须是严格 JSON。") from exc
    if not isinstance(parsed, dict):
        raise AiProviderRequestError("AI provider metadata 建议必须是 JSON object。")
    return parsed


def _confidence(parsed: dict[str, Any]) -> float:
    try:
        value = float(parsed.get("confidence", 0))
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, value))
