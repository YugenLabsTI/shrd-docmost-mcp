"""Typed errors raised by docmost-client.

Every error carries a stable machine-readable ``code`` so callers (for example an MCP
server) can map failures without parsing messages. Messages never include credentials,
tokens, or page bodies.
"""

from datetime import datetime
from typing import ClassVar


class DocmostError(Exception):
    """Base class for every error raised by docmost-client."""

    code: ClassVar[str] = "DOCMOST_ERROR"

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConfigError(DocmostError):
    """The client configuration is missing, malformed, or unsafe."""

    code: ClassVar[str] = "INVALID_CONFIG"


class AuthenticationError(DocmostError):
    """Login failed, or Docmost rejected the session even after logging in again."""

    code: ClassVar[str] = "AUTH_FAILED"


class PermissionDeniedError(DocmostError):
    """The account is not allowed to perform the operation."""

    code: ClassVar[str] = "FORBIDDEN"


class NotFoundError(DocmostError):
    """The resource does not exist or is not visible to the account.

    Docmost answers 404 (not 403) when the account is not a member of a space.
    """

    code: ClassVar[str] = "NOT_FOUND"


class InvalidRequestError(DocmostError):
    """Docmost rejected the request payload (validation error or body too large)."""

    code: ClassVar[str] = "INVALID_INPUT"


class RateLimitedError(DocmostError):
    """Docmost rate-limited the request (login is limited to 10 per minute per IP)."""

    code: ClassVar[str] = "RATE_LIMITED"


class UpstreamError(DocmostError):
    """Docmost was unreachable or answered with an unexpected response."""

    code: ClassVar[str] = "UPSTREAM_ERROR"


class UnsupportedVersionError(DocmostError):
    """The Docmost server runs a version this client has not been tested against."""

    code: ClassVar[str] = "UNSUPPORTED_VERSION"


class SpaceNotAllowedError(DocmostError):
    """The resource belongs to a space outside DOCMOST_ALLOWED_SPACES."""

    code: ClassVar[str] = "SPACE_NOT_ALLOWED"


class ReadOnlyError(DocmostError):
    """A write was attempted while DOCMOST_READ_ONLY is enabled (the default)."""

    code: ClassVar[str] = "READ_ONLY"


class StalePageError(DocmostError):
    """The page changed after the caller read it (``updatedAt`` precheck failed).

    The check narrows but cannot close the race: Docmost has no compare-and-swap, and
    edits typed in the browser are persisted up to ~45 s later.
    """

    code: ClassVar[str] = "STALE_PAGE"

    def __init__(self, message: str, *, current_updated_at: datetime) -> None:
        super().__init__(message)
        self.current_updated_at = current_updated_at


class CommentsDisabledError(DocmostError):
    """A comment was attempted while DOCMOST_ALLOW_COMMENTS is off (the default)."""

    code: ClassVar[str] = "COMMENTS_DISABLED"
