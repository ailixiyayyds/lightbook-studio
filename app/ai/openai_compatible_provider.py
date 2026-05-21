from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.metadata_schema import validate_ai_metadata
from app.ai.provider import BaseAiProvider
from app.ai.types import AiMetadataRequest, AiMetadataResponse
from app.core.models import LightBookError


logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_API_KEY_ENV = "LIGHTBOOK_AI_API_KEY"
SYSTEM_PROMPT = (
    "你是一个漫画与轻小说元数据整理助手。你的任务是根据用户提供的标题、文件名、作者、"
    "章节标题、正文样本、已有简介和搜索候选资料，整理出适合个人数字书库使用的元数据。"
    "你不是复读输入，而是要清洗噪声、规范标题、补全分类和标签，并生成自然的故事简介。"
    "\n\n"
    "严格规则：\n"
    "1. 只能输出 JSON，不要输出解释、Markdown、代码块或额外文字。\n"
    "2. 不确定的信息用空字符串、空数组或 unknown，不要编造。\n"
    "3. 去除标题中的下载站、发布组、汉化组、文件来源标记，例如 [Kome]、[Kmoe]、[汉化]、[自购]、[DL]。\n"
    "4. clean_title 必须是干净作品名，不包含卷号、页数、文件扩展名。\n"
    '5. book_title 应该是“第 01 卷”“第 02 卷”这种卷标题，不要包含发布组标记。\n'
    '6. summary 必须优先写故事简介。不要写“这是第 N 卷”“共 N 页”“漫画元数据建议”这类无意义文本。\n'
    "7. 如果没有足够剧情信息，可以写保守简介或留空，但不能编造具体剧情。\n"
    "8. genres 是大分类，数量 2 到 5 个。\n"
    "9. tags 是具体元素，数量 3 到 10 个。\n"
    "10. genres 和 tags 不要重复。\n"
    "11. language_iso 和 manga_direction 默认保留输入值。\n"
    "12. 不要把作者、语言、页数、卷号当成 tag。\n"
    "\n"
    "genres 可选范围（大分类）：漫画、轻小说、百合、恋爱、校园、日常、喜剧、奇幻、"
    "异世界、科幻、悬疑、推理、战斗、冒险、青春、治愈、历史、运动、音乐、偶像、职场、"
    "家庭、社会、恐怖\n"
    "\n"
    "tags 是具体元素（示例）：暗恋、同学、女校、社团、日常向、恋爱喜剧、青梅竹马、"
    "群像、成长、重生、转生、魔法学院、机战、吸血鬼、悬疑解谜、青春恋爱\n"
    "\n"
    'genres 和 tags 的区别：genres 回答“这是什么类型的作品”（大类），'
    'tags 回答“作品里有什么具体元素”（细粒度标签）。两者内容不应重复。'
)
TEST_SYSTEM_PROMPT = "你必须只输出 JSON，不要输出解释、Markdown、代码块或额外文本。"
TEST_USER_PROMPT = '请只输出这个 JSON：{"ok": true}'
AI_METADATA_SCHEMA_EXAMPLE: dict[str, Any] = {
    "clean_title": "",
    "original_title": "",
    "aliases": [],
    "book_title": "",
    "volume_number": None,
    "authors": [],
    "illustrators": [],
    "translators": [],
    "language_iso": "unknown",
    "summary": "",
    "genres": [],
    "tags": [],
    "content_warnings": [],
    "manga_direction": "unknown",
    "series_status": "unknown",
    "confidence": 0.0,
    "field_confidence": {},
    "notes": [],
}


class AiProviderConfigError(LightBookError):
    """Raised when an OpenAI-compatible provider is missing required config."""


class AiProviderRequestError(LightBookError):
    """Raised when an OpenAI-compatible provider returns an HTTP/API error."""


class AiProviderTimeoutError(AiProviderRequestError):
    """Raised when an OpenAI-compatible provider request times out."""


class AiProviderParseError(AiProviderRequestError):
    """Raised when an OpenAI-compatible provider response cannot be parsed."""


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    timeout_seconds: int = 60
    temperature: float = 0.2


