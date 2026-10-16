from pathlib import Path

import pytest

from docmost_client import ConfigError, DocmostSettings

SECRET = "s3cr3t-Pa55word!"


def env(**overrides: str) -> dict[str, str]:
    base = {
        "DOCMOST_BASE_URL": "https://wiki.example.com",
        "DOCMOST_EMAIL": "bot@example.com",
        "DOCMOST_PASSWORD": SECRET,
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v != "<unset>"}


def test_minimal_env_is_secure_by_default() -> None:
    settings = DocmostSettings.from_env(env())

    assert settings.base_url == "https://wiki.example.com"
    assert settings.email == "bot@example.com"
    assert settings.password.get_secret_value() == SECRET
    assert settings.read_only is True
    assert settings.allowed_spaces is None
    assert settings.allow_insecure_http is False
    assert settings.timeout_seconds == 30.0
    assert settings.max_content_bytes == 1_000_000


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://wiki.example.com/", "https://wiki.example.com"),
        ("https://wiki.example.com/docmost/", "https://wiki.example.com/docmost"),
        ("HTTPS://Wiki.Example.com", "https://wiki.example.com"),
    ],
)
def test_base_url_is_normalized(raw: str, expected: str) -> None:
    assert DocmostSettings.from_env(env(DOCMOST_BASE_URL=raw)).base_url == expected


def test_http_base_url_is_rejected_without_explicit_opt_in() -> None:
    with pytest.raises(ConfigError, match="DOCMOST_ALLOW_INSECURE_HTTP") as exc:
        DocmostSettings.from_env(env(DOCMOST_BASE_URL="http://localhost:3000"))

    assert exc.value.code == "INVALID_CONFIG"


def test_http_base_url_is_allowed_with_explicit_opt_in() -> None:
    settings = DocmostSettings.from_env(
        env(DOCMOST_BASE_URL="http://localhost:3000", DOCMOST_ALLOW_INSECURE_HTTP="1")
    )

    assert settings.base_url == "http://localhost:3000"
    assert settings.allow_insecure_http is True


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://wiki.example.com",
        "wiki.example.com",
        "https://",
        "https://user:pass@wiki.example.com",
        "https://wiki.example.com?x=1",
        "https://wiki.example.com#frag",
    ],
)
def test_malformed_or_unsafe_base_urls_are_rejected(raw: str) -> None:
    with pytest.raises(ConfigError, match="DOCMOST_BASE_URL"):
        DocmostSettings.from_env(env(DOCMOST_BASE_URL=raw, DOCMOST_ALLOW_INSECURE_HTTP="1"))


@pytest.mark.parametrize("missing", ["DOCMOST_BASE_URL", "DOCMOST_EMAIL", "DOCMOST_PASSWORD"])
def test_missing_required_variable_is_named(missing: str) -> None:
    with pytest.raises(ConfigError, match=missing):
        DocmostSettings.from_env(env(**{missing: "<unset>"}))


def test_secrets_can_be_read_from_files(tmp_path: Path) -> None:
    password_file = tmp_path / "password"
    password_file.write_text(SECRET + "\n")
    email_file = tmp_path / "email"
    email_file.write_text("bot@example.com\n")

    settings = DocmostSettings.from_env(
        env(
            DOCMOST_PASSWORD="<unset>",
            DOCMOST_EMAIL="<unset>",
            DOCMOST_PASSWORD_FILE=str(password_file),
            DOCMOST_EMAIL_FILE=str(email_file),
        )
    )

    assert settings.password.get_secret_value() == SECRET
    assert settings.email == "bot@example.com"


def test_value_and_file_variants_together_are_ambiguous(tmp_path: Path) -> None:
    password_file = tmp_path / "password"
    password_file.write_text(SECRET)

    with pytest.raises(ConfigError, match="DOCMOST_PASSWORD_FILE"):
        DocmostSettings.from_env(env(DOCMOST_PASSWORD_FILE=str(password_file)))


def test_unreadable_secret_file_is_reported_without_content(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="DOCMOST_PASSWORD_FILE"):
        DocmostSettings.from_env(
            env(DOCMOST_PASSWORD="<unset>", DOCMOST_PASSWORD_FILE=str(tmp_path / "missing"))
        )


def test_empty_secret_file_is_rejected(tmp_path: Path) -> None:
    password_file = tmp_path / "password"
    password_file.write_text("\n")

    with pytest.raises(ConfigError, match="DOCMOST_PASSWORD_FILE"):
        DocmostSettings.from_env(
            env(DOCMOST_PASSWORD="<unset>", DOCMOST_PASSWORD_FILE=str(password_file))
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", False), ("false", False), ("No", False), ("1", True), ("TRUE", True), ("yes", True)],
)
def test_read_only_flag_parsing(raw: str, expected: bool) -> None:
    assert DocmostSettings.from_env(env(DOCMOST_READ_ONLY=raw)).read_only is expected


def test_invalid_boolean_is_rejected() -> None:
    with pytest.raises(ConfigError, match="DOCMOST_READ_ONLY"):
        DocmostSettings.from_env(env(DOCMOST_READ_ONLY="maybe"))


def test_allowed_spaces_are_parsed_as_a_set() -> None:
    settings = DocmostSettings.from_env(env(DOCMOST_ALLOWED_SPACES=" eng, ops ,,eng "))

    assert settings.allowed_spaces == frozenset({"eng", "ops"})


@pytest.mark.parametrize("raw", ["", " , "])
def test_empty_allowlist_fails_closed(raw: str) -> None:
    with pytest.raises(ConfigError, match="DOCMOST_ALLOWED_SPACES"):
        DocmostSettings.from_env(env(DOCMOST_ALLOWED_SPACES=raw))


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("DOCMOST_TIMEOUT_SECONDS", "0"),
        ("DOCMOST_TIMEOUT_SECONDS", "abc"),
        ("DOCMOST_MAX_CONTENT_BYTES", "-1"),
        ("DOCMOST_MAX_CONTENT_BYTES", "1.5"),
    ],
)
def test_invalid_numbers_are_rejected(name: str, raw: str) -> None:
    with pytest.raises(ConfigError, match=name):
        DocmostSettings.from_env(env(**{name: raw}))


def test_numbers_are_parsed() -> None:
    settings = DocmostSettings.from_env(
        env(DOCMOST_TIMEOUT_SECONDS="5.5", DOCMOST_MAX_CONTENT_BYTES="2048")
    )

    assert settings.timeout_seconds == 5.5
    assert settings.max_content_bytes == 2048


def test_password_never_appears_in_repr_or_str() -> None:
    settings = DocmostSettings.from_env(env())

    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)
    assert SECRET not in str(settings.model_dump())


def test_config_errors_never_echo_the_password() -> None:
    with pytest.raises(ConfigError) as exc:
        DocmostSettings.from_env(env(DOCMOST_READ_ONLY=SECRET))

    assert SECRET not in str(exc.value)


def test_settings_are_immutable() -> None:
    settings = DocmostSettings.from_env(env())

    with pytest.raises(ValueError, match="frozen"):
        settings.read_only = False  # type: ignore[misc]


def test_reads_process_environment_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in env().items():
        monkeypatch.setenv(key, value)

    assert DocmostSettings.from_env().email == "bot@example.com"
