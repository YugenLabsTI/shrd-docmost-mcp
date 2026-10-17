# Feature: MCP resources and prompts (block 2, part 2)

Objective: expose neutral read-only resources and generic prompts, and let teams add their own prompts through configuration so their workflows live in config, not in this server's code.
Branch: `feat/resources-prompts` (from `main` 8b5f25a). Delivery: ask-on-risk; feature branch chain if over ~400 lines (cached). Test runner: `uv run pytest` (+ opt-in `-m integration` against `dev/docmost`).

## Specs

- **S1 — Resources.** Accepted design (L2): "Recursos (solo lectura, respetan `DOCMOST_ALLOWED_SPACES`): `docmost://page/{page_id}` — la página en markdown (título, `updated_at`); `docmost://space/{space}/tree` — árbol de páginas del espacio; `docmost://recent` — páginas recientes." Available in read-only mode. The tree is bounded (page and request caps) and says when it was truncated.
- **S2 — Generic prompts.** "Prompts genéricos incluidos (neutrales, sin flujo de equipo): `summarize_page(page_id)` y `answer_from_wiki(question, space?)` — busca, lee y responde citando páginas. Apagables con `DOCMOST_BUILTIN_PROMPTS=0`."
- **S3 — Team prompts from configuration.** "`DOCMOST_PROMPTS_DIR` → carpeta con un `.toml` por prompt (stdlib `tomllib`, cero dependencias)", example accepted verbatim:
  ```toml
  name = "weekly_report"
  description = "Draft the weekly report page"
  template = """
  Read the recent pages in {{space}} and draft ...
  """
  [[arguments]]
  name = "space"
  required = true
  ```
  "Sustitución segura: solo `{{arg}}` de argumentos declarados, sin evaluar nada. Validación al arrancar (tamaño, nombres únicos, argumentos requeridos) con error claro si un archivo es inválido; nunca se loguea el contenido del template."
- **S4 — Inherited constraints.** Read-only by default, allowlist in the client, no credentials or content in logs/errors, TDD, typed errors, never the live instance without authorization, no AI attribution, no instance data in the repo, minimal dependencies; help text and docs updated with behavior.

Assumptions (agent decisions): page resource text starts with title, page id and `updated_at`, then the markdown; tree caps 200 pages / 50 list requests; prompt names `^[a-z][a-z0-9_-]{0,63}$`, argument names `^[a-z_][a-z0-9_]{0,63}$`; at most 100 prompt files of 64 KiB each, non-recursive, `*.toml` only; an undeclared `{{x}}` in a template, a duplicate name or a clash with a built-in prompt is a startup error; a missing optional argument renders as its optional `default` (an added argument key, used by `answer_from_wiki`) or empty; built-in prompts instruct the agent to use the tools (they do not embed page content).

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S4 | inline | done | L3 |
| T2 | S2, S4 | inline | done | L4 |
| T3 | S3, S4 | inline | done | L4 |
| T4 | S1-S4 | inline | done (verified, L6) | L5 |

T1 resources in the MCP server. T2 built-in prompts and `DOCMOST_BUILTIN_PROMPTS`. T3 prompt file loader and `DOCMOST_PROMPTS_DIR`. T4 docs (README, SECURITY, CHANGELOG), MCP integration test against the local Docmost, smoke update.

High-risk: T3 (reads operator files, new config format). Independent verifier at the feature's end.

## Log