class OpenAICompatibleProvider(BaseAiProvider):
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        timeout_seconds: int = 60,
        temperature: float = 0.2,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        timeout_seconds: int = 60,
        temperature: float = 0.2,
    ) -> OpenAICompatibleProvider:
        return cls(
            base_url=base_url,
            api_key=os.environ.get(api_key_env, ""),
            model=model,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
        )

    def suggest_metadata(self, request: AiMetadataRequest) -> AiMetadataResponse:
        self._ensure_configured()
        payload = self._build_payload(request)
        logger.info(
            "AI suggest_metadata start provider_type=%s provider_class=%s base_url=%s model=%s "
            "messages=%s text_sample_len=%s",
            self.name,
            self.__class__.__name__,
            self.base_url,
            self.model,
            len(payload["messages"]),
            len(request.text_sample[:5000]),
        )
        response_data = self._post_chat_completion(payload)
        choices = response_data.get("choices")
        logger.info(
            "AI response choices_present=%s choices_count=%s",
            isinstance(choices, list),
            len(choices) if isinstance(choices, list) else 0,
        )
        raw_text = _extract_message_content(response_data)
        logger.debug("AI message content preview=%s", raw_text[:1000])
        parsed = extract_json_from_ai_response(raw_text)
        logger.info("AI JSON parse succeeded keys=%s", sorted(parsed.keys()))
        try:
            validated = validate_ai_metadata(parsed)
        except Exception:
            logger.exception("AI schema validation failed")
            raise
        logger.info("AI schema validation succeeded confidence=%s", validated["confidence"])
        return AiMetadataResponse(
            raw_text=raw_text,
            parsed=validated,
            provider=self.name,
            confidence=float(validated["confidence"]),
        )

    def test_connection(self) -> bool:
        self._ensure_configured()
        response_data = self._post_chat_completion(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": TEST_SYSTEM_PROMPT},
                    {"role": "user", "content": TEST_USER_PROMPT},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "stream": False,
            }
        )
        raw_text = _extract_message_content(response_data)
        parsed = extract_json_from_ai_response(raw_text)
        if parsed.get("ok") is True:
            return True
        raise AiProviderParseError("AI provider test response did not contain ok=true.")

    def _post_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = _chat_completions_url(self.base_url)
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            logger.exception("AI provider request timed out base_url=%s model=%s", self.base_url, self.model)
            raise AiProviderTimeoutError("AI provider request timed out.") from exc
        except httpx.HTTPError as exc:
            logger.exception("AI provider request failed base_url=%s model=%s", self.base_url, self.model)
            raise AiProviderRequestError(f"AI provider request failed: {exc}") from exc

        logger.info(
            "AI provider HTTP response status_code=%s response_preview=%s",
            response.status_code,
            response.text[:1000],
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise AiProviderRequestError(f"AI provider HTTP {response.status_code}: {response.text[:500]}")

        return _response_json(response)

    def _ensure_configured(self) -> None:
        if not str(self.base_url or "").strip():
            raise AiProviderConfigError("AI provider base_url is not configured.")
        if not str(self.model or "").strip():
            raise AiProviderConfigError("AI provider model is not configured.")
        if not str(self.api_key or "").strip():
            raise AiProviderConfigError(
                f"AI API key is not configured. Set environment variable {DEFAULT_API_KEY_ENV}."
            )

    def _build_payload(self, request: AiMetadataRequest) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(_user_prompt_payload(request), ensure_ascii=False, sort_keys=True),
                },
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }


class OpenAiCompatibleProvider(OpenAICompatibleProvider):
    """Backward-compatible alias for the pre-v0.4.1 class name."""

    def __init__(
        self,
        config: OpenAICompatibleConfig | None = None,
        **kwargs: Any,
    ) -> None:
        if config is not None:
            super().__init__(
                base_url=config.base_url,
                api_key=config.api_key,
                model=config.model,
                timeout_seconds=config.timeout_seconds,
                temperature=config.temperature,
            )
        else:
            super().__init__(**kwargs)


OpenAiCompatibleConfig = OpenAICompatibleConfig
AiProviderConfigurationError = AiProviderConfigError


