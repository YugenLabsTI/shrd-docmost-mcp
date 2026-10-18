# Feature: publish to PyPI, TestPyPI first

Objective: publish both packages to PyPI from CI with Trusted Publishing, always through TestPyPI first, now that the repository is public; protect `main` and the publishing environments.
Branch: `feat/pypi-publishing` (from `main` aa34d85). Delivery: ask-on-risk; single PR expected (under ~400 lines). Test runner: `uv run pytest`; workflows checked with actionlint and zizmor.

## Specs

- **S1 — Go public and publish to PyPI.** "Si, el código ya puede ser publico, miremos para convertir el repo a publico y así ahorramos problemas!" Repository made public on 2026-10-18 after the pre-public audit (L3).
- **S2 — TestPyPI first, always.** "ya ire entonces creando las cunetas en Test para que el flujo y principio rector siempre sea probar en test primero". Every publication uploads to TestPyPI, installs from it, and only then publishes to PyPI.
- **S3 — Pending publisher limit.** "A pending trusted publisher matching this configuration has already been registered for a different project name. Please contact PyPI's admins if this wasn't intentional." The first publication of `docmost-client` must be possible on its own, so the `yugen-docmost-mcp` pending publisher can be registered afterwards.
- **S4 — Inherited constraints.** No AI attribution, no instance data in the repo, pinned actions, least-privilege workflow permissions, docs updated with behavior; push, PR and merge only with explicit OK.

Assumptions (agent decisions): a separate `publish.yml` dispatched on `main` with the release tags as input (tags created with `GITHUB_TOKEN` start no workflows); the release job dispatches it after tagging; environments `testpypi` and `pypi` (deployment from `main` only; `pypi` needs the maintainer's approval); one run builds every tag from its own commit, uploads to TestPyPI, installs the exact versions from TestPyPI (an explicit index, so nothing else resolves from TestPyPI), then publishes to PyPI; uploads skip files that already exist so a failed run can be re-run; bootstrap publishes the existing 0.1.0 tags by hand, client first; `main` gets a ruleset (no deletion or force push, pull request and passing CI required); the lowest-client CI job stays deferred (the lowest allowed client is the current one).

## Tasks

| ID | Specs | Route | Status | Evidence |
|----|-------|-------|--------|----------|
| T1 | S1, S2, S4 | inline | done | GitHub settings, L5 |
| T2 | S2, S3, S4 | inline | done | 3b0b242, L5 |
| T3 | S1, S3, S4 | inline | done | 7b4961b, docs commit, L5 |

T1 GitHub settings: environments `testpypi` and `pypi`, `main` ruleset, private vulnerability reporting, secret scanning and push protection. T2 `publish.yml` and the release job dispatch. T3 docs and metadata: README install from PyPI and the publishing flow with the bootstrap, package READMEs with absolute links, `project.urls`, SECURITY, CHANGELOG.

High-risk: T1 and T2 (release/CI, item 5). Independent verifier at the feature's end.

## Log

- **L1 (2026-10-18, user, verbatim):** "Vale, ahora creo que ya teniendo un producto completo que ya podemos ir validando, tengo un par de colegas que pueden estar interesados en probarlo! Para ello creo que ya debemosirnos a PiPy ¿Que debemos hacer? ¿Cuenta en Test y normal? ¿Debemos crear una organización?"
- **L2 (2026-10-18, user, verbatim):** "Si, el código ya puede ser publico, miremos para convertir el repo a publico y así ahorramos problemas! Ademas, ya ire entonces creando las cunetas en Test para que el flujo y principio rector siempre sea probar en test primero" Later: "Ah vale, ya revise y no, así que tranquilo. Y ya quedo los dos publisher configurados. Sigamos!!"
- **L3 (pre-public audit):** gitleaks over 84 commits found one false positive (a fake test JWT); hostnames in the whole history and in PR, issue and comment text are public or example domains; no AI attribution in commits or GitHub text; `dev/live/.env*` never tracked; the user checked space names, page IDs and the instance domain against the history: no matches. Package names are free on PyPI and TestPyPI. Repository made public with `gh repo edit --visibility public`.
- **L4 (research):** PyPI accepts one pending publisher per configuration (owner, repository, workflow, environment) at a time; a pending publisher becomes a normal one on first use, after which the second project can be registered. Corporate PyPI organizations cost $5 per member per month; not needed now.
- **L5 (evidence):** T1: environments `testpypi` and `pypi` limited to `main`, `pypi` with the maintainer as required reviewer; ruleset `main` (deletion, non_fast_forward, pull_request, required_status_checks lint/audit/build/test 3.11-3.14 from GitHub Actions); private vulnerability reporting, secret scanning and push protection enabled; all read back through the API. T2: actionlint ok, zizmor no findings; release-please-action v5.0.0 source sets `releases_created`, `paths_released` and `<path>--tag_name`. Build step probed with bash 5 in a scratch clone: one tag builds that package; two tags given server first build the client first; `;rm`, unknown package, missing tag, duplicate tag, no tags and a tag outside `main` fail with their messages. Smoke step probed against a local flat index standing in for TestPyPI: client only, both, server only install the exact versions and run `yugen-docmost-mcp --version`; a missing version fails after the retries. No RED test: workflow shell is not covered by the pytest suite (exception, probes instead). T3: `project.urls` and absolute README links as a `fix(packaging)` commit so the next release (0.1.1) carries them; README install from PyPI (`uvx yugen-docmost-mcp@0.1.0`), publishing flow and bootstrap; SECURITY reporting through GitHub and the publishing row. `uv lock --check` ok, `twine check --strict` passed, suite 609 passed, 26 skipped.
- **L6 (bootstrap plan):** after merge, start Publish by hand with `docmost-client-v0.1.0`, approve `pypi`; the user registers the `yugen-docmost-mcp` pending publishers on both indexes; start Publish with `yugen-docmost-mcp-v0.1.0`. The release PR for 0.1.1 is merged only after both, so its automatic publication finds both publishers.
