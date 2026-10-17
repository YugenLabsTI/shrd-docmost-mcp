"""Command-line entry point: ``yugen-docmost-mcp`` serves MCP over stdio."""

import argparse
import dataclasses
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from docmost_client import AsyncDocmostClient, ConfigError, DocmostSettings
from docmost_client.settings import env_flag
from yugen_docmost_mcp._version import __version__
from yugen_docmost_mcp.audit import (
    AuditLog,
    audit_settings_from_env,
    parse_since,
    read_events,
    render_report,
    summarize,
)
from yugen_docmost_mcp.prompts import BUILTIN_PROMPTS, PromptSpec, prompts_from_env
from yugen_docmost_mcp.server import build_server


def confirm_replace_from_env(environ: Mapping[str, str] | None = None) -> bool:
    """DOCMOST_CONFIRM_REPLACE (default true): ask the user before a replace."""
    env = os.environ if environ is None else environ
    return env_flag(env, "DOCMOST_CONFIRM_REPLACE", default=True)


def create_server(
    settings: DocmostSettings,
    *,
    confirm_replace: bool = True,
    prompts: Sequence[PromptSpec] = BUILTIN_PROMPTS,
    audit: AuditLog | None = None,
    expose_audit: bool = False,
) -> MCPServer[Any]:
    """Build the server for ``settings`` with ``prompts`` (see ``prompts_from_env``).

    Page write tools exist only when DOCMOST_READ_ONLY is off, ``move_page`` only when
    DOCMOST_ALLOW_MOVE is on as well, and ``add_comment`` only when DOCMOST_ALLOW_COMMENTS
    is on; the client enforces these again on every call.
    """
    client = AsyncDocmostClient(settings)
    return build_server(
        client,
        None if settings.read_only else client,
        commenter=client if settings.allow_comments else None,
        mover=client if settings.allow_move and not settings.read_only else None,
        confirm_replace=confirm_replace,
        prompts=prompts,
        audit=audit,
        expose_audit=expose_audit,
        on_shutdown=client.aclose,
    )


def audit_from_env(environ: Mapping[str, str] | None = None) -> tuple[AuditLog | None, bool]:
    """The audit log (or None) and whether ``audit_summary`` is exposed; ConfigError."""
    audit_settings = audit_settings_from_env(environ)
    if audit_settings.path is None:
        return None, False
    audit = AuditLog.open(audit_settings.path, reads=audit_settings.reads)
    return audit, audit_settings.expose


def main(argv: Sequence[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else list(argv)
    if args[:1] == ["audit"]:
        raise SystemExit(audit_command(args[1:]))
    if "--version" in args:
        sys.stdout.write(f"yugen-docmost-mcp {__version__}\n")
        raise SystemExit(0)
    # stdout carries the MCP protocol; logs go to stderr. Request and response
    # bodies are never logged.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        settings = DocmostSettings.from_env()
        confirm_replace = confirm_replace_from_env()
        prompts = prompts_from_env()
        audit, expose_audit = audit_from_env()
    except ConfigError as exc:
        sys.stderr.write(f"yugen-docmost-mcp: {exc}\n")
        raise SystemExit(2) from None
    create_server(
        settings,
        confirm_replace=confirm_replace,
        prompts=prompts,
        audit=audit,
        expose_audit=expose_audit,
    ).run("stdio")


def audit_command(argv: Sequence[str]) -> int:
    """``audit report``: summarize the audit log for the operator (exit 2 on errors)."""
    parser = argparse.ArgumentParser(prog="yugen-docmost-mcp audit")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="Summarize the audit log.")
    report.add_argument("--file", help="Audit log file (default: DOCMOST_AUDIT_LOG).")
    report.add_argument("--since", help="Only the last 30m, 24h, 7d, ...")
    report.add_argument("--json", action="store_true", help="Print the summary as JSON.")
    options = parser.parse_args(list(argv))

    raw = options.file or os.environ.get("DOCMOST_AUDIT_LOG", "").strip()
    if not raw:
        parser.error("no audit log: pass --file or set DOCMOST_AUDIT_LOG.")
    since = None
    if options.since:
        try:
            since = parse_since(options.since, datetime.now(UTC))
        except ValueError:
            parser.error("--since must look like 30m, 24h or 7d.")
    path = Path(raw)
    try:
        summary = summarize(read_events(path, since))
    except OSError:
        parser.error(f"the audit log {path} cannot be read.")
    if options.json:
        sys.stdout.write(json.dumps(dataclasses.asdict(summary), indent=2) + "\n")
    else:
        sys.stdout.write(render_report(summary, str(path)))
    return 0


if __name__ == "__main__":
    main()
