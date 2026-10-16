"""Typed views of Docmost v0.96.0 API responses.

Models ignore unknown fields so additive server changes do not break parsing, and expose
snake_case attributes. Field provenance is documented in docs/docmost-api-v0.96.0.md.
"""

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import AliasPath, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

ContentFormat = Literal["markdown", "html", "json"]
"""Content formats Docmost v0.96.0 accepts for reading and writing pages.

- ``markdown``: compact and readable; lossy (drops comments anchors, mentions, colors,
  diagrams, embeds, and turns single newlines into hard breaks).
- ``html``: round-trips nearly everything the editor supports.
- ``json``: the editor's ProseMirror document; exact but verbose.
"""

CONTENT_FORMATS: tuple[ContentFormat, ...] = ("markdown", "html", "json")

ContentOperation = Literal["append", "prepend", "replace"]
"""How written content combines with the page.

``append``/``prepend`` insert top-level blocks and merge safely with concurrent editors.
``replace`` deletes the whole page body first, including edits made after it was read.
"""

CONTENT_OPERATIONS: tuple[ContentOperation, ...] = ("append", "prepend", "replace")

Compatibility = Literal["supported", "untested", "unknown"]

T = TypeVar("T")


class _Model(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="ignore", alias_generator=to_camel, populate_by_name=True
    )


class SpaceRef(_Model):
    """Minimal space reference embedded in pages and search hits."""

    id: str
    name: str
    slug: str


class Space(_Model):
    """A space the account is a member of."""

    id: str
    name: str
    slug: str
    description: str | None = None
    visibility: str | None = None
    member_count: int | None = None
    role: str | None = Field(
        default=None,
        validation_alias=AliasPath("membership", "role"),
        description="The account's role in the space: admin, writer, or reader.",
    )


class CurrentUser(_Model):
    """The account the client is logged in as."""

    id: str = Field(validation_alias=AliasPath("user", "id"))
    email: str = Field(validation_alias=AliasPath("user", "email"))
    name: str | None = Field(default=None, validation_alias=AliasPath("user", "name"))
    role: str | None = Field(default=None, validation_alias=AliasPath("user", "role"))
    workspace_id: str = Field(validation_alias=AliasPath("user", "workspaceId"))


class Page(_Model):
    """A page with its content in the requested ``format``."""

    id: str
    slug_id: str
    title: str | None = None
    icon: str | None = None
    parent_page_id: str | None = None
    space_id: str
    space: SpaceRef | None = None
    is_locked: bool = False
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    format: ContentFormat
    content: str | dict[str, Any] | None = None
    can_edit: bool | None = Field(
        default=None, validation_alias=AliasPath("permissions", "canEdit")
    )


class PageSummary(_Model):
    """A page as listed in the space tree (no content, no timestamps)."""

    id: str
    slug_id: str
    title: str | None = None
    icon: str | None = None
    parent_page_id: str | None = None
    space_id: str
    has_children: bool = False
    can_edit: bool | None = None


class SearchHit(_Model):
    """A full-text search result.

    ``highlight`` is raw page text with ``<b>`` markers around matches; it is not
    HTML-escaped and must be treated as untrusted text.
    """

    id: str
    slug_id: str | None = None
    title: str | None = None
    icon: str | None = None
    parent_page_id: str | None = None
    space: SpaceRef
    updated_at: datetime | None = None
    rank: float | None = None
    highlight: str | None = None


class Paginated(BaseModel, Generic[T]):
    """One page of a cursor-paginated listing. Page on ``next_cursor``, not item count."""

    model_config = ConfigDict(frozen=True)

    items: list[T]
    has_next_page: bool
    next_cursor: str | None = None


class CompatibilityReport(BaseModel):
    """Result of comparing the server version with the versions this client is tested on."""

    model_config = ConfigDict(frozen=True)

    status: Compatibility
    docmost_version: str | None
    supported_versions: tuple[str, ...]
