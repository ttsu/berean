"""The PCA's creation study committee report, adopted by the 28th GA (2000).

The corpus that makes UC-4 answerable. Without it the corpus says only "in the
space of six days" (WCF 4.1), and the denomination's actual ruling — that a
diversity of views on the creation days is acceptable — appears nowhere. It is
what establishes the contested status of `creation-days` (ADR-0015).

**The recommendations are addressable apart from the body**, under a locator
form that cannot be confused with one: `GA28 Rec.2` against `GA28 IV.A.7`. A
profile's `ruling_source` resolves to the first and must never resolve to the
second, because the body argues four interpretations the denomination did not
adopt, and tier is per corpus rather than per chunk. The locator is the only
thing separating advocacy from ruling.

**PLAN's "per numbered section" does not survive the document.** Section IV.A,
the Calendar-Day Interpretation, is 40,659 characters with no subsections —
about 10,000 tokens, past BGE-M3's 8,192 limit, so it could not be embedded at
all. The deepest headings run from 1 KB to 40 KB. Chunks are paragraphs and the
section path lives in the locator, which keeps retrieval workable while still
saying where in the argument a citation came from.

**On the date.** The source is filed by the PCA Historical Center under
"[27th General Assembly (1999)]", while the corpus ID says the 28th and 2000.
The document itself settles it: it contains "PROPOSAL FOR REPORTING TO THE 28TH
GENERAL ASSEMBLY" and records each recommendation's outcome — "Adopted",
"Adopted as amended" — which are actions only an Assembly takes, and the
Assembly that took them was the 28th in 2000. The 1999 label is the committee's
work being filed under the year it was written.

`local-only` under ADR-0017: acquired and ingested, and refused at verification
check 4 unless the deployer has opted in. The repository distributes nothing
either way (ADR-0014).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterator

from catena.acquire.fetch import FetchPlan
from catena.acquire.record import AcquisitionError, Segment, WorkFacts

corpus_id = "pca-ga28-2000-creation-study"

SOURCE_URL = "https://pcahistory.org/pca/digest/studies/creation/report.html"
ARCHIVE_URL = (
    "https://web.archive.org/web/2id_/"
    "https://pcahistory.org/pca/digest/studies/creation/report.html"
)

#: Three, each recorded with its outcome. Asserted because the ruling is the
#: reason this corpus exists, and a report acquired without its recommendations
#: would stage, bless and verify clean while answering nothing.
EXPECTED_RECOMMENDATIONS = 3

#: The ruling itself: the Assembly affirming that a diversity of views on the
#: creation days is acceptable. It is the diagnostic because it is what
#: distinguishes the adopted report from the committee's draft — a draft has
#: recommendations, only the adopted report records that they carried.
diagnostic = "GA28 Rec.2"

work = WorkFacts(
    work="Report of the Creation Study Committee",
    # Corporate: a committee of the General Assembly.
    author=None,
    era="2000",
    language="en",
    source_language="en",
    text_form="not-applicable",
    edition="As adopted by the 28th General Assembly of the PCA, 2000",
    license="local-only",
    attribution=(
        "Report of the Creation Study Committee, Presbyterian Church in America, "
        "adopted by the 28th General Assembly (2000). Text obtained from the PCA "
        "Historical Center, https://pcahistory.org/pca/digest/studies/creation/report.html."
    ),
)

license_terms = """\
Published by the Presbyterian Church in America and hosted by the PCA Historical
Center. Not assumed permissive: public availability on a denominational website
is not a licence, and a permission to read or quote is not a permission to
ingest.

The source page, https://pcahistory.org/pca/digest/studies/creation/report.html,
carries no statement of terms about the report's text and no copyright notice on
the document itself. That absence is recorded rather than read as permission.

