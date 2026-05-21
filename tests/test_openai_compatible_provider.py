from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from app.ai.openai_compatible_provider import (
    AiProviderConfigError,
    AiProviderParseError,
    AiProviderRequestError,
    AiProviderTimeoutError,
    OpenAICompatibleProvider,
    extract_json_from_ai_response,
)
from app.ai.types import AiMetadataRequest


def test_openai_compatible_provider_parses_normal_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_transport(monkeypatch, _json_response_handler())
    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com",
        api_key="test-key",
        model="deepseek-v4-flash",
    )

    response = provider.suggest_metadata(_request())

    assert response.provider == "openai_compatible"
    assert response.parsed["clean_title"] == "Clean Title"
    assert response.parsed["tags"] == ["local", "metadata"]
    assert response.confidence == pytest.approx(0.81)
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "deepseek-v4-flash"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["stream"] is False
    assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["messages"][0]["role"] == "system"
    user_payload = json.loads(captured["body"]["messages"][1]["content"])
    assert "schema_example" in user_payload
    assert "context" in user_payload


def test_openai_compatible_provider_handles_base_url_with_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_transport(monkeypatch, _json_response_handler())
    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com/",
        api_key="test-key",
        model="deepseek-v4-flash",
    )

    provider.suggest_metadata(_request())

    assert captured["url"] == "https://api.deepseek.com/chat/completions"


def test_openai_compatible_provider_rejects_empty_api_key() -> None:
    provider = OpenAICompatibleProvider(api_key="", model="deepseek-v4-flash")

    with pytest.raises(AiProviderConfigError, match="LIGHTBOOK_AI_API_KEY"):
        provider.suggest_metadata(_request())


def test_openai_compatible_provider_reads_api_key_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIGHTBOOK_AI_API_KEY", "env-secret")

    provider = OpenAICompatibleProvider.from_env()

    assert provider.api_key == "env-secret"
    assert provider.base_url == "https://api.deepseek.com"
    assert provider.model == "deepseek-v4-flash"


def test_openai_compatible_provider_raises_request_error_for_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(401, text="unauthorized"),
    )
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")

    with pytest.raises(AiProviderRequestError, match="HTTP 401.*unauthorized"):
        provider.suggest_metadata(_request())


def test_openai_compatible_provider_raises_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow", request=request)

    _install_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")

    with pytest.raises(AiProviderTimeoutError):
        provider.suggest_metadata(_request())


def test_openai_compatible_provider_rejects_non_json_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_transport(
        monkeypatch,
        lambda request: httpx.Response(200, text="not json"),
    )
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")

    with pytest.raises(AiProviderParseError, match="response body is not JSON"):
        provider.suggest_metadata(_request())


def test_openai_compatible_provider_strips_markdown_code_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fenced = (
        "```json\n"
        '{"clean_title":"Fenced Title","tags":"tag-a, tag-b","confidence":0.7}'
        "\n```"
    )
    _install_transport(monkeypatch, _json_response_handler(content=fenced))
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")

    response = provider.suggest_metadata(_request())

    assert response.parsed["clean_title"] == "Fenced Title"
    assert response.parsed["tags"] == ["tag-a", "tag-b"]
    assert response.confidence == pytest.approx(0.7)


def test_extract_json_from_ai_response_allows_surrounding_text() -> None:
    parsed = extract_json_from_ai_response('Here is JSON:\n{"clean_title":"A","tags":[]}\nThanks')

    assert parsed == {"clean_title": "A", "tags": []}


def test_openai_compatible_provider_limits_text_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_transport(monkeypatch, _json_response_handler())
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")

    provider.suggest_metadata(_request(text_sample="x" * 6000))

    user_content = captured["body"]["messages"][1]["content"]
    context = json.loads(user_content)
    assert len(context["context"]["text_sample"]) == 5000


def test_openai_compatible_provider_test_connection_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _install_transport(
        monkeypatch,
        _json_response_handler(content='{"ok": true}'),
    )
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")

    assert provider.test_connection() is True
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["temperature"] == 0.2
    assert captured["body"]["stream"] is False
    assert "只输出 JSON" in captured["body"]["messages"][0]["content"]
    assert captured["body"]["messages"][1]["content"] == '请只输出这个 JSON：{"ok": true}'


def test_openai_compatible_provider_test_connection_rejects_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_transport(
        monkeypatch,
        _json_response_handler(content='{"ok": false}'),
    )
    provider = OpenAICompatibleProvider(api_key="test-key", model="deepseek-v4-flash")

    with pytest.raises(AiProviderParseError, match="ok=true"):
        provider.test_connection()


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
) -> dict[str, object]:
    captured: dict[str, object] = {}
    real_client = httpx.Client

    def wrapped_handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return handler(request)

    def client_factory(**kwargs: object) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(wrapped_handler), **kwargs)

    monkeypatch.setattr("app.ai.openai_compatible_provider.httpx.Client", client_factory)
    return captured


def _json_response_handler(content: str | None = None) -> Callable[[httpx.Request], httpx.Response]:
    metadata = content or json.dumps(
        {
            "clean_title": "Clean Title",
            "tags": ["local", "metadata"],
            "confidence": 0.81,
            "manga_direction": "rtl",
            "series_status": "unknown",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": metadata,
                        }
                    }
                ]
            },
        )

    return handler


def _request(text_sample: str = "") -> AiMetadataRequest:
    return AiMetadataRequest(
        book_id=1,
        media_type="novel" if text_sample else "comic",
        current_metadata={"series_title": "Raw Title"},
        source_info={"source_type": "novel_txt" if text_sample else "cbz"},
        chapter_titles=["Chapter 1"],
        page_count=None if text_sample else 10,
        text_sample=text_sample,
        cover_path="C:/covers/cover.jpg",
    )
