"""Local validation of content before it is sent to Docmost.

Each guard mirrors a documented Docmost v0.96.0 behavior (docs/docmost-api-v0.96.0.md,
section 5) that would otherwise silently lose data or cause side effects.
"""

import html
import json
import re
from collections.abc import Collection
from html.parser import HTMLParser
from typing import Any, Literal, cast

from docmost_client.errors import InvalidRequestError
from docmost_client.models import ContentFormat

# Docmost strips this pattern as YAML front matter before parsing Markdown
# (marked.utils.ts: /^\s*---[\s\S]*?---\s*/), deleting everything in between. JavaScript's
# \s also matches U+FEFF (byte order mark); Python's does not.
_FRONT_MATTER = re.compile(r"[\s\ufeff]*---[\s\S]*?---")
_MENTION_MARKUP = re.compile(r"""data-type\s*=\s*["']?mention\b""", re.IGNORECASE)

# What Docmost compares to decide whom to notify: (entityType, entityId) of a mention.
MentionKey = tuple[str | None, str]


def check_content(
    content: object,
    format: ContentFormat,
    max_bytes: int,
    *,
    mentions: Literal["refuse", "defer"] = "refuse",
) -> None:
    """Raise InvalidRequestError when ``content`` must not be sent as ``format``.

    With ``mentions="defer"`` mentions are left to ``check_mentions``, which needs the
    current page.
    """
    if format == "json":
        if not isinstance(content, dict):
            raise InvalidRequestError(
                "content must be a JSON object (a ProseMirror document) when format is json."
            )
        document = cast(dict[str, Any], content)
        size = _encoded_size(document)
        has_mention = _json_has_mention(document)
    else:
        if not isinstance(content, str):
            raise InvalidRequestError("content must be a string when format is markdown or html.")
        if not content.strip():
            raise InvalidRequestError(
                "content must not be empty; Docmost silently ignores empty content. To clear "
                'a page, replace it with the json document {"type": "doc", "content": '
                '[{"type": "paragraph"}]}.'
            )
        size = _encoded_size(content)
        # Docmost's HTML parser decodes entities in attribute values before matching
        # span[data-type="mention"], so match the decoded text.
        has_mention = _MENTION_MARKUP.search(html.unescape(content)) is not None
        if format == "markdown" and _FRONT_MATTER.match(content):
            raise InvalidRequestError(
                "Markdown that starts with '---' and contains another '---' is stripped by "
                "Docmost as front matter, deleting the text between them. Start the content "
                "with something other than a horizontal rule, or send it as html."
            )
    if size > max_bytes:
        raise InvalidRequestError(
            f"content is {size} bytes, over the DOCMOST_MAX_CONTENT_BYTES limit of {max_bytes}."
        )
    if has_mention and mentions == "refuse":
        raise InvalidRequestError(
            "content contains mention nodes, which notify the mentioned users; this client "
            "does not write mentions. Use plain text names instead."
        )


def check_mentions(
    content: object, format: ContentFormat, page_mentions: Collection[MentionKey]
) -> None:
    """Allow only mentions already on the page.

    Docmost notifies (in-app and by email) only users who were not mentioned in the
    previously saved content, so keeping existing mentions notifies nobody.
    """
    if any(key is None or key not in page_mentions for key in mention_keys(content, format)):
        raise InvalidRequestError(
            "content contains mentions that are not already on the page; new mentions notify "
            "the mentioned users, so this client only keeps existing ones. Use plain text "
            "names instead."
        )


def mention_keys(content: object, format: ContentFormat) -> list[MentionKey | None]:
    """One entry per mention in ``content``; None when it cannot be matched to a user or page."""
    if format == "json":
        return [_json_key(node) for node in _json_mentions(content)]
    if not isinstance(content, str):
        return []
    collector = _MentionCollector()
    collector.feed(content)
    collector.close()
    keys: list[MentionKey | None] = [
        _key(a.get("data-entity-type"), a.get("data-entity-id")) for a in collector.found
    ]
    # Markup the parser does not see as an element (entity-encoded, malformed) may still
    # become a mention in Docmost, which decodes entities first: never let it through.
    hidden = len(_MENTION_MARKUP.findall(html.unescape(content))) - len(keys)
    return keys + [None] * max(hidden, 0)


