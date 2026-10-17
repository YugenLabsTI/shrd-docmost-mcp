"""Generic built-in prompts and team prompts loaded from DOCMOST_PROMPTS_DIR."""

from pathlib import Path
from typing import Any

import pytest
from mcp import Client, MCPError

from docmost_client import ConfigError
from yugen_docmost_mcp.prompts import (
    BUILTIN_PROMPTS,
    MAX_PROMPT_FILE_BYTES,
    MAX_PROMPT_FILES,
    load_prompt_dir,
    prompts_from_env,
)
from yugen_docmost_mcp.server import build_server

pytestmark = pytest.mark.anyio

WEEKLY = '''
name = "weekly_report"
description = "Draft the weekly report page"
template = """
Read the recent pages in {{space}} and draft ...
"""
[[arguments]]
name = "space"
required = true
'''


class FakeWiki:
    """Prompts never call the reader; listing and rendering them needs no Docmost."""


READER: Any = FakeWiki()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


async def get_prompt(prompts: Any, name: str, **arguments: str) -> str:
    async with Client(build_server(READER, writer=None, prompts=prompts)) as client:
        result = await client.get_prompt(name, arguments)
    return result.messages[0].content.text  # type: ignore[union-attr]


# --- built-in prompts --------------------------------------------------------------


async def test_builtin_prompts_are_listed_by_default() -> None:
    async with Client(build_server(READER, writer=None)) as client:
        prompts = {p.name: p for p in (await client.list_prompts()).prompts}

    assert set(prompts) == {"summarize_page", "answer_from_wiki"}
    answer = prompts["answer_from_wiki"].arguments or []
    assert [(a.name, a.required) for a in answer] == [("question", True), ("space", False)]


async def test_summarize_page_points_the_agent_at_the_page() -> None:
    text = await get_prompt(BUILTIN_PROMPTS, "summarize_page", page_id="abc123xyz0")

    assert "abc123xyz0" in text
    assert "get_page" in text


@pytest.mark.parametrize(
    ("arguments", "scope"),
    [({}, "all the spaces you can access"), ({"space": "engineering"}, "engineering")],
)
async def test_answer_from_wiki_searches_the_given_space_or_all(
    arguments: dict[str, str], scope: str
) -> None:
    text = await get_prompt(
        BUILTIN_PROMPTS, "answer_from_wiki", question="How do we deploy?", **arguments
    )

    assert "How do we deploy?" in text
    assert f"Spaces to search: {scope}" in text
    assert "search" in text
    assert "cite" in text


async def test_a_missing_required_argument_is_an_error() -> None:
    async with Client(build_server(READER, writer=None)) as client:
        with pytest.raises(MCPError, match="page_id") as exc:
            await client.get_prompt("summarize_page", {})

    assert exc.value.code == -32602


async def test_a_server_without_prompts_lists_none() -> None:
    async with Client(build_server(READER, writer=None, prompts=())) as client:
        assert (await client.list_prompts()).prompts == []


@pytest.mark.parametrize(("raw", "expected"), [(None, 2), ("1", 2), ("0", 0), ("false", 0)])
def test_builtin_prompts_flag(raw: str | None, expected: int) -> None:
    environ = {} if raw is None else {"DOCMOST_BUILTIN_PROMPTS": raw}

    assert len(prompts_from_env(environ)) == expected


def test_an_invalid_builtin_prompts_flag_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="DOCMOST_BUILTIN_PROMPTS"):
        prompts_from_env({"DOCMOST_BUILTIN_PROMPTS": "maybe"})


# --- prompt files ------------------------------------------------------------------


async def test_a_prompt_file_becomes_a_prompt(tmp_path: Path) -> None:
    write(tmp_path, "weekly.toml", WEEKLY)

    prompts = load_prompt_dir(tmp_path)
    async with Client(build_server(READER, writer=None, prompts=prompts)) as client:
        listed = (await client.list_prompts()).prompts
        result = await client.get_prompt("weekly_report", {"space": "engineering"})

    assert [(p.name, p.description) for p in listed] == [
        ("weekly_report", "Draft the weekly report page")
    ]
    assert [(a.name, a.required) for a in listed[0].arguments or []] == [("space", True)]
    text = result.messages[0].content.text  # type: ignore[union-attr]
    assert text.strip() == "Read the recent pages in engineering and draft ..."


def test_prompts_from_env_adds_files_after_the_builtins(tmp_path: Path) -> None:
    write(tmp_path, "weekly.toml", WEEKLY)

    names = [p.name for p in prompts_from_env({"DOCMOST_PROMPTS_DIR": str(tmp_path)})]

    assert names == ["summarize_page", "answer_from_wiki", "weekly_report"]


async def test_argument_values_are_inserted_verbatim_and_never_expanded(tmp_path: Path) -> None:
    write(
        tmp_path,
        "two.toml",
        'name = "two"\ntemplate = "A={{a}} B={{ b }}"\n'
        '[[arguments]]\nname = "a"\n[[arguments]]\nname = "b"\ndefault = "none"\n',
    )

    text = await get_prompt(load_prompt_dir(tmp_path), "two", a="{{b}} {0} %s ${x}")

    assert text == "A={{b}} {0} %s ${x} B=none"


