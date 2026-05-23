"""AI-powered metadata content extractor.

This module provides functionality to extract structured metadata from
raw page content using AI. The AI only extracts information from real
API responses - it never invents source_url or cover_url.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.search.mediawiki_utils import clean_mediawiki_categories, filter_useful_categories
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery

logger = logging.getLogger(__name__)

# Maximum content length to send to AI (to avoid token limits)
_MAX_CONTENT_LENGTH = 15000

# Schema for AI extraction output
_EXTRACTION_SCHEMA: dict[str, Any] = {
    "title": "",
    "original_title": "",
    "authors": [],
    "publisher": "",
    "publication_date": "",
    "summary_zh": "",
    "cover_url_candidates": [],
    "genres": [],
    "tags": [],
    "content_warnings": [],
    "match_assessment": {
        "is_likely_same_work": True,
        "reason": "",
        "matched_titles": [],
        "matched_authors": [],
    },
    "translation_notes": [],
    "notes": [],
}

_SYSTEM_PROMPT = """你是一个漫画与轻小说元数据抽取助手。你的任务是从真实 API 页面内容中抽取结构化元数据，并把可展示给中文书库用户的内容整理成中文。

严格规则：
1. 只能输出 JSON，不要输出解释、Markdown、代码块或额外文字。
2. 你只能从提供的内容中抽取信息，不能编造任何内容。
3. source_url 和 cover_url 绝对不允许由你生成——它们必须来自真实 API 或用户输入。
4. cover_url_candidates 只能从提供的 images 列表中选择，不能编造 URL。
5. 如果页面内容不足，字段留空或使用空数组。
6. summary_zh 必须是自然中文故事简介；如果原始资料是日文，请翻译成中文，不要直接照搬日文。
7. summary_zh 不要写“这是第 N 卷”“共 N 页”“元数据建议”这类无意义文本。
8. 作者名如果 API 内容中出现，必须提取；出版社、发售日同理。
9. genres 是大分类（如：漫画、轻小说、百合、恋爱、校园、日常、喜剧、奇幻、悬疑、战斗、青春等），数量 2-5 个。
10. tags 是具体元素（如：师生、女高中生、人外、校园、恋爱、日常、青梅竹马、转生、魔法学院等），数量 3-10 个。
9. genres 和 tags 不要重复。
10. 不要把维护分类、页面分类、模板分类塞进 tags。
11. 如果页面明显不是同一作品（例如是同名不同作品、消歧义页、或者完全不相关），将 is_likely_same_work 设为 false。
12. 匹配原因要简洁说明为什么判定为同一作品或不同作品。

genres 可选范围（大分类）：漫画、轻小说、百合、恋爱、校园、日常、喜剧、奇幻、异世界、科幻、悬疑、推理、战斗、冒险、青春、治愈、历史、运动、音乐、偶像、职场、家庭、社会、恐怖

