"""The Westminster Confession of Faith, 1788 American revision.

The PCA holds this revision, not the 1646 original; they differ on the civil
magistrate, and getting the edition wrong here silently poisons every answer
that cites the confession. WCF 23.3 is the diagnostic.

**Source authority does not rest on the publisher.** The PCA publishes no
fetchable bare text of the confession: `pcaac.org` serves it through a
JavaScript application — 230 KB of markup over 2.3 KB of text, and a WordPress
REST payload carrying page shortcodes rather than the confession — and its only
bare-text artefacts are proof-text PDFs, which is the apparatus this project
refuses to take. So `source_url` is provenance, not warrant. What makes this
corpus `wcf-1788-american` is that a human verified the diagnostic at bless
time and the fingerprints hold run to run.

The OPC's plain HTML edition carries the American revision at 23.3 and no
proof-text apparatus, which is why it is the source. The OPC and the PCA hold
the same revision; they differ on permitted exceptions, which is a matter for
the tradition profile rather than for the text.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterator

from catena.acquire.fetch import FetchPlan
from catena.acquire.record import AcquisitionError, Segment, WorkFacts

corpus_id = "wcf-1788-american"

SOURCE_URL = "https://www.opc.org/wcf.html"
#: The `id_` form returns the archived bytes without the Wayback toolbar, so a
#: fallback acquisition takes the same path through extraction as a live one.
ARCHIVE_URL = "https://web.archive.org/web/20260831082916id_/https://opc.org/wcf.html"

#: The 1903 PCUSA revision added chapters 34 and 35. A source carrying them
#: would be the wrong edition in a way WCF 23.3 does not detect, because the
#: divergence is structural rather than textual. The PCA's own publication ends
#: at chapter 33, "Of the Last Judgment". The manifest's hand-blessed
#: `chunk_count` remains the authority; this is a cheaper assertion that fails
#: earlier and names the problem.
EXPECTED_CHAPTERS = 33

#: The locator whose text separates 1788 from 1646. The text itself is not
#: here: it lives in the manifest, written at bless from what the human read,
#: so it has one home and that home is the committed record.
diagnostic = "WCF 23.3"

work = WorkFacts(
    work="The Westminster Confession of Faith",
    # Corporate. The Westminster Assembly drafted it and the 1788 Synod revised
    # it; neither is an author in the sense the column means.
    author=None,
    era="1646; American revision 1788",
    language="en",
    source_language="en",
    # The TR-versus-critical distinction exists only for biblical text.
    text_form="not-applicable",
    edition="1788 American revision",
    license="public-domain",
    attribution=(
        "The Westminster Confession of Faith, 1788 American revision. Public domain. "
        "Text obtained from the Orthodox Presbyterian Church, https://www.opc.org/wcf.html."
    ),
)

#: The terms verbatim as found, with the URL. Hard-wrapped: this string is
#: copied into the committed manifest exactly as written here, and the manifest
#: is meant to be read.
license_terms = """\
Public domain by age: the work is a 1646 document in a 1788 revision, and no
copyright term reaches either.

The source page, https://www.opc.org/wcf.html, makes no statement of terms about
the confession's text. The only notice it carries is a site-wide footer, quoted
here verbatim as found on the retrieval date recorded in this manifest:

    © 2026 The Orthodox Presbyterian Church

