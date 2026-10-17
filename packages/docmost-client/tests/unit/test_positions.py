"""Docmost page positions: base62 fractional keys compared as plain strings."""

import random

import pytest

from docmost_client import InvalidRequestError
from docmost_client._positions import MAX_POSITION_LENGTH, MIN_POSITION_LENGTH, key_between


def valid(key: str, lower: str | None, upper: str | None) -> bool:
    return (
        MIN_POSITION_LENGTH <= len(key) <= MAX_POSITION_LENGTH
        and (lower is None or lower < key)
        and (upper is None or key < upper)
    )


def test_first_page_of_an_empty_parent() -> None:
    key = key_between(None, None)

    assert key.startswith("a0")
    assert valid(key, None, None)


@pytest.mark.parametrize(
    ("lower", "expected"),
    [("a07gp", "a1000"), ("a1xyz", "a2000"), ("a9", "aA000"), ("b0Azz", "b0B00")],
)
def test_after_the_last_page_the_integer_is_incremented(lower: str, expected: str) -> None:
    assert key_between(lower, None) == expected


# Keys recorded from Docmost 0.96.0 and keys it generates (jittered, 5 characters).
@pytest.mark.parametrize(
    ("lower", "upper"),
    [
        ("a07gp", "a0AHy"),
        ("a07gp", "a07gq"),
        ("a0AHy", "a89DE"),
        ("a0000", "a0001"),
        ("a1", "a2"),
        ("a1000", "a1001"),
        (None, "a07gp"),
        (None, "a0AHy"),
        (None, "a1"),
        ("Zz", "a0"),
    ],
)
def test_between_two_pages(lower: str | None, upper: str) -> None:
    assert valid(key_between(lower, upper), lower, upper)


def test_repeated_inserts_stay_ordered_until_there_is_no_room() -> None:
    lower, upper = "a07gp", "a07gq"
    for _ in range(4):
        key = key_between(lower, upper)
        assert valid(key, lower, upper)
        upper = key

    def fill() -> None:
        nonlocal upper
        for _ in range(100):
            upper = key_between(lower, upper)

    with pytest.raises(InvalidRequestError, match="no room"):
        fill()


def test_random_sibling_lists_always_get_a_key_in_between() -> None:
    rng = random.Random(7)  # noqa: S311 - a reproducible sequence, not a secret
    keys = [key_between(None, None)]
    for _ in range(300):
        index = rng.randrange(len(keys) + 1)
        lower = keys[index - 1] if index > 0 else None
        upper = keys[index] if index < len(keys) else None
        try:
            key = key_between(lower, upper)
        except InvalidRequestError:
            continue
        assert valid(key, lower, upper)
        keys.insert(index, key)
    assert keys == sorted(keys)
    assert len(keys) > 200


@pytest.mark.parametrize(
    ("lower", "upper"),
    [("a1", "a1"), ("a2", "a1"), ("zz", None), ("!x", None), ("a", None)],
)
def test_unusable_neighbours_are_refused(lower: str, upper: str | None) -> None:
    with pytest.raises(InvalidRequestError):
        key_between(lower, upper)
