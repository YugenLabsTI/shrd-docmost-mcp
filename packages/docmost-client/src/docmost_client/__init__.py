"""Unofficial typed client for the internal API of self-hosted Docmost Community Edition."""

from docmost_client._version import __version__
from docmost_client.client import AsyncDocmostClient, DocmostClient
from docmost_client.compat import SUPPORTED_DOCMOST_VERSIONS
from docmost_client.errors import (
    AuthenticationError,
    ConfigError,
    DocmostError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ReadOnlyError,
    SpaceNotAllowedError,
    StalePageError,
    UnsupportedVersionError,
    UpstreamError,
)
from docmost_client.models import (
    CONTENT_FORMATS,
    CONTENT_OPERATIONS,
    CompatibilityReport,
    ContentFormat,
    ContentOperation,
    CurrentUser,
    Page,
    PageSummary,
    Paginated,
    SearchHit,
    Space,
    SpaceRef,
)
from docmost_client.session import AsyncSession, Session
from docmost_client.settings import DocmostSettings

__all__ = [
    "CONTENT_FORMATS",
    "CONTENT_OPERATIONS",
    "SUPPORTED_DOCMOST_VERSIONS",
    "AsyncDocmostClient",
    "AsyncSession",
    "AuthenticationError",
    "CompatibilityReport",
    "ConfigError",
    "ContentFormat",
    "ContentOperation",
    "CurrentUser",
    "DocmostClient",
    "DocmostError",
    "DocmostSettings",
    "InvalidRequestError",
    "NotFoundError",
    "Page",
    "PageSummary",
    "Paginated",
    "PermissionDeniedError",
    "RateLimitedError",
    "ReadOnlyError",
    "SearchHit",
    "Session",
    "Space",
    "SpaceNotAllowedError",
    "SpaceRef",
    "StalePageError",
    "UnsupportedVersionError",
    "UpstreamError",
    "__version__",
]
