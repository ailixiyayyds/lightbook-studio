from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import httpx

from app.ai.config import AiProviderConfig
from app.core.models import LightBookError
from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery
from app.storage.repositories import create_ai_request_log

logger = logging.getLogger(__name__)

_AI_SEARCH_SYSTEM_PROMPT = (
    "你是漫画和轻小说资料检索助手。请根据作品名、作者、类型，给出可能可靠的资料候选。"
    "你不能编造不存在的具体链接。如果无法确定链接，请留空。"
    "优先给出官方出版社、书城、Bangumi、豆瓣读书、AniList、MyAnimeList、"
    "MangaUpdates、MangaDex、Wikipedia、Fandom 等来源。"
    "你必须只输出 JSON，不要输出解释、Markdown、代码块或额外文字。"
)

_MAX_CANDIDATES = 6

_BOILERPLATE_PATTERNS = [
    re.compile(p)
    for p in [
        r"这是第\s*\d+\s*卷",
        r"共\s*\d+\s*页",
        r"漫画元数据",
        r"metadata\s+suggestion",
        r"the\s+volume\s+\d+",
        r"a\s+total\s+of\s+\d+\s+pages",
    ]
]


class AiSearchProviderError(LightBookError):
    """Raised when the AI search provider fails."""


class AiMetadataSearchProvider(BaseMetadataSearchProvider):
    name = "ai"

    def __init__(self, ai_config: AiProviderConfig) -> None:
        self._base_url = ai_config.base_url.rstrip("/")
        self._model = ai_config.model
        self._api_key = os.environ.get(ai_config.api_key_env, "")
        self._timeout = ai_config.timeout_seconds
        self._temperature = ai_config.temperature

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        if not query.title.strip():
            return []

        if not self._api_key:
            raise AiSearchProviderError(
                "AI 搜索需要 API Key。请设置环境变量或在设置中配置。"
            )

        user_message = _build_user_message(query)
        url = f"{self._base_url}/chat/completions"
        if not self._base_url.endswith("/chat/completions"):
            url = f"{self._base_url}/chat/completions"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _AI_SEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": self._temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }

        logger.info(
            "AI search start model=%s base_url=%s title=%s",
            self._model,
            self._base_url,
            query.title,
        )

        started = time.perf_counter()
        raw_text = ""
        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            _log_ai_search_request(query, self, user_message, "", {}, "failed", "timeout", started)
            raise AiSearchProviderError("AI 搜索超时，请检查网络或增加超时设置。")
        except httpx.HTTPError as exc:
            _log_ai_search_request(query, self, user_message, "", {}, "failed", str(exc), started)
            raise AiSearchProviderError(f"AI 搜索网络错误：{exc}")

        if response.status_code < 200 or response.status_code >= 300:
            logger.warning("AI search HTTP error status=%s", response.status_code)
            _log_ai_search_request(
                query,
                self,
                user_message,
                response.text[:20000],
                {},
                "failed",
                f"HTTP {response.status_code}: {response.text[:500]}",
                started,
            )
            raise AiSearchProviderError(
                f"AI 搜索 HTTP {response.status_code}：{response.text[:200]}"
            )

        try:
            body = response.json()
        except json.JSONDecodeError:
            _log_ai_search_request(query, self, user_message, response.text[:20000], {}, "failed", "response is not JSON", started)
            raise AiSearchProviderError("AI 搜索返回不是 JSON。")

        raw_text = _extract_content(body)
        logger.info("AI search response received len=%s", len(raw_text))
        candidates = _parse_candidates(raw_text)
        _log_ai_search_request(
            query,
            self,
            user_message,
            raw_text,
            {"candidate_count": len(candidates)},
            "completed",
            "",
            started,
        )
        return candidates


def _extract_content(body: dict[str, Any]) -> str:
    try:
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        raise AiSearchProviderError("AI 搜索结果格式异常，缺少 choices[0].message.content。")


def _build_user_message(query: MetadataSearchQuery) -> str:
    parts = [f"作品名：{query.title}"]
    if query.original_title:
        parts.append(f"原名：{query.original_title}")
    if query.authors:
        parts.append(f"作者：{', '.join(query.authors)}")
    parts.append(f"类型：{query.media_type or '未知'}")
    parts.append(f"语言：{query.language_iso or 'unknown'}")

    parts.append(
        "请根据以上信息给出最多 6 个候选资料链接。"
        "返回 JSON 格式：{\"candidates\": [{...}, ...]}。"
        "每个候选包含：title, original_title, authors, summary, cover_url, source_name, source_url, tags, genres。"
        "cover_url 如果无法确定就留空。"
        "summary 必须是故事简介，不要写\"这是第 N 卷\"或\"共 N 页\"。"
        "如果信息不足，返回 {\"candidates\": []}。"
    )
    return "\n".join(parts)


def _parse_candidates(raw_text: str) -> list[MetadataSearchCandidate]:
    parsed = _extract_json(raw_text)
    if not isinstance(parsed, dict):
        return []

    raw_candidates = parsed.get("candidates")
    if not isinstance(raw_candidates, list):
        return []

    result: list[MetadataSearchCandidate] = []
    for item in raw_candidates[: _MAX_CANDIDATES]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue

        summary = str(item.get("summary", "")).strip()
        if _is_boilerplate(summary):
            summary = ""

        cover_url = str(item.get("cover_url", "")).strip()
        if cover_url and not (cover_url.startswith("http://") or cover_url.startswith("https://")):
            cover_url = ""

        result.append(MetadataSearchCandidate(
            title=title,
            original_title=str(item.get("original_title", "")).strip(),
            authors=_string_list(item.get("authors")),
            summary=summary,
            cover_url=cover_url,
            source_name=str(item.get("source_name", "")).strip() or "AI 搜索",
            source_url=str(item.get("source_url", "")).strip(),
            tags=_string_list(item.get("tags")),
            genres=_string_list(item.get("genres")),
        ))

    return result


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _is_boilerplate(summary: str) -> bool:
    for pattern in _BOILERPLATE_PATTERNS:
        if pattern.search(summary):
            return True
    return False


def _extract_json(text: str) -> object:
    raw = text.strip()
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _log_ai_search_request(
    query: MetadataSearchQuery,
    provider: AiMetadataSearchProvider,
    user_message: str,
    response_text: str,
    parsed_json: dict[str, Any],
    status: str,
    error_message: str,
    started: float,
) -> None:
    try:
        create_ai_request_log(
            book_id=query.book_id,
            task_id=f"search_ai:{query.title}",
            request_type="search_ai",
            provider=provider.name,
            model=provider._model,
            request_json={
                "title": query.title,
                "original_title": query.original_title,
                "authors": query.authors,
                "media_type": query.media_type,
                "language_iso": query.language_iso,
                "user_message": user_message,
            },
            response_text=response_text[:20000],
            parsed_json=parsed_json,
            status=status,
            error_message=error_message,
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        )
    except Exception:
        logger.exception("Failed to write AI search request log")
