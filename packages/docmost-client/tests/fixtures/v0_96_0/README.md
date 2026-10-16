# Docmost v0.96.0 contract fixtures

Response bodies (the `data` of `{"data", "success", "status"}`) for the endpoints
docmost-client uses.

| Location | Origin | Used by |
|----------|--------|---------|
| `*.json` | Synthesized from the v0.96.0 source types (`docs/docmost-api-v0.96.0.md`) with stable, readable IDs | Unit tests |
| `recorded/*.json` | Recorded from a local, disposable Docmost 0.96.0 by `dev/docmost/record_fixtures.py` | Contract tests |
| `recorded/errors/*.json` | Raw error responses (`status` + `body`) from the same instance | Contract tests |

`tests/contract/test_recorded_v0_96_0.py` checks that the models parse the recorded
responses, that recorded errors map to the right typed errors, and that the synthesized
fixtures only use fields Docmost really returns. Never record from a production instance.
