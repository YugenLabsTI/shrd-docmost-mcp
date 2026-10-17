"""MCP prompts: two generic built-ins and team prompts loaded from TOML files.

Team workflows live in configuration, not in this server: DOCMOST_PROMPTS_DIR names a
directory with one ``.toml`` file per prompt::

    name = "weekly_report"
    description = "Draft the weekly report page"
    template = \"\"\"
    Read the recent pages in {{space}} and draft ...
    \"\"\"
    [[arguments]]
    name = "space"
    required = true

Templates only substitute ``{{argument}}`` placeholders of declared arguments, in a
single pass, so argument values are inserted verbatim and nothing is evaluated. Files
are validated at startup; errors name the file, never its template.
"""

import os
import re
import tomllib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from mcp import MCPError
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.prompts.base import Message, Prompt, PromptArgument
from mcp_types.jsonrpc import INVALID_PARAMS

from docmost_client import ConfigError
from docmost_client.settings import env_flag

MAX_PROMPT_FILES = 100
MAX_PROMPT_FILE_BYTES = 64 * 1024
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_ARGUMENT = re.compile(r"[a-z_][a-z0-9_]{0,63}")
_PLACEHOLDER = re.compile(r"\{\{\s*([^{}\s]*)\s*\}\}")
_POSITION = re.compile(r"\(at line \d+, column \d+\)")
_FILE_KEYS = frozenset({"name", "title", "description", "template", "arguments"})
_ARGUMENT_KEYS = frozenset({"name", "description", "required", "default"})


@dataclass(frozen=True)
class PromptArgumentSpec:
    name: str
    description: str | None = None
    required: bool = False
    default: str | None = None


@dataclass(frozen=True)
class PromptSpec:
    """A validated prompt: metadata plus a ``{{argument}}`` template."""

    name: str
    template: str
    title: str | None = None
    description: str | None = None
    arguments: tuple[PromptArgumentSpec, ...] = ()

    def render(self, values: Mapping[str, object]) -> str:
        declared = {argument.name: argument for argument in self.arguments}

        def fill(match: re.Match[str]) -> str:
            argument = declared[match.group(1)]
            value = values.get(argument.name)
            if isinstance(value, str) and value:
                return value
            return argument.default or ""

        return _PLACEHOLDER.sub(fill, self.template)


def parse_prompt(data: Mapping[str, Any], source: str) -> PromptSpec:
    """Validate one prompt definition; ``source`` labels errors (a file name)."""

    def fail(reason: str) -> ConfigError:
        return ConfigError(f"Prompt file {source}: {reason}")

    unknown = sorted(set(data) - _FILE_KEYS)
    if unknown:
        raise fail(f"unknown key {unknown[0]!r}; allowed keys: {', '.join(sorted(_FILE_KEYS))}.")
    name = data.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise fail("name must be a string of lowercase letters, digits, '_' or '-'.")
    template = data.get("template")
    if not isinstance(template, str) or not template.strip():
        raise fail("template must be a non-empty string.")
    title, description = data.get("title"), data.get("description")
    if title is not None and not isinstance(title, str):
        raise fail("title must be a string.")
    if description is not None and not isinstance(description, str):
        raise fail("description must be a string.")

    raw_arguments = data.get("arguments", [])
    if not isinstance(raw_arguments, list):
        raise fail("arguments must be a list of [[arguments]] tables.")
    arguments: list[PromptArgumentSpec] = []
    for raw in cast(list[object], raw_arguments):
        argument = _parse_argument(raw, fail)
        if any(existing.name == argument.name for existing in arguments):
            raise fail(f"argument {argument.name!r} is declared twice.")
        arguments.append(argument)

    declared = {argument.name for argument in arguments}
    for placeholder in _PLACEHOLDER.findall(template):
        if placeholder not in declared:
            shown = repr(placeholder) if _ARGUMENT.fullmatch(placeholder) else "a placeholder"
            raise fail(f"template uses {shown}, which is not a declared argument.")
    return PromptSpec(
        name=name,
        template=template,
        title=title,
        description=description,
        arguments=tuple(arguments),
    )


def _parse_argument(raw: object, fail: Callable[[str], ConfigError]) -> PromptArgumentSpec:
    if not isinstance(raw, dict):
        raise fail("each argument must be a [[arguments]] table.")
    values = cast(dict[str, Any], raw)
    unknown = sorted(set(values) - _ARGUMENT_KEYS)
    if unknown:
        raise fail(f"unknown argument key {unknown[0]!r}.")
    name = values.get("name")
    if not isinstance(name, str) or not _ARGUMENT.fullmatch(name):
        raise fail(
            "argument name must be lowercase letters, digits or '_', not starting with a digit."
        )
    required = values.get("required", False)
    if not isinstance(required, bool):
        raise fail(f"argument {name!r}: required must be true or false.")
    description, default = values.get("description"), values.get("default")
    if description is not None and not isinstance(description, str):
        raise fail(f"argument {name!r}: description must be a string.")
    if default is not None and not isinstance(default, str):
        raise fail(f"argument {name!r}: default must be a string.")
    if default is not None and required:
        raise fail(f"argument {name!r}: a default is only allowed for optional arguments.")
    return PromptArgumentSpec(
        name=name, description=description, required=required, default=default
    )