That notice sits in the page furniture rather than beside the text, and it covers
the site rather than the eighteenth-century document reproduced on it. It is
recorded because a licence is evidence, not a label, and because the next person
to ask should be able to see what was actually there rather than what was
concluded from it.
"""


def fetch_plan() -> FetchPlan:
    return FetchPlan(source_url=SOURCE_URL, archive_url=ARCHIVE_URL)


# --- extract ---------------------------------------------------------------

#: The confession's body. Everything else on the page is navigation, and the
#: table of contents inside this div is the one part of it that is not.
_CONTAINER_CLASS = "mainBlock"

#: Subtrees dropped whole. `ol`/`ul` is the chapter table of contents, which is
#: an index rather than text; `h1`/`h2` is the page title; `sup` is where a
#: proof-text apparatus lives in every edition that carries one, and taking the
#: apparatus is what turns a public-domain text into someone's copyrighted
#: arrangement of it.
_DROPPED = frozenset({"ol", "ul", "h1", "h2", "sup", "script", "style", "noscript"})

#: A line break in the extracted document. `br` is here because the chapter
#: heading uses one.
_BLOCK = frozenset({"p", "div", "li", "center", "blockquote", "br", "h3", "h4"})

#: Tables are held rather than streamed, because this page's two of them —
#: WCF 1.2's lists of the canonical books — are laid out in three columns read
#: **down** each column, not across each row. Read row-major, the Old Testament
#: opens "Genesis, II Chronicles, Daniel" and the New splits "The Epistle to" in
#: one row from "the Hebrews" in the next. That is the wrong-column-order
#: failure extraction is separated from segmentation to make visible, and it
#: would have been committed as a fingerprint of garbled text.
_CELLS = frozenset({"td", "th"})


class _Extractor(HTMLParser):
    """HTML to one line per block, restricted to the confession's container.

    The source is real-world markup — a `</p>` closes after a `</center>` that
    was never opened inside it — so nothing here depends on tags nesting
    correctly. Lines are flushed at any block boundary, open or close, which is
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
            if tag == "div" and _has_class(attrs, _CONTAINER_CLASS):
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
            # The heading is `CHAPTER n<br /><i>Title</i>`, and it is one line.
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


def extract(raw: bytes) -> str:
    """The page's bytes to a plain-text document, one line per block.

    Chapter headings survive as their own lines, in the source's own words
    (`CHAPTER 1 Of the Holy Scripture`), because the segmenter needs the chapter
    number and inventing a marker syntax here would put a private format between
    two stages that are already separate for a reason.
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
            f"{corpus_id}: no <div class=\"{_CONTAINER_CLASS}\"> in {len(raw)} bytes — "
            "the source's shape changed, or this is not the confession's page"
        )
    return "\n".join(parser.lines) + "\n"


# --- segment ---------------------------------------------------------------

_CHAPTER = re.compile(r"^CHAPTER\s+(\d+)\b")
#: A section opens with its own number. Continuation blocks — WCF 1.2's list of
#: canonical books and the sentence that closes it — do not, and belong to the
#: section above them.
_SECTION = re.compile(r"^(\d+)\.\s+(\S.*)$")


def segment(document: str) -> Iterator[Segment]:
    """One chunk per numbered section: `WCF 7.2`.

    Structural, never fixed-token. The numbering is asserted contiguous from 1
    in both dimensions, because a missed heading and a dropped section both show
    up as a gap and neither shows up as an error anywhere else.
    """
    chapter: int | None = None
    next_chapter = 1
    next_section = 1
    locator: str | None = None
    body: list[str] = []

    for line in document.splitlines():
        if not line.strip():
            continue

        heading = _CHAPTER.match(line)
        if heading:
            if locator is not None:
                yield Segment(locator, "\n".join(body))
                locator, body = None, []
            number = int(heading.group(1))
            if number != next_chapter:
                raise AcquisitionError(
                    f"{corpus_id}: chapter {number} where chapter {next_chapter} was "
                    "expected; the chapter numbering is not contiguous, so extraction "
                    "dropped a heading or the source is not the confession"
                )
            chapter, next_chapter, next_section = number, number + 1, 1
            continue

        opening = _SECTION.match(line)
        if opening:
            if chapter is None:
                raise AcquisitionError(
                    f"{corpus_id}: a numbered section appears before any chapter heading"
                )
            if locator is not None:
                yield Segment(locator, "\n".join(body))
            number = int(opening.group(1))
            if number != next_section:
                raise AcquisitionError(
                    f"{corpus_id}: chapter {chapter} section {number} where section "
                    f"{next_section} was expected; the section numbering is not contiguous"
                )
            next_section = number + 1
            locator, body = f"WCF {chapter}.{number}", [opening.group(2)]
            continue

        if locator is None:
            raise AcquisitionError(
                f"{corpus_id}: text outside any numbered section: {line[:60]!r}… — "
                "dropping it silently is how a chunk goes missing without anything failing"
            )
        body.append(line)

    if locator is not None:
        yield Segment(locator, "\n".join(body))

    chapters = next_chapter - 1
    if chapters != EXPECTED_CHAPTERS:
        raise AcquisitionError(
            f"{corpus_id}: {chapters} chapters, expected {EXPECTED_CHAPTERS}. The 1903 "
            "PCUSA revision added chapters 34 and 35, and the PCA's confession ends at "
            "33. A different count is a different edition."
        )
