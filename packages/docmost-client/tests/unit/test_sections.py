"""Splicing one section of a Docmost HTML document (pure, no I/O)."""

import pytest

from docmost_client import InvalidRequestError, NotFoundError
from docmost_client._sections import splice_section

X = 'xmlns="http://www.w3.org/1999/xhtml"'

# Shaped like real Docmost v0.96.0 output (format: html): XHTML serialization, flat
# top-level blocks, headings with data-id/id, tables wrapped in a div with self-closing
# <col /> elements, nested blocks inside callouts and details.
DOC = (
    f'<h1 {X} data-id="h1" dir="auto" id="h1">Guide</h1>'
    f'<p {X} data-id="p1" dir="auto">Intro.</p>'
    f'<h2 {X} data-id="h2a" dir="auto" id="h2a">Install</h2>'
    f'<p {X} data-id="p2" dir="auto">Run <strong>it</strong>.</p>'
    f'<div {X} class="tableWrapper"><table dir="auto"><colgroup><col style="min-width: 25px;" />'
    '<col style="min-width: 25px;" /></colgroup><tbody><tr><td><p>a &gt; b</p></td></tr>'
    "</tbody></table></div>"
    f'<h3 {X} data-id="h3" dir="auto" id="h3">Advanced</h3>'
    f'<div {X} data-type="callout" data-callout-type="warning"><p>Careful.</p></div>'
    f'<h2 {X} data-id="h2b" dir="auto" id="h2b">Configure</h2>'
    f'<details {X} dir="auto"><summary>More</summary><div data-type="detailsContent">'
    '<h3 data-id="nested" id="nested">Nested</h3><p>Hidden.</p></div></details>'
    f'<p {X} data-id="p3" dir="auto">End<br />line.</p>'
)

NEW = "<p>New.</p>"


def section(html: str, start: str, end: str | None) -> str:
    begin = html.index(start)
    return html[begin:] if end is None else html[begin : html.index(end)]


def test_replace_keeps_the_heading_and_swaps_the_body_with_subsections() -> None:
    result = splice_section(DOC, "h2a", "replace", NEW)

    assert section(result, 'data-id="h2a"', 'data-id="h2b"').endswith(f"Install</h2>{NEW}<h2 {X} ")
    assert "Advanced" not in result
    assert "tableWrapper" not in result
    assert result.startswith(DOC[: DOC.index("Install</h2>") + len("Install</h2>")])
    assert result.endswith(DOC[DOC.index(f'<h2 {X} data-id="h2b"') :])


def test_prepend_inserts_right_after_the_heading() -> None:
    result = splice_section(DOC, "h2a", "prepend", NEW)

    assert f'Install</h2>{NEW}<p {X} data-id="p2"' in result
    assert result.replace(NEW, "", 1) == DOC


def test_append_inserts_before_the_next_heading_of_same_or_higher_level() -> None:
    result = splice_section(DOC, "h2a", "append", NEW)

    assert f'Careful.</p></div>{NEW}<h2 {X} data-id="h2b"' in result
    assert result.replace(NEW, "", 1) == DOC


def test_a_subsection_ends_at_the_next_heading_of_any_higher_level() -> None:
    result = splice_section(DOC, "h3", "replace", NEW)

    assert f'Advanced</h3>{NEW}<h2 {X} data-id="h2b"' in result
    assert "Careful." not in result
    assert "tableWrapper" in result


def test_the_last_section_runs_to_the_end_of_the_page() -> None:
    result = splice_section(DOC, "h2b", "replace", NEW)

    assert result.endswith(f"Configure</h2>{NEW}")
    assert "Hidden." not in result


def test_a_top_level_h1_section_contains_every_lower_heading() -> None:
    result = splice_section(DOC, "h1", "append", NEW)

    assert result.endswith(NEW)
    assert result.replace(NEW, "", 1) == DOC


def test_heading_ids_are_matched_exactly() -> None:
    with pytest.raises(NotFoundError, match="outline"):
        splice_section(DOC, "h2", "replace", NEW)


def test_headings_inside_other_blocks_cannot_be_targeted() -> None:
    with pytest.raises(NotFoundError, match="top-level"):
        splice_section(DOC, "nested", "replace", NEW)


@pytest.mark.parametrize(
    "bad",
    [
        "<div><p>unclosed",
        "<p>ok</p></div>",
        "<p>ok</span></p>",
        "<details><summary>x</summary>",
        # Docmost's parser (happy-dom) drops or swallows everything after these.
        "<p>x</p><!-- todo",
        "<p>x</p><!-- closed -->",
        "<![CDATA[ x",
        "<!x",
        "<?php echo 1 ?>",
        "<p>x</p><div",
        "<p>x</p><",
        '<p>x</p><blockquote title=">"',
        "<p>a < b</p>",
        # happy-dom ignores "/>" on non-void elements, nesting the following sections.
        "<blockquote/>",
        '<div data-type="callout"/>',
        "<ul />",
    ],
)
def test_malformed_new_content_is_rejected(bad: str) -> None:
    with pytest.raises(InvalidRequestError, match="well-formed"):
        splice_section(DOC, "h2a", "replace", bad)


@pytest.mark.parametrize(
    "good",
    [
        "<p>a<br>b</p>",
        '<p>img <img src="https://example.com/x.png"></p>',
        "<p>self-closing<br /></p>",
        "plain text",
        '<p title="a > b">attr with gt</p>',
        "<ul><li><p>one</p></li><li><p>two</p></li></ul>",
        "<p>a &lt; b &amp;&amp; c &gt; d</p>",
        "<p>caf&eacute; &#169;</p>",
    ],
)
def test_well_formed_new_content_is_accepted(good: str) -> None:
    result = splice_section(DOC, "h2a", "prepend", good)

    assert good in result


def test_unparseable_page_html_is_reported() -> None:
    with pytest.raises(InvalidRequestError, match="page"):
        splice_section("<h2 data-id='a'>A</h2><div>", "a", "replace", NEW)


def test_surrounding_whitespace_and_text_are_preserved() -> None:
    doc = '\n<h2 data-id="a">A</h2>\n<p>one</p>\n<h2 data-id="b">B</h2>\n'

    result = splice_section(doc, "a", "replace", NEW)

    assert result == f'\n<h2 data-id="a">A</h2>{NEW}<h2 data-id="b">B</h2>\n'


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(InvalidRequestError, match="operation"):
        splice_section(DOC, "h2a", "delete", NEW)  # type: ignore[arg-type]