def page_mentions(content: object, format: ContentFormat) -> set[MentionKey]:
    return {key for key in mention_keys(content, format) if key is not None}


class _MentionCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if (values.get("data-type") or "").lower() == "mention":
            self.found.append(values)

    handle_startendtag = handle_starttag


def _key(entity_type: object, entity_id: object) -> MentionKey | None:
    if not isinstance(entity_id, str) or not entity_id:
        return None
    return (entity_type if isinstance(entity_type, str) else None, entity_id)


def _json_key(node: dict[str, Any]) -> MentionKey | None:
    attrs = node.get("attrs")
    if not isinstance(attrs, dict):
        return None
    values = cast(dict[str, Any], attrs)
    return _key(values.get("entityType"), values.get("entityId"))


def _json_mentions(node: object) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        mapping = cast(dict[str, Any], node)
        if mapping.get("type") == "mention":
            return [mapping]
        return [found for value in mapping.values() for found in _json_mentions(value)]
    if isinstance(node, list):
        return [found for item in cast(list[Any], node) for found in _json_mentions(item)]
    return []


_INLINE_NODES = frozenset({"text", "hardBreak", "mention", "emoji"})


def comment_document(text: str) -> dict[str, Any]:
    """Build a comment document from plain text: one paragraph per line.

    Only text nodes are produced, so a comment can never carry a mention (which would
    notify users) or any other structured node.
    """
    paragraphs: list[dict[str, Any]] = []
    for line in re.split(r"\r\n|\r|\n", text.strip()):
        paragraph: dict[str, Any] = {"type": "paragraph"}
        if line:
            paragraph["content"] = [{"type": "text", "text": line}]
        paragraphs.append(paragraph)
    return {"type": "doc", "content": paragraphs}


def document_text(node: object) -> str:
    """Plain text of a ProseMirror document: blocks on separate lines, mentions as @label."""
    if not isinstance(node, dict):
        return ""
    mapping = cast(dict[str, Any], node)
    kind = mapping.get("type")
    if kind == "text":
        return str(mapping.get("text", ""))
    if kind == "hardBreak":
        return "\n"
    if kind == "mention":
        attrs = mapping.get("attrs")
        label = cast(dict[str, Any], attrs).get("label") if isinstance(attrs, dict) else None
        return f"@{label}" if label else "@"
    children = mapping.get("content")
    if not isinstance(children, list):
        return ""
    items = cast(list[object], children)
    inline = all(
        isinstance(child, dict) and cast(dict[str, Any], child).get("type") in _INLINE_NODES
        for child in items
    )
    return ("" if inline else "\n").join(document_text(child) for child in items)


def top_level_headings(document: object) -> list[tuple[str, int, str]]:
    """(id, level, text) of the document's top-level headings that carry an id."""
    if not isinstance(document, dict):
        return []
    blocks = cast(dict[str, Any], document).get("content")
    if not isinstance(blocks, list):
        return []
    headings: list[tuple[str, int, str]] = []
    for block in cast(list[object], blocks):
        if not isinstance(block, dict):
            continue
        node = cast(dict[str, Any], block)
        attrs = node.get("attrs")
        if node.get("type") != "heading" or not isinstance(attrs, dict):
            continue
        values = cast(dict[str, Any], attrs)
        heading_id, level = values.get("id"), values.get("level")
        if isinstance(heading_id, str) and heading_id and isinstance(level, int):
            headings.append((heading_id, level, document_text(node)))
    return headings


def check_size(content: object, max_bytes: int) -> None:
    size = _encoded_size(content)
    if size > max_bytes:
        raise InvalidRequestError(
            f"content is {size} bytes, over the DOCMOST_MAX_CONTENT_BYTES limit of {max_bytes}."
        )


def _encoded_size(content: object) -> int:
    """Bytes ``content`` occupies in the JSON request body (escapes included)."""
    try:
        encoded = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise InvalidRequestError("content is not JSON-serializable.") from None
    return len(encoded.encode())


def _json_has_mention(node: object) -> bool:
    if isinstance(node, dict):
        mapping = cast(dict[str, Any], node)
        if mapping.get("type") == "mention":
            return True
        return any(_json_has_mention(value) for value in mapping.values())
    if isinstance(node, list):
        return any(_json_has_mention(item) for item in cast(list[Any], node))
    return False