- **L1 (2026-10-17, user, verbatim):** "Vale, sigamos!!" — next roadmap item: block 2 part 2 (MCP resources, generic prompts, configurable prompts).
- **L2 (2026-10-17, design accepted):** user chose "Sí, avanzá (Recommended)" for: 3 resources (page, space tree, recent), 2 generic prompts switchable with `DOCMOST_BUILTIN_PROMPTS=0`, team prompts as `.toml` files in `DOCMOST_PROMPTS_DIR` with safe `{{arg}}` substitution and startup validation. MCP SDK 2.3: `MCPServer.resource(uri)` registers RFC 6570 templates; `Prompt(name, description, arguments=[PromptArgument], fn)` can be added with `add_prompt`.
- **L3 (2026-10-17, T1 evidence):** RED: 7 failed. GREEN: 453 passed (MCP package also on Python 3.11: 80 passed); ruff, pyright clean. New module `yugen_docmost_mcp/resources.py` registers `docmost://page/{page_id}` (markdown after title, page id, slug id, space, updated), `docmost://space/{space}/tree` (depth-first walk, 200 pages / 50 list requests, "(truncated: ...)" marker), `docmost://recent` (50 pages). Each read runs the compatibility gate and turns client errors into `ResourceError("<CODE>: <message>")`. README "MCP resources" section.
- **L4 (2026-10-17, T2+T3 evidence):** RED: ImportError (module missing). GREEN: 492 passed (MCP package on Python 3.11: 117 passed); ruff, pyright clean. New module `yugen_docmost_mcp/prompts.py`: `PromptSpec` (+ `render`, single-pass `re.sub` of declared `{{arg}}` only), `parse_prompt` (keys, name/argument patterns, types, undeclared placeholders, duplicate arguments, `default` only on optional arguments), `load_prompt_dir` (top-level `*.toml`, sorted, ≤100 files, ≤64 KiB, UTF-8, duplicate names), `prompts_from_env` (`DOCMOST_BUILTIN_PROMPTS`, `DOCMOST_PROMPTS_DIR`, clash with built-ins refused), `register_prompts`. Built-ins `summarize_page`, `answer_from_wiki` are defined as data and go through `parse_prompt`. The SDK reports a missing required argument as "Internal server error" (-32603), so prompts check it first and raise `MCPError(INVALID_PARAMS)` naming the arguments. Errors name the file, never the template. `build_server(prompts=...)`, `create_server(prompts=...)`, `main` loads them inside the ConfigError block (exit 2). `examples/prompts/weekly-report.toml` with a test that keeps it valid. README configuration rows and "MCP prompts" section.
- **L5 (2026-10-17, T4 evidence):** `test_resources_and_prompts_over_mcp` against the local Docmost (sandbox-only allowlist): page resource starts with the title and holds the content, the sandbox tree and recent list show the new page, the engineering tree is refused with `SPACE_NOT_ALLOWED`, both built-in prompts are listed and `summarize_page` names the page. Integration 23 passed; default suite 492 passed. `dev/live/smoke.py` now reads the read space's tree resource and lists prompts, printing only counts. SECURITY rows for resources and prompt files; CHANGELOG.
- **L6 (2026-10-17, independent verifier):** S1-S4 PASS, no blockers; tool schemas/outputs byte-identical to baseline. Two advisories touching S3 applied: prompt and argument names used `re.match` with `$`, which accepts a trailing newline (now `fullmatch`); some tomllib messages quote keys from the file (e.g. `Cannot declare ('...',) twice`), so a broken file could leak template text into the startup error (now only "(at line N, column M)" is kept). RED 3 failed, GREEN 495 passed. Remaining advisories, accepted: a UTF-8 BOM gives a generic position error; `*.TOML`, FIFOs and dangling symlinks are skipped silently; the SDK maps resource errors and unknown prompts to -32603 (the typed code stays in the message).
- **L7 (2026-10-17, native review):** user granted review of the corrected candidate; lenses risk, resilience, readability, reliability; approved and acknowledged (lineage review-1fefda844eaaf81e). Non-blocking follow-ups, all in the space tree resource: when the request budget runs out in the middle of a paginated level, the items already fetched for that level are dropped instead of shown; tree pagination (next cursor) has no direct test; the caps are not tested in isolation; a large tree can take up to 50 sequential requests. Readability nits: `_FilePrompt` name, the `limit=100` constant, the `lines` variable name, a test docstring. Next: delivery after the user's OK.