def load_prompt_dir(directory: Path) -> list[PromptSpec]:
    """Load every ``*.toml`` file directly inside ``directory`` (sorted by file name)."""
    try:
        files = sorted(
            path for path in directory.iterdir() if path.suffix == ".toml" and path.is_file()
        )
    except OSError:
        raise ConfigError("DOCMOST_PROMPTS_DIR cannot be read.") from None
    if len(files) > MAX_PROMPT_FILES:
        raise ConfigError(f"DOCMOST_PROMPTS_DIR holds more than {MAX_PROMPT_FILES} prompt files.")
    prompts: list[PromptSpec] = []
    for path in files:
        prompt = parse_prompt(_read_toml(path), path.name)
        if any(existing.name == prompt.name for existing in prompts):
            raise ConfigError(
                f"Prompt file {path.name}: the prompt name {prompt.name!r} is already defined "
                "by another file."
            )
        prompts.append(prompt)
    return prompts


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_PROMPT_FILE_BYTES + 1)
    except OSError:
        raise ConfigError(f"Prompt file {path.name}: cannot be read.") from None
    if len(raw) > MAX_PROMPT_FILE_BYTES:
        raise ConfigError(f"Prompt file {path.name}: is larger than {MAX_PROMPT_FILE_BYTES} bytes.")
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ConfigError(f"Prompt file {path.name}: is not valid UTF-8.") from None
    except tomllib.TOMLDecodeError as exc:
        # Keep only the position: some decoder messages quote keys from the file.
        position = _POSITION.search(str(exc))
        where = f" {position.group(0)}" if position else ""
        raise ConfigError(f"Prompt file {path.name}: is not valid TOML{where}.") from None


BUILTIN_PROMPTS: tuple[PromptSpec, ...] = (
    parse_prompt(
        {
            "name": "summarize_page",
            "title": "Summarize a Docmost page",
            "description": "Read one page and summarize it, without changing it.",
            "template": (
                "Summarize the Docmost page {{page_id}}.\n\n"
                "Read it with the get_page tool (markdown is enough unless the page relies on "
                "tables, diagrams or colors; then read it as html). Start with a two- or "
                "three-sentence summary, then list the key points, and end with any open "
                "questions or decisions the page records. Do not change the page."
            ),
            "arguments": [
                {"name": "page_id", "description": "Page UUID or slug id.", "required": True}
            ],
        },
        "built-in",
    ),
    parse_prompt(
        {
            "name": "answer_from_wiki",
            "title": "Answer a question from the wiki",
            "description": "Search the wiki, read the relevant pages and answer with citations.",
            "template": (
                "Answer this question using the Docmost wiki.\n\n"
                "Question: {{question}}\n"
                "Spaces to search: {{space}}\n\n"
                "Use the search tool, then read the most relevant pages with get_page. Base "
                "the answer only on what those pages say, cite each page you used by title "
                "and slug id, and say plainly if the wiki does not answer the question. Do "
                "not change any page."
            ),
            "arguments": [
                {"name": "question", "description": "What to answer.", "required": True},
                {
                    "name": "space",
                    "description": "Limit the search to one space (slug or id).",
                    "default": "all the spaces you can access",
                },
            ],
        },
        "built-in",
    ),
)


def prompts_from_env(environ: Mapping[str, str] | None = None) -> list[PromptSpec]:
    """DOCMOST_BUILTIN_PROMPTS (default true) and DOCMOST_PROMPTS_DIR (optional)."""
    env = os.environ if environ is None else environ
    prompts = (
        list(BUILTIN_PROMPTS) if env_flag(env, "DOCMOST_BUILTIN_PROMPTS", default=True) else []
    )
    raw = env.get("DOCMOST_PROMPTS_DIR", "").strip()
    if not raw:
        return prompts
    directory = Path(raw)
    if not directory.is_dir():
        raise ConfigError("DOCMOST_PROMPTS_DIR must be a directory of .toml prompt files.")
    names = {prompt.name for prompt in prompts}
    for prompt in load_prompt_dir(directory):
        if prompt.name in names:
            raise ConfigError(
                f"The prompt {prompt.name!r} in DOCMOST_PROMPTS_DIR has the name of a built-in "
                "prompt; rename it, or set DOCMOST_BUILTIN_PROMPTS=0 to replace the built-ins."
            )
        prompts.append(prompt)
    return prompts


class _FilePrompt(Prompt):
    async def render(  # type: ignore[override]
        self, arguments: dict[str, Any] | None, context: Context[Any, Any]
    ) -> Any:
        # The SDK hides its own "missing argument" error behind "Internal server error";
        # report it as invalid parameters, naming the arguments.
        missing = sorted(
            argument.name
            for argument in self.arguments or []
            if argument.required and not (arguments or {}).get(argument.name)
        )
        if missing:
            raise MCPError(
                INVALID_PARAMS, f"Prompt {self.name!r} needs the argument(s): {', '.join(missing)}."
            )
        return cast(list[Message], await super().render(arguments, context))


def register_prompts(server: MCPServer[Any], prompts: Sequence[PromptSpec]) -> None:
    for spec in prompts:
        server.add_prompt(
            _FilePrompt(
                name=spec.name,
                title=spec.title,
                description=spec.description,
                arguments=[
                    PromptArgument(
                        name=argument.name,
                        description=argument.description,
                        required=argument.required,
                    )
                    for argument in spec.arguments
                ],
                fn=_renderer(spec),
                context_kwarg=None,
            )
        )


def _renderer(spec: PromptSpec) -> Callable[..., Awaitable[str]]:
    # Arguments arrive as keyword arguments, including any the client made up; only
    # declared ones reach the template.
    async def render(**values: object) -> str:
        return spec.render(values)

    return render
