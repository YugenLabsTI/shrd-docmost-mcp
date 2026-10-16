"""Create, then validate, the environment file for the live smoke test.

    uv run python dev/live/init_env.py           # writes dev/live/.env.live (git-ignored)
    uv run python dev/live/init_env.py --check   # validates it after you fill it in

The file never holds the password: it points to a separate password file outside the
repository, which this script creates empty with owner-only permissions. --check loads
the settings the same way the server does and contacts nothing.
"""

import argparse
import contextlib
import os
import shlex
import sys
from pathlib import Path

from docmost_client import ConfigError, DocmostSettings

ENV_FILE = Path(__file__).parent / ".env.live"
PASSWORD_FILE = Path.home() / ".config" / "yugen-docmost-mcp" / "live-password"
TEST_VARIABLES = ("DOCMOST_LIVE_READ_SPACE", "DOCMOST_LIVE_SANDBOX_SPACE")

TEMPLATE = """\
# Live smoke test against the real Docmost instance. Fill in every empty value.
# This file is git-ignored. Never put the password here: it goes in the password file.

# Instance URL, e.g. https://wiki.example.com (https only).
DOCMOST_BASE_URL=

# Dedicated agent account: password login, no MFA, no SSO.
DOCMOST_EMAIL=

# File that contains only the account password. Created empty by this script.
DOCMOST_PASSWORD_FILE={password_file}

# Space the account can READ (role: reader). Slug or ID.
DOCMOST_LIVE_READ_SPACE=

# Sandbox space created for this test, the only one it may WRITE to (role: writer).
DOCMOST_LIVE_SANDBOX_SPACE=

# Leave as is: writes stay disabled unless a test enables them for the sandbox, and the
# allowlist must list exactly the two spaces above (comma-separated).
DOCMOST_READ_ONLY=1
DOCMOST_ALLOWED_SPACES=
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="validate the filled-in file")
    args = parser.parse_args()
    if args.check:
        sys.exit(check())
    create()


def create() -> None:
    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        _write_private(ENV_FILE, TEMPLATE.format(password_file=PASSWORD_FILE))
    except FileExistsError:
        sys.exit(f"{_relative(ENV_FILE)} already exists; edit it or delete it first.")
    with contextlib.suppress(FileExistsError):  # keep a password the user already wrote
        _write_private(PASSWORD_FILE, "")
    print(f"Created {_relative(ENV_FILE)} and the empty password file {PASSWORD_FILE}.")
    print("Fill in both, then run: uv run python dev/live/init_env.py --check")


def check() -> int:
    if not ENV_FILE.exists():
        print(f"{_relative(ENV_FILE)} does not exist; run this script without --check first.")
        return 1
    env = _parse(ENV_FILE.read_text())
    problems = [f"{name} is empty" for name in TEST_VARIABLES if not env.get(name)]
    read_space, sandbox = (env.get(name, "").lower() for name in TEST_VARIABLES)
    if read_space and read_space == sandbox:
        problems.append(
            "DOCMOST_LIVE_READ_SPACE and DOCMOST_LIVE_SANDBOX_SPACE must be different spaces"
        )
    try:
        settings = DocmostSettings.from_env(env)
    except ConfigError as exc:
        problems.append(str(exc))
    else:
        if settings.allow_insecure_http:
            problems.append("DOCMOST_ALLOW_INSECURE_HTTP must not be set for the live test")
        if not settings.read_only:
            problems.append("DOCMOST_READ_ONLY must stay 1; the test enables writes itself")
        expected = {env.get(name, "").lower() for name in TEST_VARIABLES}
        if (
            settings.allowed_spaces is None
            or {s.lower() for s in settings.allowed_spaces} != expected
        ):
            problems.append(
                "DOCMOST_ALLOWED_SPACES must list exactly DOCMOST_LIVE_READ_SPACE and "
                "DOCMOST_LIVE_SANDBOX_SPACE"
            )
    password = Path(env.get("DOCMOST_PASSWORD_FILE", ""))
    if password.is_file() and password.stat().st_mode & 0o077:
        problems.append(f"{password} is readable by other users; run: chmod 600 {password}")
    if problems:
        print("Not ready:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Ready: the settings load and the allowlist matches the two test spaces.")
    return 0


def _parse(text: str) -> dict[str, str]:
    """Read KEY=VALUE lines the way a POSIX shell sourcing the file would."""
    env: dict[str, str] = {}
    for line in text.splitlines():
        try:
            words = shlex.split(line, comments=True)
        except ValueError:
            continue  # unbalanced quotes: the shell would fail too
        if words and words[0] == "export":
            words = words[1:]
        if len(words) == 1 and "=" in words[0]:
            key, value = words[0].split("=", 1)
            env[key] = value
    return env


def _write_private(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(content)


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
