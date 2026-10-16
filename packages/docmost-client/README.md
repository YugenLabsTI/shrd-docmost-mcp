# docmost-client

> **Unofficial, not affiliated with Docmost.**

Typed sync and async Python client for the internal API of self-hosted
**Docmost Community Edition** (tested with Docmost 0.96.0).

```python
from docmost_client import DocmostClient

with DocmostClient.from_env() as docmost:  # reads DOCMOST_* environment variables
    hits = docmost.search("deploy runbook", limit=5)
    for hit in hits:
        print(hit.title, hit.space.slug)
    if hits:
        page = docmost.get_page(hits[0].id, format="markdown")
        print(page.updated_at, page.content)
```

`AsyncDocmostClient` has the same methods as coroutines.

- Read-only by default; set `DOCMOST_READ_ONLY=0` to allow `create_page` / `update_page`.
- `DOCMOST_ALLOWED_SPACES` restricts every operation to the listed spaces.
- The JWT stays in memory and is revoked when the client is closed.
- Errors are subclasses of `DocmostError` with a stable `code`.

See the [project README](../../README.md) for configuration, formats, and limitations.
