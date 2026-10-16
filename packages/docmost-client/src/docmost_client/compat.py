"""Docmost versions this client is tested against.

The client talks to Docmost's internal API, which can change in any release. Each
supported version has contract fixtures under ``tests/fixtures/<version>``.
"""

from docmost_client.errors import UnsupportedVersionError
from docmost_client.models import CompatibilityReport

SUPPORTED_DOCMOST_VERSIONS: tuple[str, ...] = ("0.96.0",)


def evaluate(version: str | None, *, allow_untested: bool) -> CompatibilityReport:
    """Classify ``version``; raise for an untested version unless explicitly allowed.

    An unknown version (Docmost could not report it) is not an error: Docmost v0.96.0
    omits the version whenever its own GitHub release lookup fails.
    """
    if version is None:
        status = "unknown"
    elif version in SUPPORTED_DOCMOST_VERSIONS:
        status = "supported"
    elif allow_untested:
        status = "untested"
    else:
        raise UnsupportedVersionError(
            f"Docmost {version} is not a tested version "
            f"({', '.join(SUPPORTED_DOCMOST_VERSIONS)}); its internal API may differ. "
            "Set DOCMOST_ALLOW_UNTESTED_VERSION=1 to connect anyway."
        )
    return CompatibilityReport(
        status=status, docmost_version=version, supported_versions=SUPPORTED_DOCMOST_VERSIONS
    )
