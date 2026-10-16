"""The offline gate in init_env.py that must pass before any live test runs."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

GOOD = {
    "DOCMOST_BASE_URL": "https://wiki.example.com",
    "DOCMOST_EMAIL": "agent@example.com",
    "DOCMOST_LIVE_READ_SPACE": "engineering",
    "DOCMOST_LIVE_SANDBOX_SPACE": "mcp-sandbox",
    "DOCMOST_READ_ONLY": "1",
    "DOCMOST_ALLOWED_SPACES": "engineering,mcp-sandbox",
}


@pytest.fixture
def module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "init_env", Path(__file__).with_name("init_env.py")
    )
    assert spec is not None
    assert spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    monkeypatch.setattr(loaded, "ENV_FILE", tmp_path / ".env.live")
    monkeypatch.setattr(loaded, "PASSWORD_FILE", tmp_path / "home" / "live-password")
    return loaded


def write(module: ModuleType, password: str | None = "secret", **overrides: str) -> None:
    password_file: Path = module.PASSWORD_FILE
    password_file.parent.mkdir(parents=True, exist_ok=True)
    if password is not None:
        password_file.write_text(password)
        password_file.chmod(0o600)
    values = GOOD | {"DOCMOST_PASSWORD_FILE": str(password_file)} | overrides
    module.ENV_FILE.write_text("".join(f"{k}={v}\n" for k, v in values.items()))


def check(module: ModuleType, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = module.check()
    return code, capsys.readouterr().out


def test_complete_file_is_ready(module: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    write(module)

    assert check(module, capsys) == (
        0,
        "Ready: the settings load and the allowlist matches the two test spaces.\n",
    )


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [
        ({"DOCMOST_LIVE_READ_SPACE": ""}, "DOCMOST_LIVE_READ_SPACE is empty"),
        ({"DOCMOST_ALLOW_INSECURE_HTTP": "1"}, "DOCMOST_ALLOW_INSECURE_HTTP"),
        ({"DOCMOST_READ_ONLY": "0"}, "DOCMOST_READ_ONLY must stay 1"),
        ({"DOCMOST_ALLOWED_SPACES": "engineering"}, "must list exactly"),
        ({"DOCMOST_BASE_URL": "http://wiki.example.com"}, "DOCMOST_BASE_URL"),
        (
            {
                "DOCMOST_LIVE_SANDBOX_SPACE": "Engineering",
                "DOCMOST_ALLOWED_SPACES": "engineering",
            },
            "must be different spaces",
        ),
    ],
)
def test_unsafe_or_incomplete_files_are_refused(
    module: ModuleType,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, str],
    problem: str,
) -> None:
    write(module, **overrides)

    code, out = check(module, capsys)

    assert code == 1
    assert problem in out


@pytest.mark.parametrize(("password", "problem"), [("", "empty file"), (None, "cannot be read")])
def test_missing_or_empty_password_is_refused(
    module: ModuleType, capsys: pytest.CaptureFixture[str], password: str | None, problem: str
) -> None:
    write(module, password=password)

    code, out = check(module, capsys)

    assert code == 1
    assert problem in out


def test_password_readable_by_others_is_refused(
    module: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    write(module)
    module.PASSWORD_FILE.chmod(0o644)

    code, out = check(module, capsys)

    assert code == 1
    assert "chmod 600" in out


def test_values_are_read_as_a_shell_would(
    module: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    write(module)
    text = module.ENV_FILE.read_text()
    text = text.replace(
        "DOCMOST_BASE_URL=https://wiki.example.com",
        'export DOCMOST_BASE_URL="https://wiki.example.com"',
    ).replace("DOCMOST_READ_ONLY=1", "DOCMOST_READ_ONLY=1  # keep")
    module.ENV_FILE.write_text(text)

    assert check(module, capsys)[0] == 0


def test_create_never_overwrites(module: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    module.create()
    capsys.readouterr()

    with pytest.raises(SystemExit, match="already exists"):
        module.create()


def test_create_writes_owner_only_files(module: ModuleType) -> None:
    module.create()

    assert module.ENV_FILE.stat().st_mode & 0o777 == 0o600
    assert module.PASSWORD_FILE.stat().st_mode & 0o777 == 0o600
    assert module.PASSWORD_FILE.read_text() == ""
