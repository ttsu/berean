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
from typing import Iterator

from catena.acquire.corpora import _opc
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


def extract(raw: bytes) -> str:
    """The page's bytes to a plain-text document, one line per block.

    The OPC's page shape is shared with both catechisms and lives in `_opc`.
    What is specific to the confession is what `segment` does with the lines:
    chapter headings survive as their own lines, in the source's own words
    (`CHAPTER 1 Of the Holy Scripture`), because the segmenter needs the chapter
    number and inventing a marker syntax in extraction would put a private
    format between two stages that are already separate for a reason.
    """
    return _opc.extract_main_block(raw, corpus_id)


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
