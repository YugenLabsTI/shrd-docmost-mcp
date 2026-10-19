# Contributing

Thanks for helping. Bug reports, proposals and pull requests are welcome. Security issues
go through [private vulnerability reporting](SECURITY.md), never a public issue.

## Quick path

1. Open an issue and wait until a maintainer labels it `status:approved` (see
   [Issues first](#issues-first)). Every pull request needs one, maintainers' included.
2. Set up and check:

   ```bash
   uv sync
   uv run pytest            # HTTP mocked with respx; no Docmost needed
   uv run ruff check .
   uv run ruff format --check .
   uv run pyright           # strict on src
   ```

3. Open a pull request against `main` whose description links the issue (`Closes #12`).
   CI must pass (lint, tests on Python 3.11 to 3.14, dependency audit, wheel check, and
   the `issue` check) before it can be merged. CI also runs the integration tests against
   a disposable Docmost (`integration`); that check is not required yet.

## Issues first

Every change starts as an issue, so we agree on what to build before anyone writes it.

| Label | Meaning |
|-------|---------|
| `status:needs-review` | New; a maintainer has not looked at it yet (the issue forms add it) |
| `status:needs-info` | Waiting for the reporter to answer a question |
| `status:needs-design` | Valid, but needs a design decision before a pull request |
| `status:approved` | Accepted: a pull request can be opened |

A pull request links the issue it implements in its description, with `Closes #12`
(also `Fixes` or `Resolves`; the issue closes on merge) or `Refs #12` (it stays open).
References inside HTML comments or code do not count. The required `issue` check fails until
every linked issue is labelled `status:approved`; when the label arrives after the pull
request, re-run the check or edit the description. Release pull requests and Dependabot
updates are exempt.

## Keep your instance's data out of the repository

Use the server and the client with your own Docmost: that is what they are for. What
must not reach this public repository is data from it. Code, tests, fixtures, logs,
issues and pull requests contain no URLs, credentials, space names, page IDs or page
content of a real instance. Use `https://wiki.example.com`, `agent@example.com` and the
seeded spaces of the local Docmost instead.

For the same reason, contract fixtures are recorded only from the disposable Docmost in
[dev/docmost](dev/docmost/README.md), which binds to `127.0.0.1` and is seeded with
sample data:

```bash
set -a; . dev/docmost/.env.test; set +a
DOCMOST_INTEGRATION=1 uv run pytest -m integration   # integration tests
uv run python dev/docmost/record_fixtures.py         # re-record the fixtures
```

## Commits and pull request titles

Commits follow [Conventional Commits](https://www.conventionalcommits.org/). They decide
the next version of each package (see
[Releases and versioning](README.md#releases-and-versioning)):

| Type | Releases |
|------|----------|
| `fix:`, `perf:`, `deps:`, `docs:`, `revert:` | a patch of the packages whose files changed |
| `feat:` | a patch before 1.0, a minor from 1.0 |
| `feat!:` or a `BREAKING CHANGE:` footer | a minor before 1.0, a major from 1.0 |
| `chore:`, `ci:`, `test:`, `refactor:`, `build:`, `style:` | nothing |

Pull requests are merged with a merge commit, so every commit of the branch reaches
`main` and the changelog: keep each commit a working unit with its tests and docs, and
give it a clear message. Do not add release commits or edit `CHANGELOG.md`; the release
pull request does that.

## Changing behavior

- **Tests.** Test the behavior through the public API (`docmost_client`) or the MCP
  tools, covering the cases the rule names and the errors it returns.
- **Docs.** A new or changed tool, setting, error code or message updates the README
  (tables and sections), the package README, and the help text.
- **Writes stay opt-in.** Read-only is the default. A new write needs its own switch or
  must sit behind `DOCMOST_READ_ONLY=0`, is recorded by the audit log, and documents
  what an agent could break with it.
- **Docmost's internal API.** It can change in any release. A new endpoint gets
  recorded fixtures and a contract test; supporting a new Docmost version adds it to the
  [compatibility](README.md#compatibility) matrix with its own fixtures.

## Code review

A maintainer reviews every pull request ([CODEOWNERS](.github/CODEOWNERS)). Reviews
look first at safety (what an agent can do, what reaches Docmost), then at tests and
docs.
