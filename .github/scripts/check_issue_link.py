"""Fail a pull request that does not link an issue labelled ``status:approved``.

Runs from the default branch (workflow ``issue-link.yml``), never from the pull
request's code. Reads ``PR_BODY`` and ``PR_AUTHOR``; looks the issues up with ``GH_TOKEN`` in
``GITHUB_REPOSITORY``. Standard library only, so the runner needs no install.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

APPROVED = "status:approved"
# Accounts whose pull requests need no issue: the release App and Dependabot.
EXEMPT_AUTHORS = frozenset({"yugen-release-docmost-mcp-bot[bot]", "dependabot[bot]"})
# GitHub's closing keywords plus "Ref"/"Refs" for a link that keeps the issue open. A
# reference to another repository (owner/repo#N) does not match.
REFERENCE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?):?\s+#(\d+)\b", re.IGNORECASE
)
# Text that does not count: HTML comments (also one left open), fenced code blocks and
# inline code, where GitHub does not link issues either.
IGNORED = re.compile(
    r"<!--.*?(?:-->|\Z)|^ {0,3}(```|~~~).*?(?:^ {0,3}\1|\Z)|`[^`\n]*`", re.DOTALL | re.MULTILINE
)
HOW_TO_LINK = (
    "Link the issue this pull request implements in its description, with one of:\n"
    "  Closes #<number>   (closes the issue on merge; also Fixes or Resolves)\n"
    "  Refs #<number>     (links it without closing it)\n"
    "References inside HTML comments or code do not count. A maintainer labels the issue "
    f"{APPROVED} once it is accepted; then re-run this check."
)

Issue = dict[str, Any]
Fetch = Callable[[int], Issue | None]


def linked_issues(body: str) -> list[int]:
    """Issue numbers the body references, in order, without repeats."""
    numbers = (int(match) for match in REFERENCE.findall(IGNORED.sub("", body)))
    return list(dict.fromkeys(numbers))


def check(body: str, author: str, fetch: Fetch) -> tuple[bool, str]:
    """Whether the pull request may be merged, and the reason to show."""
    if author in EXEMPT_AUTHORS:
        return True, f"Opened by {author}; no issue needed."
    numbers = linked_issues(body)
    if not numbers:
        return False, f"This pull request links no issue.\n{HOW_TO_LINK}"
    problems: list[str] = []
    for number in numbers:
        issue = fetch(number)
        if issue is None:
            problems.append(f"#{number} does not exist")
        elif "pull_request" in issue:
            problems.append(f"#{number} is a pull request, not an issue")
        elif APPROVED not in {label["name"] for label in issue.get("labels", [])}:
            problems.append(f"#{number} is not labelled {APPROVED} yet")
    if problems:
        return False, "Linked issues not ready:\n" + "\n".join(
            f"  - {problem}" for problem in problems
        ) + f"\n{HOW_TO_LINK}"
    return True, "Linked approved issues: " + ", ".join(f"#{number}" for number in numbers)


def fetch_from_github(number: int) -> Issue | None:
    """The issue (or pull request) with this number; None when there is none."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/issues/{number}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        # Fixed https URL to the GitHub API.
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (404, 410):
            return None
        raise


def main(fetch: Fetch = fetch_from_github) -> int:
    ok, message = check(os.environ.get("PR_BODY", ""), os.environ["PR_AUTHOR"], fetch)
    sys.stdout.write(message + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
