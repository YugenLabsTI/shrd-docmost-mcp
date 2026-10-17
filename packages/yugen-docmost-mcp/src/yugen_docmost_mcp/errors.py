"""Errors raised by the MCP layer itself (not by Docmost or the client)."""

from typing import ClassVar

from docmost_client import DocmostError


class ConfirmationUnavailableError(DocmostError):
    """A replace needs the user's confirmation, but the MCP host cannot ask for it."""

    code: ClassVar[str] = "CONFIRMATION_UNAVAILABLE"


class ConfirmationDeclinedError(DocmostError):
    """The user declined or cancelled the confirmation for a replace."""

    code: ClassVar[str] = "CONFIRMATION_DECLINED"


class AuditUnavailableError(DocmostError):
    """The audit log is configured but this call could not be recorded, so it was refused."""

    code: ClassVar[str] = "AUDIT_UNAVAILABLE"