async def test_undeclared_arguments_sent_by_a_client_are_ignored(tmp_path: Path) -> None:
    write(tmp_path, "weekly.toml", WEEKLY)

    text = await get_prompt(load_prompt_dir(tmp_path), "weekly_report", space="ops", extra="x")

    assert "ops" in text
    assert "x" not in text.replace("ops", "")


def test_only_toml_files_at_the_top_level_are_loaded(tmp_path: Path) -> None:
    write(tmp_path, "weekly.toml", WEEKLY)
    write(tmp_path, "notes.md", "not a prompt")
    (tmp_path / "nested").mkdir()
    write(tmp_path / "nested", "other.toml", WEEKLY.replace("weekly_report", "other"))

    assert [p.name for p in load_prompt_dir(tmp_path)] == ["weekly_report"]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("name = ", "TOML"),
        ('template = "x"', "name"),
        ('name = "x"', "template"),
        ('name = "x"\ntemplate = "   "', "template"),
        ('name = "Bad Name"\ntemplate = "x"', "name"),
        ('name = "x"\ntemplate = "x"\ncolor = "red"', "color"),
        ('name = "x"\ntemplate = "{{who}}"', "who"),
        ('name = "x"\ntemplate = "x"\n[[arguments]]\nname = "1st"', "argument"),
        ('name = "x"\ntemplate = "x"\n[[arguments]]\nname = "a"\nrequired = "yes"', "required"),
        ('name = "x"\ntemplate = "x"\n[[arguments]]\nname = "a"\n[[arguments]]\nname = "a"', "a"),
        ('name = "x"\ntemplate = "x"\n[[arguments]]\nname = "a"\nrequired = true\ndefault = "d"',
         "default"),
        ('name = 3\ntemplate = "x"', "name"),
    ],
)  # fmt: skip
def test_invalid_prompt_files_stop_startup_with_a_clear_error(
    tmp_path: Path, text: str, reason: str
) -> None:
    write(tmp_path, "bad.toml", text)

    with pytest.raises(ConfigError, match=reason) as exc:
        load_prompt_dir(tmp_path)

    assert "bad.toml" in str(exc.value)


def test_errors_never_include_the_template(tmp_path: Path) -> None:
    write(tmp_path, "bad.toml", 'name = "x"\ntemplate = "secret plan {{who}}"')

    with pytest.raises(ConfigError) as exc:
        load_prompt_dir(tmp_path)

    assert "secret plan" not in str(exc.value)


def test_duplicate_prompt_names_are_refused(tmp_path: Path) -> None:
    write(tmp_path, "a.toml", WEEKLY)
    write(tmp_path, "b.toml", WEEKLY)

    with pytest.raises(ConfigError, match="weekly_report"):
        load_prompt_dir(tmp_path)


def test_a_file_cannot_replace_a_builtin_prompt(tmp_path: Path) -> None:
    write(tmp_path, "mine.toml", 'name = "summarize_page"\ntemplate = "x"')

    with pytest.raises(ConfigError, match="summarize_page"):
        prompts_from_env({"DOCMOST_PROMPTS_DIR": str(tmp_path)})
    names = prompts_from_env({"DOCMOST_PROMPTS_DIR": str(tmp_path), "DOCMOST_BUILTIN_PROMPTS": "0"})
    assert [p.name for p in names] == ["summarize_page"]


def test_oversized_prompt_files_are_refused(tmp_path: Path) -> None:
    write(tmp_path, "big.toml", 'name = "x"\ntemplate = "' + "a" * MAX_PROMPT_FILE_BYTES + '"')

    with pytest.raises(ConfigError, match=r"big\.toml"):
        load_prompt_dir(tmp_path)


def test_too_many_prompt_files_are_refused(tmp_path: Path) -> None:
    for n in range(MAX_PROMPT_FILES + 1):
        write(tmp_path, f"p{n}.toml", f'name = "p{n}"\ntemplate = "x"')

    with pytest.raises(ConfigError, match=str(MAX_PROMPT_FILES)):
        load_prompt_dir(tmp_path)


@pytest.mark.parametrize("kind", ["missing", "file", "empty"])
def test_prompts_dir_must_be_a_readable_directory(tmp_path: Path, kind: str) -> None:
    target = {"missing": tmp_path / "nope", "file": write(tmp_path, "f.toml", WEEKLY)}.get(kind)
    environ = {"DOCMOST_PROMPTS_DIR": "" if target is None else str(target)}

    if kind == "empty":
        assert len(prompts_from_env(environ)) == len(BUILTIN_PROMPTS)
        return
    with pytest.raises(ConfigError, match="DOCMOST_PROMPTS_DIR"):
        prompts_from_env(environ)


def test_the_builtin_prompts_are_valid_prompt_definitions() -> None:
    # Built-ins go through the same validation as files.
    assert [p.name for p in BUILTIN_PROMPTS] == ["summarize_page", "answer_from_wiki"]
