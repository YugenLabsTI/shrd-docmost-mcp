"""Local audit log: what the agent did through this server, without any page content.

Enabled by DOCMOST_AUDIT_LOG (a file path). Each tool call becomes JSON lines (one per
event) appended to that file, created with mode 0600:

    {"ts": "...", "session": "...", "call": "...", "phase": "started" | "finished",
     "tool": "update_page", "kind": "write", "args": {"page_id": "...", ...},
     "outcome": "ok" | "error", "code": "PAGE_BUSY", "duration_ms": 12,
     "result_page_id": "..."}

Only identifiers and enum-like arguments are kept (``AUDITED_ARGUMENTS``); content,
titles, comment text, search queries and icons never are. Write tools fail closed: their
``started`` line is written before the call, and the call is refused if it cannot be.
Reads are recorded only with DOCMOST_AUDIT_READS=1.
"""

import json
import logging
import os
import re
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from docmost_client import ConfigError
from docmost_client.settings import env_flag
from yugen_docmost_mcp.errors import AuditUnavailableError

logger = logging.getLogger(__name__)

AUDITED_ARGUMENTS = frozenset(
    {
        "page_id", "space", "parent_page_id", "operation", "format", "heading_id",
        "after_page_id", "placement", "parent_comment_id",
    }
)  # fmt: skip
WRITE_TOOLS = frozenset({"create_page", "update_page", "edit_section", "move_page", "add_comment"})
MAX_VALUE_LENGTH = 128
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

Outcome = Literal["ok", "error"]


@dataclass(frozen=True)
class AuditSettings:
    path: Path | None = None
    reads: bool = False
    expose: bool = False


def audit_settings_from_env(environ: Mapping[str, str] | None = None) -> AuditSettings:
    """DOCMOST_AUDIT_LOG (path), DOCMOST_AUDIT_READS and DOCMOST_AUDIT_EXPOSE (flags)."""
    env = os.environ if environ is None else environ
    raw = env.get("DOCMOST_AUDIT_LOG", "").strip()
    reads = env_flag(env, "DOCMOST_AUDIT_READS", default=False)
    expose = env_flag(env, "DOCMOST_AUDIT_EXPOSE", default=False)
    if not raw:
        if reads or expose:
            raise ConfigError(
                "DOCMOST_AUDIT_READS and DOCMOST_AUDIT_EXPOSE need DOCMOST_AUDIT_LOG "
                "(the audit log file)."
            )
        return AuditSettings()
    return AuditSettings(path=Path(raw), reads=reads, expose=expose)


