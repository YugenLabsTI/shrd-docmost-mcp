"""Unofficial typed client for the internal API of self-hosted Docmost Community Edition."""

from docmost_client._version import __version__
from docmost_client.errors import (
    AuthenticationError,
    ConfigError,
    DocmostError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    UpstreamError,
)
from docmost_client.session import AsyncSession, Session
from docmost_client.settings import DocmostSettings

__all__ = [
    "AsyncSession",
    "AuthenticationError",
    "ConfigError",
    "DocmostError",
    "DocmostSettings",
    "InvalidRequestError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitedError",
    "Session",
    "UpstreamError",
    "__version__",
]
