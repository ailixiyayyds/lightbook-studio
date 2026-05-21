from app.search.provider import BaseMetadataSearchProvider
from app.search.types import MetadataSearchCandidate, MetadataSearchQuery


class NdlSearchProvider(BaseMetadataSearchProvider):
    name = "ndl_search"

    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        return []


class AmazonJpProvider(BaseMetadataSearchProvider):
    name = "amazon_jp"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        return []


class GenericSearchProvider(BaseMetadataSearchProvider):
    name = "generic_search"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def search(self, query: MetadataSearchQuery) -> list[MetadataSearchCandidate]:
        return []


class ManualUrlProvider:
    def create_from_url(self, cover_url: str, source_url: str = "", title: str = "") -> MetadataSearchCandidate | None:
        if not cover_url.strip():
            return None
        url = cover_url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return None

        return MetadataSearchCandidate(
            title=title or "手动输入",
            cover_url=url,
            source_url=source_url or url,
            source_name="用户手动输入",
            source_type="manual",
            verified=True,
            notes=["用户提供链接，程序未验证版权来源"],
        )