class AuditLog:
    """Appends audit events to a JSON-lines file; one instance per server process."""

    def __init__(
        self,
        path: Path,
        *,
        reads: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = path
        self.reads = reads
        self.session = uuid.uuid4().hex[:12]
        self._clock = clock

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        reads: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> "AuditLog":
        """Check that ``path`` can be appended to (creating it), or raise ConfigError."""
        audit = cls(path, reads=reads, clock=clock)
        try:
            os.close(audit._open())
        except OSError:
            raise ConfigError(
                "DOCMOST_AUDIT_LOG must be a file this process can create or append to."
            ) from None
        return audit

    def wants(self, tool: str) -> bool:
        return tool in WRITE_TOOLS or self.reads

    def started(self, call: str, tool: str, arguments: Mapping[str, object]) -> None:
        """Record that a call begins; raise AuditUnavailableError if it cannot be recorded."""
        try:
            self._append(self._event(call, "started", tool, arguments))
        except OSError:
            raise AuditUnavailableError(
                "The audit log could not be written, so the call was refused; check "
                "DOCMOST_AUDIT_LOG."
            ) from None

    def finished(
        self,
        call: str,
        tool: str,
        arguments: Mapping[str, object],
        *,
        outcome: Outcome,
        code: str | None,
        duration_ms: int,
        result_page_id: str | None = None,
    ) -> None:
        """Record how a call ended; best effort (the call already happened)."""
        event = self._event(call, "finished", tool, arguments)
        event["outcome"] = outcome
        event["code"] = code
        event["duration_ms"] = duration_ms
        if result_page_id:
            event["result_page_id"] = _clean(result_page_id)
        try:
            self._append(event)
        except OSError:
            # Never include the error text: it may carry the path or system details.
            logger.warning("Could not write the audit log entry for %s.", tool)

    def _event(
        self, call: str, phase: str, tool: str, arguments: Mapping[str, object]
    ) -> dict[str, Any]:
        return {
            "ts": self._clock().isoformat(),
            "session": self.session,
            "call": call,
            "phase": phase,
            "tool": tool,
            "kind": "write" if tool in WRITE_TOOLS else "read",
            "args": {
                name: _clean(value)
                for name, value in arguments.items()
                if name in AUDITED_ARGUMENTS and isinstance(value, str) and value
            },
        }

    def _open(self) -> int:
        return os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)

    def _append(self, event: Mapping[str, Any]) -> None:
        line = (json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        fd = self._open()
        try:
            # One write of a short line: O_APPEND keeps concurrent writers' lines whole.
            os.write(fd, line)
        finally:
            os.close(fd)


def _clean(value: str) -> str:
    return _CONTROL.sub(" ", value)[:MAX_VALUE_LENGTH]


def read_events(path: Path, since: datetime | None) -> Iterator[dict[str, Any]]:
    """Events in file order; malformed lines and events before ``since`` are skipped."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            row = cast(dict[str, Any], event)
            when = _parse_ts(row.get("ts"))
            if when is None or (since is not None and when < since):
                continue
            yield row


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


@dataclass
class AuditSummary:
    """What happened in a span of the audit log."""

    calls: int = 0
    first: str | None = None
    last: str | None = None
    by_tool: dict[str, dict[str, int]] = field(default_factory=dict[str, dict[str, int]])
    errors_by_code: dict[str, int] = field(default_factory=dict[str, int])
    spaces: dict[str, int] = field(default_factory=dict[str, int])
    pages_written: list[str] = field(default_factory=list[str])
    pages_refused: list[str] = field(default_factory=list[str])
    interrupted: list[dict[str, str]] = field(default_factory=list[dict[str, str]])


def summarize(events: Iterable[Mapping[str, Any]]) -> AuditSummary:
    summary = AuditSummary()
    open_calls: dict[str, Mapping[str, Any]] = {}
    written: set[str] = set()
    refused: set[str] = set()
    for event in events:
        call, tool, ts = str(event.get("call")), str(event.get("tool")), str(event.get("ts"))
        summary.first = summary.first or ts
        summary.last = ts
        if event.get("phase") == "started":
            open_calls[call] = event
            continue
        if event.get("phase") != "finished":
            continue
        open_calls.pop(call, None)
        summary.calls += 1
        outcome = "ok" if event.get("outcome") == "ok" else "error"
        counts = summary.by_tool.setdefault(tool, {"ok": 0, "error": 0})
        counts[outcome] += 1
        args = cast(Mapping[str, Any], event.get("args") or {})
        space = args.get("space")
        if isinstance(space, str):
            summary.spaces[space] = summary.spaces.get(space, 0) + 1
        page = event.get("result_page_id") or args.get("page_id")
        if outcome == "error":
            code = str(event.get("code") or "UNKNOWN")
            summary.errors_by_code[code] = summary.errors_by_code.get(code, 0) + 1
        if event.get("kind") == "write" and isinstance(page, str):
            (written if outcome == "ok" else refused).add(page)
    summary.pages_written = sorted(written)
    summary.pages_refused = sorted(refused - written)
    summary.interrupted = [
        {"call": call, "tool": str(event.get("tool")), "ts": str(event.get("ts"))}
        for call, event in open_calls.items()
    ]
    return summary
