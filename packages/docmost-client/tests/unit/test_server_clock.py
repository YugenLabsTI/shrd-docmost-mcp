"""The busy window is measured on Docmost's clock, taken from its Date header."""

from datetime import UTC, datetime

import httpx

from docmost_client._protocol import ServerClock


class Monotonic:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def response(date: str | None) -> httpx.Response:
    headers = {"date": date} if date is not None else {}
    return httpx.Response(200, headers=headers, json={})


def test_now_is_the_last_date_header_plus_the_time_since_it_arrived() -> None:
    monotonic = Monotonic()
    clock = ServerClock(monotonic=monotonic)

    clock.observe(response("Fri, 16 Oct 2026 10:00:30 GMT"))
    monotonic.value += 4.5

    assert clock.now() == datetime(2026, 10, 16, 10, 0, 34, 500000, tzinfo=UTC)


def test_the_latest_response_wins() -> None:
    monotonic = Monotonic()
    clock = ServerClock(monotonic=monotonic)

    clock.observe(response("Fri, 16 Oct 2026 10:00:30 GMT"))
    monotonic.value += 10
    clock.observe(response("Fri, 16 Oct 2026 10:05:00 GMT"))

    assert clock.now() == datetime(2026, 10, 16, 10, 5, tzinfo=UTC)


def test_no_estimate_without_a_usable_date_header() -> None:
    clock = ServerClock()

    clock.observe(response(None))
    clock.observe(response("not a date"))

    assert clock.now() is None


def test_an_unusable_header_keeps_the_previous_estimate() -> None:
    monotonic = Monotonic()
    clock = ServerClock(monotonic=monotonic)
    clock.observe(response("Fri, 16 Oct 2026 10:00:30 GMT"))

    clock.observe(response("garbage"))

    assert clock.now() == datetime(2026, 10, 16, 10, 0, 30, tzinfo=UTC)
