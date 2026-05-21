"""Metadata search providers.

All source_url and cover_url values come from real provider APIs
or user manual input. AI is never used to invent URLs.
"""

from app.search.providers.google_books_provider import GoogleBooksProvider
from app.search.providers.open_library_provider import OpenLibraryProvider
from app.search.providers.other_providers import (
    AmazonJpProvider,
    GenericSearchProvider,
    ManualUrlProvider,
    NdlSearchProvider,
)

__all__ = [
    "GoogleBooksProvider",
    "OpenLibraryProvider",
    "NdlSearchProvider",
    "AmazonJpProvider",
    "GenericSearchProvider",
    "ManualUrlProvider",
]
