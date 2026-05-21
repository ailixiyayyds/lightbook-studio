from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.core.models import LightBookError
from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery

logger = logging.getLogger(__name__)

_COVER_DOWNLOAD_TIMEOUT = 30


class SearchRepository(Protocol):
    def get_book(self, book_id: int) -> dict[str, Any] | None: ...

    def get_work(self, work_id: int) -> dict[str, Any] | None: ...

    def update_work(
        self,
        work_id: int,
        *,
        title: str | None = None,
        original_title: str | None = None,
        author: str | None = None,
        summary: str | None = None,
        genres: str | None = None,
        tags: str | None = None,
        language_iso: str | None = None,
    ) -> dict[str, Any] | None: ...

    def update_book(
        self,
        book_id: int,
        *,
        title: str | None = None,
        volume_number: int | None = None,
        manga_direction: str | None = None,
        cover_override_path: str | None = None,
    ) -> dict[str, Any] | None: ...


class MetadataSearchServiceError(LightBookError):
    """Raised when metadata search or candidate application fails."""


class MetadataSearchService:
    def __init__(
        self,
        repository: SearchRepository,
        provider: BaseMetadataSearchProvider,
        data_dir: str | Path = "data",
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.data_dir = Path(data_dir)

    def search_for_book(self, book_id: int) -> list[MetadataSearchCandidate]:
        query = _build_query(book_id, self.repository)
        if not query.title and not query.original_title:
            return []
        logger.info(
            "Metadata search start book_id=%s provider=%s title=%s",
            book_id,
            getattr(self.provider, "name", self.provider.__class__.__name__),
            query.title,
        )
        candidates = self.provider.search(query)
        logger.info(
            "Metadata search result book_id=%s candidate_count=%s",
            book_id,
            len(candidates),
        )
        return candidates

    def apply_candidate(
        self,
        book_id: int,
        candidate: MetadataSearchCandidate,
        fields: list[str],
    ) -> None:
        selected = set(fields)
        if not selected:
            return

        book = self.repository.get_book(book_id)
        if book is None:
            raise MetadataSearchServiceError(f"book 不存在：{book_id}")
        work = self.repository.get_work(int(book["work_id"]))
        if work is None:
            raise MetadataSearchServiceError(f"book {book_id} 找不到对应 work。")

        work_updates: dict[str, Any] = {}
        book_updates: dict[str, Any] = {}

        if "title" in selected and candidate.title:
            work_updates["title"] = candidate.title
        if (
            "original_title" in selected
            and candidate.original_title
            and "original_title" in work
        ):
            work_updates["original_title"] = candidate.original_title
        if "authors" in selected and candidate.authors:
            work_updates["author"] = candidate.authors[0]
        if "summary" in selected and candidate.summary:
            work_updates["summary"] = candidate.summary
        if "genres" in selected and candidate.genres:
            work_updates["genres"] = _join_list(candidate.genres)
        if "tags" in selected and candidate.tags:
            work_updates["tags"] = _join_list(candidate.tags)

        cover_path: str | None = None
        if "cover_url" in selected and candidate.cover_url:
            target_dir = self.data_dir / "covers" / str(book_id)
            target_dir.mkdir(parents=True, exist_ok=True)
            ext = _guess_cover_extension(candidate.cover_url)
            target_path = target_dir / f"search_cover{ext}"
            downloaded = download_cover(candidate.cover_url, target_path)
            cover_path = str(downloaded)

        if cover_path:
            book_updates["cover_override_path"] = cover_path

        if work_updates:
            self.repository.update_work(int(work["id"]), **work_updates)
        if book_updates:
            self.repository.update_book(book_id, **book_updates)

        logger.info(
            "Applied search candidate book_id=%s fields=%s cover=%s",
            book_id,
            sorted(selected),
            bool(cover_path),
        )


def download_cover(cover_url: str, target_path: str | Path) -> Path:
    dest = Path(target_path)
    if _is_mock_url(cover_url):
        _write_mock_cover(dest)
        return dest

    parsed = urlparse(cover_url)
    if parsed.scheme not in ("http", "https"):
        raise MetadataSearchServiceError(f"不支持的封面 URL 协议：{cover_url}")

    try:
        with httpx.Client(timeout=_COVER_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            response = client.get(cover_url)
            if response.status_code < 200 or response.status_code >= 300:
                raise MetadataSearchServiceError(
                    f"封面下载失败 HTTP {response.status_code}：{cover_url}"
                )
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                raise MetadataSearchServiceError(
                    f"封面 URL 返回的不是图片（{content_type}）：{cover_url}"
                )
            dest.write_bytes(response.content)
    except httpx.TimeoutException as exc:
        raise MetadataSearchServiceError(f"封面下载超时：{cover_url}") from exc
    except httpx.HTTPError as exc:
        raise MetadataSearchServiceError(f"封面下载网络错误：{exc}") from exc

    logger.info("Cover downloaded from=%s to=%s size=%s", cover_url, dest, dest.stat().st_size)
    return dest


def _build_query(book_id: int, repository: SearchRepository) -> MetadataSearchQuery:
    book = repository.get_book(book_id)
    if book is None:
        raise MetadataSearchServiceError(f"book 不存在：{book_id}")
    work = repository.get_work(int(book["work_id"]))
    if work is None:
        raise MetadataSearchServiceError(f"book {book_id} 找不到对应 work。")

    media_type = str(book.get("media_type") or "")
    if not media_type:
        source_type = str(book.get("source_type") or "")
        if source_type == "novel_txt":
            media_type = "novel"
        else:
            media_type = "comic"

    authors: list[str] = []
    raw_author = str(work.get("author") or "").strip()
    if raw_author:
        authors = [a.strip() for a in raw_author.split(",") if a.strip()]

    return MetadataSearchQuery(
        book_id=book_id,
        title=str(work.get("title") or "").strip(),
        original_title=str(work.get("original_title") or "").strip(),
        authors=authors,
        media_type=media_type,
        language_iso=str(work.get("language_iso") or "zh").strip(),
    )


def _join_list(values: list[str]) -> str:
    return ", ".join(values)


def _guess_cover_extension(url: str) -> str:
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    if ext and len(ext) <= 5 and ext.startswith("."):
        return ext.casefold()
    return ".jpg"


def _is_mock_url(url: str) -> bool:
    return url.startswith("mock://")


def _write_mock_cover(dest: Path) -> None:
    dest.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
