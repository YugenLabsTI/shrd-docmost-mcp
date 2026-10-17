"""Local audit log: sanitized JSON lines, fail-closed writes, reading and summarizing."""

import json
import logging
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from docmost_client import ConfigError
from yugen_docmost_mcp.audit import (
    AuditLog,
    audit_settings_from_env,
    read_events,
    summarize,
)
from yugen_docmost_mcp.errors import AuditUnavailableError

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def log(tmp_path: Path, **kwargs: Any) -> AuditLog:
    return AuditLog.open(tmp_path / "audit.jsonl", clock=lambda: NOW, **kwargs)


# --- settings ------------------------------------------------------------------------


def test_auditing_is_off_without_a_log_path() -> None:
    settings = audit_settings_from_env({})

    assert settings.path is None
    assert settings.reads is False
    assert settings.expose is False


def test_audit_settings_from_env(tmp_path: Path) -> None:
    settings = audit_settings_from_env(
        {
            "DOCMOST_AUDIT_LOG": str(tmp_path / "a.jsonl"),
            "DOCMOST_AUDIT_READS": "1",
            "DOCMOST_AUDIT_EXPOSE": "1",
        }
    )

    assert settings.path == tmp_path / "a.jsonl"
    assert settings.reads is True
    assert settings.expose is True


@pytest.mark.parametrize("flag", ["DOCMOST_AUDIT_READS", "DOCMOST_AUDIT_EXPOSE"])
def test_audit_flags_need_a_log(flag: str) -> None:
    with pytest.raises(ConfigError, match="DOCMOST_AUDIT_LOG"):
        audit_settings_from_env({flag: "1"})


def test_invalid_audit_flags_are_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="DOCMOST_AUDIT_READS"):
        audit_settings_from_env(
            {"DOCMOST_AUDIT_LOG": str(tmp_path / "a"), "DOCMOST_AUDIT_READS": "maybe"}
        )


# --- opening -------------------------------------------------------------------------


def test_the_log_file_is_private_to_its_owner(tmp_path: Path) -> None:
    log(tmp_path)

    mode = stat.S_IMODE(os.stat(tmp_path / "audit.jsonl").st_mode)
    assert mode == 0o600


