# Feature: move_page behind a flag

Objective: let an agent move a page under another parent (or to the space root) and place it among its siblings, behind its own opt-in flag.
Branch: `feat/move-page` (from `main` 45fcebb, after the cleanup pass #38 merged). Delivery: ask-on-risk; user asked for auto mode ("si todo pinta bien ve directo entonces al move_page"). Test runner: `uv run pytest` (+ opt-in `-m integration` against `dev/docmost`).

## Specs

- **S1 — move_page behind a flag.** Roadmap (Engram roadmap/docmost-mcp-next-blocks): "move_page behind a flag (was already in the original spec \"maybe later, behind a flag\"). Verified gotcha (docs/docmost-api-v0.96.0.md §3.11): pages/move with parentPageId omitted moves a nested page to the root — always send the intended parentPageId; position is a 5-12 char fractional index; same-space only; 409 \"Page location changed; retry the move\"." User, verbatim: "dale, sigamos con la pasada de limpieza. Esta vez ve en auto, si todo pinta bien ve directo entonces al move_page".
- **S2 — Inherited constraints.** Read-only by default and enforced in the client, allowlist in the client, `updatedAt` precheck, no credentials/content in logs or errors, TDD, typed errors, never the live instance without authorization, no AI attribution, no instance data in the repo, minimal dependencies; help text and docs updated with behavior.

Assumptions (agent decisions in auto mode): flag `DOCMOST_ALLOW_MOVE` (default off) on top of `DOCMOST_READ_ONLY=0`, enforced in the client (`MOVE_DISABLED`) and the tool registered only when both allow it; parameters `page_id`, `parent_page_id` (empty = space root), optional `after_page_id` (a sibling under the new parent) or `placement` `start`/`end` (default `end`), required `expected_updated_at`; same-space only; the client computes the position (port of the base62 fractional keys, no jitter, 5-12 chars, strictly between the neighbours) and refuses when there is no room; it always sends `parentPageId` (null for root); returns the page re-read after the move; no confirmation question (a move is reversible and changes no content).

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S2 | inline | done | L3 |
| T2 | S1, S2 | inline | pending | |
| T3 | S1, S2 | inline | pending | |

T1 client: positions module, `position` on page models, `DOCMOST_ALLOW_MOVE`, `MoveDisabledError`, `move_page` op (sync and async). T2 MCP tool `move_page` and its flag wiring. T3 docs (README, SECURITY, CHANGELOG) and integration tests against the local Docmost.

High-risk: T1, T2 (a new write that restructures page trees). Independent verifier at the feature's end.

## Log

- **L1 (2026-10-17, user, verbatim):** "dale, sigamos con la pasada de limpieza. Esta vez ve en auto, si todo pinta bien ve directo entonces al move_page".
- **L2 (2026-10-17, evidence, local Docmost 0.96.0 source, read-only):** positions come from `fractional-indexing-jittered@1.0.0` (base62 `0-9A-Za-z`, start key `a0`, jitter pads to 5 chars, e.g. `a07gp`); siblings are ordered by `position COLLATE "C"` then id; new pages are appended with `generateJitteredKeyBetween(last, null)`; the web UI computes move positions between the drop slot's neighbours and always sends `parentPageId`. `MovePageDto.position` is 5-12 chars (only the DTO enforces it); the server validates the key shape only. 409 fires only when the page changed space mid-move. The move bumps `updatedAt` and returns no data. `sidebar-pages` and `pages/info` include `position`; the client models dropped it.
- **L3 (2026-10-17, T1 evidence):** RED: ImportError (`_positions`, `MoveDisabledError`). GREEN: 548 passed; ruff, pyright clean. `_positions.key_between(lower, upper)`: increments the integer part after the last sibling (`a07gp` → `a1000`, Docmost's own behaviour for new pages), takes a base62 fraction midpoint between neighbours with the same integer part, uses a smaller fraction or a decremented integer before the first sibling, pads to 5 chars and checks `lower < key < upper` and ≤ 12 chars, else `InvalidRequestError` ("no room"); extreme heads `z`/`A` and malformed keys refused. 300 random inserts stay sorted. `position` added to `Page` and `PageSummary` (MCP result models are explicit, so tool outputs do not change). `DOCMOST_ALLOW_MOVE` (default off) + `MoveDisabledError` (`MOVE_DISABLED`); `_ops.move_page` checks writes and the flag before any request, placement/after combination, aware timestamp, then page (allowlist, trash, lock, can_edit, stale), parent (allowlist, not itself, same space, can_edit), lists siblings (≤ 50 requests, excludes the page, sorted by position then id), computes the key, posts `pages/move` always with `parentPageId` (null for root) and returns the page re-read. Sync and async `move_page`.
