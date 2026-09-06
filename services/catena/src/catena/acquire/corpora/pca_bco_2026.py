"""The PCA's Book of Church Order, 2026 edition.

The `governing` corpus under a PCA profile, and the only one whose source is a
PDF. `pcaac.org` serves the BCO through a JavaScript application — 230 KB of
markup over 0.5% text, and that text is navigation — and no bare-text edition
exists anywhere. So the source is the publisher's own 423-page PDF, and this is
the one adapter that costs a parser: extraction was stdlib everywhere else
(`html.parser`, `zipfile`) and there is no stdlib route to a PDF.

**The edition is 2026, not 2024.** The specs named this corpus `pca-bco-2024`;
the source's title page says it "[i]ncludes all amendments approved up to and
including the 53rd General Assembly, in Louisville, Kentucky, June 22-26, 2026".
A BCO is amended most years, so those are genuinely different constitutions and
a citation resolving against the wrong one is a live correctness failure rather
than a naming nit. This is the third Phase 1 corpus whose spec ID named an
edition the source does not serve, after `wcf-1646-original` and `web-2000`.

**The appendices are not in the corpus, and that is a correctness decision.**
The constitutional BCO is Parts I–III — Form of Government, Rules of Discipline,
Directory for Worship — which run to chapter 63 and end where the appendices
begin. The PCA says of Appendix I that it was approved "as a non-binding
informational Appendix to the BCO" and "has no binding constitutional
authority", and the appendices are liturgical forms and advisory material
besides. Tier is per corpus and not per chunk, so an appendix ingested here
would be served at `governing` — the system telling a user that a funeral
service form is constitutional law.

**The page furniture is a printed book's, so it alternates.** The running head
carries the part's name on the recto and the book's title on the verso, with the
paragraph number moving from one end of the line to the other; chapters open on
a recto, so blank pages carry a notice; the three part dividers are not shaped
alike; and one paragraph opener is split in two by the page break. Filtering
the recto head alone left the verso half in 49 of 430 paragraphs and the split
opener deleted `BCO 36-8` outright, both found after the corpus had been staged
and reviewed. `_document` is where all of that is handled, and the suite's
fixture now builds both page sides.

`local-only` under ADR-0017, like the 2000 study report: acquired and ingested,
refused at verification check 4 unless the deployer opts in.
"""

from __future__ import annotations

import io
import re
from typing import Iterator

from catena.acquire.fetch import FetchPlan
from catena.acquire.record import AcquisitionError, Segment, WorkFacts

corpus_id = "pca-bco-2026"

SOURCE_URL = "https://www.pcaac.org/wp-content/uploads/2026/07/BCO_2026.pdf"
ARCHIVE_URL = (
    "https://web.archive.org/web/2id_/"
    "https://www.pcaac.org/wp-content/uploads/2026/07/BCO_2026.pdf"
)

#: Chapters 1–63, less the one the Assembly vacated.
EXPECTED_CHAPTERS = 63

#: Chapter 44 was removed by amendment and left a placeholder heading reading
#: "(Vacated)" with no paragraphs. It is a real feature of the document, so
#: chapter numbering is not contiguous and the gap is named rather than
#: tolerated: a second vacated chapter would be a different edition.
VACATED_CHAPTERS = (44,)

#: The locator whose text would differ between editions if anything did. 21-4 is
#: the ordination vow paragraph, amended within living memory and the passage a
#: PCA officer is likeliest to recognise on sight.
diagnostic = "BCO 21-4"

work = WorkFacts(
    work="The Book of Church Order of the Presbyterian Church in America",
    author=None,
    era="2026",
    language="en",
    source_language="en",
    text_form="not-applicable",
    edition=(
        "2026 edition, including all amendments approved up to and including the "
        "53rd General Assembly"
    ),
    license="local-only",
    attribution=(
        "The Book of Church Order of the Presbyterian Church in America, 2026 edition. "
        "Published by the Office of the Stated Clerk of the General Assembly of the "
        "Presbyterian Church in America. Text obtained from "
        "https://www.pcaac.org/wp-content/uploads/2026/07/BCO_2026.pdf."
    ),
)

license_terms = """\
Published by the Office of the Stated Clerk of the General Assembly of the
Presbyterian Church in America. Not assumed permissive: public availability of a
PDF on a denominational website is not a licence, and a permission to read or
quote is not a permission to ingest.

The document carries no statement of terms and no copyright notice. That absence
is recorded rather than read as permission.

So the corpus is `local-only` under ADR-0017. Ingestion and serving are separate
acts and serving is the licensed one: the repository distributes no text at all
(ADR-0014), and verification check 4 refuses to serve these chunks unless the
deployer has set an explicit opt-in, which defaults to off.
"""


