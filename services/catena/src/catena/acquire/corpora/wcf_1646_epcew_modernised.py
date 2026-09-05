"""The Westminster Confession of Faith, 1646 recension, in modernised English.

The profile's `contrary` corpus: what a PCA profile examined and repudiated on
the civil magistrate.

**This is not the 1646 original, and the corpus ID says so.** The source has the
original's substance — 23.3 gives the magistrate authority to call synods, with
no "nursing fathers"; chapter 31 has five sections against the American
revision's four; `WCF 31.5` exists here and nowhere else — but its English has
been modernised throughout. Measured against the OPC's 1788 text: `hath` 1 times
against 38, `doth` 0 against 23, `-eth` verbs 1 against 52, and `has` and `does`
37 and 23 times where the older text has neither.

That is a difference of diction and not of doctrine, which is why the corpus is
kept: for showing what a tradition repudiated, the argument survives the
rewording. What it may not do is claim to be the 1646 text, because every
citation would then verify against words no seventeenth-century document
contains. Hence `wcf-1646-epcew-modernised` rather than `wcf-1646-original`.

**The finding worth carrying forward:** this source passes every check in this
pipeline. The edition diagnostic at 23.3 passes, the 33-chapter count passes,
chapter 31's five sections pass. Only a diff against the 1788 corpus exposed it.
A diagnostic locator catches the wrong recension; it does not catch a modernised
rendering of the right one, which is why `--bless` now prints a register profile
beside the diagnostic.

**Its locators are the same as the 1788 corpus's.** `WCF 23.3` exists in both
editions and says opposite things about the civil magistrate, which is precisely
why INTEGRATION-SPEC says a locator alone is not unique and verification
resolves `{corpus_id, locator}`. Getting these two corpora confused is the
failure the whole edition-specific ID rule exists to prevent.

**No faithful 1646 text exists in fetchable form.** Everything that
looks like one is the 1788 American revision wearing the original's title: the
OPC's page and CCEL's `westminster3` both carry "nursing fathers" at 23.3.
Wikisource has the genuine text under its original title, *The Humble Advice of
the Assembly of Divines*, but only nine of thirty-three chapters are
transcribed. The Internet Archive's 1647 printing is page images with no OCR
text at all.

What remains is the EPCEW's modernised rendering, published a chapter to a page.
So this is the first corpus to use `FetchPlan.follow`: the chapter URLs are read
out of the contents page and fetch downloads them into one blob.

The URLs are discovered rather than listed because they carry the confession's
chapter titles, and thirty-three of those written into an adapter is the
document's table of contents committed to a public repository (ADR-0014).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterator

from catena.acquire.fetch import FetchPlan
from catena.acquire.record import AcquisitionError, Segment, WorkFacts

corpus_id = "wcf-1646-epcew-modernised"

SOURCE_URL = "https://www.epcew.org.uk/westminster-confession-of-faith/"
ARCHIVE_URL = (
    "https://web.archive.org/web/2id_/https://www.epcew.org.uk/westminster-confession-of-faith/"
)

EXPECTED_CHAPTERS = 33

#: Chapter 31 has five sections in the original and four in the 1788 American
#: revision, which deleted the one on magistrates calling synods. The structural
#: half of the edition check, and it needs no text to detect — the textual half
#: is the diagnostic below.
CHAPTER_31_SECTIONS = 5

#: Chapter 12, *Of Adoption*, is a single paragraph and the source does not
#: number it. It is still section 1 — the 1788 edition numbers the same
#: paragraph — and dropping it would lose `WCF 12.1` entirely. Exactly one
#: chapter is like this, and the count is asserted: one is a feature of the
#: document, two would be stray text being absorbed into a chunk.
UNNUMBERED_CHAPTERS = 1

#: Two per chapter page, above and below the text. Counted rather than dropped
#: silently, for the reason the catechisms count their division headings: a
#: change in the number means the page's shape moved.
NAVIGATION_PER_CHAPTER = 2

#: The locator whose text separates 1646 from 1788, read from the other side.
#: The American revision replaces the magistrate's authority over the Church
#: with the "nursing fathers" language; what a verifier confirms here is that
#: this text has the original.
diagnostic = "WCF 23.3"

work = WorkFacts(
    work="The Westminster Confession of Faith",
    author=None,
    era="1646",
    language="en",
    source_language="en",
    text_form="not-applicable",
    edition=(
        "1646 recension in modernised English, as published by the EPCEW — not the "
        "original wording, whose archaic verb forms this rendering replaces"
    ),
    license="public-domain",
    attribution=(
        "The Westminster Confession of Faith, 1646 recension in modernised English. "
        "Public domain. Text obtained from the Evangelical Presbyterian Church in "
        "England and Wales, "
        "https://www.epcew.org.uk/westminster-confession-of-faith/."
    ),
)

#: The terms verbatim as found — which here is an absence, recorded as one.
license_terms = """\
Public domain by age: the work is a 1646 document and no copyright term reaches
it.

