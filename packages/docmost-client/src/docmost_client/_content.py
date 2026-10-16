"""Local validation of content before it is sent to Docmost.

Each guard mirrors a documented Docmost v0.96.0 behavior (docs/docmost-api-v0.96.0.md,
section 5) that would otherwise silently lose data or cause side effects.
"""

import json
import re
from typing import Any, cast

from docmost_client.errors import InvalidRequestError
from docmost_client.models import ContentFormat

# Docmost strips this pattern as YAML front matter before parsing Markdown
# (marked.utils.ts: /^\s*---[\s\S]*?---\s*/), deleting everything in between.
_FRONT_MATTER = re.compile(r"\s*---[\s\S]*?---")
_MENTION_MARKUP = re.compile(r"""data-type\s*=\s*["']?mention\b""", re.IGNORECASE)


def check_content(content: object, format: ContentFormat, max_bytes: int) -> None:
    """Raise InvalidRequestError when ``content`` must not be sent as ``format``."""
    if format == "json":
        if not isinstance(content, dict):
            raise InvalidRequestError(
                "content must be a JSON object (a ProseMirror document) when format is json."
            )
        document = cast(dict[str, Any], content)
        size = len(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode())
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
        size = len(content.encode())
        has_mention = _MENTION_MARKUP.search(content) is not None
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
    if has_mention:
        raise InvalidRequestError(
            "content contains mention nodes, which notify the mentioned users; this client "
            "does not write mentions. Use plain text names instead."
        )


def _json_has_mention(node: object) -> bool:
    if isinstance(node, dict):
        mapping = cast(dict[str, Any], node)
        if mapping.get("type") == "mention":
            return True
        return any(_json_has_mention(value) for value in mapping.values())
    if isinstance(node, list):
        return any(_json_has_mention(item) for item in cast(list[Any], node))
    return False
