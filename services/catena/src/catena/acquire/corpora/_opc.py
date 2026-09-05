"""The shape of an OPC page, extracted once for the three Westminster adapters.

A helper rather than an adapter: the leading underscore keeps it out of the
`corpus_id` → module mapping, which can never produce a name starting with one.

The confession and both catechisms are three documents on one publisher's site
in one markup shape — a `div.mainBlock` holding the text, wrapped in navigation
and a footer that are not text. Three copies of this parser would be three
places to fix when that shape changes, and the copies would drift silently
because each corpus's fingerprints are blessed separately.

The rules are deliberately not parameterised per corpus. A catechism page
carries no table of contents, no tables and no proof-text apparatus, so the
confession's rules are inert there — and load-bearing the day the OPC adds
proof-texts to a catechism, which would otherwise be segmented as garbage.

This module knows the shape of a page. It does not know what any corpus says,
and it never decides what a chunk is: that is the adapter's `segment`, separated
because the two fail differently. See ADR-0014.
"""

from __future__ import annotations

from html.parser import HTMLParser

from catena.acquire.record import AcquisitionError

#: The text's container. Everything else on the page is furniture, and the
#: table of contents inside this div is the one part of it that is not.
CONTAINER_CLASS = "mainBlock"

#: Subtrees dropped whole. `ol`/`ul` is a table of contents, which is an index
#: rather than text; `h1`/`h2` is the page title; `sup` is where a proof-text
#: apparatus lives in every edition that carries one, and taking the apparatus
#: is what turns a public-domain text into someone's copyrighted arrangement of
#: it.
_DROPPED = frozenset({"ol", "ul", "h1", "h2", "sup", "script", "style", "noscript"})

#: A line break in the extracted document. `br` is here for two reasons: the
#: confession's chapter heading uses one, and a catechism's `Q. …<br />A. …` is
#: one paragraph that has to reach the segmenter as two lines, so an answer
#: dropped from its question is visible rather than silent.
_BLOCK = frozenset({"p", "div", "li", "center", "blockquote", "br", "h3", "h4"})

#: Tables are held rather than streamed, because the confession's two — WCF
#: 1.2's lists of the canonical books — are laid out in three columns read
#: **down** each column, not across each row. Read row-major, the Old Testament
#: opens "Genesis, II Chronicles, Daniel" and the New splits "The Epistle to" in
#: one row from "the Hebrews" in the next. That is the wrong-column-order
#: failure extraction is separated from segmentation to make visible, and it
#: would have been committed as a fingerprint of garbled text.
_CELLS = frozenset({"td", "th"})


class _Extractor(HTMLParser):
    """HTML to one line per block, restricted to the text's container.

    The source is real-world markup — a `</p>` closes after a `</center>` that
    was never opened inside it, and WLC 196's paragraph is never closed at all —
    so nothing here depends on tags nesting correctly. Lines are flushed at any
    block boundary, open or close, and again when the container closes, which is
    tolerant of soup in the way a tree builder is not.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buffer: list[str] = []
        self._depth = 0
        self._finished = False
        self._dropping: str | None = None
        self._drop_depth = 0
        self._in_heading = False
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None

    # -- capture window --

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._finished:
            return
        if self._depth == 0:
            if tag == "div" and _has_class(attrs, CONTAINER_CLASS):
                self._depth = 1
            return
        if tag == "div":
            self._depth += 1

        if self._dropping is not None:
            if tag == self._dropping:
                self._drop_depth += 1
            return
        if tag in _DROPPED:
            self._dropping, self._drop_depth = tag, 1
            return

        if tag == "table":
            self._flush()
            self._table, self._row = [], None
        elif tag == "tr":
            self._flush()
            if self._table is not None:
                self._row = []
                self._table.append(self._row)
        elif tag in _CELLS:
            self._flush()
        elif tag == "h3":
            self._flush()
            self._in_heading = True
        elif tag == "br" and self._in_heading:
            # The confession's heading is `CHAPTER n<br /><i>Title</i>`, and it
            # is one line.
            self._buffer.append(" ")
        elif tag in _BLOCK:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if self._finished or self._depth == 0:
            return

        if self._dropping is not None:
            if tag == self._dropping:
                self._drop_depth -= 1
                if self._drop_depth == 0:
                    self._dropping = None
            if tag == "div":
                self._close_div()
            return

        if tag == "table":
            self._flush()
            self._emit_table()
        elif tag == "tr" or tag in _CELLS:
            self._flush()
        elif tag == "h3":
            self._flush()
            self._in_heading = False
        elif tag in _BLOCK and not (tag == "br" and self._in_heading):
            self._flush()

        if tag == "div":
            self._close_div()

    def _close_div(self) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._flush()
            self._emit_table()
            self._finished = True

    # -- text --

    def handle_data(self, data: str) -> None:
        if self._finished or self._depth == 0 or self._dropping is not None:
            return
        self._buffer.append(data)

    def _flush(self) -> None:
        """Emit the pending run of text as a line, or as a cell inside a table."""
        line = " ".join("".join(self._buffer).split())
        self._buffer.clear()
        if not line:
            return
        if self._row is not None:
            self._row.append(line)
        else:
            self.lines.append(line)

    def _emit_table(self) -> None:
        """Flatten a held table down its columns, then move to the next."""
        if self._table is None:
            return
        rows, self._table, self._row = self._table, None, None
        width = max((len(row) for row in rows), default=0)
        for column in range(width):
            for row in rows:
                if column < len(row):
                    self.lines.append(row[column])

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()
        self._emit_table()


def _has_class(attrs: list[tuple[str, str | None]], wanted: str) -> bool:
    for name, value in attrs:
        if name == "class" and value and wanted in value.split():
            return True
    return False


def extract_main_block(raw: bytes, corpus_id: str) -> str:
    """The page's bytes to a plain-text document, one line per block.

    Headings survive as their own lines in the source's own words, because a
    segmenter needs them and inventing a marker syntax here would put a private
    format between two stages that are already separate for a reason.
    """
    try:
        page = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise AcquisitionError(
            f"{corpus_id}: the source is not UTF-8 ({error}). Decoding it loosely would "
            "silently change the text the fingerprints are taken over, so acquisition "
            "stops here rather than guessing an encoding."
        ) from error
    parser = _Extractor()
    parser.feed(page)
    parser.close()
    if not parser.lines:
        raise AcquisitionError(
            f'{corpus_id}: no <div class="{CONTAINER_CLASS}"> in {len(raw)} bytes — '
            "the source's shape changed, or this is not the page it claims to be"
        )
    return "\n".join(parser.lines) + "\n"