@pytest.mark.parametrize("kind", ["missing-dir", "directory"])
def test_a_log_that_cannot_be_opened_is_a_config_error(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "nope" / "audit.jsonl" if kind == "missing-dir" else tmp_path

    with pytest.raises(ConfigError, match="DOCMOST_AUDIT_LOG"):
        AuditLog.open(target)


def test_an_existing_log_is_appended_to(tmp_path: Path) -> None:
    (tmp_path / "audit.jsonl").write_text('{"old": true}\n')

    log(tmp_path).finished("c1", "search", {}, outcome="ok", code=None, duration_ms=3)

    assert len(lines(tmp_path / "audit.jsonl")) == 2


# --- events --------------------------------------------------------------------------


def test_events_keep_only_ids_and_enums(tmp_path: Path) -> None:
    audit = log(tmp_path)
    arguments = {
        "page_id": "abc123xyz0",
        "space": "engineering",
        "operation": "replace",
        "content": "SECRET body",
        "title": "Secret title",
        "text": "a comment",
        "query": "salaries",
        "icon": "🔥",
        "section_gate": {"status": "accepted"},
    }

    audit.started("c1", "update_page", arguments)
    audit.finished(
        "c1",
        "update_page",
        arguments,
        outcome="error",
        code="CONFIRMATION_DECLINED",
        duration_ms=12,
        result_page_id=None,
    )

    started, finished = lines(tmp_path / "audit.jsonl")
    assert started == {
        "ts": "2026-10-17T12:00:00+00:00",
        "session": audit.session,
        "call": "c1",
        "phase": "started",
        "tool": "update_page",
        "kind": "write",
        "args": {"page_id": "abc123xyz0", "space": "engineering", "operation": "replace"},
    }
    assert finished["phase"] == "finished"
    assert finished["outcome"] == "error"
    assert finished["code"] == "CONFIRMATION_DECLINED"
    assert finished["duration_ms"] == 12
    text = (tmp_path / "audit.jsonl").read_text()
    for secret in ("SECRET", "Secret title", "a comment", "salaries", "🔥", "section_gate"):
        assert secret not in text


def test_argument_values_are_truncated_and_cleaned(tmp_path: Path) -> None:
    audit = log(tmp_path)

    audit.started("c1", "create_page", {"space": "x" * 500, "parent_page_id": "a\nb\x1bc"})

    args = lines(tmp_path / "audit.jsonl")[0]["args"]
    assert args["space"] == "x" * 128
    assert args["parent_page_id"] == "a b c"


def test_reads_are_recorded_only_when_asked(tmp_path: Path) -> None:
    assert log(tmp_path).wants("create_page") is True
    assert log(tmp_path).wants("get_page") is False
    assert log(tmp_path, reads=True).wants("get_page") is True


def test_a_start_that_cannot_be_written_refuses_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = log(tmp_path)

    def broken(*args: Any, **kwargs: Any) -> int:
        raise OSError("disk full")

    monkeypatch.setattr("yugen_docmost_mcp.audit.os.open", broken)

    with pytest.raises(AuditUnavailableError, match="audit log") as exc:
        audit.started("c1", "create_page", {})
    assert exc.value.code == "AUDIT_UNAVAILABLE"


def test_a_finish_that_cannot_be_written_only_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    audit = log(tmp_path)

    def broken(*args: Any, **kwargs: Any) -> int:
        raise OSError("disk full")

    monkeypatch.setattr("yugen_docmost_mcp.audit.os.open", broken)
    with caplog.at_level(logging.WARNING):
        audit.finished("c1", "create_page", {}, outcome="ok", code=None, duration_ms=1)

    assert "audit" in caplog.text.lower()
    assert "disk full" not in caplog.text


# --- reading and summarizing -----------------------------------------------------------


def event(phase: str, tool: str, call: str, minutes_ago: int = 0, **extra: Any) -> str:
    ts = (NOW - timedelta(minutes=minutes_ago)).isoformat()
    kind = "read" if tool in {"get_page", "search"} else "write"
    return json.dumps({"ts": ts, "session": "s", "call": call, "phase": phase, "tool": tool,
                       "kind": kind, "args": extra.pop("args", {}), **extra})  # fmt: skip


def write_log(path: Path, *rows: str) -> Path:
    path.write_text("".join(f"{row}\n" for row in rows))
    return path


def test_read_events_skips_malformed_lines_and_filters_by_time(tmp_path: Path) -> None:
    path = write_log(
        tmp_path / "a.jsonl",
        event("finished", "create_page", "c1", minutes_ago=600, outcome="ok"),
        "not json",
        '["a list"]',
        event("finished", "update_page", "c2", minutes_ago=5, outcome="ok"),
    )

    events = list(read_events(path, since=NOW - timedelta(hours=1)))

    assert [e["call"] for e in events] == ["c2"]


def test_summary_counts_outcomes_refusals_pages_and_interrupted_calls(tmp_path: Path) -> None:
    path = write_log(
        tmp_path / "a.jsonl",
        event("started", "create_page", "c1"),
        event("finished", "create_page", "c1", outcome="ok", args={"space": "eng"},
              result_page_id="p-new"),
        event("started", "update_page", "c2"),
        event("finished", "update_page", "c2", outcome="error", code="CONFIRMATION_DECLINED",
              args={"page_id": "p1", "operation": "replace"}),
        event("started", "edit_section", "c3"),
        event("finished", "edit_section", "c3", outcome="error", code="PAGE_BUSY",
              args={"page_id": "p1"}),
        event("started", "move_page", "c4"),
        event("finished", "get_page", "c5", outcome="ok", args={"page_id": "p2"}),
    )  # fmt: skip

    summary = summarize(read_events(path, since=None))

    assert summary.calls == 4
    assert summary.by_tool == {
        "create_page": {"ok": 1, "error": 0},
        "update_page": {"ok": 0, "error": 1},
        "edit_section": {"ok": 0, "error": 1},
        "get_page": {"ok": 1, "error": 0},
    }
    assert summary.errors_by_code == {"CONFIRMATION_DECLINED": 1, "PAGE_BUSY": 1}
    assert summary.pages_written == ["p-new"]
    assert summary.pages_refused == ["p1"]
    assert summary.interrupted == [{"call": "c4", "tool": "move_page", "ts": NOW.isoformat()}]
    assert summary.first == NOW.isoformat()
    assert summary.last == NOW.isoformat()


def test_unicode_format_and_control_characters_are_removed(tmp_path: Path) -> None:
    audit = log(tmp_path)

    audit.started("c1", "add_comment", {"page_id": "p\u202eevil\u009b\u2028x\u200by"})

    assert lines(tmp_path / "audit.jsonl")[0]["args"]["page_id"] == "p evil  x y"


def test_unencodable_values_are_still_recorded(tmp_path: Path) -> None:
    audit = log(tmp_path)

    audit.started("c1", "add_comment", {"page_id": "p\ud800"})

    assert len(lines(tmp_path / "audit.jsonl")) == 1


def test_summary_tolerates_hand_edited_lines(tmp_path: Path) -> None:
    path = write_log(
        tmp_path / "a.jsonl",
        event("finished", "create_page", "c1", outcome="ok", args=["not", "a", "dict"]),
        event("finished", "update_page", "c2", outcome="error", code=7, args="x"),
    )

    summary = summarize(read_events(path, since=None))

    assert summary.calls == 2
    assert summary.errors_by_code == {"7": 1}


def test_short_writes_are_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit = log(tmp_path)
    real_write = os.write

    def one_byte_at_a_time(fd: int, data: bytes) -> int:
        return real_write(fd, data[:1])

    monkeypatch.setattr("yugen_docmost_mcp.audit.os.write", one_byte_at_a_time)
    audit.started("c1", "create_page", {"space": "eng"})

    assert lines(tmp_path / "audit.jsonl")[0]["args"] == {"space": "eng"}


def test_a_write_that_makes_no_progress_refuses_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audit = log(tmp_path)
    monkeypatch.setattr("yugen_docmost_mcp.audit.os.write", lambda fd, data: 0)

    with pytest.raises(AuditUnavailableError):
        audit.started("c1", "create_page", {})
