# Docmost v0.97.0 internal API changes (for `docmost-client`)

- **Base:** [docmost-api-v0.96.0.md](docmost-api-v0.96.0.md) still describes the API. This document lists only what changed between the `docmost/docmost` tags `v0.96.0` and `v0.97.0` (46 commits) for the endpoints and conversions `docmost-client` uses. Everything not listed here is unchanged.
- **Method:** derived from source, then checked on a local, disposable Docmost 0.97.0 (`dev/docmost`). The checks were recorded contract fixtures (`packages/docmost-client/tests/fixtures/v0_97_0/recorded`), the integration tests and the probes in section 5. No request was sent to any other Docmost server.
- **Verdict:** no breaking change for the client. Three behavior changes are pinned by tests or documented below.

All links point to `https://github.com/docmost/docmost/blob/v0.97.0/...`.

## 1. Endpoints

| Endpoint | Change | Impact on the client |
|----------|--------|----------------------|
| `/auth/login`, `/auth/logout` | Request and response unchanged; still 10 requests / 60 s per IP ([throttle.module.ts#L28](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/integrations/throttle/throttle.module.ts#L28)). How the client IP is resolved changed (section 2). Logout also disconnects the user's websockets. | None |
| `/version` | Reports `0.97.0` | `SUPPORTED_DOCMOST_VERSIONS` includes it |
| `/users/me`, `/spaces`, `/spaces/info`, `/pages/recent`, `/pages/move`, `/comments`, `/comments/create` | Unchanged contract (only websocket and collaboration access rechecks, and an audit log on comment updates, which the client does not call) | None |
| `/pages/info` | Unchanged contract; markdown output changed (section 3) | Documented |
| `/pages/create`, `/pages/update` | `format` now defaults to `json` ([create-page.dto.ts#L32-L35](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/core/page/dto/create-page.dto.ts#L32-L35), [update-page.dto.ts#L20-L23](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/core/page/dto/update-page.dto.ts#L20-L23)). Content sent without a format used to fail with `"format must be one of the following values: json, markdown, html"`; now it is parsed as JSON, so text fails with 400 `"Invalid content format"`. | None: the client always sends `format`. Both errors are pinned by `test_content_without_format_is_rejected`. |
| `/pages/sidebar-pages` | Each item gains `updatedAt` ([page.service.ts#L309-L322](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/core/page/services/page.service.ts#L309-L322)) | Ignored by `PageSummary` (`extra="ignore"`) |
| `/search` | `query` is limited to 200 characters ([search.dto.ts#L12-L17](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/core/search/dto/search.dto.ts#L12-L17)): a longer query returns 400 `"query must be shorter than or equal to 200 characters"`. Highlights are built only from the first 100,000 characters of a page's text ([search.service.ts#L186-L214](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/core/search/search.service.ts#L186-L214)), so a match beyond that still returns the page with an empty highlight. The default `limit` (25, no upper cap) is unchanged. | A long query surfaces as `INVALID_INPUT` with Docmost's message |

## 2. Cross-cutting

- **Response wrapper, validation and error bodies:** unchanged (`http-response.interceptor.ts` untouched; `ValidationPipe` still `whitelist`, `stopAtFirstError`, `transform`, [main.ts#L156-L159](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/main.ts#L156-L159)).
- **Workspace pre-handler:** unchanged for the client's paths; it only gains exclusions for Slack and OAuth callbacks ([main.ts#L127-L147](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/main.ts#L127-L147)).
- **Client IP for throttling** (docmost/docmost#2580): `fastify-ip` was replaced by an `onRequest` hook that sets `request.ip` ([client-ip.utils.ts#L32-L83](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/common/helpers/client-ip.utils.ts#L32-L83)). `X-Forwarded-For` is trusted only through loopback, link-local, private and `100.64.0.0/10` hops, and `CF-Connecting-IP` only from Cloudflare edges. This replaces the 0.96.0 wording in section 2.4 of the base document ("the proxy's forwarded address is used"): behind a private reverse proxy, or in Docker, the forwarded address is still used.

## 3. Content formats

Libraries: `happy-dom` 20.8.9 → 21.0.4 (the DOM behind `jsonToHtml`/`htmlToJson`); Tiptap 3.31.3, `marked` 17.0.5 and `@joplin/turndown` 4.0.82 are unchanged. The write path (`parseProsemirrorContent`, `marked.utils.ts`, `updatePageContent`) is unchanged.

New schema nodes ([collaboration.util.ts](https://github.com/docmost/docmost/blob/v0.97.0/apps/server/src/collaboration/collaboration.util.ts)):

- **Tabs** (docmost/docmost#2381): `tabs` (block) > `tab` (attribute `id` as `data-tab-id`) > `tabLabel` (inline content) + `tabPanel` (blocks), all rendered as `div[data-type="..."]` ([lib/tabs](https://github.com/docmost/docmost/tree/v0.97.0/packages/editor-ext/src/lib/tabs)).
- **Integration cards and mentions:** `integrationCard` (block, `div[data-type="integrationCard"]`) and `integrationMention` (inline, `span[data-type="integrationMention"]`); links gain a `data-integration-provider` attribute.
- **Subpages** gains a `sortBy` attribute, rendered as `data-sort-by` ([subpages.ts#L38-L40](https://github.com/docmost/docmost/blob/v0.97.0/packages/editor-ext/src/lib/subpages/subpages.ts#L38-L40)).

Markdown read path changes ([turndown.utils.ts](https://github.com/docmost/docmost/blob/v0.97.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts)):

- **Tabs** become one `#### <label>` heading per tab, followed by the panel's content. They look like ordinary headings; markdown has no syntax for tabs.
- **Tables:** `<colgroup>` is stripped before conversion, so the first row is now a real GFM header row. In 0.96.0 it became a body row under an empty header.
- **Details** are written as `<details markdown="1">` instead of `<details>`.

Additions to the loss matrix (section 5.4 of the base document):

| Content | JSON | HTML read → HTML write | Markdown read | Markdown write |
|---------|------|------------------------|---------------|----------------|
| Tabs | ✅ | ✅ (labels, panels and `data-tab-id` round-trip) | ⚠️ `#### label` + content per tab | ❌ the headings stay headings: a markdown `replace` flattens the tabs |
| Integration cards and mentions † | ✅ | ✅ | ⚠️ text or link † | ❌ |

The outline and section editing are unaffected: the outline lists only top-level headings, and a tabs block is a single top-level block, so tab labels are never sections and headings inside a panel are rejected as nested.

## 4. Not verified

- The Enterprise submodule `apps/server/src/ee` is private; Enterprise-only overrides (for example Enterprise search or the MCP v2 work in docmost/docmost#2568) were not reviewed. The client targets Community Edition.
- Integration nodes († above) were not exercised on a running instance.

## 5. Observed on a running Docmost 0.97.0

| Check | Result |
|-------|--------|
| Recorded fixtures vs 0.96.0 | Same files and fields, except `updatedAt` added to sidebar items and the `content_without_format` error message (section 1) |
| Integration tests (`pytest -m integration`) | All pass, including the new tabs test (html round-trip and replace keep both tabs and their ids; markdown reads `#### Windows\n\nRun setup.exe`; the outline has no headings) |
| Markdown read of the seeded "Rich page" | Table header row `\| Service \| Owner \|` then `\| --- \| --- \|`; details as `<details markdown="1">` |
| Search with a 201-character query | `INVALID_INPUT`: `"query must be shorter than or equal to 200 characters"`; 200 characters are accepted |
