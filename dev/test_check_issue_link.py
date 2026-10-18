"""The issue-link check refuses pull requests that do not link an approved issue."""

import importlib.util
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".github/scripts/check_issue_link.py"
_spec = importlib.util.spec_from_file_location("check_issue_link", SCRIPT)
assert _spec is not None
assert _spec.loader is not None
check_issue_link = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_issue_link)


def issue(*labels: str) -> dict[str, Any]:
    return {"labels": [{"name": label} for label in labels]}


def fetcher(issues: dict[int, dict[str, Any] | None]):
    def fetch(number: int) -> dict[str, Any] | None:
        return issues.get(number)

    return fetch


APPROVED = issue("status:approved", "bug")


@pytest.mark.parametrize(
    "body",
    [
        "Closes #7",
        "closes #7",
        "Closed #7",
        "Fixes #7",
        "fixed #7",
        "Resolves #7",
        "resolved #7",
        "Refs #7",
        "Ref #7",
        "Fixes: #7",
        "Some context.\n\nCloses #7.",
        "```\nCloses #8\n```\nCloses #7",
        "`Closes #8` is the syntax.\nCloses #7",
        "```Closes #8``` inline, not a fence.\nCloses #7",
    ],
)
def test_accepts_a_reference_to_an_approved_issue(body: str) -> None:
    ok, message = check_issue_link.check(body, "someone", fetcher({7: APPROVED}))

    assert ok
    assert message == "Linked approved issues: #7"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "Related to #7",
        "See #7",
        "<!-- Closes #7 -->",
        "<!-- Closes #7",
        "```\nCloses #7\n```",
        "~~~\nCloses #7",
        "`Closes #7`",
        "Closes owner/repo#7",
        "Closes #",
        "Closes#7",
    ],
)
def test_refuses_a_body_without_a_reference(body: str) -> None:
    ok, message = check_issue_link.check(body, "someone", fetcher({7: APPROVED}))

    assert not ok
    assert "Closes #<number>" in message
    assert "Refs #<number>" in message


def test_refuses_an_issue_that_is_not_approved() -> None:
    ok, message = check_issue_link.check(
        "Closes #7", "someone", fetcher({7: issue("status:needs-review")})
    )

    assert not ok
    assert "#7 is not labelled status:approved yet" in message


def test_refuses_a_missing_issue() -> None:
    ok, message = check_issue_link.check("Closes #7", "someone", fetcher({}))

    assert not ok
    assert "#7 does not exist" in message


def test_refuses_a_pull_request_reference() -> None:
    pull = {**APPROVED, "pull_request": {"url": "x"}}

    ok, message = check_issue_link.check("Closes #7", "someone", fetcher({7: pull}))

    assert not ok
    assert "#7 is a pull request, not an issue" in message


def test_every_referenced_issue_must_be_approved() -> None:
    issues = {7: APPROVED, 8: issue()}

    ok, message = check_issue_link.check("Closes #7\nRefs #8", "someone", fetcher(issues))

    assert not ok
    problems = [line for line in message.splitlines() if line.startswith("  - ")]
    assert problems == ["  - #8 is not labelled status:approved yet"]


def test_a_repeated_reference_is_checked_once() -> None:
    calls: list[int] = []

    def fetch(number: int) -> dict[str, Any] | None:
        calls.append(number)
        return APPROVED

    ok, _ = check_issue_link.check("Closes #7\nRefs #7", "someone", fetch)

    assert ok
    assert calls == [7]


@pytest.mark.parametrize("author", ["yugen-release-docmost-mcp-bot[bot]", "dependabot[bot]"])
def test_exempts_the_release_app_and_dependabot(author: str) -> None:
    def fetch(number: int) -> dict[str, Any] | None:
        raise AssertionError("no issue is fetched for an exempt author")

    ok, message = check_issue_link.check("", author, fetch)

    assert ok
    assert author in message


@pytest.mark.parametrize("author", ["sgg10", "github-actions[bot]", "other-bot[bot]"])
def test_maintainers_and_other_bots_are_not_exempt(author: str) -> None:
    ok, _ = check_issue_link.check("", author, fetcher({}))

    assert not ok


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _urlopen(*outcomes: object):
    """urlopen answering each call with the next outcome: an issue or an exception."""
    remaining = list(outcomes)

    def urlopen(request: urllib.request.Request, timeout: float) -> _Response:
        assert request.full_url == "https://api.github.com/repos/owner/repo/issues/7"
        assert request.get_header("Authorization") == "Bearer token"
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(json.dumps(outcome).encode())

    return urlopen


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Seconds slept between attempts; the GitHub environment is set."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "token")
    slept: list[float] = []
    monkeypatch.setattr(check_issue_link.time, "sleep", slept.append)
    return slept


def _http_error(code: int, **headers: str) -> urllib.error.HTTPError:
    message = Message()
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    return urllib.error.HTTPError("url", code, "error", message, None)


def test_fetch_returns_the_issue(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen(APPROVED))

    assert check_issue_link.fetch_from_github(7) == APPROVED
    assert sleeps == []


@pytest.mark.parametrize("code", [404, 410])
def test_fetch_returns_none_for_a_missing_issue(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], code: int
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen(_http_error(code)))

    assert check_issue_link.fetch_from_github(7) is None


@pytest.mark.parametrize(
    "error",
    [
        _http_error(503),
        _http_error(429),
        _http_error(403, x_ratelimit_remaining="0"),
        urllib.error.URLError("unreachable"),
    ],
)
def test_fetch_retries_a_transient_failure(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], error: Exception
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen(error, error, APPROVED))

    assert check_issue_link.fetch_from_github(7) == APPROVED
    assert sleeps == [2, 4]


@pytest.mark.parametrize("error", [_http_error(503), urllib.error.URLError("unreachable")])
def test_fetch_fails_closed_after_three_attempts(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], error: Exception
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen(error, error, error))

    with pytest.raises(urllib.error.URLError):
        check_issue_link.fetch_from_github(7)
    assert sleeps == [2, 4]


@pytest.mark.parametrize("error", [_http_error(401), _http_error(403), _http_error(422)])
def test_fetch_fails_at_once_on_a_final_error(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], error: Exception
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen(error))

    with pytest.raises(urllib.error.HTTPError):
        check_issue_link.fetch_from_github(7)
    assert sleeps == []


def test_main_explains_a_github_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PR_BODY", "Closes #7")
    monkeypatch.setenv("PR_AUTHOR", "someone")

    def fetch(number: int) -> dict[str, Any] | None:
        raise _http_error(503)

    assert check_issue_link.main(fetch) == 1
    out = capsys.readouterr().out
    assert "Could not read the linked issues from GitHub" in out
    assert "re-run this check" in out


def test_main_exits_non_zero_and_prints_why(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PR_BODY", "no reference")
    monkeypatch.setenv("PR_AUTHOR", "someone")

    assert check_issue_link.main(fetcher({})) == 1
    assert "Closes #<number>" in capsys.readouterr().out


def test_main_exits_zero_when_linked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PR_BODY", "Closes #7")
    monkeypatch.setenv("PR_AUTHOR", "someone")

    assert check_issue_link.main(fetcher({7: APPROVED})) == 0
    assert "#7" in capsys.readouterr().out
