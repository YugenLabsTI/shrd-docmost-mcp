# Feature: section-level page editing (block 2, part 1)

Objective: let agents change one section of a page (insert at its start or end, or replace its body) instead of rewriting the whole page, with strong protection against losing live edits.
Branch: `feat/section-editing` (from `main`). Delivery: chained PRs if over ~400 lines (feature branch chain, cached). Test runner: `uv run pytest` (+ opt-in `-m integration` against `dev/docmost`).

## Specs

- **S1 — Section editing.** "Dejaste por fuera lo mas importante: la edición por secciones en vez de reemplazar todo completo, eso tambien es de bloque 2" / "dale, arrancá con la edición por secciones". Design proposed and accepted with S2 (L3): a read tool `get_page_outline` (top-level headings: id, level, text, plus `updated_at`) and a write tool `edit_section` (`page_id`, heading id, `operation` `replace`|`prepend`|`append`, HTML content, required `expected_updated_at`). A section is a top-level heading plus everything until the next heading of the same or higher level (subsections included). Content format: HTML only in this version.
- **S2 — Protection.** User answer to "¿qué protección le ponemos a edit_section?": "Ambas" — i.e. "Bloquea si hubo actividad reciente y, si no la hubo, igual pide confirmación. Máxima protección, máxima fricción." Recent activity: the page was saved in the last ~60 s → refuse with a retryable `PAGE_BUSY`. Confirmation: the same mechanism and flag as replace (`DOCMOST_CONFIRM_REPLACE`).
- **S3 — Inherited constraints.** MVP and block 1 constraints apply: read-only by default and enforced in the client, allowlist inside the client, `updatedAt` precheck, no credentials/content in logs or errors, TDD, typed errors, never the live instance without authorization, no AI attribution, no instance data in the repo, minimal dependencies.

Assumptions (agent decisions, documented): headings are addressed by their stable Docmost id (`data-id` / `attrs.id`), not by text; only top-level headings (not inside columns, details, callouts); the edit reads the page as HTML, splices the section with a stdlib HTML parser and writes it back with `replace` + `format: html` (Docmost has no fragment API; HTML round-trips verified, L2); the busy window uses the local UTC clock against Docmost's `updatedAt` (clock skew documented); mentions/size/empty guards apply to the new HTML.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S3 | inline | done | L4; commit `feat(client): list a page outline` |
| T2 | S1, S3 | inline | done (verifier pending) | L5; commit `feat(client): splice one section of a page HTML` |
| T3 | S1, S2, S3 | inline | pending | |
| T4 | S1, S2, S3 | inline | pending | |
| T5 | S1, S2, S3 | inline | pending | |

T1 client `get_page_outline` (top-level headings from the JSON document). T2 pure HTML section splicer (top-level element split, section range, replace/prepend/append) with exhaustive unit tests. T3 client `edit_section` (read-only refusal, content guards, precheck, `PAGE_BUSY` window, splice, replace write with `expected_updated_at`). T4 MCP tools `get_page_outline`, `edit_section` (confirmation via the replace resolver chain, `PAGE_BUSY` retryable, descriptions). T5 docs (README, SECURITY, CHANGELOG), integration tests against the local Docmost, smoke update.

High-risk: T2, T3, T4 (rewrites whole pages). Independent verifier after T4.

## Log

- **L1 (2026-10-16, user, verbatim):** "Dejaste por fuera lo mas importante: la edición por secciones en vez de reemplazar todo completo, eso tambien es de bloque 2" — then "dale, arrancá con la edición por secciones".
- **L2 (2026-10-16, evidence, local Docmost probe):** Docmost HTML and JSON are flat top-level block sequences; every heading carries a stable id (`data-id` in HTML, `attrs.id` + `attrs.level` in JSON). Splicing the body of one h2 section in the HTML and writing it back with `replace`/`html` left every other block and every remaining heading id intact (the h3 subsection went with its parent section, as intended). Docmost has no fragment-update API, so a section edit rewrites the whole page: unsaved live edits anywhere on the page (persisted up to ~45 s late) can be lost and the `updatedAt` precheck cannot see them.
- **L3 (2026-10-16, user decision):** protection "Ambas" (see S2).
- **L4 (2026-10-17, T1 evidence):** RED: 4 failed (missing method). GREEN: 319 passed; ruff, pyright clean. `get_page_outline(page_id)` reads the page as JSON (allowlist, trash checks via get_page) and returns `PageOutline(page_id, title, updated_at, headings[Heading(id, level, text)])` for top-level headings with an id; nested headings (e.g. inside details) and headings without an id are skipped; text flattened with `document_text`.
- **L5 (2026-10-17, T2 evidence):** RED: collection ImportError. GREEN first run: 21 splicer tests on HTML shaped like real Docmost output (XHTML `xmlns`, `tableWrapper` + self-closing `<col />`, callouts, details with a nested heading, entities, `<br />`). `_sections.splice_section(html, heading_id, operation, new_html)`: stdlib `HTMLParser` collects top-level blocks with source offsets (void and self-closing tags, raw start-tag length so `>` inside attributes is safe); matches `data-id` or `id`; section ends at the next top-level heading of same/higher level or after the last block; `replace` keeps the heading, `prepend` after the heading, `append` before the next same/higher heading; nested headings → NOT_FOUND ("inside another block"), unknown → NOT_FOUND ("read the outline again"); malformed new content or page → INVALID_INPUT. No new dependency.
