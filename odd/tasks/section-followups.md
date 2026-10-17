# Feature: section editing follow-ups

Objective: close the non-blocking findings from the section-editing review (odd/tasks/section-editing.md L6, L10) and the update_page mention round-trip limitation.
Branch: `feat/section-followups` (from `main`). Delivery: ask-on-risk; feature branch chain if over ~400 lines (cached from previous features). Test runner: `uv run pytest` (+ opt-in `-m integration` against `dev/docmost`).

## Specs

- **S1 — Mention round-trip.** From L6: "`update_page` runs the mention guard over the full content, so an html round-trip `replace` of a page that already contains people's mentions is rejected — pre-existing limitation, to address separately (e.g. allow mentions already present in the page)." Writes (`update_page`, `edit_section`) accept mentions whose `(entityType, entityId)` is already on the current page and still reject any other mention. Evidence (L2): Docmost 0.96 notifies only users not mentioned in the previously saved content.
- **S2 — Busy window on the server clock.** From L10: "busy-window clock skew (R1-001, R3, R4; `_ops.py` busy check)". The 60 s window is measured against Docmost's clock (HTTP `Date` header plus local monotonic time since that response), falling back to the local clock when no `Date` was seen.
- **S3 — Duplicate heading ids.** From L10: "new content may reuse an existing heading id (`_sections.py`)". A section edit is refused when a heading in the new content reuses an id that another heading of the resulting page also has.
- **S4 — Accurate NOT_FOUND.** From L10: "the \"inside another block\" NOT_FOUND can fire when the id belongs to a non-heading block". "Inside another block" only when a nested heading has that id; an id on a non-heading block gets its own message.
- **S5 — Raw-text elements.** From L10: "stdlib vs happy-dom raw-text element divergence". New section content with raw-text or RCDATA elements (`script`, `style`, `textarea`, `title`, `xmp`, `iframe`, `noembed`, `noframes`, `noscript`, `plaintext`) is refused.
- **S6 — Inherited constraints.** Read-only by default, allowlist in the client, no credentials or content in logs/errors, TDD, typed errors, never the live instance without authorization, no AI attribution, no instance data in the repo, minimal dependencies. Help text and docs updated with behavior.

Assumptions (agent decisions): S1 compares mentions by `(entityType, entityId)` (what Docmost diffs on); when the write format is not json the current page is read once more as json only if the new content has mentions. S3 rejects instead of silently stripping ids. S5 rejects instead of escaping.

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S6 | inline | pending | |
| T2 | S3, S4, S5, S6 | inline | pending | |
| T3 | S2, S6 | inline | pending | |
| T4 | S1-S6 | inline | pending | |

T1 client mention guard that allows mentions already on the page (update_page, edit_section). T2 splicer: duplicate heading ids, NOT_FOUND messages, raw-text elements. T3 server clock from the `Date` header in the sessions, used by the client busy check and the MCP resolver. T4 docs (README, SECURITY, CHANGELOG) and an integration test of the mention round-trip against the local Docmost.

High-risk: T1 (relaxes a security guard), T3 (changes the busy protection). Independent verifier at the feature's end.

## Log

- **L1 (2026-10-17, user, verbatim):** "Vale, entonces continuemos!" — continuing the roadmap's first item: the section-editing review follow-ups and the update_page mention round-trip limitation.
- **L2 (2026-10-17, evidence, local Docmost 0.96.0 source, read-only):** REST `pages/update` goes through hocuspocus `PersistenceExtension.onStoreDocument`, the same path as editor saves. `PageNotificationService.processPageMention` notifies only user mentions whose user was not mentioned in the previously saved content (and not self-mentions); identical content stores and notifies nothing. Mention HTML: `span[data-type="mention"]` with `data-id`, `data-label`, `data-entity-type`, `data-entity-id`, `data-slug-id`, `data-creator-id`, `data-anchor-id`; JSON attrs `id`, `label`, `entityType`, `entityId`, `slugId`, `creatorId`, `anchorId`. The server never deduplicates node ids (`addUniqueIdsToDoc` fills only missing ids). Docmost sends an HTTP `Date` header (1 s resolution); the client drops all headers except `set-cookie` in `_protocol.unwrap`.
