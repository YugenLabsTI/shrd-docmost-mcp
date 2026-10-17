"""Space allowlist (DOCMOST_ALLOWED_SPACES) state shared by a client's operations.

Entries are space slugs or UUIDs, compared case-insensitively. Objects that carry both
the space id and slug are checked directly; objects that only carry a space id (sidebar
children, caller-supplied UUIDs) need the slug entries resolved to ids once, which the
operations in ``_ops`` do lazily and cache here. Entries that do not resolve grant
nothing.
"""


class SpaceAllowlist:
    def __init__(self, allowed: frozenset[str] | None) -> None:
        self._entries = None if allowed is None else frozenset(e.lower() for e in allowed)
        self._resolved_ids: frozenset[str] | None = None

    @property
    def entries(self) -> frozenset[str] | None:
        return self._entries

    @property
    def single_entry(self) -> str | None:
        """The only allowed space, when the allowlist names exactly one."""
        if self._entries is not None and len(self._entries) == 1:
            return next(iter(self._entries))
        return None

    @property
    def needs_resolution(self) -> bool:
        return self._entries is not None and self._resolved_ids is None

    def resolved(self, ids: frozenset[str]) -> None:
        self._resolved_ids = frozenset(i.lower() for i in ids)

    def allows(self, space_id: str, slug: str | None) -> bool | None:
        """Decide access; None means the slug entries must be resolved first."""
        if self._entries is None or space_id.lower() in self._entries:
            return True
        if slug is not None:
            return slug.lower() in self._entries
        if self._resolved_ids is None:
            return None
        return space_id.lower() in self._resolved_ids