This rendering modernises the confession's English — "has" for "hath", "depends"
for "dependeth" — and a modernisation involves more editorial choice than a
transcription does. The corpus is recorded as public domain on the age of the
work, and the ID and `edition` field say plainly that the wording is not the
original's, so nothing downstream can mistake this for the 1646 text.

The source, https://www.epcew.org.uk/westminster-confession-of-faith/, makes no
statement of terms about the confession's text, and none was found elsewhere on
the site. There is no copyright notice on the chapter pages; the only footer
credit they carry concerns the site's design rather than the text:

    Website design & development by Conor Tomkins Creative

That absence is recorded rather than treated as permission. What admits this
corpus is the age of the work, not anything the publisher says about it, and the
next person to ask should be able to see that nothing was said.
"""


# --- fetch -----------------------------------------------------------------

_CHAPTER_HREF = re.compile(
    rb'href="(https?://[^"]*/westminster-confession-of-faith/chapter-[^"]*)"', re.I
)


def _chapter_urls(index: bytes) -> tuple[str, ...]:
    """The chapter pages, in the order the contents page lists them.

    Deduplicated by first appearance rather than sorted: bytewise order would
    put chapter X before chapter II, and the contents page is already in reading
    order.
    """
    found: list[str] = []
    for match in _CHAPTER_HREF.finditer(index):
        url = match.group(1).decode("utf-8", errors="strict")
        if url not in found:
            found.append(url)
    if len(found) != EXPECTED_CHAPTERS:
        raise AcquisitionError(
            f"{corpus_id}: the contents page lists {len(found)} chapters, expected "
            f"{EXPECTED_CHAPTERS}. Acquiring it would produce a confession missing a "
            "chapter, which would stage and bless as though complete."
        )
    return tuple(found)


def fetch_plan() -> FetchPlan:
    return FetchPlan(source_url=SOURCE_URL, archive_url=ARCHIVE_URL, follow=_chapter_urls)


# --- extract ---------------------------------------------------------------

#: The chapter heading, and the one block holding the sections. Everything else
#: on the page is site furniture.
_HEADING_CLASS = "et_pb_module_header"
_TEXT_CLASS = "et_pb_text_inner"

#: A proof-text marker's anchor. The site carries two link styles — the current
#: one puts `footnotes` in the path, the older one is `/wcf/I_fn.html#fn10` —
#: and matching the path caught only the first, leaving markers in eight chunks.
#: What both share is the `fn<n>` fragment and name, which is the marker's real
#: signature.
#:
#: The apparatus lives behind these links, and taking the apparatus is what
#: turns a public-domain text into someone's copyrighted arrangement of it.
_FOOTNOTE_FRAGMENT = re.compile(r"#fn\d+\b")
_FOOTNOTE_NAME = re.compile(r"^fn\d+$")

#: What a leaked marker looks like in the extracted text. A fingerprint of text
#: plus apparatus blesses and verifies clean forever, so extraction refuses.
_MARKER = re.compile(r"\[\d+\]")


class _Extractor(HTMLParser):
    """The concatenated chapter pages to one line per heading and section."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buffer: list[str] = []
        self._depth = 0
        self._in_heading = False
        self._dropping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = _classes(attrs)
        if tag == "h1" and _HEADING_CLASS in classes:
            self._flush()
            self._in_heading = True
            return
        if tag == "div":
            if _TEXT_CLASS in classes:
                self._flush()
                self._depth = 1
                return
            if self._depth:
                self._depth += 1
        if self._dropping:
            if tag == "a":
                self._dropping += 1
            return
        if tag == "a" and _is_footnote(attrs):
            self._dropping = 1
            return
        if tag == "p":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if self._dropping:
            if tag == "a":
                self._dropping -= 1
            return
        if tag == "h1" and self._in_heading:
            self._flush()
            self._in_heading = False
            return
        if tag == "p":
            self._flush()
        if tag == "div" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                self._flush()

    def handle_data(self, data: str) -> None:
        if self._dropping:
            return
        if self._in_heading or self._depth:
            self._buffer.append(data)

    def _flush(self) -> None:
        line = " ".join("".join(self._buffer).split())
        self._buffer.clear()
        if line:
            self.lines.append(line)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush()


def _classes(attrs: list[tuple[str, str | None]]) -> set[str]:
    for name, value in attrs:
        if name == "class" and value:
            return set(value.split())
    return set()


def _is_footnote(attrs: list[tuple[str, str | None]]) -> bool:
    for name, value in attrs:
        if not value:
            continue
        if name == "href" and _FOOTNOTE_FRAGMENT.search(value):
            return True
        if name == "name" and _FOOTNOTE_NAME.match(value):
            return True
    return False