def fetch_plan() -> FetchPlan:
    return FetchPlan(source_url=SOURCE_URL, archive_url=ARCHIVE_URL)


# --- extract ---------------------------------------------------------------

#: The three parts of the constitution. Their names head every page, and the
#: appendices that follow chapter 63 are not among them.
PARTS = ("FORM OF GOVERNMENT", "RULES OF DISCIPLINE", "DIRECTORY FOR WORSHIP")

#: The book's title, which heads the verso pages as the part's name heads the
#: recto ones.
TITLE = "THE BOOK OF CHURCH ORDER"

#: The typesetter's running head, which alternates by page side as a printed
#: book's does: on the recto the part's name and the first paragraph on the
#: page, on the verso that same paragraph number and the book's title, in the
#: opposite order. Either tail looks exactly like a paragraph opener, so leaving
#: one in invents a chunk on every other page and corrupts the numbering.
#: Filtering one side and not the other is worse than filtering neither, because
#: the surviving half lands mid-sentence in whichever paragraph spans the break.
_RUNNING_HEADER = re.compile(
    rf"^(?:(?:{'|'.join(PARTS)})\s+\d{{1,2}}-\d{{1,3}}"
    rf"|\d{{1,2}}-\d{{1,3}}\s+{TITLE})\s*$"
)

#: The notice on the empty page that keeps each chapter opening on a recto.
_BLANK_PAGE = re.compile(r"^This page intentionally left blank\.?$", re.IGNORECASE)

#: A paragraph opener the page break split in two: the chapter number alone at
#: the foot of the text block and the rest at the head of the next line. It
#: happens once in the 2026 edition, at `36-8.`, and the cost of missing it is
#: not noise but a lost chunk -- no opener matches, so the paragraph is absorbed
#: into the one before it and `BCO 36-8` resolves to nothing.
_SPLIT_CHAPTER = re.compile(r"^\d{1,2}$")
_SPLIT_TAIL = re.compile(r"^-\d{1,3}\.\s")

#: The second running line, and the chapter heading proper.
_RUNNING_CHAPTER = re.compile(r"^Chapter\s+\d{1,2}:\s")
_CHAPTER = re.compile(r"^CHAPTER\s+(\d{1,2})\s*$")

#: The divider page between the parts, which carries the part's number and its
#: name twice. Left in, it becomes the tail of the last paragraph of the part
#: before it — `BCO 26-6` in the 2026 edition, which would then end with "PART
#: II THE RULES OF DISCIPLINE".
#:
#: Matching a divider line suspends the document until the next chapter heading,
#: because the three dividers are not shaped alike and a per-line pattern can
#: only ever chase the differences. The Directory's spells its title in full and
#: breaks it across two lines — `THE DIRECTORY FOR THE WORSHIP` / `OF GOD`,
#: where `PARTS` carries the short form the running head uses — and then runs a
#: preface of ordinary prose that no pattern could tell from the constitution.
#: A divider page holds no numbered paragraph, so the chapter heading after it is
#: the next thing worth keeping. If a divider pattern ever matched inside a
#: chapter, the paragraphs it swallowed would break the segment stage's
#: contiguity check rather than pass silently.
_PART_DIVIDER = re.compile(
    rf"^(?:PART\s+[IVX]+|(?:THE\s+)?(?:{'|'.join(PARTS)})|"
    rf"(?:The\s+)?(?:{'|'.join(p.title() for p in PARTS)}))$",
    re.IGNORECASE,
)

#: Where the constitution starts, and it must be the bare marker. The contents
#: pages carry `PART I -- FORM OF GOVERNMENT`, and the amendment summary before
#: them lists cross-references — `4-21.d.5; 11-5; 16-3.e.5` — that match a
#: paragraph opener exactly. Without this boundary they abort the run; with a
#: loose one they become chunks of a corpus that claims to be the constitution.
_BODY_START = re.compile(r"^PART\s+I$")

#: Where the constitution stops and the appended material starts.
_APPENDICES = re.compile(r"^APPENDICES\s*$")

#: The publisher's marginal mark for what changed this year, in a symbol font
#: that extracts as a private-use code point. Annotation, not text.
AMENDMENT_BULLET = ""

_PARAGRAPH = re.compile(r"^(\d{1,2})-(\d{1,3})\.\s*(\S.*)$")


