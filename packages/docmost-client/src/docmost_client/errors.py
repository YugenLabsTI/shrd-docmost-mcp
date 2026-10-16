"""Typed errors raised by docmost-client.

Every error carries a stable machine-readable ``code`` so callers (for example an MCP
server) can map failures without parsing messages. Messages never include credentials,
tokens, or page bodies.
"""

from typing import ClassVar


class DocmostError(Exception):
    """Base class for every error raised by docmost-client."""

    code: ClassVar[str] = "DOCMOST_ERROR"


class ConfigError(DocmostError):
    """The client configuration is missing, malformed, or unsafe."""

    code: ClassVar[str] = "INVALID_CONFIG"