So the corpus is `local-only` under ADR-0017. Ingestion and serving are separate
acts and serving is the licensed one: the repository distributes no text at all
(ADR-0014), and verification check 4 refuses to serve these chunks unless the
deployer has set an explicit opt-in, which defaults to off. Whether a deployer
may serve this document from their own machine is the deployer's call to make.
"""


def fetch_plan() -> FetchPlan:
    return FetchPlan(source_url=SOURCE_URL, archive_url=ARCHIVE_URL)


# --- extract ---------------------------------------------------------------

#: Where the report begins — and it appears twice, once as the page's title
#: above the contents table and once as the body's own heading below it. The
#: last occurrence is the real one; starting at the first swallows the Historical
#: Center's "[27th General Assembly (1999).]" filing label and the entire index.
_BODY_MARKER = re.compile(r"^REPORT OF THE CREATION STUDY COMMITTEE$", re.I)

#: A footnote marker's anchor — 173 of them.
_FOOTNOTE = re.compile(r"^_ftn(ref)?\d+$")

#: A footnote *body*. All 173 sit after the report in their own `div id="ftnN"`,
#: and dropping only the marker leaves the note's text to be chunked as a
#: paragraph of the report — `[35]Ibid.` under a locator claiming to be the
#: appendix on General Revelation. The apparatus is a later editor's, and taking
#: it is what turns a published document into someone's arrangement of it.
_FOOTNOTE_BODY = re.compile(r"^ftn\d+$")

#: Headings are bold and paragraphs are not, and that distinction exists only in
#: the markup. Carrying it across the stage boundary is the whole reason for a
#: prefix: without it `1. Literal.` (a heading in section III) and `1. That the
#: report be distributed` (a recommendation) are the same string, and the
#: segmenter would have to guess. The Institutes' adapter refuses to invent a
#: marker syntax because its source already marks chapters in its own words;
#: this source marks them only in `<b>`, which is the opposite case.
HEADING_PREFIX = "# "


class _Extractor(HTMLParser):
    """The report's paragraphs, one to a line, headings prefixed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buffer: list[str] = []
        #: What of the paragraph was bold. A heading is a paragraph that is
        #: *entirely* bold; the body is full of bold emphasis mid-sentence, and
        #: treating that as a heading puts chunks under a path that does not
        #: describe them.
        self._bold_text: list[str] = []
        self._started = False
        self._bold = 0
        self._dropping = 0
        self._in_footnote_body = False
        self._in_paragraph = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._dropping:
            if tag == "a":
                self._dropping += 1
            return
        if tag == "a" and _is_footnote(attrs):
            self._dropping = 1
            return
        if tag == "div" and _is_footnote_body(attrs):
            self._flush()
            self._in_footnote_body = True
            return
        if tag == "p":
            self._flush()
            self._in_paragraph = True
        elif tag == "b":
            self._bold += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_footnote_body:
            self._buffer.clear()
            self._bold_text.clear()
            self._in_footnote_body = False
            return
        if self._dropping:
            if tag == "a":
                self._dropping -= 1
            return
        if tag == "p":
            self._flush()
            self._in_paragraph = False
        elif tag == "div" or tag == "td":
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._dropping or self._in_footnote_body:
            return
        self._buffer.append(data)
        if self._bold:
            self._bold_text.append(data)

    def _flush(self) -> None:
        line = " ".join("".join(self._buffer).split())
        bold = " ".join("".join(self._bold_text).split())
        was_bold = bool(line) and bold == line
        self._buffer.clear()
        self._bold_text.clear()
        self._bold = 0
        if not line:
            return
        if _BODY_MARKER.match(line):
            # The marker appears twice — once as the page's title above the
            # contents table, once as the body's own heading below it. The last
            # one wins, so anything collected from an earlier match (the
            # Historical Center's filing label, the whole index) is discarded
            # rather than chunked.
            self._started = True
            self.lines.clear()
            return
        if not self._started:
            return
        if line.startswith(HEADING_PREFIX):
            raise AcquisitionError(
                f"{corpus_id}: a paragraph begins with {HEADING_PREFIX!r}, which "
                "extraction uses to mark a heading. The source's shape changed and the "
                "two can no longer be told apart."
            )
        self.lines.append(f"{HEADING_PREFIX}{line}" if was_bold else line)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


def _is_footnote_body(attrs: list[tuple[str, str | None]]) -> bool:
    return any(name == "id" and value and _FOOTNOTE_BODY.match(value) for name, value in attrs)


def _is_footnote(attrs: list[tuple[str, str | None]]) -> bool:
    for name, value in attrs:
        if not value:
            continue
        if name == "name" and _FOOTNOTE.match(value):
            return True
        if name == "href" and value.startswith("#_ftn"):
            return True
    return False