def _document(pages: list[str]) -> str:
    """Page texts to one line per structural unit.

    Separated from the PDF read so the shape work — which is where the failures
    are — is testable without a PDF, and so the parser touches exactly one
    function.
    """
    lines: list[str] = []
    started = False
    dividing = False
    for page in pages:
        for raw in page.splitlines():
            line = " ".join(raw.replace(AMENDMENT_BULLET, " ").split())
            if not line:
                continue
            if not started:
                started = bool(_BODY_START.match(line))
                continue
            if _APPENDICES.match(line):
                return "\n".join(lines) + "\n"
            if dividing:
                if not _CHAPTER.match(line):
                    continue
                dividing = False
            if _RUNNING_HEADER.match(line) or _RUNNING_CHAPTER.match(line):
                continue
            if _BLANK_PAGE.match(line):
                continue
            if _PART_DIVIDER.match(line):
                dividing = True
                continue
            if _SPLIT_TAIL.match(line) and lines and _SPLIT_CHAPTER.match(lines[-1]):
                lines[-1] += line
                continue
            lines.append(line)
    if not started:
        raise AcquisitionError(
            f"{corpus_id}: no bare 'PART I' line in {len(pages)} pages — the "
            "constitution's opening marker is gone, so the source's shape changed and "
            "acquiring it would take whichever region happened to follow instead"
        )
    return "\n".join(lines) + "\n"


def extract(raw: bytes) -> str:
    """The PDF's bytes to the constitution's text, appendices excluded."""
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(raw))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as error:  # pypdf raises a family of its own
        raise AcquisitionError(
            f"{corpus_id}: the source is not a readable PDF ({error}). A truncated "
            "download and a changed publication both look like this; check the bytes "
            "before assuming the document moved."
        ) from error
    if not pages:
        raise AcquisitionError(f"{corpus_id}: the PDF has no pages")
    document = _document(pages)
    if not document.strip():
        raise AcquisitionError(
            f"{corpus_id}: no text in {len(pages)} pages — the publisher has replaced the "
            "PDF with a scan, and an image-only source needs OCR that this pipeline "
            "deliberately does not do"
        )
    return document


# --- segment ---------------------------------------------------------------


def segment(document: str) -> Iterator[Segment]:
    """One chunk per numbered paragraph: `BCO 21-4`.

    Chapter numbering is deliberately not asserted contiguous. Chapter 44 was
    vacated by amendment and the document keeps its heading with no paragraphs
    under it, so a contiguity check would fail on the source being correct.
    """
    chapter: int | None = None
    next_paragraph = 1
    locator: str | None = None
    body: list[str] = []
    seen: list[int] = []
    with_paragraphs: set[int] = set()

    for line in document.splitlines():
        if not line.strip():
            continue

        heading = _CHAPTER.match(line)
        if heading:
            if locator is not None:
                yield Segment(locator, " ".join(body))
                locator, body = None, []
            chapter = int(heading.group(1))
            seen.append(chapter)
            next_paragraph = 1
            continue

        opening = _PARAGRAPH.match(line)
        if opening:
            found_chapter, found = int(opening.group(1)), int(opening.group(2))
            if chapter is None:
                raise AcquisitionError(
                    f"{corpus_id}: paragraph {found_chapter}-{found} appears before any "
                    "chapter heading"
                )
            if found_chapter != chapter:
                raise AcquisitionError(
                    f"{corpus_id}: paragraph {found_chapter}-{found} inside chapter "
                    f"{chapter}. The running header carries a paragraph number and looks "
                    "exactly like an opener, so this is what a header surviving "
                    "extraction looks like."
                )
            if found != next_paragraph:
                raise AcquisitionError(
                    f"{corpus_id}: paragraph {chapter}-{found} where {chapter}-"
                    f"{next_paragraph} was expected; the numbering is not contiguous "
                    "within the chapter, so a paragraph was dropped"
                )
            if locator is not None:
                yield Segment(locator, " ".join(body))
            next_paragraph = found + 1
            with_paragraphs.add(chapter)
            locator, body = f"BCO {chapter}-{found}", [opening.group(3)]
            continue

        if locator is None:
            # A chapter title, or the "(Vacated)" placeholder. Structure rather
            # than text: the chunk is the numbered paragraph, and a chapter's
            # title is no more a chunk here than in the confession.
            continue
        body.append(line)

    if locator is not None:
        yield Segment(locator, " ".join(body))

    if seen != sorted(set(seen)):
        raise AcquisitionError(
            f"{corpus_id}: chapter headings are out of order — {seen[:8]}…"
        )
    if seen and seen[-1] != EXPECTED_CHAPTERS:
        raise AcquisitionError(
            f"{corpus_id}: the last chapter is {seen[-1]}, expected {EXPECTED_CHAPTERS}"
        )
    vacated = tuple(n for n in seen if n not in with_paragraphs)
    if vacated != VACATED_CHAPTERS:
        raise AcquisitionError(
            f"{corpus_id}: chapters {vacated} have a heading and no paragraphs, expected "
            f"{VACATED_CHAPTERS}. Chapter 44 was vacated by amendment; a different set is "
            "a different edition, and an empty chapter that is not 44 is a parser losing "
            "paragraphs rather than the Assembly removing them."
        )
