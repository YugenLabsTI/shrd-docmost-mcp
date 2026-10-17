"""Splice one section of a Docmost HTML document (I/O-free).

Docmost has no API to update part of a page, so a section edit reads the page as HTML,
replaces or extends one section here, and writes the whole document back. Docmost's HTML
is a flat sequence of top-level blocks; a section is a top-level heading (addressed by
its stable ``data-id``) plus every block until the next top-level heading of the same or
a higher level. Only well-formed HTML is accepted, because an unclosed element in new
content would swallow the sections that follow it when Docmost parses the page. Docmost
parses with happy-dom, which also drops everything after an unclosed comment or a stray
``<`` and ignores ``/>`` on non-void elements, so comments, declarations, processing
instructions, unescaped ``<`` and self-closed non-void elements are rejected too.
"""

from html.parser import HTMLParser
from typing import Literal

from docmost_client.errors import InvalidRequestError, NotFoundError

SectionOperation = Literal["replace", "prepend", "append"]
SECTION_OPERATIONS: tuple[SectionOperation, ...] = ("replace", "prepend", "append")

_VOID = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
)  # fmt: skip
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# Elements whose content Python's parser and Docmost's (happy-dom) may split differently.
_RAW_TEXT = (
    "script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes",
    "noscript", "plaintext",
)  # fmt: skip


class _Block:
    __slots__ = ("attrs", "end", "start", "tag")

    def __init__(self, start: int, end: int, tag: str, attrs: dict[str, str | None]) -> None:
        self.start, self.end, self.tag, self.attrs = start, end, tag, attrs


class _TopLevel(HTMLParser):
    """Collect the top-level elements of an HTML fragment with their source offsets."""

    def __init__(self, html: str) -> None:
        # Keep character references out of the data, so a raw "<" in text is visible.
        super().__init__(convert_charrefs=False)
        self._html = html
        self._line_starts = [0]
        for index, char in enumerate(html):
            if char == "\n":
                self._line_starts.append(index + 1)
        self._stack: list[str] = []
        self._open: tuple[int, str, dict[str, str | None]] | None = None
        self.blocks: list[_Block] = []
        self.broken = False
        # Ids (data-id and id) of every heading at any depth, one set per heading.
        self.heading_ids: list[set[str]] = []
        self.element_ids: set[str] = set()
        self.raw_text: str | None = None

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_starts[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._note(tag, attrs)
        start = self._offset()
        if tag in _VOID:
            self._complete(start, start + len(self.get_starttag_text() or ""), tag, attrs)
            return
        if not self._stack:
            self._open = (start, tag, dict(attrs))
        self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _VOID:
            self.broken = True
        self._note(tag, attrs)
        start = self._offset()
        self._complete(start, start + len(self.get_starttag_text() or ""), tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID:
            return
        if not self._stack or self._stack[-1] != tag:
            self.broken = True
            return
        self._stack.pop()
        if not self._stack and self._open is not None:
            start, open_tag, attrs = self._open
            end = self._html.index(">", self._offset()) + 1
            self.blocks.append(_Block(start, end, open_tag, attrs))
            self._open = None

    def _note(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ids = {value for name, value in attrs if name in ("data-id", "id") and value}
        self.element_ids |= ids
        if tag in _HEADINGS:
            self.heading_ids.append(ids)
        if tag in _RAW_TEXT and self.raw_text is None:
            self.raw_text = tag

    def handle_data(self, data: str) -> None:
        if "<" in data:
            self.broken = True

    def handle_comment(self, data: str) -> None:
        self.broken = True

    def handle_decl(self, decl: str) -> None:
        self.broken = True

    def handle_pi(self, data: str) -> None:
        self.broken = True

    def unknown_decl(self, data: str) -> None:
        self.broken = True

    def _complete(
        self, start: int, end: int, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if not self._stack:
            self.blocks.append(_Block(start, end, tag, dict(attrs)))

    @property
    def well_formed(self) -> bool:
        return not self.broken and not self._stack


def _parse(html: str) -> _TopLevel:
    parser = _TopLevel(html)
    parser.feed(html)
    # An incomplete construct at the end ("<p>x</p><div", '<div title=">"') stays in
    # rawdata after feed() and close() would silently drop it.
    if parser.rawdata:
        parser.broken = True
    parser.close()
    return parser


def splice_section(html: str, heading_id: str, operation: SectionOperation, new_html: str) -> str:
    """Return ``html`` with ``new_html`` applied to the section that ``heading_id`` starts.

    ``replace`` swaps the section body (subsections included) and keeps the heading;
    ``prepend`` inserts right after the heading; ``append`` inserts at the end of the
    section, before the next heading of the same or a higher level.
    """
    if operation not in SECTION_OPERATIONS:
        raise InvalidRequestError(f"operation must be one of: {', '.join(SECTION_OPERATIONS)}.")
    page = _parse(html)
    if not page.well_formed:
        raise InvalidRequestError(
            "The page HTML could not be split into blocks; edit it with update_page instead."
        )
    new = _parse(new_html)
    if new.raw_text is not None:
        raise InvalidRequestError(
            f"content cannot contain <{new.raw_text}> elements; Docmost does not keep them and "
            "may parse their content differently."
        )
    if not new.well_formed:
        raise InvalidRequestError(
            "content is not well-formed HTML: close and nest every element, write < as &lt; "
            "in text, and do not use comments or self-closed elements such as <div/>."
        )

    blocks = page.blocks
    index = next(
        (
            i
            for i, block in enumerate(blocks)
            if block.tag in _HEADINGS
            and heading_id in (block.attrs.get("data-id"), block.attrs.get("id"))
        ),
        None,
    )
    if index is None:
        if any(heading_id in ids for ids in page.heading_ids):
            raise NotFoundError(
                "That heading is inside another block; only top-level headings can be "
                "edited as sections."
            )
        if heading_id in page.element_ids:
            raise NotFoundError(
                "That id belongs to a block that is not a heading; use a heading id from "
                "the page outline."
            )
        raise NotFoundError("No heading with that id; read the page outline again.")

    heading = blocks[index]
    level = int(heading.tag[1])
    following = (
        block
        for block in blocks[index + 1 :]
        if block.tag in _HEADINGS and int(block.tag[1]) <= level
    )
    next_heading = next(following, None)
    section_end = next_heading.start if next_heading is not None else blocks[-1].end

    if operation == "prepend":
        result = html[: heading.end] + new_html + html[heading.end :]
    elif operation == "append":
        result = html[:section_end] + new_html + html[section_end:]
    else:
        result = html[: heading.end] + new_html + html[section_end:]
    _check_unique_heading_ids(new, result)
    return result


def _check_unique_heading_ids(new: _TopLevel, result: str) -> None:
    """Docmost stores node ids as sent, and sections are addressed by heading id."""
    new_ids = set[str]().union(*new.heading_ids)
    if not new_ids:
        return
    headings = _parse(result).heading_ids
    if any(sum(value in ids for ids in headings) > 1 for value in new_ids):
        raise InvalidRequestError(
            "content reuses a heading id that another heading on the page already has; "
            "remove the data-id and id attributes from new headings and Docmost will assign "
            "fresh ones."
        )