def extract(raw: bytes) -> str:
    try:
        page = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        # The source is a 2000-era page served without a usable charset; it is
        # Windows-1252 in practice. Decoding it as UTF-8 would fail on the
        # curly quotes the document is full of.
        page = raw.decode("cp1252", errors="strict")
    parser = _Extractor()
    parser.feed(page)
    parser.close()
    if not parser.lines:
        raise AcquisitionError(
            f"{corpus_id}: no report body in {len(raw)} bytes — the marker "
            "'REPORT OF THE CREATION STUDY COMMITTEE' was not found, so the source's "
            "shape changed or this is not the report"
        )
    return "\n".join(parser.lines) + "\n"


# --- segment ---------------------------------------------------------------

_ROMAN = re.compile(r"^([IVX]+)\.\s+(\S.*)$")
_LETTER = re.compile(r"^([A-Z])\.\s+(\S.*)$")
_NUMBER = re.compile(r"^(\d+)\.\s+(\S.*)$")
_RECOMMENDATIONS = re.compile(r"^RECOMMENDATIONS\s*$", re.I)

#: Longest a fully-bold paragraph may be and still be a heading.
#:
#: "Entirely bold" alone does not identify one. The report has 36 fully-bold
#: paragraphs carrying no number: most are short sub-headings — `Conclusion`,
#: `Strengths:`, `Definition of the Position` — but some are whole paragraphs
#: the source set in bold for emphasis, and those are text. Length separates
#: them cleanly, because no heading in this document approaches this and every
#: bold body paragraph exceeds it.
HEADING_MAX_CHARS = 120


def segment(document: str) -> Iterator[Segment]:
    """Paragraphs under their section path, and the recommendations apart.

    `GA28 IV.B.2.4` is the fourth paragraph of section IV, subsection B,
    sub-subsection 2. `GA28 Rec.2` is the second recommendation, and nothing in
    the body can collide with it.
    """
    roman: str | None = None
    letter: str | None = None
    number: str | None = None
    paragraph = 0
    recommendations = 0
    unnumbered = 0
    in_recommendations = False

    for line in document.splitlines():
        if not line.strip():
            continue

        if line.startswith(HEADING_PREFIX) and len(line) - len(HEADING_PREFIX) > HEADING_MAX_CHARS:
            # Bold, but far past any heading's length: the source set a whole
            # paragraph in bold for emphasis. It is text.
            line = line[len(HEADING_PREFIX) :].strip()

        if line.startswith(HEADING_PREFIX):
            head = line[len(HEADING_PREFIX) :].strip()
            if _RECOMMENDATIONS.match(head):
                in_recommendations = True
                paragraph = 0
                continue
            in_recommendations = False
            found = _ROMAN.match(head)
            if found:
                roman, letter, number, paragraph = found.group(1), None, None, 0
                continue
            found = _LETTER.match(head)
            if found and roman:
                letter, number, paragraph = found.group(1), None, 0
                continue
            found = _NUMBER.match(head)
            if found and roman:
                number, paragraph = found.group(1), 0
                continue
            # An unnumbered heading — `Conclusion`, `Strengths:`, and the
            # proposal preceding the recommendations. It opens no new path and
            # its paragraphs belong to the section above it. Counted rather than
            # dropped silently.
            unnumbered += 1
            continue

        if in_recommendations:
            found = _NUMBER.match(line)
            if not found:
                # `We, therefore, recommend the following:` and the like.
                continue
            recommendations += 1
            if int(found.group(1)) != recommendations:
                raise AcquisitionError(
                    f"{corpus_id}: recommendation {found.group(1)} where "
                    f"{recommendations} was expected; the numbering is not contiguous"
                )
            yield Segment(f"GA28 Rec.{recommendations}", found.group(2))
            continue

        if roman is None:
            raise AcquisitionError(
                f"{corpus_id}: text before any section heading: {line[:60]!r}… — "
                "dropping it silently is how a chunk goes missing without anything failing"
            )
        paragraph += 1
        path = ".".join(part for part in (roman, letter, number) if part)
        yield Segment(f"GA28 {path}.{paragraph}", line)

    if recommendations != EXPECTED_RECOMMENDATIONS:
        raise AcquisitionError(
            f"{corpus_id}: {recommendations} recommendations, expected "
            f"{EXPECTED_RECOMMENDATIONS}. The recommendations are the ruling this corpus "
            "exists to make citable, and a report acquired without them would stage, "
            "bless and verify clean while answering nothing."
        )
