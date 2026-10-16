"""Client settings loaded from environment variables.

Secure defaults: HTTPS only, read-only, credentials kept in memory as ``SecretStr``.
Error messages name the offending variable but never echo its value.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, SecretStr

from docmost_client.errors import ConfigError

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})
_MAX_SECRET_FILE_BYTES = 64 * 1024

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_CONTENT_BYTES = 1_000_000


class DocmostSettings(BaseModel):
    """Connection, credential, and policy settings for a Docmost instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    email: str
    password: SecretStr
    read_only: bool = True
    allowed_spaces: frozenset[str] | None = None
    allow_insecure_http: bool = False
    allow_untested_version: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_content_bytes: int = DEFAULT_MAX_CONTENT_BYTES

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DocmostSettings":
        """Build settings from ``environ`` (defaults to ``os.environ``).

        Variables:
            DOCMOST_BASE_URL: instance URL; must be ``https://`` unless
                DOCMOST_ALLOW_INSECURE_HTTP is true.
            DOCMOST_EMAIL / DOCMOST_EMAIL_FILE: login email, or a file containing it.
            DOCMOST_PASSWORD / DOCMOST_PASSWORD_FILE: password, or a file containing it.
            DOCMOST_READ_ONLY: defaults to true; set to false to allow writes.
            DOCMOST_ALLOWED_SPACES: comma-separated space slugs or IDs; unset means
                every space the account can access.
            DOCMOST_ALLOW_INSECURE_HTTP: allow ``http://`` base URLs (local development).
            DOCMOST_ALLOW_UNTESTED_VERSION: allow Docmost versions this client is not
                tested against (the internal API may differ).
            DOCMOST_TIMEOUT_SECONDS: per-request timeout, default 30.
            DOCMOST_MAX_CONTENT_BYTES: maximum page content size accepted for writes.
        """
        env = os.environ if environ is None else environ
        allow_insecure_http = _bool(env, "DOCMOST_ALLOW_INSECURE_HTTP", default=False)
        return cls(
            base_url=_base_url(_required(env, "DOCMOST_BASE_URL"), allow_insecure_http),
            email=_secret_or_file(env, "DOCMOST_EMAIL"),
            password=SecretStr(_secret_or_file(env, "DOCMOST_PASSWORD")),
            read_only=_bool(env, "DOCMOST_READ_ONLY", default=True),
            allowed_spaces=_allowed_spaces(env),
            allow_insecure_http=allow_insecure_http,
            allow_untested_version=_bool(env, "DOCMOST_ALLOW_UNTESTED_VERSION", default=False),
            timeout_seconds=_positive_float(
                env, "DOCMOST_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
            ),
            max_content_bytes=_positive_int(
                env, "DOCMOST_MAX_CONTENT_BYTES", DEFAULT_MAX_CONTENT_BYTES
            ),
        )


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required.")
    return value


def _secret_or_file(env: Mapping[str, str], name: str) -> str:
    file_name = f"{name}_FILE"
    # Empty values count as unset: compose files often declare VAR="" placeholders.
    direct = env.get(name) or None
    file_path = env.get(file_name) or None
    if direct is not None and file_path is not None:
        raise ConfigError(f"Set either {name} or {file_name}, not both.")
    if file_path is not None:
        return _read_secret_file(file_name, file_path)
    if not direct:
        raise ConfigError(f"{name} or {file_name} is required.")
    return direct


def _read_secret_file(name: str, path: str) -> str:
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(_MAX_SECRET_FILE_BYTES + 1)
    except OSError:
        raise ConfigError(f"{name} points to a file that cannot be read.") from None
    if len(raw) > _MAX_SECRET_FILE_BYTES:
        raise ConfigError(f"{name} points to a file that is too large.")
    try:
        value = raw.decode("utf-8").rstrip("\r\n")
    except UnicodeDecodeError:
        raise ConfigError(f"{name} points to a file that is not valid UTF-8.") from None
    if not value:
        raise ConfigError(f"{name} points to an empty file.")
    return value


def _base_url(raw: str, allow_insecure_http: bool) -> str:
    error = ConfigError(
        "DOCMOST_BASE_URL must be an absolute https:// URL without credentials, query, or fragment."
    )
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise error from None
    scheme = parts.scheme.lower()
    if scheme == "http" and not allow_insecure_http:
        raise ConfigError(
            "DOCMOST_BASE_URL uses http://; set DOCMOST_ALLOW_INSECURE_HTTP=1 to allow it "
            "(local development only)."
        )
    if scheme not in {"https", "http"} or not parts.hostname:
        raise error
    if parts.username is not None or parts.password is not None:
        raise error
    if parts.query or parts.fragment or raw.endswith(("?", "#")):
        raise error
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))


def _bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{name} must be one of: 1, 0, true, false, yes, no, on, off.")


def _allowed_spaces(env: Mapping[str, str]) -> frozenset[str] | None:
    raw = env.get("DOCMOST_ALLOWED_SPACES")
    if raw is None:
        return None
    spaces = frozenset(item.strip() for item in raw.split(",") if item.strip())
    if not spaces:
        raise ConfigError(
            "DOCMOST_ALLOWED_SPACES is set but lists no spaces; unset it to allow every "
            "space or list at least one slug or ID."
        )
    return spaces


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a positive number.") from None
    if not value > 0 or value == float("inf"):
        raise ConfigError(f"{name} must be a positive number.")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a positive integer.") from None
    if value <= 0:
        raise ConfigError(f"{name} must be a positive integer.")
    return value
