"""Sibling positions for moving pages (I/O-free).

Docmost 0.96 orders sibling pages by ``position`` compared as plain strings (``COLLATE
"C"``). Positions are keys of ``fractional-indexing-jittered``: an integer part (a head
character from ``0-9A-Za-z`` plus as many digits as the head implies, e.g. ``a0``,
``b00``) followed by a base62 fraction. ``pages/move`` only accepts keys of 5 to 12
characters, so a move needs a valid key strictly between the two neighbours of the new
slot; this module computes one without jitter and refuses when there is no room.

Only the integer heads ``A``-``Z`` and ``a``-``y`` are handled. The extreme heads
``z``/``A`` encode huge integers that Docmost reaches only after millions of pages.
"""

from docmost_client.errors import InvalidRequestError

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
MIN_POSITION_LENGTH = 5
MAX_POSITION_LENGTH = 12
_BASE = len(DIGITS)
_VALUE = {char: index for index, char in enumerate(DIGITS)}
_NO_ROOM = (
    "There is no room for a new position between those pages (Docmost positions are at "
    "most 12 characters). Place the page somewhere else, or reorder its neighbours in "
    "Docmost first."
)


def key_between(lower: str | None, upper: str | None) -> str:
    """A position strictly between ``lower`` and ``upper`` (None: no neighbour there)."""
    if lower is not None and upper is not None and not lower < upper:
        raise InvalidRequestError("The neighbouring positions are not in order.")
    candidates = _candidates(lower, upper)
    for candidate in candidates:
        key = candidate.ljust(MIN_POSITION_LENGTH, "0")
        in_order = (lower is None or lower < key) and (upper is None or key < upper)
        if in_order and len(key) <= MAX_POSITION_LENGTH:
            return key
    raise InvalidRequestError(_NO_ROOM)


def _candidates(lower: str | None, upper: str | None) -> list[str]:
    """Keys to try, shortest first; each is checked against both neighbours."""
    if upper is None:
        if lower is None:
            return ["a0"]
        integer, fraction = _split(lower)
        found = [_fraction_after(integer, fraction)]
        following = _increment(integer)
        return ([following] if following else []) + found
    integer, fraction = _split(upper)
    if lower is None:
        found = [integer + _between_fractions("", fraction)] if fraction.strip("0") else []
        previous = _decrement(integer)
        return found + ([previous] if previous else [])
    low_integer, low_fraction = _split(lower)
    if low_integer == integer:
        return [integer + _between_fractions(low_fraction, fraction)]
    return [_fraction_after(low_integer, low_fraction)]


def _split(key: str) -> tuple[str, str]:
    """(integer part, fraction) of a Docmost position, validating its shape."""
    if not key or any(char not in _VALUE for char in key):
        raise InvalidRequestError("A sibling page has a position this client cannot read.")
    head = key[0]
    if head in "zA":
        raise InvalidRequestError(
            "A sibling page has a position beyond what this client supports; move the page "
            "in Docmost instead."
        )
    if "a" <= head <= "y":
        length = _VALUE[head] - _VALUE["a"] + 2
    elif "B" <= head <= "Z":
        length = _VALUE["Z"] - _VALUE[head] + 2
    else:
        raise InvalidRequestError("A sibling page has a position this client cannot read.")
    if len(key) < length:
        raise InvalidRequestError("A sibling page has a position this client cannot read.")
    return key[:length], key[length:]


def _increment(integer: str) -> str | None:
    """The next integer with the same head, or None when its digits are all maxed."""
    head, digits = integer[0], integer[1:]
    value = _to_number(digits) + 1
    if value >= _BASE ** len(digits):
        return None
    return head + _to_digits(value, len(digits))


def _decrement(integer: str) -> str | None:
    head, digits = integer[0], integer[1:]
    value = _to_number(digits) - 1
    if value < 0:
        return None
    return head + _to_digits(value, len(digits))


def _fraction_after(integer: str, fraction: str) -> str:
    return integer + _between_fractions(fraction, None)


def _between_fractions(lower: str, upper: str | None) -> str:
    """A base62 fraction strictly between ``lower`` and ``upper`` (None: no upper bound)."""
    width = max(len(lower), len(upper or ""), 1)
    while True:
        low = _to_number(lower.ljust(width, "0"))
        high = _BASE**width if upper is None else _to_number(upper.ljust(width, "0"))
        if high - low >= 2:
            return _to_digits((low + high) // 2, width).rstrip("0") or "0"
        width += 1


def _to_number(digits: str) -> int:
    value = 0
    for char in digits:
        value = value * _BASE + _VALUE[char]
    return value


def _to_digits(value: int, width: int) -> str:
    chars: list[str] = []
    for _ in range(width):
        value, remainder = divmod(value, _BASE)
        chars.append(DIGITS[remainder])
    return "".join(reversed(chars))