tags 是具体元素（示例）：暗恋、同学、女校、社团、日常向、恋爱喜剧、青梅竹马、群像、成长、重生、转生、魔法学院、机战、吸血鬼、悬疑解谜、青春恋爱
"""


class ContentExtractorRepository(Protocol):
    """Protocol for repository that can log AI requests."""

    def create_ai_request_log(
        self,
        *,
        book_id: int | None,
        task_id: str,
        request_type: str,
        provider: str,
        model: str = "",
        request_json: Any = "{}",
        response_text: str = "",
        parsed_json: Any = "{}",
        status: str = "",
        error_message: str = "",
        duration_ms: int = 0,
    ) -> dict[str, Any]: ...


class ContentExtractorAiProvider(Protocol):
    """Protocol for AI provider that can extract metadata from content."""

    def extract_from_content(
        self,
        system_prompt: str,
        user_content: str,
    ) -> str:
        """Send request to AI and return raw text response."""
        ...


@dataclass
class ExtractionResult:
    """Result of content extraction."""

    candidate: MetadataSearchCandidate
    success: bool
    error: str = ""


class MetadataContentExtractor:
    """Extract structured metadata from raw page content using AI."""

    def __init__(
        self,
        ai_provider: ContentExtractorAiProvider,
        repository: ContentExtractorRepository | None = None,
        max_content_length: int = _MAX_CONTENT_LENGTH,
    ) -> None:
        self._ai_provider = ai_provider
        self._repository = repository
        self._max_content_length = max(1000, min(max_content_length, 40000))

    def extract_from_candidate(
        self,
        query: MetadataSearchQuery,
        candidate: MetadataSearchCandidate,
        *,
        book_id: int | None = None,
    ) -> MetadataSearchCandidate:
        """Extract metadata from a candidate's raw_content.

        Args:
            query: The original search query.
            candidate: The candidate with raw_content to extract from.
            book_id: Optional book ID for logging.

        Returns:
            Updated candidate with extraction results filled in.
        """
        # Skip if no raw content
        if not candidate.raw_content:
            logger.debug(
                "Skipping extraction for candidate title=%s: no raw_content",
                candidate.title,
            )
            return candidate

        # Skip if already extracted
        if candidate.extraction_status == "extracted":
            logger.debug(
                "Skipping extraction for candidate title=%s: already extracted",
                candidate.title,
            )
            return candidate

        started = time.perf_counter()
        provider_name = getattr(self._ai_provider, "name", "unknown")

        try:
            user_prompt = self._build_user_prompt(query, candidate)
            request_json = {
                "system_prompt": _SYSTEM_PROMPT[:500],
                "user_prompt": user_prompt,
            }

            raw_response = self._ai_provider.extract_from_content(
                _SYSTEM_PROMPT,
                user_prompt,
            )

            parsed = self._parse_ai_response(raw_response)
            validated = self._validate_extraction(parsed)

            duration_ms = int((time.perf_counter() - started) * 1000)

            # Log successful extraction
            self._log_request(
                book_id=book_id,
                task_id=f"content_extraction:{candidate.source_name}:{candidate.title}",
                provider=provider_name,
                request_json=request_json,
                response_text=raw_response[:20000],
                parsed_json=validated,
                status="completed",
                duration_ms=duration_ms,
            )

            # Build updated candidate
            return self._apply_extraction(candidate, validated)

        except Exception as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            error_msg = str(exc)
            logger.warning(
                "Content extraction failed for candidate title=%s: %s",
                candidate.title,
                error_msg,
            )

            self._log_request(
                book_id=book_id,
                task_id=f"content_extraction:{candidate.source_name}:{candidate.title}",
                provider=provider_name,
                request_json={},
                response_text="",
                parsed_json={},
                status="failed",
                error_message=error_msg,
                duration_ms=duration_ms,
            )

            # Return candidate with failed status
            return MetadataSearchCandidate(
                title=candidate.title,
                original_title=candidate.original_title,
                authors=candidate.authors,
                publisher=candidate.publisher,
                publication_date=candidate.publication_date,
                isbn=candidate.isbn,
                summary=candidate.summary,
                cover_url=candidate.cover_url,
                source_name=candidate.source_name,
                source_url=candidate.source_url,
                source_type=candidate.source_type,
                genres=candidate.genres,
                tags=candidate.tags,
                confidence=candidate.confidence,
                verified=candidate.verified,
                notes=candidate.notes,
                raw_content=candidate.raw_content,
                raw_content_type=candidate.raw_content_type,
                categories=candidate.categories,
                images=candidate.images,
                extraction_json={},
                extraction_status="failed",
                extraction_error=error_msg,
            )

    def _build_user_prompt(
        self,
        query: MetadataSearchQuery,
        candidate: MetadataSearchCandidate,
    ) -> str:
        """Build the user prompt for AI extraction."""
        # Truncate raw content if too long
        raw_content = candidate.raw_content[: self._max_content_length]
        if len(candidate.raw_content) > self._max_content_length:
            raw_content += "\n...[内容已截断]"

        # Filter categories to only useful ones
        useful_categories = filter_useful_categories(
            clean_mediawiki_categories(candidate.categories)
        )

        prompt_data = {
            "query": {
                "title": query.title,
                "original_title": query.original_title,
            "authors": query.authors,
            "media_type": query.media_type,
            "language_iso": query.language_iso,
            },
            "candidate": {
                "title": candidate.title,
                "source_name": candidate.source_name,
                "source_url": candidate.source_url,
                "raw_content_type": candidate.raw_content_type,
            },
            "raw_content": raw_content,
            "categories": useful_categories,
            "images": candidate.images[:10],  # Limit images for prompt
            "existing_candidate_fields": {
                "authors": candidate.authors,
                "publisher": candidate.publisher,
                "publication_date": candidate.publication_date,
                "summary": candidate.summary,
                "genres": candidate.genres,
                "tags": candidate.tags,
            },
            "schema_example": _EXTRACTION_SCHEMA,
        }

        return json.dumps(prompt_data, ensure_ascii=False, indent=2)

    def _parse_ai_response(self, raw_response: str) -> dict[str, Any]:
        """Parse AI response to JSON."""
        text = raw_response.strip()
        if not text:
            raise ContentExtractionError("AI response is empty")

        # Try to extract JSON from code fence
        code_fence_match = re.match(r"^\s*```(?:json|JSON)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
        if code_fence_match:
            text = code_fence_match.group(1).strip()

        # Try to extract first JSON object
        start = text.find("{")
        if start >= 0:
            depth = 0
            in_string = False
            escape = False
            for i in range(start, len(text)):
                char = text[i]
                if in_string:
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        text = text[start : i + 1]
                        break

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ContentExtractionError(f"AI response is not valid JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ContentExtractionError("AI response must be a JSON object")

        return parsed

    def _validate_extraction(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate and normalize extraction result."""
        validated: dict[str, Any] = {
            "title": str(data.get("title", "")).strip(),
            "original_title": str(data.get("original_title", "")).strip(),
            "authors": _to_string_list(data.get("authors", [])),
            "publisher": str(data.get("publisher", "")).strip(),
            "publication_date": str(data.get("publication_date", "")).strip(),
            "summary_zh": str(data.get("summary_zh", data.get("summary", ""))).strip(),
            "cover_url_candidates": _to_string_list(data.get("cover_url_candidates", [])),
            "genres": _to_string_list(data.get("genres", []))[:5],
            "tags": _to_string_list(data.get("tags", []))[:10],
            "content_warnings": _to_string_list(data.get("content_warnings", [])),
            "translation_notes": _to_string_list(data.get("translation_notes", [])),
            "notes": _to_string_list(data.get("notes", [])),
        }

        # Validate match_assessment
        match_assessment = data.get("match_assessment", {})
        if isinstance(match_assessment, dict):
            validated["match_assessment"] = {
                "is_likely_same_work": bool(match_assessment.get("is_likely_same_work", True)),
                "reason": str(match_assessment.get("reason", "")).strip(),
                "matched_titles": _to_string_list(match_assessment.get("matched_titles", [])),
                "matched_authors": _to_string_list(match_assessment.get("matched_authors", [])),
            }
        else:
            validated["match_assessment"] = {
                "is_likely_same_work": True,
                "reason": "",
                "matched_titles": [],
                "matched_authors": [],
            }

        return validated

    def _apply_extraction(
        self,
        candidate: MetadataSearchCandidate,
        extraction: dict[str, Any],
    ) -> MetadataSearchCandidate:
        """Apply extraction results to candidate."""
        # Extract fields from AI result
        summary = extraction.get("summary_zh") or extraction.get("summary", "")
        if not summary:
            summary = candidate.summary

        genres = extraction.get("genres", []) or candidate.genres
        tags = extraction.get("tags", []) or candidate.tags

        # Handle cover_url_candidates - only use if from images list
        cover_url = candidate.cover_url
        cover_candidates = extraction.get("cover_url_candidates", [])
        if not cover_url and cover_candidates:
            for url in cover_candidates:
                if url in candidate.images:
                    cover_url = url
                    break

        # Build notes with match assessment
        notes = list(candidate.notes)
        match_assessment = extraction.get("match_assessment", {})
        if match_assessment.get("reason"):
            notes.append(f"匹配判定: {match_assessment['reason']}")

        return MetadataSearchCandidate(
            title=extraction.get("title") or candidate.title,
            original_title=extraction.get("original_title") or candidate.original_title,
            authors=extraction.get("authors") or candidate.authors,
            publisher=extraction.get("publisher") or candidate.publisher,
            publication_date=extraction.get("publication_date") or candidate.publication_date,
            isbn=candidate.isbn,
            summary=summary,
            cover_url=cover_url,
            source_name=candidate.source_name,
            source_url=candidate.source_url,
            source_type=candidate.source_type,
            genres=genres,
            tags=tags,
            confidence=candidate.confidence,
            verified=candidate.verified,
            notes=notes,
            raw_content=candidate.raw_content,
            raw_content_type=candidate.raw_content_type,
            categories=candidate.categories,
            images=candidate.images,
            extraction_json=extraction,
            extraction_status="extracted",
            extraction_error="",
        )

    def _log_request(
        self,
        *,
        book_id: int | None,
        task_id: str,
        provider: str,
        request_json: Any,
        response_text: str,
        parsed_json: Any,
        status: str,
        error_message: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Log AI request to repository if available."""
        if self._repository is None:
            return
        try:
            self._repository.create_ai_request_log(
                book_id=book_id,
                task_id=task_id,
                request_type="metadata_content_extraction",
                provider=provider,
                model=getattr(self._ai_provider, "model", ""),
                request_json=request_json,
                response_text=response_text[:20000],
                parsed_json=parsed_json,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.exception("Failed to log content extraction request")


def _to_string_list(value: Any) -> list[str]:
    """Convert value to list of strings."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


class ContentExtractionError(Exception):
    """Raised when content extraction fails."""
    pass