def extract(raw: bytes) -> str:
    try:
        pages = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise AcquisitionError(
            f"{corpus_id}: the source is not UTF-8 ({error}). Decoding it loosely would "
            "silently change the text the fingerprints are taken over, so acquisition "
            "stops here rather than guessing an encoding."
        ) from error
    parser = _Extractor()
    parser.feed(pages)
    parser.close()
    if not parser.lines:
        raise AcquisitionError(
            f"{corpus_id}: no chapter content in {len(raw)} bytes — the source's shape "
            "changed, or these are not the confession's pages"
        )
    document = "\n".join(parser.lines) + "\n"
    leaked = _MARKER.search(document)
    if leaked:
        raise AcquisitionError(
            f"{corpus_id}: a proof-text marker survived extraction ({leaked.group(0)}). "
            "The apparatus is linked in more than one style on this source, and a "
            "fingerprint of text-plus-marker would bless and verify clean forever. "
            "Acquisition stops rather than committing one."
        )
    return document


# --- segment ---------------------------------------------------------------

_CHAPTER = re.compile(r"^Chapter\s+([IVXLC]+)\b", re.I)
_SECTION = re.compile(r"^([IVXLC]+)\.\s+(\S.*)$")
_NAVIGATION = re.compile(r"^Previous\s*\|\s*Next\s*\|\s*Contents$", re.I)

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _arabic(numeral: str) -> int:
    """Roman to Arabic. The source numbers both chapters and sections this way."""
    total = 0
    previous = 0
    for character in reversed(numeral.upper()):
        value = _ROMAN[character]
        total = total - value if value < previous else total + value
        previous = max(previous, value)
    return total


def segment(document: str) -> Iterator[Segment]:
    """One chunk per numbered section: `WCF 23.3`, as in the 1788 corpus."""
    chapter: int | None = None
    next_chapter = 1
    next_section = 1
    locator: str | None = None
    body: list[str] = []
    navigation = 0
    sections_in_chapter = 0
    unnumbered = 0

    for line in document.splitlines():
        if not line.strip():
            continue

        if _NAVIGATION.match(line):
            navigation += 1
            continue

        heading = _CHAPTER.match(line)
        if heading:
            if locator is not None:
                yield Segment(locator, "\n".join(body))
                locator, body = None, []
            _require_section_count(chapter, sections_in_chapter)
            number = _arabic(heading.group(1))
            if number != next_chapter:
                raise AcquisitionError(
                    f"{corpus_id}: chapter {number} where chapter {next_chapter} was "
                    "expected; the chapters are out of order, so a page was dropped or "
                    "the contents page listed them wrongly"
                )
            chapter, next_chapter, next_section = number, number + 1, 1
            sections_in_chapter = 0
            continue

        opening = _SECTION.match(line)
        if opening:
            if chapter is None:
                raise AcquisitionError(
                    f"{corpus_id}: a numbered section appears before any chapter heading"
                )
            if locator is not None:
                yield Segment(locator, "\n".join(body))
            number = _arabic(opening.group(1))
            if number != next_section:
                raise AcquisitionError(
                    f"{corpus_id}: chapter {chapter} section {number} where section "
                    f"{next_section} was expected; the section numbering is not contiguous"
                )
            next_section = number + 1
            sections_in_chapter = number
            locator, body = f"WCF {chapter}.{number}", [opening.group(2)]
            continue

        if locator is None:
            if chapter is not None and next_section == 1:
                # A chapter the source leaves unnumbered because it holds one
                # section. The count below is what keeps this from quietly
                # absorbing stray text in a chapter that does number its
                # sections.
                unnumbered += 1
                next_section = 2
                sections_in_chapter = 1
                locator, body = f"WCF {chapter}.1", [line]
                continue
            raise AcquisitionError(
                f"{corpus_id}: text outside any numbered section: {line[:60]!r}… — "
                "dropping it silently is how a chunk goes missing without anything failing"
            )
        body.append(line)

    if locator is not None:
        yield Segment(locator, "\n".join(body))
    _require_section_count(chapter, sections_in_chapter)

    chapters = next_chapter - 1
    if chapters != EXPECTED_CHAPTERS:
        raise AcquisitionError(
            f"{corpus_id}: {chapters} chapters, expected {EXPECTED_CHAPTERS}"
        )
    if unnumbered != UNNUMBERED_CHAPTERS:
        raise AcquisitionError(
            f"{corpus_id}: {unnumbered} chapters opened with unnumbered text, expected "
            f"{UNNUMBERED_CHAPTERS}. Exactly one chapter — 12, *Of Adoption* — is a "
            "single unnumbered paragraph in this source. More than that means text is "
            "being absorbed into a chunk it does not belong to."
        )
    expected_navigation = chapters * NAVIGATION_PER_CHAPTER
    if navigation != expected_navigation:
        raise AcquisitionError(
            f"{corpus_id}: {navigation} navigation paragraphs, expected "
            f"{expected_navigation}. Navigation is dropped rather than chunked, so a "
            "change in their number means the page shape moved and text may be going "
            "with them."
        )


def _require_section_count(chapter: int | None, sections: int) -> None:
    if chapter == 31 and sections != CHAPTER_31_SECTIONS:
        raise AcquisitionError(
            f"{corpus_id}: chapter 31 has {sections} sections, expected "
            f"{CHAPTER_31_SECTIONS}. The 1788 American revision has four there, having "
            "deleted the section on magistrates calling synods. A different count is a "
            "different edition, and this divergence needs no text to detect."
        )
