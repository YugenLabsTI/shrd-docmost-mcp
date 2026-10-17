"""`yugen-docmost-mcp audit report`: the operator's view of the audit log."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from yugen_docmost_mcp.__main__ import main


def row(phase: str, tool: str, call: str, hours_ago: float = 0, **extra: Any) -> str:
    ts = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    kind = "read" if tool == "get_page" else "write"
    return json.dumps({"ts": ts, "session": "s", "call": call, "phase": phase, "tool": tool,
                       "kind": kind, "args": extra.pop("args", {}), **extra})  # fmt: skip


@pytest.fixture
def audit_file(tmp_path: Path) -> Path:
    path = tmp_path / "audit.jsonl"
    rows = [
        row("started", "create_page", "c1", hours_ago=48),
        row("finished", "create_page", "c1", hours_ago=48, outcome="ok",
            args={"space": "eng"}, result_page_id="p-old"),
        row("started", "update_page", "c2", hours_ago=1),
        row("finished", "update_page", "c2", hours_ago=1, outcome="error",
            code="CONFIRMATION_DECLINED", args={"page_id": "p1", "space": "eng"}),
        row("started", "move_page", "c3", hours_ago=0.5),
    ]  # fmt: skip
    path.write_text("".join(f"{line}\n" for line in rows))
    return path


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc:
        main(list(argv))
    captured = capsys.readouterr()
    return int(exc.value.code or 0), captured.out, captured.err


def test_text_report_summarizes_the_log(
    capsys: pytest.CaptureFixture[str], audit_file: Path
) -> None:
    code, out, _ = run(capsys, "audit", "report", "--file", str(audit_file))

    assert code == 0
    assert "Calls: 2 (ok 1, errors 1)" in out
    assert "create_page" in out
    assert "CONFIRMATION_DECLINED  1" in out
    assert "Interrupted calls: 1" in out
    assert "move_page" in out


def test_json_report_and_since_filter(capsys: pytest.CaptureFixture[str], audit_file: Path) -> None:
    code, out, _ = run(
        capsys, "audit", "report", "--file", str(audit_file), "--since", "24h", "--json"
    )

    report = json.loads(out)
    assert code == 0
    assert report["calls"] == 1
    assert report["by_tool"] == {"update_page": {"ok": 0, "error": 1}}
    assert report["pages_refused"] == ["p1"]
    assert report["pages_written"] == []


def test_the_log_comes_from_the_environment_by_default(
    capsys: pytest.CaptureFixture[str], audit_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCMOST_AUDIT_LOG", str(audit_file))

    code, out, _ = run(capsys, "audit", "report", "--json")

    assert code == 0
    assert json.loads(out)["calls"] == 2


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["audit", "report"], "DOCMOST_AUDIT_LOG"),
        (["audit", "report", "--file", "/nonexistent/audit.jsonl"], "cannot be read"),
        (["audit", "report", "--file", "{file}", "--since", "yesterday"], "--since"),
        (["audit", "frobnicate"], "invalid choice"),
    ],
)
def test_report_errors_exit_2(
    capsys: pytest.CaptureFixture[str],
    audit_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    message: str,
) -> None:
    monkeypatch.delenv("DOCMOST_AUDIT_LOG", raising=False)

    code, _, err = run(capsys, *[arg.replace("{file}", str(audit_file)) for arg in argv])

    assert code == 2
    assert message in err


def test_a_huge_since_is_a_clear_error(
    capsys: pytest.CaptureFixture[str], audit_file: Path
) -> None:
    code, _, err = run(
        capsys, "audit", "report", "--file", str(audit_file), "--since", "99999999999d"
    )

    assert code == 2
    assert "--since" in err