def _user_prompt_payload(request: AiMetadataRequest) -> dict[str, Any]:
    context = _request_context(request)
    current_metadata = request.current_metadata
    source_info = request.source_info
    return {
        "instruction": "请完成元数据清洗和整理任务，最终只返回一个符合 schema_example 的 JSON 对象。",
        "schema_example": AI_METADATA_SCHEMA_EXAMPLE,
        "genres_vs_tags": {
            'genres_definition': 'genres 是大分类，回答“这是什么类型的作品”，数量 2~5 个。',
            'tags_definition': 'tags 是具体元素，回答“作品里有什么”，数量 3~10 个。',
            "no_overlap": "genres 和 tags 的内容不应重复。",
            "not_tags": "不要把作者、语言、页数、卷号当成 tag。",
        },
        "summary_rule": {
            "priority": "必须优先写故事简介，描述作品讲的是什么故事。",
            'forbidden': '禁止输出“这是第 N 卷”“共 N 页”“漫画元数据建议”等无意义文本。',
            'fallback': '如果正文样本不足以推断剧情，可写保守简介（如“《作品名》系列第 N 卷”）或留空。',
        },
        "rules": [
            "Do not invent unknown facts or plot details.",
            "Remove release group markers, website tags, file extensions, page counts, and volume suffixes from clean_title.",
            "Use local_clean_guess when it is consistent with the raw input.",
            "For comic items without text_sample, still clean titles and provide conservative genres/tags based on title and existing metadata.",
            "Preserve language_iso and manga_direction unless the input clearly indicates otherwise.",
            "Use empty strings, empty lists, null, or unknown for uncertain fields.",
            "manga_direction must be rtl, ltr, webtoon, or unknown.",
            "series_status must be ongoing, completed, hiatus, or unknown.",
            "confidence must be a number from 0 to 1.",
        ],
        "raw_input": {
            "raw_series_title": source_info.get("raw_series_title", current_metadata.get("series_title", "")),
            "raw_book_title": source_info.get("raw_book_title", current_metadata.get("book_title", "")),
            "source_filename": source_info.get("source_filename", source_info.get("original_filename", "")),
            "source_path_basename": source_info.get("original_filename", ""),
            "current_author": current_metadata.get("author", ""),
            "current_summary": current_metadata.get("summary", ""),
            "current_genres": current_metadata.get("genres", ""),
            "current_tags": current_metadata.get("tags", ""),
            "volume_number": current_metadata.get("volume_number"),
            "page_count": request.page_count,
            "language_iso": current_metadata.get("language_iso", ""),
            "manga_direction": current_metadata.get("manga_direction", ""),
            "media_type": request.media_type,
            "chapter_titles": request.chapter_titles[:80],
            "text_sample": request.text_sample[:5000],
            "local_clean_guess": source_info.get("local_clean_guess", {}),
            "search_candidates": source_info.get("search_candidates", []),
        },
        "context": context,
    }


def _request_context(request: AiMetadataRequest) -> dict[str, Any]:
    return {
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


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        logger.exception("AI response body JSON parse failed")
        raise AiProviderParseError("AI provider response body is not JSON.") from exc
    if not isinstance(data, dict):
        raise AiProviderParseError("AI provider response body must be a JSON object.")
    return data


def _extract_message_content(response_data: dict[str, Any]) -> str:
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AiProviderParseError("AI provider response is missing choices[0].message.content.") from exc
    if not isinstance(content, str):
        raise AiProviderParseError("AI provider message.content must be a string.")
    if not content.strip():
        raise AiProviderParseError("AI provider message.content is empty.")
    return content


_CODE_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json_from_ai_response(text: str) -> dict[str, Any]:
    raw_text = text.strip()
    if not raw_text:
        raise AiProviderParseError("AI provider message.content is empty.")

    candidates = [raw_text]
    match = _CODE_FENCE_RE.match(raw_text)
    if match:
        candidates.insert(0, match.group(1).strip())

    extracted = _extract_first_json_object(raw_text)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(data, dict):
            raise AiProviderParseError("AI provider metadata suggestion must be a JSON object.")
        return data

    raise AiProviderParseError("AI provider message.content is not valid JSON.") from last_error


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
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
                return text[start : index + 1]
    return None
