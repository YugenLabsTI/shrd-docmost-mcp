<!-- The title is a Conventional Commit (fix:, feat:, docs:, ci: ...): it decides the next version. See CONTRIBUTING.md. -->

Closes #

<!-- The issue must be labelled status:approved; use "Refs #" to link it without closing it. -->

## What and why

<!-- One paragraph: what changes, who it helps, and why. -->

## What to review first

1.

## Checklist

- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run pyright` pass
- [ ] Tests cover the new behavior through the public API or the MCP tools
- [ ] README and package README updated if a tool, setting, error code or message changed
- [ ] No Docmost URL, credential, space name, page ID or page content from a real instance (code, fixtures, logs or this description)
