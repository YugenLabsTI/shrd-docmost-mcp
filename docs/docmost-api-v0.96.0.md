# Docmost v0.96.0 internal API reference (for `docmost-client`)

- **Source:** `github.com/docmost/docmost` tag `v0.96.0` (commit `9b3e5dd`, `package.json` version `0.96.0`, [package.json#L4](https://github.com/docmost/docmost/blob/v0.96.0/package.json#L4)).
- **Date:** 2026-10-16.
- **Method:** derived from source, not from a live instance. No request was sent to any Docmost server. Statements marked **(inferred)** are deductions from library semantics or code paths, not lines read verbatim; they must be confirmed by contract fixtures recorded against a local (non-production) Docmost 0.96.0.
- **Scope:** the internal JSON API used by the Docmost web client. It is not a public, versioned API; any upgrade may break it.

All links below point to `https://github.com/docmost/docmost/blob/v0.96.0/...` unless stated otherwise. Paths are abbreviated in link text (`server/` = `apps/server/src/`, `editor-ext/` = `packages/editor-ext/src/lib/`).

---

## 1. Conventions

| Topic | Behavior | Evidence |
|---|---|---|
| Route prefix | Every controller is mounted under `/api` (excluded: `robots.txt`, `share/...`, `mcp`, `.well-known/...`, `docs/...`). | [server/main.ts#L44-L56](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L44-L56) |
| HTTP framework | NestJS 11 on Fastify (`FastifyAdapter`, `trustProxy: true`, `ignoreTrailingSlash: true`). | [server/main.ts#L22-L31](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L22-L31), [apps/server/package.json#L55-L62](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/package.json#L55-L62) |
| Verb + body | All endpoints in this document are `POST` with a JSON body (even reads such as `/api/version`, `/api/users/me`, `/api/spaces`). | e.g. [server/core/page/page.controller.ts#L71-L74](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L71-L74) |
| Success status | Every endpoint below is decorated `@HttpCode(HttpStatus.OK)`, so success is **200** (not Nest's default 201 for POST). | e.g. [page.controller.ts#L202-L204](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L202-L204), [space.controller.ts#L50-L52](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/space/space.controller.ts#L50-L52) |
| Success wrapper | A global interceptor wraps every successful handler result as `{"data": <result>, "success": true, "status": <http status>}` unless the handler is marked `@SkipTransform()`. A handler returning `undefined` (login, logout, move) serializes as `{"success": true, "status": 200}` (no `data` key) **(inferred: `JSON.stringify` drops `undefined`)**. | [server/common/interceptors/http-response.interceptor.ts#L24-L38](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/interceptors/http-response.interceptor.ts#L24-L38), [server/main.ts#L161](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L161) |
| Error body | No global exception filter is registered; the interceptor only maps successes. Errors therefore use NestJS's default body, **not** the wrapper: `{"message": string \| string[], "error": string, "statusCode": number}` (e.g. `{"message":"Page not found","error":"Not Found","statusCode":404}`). Non-HTTP exceptions (plain `Error`) become `{"statusCode":500,"message":"Internal server error"}` **(inferred: NestJS 11 `BaseExceptionFilter` defaults)**. | [server/main.ts#L152-L161](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L152-L161) (no `useGlobalFilters`), [server/app.module.ts#L106-L112](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/app.module.ts#L106-L112) (only an interceptor provider) |
| Validation | Global `ValidationPipe({ whitelist: true, stopAtFirstError: true, transform: true })`. Unknown properties are **silently stripped** (no `forbidNonWhitelisted`); validation errors return **400** with `message` as an array of strings. No implicit type conversion is enabled, so numbers must be JSON numbers and booleans JSON booleans. | [server/main.ts#L152-L158](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L152-L158) |
| Workspace resolution | A pre-handler throws `404 Workspace not found` for any `/api/*` request when no workspace exists (fresh install), except setup/health and a few others. | [server/main.ts#L126-L150](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L126-L150) |
| Body size | No `bodyLimit` is passed to Fastify, so Fastify's default (1 MiB) applies; larger bodies are rejected with 413 before reaching Nest **(inferred: Fastify default)**. DTOs impose no content length limit. | [server/main.ts#L22-L31](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L22-L31), [create-page.dto.ts#L29-L30](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/dto/create-page.dto.ts#L29-L30) |
| CORS | `app.enableCors()` with defaults; irrelevant for a server-side client. | [server/main.ts#L160](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L160) |
| IDs | Pages accept either UUID `id` or short `slugId` wherever the controller calls `pageRepo.findById` (it branches on `isValidUUID`). Spaces accept UUID or slug (case-insensitive) in `spaces/info`. Exceptions are noted per endpoint. | [server/database/repos/page/page.repo.ts#L100-L104](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/page/page.repo.ts#L100-L104), [space.repo.ts#L43-L47](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/space/space.repo.ts#L43-L47) |
| Timestamps | `createdAt`, `updatedAt`, `deletedAt` are Postgres timestamps serialized as ISO-8601 strings **(inferred: `Date` JSON serialization)**. | [server/database/types/db.d.ts#L313-L337](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/types/db.d.ts#L313-L337) |

### 1.1 Cursor pagination (shared by spaces, recent pages, sidebar pages, comments)

Request fields (`PaginationOptions`, validated as a second `@Body()` DTO, so they share the same JSON body as the endpoint DTO):

| Field | Type | Default | Constraint |
|---|---|---|---|
| `limit` | number | `20` | `1..100` |
| `cursor` | string | – | opaque, forward |
| `beforeCursor` | string | – | opaque, backward |
| `query` | string | – | used by some endpoints (e.g. spaces name/description filter) |
| `adminView` | boolean | – | not used by endpoints in this document |

Evidence: [server/database/pagination/pagination-options.ts#L11-L34](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/pagination/pagination-options.ts#L11-L34).

Response shape (inside `data`):

```json
{
  "items": [],
  "meta": { "limit": 20, "hasNextPage": false, "hasPrevPage": false, "nextCursor": null, "prevCursor": null }
}
```

Evidence: [cursor-pagination.ts#L113-L127](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/pagination/cursor-pagination.ts#L113-L127), [#L239-L274](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/pagination/cursor-pagination.ts#L239-L274).

Notes:
- Cursors are base64url-encoded `URLSearchParams` of the sort keys; a malformed cursor throws a plain `Error` (→ 500, **inferred**) ([#L327-L366](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/pagination/cursor-pagination.ts#L327-L366)). Treat cursors as opaque.
- Several endpoints filter by page-level permissions **after** the SQL limit, so a page can contain fewer than `limit` items while `hasNextPage` is `true` ([page.service.ts#L344-L393](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L344-L393), [#L980-L998](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L980-L998)). Clients must page on `hasNextPage`/`nextCursor`, never on item count.
- `/api/search` does **not** use this format (offset + limit, `{items}` only; see section 4).

---

## 2. Authentication

### 2.1 `POST /api/auth/login`

| Field | Type | Validators |
|---|---|---|
| `email` | string | `@IsNotEmpty() @IsEmail()` |
| `password` | string | `@IsNotEmpty() @IsString()` |

Evidence: [server/core/auth/dto/login.dto.ts#L3-L11](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/dto/login.dto.ts#L3-L11).

Flow ([auth.controller.ts#L55-L105](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/auth.controller.ts#L55-L105)):

1. `validateSsoEnforcement(workspace)` → **400** `"This workspace has enforced SSO login."` when `workspace.enforceSso` ([auth.util.ts#L36-L40](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/auth.util.ts#L36-L40)).
2. If the Enterprise MFA module is bundled (`require('./../../ee/mfa/...')` succeeds), `checkMfaRequirements` runs. If the user has MFA or the workspace enforces it, the handler returns `{userHasMfa, requiresMfaSetup, isMfaEnforced}` in `data` and sets **no** auth cookie. Password login cannot complete for such an account through this endpoint ([#L64-L101](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/auth.controller.ts#L64-L101)).
3. Otherwise `AuthService.login` → **401** `"Email or password does not match"` for unknown, disabled (deactivated/deleted) users or a wrong password ([auth.service.ts#L66-L83](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/services/auth.service.ts#L66-L83)). Email-verification checks only apply to Cloud ([auth.util.ts#L15-L34](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/auth.util.ts#L15-L34)).
4. A **server-side session row** is created for every successful login and the JWT embeds its `sessionId` ([session.service.ts#L39-L56](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/session/session.service.ts#L39-L56), [token.service.ts#L30-L43](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/services/token.service.ts#L30-L43)).

**The JWT is returned only as a cookie, never in the body.** `setAuthCookie` sets `authToken=<jwt>` with `httpOnly: true`, `sameSite: 'lax'`, `path: '/'`, `secure` only when `APP_URL` is `https:`, and `expires` = now + `JWT_TOKEN_EXPIRES_IN` (default `90d`) ([auth.controller.ts#L222-L230](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/auth.controller.ts#L222-L230), [environment.service.ts#L26-L34](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/environment/environment.service.ts#L26-L34), [#L63-L76](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/environment/environment.service.ts#L63-L76)). The body is `{"success":true,"status":200}` **(inferred)**. The JWT is signed with `APP_SECRET`, `issuer: 'Docmost'`, and `expiresIn: JWT_TOKEN_EXPIRES_IN` ([token.module.ts#L9-L20](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/token.module.ts#L9-L20)).

Client consequence: parse `authToken` from the `Set-Cookie` response header. A `200` without an `authToken` cookie means an MFA challenge (or another non-password path) and must map to a typed error, not a success.

JWT payload: `{sub, email, workspaceId, type: "access", sessionId}` ([jwt-payload.ts#L12-L18](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/dto/jwt-payload.ts#L12-L18)).

### 2.2 Token extraction and validation

- Extraction: `req.cookies?.authToken || extractBearerTokenFromHeader(req)`. **The cookie wins over the `Authorization: Bearer` header** when both are present ([jwt.strategy.ts#L31-L38](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/strategies/jwt.strategy.ts#L31-L38)). The Bearer parser is case-insensitive on the scheme and splits on a single space ([utils.ts#L134-L139](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/helpers/utils.ts#L134-L139)).
- `ignoreExpiration: false`; expired JWT → 401.
- The token's `workspaceId` must equal the request's resolved workspace, else 401 `"Workspace does not match"` ([jwt.strategy.ts#L45-L51](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/strategies/jwt.strategy.ts#L45-L51)).
- Only `type: "access"` is accepted for user tokens; `api_key` and `oauth_access` tokens require the Enterprise module and otherwise fail with 401 `"Enterprise API Key module missing"` / `"Enterprise OAuth module missing"` ([#L53-L72](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/strategies/jwt.strategy.ts#L53-L72), [#L98-L154](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/strategies/jwt.strategy.ts#L98-L154)).
- The user must exist and not be disabled; the embedded session must be active (not expired, not revoked) and belong to the same user/workspace, else 401 ([#L74-L95](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/strategies/jwt.strategy.ts#L74-L95), [user-session.repo.ts#L27-L35](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/session/user-session.repo.ts#L27-L35)). Revoking the session (logout, password change, admin action) invalidates the JWT before its `exp`.
- The guard returns 401 `Unauthorized` when no/invalid token ([jwt-auth.guard.ts#L44-L47](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/guards/jwt-auth.guard.ts#L44-L47)). OAuth-scope checks only apply to OAuth tokens ([#L62-L80](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/guards/jwt-auth.guard.ts#L62-L80)), so `@OAuthScope` annotations do not affect password-session clients.

### 2.3 Workspace resolution (self-hosted)

When `CLOUD` is not `true`, `DomainMiddleware` attaches the **first workspace ordered by `createdAt` ascending** to every request ([domain.middleware.ts#L17-L27](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/middlewares/domain.middleware.ts#L17-L27), [workspace.repo.ts#L83-L90](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/workspace/workspace.repo.ts#L83-L90), [environment.service.ts#L206-L215](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/environment/environment.service.ts#L206-L215)). No host header or workspace id is needed from the client.

### 2.4 Throttling

The `AuthController` class uses `ThrottlerGuard` with only the `auth` throttler enabled: **10 requests / 60 s**, tracked per client IP (default tracker; `trustProxy` is on, so the proxy's forwarded address is used). `change-password`, `collab-token` and `logout` skip it. Exceeding it returns **429** with message `"Too many requests"`. No other endpoint in this document is throttled. Evidence: [auth.controller.ts#L41-L44](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/auth.controller.ts#L41-L44), [throttle.module.ts#L24-L33](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/throttle/throttle.module.ts#L24-L33), the only `@UseGuards(ThrottlerGuard)` in the server is in `auth.controller.ts`.

### 2.5 `POST /api/auth/logout`

Requires a valid JWT. Revokes the session embedded in the JWT and clears the `authToken` cookie; returns `{"success":true,"status":200}` **(inferred)**. Not throttled. Evidence: [auth.controller.ts#L195-L220](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/auth.controller.ts#L195-L220), [user-session.repo.ts#L60-L70](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/session/user-session.repo.ts#L60-L70).

### 2.6 Session hygiene

Sessions are capped at 25 per user and stale sessions (7-day retention) are cleaned by a daily job ([session.service.ts#L14-L37](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/session/session.service.ts#L14-L37)). A client that logs in on every process start without logging out accumulates sessions; the daily trim may then revoke older sessions of the same account **(inferred from `trimExcessSessions`)**. Reuse the in-memory token for the process lifetime and call logout on shutdown.

---

## 3. Endpoints

All endpoints in this section require a valid JWT (`@UseGuards(JwtAuthGuard)` on the controller). Response examples show the content of `data`; the full body is always `{"data": ..., "success": true, "status": 200}`.

### 3.1 `POST /api/version`

- Controller: `VersionController.getVersion`, guarded, returns 404 on Cloud ([version.controller.ts#L13-L26](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/security/version.controller.ts#L13-L26)).
- Request: empty body.
- Response ([version.service.ts#L9-L27](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/security/version.service.ts#L9-L27)):

```json
{ "currentVersion": "0.96.0", "latestVersion": "0.96.0", "releaseUrl": "https://github.com/docmost/docmost/releases" }
```

- Caveats: the server calls `api.github.com` on every request to obtain `latestVersion`. If that call returns a non-OK status the handler returns `undefined`, so `data` is **absent** even though the request succeeds; if it throws (network), `latestVersion` is `0`. Use `currentVersion` only, and treat a missing `data` as "version unknown". Note the route is `POST`, and it requires authentication.

### 3.2 `POST /api/users/me`

- Controller: `UserController.getUserInfo` ([user.controller.ts#L26-L45](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/user/user.controller.ts#L26-L45)).
- Request: empty body.
- Response: `{user, workspace}`. `user` has the `UserRepo.baseFields` (no password) ([user.repo.ts#L22-L39](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/user/user.repo.ts#L22-L39)); `workspace` is every workspace column except `licenseKey`, plus `memberCount` ([db.d.ts#L476-L501](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/types/db.d.ts#L476-L501)).

```json
{
  "user": {
    "id": "uuid", "email": "bot@example.com", "name": "Bot", "emailVerifiedAt": null, "avatarUrl": null,
    "role": "member", "workspaceId": "uuid", "locale": "en-US", "timezone": null, "settings": null,
    "lastLoginAt": "2026-10-16T00:00:00.000Z", "deactivatedAt": null, "createdAt": "...", "updatedAt": "...",
    "deletedAt": null, "hasGeneratedPassword": false
  },
  "workspace": {
    "id": "uuid", "name": "...", "description": null, "logo": null, "hostname": null, "customDomain": null,
    "defaultRole": "member", "defaultSpaceId": "uuid", "emailDomains": [], "enforceSso": false, "enforceMfa": false,
    "isScimEnabled": false, "settings": null, "plan": null, "status": null, "billingEmail": null,
    "stripeCustomerId": null, "trialEndAt": null, "auditRetentionDays": 0, "trashRetentionDays": 0,
    "createdAt": "...", "updatedAt": "...", "deletedAt": null, "memberCount": 3
  }
}
```

(Values are illustrative; field names are from the source.) Useful as a cheap "is my token valid" probe.

### 3.3 `POST /api/spaces` (list spaces the user is a member of)

- Controller: `SpaceController.getWorkspaceSpaces` ([space.controller.ts#L50-L93](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/space/space.controller.ts#L50-L93)).
- Request: `PaginationOptions` only (section 1.1). `query` filters by name or description (`ILIKE`, accent-insensitive) ([space-member.repo.ts#L345-L376](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/space/space-member.repo.ts#L345-L376)).
- Ordering: `name ASC, id ASC`.
- Response items: every `spaces` column ([db.d.ts#L401-L416](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/types/db.d.ts#L401-L416)) + `memberCount` + `membership: {userId, role}` where `role` is `admin | writer | reader` ([permission.ts#L12-L16](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/helpers/types/permission.ts#L12-L16)).

```json
{
  "items": [
    {
      "id": "uuid", "name": "Engineering", "description": null, "slug": "engineering", "logo": null,
      "visibility": "private", "defaultRole": "writer", "isPersonal": false, "settings": null,
      "creatorId": "uuid", "workspaceId": "uuid", "createdAt": "...", "updatedAt": "...", "deletedAt": null,
      "memberCount": 5, "membership": { "userId": "uuid", "role": "writer" }
    }
  ],
  "meta": { "limit": 20, "hasNextPage": false, "hasPrevPage": false, "nextCursor": null, "prevCursor": null }
}
```

- Permissions: only spaces where the user is a direct or group member are listed.

### 3.4 `POST /api/spaces/info`

- Controller: `SpaceController.getSpaceInfo` ([space.controller.ts#L95-L131](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/space/space.controller.ts#L95-L131)).
- Request: `{ "spaceId": string }` — `@IsString() @IsNotEmpty()`; the UUID validator is commented out, so **either the UUID or the space `slug` (case-insensitive)** is accepted ([space-id.dto.ts#L3-L8](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/space/dto/space-id.dto.ts#L3-L8), [space.repo.ts#L25-L54](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/space/space.repo.ts#L25-L54)). The slug field on the response is `slug`.
- Response: space columns + `memberCount` + `isPublished` ([space.repo.ts#L213-L245](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/space/space.repo.ts#L213-L245)) + `membership: {userId, role, permissions}` where `permissions` is the CASL rule list ([space-ability.factory.ts#L41-L72](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/casl/abilities/space-ability.factory.ts#L41-L72)).

```json
{
  "id": "uuid", "name": "Engineering", "slug": "engineering", "description": null, "visibility": "private",
  "memberCount": 5, "isPublished": false, "...": "other space columns",
  "membership": {
    "userId": "uuid", "role": "writer",
    "permissions": [ { "action": "read", "subject": "settings" }, { "action": "manage", "subject": "page" } ]
  }
}
```

- Errors: **404** `"Space not found"` (unknown id/slug, [space.service.ts#L257-L266](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/space/services/space.service.ts#L257-L266)); **404** `"Space permissions not found"` when the user is not a member (the ability factory throws for "no role") ([space-ability.factory.ts#L20-L38](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/casl/abilities/space-ability.factory.ts#L20-L38)). Non-membership is therefore indistinguishable from non-existence by status code.

### 3.5 `POST /api/search`

See section 4 (dedicated).

### 3.6 `POST /api/pages/info`

- Controller: `PageController.getPage` ([page.controller.ts#L71-L106](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L71-L106)).
- Request (`PageInfoDto`, [page.dto.ts#L13-L42](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/dto/page.dto.ts#L13-L42)):

| Field | Type | Validators | Notes |
|---|---|---|---|
| `pageId` | string | `@IsString() @IsNotEmpty()` | UUID or `slugId` |
| `includeSpace` | boolean | optional | **ignored**: the controller always includes the space |
| `includeContent` | boolean | optional | **ignored**: content is always included |
| `format` | `json \| markdown \| html` | optional, lower-cased | default: JSON (ProseMirror) |

- Response: `PageRepo.baseFields` + `content` + `space` + `creator` + `lastUpdatedBy` + `contributors` + `deletedBy` + `permissions` ([page.repo.ts#L28-L46](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/page/page.repo.ts#L28-L46), [#L443-L486](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/page/page.repo.ts#L443-L486)). No `hasChildren`, no `textContent`, no `ydoc`.

```json
{
  "id": "uuid", "slugId": "abc123xyz0", "title": "Runbook", "icon": null, "coverPhoto": null,
  "position": "a0", "parentPageId": null, "creatorId": "uuid", "lastUpdatedById": "uuid",
  "spaceId": "uuid", "workspaceId": "uuid", "isLocked": false, "isBase": false,
  "createdAt": "...", "updatedAt": "2026-10-16T10:00:00.000Z", "deletedAt": null, "contributorIds": ["uuid"],
  "content": "# Runbook\n\n...",
  "space": { "id": "uuid", "name": "Engineering", "slug": "engineering" },
  "creator": { "id": "uuid", "name": "Ana", "avatarUrl": null },
  "lastUpdatedBy": { "id": "uuid", "name": "Ana", "avatarUrl": null },
  "contributors": [ { "id": "uuid", "name": "Ana", "avatarUrl": null } ],
  "deletedBy": null,
  "permissions": { "canEdit": true, "hasRestriction": false }
}
```

- `content` is a ProseMirror JSON object for `json`, a string for `markdown`/`html`, and `null` for a page that has never had content (conversion is skipped when `page.content` is falsy).
- Permissions: space role must allow `read page`; if the page (or an ancestor) has page-level restrictions, the page-level grant decides ([page-access.service.ts#L46-L69](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page-access/page-access.service.ts#L46-L69)).
- Errors: **404** `"Page not found"`; **404** `"Space permissions not found"` (not a member); **403** (restricted page).
- **Trashed pages are returned** (no `deletedAt` check); the client must check `deletedAt`.
- `content` reflects the last persisted state, which can lag live editor sessions by up to ~45 s (section 6.3).

### 3.7 `POST /api/pages/recent`

- Controller: `PageController.getRecentPages` ([page.controller.ts#L418-L444](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L418-L444)).
- Request: `RecentPageDto { spaceId?: string }` (`@IsString`, not UUID-validated, [recent-page.dto.ts#L3-L7](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/dto/recent-page.dto.ts#L3-L7)) + `PaginationOptions`. Pass a UUID: a slug reaches a UUID column comparison in the role lookup and likely fails with 500 **(inferred)**.
- Response: paginated `PageRepo.baseFields` + `space {id, name, slug}`, ordered `updatedAt DESC, id DESC`, excluding trashed pages and post-filtered by page permissions ([page.repo.ts#L327-L371](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/page/page.repo.ts#L327-L371), [page.service.ts#L955-L998](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L955-L998)). No `content`.
- Without `spaceId`: pages from all spaces the user belongs to. With `spaceId`: **403** if the user cannot read pages there (or 404 if not a member).

### 3.8 `POST /api/pages/sidebar-pages` (children listing)

- Controller: `PageController.getSidebarPages` ([page.controller.ts#L533-L574](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L533-L574)).
- Request: `SidebarPageDto` ([sidebar-page.dto.ts#L3-L11](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/dto/sidebar-page.dto.ts#L3-L11)) + `PaginationOptions`:

| Field | Type | Validators | Notes |
|---|---|---|---|
| `spaceId` | string | optional `@IsUUID()` | root pages of the space |
| `pageId` | string | optional `@IsString()` | children of this page; when present, `spaceId` is ignored and derived from the page |

- At least one is required → **400** `"Either spaceId or pageId must be provided"`.
- **Pass a UUID `pageId`.** The page lookup accepts a slug, but the children query filters `parentPageId = <raw dto.pageId>` ([page.service.ts#L319-L323](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L319-L323)); a slug there is compared to a UUID column and likely yields a 500 **(inferred)**.
- Unknown `pageId` → **403** (not 404) ([page.controller.ts#L548-L552](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L548-L552)).
- Response items ([page.service.ts#L294-L396](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L294-L396)), ordered by `position` (C collation) then `id`; excludes trashed pages:

```json
{
  "items": [
    {
      "id": "uuid", "slugId": "abc123xyz0", "title": "Child", "icon": null, "position": "a0",
      "parentPageId": "uuid", "spaceId": "uuid", "creatorId": "uuid", "isBase": false, "deletedAt": null,
      "hasChildren": true, "canEdit": true
    }
  ],
  "meta": { "limit": 20, "hasNextPage": false, "hasPrevPage": false, "nextCursor": null, "prevCursor": null }
}
```

- There is **no `updatedAt`** in sidebar items. When restricted pages exist in the space, inaccessible items are removed and `hasChildren` is recomputed to "has accessible children" ([#L344-L393](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L344-L393)).

### 3.9 `POST /api/pages/create`

- Controller: `PageController.create` ([page.controller.ts#L202-L271](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L202-L271)); service: [page.service.ts#L92-L176](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L92-L176).
- Request (`CreatePageDto`, [create-page.dto.ts#L13-L36](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/dto/create-page.dto.ts#L13-L36)):

| Field | Type | Validators | Notes |
|---|---|---|---|
| `spaceId` | string | `@IsUUID()` (required) | slug not accepted |
| `title` | string | optional `@IsString()` | no length limit |
| `icon` | string | optional `@IsString()` | emoji string |
| `parentPageId` | string | optional `@IsString()` | UUID or slugId; must be in `spaceId` and not trashed |
| `content` | string \| object | optional, no type validator | object for `json`, string for `markdown`/`html` |
| `format` | `json \| markdown \| html` | `@ValidateIf(content !== undefined) @IsIn(...)`, lower-cased | see note |

- **Always send `format` explicitly when sending `content`.** The `@Transform(... ?? 'json')` default only runs when the key is present in the body; with `content` present and `format` absent, `@IsIn` sees `undefined` and the request is rejected with 400 **(inferred: class-transformer 0.5.1 only transforms keys present in the plain object)**. The service also ignores content unless both `content` and `format` are truthy ([page.service.ts#L122-L131](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L122-L131)).
- Permissions: with `parentPageId`, edit permission on the parent page; without it, space ability `create page` (writer/admin) → **403** otherwise.
- Errors: **404** `"Parent page not found"` (missing, trashed, or in a different space); **400** `"Invalid content format"` (content fails schema parsing, section 5); **403**; **404** `"Space permissions not found"`.
- Position: appended after the last sibling ([page.service.ts#L178-L221](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L178-L221)).
- Content is written directly to `pages.content`, `text_content` and `ydoc` (no collaboration round-trip) ([#L122-L150](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L122-L150)).
- Response: `insertPage` returns only `baseFields` ([page.repo.ts#L180-L197](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/page/page.repo.ts#L180-L197)), so the response is the base page + `permissions`, **without `content`** (the format conversion branch is skipped because `page.content` is undefined) and without `space`/`creator`.

```json
{
  "id": "uuid", "slugId": "abc123xyz0", "title": "New page", "icon": null, "coverPhoto": null, "position": "a1",
  "parentPageId": "uuid", "creatorId": "uuid", "lastUpdatedById": "uuid", "spaceId": "uuid", "workspaceId": "uuid",
  "isLocked": false, "isBase": false, "createdAt": "...", "updatedAt": "...", "deletedAt": null,
  "contributorIds": null,
  "permissions": { "canEdit": true, "hasRestriction": false }
}
```

### 3.10 `POST /api/pages/update`

- Controller: `PageController.update` ([page.controller.ts#L273-L309](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L273-L309)); service: [page.service.ts#L223-L292](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L223-L292).
- Request (`UpdatePageDto extends PartialType(CreatePageDto)`, [update-page.dto.ts#L6-L24](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/dto/update-page.dto.ts#L6-L24)):

| Field | Type | Validators | Effect |
|---|---|---|---|
| `pageId` | string | `@IsString()` (required) | UUID or slugId |
| `title` | string | optional | updated when present |
| `icon` | string | optional | updated when present |
| `content` | string \| object | optional | see section 5 |
| `operation` | `append \| prepend \| replace` | `@ValidateIf(content !== undefined) @IsIn(...)`, lower-cased | **required whenever `content` is sent** (no default; not inherited, so no `IsOptional`) |
| `format` | `json \| markdown \| html` | `@ValidateIf(content !== undefined) @IsIn(...)` | **send explicitly**; same default caveat as create **(inferred)** |
| `spaceId`, `parentPageId` | inherited | validated (`spaceId` must be a UUID if sent) | **accepted but ignored** by the service |

- Permissions: `validateCanEdit` — space writer/admin, or page-level writer when restrictions apply ([page-access.service.ts#L76-L103](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page-access/page-access.service.ts#L76-L103)).
- Errors: **404** `"Page not found"`; **403**; **404** `"Space permissions not found"`; **400** validation / `"Invalid content format"`; **500** if the collaboration event times out (section 6).
- **No `deletedAt` check**: trashed pages can be updated. **No `isLocked` enforcement** anywhere in the server (the column is only selected, [db.d.ts#L325](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/types/db.d.ts#L325), [page.repo.ts#L40](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/page/page.repo.ts#L40)).
- Response: the page re-read after the write with `space`, `content`, `creator`, `lastUpdatedBy`, `contributors` ([page.service.ts#L268-L274](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L268-L274)) + `permissions: {canEdit: true, hasRestriction}`. It **includes the new `updatedAt`**. `content` is converted to `format` when `format` is `markdown`/`html`; otherwise (including title-only updates without `format`) the full ProseMirror JSON is returned. See section 6 for semantics.

### 3.11 Later scope (brief)

**`POST /api/pages/move`** ([page.controller.ts#L715-L746](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L715-L746), [page.service.ts#L834-L899](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L834-L899), [move-page.dto.ts#L9-L21](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/dto/move-page.dto.ts#L9-L21))
- Request: `pageId` (string), `position` (string, 5–12 chars, a fractional-index key; invalid → 400 `"Invalid move position"`), `parentPageId` (optional string or null).
- Same space only (`move-to-space` is a separate endpoint). Requires space `edit page` + page edit + edit on the target parent.
- **Gotcha:** if `parentPageId` is omitted and the page currently has a parent, the page is moved to the **root** (the service sets `parentPageId = null` whenever the DTO value differs from the current one and is falsy). Always send the intended `parentPageId`.
- Errors: 400 `"A page cannot be its own parent"`, 400 `"A page cannot be moved under its descendant"`, 404 `"Parent page not found"`, 409 `"Page location changed; retry the move"`.
- Returns no data (`{"success":true,"status":200}`, **inferred**). Bumps `updatedAt` (section 6.1).

**`POST /api/comments`** ([comment.controller.ts#L87-L105](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/comment/comment.controller.ts#L87-L105))
- Request: `{pageId: string}` + `PaginationOptions`; cursor-paginated `Comment` rows ([comment.service.ts#L148-L158](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/comment/comment.service.ts#L148-L158), columns at [db.d.ts#L204-L221](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/types/db.d.ts#L204-L221)). 404 for trashed pages; view permission required.

**`POST /api/comments/create`** ([comment.controller.ts#L50-L85](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/comment/comment.controller.ts#L50-L85), [create-comment.dto.ts#L21-L46](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/comment/dto/create-comment.dto.ts#L21-L46), [comment.service.ts#L49-L104](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/comment/comment.service.ts#L49-L104))
- Request: `pageId` (string), `content` (**a JSON string** — `@IsJSON()`, then `JSON.parse`; not schema-validated), `selection?` (string, truncated to 250 chars), `type?` (`inline | page`, default `page`), `parentCommentId?` (UUID; replies to replies are rejected), `yjsSelection?` (object; invalid shapes are logged and ignored).
- Permission: edit permission, or view permission when the space setting `comments.allowViewerComments` is enabled ([page-access.service.ts#L105-L124](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page-access/page-access.service.ts#L105-L124)).

---

## 4. `POST /api/search`

- Controller: `SearchController.pageSearch` ([search.controller.ts#L49-L81](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.controller.ts#L49-L81)); service: [search.service.ts#L25-L217](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.service.ts#L25-L217).
- Request (`SearchDTO`, [search.dto.ts#L11-L44](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/dto/search.dto.ts#L11-L44)):

| Field | Type | Validators | Notes |
|---|---|---|---|
| `query` | string | optional | trimmed; empty query returns `{items: []}` unless `creatorId`/`labelIds` are given |
| `spaceId` | string | optional `@IsUUID()` | restrict to one space; read permission checked (403/404) |
| `creatorId` | string | optional `@IsUUID()` | filter |
| `labelIds` | string[] | optional, UUIDs | filter |
| `titleOnly` | boolean | optional | title `LIKE` + `word_similarity` ranking, empty `highlight` |
| `limit` | number | optional `@IsNumber()` | default **25**, **no maximum** |
| `offset` | number | optional `@IsNumber()` | default 0 (offset pagination) |
| `shareId` | string | optional | deleted by the controller for this endpoint |

- Matching: full-text `tsv @@ to_tsquery('english', f_unaccent(query + '*'))` (prefix match on the last term via `pg-tsquery`), ranked by `ts_rank`; trashed pages excluded ([#L43-L111](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.service.ts#L43-L111)).
- Scope / permissions: without `spaceId`, only spaces the user is a member of (and the current workspace); results are then post-filtered by page-level permissions, so fewer than `limit` items may return ([#L117-L190](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.service.ts#L117-L190)).
- Response: `{items: [...]}` — **no `meta`, no total, no cursor**. Fields ([#L64-L77](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.service.ts#L64-L77), [#L113-L115](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.service.ts#L113-L115), [#L193-L214](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.service.ts#L193-L214)):

```json
{
  "items": [
    {
      "id": "uuid", "slugId": "abc123xyz0", "title": "Runbook", "icon": null, "parentPageId": null,
      "creatorId": "uuid", "createdAt": "...", "updatedAt": "...",
      "rank": 0.0759, "highlight": "... restart the <b>worker</b> pool ...",
      "space": { "id": "uuid", "name": "Engineering", "slug": "engineering" },
      "wholeWord": true, "matchedText": ["worker"]
    }
  ]
}
```

- There is **no top-level `spaceId`** on search items; use `space.id`. `SearchResponseDto` declares no `slugId` but the query selects it ([search-response.dto.ts#L3-L16](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/dto/search-response.dto.ts#L3-L16)).
- `highlight` is produced by Postgres `ts_headline` over `text_content` with `<b>` markers; the surrounding text is raw page text and is not HTML-escaped **(inferred: `ts_headline` does not escape)**. Treat it as untrusted text, not HTML.
- If `SEARCH_DRIVER=typesense` and the Enterprise module is absent, the endpoint returns **400** `"Enterprise Typesense search module missing"` ([search.controller.ts#L70-L75](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.controller.ts#L70-L75), [#L153-L186](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.controller.ts#L153-L186), [environment.service.ts#L266-L270](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/environment/environment.service.ts#L266-L270)).

### 4.1 `POST /api/search/suggest`

- Request (`SearchSuggestionDTO`, [search.dto.ts#L62-L85](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/dto/search.dto.ts#L62-L85)): `query` (string, required), `includeUsers?`, `includeGroups?`, `includePages?` (booleans), `spaceId?` (prioritizes that space), `limit?` (number, default 10, no maximum).
- Response: `{users: [{id, name, email, avatarUrl}], groups: [{id, name, description}], pages: [{id, slugId, title, icon, spaceId, space}]}`; pages are title-substring matches in the user's spaces, permission-filtered ([search.service.ts#L219-L314](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/search/search.service.ts#L219-L314)). Note: `includeUsers` exposes workspace user emails; the MCP layer should not use it.

---

## 5. Content formats (S5)

### 5.1 Schema

The server-side ProseMirror schema is built from the Tiptap extension list `tiptapExtensions` ([server/collaboration/collaboration.util.ts#L69-L132](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.util.ts#L69-L132)): StarterKit (without its document, codeBlock, link, trailingNode, heading), a `Document` whose content is `block+ footnotes?`, Heading, UniqueID (on heading, paragraph, transclusionSource), Comment mark, TextAlign, Indent, TaskList/TaskItem, Link, Superscript, Subscript, Highlight, Typography, TextStyle, Color, MathInline/MathBlock, Details, tables, Youtube, Image, Video, Audio, PDF, PageBreak, Callout, Attachment, CodeBlock, Drawio, Excalidraw, Embed, Mention, Subpages, Columns/Column, Status, TransclusionSource/Reference, BaseEmbed, Footnotes. Library versions: Tiptap 3.31.3, `happy-dom` 20.8.9, `marked` 17.0.5, `@joplin/turndown` 4.0.82 ([package.json#L22-L81](https://github.com/docmost/docmost/blob/v0.96.0/package.json#L22-L81), [apps/server/package.json#L85](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/package.json#L85)).

### 5.2 Read path (`pages/info`, and the content echoed by `create`/`update`)

| `format` | Conversion | Evidence |
|---|---|---|
| `json` / absent | stored `pages.content` returned as-is | [page.controller.ts#L93-L105](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/page.controller.ts#L93-L105) |
| `html` | `jsonToHtml` = `Node.fromJSON` + ProseMirror `DOMSerializer` in a `happy-dom` window, serialized with `XMLSerializer` | [collaboration.util.ts#L134-L136](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.util.ts#L134-L136), [generateHTML.ts#L18-L29](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/helpers/prosemirror/html/generateHTML.ts#L18-L29), [getHTMLFromFragment.ts#L34-L53](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/helpers/prosemirror/html/getHTMLFromFragment.ts#L34-L53) |
| `markdown` | `jsonToMarkdown` = `jsonToHtml` then Turndown (`htmlToMarkdown`) with GFM tables/strikethrough/highlighted code blocks + custom rules | [collaboration.util.ts#L246-L249](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.util.ts#L246-L249), [turndown.utils.ts#L15-L41](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L15-L41) |

### 5.3 Write path (`pages/create`, `pages/update`)

`parseProsemirrorContent(content, format)` ([page.service.ts#L1108-L1138](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L1108-L1138)):

| `format` | Conversion |
|---|---|
| `markdown` | `markdownToHtml` (marked, `breaks: true`, custom callout/math/footnote extensions, task-list renderer; YAML front matter stripped) → `htmlToJson` ([marked.utils.ts#L12-L71](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/marked.utils.ts#L12-L71)) |
| `html` | `htmlToJson` = parse into a `happy-dom` document, then ProseMirror `DOMParser.fromSchema(schema).parse(body)`, then `addUniqueIdsToDoc` ([collaboration.util.ts#L138-L147](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.util.ts#L138-L147), [generateJSON.ts#L19-L55](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/helpers/prosemirror/html/generateJSON.ts#L19-L55)) |
| `json` | used as-is (must be a ProseMirror JSON object) |

All formats then go through `jsonToNode` as a validity check; failure → **400 `"Invalid content format"`**. `jsonToNode` calls `Node.fromJSON(schema, json)`; if it fails with `Unknown node type`, it **strips unknown node types** (unwrapping their children, mutating the input object in place) and retries ([collaboration.util.ts#L153-L215](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.util.ts#L153-L215)). Unknown marks or a non-object JSON raise other errors → 400 **(inferred)**. The **original** JSON object (not the normalized node) is what gets stored or applied, and `Node.fromJSON` does not enforce content expressions, so structurally invalid JSON (e.g. a paragraph directly inside a list) may be accepted **(inferred)**. Recommendation: the client should send `markdown` or `html` by default and allow `json` only as an explicit expert option.

Markdown-specific gotchas (all from [marked.utils.ts#L52-L71](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/marked.utils.ts#L52-L71)):
- `breaks: true`: **every single newline becomes a hard line break**. Soft-wrapped Markdown from an LLM produces broken paragraphs; the client should unwrap paragraphs or warn.
- Front matter stripping uses `/^\s*---[\s\S]*?---\s*/`: a document that **starts with a horizontal rule `---`** and contains any later `---` loses everything between them. Because the read path emits horizontal rules as `---` ([turndown.utils.ts#L16-L21](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L16-L21)), a read-modify-write round trip of a page beginning with a divider can delete content. The client should guard against leading `---`.
- Raw HTML inside Markdown is passed through by `marked` and then parsed by the same schema-driven HTML parser (**inferred**: marked does not sanitize; `htmlToJson` handles the result).

### 5.4 Loss matrix

Legend: ✅ preserved, ⚠️ degraded, ❌ lost. "HTML write" assumes input that matches Docmost's own `parseHTML` rules (e.g. HTML previously read with `format: html`). Rows marked † are **(inferred)** from the converter rules cited, not observed.

| Content | JSON | HTML read → HTML write | Markdown read | Markdown write | Evidence |
|---|---|---|---|---|---|
| Paragraphs, headings, bold, italic, inline code, links, lists, blockquote, rule, code block (language) | ✅ | ✅ | ✅ | ✅ (but single newlines → hard breaks) | [turndown.utils.ts#L15-L41](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L15-L41), [marked.utils.ts#L52](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/marked.utils.ts#L52) |
| Strikethrough | ✅ | ✅ | ✅ `~~` (GFM) | ✅ | [turndown.utils.ts#L25](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L25) |
| Underline, highlight, text color, sub/superscript, text align, indent † | ✅ | ✅ | ❌ no Turndown rule; text kept, formatting dropped | ❌ no Markdown syntax | [turndown.utils.ts#L23-L39](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L23-L39) (rule list) |
| Comment marks (inline comment anchors) | ✅ | ✅ `span[data-comment-id]` round-trips | ❌ plain text † | ❌ | [comment.ts#L72-L84](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/comment/comment.ts#L72-L84), [#L171-L183](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/comment/comment.ts#L171-L183) |
| Mentions (user/page) | ✅ | ✅ `data-*` attrs round-trip | ⚠️ rendered as text `@Label` / label | ❌ becomes plain text | [mention.ts#L112-L118](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/mention.ts#L112-L118), [#L170-L210](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/mention.ts#L170-L210) |
| Callouts | ✅ | ✅ | ✅ `:::type` | ✅ only `info/success/warning/danger`; other types coerced to `info` | [turndown.utils.ts#L89-L101](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L89-L101), [callout.marked.ts#L16-L40](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/callout.marked.ts#L16-L40) |
| Math inline / block | ✅ | ✅ | ✅ `$…$` / `$$…$$` | ✅ | [turndown.utils.ts#L154-L180](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L154-L180), [marked.utils.ts#L42-L50](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/marked.utils.ts#L42-L50) |
| Task lists | ✅ | ✅ | ⚠️ `- [x] text`; item uses `textContent`, so **inline formatting/links inside task items are lost** | ✅ structure | [turndown.utils.ts#L103-L125](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L103-L125), [marked.utils.ts#L12-L40](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/marked.utils.ts#L12-L40) |
| Details (collapsible) | ✅ | ✅ | ⚠️ kept as raw `<details><summary>` HTML | ⚠️ re-parsed from raw HTML † | [turndown.utils.ts#L127-L152](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L127-L152) |
| Tables † | ✅ | ✅ | ⚠️ GFM pipe tables; merged cells, widths, header column, cell colors lost | ⚠️ simple table | [turndown.utils.ts#L24](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L24) |
| Footnotes | ✅ | ✅ | ✅ `[^n]` + definitions | ✅ | [turndown.utils.ts#L208-L256](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L208-L256) |
| Images | ✅ | ✅ (src, width, align, alt via `data-*`) | ⚠️ `![alt](src "title")`; size/alignment/attachment id lost | ⚠️ plain image | [turndown.utils.ts#L194-L206](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L194-L206), [image.ts#L82-L122](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/image/image.ts#L82-L122) |
| Video | ✅ | ✅ † | ⚠️ `[name](src)` link | ❌ becomes a link | [turndown.utils.ts#L258-L271](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L258-L271) |
| Embeds / iframes (YouTube etc.) | ✅ | ✅ † | ⚠️ `[src](src)` link | ❌ becomes a link | [turndown.utils.ts#L182-L192](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/markdown/utils/turndown.utils.ts#L182-L192), [embed.ts#L83-L103](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/embed.ts#L83-L103) |
| Attachments (files) † | ✅ | ✅ | ⚠️ link to `/api/files/...` | ❌ becomes a link | [attachment.ts#L89-L109](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/attachment/attachment.ts#L89-L109) |
| Draw.io / Excalidraw † | ✅ | ✅ | ⚠️ preview `<img>` → `![…](src)` | ❌ becomes a static image; diagram no longer editable as a diagram | [drawio.ts#L146-L166](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/drawio.ts#L146-L166), [excalidraw.ts#L146-L166](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/excalidraw.ts#L146-L166) |
| Status badges † | ✅ | ✅ | ⚠️ text only | ❌ | [status.ts#L68-L85](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/status.ts#L68-L85) |
| Subpages block, columns, page break, transclusions, base embeds † | ✅ | ✅ (if their `parseHTML` rule matches) | ❌ empty or flattened | ❌ | [subpages.ts#L34-L51](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/subpages/subpages.ts#L34-L51) |
| Block IDs (heading/paragraph `UniqueID`) † | ✅ | ⚠️ new IDs are assigned on write (`addUniqueIdsToDoc`) when missing | ❌ | ❌ new IDs | [collaboration.util.ts#L82-L84](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.util.ts#L82-L84), [#L138-L147](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.util.ts#L138-L147) |

Conclusions for the client:
- `markdown` is the best format for **reading** by agents and for **appending new prose**. It is unsafe for a **`replace` of an existing page** that contains comments, mentions, diagrams, attachments, embeds, colors, or complex tables: those are destroyed.
- `html` read → edit → `html` write preserves almost everything (each node renders `data-*` attributes that its `parseHTML` rule reads back). Prefer it for `replace` of rich pages.
- `json` is lossless but verbose and only lightly validated.

### 5.5 Sanitization and XSS

- HTML input is never stored as HTML: it is parsed into ProseMirror nodes by the schema's `parseHTML` rules ([generateJSON.ts#L45-L47](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/common/helpers/prosemirror/html/generateJSON.ts#L45-L47)). Elements and attributes without a matching rule (`<script>`, `style`, `on*` handlers) are dropped **(inferred: ProseMirror `DOMParser` semantics)**. There is no separate HTML sanitizer.
- Links use Tiptap's `Link` extension (3.31.3), extended only with an `internal` attribute ([link.ts#L5-L19](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/link.ts#L5-L19)); rejection of `javascript:` URLs relies on Tiptap's own URI allow-list **(inferred)**.
- On the HTML read path, attachment and embed `href`s pass through `@braintree/sanitize-url` ([utils.ts#L385-L392](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/utils.ts#L385-L392), [attachment.ts#L105-L109](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/attachment/attachment.ts#L105-L109), [embed.ts#L91-L103](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/embed.ts#L91-L103)); image and diagram `src` are emitted raw ([drawio.ts#L162-L166](https://github.com/docmost/docmost/blob/v0.96.0/packages/editor-ext/src/lib/drawio.ts#L162-L166)). HTML returned by `format: html` must be treated as untrusted if ever rendered.
- **Forged structured nodes:** HTML/JSON input can create mention nodes for arbitrary user ids, which trigger mention notifications when the document is stored ([persistence.extension.ts#L189-L209](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/extensions/persistence.extension.ts#L189-L209)), and image/embed nodes pointing at arbitrary external URLs (tracking pixels, iframes in other users' browsers). The client cannot detect this without parsing; at minimum, document it and consider rejecting `data-type="mention"` and external `iframe`/embed sources in agent-supplied HTML.
- For `append`/`prepend`, JSON node attributes and marks are copied verbatim into the Yjs document (`prosemirrorNodeToYElement` copies every non-null attr) ([collaboration.util.ts#L217-L244](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.util.ts#L217-L244)).

### 5.6 Operations

From `CollaborationHandler.updatePageContent` ([collaboration.handler.ts#L78-L114](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.handler.ts#L78-L114)):

| Operation | Behavior | Notes |
|---|---|---|
| `replace` | Deletes the whole `default` Yjs fragment, then merges a Yjs document built from the new ProseMirror JSON | Removes comment anchors, transclusion sources, block IDs unless the new content carries them |
| `append` | Inserts the parsed doc's **top-level** blocks at the end of the fragment | Applies to every format; the conversion is identical |
| `prepend` | Inserts the top-level blocks at position 0 | Same |

- Because only top-level nodes are inserted, appended content that contains footnotes may place a `footnotes` block in the middle of the document, outside the `block+ footnotes?` content rule **(inferred)**. Avoid footnotes in append/prepend.
- `content: ""` (or any falsy content) is silently ignored: the service only applies content when `content && operation && format` are all truthy ([page.service.ts#L254-L266](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L254-L266)). To clear a page, `replace` with JSON `{"type":"doc","content":[{"type":"paragraph"}]}`.

---

## 6. Update semantics and concurrency (S15)

### 6.1 What `pages/update` writes

1. Always: `title`, `icon` (undefined values are skipped by Kysely, **inferred**), `lastUpdatedById`, `contributorIds`, and **`updatedAt = now`**, even when nothing else changes ([page.service.ts#L228-L241](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L228-L241), [page.repo.ts#L141-L162](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/database/repos/page/page.repo.ts#L141-L162)). `updatePages` forces `updatedAt: new Date()` on every row update, including moves.
2. `spaceId` and `parentPageId` are validated (inherited from `CreatePageDto` via `PartialType`) but **never written**. An update cannot move a page to another space or parent in v0.96.0. The client must still never forward them (a future version may honor them).
3. If content is present: content is applied through the collaboration layer (6.2), which then persists `content`, `text_content`, `ydoc` and bumps `updatedAt` again.
4. Response: the page re-read after the write, including the new `updatedAt` ([page.service.ts#L268-L274](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L268-L274)).

### 6.2 Content goes through Yjs/Hocuspocus

- `updatePageContent` calls `collaborationGateway.handleYjsEvent('updatePageContent', 'page.<id>', …)` ([page.service.ts#L277-L292](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/services/page.service.ts#L277-L292)).
- `handleYjsEvent` returns `this.redisSync?.handleEvent(...)` ([collaboration.gateway.ts#L145-L151](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.gateway.ts#L145-L151)). **When `COLLAB_DISABLE_REDIS=true`, `redisSync` is `null`, the call is a no-op, and the API still returns 200 with the title/`updatedAt` changes but without the content change** ([#L46-L83](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.gateway.ts#L46-L83), [environment.service.ts#L237-L242](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/environment/environment.service.ts#L237-L242)). Default is `false`.
- With Redis sync, if the document is loaded on this server or the lock is free, the change is applied locally; if another server (e.g. a separate collaboration process) owns the document, the event is proxied over Redis and awaited with a **30 s timeout** that rejects with `Error('TIMEOUT')` (→ 500, **inferred**) ([redis-sync.extension.ts#L265-L311](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/extensions/redis-sync/redis-sync.extension.ts#L265-L311), [#L82](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/extensions/redis-sync/redis-sync.extension.ts#L82)).
- The handler opens a Hocuspocus **direct connection**, applies the change in one Yjs transaction, then disconnects ([collaboration.handler.ts#L118-L133](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.handler.ts#L118-L133)). In Hocuspocus 4.5.0, `DirectConnection.disconnect()` defaults to `unloadImmediately = true` and awaits `storeDocumentHooks(..., true)`, which runs the store with debounce 0 ([hocuspocus DirectConnection.ts#L47-L74](https://github.com/ueberdosis/hocuspocus/blob/v4.5.0/packages/server/src/DirectConnection.ts#L47-L74), [Hocuspocus.ts#L507-L547](https://github.com/ueberdosis/hocuspocus/blob/v4.5.0/packages/server/src/Hocuspocus.ts#L507-L547)). The persistence hook writes `content`, `text_content`, `ydoc` in a row-locked transaction ([persistence.extension.ts#L98-L162](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/extensions/persistence.extension.ts#L98-L162)).
- Therefore, in the normal (Redis-enabled) case, the content is **persisted before the HTTP response**, and reading back immediately sees it. Two exceptions: (a) the persistence extension catches and logs DB errors ([#L163-L165](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/extensions/persistence.extension.ts#L163-L165)) and Hocuspocus catches store errors and keeps the document in memory ([Hocuspocus.ts#L532-L536](https://github.com/ueberdosis/hocuspocus/blob/v4.5.0/packages/server/src/Hocuspocus.ts#L532-L536)); the API still returns 200; (b) the `COLLAB_DISABLE_REDIS` no-op above. A client that must be sure should compare the returned `content` with what it expected (e.g. the appended text is present).
- When nothing changed, the store is skipped (`isDeepStrictEqual`), so `updatedAt` reflects only step 1 ([persistence.extension.ts#L130-L133](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/extensions/persistence.extension.ts#L130-L133)).
- Side effects of every content store: page-history job, AI/search reindex job, mention notifications, transclusion sync ([persistence.extension.ts#L167-L217](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/extensions/persistence.extension.ts#L167-L217)).

### 6.3 Concurrency with users in the editor

- Live editors and API writes share the same in-memory Yjs document. `append`/`prepend` merge as CRDT inserts: no lost update, but the inserted blocks are placed relative to the document state at apply time **(inferred: Yjs semantics)**.
- `replace` deletes all existing Yjs items, including text other users wrote after the agent last read the page. Concurrent keystrokes arriving after the delete may survive as orphan fragments interleaved with the new content **(inferred)**.
- Browser edits are persisted with `debounce: 10000` and `maxDebounce: 45000` ms ([collaboration.gateway.ts#L49-L58](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/collaboration/collaboration.gateway.ts#L49-L58)). **`pages/info` content and `updatedAt` can therefore be up to ~45 s behind what a user sees.** An API update that touches content flushes the whole in-memory document, including those pending user edits.
- There is no ETag, `If-Match`, version number, or compare-and-swap parameter on any page endpoint (no such field exists in `UpdatePageDto`, [update-page.dto.ts#L8-L24](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/page/dto/update-page.dto.ts#L8-L24)).

Recommended `updatedAt` precheck and its residual race (document this to users):
1. `pages/info` → remember `updatedAt` (the agent's base version).
2. Immediately before writing, `pages/info` again; if `updatedAt` differs from the base, refuse with a typed `CONFLICT` error.
3. `pages/update`; then compare the returned `updatedAt` / content.

Residual races that the precheck cannot close: (a) the window between step 2 and step 3 (no atomicity); (b) user edits not yet persisted (≤ ~45 s) are invisible to `updatedAt`; (c) any title-only or move operation also bumps `updatedAt`, which only causes false conflicts (safe). Prefer `append`/`prepend` for agents; restrict `replace` to explicit requests and to the `html`/`json` formats on pages with rich content.

---

## 7. Security notes for API clients

1. **Token transport.** Login returns the JWT only via `Set-Cookie: authToken=…` (section 2.1). Extract it once, keep it in memory, and send `Authorization: Bearer <jwt>`. **Disable or clear the HTTP cookie jar**: the server reads the cookie before the header ([jwt.strategy.ts#L32-L34](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/strategies/jwt.strategy.ts#L32-L34)), so a stale cookie would override a fresh Bearer token, and a persisted jar would write the token to disk.
2. **Cookie `Secure` flag** depends on the server's `APP_URL`, not on the request scheme ([environment.service.ts#L26-L34](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/integrations/environment/environment.service.ts#L26-L34)). Enforce HTTPS client-side (S7).
3. **401 handling.** 401 means expired JWT, revoked session, disabled user, or workspace mismatch. Re-login at most once per request; login is limited to 10/min/IP (429). Never retry login in a loop.
4. **Sessions.** Each login creates a session row (cap 25/user). Reuse the token; call `POST /api/auth/logout` on shutdown.
5. **MFA / SSO.** `enforceSso` → 400 on login. If the Enterprise MFA module is present in the image and the account has (or is required to set up) MFA, login returns 200 with `{userHasMfa, requiresMfaSetup, isMfaEnforced}` and no cookie. Use a dedicated service account without MFA, and map this case to a typed error.
6. **CSRF.** The server has no CSRF token checks (no CSRF code in `apps/server/src`); the cookie is `SameSite=Lax`. Irrelevant for a Bearer-only, non-browser client.
7. **Body size.** Fastify default 1 MiB **(inferred)**; enforce a lower client-side cap and fail fast. Reverse proxies may impose smaller limits.
8. **Unbounded parameters.** `search.limit` and `search/suggest.limit` have no server-side maximum; cap them client-side.
9. **Untrusted output.** Page content, titles, search `highlight`, comment bodies, and user names are user-controlled; they can carry prompt-injection payloads and, in `html`, raw image URLs. Never treat them as instructions or render them as trusted HTML.
10. **Permission model.** Docmost enforces space roles and page-level restrictions server-side (sections 3–4); a least-privilege service account is the primary barrier, the client allowlist (S9) the second. Note that non-membership surfaces as **404 `"Space permissions not found"`**, not 403.
11. **Trash and locks.** `pages/info` and `pages/update` do not check `deletedAt`; `isLocked` is never enforced. The client should refuse to write pages with `deletedAt != null` (and may choose to honor `isLocked`).
12. **Enterprise-only surfaces.** API keys, OAuth tokens and the native `/mcp` route require the private `ee` module (`.gitmodules` points `apps/server/src/ee` to the private `docmost/ee` repository) and are not used by this client ([main.ts#L44-L56](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/main.ts#L44-L56), [jwt.strategy.ts#L98-L154](https://github.com/docmost/docmost/blob/v0.96.0/apps/server/src/core/auth/strategies/jwt.strategy.ts#L98-L154), [.gitmodules](https://github.com/docmost/docmost/blob/v0.96.0/.gitmodules)).

---

## 8. Open questions (need a running instance or deployment facts)

Answers observed on a running instance are in [section 9](#9-observed-on-a-running-docmost-0960).

1. **EE bundling in `docmost/docmost:0.96.0`.** The `ee` submodule is private, so the source cannot show whether the published image includes the MFA / Typesense / API-key modules, nor how MFA behaves without a license. Determines whether login can return an MFA challenge.
2. **Deployment settings** that change behavior: `APP_URL` scheme (cookie `Secure`), `JWT_TOKEN_EXPIRES_IN` (user reports `30d`), `COLLAB_DISABLE_REDIS` (silent content no-op if `true`), `SEARCH_DRIVER`, whether collaboration runs in a separate process (30 s proxy timeout path), and any reverse-proxy body-size or rate limits.
3. **Exact error bodies** for Fastify-level 413, throttler 429, and validation 400 (NestJS defaults are assumed; record fixtures).
4. **`format`/`operation` defaults.** Whether a request with `content` but no `format` is rejected (expected from class-transformer 0.5.1 semantics) or defaults to `json`. The client sends both explicitly regardless; a fixture should pin the observed behavior.
5. **Login body.** Whether the success body is exactly `{"success":true,"status":200}` (no `data`), and the exact `Set-Cookie` attributes as seen behind the proxy.
6. **Markdown fidelity in practice** for tables, columns, details and embeds (the loss matrix rows marked †), and whether `<details>` raw HTML round-trips through `marked` + the schema.
7. **Concurrent `replace` outcome** while a user is typing (Yjs merge result), and how the editor UI reacts.
8. **`Node.fromJSON` strictness** in the bundled `prosemirror-model` (attribute and content-expression checks) for `json` input.
9. **`/api/version` latency/failure** when the server has no outbound internet (it calls `api.github.com` per request).

Recommendation for questions 3–8: record contract fixtures against a **local, disposable** Docmost 0.96.0 (Docker Compose), never against the production instance (S14).

---

## 9. Observed on a running Docmost 0.96.0

Observed on 2026-10-16 against the local, disposable instance from `dev/docmost`
(`docmost/docmost:0.96.0`, Postgres 18, Redis 8). Recorded bodies live in
`packages/docmost-client/tests/fixtures/v0_96_0/recorded/`; behavior is pinned by
`tests/contract/` and the opt-in `tests/integration/` suites.

| Question (section 8) | Observed |
|---|---|
| 1. EE bundling | The image bundles the MFA module: a successful login also sends `Set-Cookie: mfaToken=; Max-Age=0` before `authToken`. Accounts with MFA cannot use password-only login. |
| 3. Error bodies | 413 `{"message": "Request body is too large", ...}` (body over 1 MiB); 429 `"Too many requests"` after 10 logins/min; 400 validation messages as arrays, e.g. `["operation must be one of the following values: append, prepend, replace"]`; reader writing → 403 `"Forbidden"`; non-member space → 404 `"Space permissions not found"`; bad credentials → 401 `"Email or password does not match"`. |
| 4. `content` without `format` | Rejected: 400 `["format must be one of the following values: json, markdown, html"]`. |
| 5. Login body | `{"success":true,"status":200}` (no `data`); `authToken` cookie is `HttpOnly; SameSite=Lax; Path=/` with `Expires` = now + `JWT_TOKEN_EXPIRES_IN`, no `Secure` when `APP_URL` is `http://`. |
| 6. Markdown fidelity | Read as markdown: a table's header row becomes a body row under an empty header; bold inside task items is lost; underline and text color are dropped; highlight survives as `==text==`; callouts as `:::warning`; details as raw `<details>` HTML. A rich page copied through `html` (read html → create with that html) reads back identical. Writing markdown: a single newline becomes a hard break (`line one  \nline two`). |
| 6. Front matter | Writing `---\nIntro\n---\nBody` as markdown stores only `Body`: the text between the dashes is deleted (the client refuses such input). |
| 8. JSON strictness | Unknown node types are stripped and their children kept; structurally invalid content (text directly inside a `bulletList`) is accepted; an unknown mark is rejected with 400 `"Invalid content format"`. |
| — HTML input | `<script>` elements and `on*` attributes are dropped. |
| — Empty content | `content: ""` is ignored: the page is created without content (the client refuses empty content). |
| — Default space | Docmost adds every new workspace member to the workspace's default space (`general` on a fresh install) with the **writer** role. |

Still open: 2 (deployment settings of the production instance), 7 (concurrent `replace`
while a user types), and 9 (`/api/version` without outbound internet).
