from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

from app.ai.config import AiProviderConfig
from app.search.types import MetadataSearchQuery
from app.storage.repositories import create_ai_request_log

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是漫画和轻小说搜索词规划助手。你的任务是给出搜索关键词，帮助查找图书元数据、封面和资料页。"
    "你不能输出任何 URL、链接或文件路径。你只能输出搜索关键词。"
    "你必须只输出 JSON，不要输出解释、Markdown、代码块或额外文字。"
)


class AiQueryPlan:
    def __init__(
        self,
        normalized_titles: list[str] | None = None,
        possible_original_titles: list[str] | None = None,
        romanized_titles: list[str] | None = None,
        author_queries: list[str] | None = None,
        publisher_queries: list[str] | None = None,
        bookstore_queries: list[str] | None = None,
        official_queries: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> None:
        self.normalized_titles = normalized_titles or []
        self.possible_original_titles = possible_original_titles or []
        self.romanized_titles = romanized_titles or []
        self.author_queries = author_queries or []
        self.publisher_queries = publisher_queries or []
        self.bookstore_queries = bookstore_queries or []
        self.official_queries = official_queries or []
        self.notes = notes or []

    def all_queries(self) -> list[str]:
        return _dedupe(
            [
                *self.normalized_titles,
                *self.possible_original_titles,
                *self.romanized_titles,
                *self.author_queries,
                *self.publisher_queries,
                *self.bookstore_queries,
                *self.official_queries,
            ]
        )


def build_ai_query_plan(query: MetadataSearchQuery, ai_config: AiProviderConfig) -> AiQueryPlan:
    api_key = os.environ.get(ai_config.api_key_env, "")
    if not api_key:
        return AiQueryPlan(notes=["AI Query Planner 未启用：缺少 API Key"])

    user_msg = (
        "作品信息：\n"
        f"title: {query.title}\n"
        f"original_title: {query.original_title}\n"
        f"authors: {', '.join(query.authors)}\n"
        f"media_type: {query.media_type}\n"
        f"language: {query.language_iso}\n"
        f"raw_filename: {query.raw_filename}\n"
        f"local_clean_title: {query.local_clean_title}\n"
        f"volume_number: {query.volume_number or '?'}\n\n"
        "请输出 JSON：\n"
        "{\n"
        '  "normalized_titles": ["清理后的标题"],\n'
        '  "possible_original_titles": ["可能的原文标题"],\n'
        '  "romanized_titles": ["可能的罗马字标题"],\n'
        '  "author_queries": ["作者搜索词"],\n'
        '  "publisher_queries": ["出版社搜索词"],\n'
        '  "bookstore_queries": ["书城搜索词"],\n'
        '  "official_queries": ["官网搜索词"],\n'
        '  "notes": ["备注"]\n'
        "}\n"
        "每个字段最多 5 个搜索词。不确定时留空数组。"
    )
    request_json = {
        "title": query.title,
        "original_title": query.original_title,
        "authors": query.authors,
        "media_type": query.media_type,
        "language_iso": query.language_iso,
        "raw_filename": query.raw_filename,
        "local_clean_title": query.local_clean_title,
        "volume_number": query.volume_number,
        "user_message": user_msg,
    }
    base_url = ai_config.base_url.rstrip("/")
    url = f"{base_url}/chat/completions" if not base_url.endswith("/chat/completions") else base_url
    started = time.perf_counter()
    response_text = ""

    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": ai_config.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "stream": False,
            },
            timeout=ai_config.timeout_seconds,
        )
        if response.status_code < 200 or response.status_code >= 300:
            _write_request_log(query, ai_config, request_json, response.text[:20000], {}, "failed", f"HTTP {response.status_code}", started)
            return AiQueryPlan(notes=[f"AI Query Planner HTTP {response.status_code}"])

        body = response.json()
        response_text = str(body["choices"][0]["message"]["content"])
        parsed = _extract_json(response_text)
    except Exception as exc:
        logger.warning("AI Query Planner failed: %s", exc)
        _write_request_log(query, ai_config, request_json, response_text, {}, "failed", str(exc), started)
        return AiQueryPlan(notes=[f"AI Query Planner 错误：{exc}"])

    if not isinstance(parsed, dict):
        _write_request_log(query, ai_config, request_json, response_text, {}, "failed", "response is not JSON object", started)
        return AiQueryPlan(notes=["AI Query Planner 返回非 JSON 响应"])

    _write_request_log(query, ai_config, request_json, response_text, parsed, "completed", "", started)

    def _list(key: str) -> list[str]:
        value = parsed.get(key, [])
        return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []

    return AiQueryPlan(
        normalized_titles=_list("normalized_titles"),
        possible_original_titles=_list("possible_original_titles"),
        romanized_titles=_list("romanized_titles"),
        author_queries=_list("author_queries"),
        publisher_queries=_list("publisher_queries"),
        bookstore_queries=_list("bookstore_queries"),
        official_queries=_list("official_queries"),
        notes=_list("notes"),
    )


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


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(item.strip())
    return result


def _write_request_log(
    query: MetadataSearchQuery,
    ai_config: AiProviderConfig,
    request_json: dict[str, Any],
    response_text: str,
    parsed_json: dict[str, Any],
    status: str,
    error_message: str,
    started: float,
) -> None:
    try:
        create_ai_request_log(
            book_id=query.book_id,
            task_id=f"query_planner:{query.book_id or query.title}",
            request_type="query_planner",
            provider="openai_compatible",
            model=ai_config.model,
            request_json=request_json,
            response_text=response_text[:20000],
            parsed_json=parsed_json,
            status=status,
            error_message=error_message,
            duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
        )
    except Exception:
        logger.exception("Failed to write AI query planner request log")
