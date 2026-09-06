"""The Westminster Shorter Catechism, as held by the PCA.

**The 1788 American revision did not alter this document.** The Synod's changes
were to the confession's chapters on the civil magistrate and to WLC 109; the
Shorter Catechism came through unchanged. The corpus ID is
`wsc-1788-american` all the same, because a corpus ID is edition-specific by
rule and the PCA's standards are one set — a bare `wsc` would be the bug the
rule exists to prevent, and an ID asserting a different date would invent a
distinction the document does not have.

That leaves the edition check pointing at something other than 1646-versus-1788,
because there is no such divergence here to point it at. **The confusion this
corpus is actually exposed to is a modernised printing**, and the first thing a
modernised printing changes is `Holy Ghost` to `Holy Spirit`. WSC 6 is one short
answer containing it, which makes it the cheapest thing a human can read at
bless and be certain about. The diagnostic guards the register of the text, and
that is the honest description of what it does.

**Source authority does not rest on the publisher**, for the reason the
confession's adapter records at length: the PCA publishes no fetchable bare text
of the standards. `source_url` is provenance, not warrant. What makes this corpus
what it claims to be is that a human verified the diagnostic at bless time and
the fingerprints hold run to run.
"""

from __future__ import annotations

from typing import Iterator

from catena.acquire.corpora import _catechism, _opc
from catena.acquire.fetch import FetchPlan
from catena.acquire.record import Segment, WorkFacts

corpus_id = "wsc-1788-american"

SOURCE_URL = "https://www.opc.org/sc.html"
#: The `id_` form returns the archived bytes without the Wayback toolbar, so a
#: fallback acquisition takes the same path through extraction as a live one.
ARCHIVE_URL = "https://web.archive.org/web/20260706010651id_/https://www.opc.org/sc.html"

#: The catechism has 107 questions. Asserted rather than assumed, for the reason
#: the confession asserts 33 chapters: a source with a different count is a
#: different edition, and that divergence is structural where the diagnostic's
#: is textual. The manifest's hand-blessed `chunk_count` remains the authority;
#: this is a cheaper assertion that fails earlier and names the problem.
EXPECTED_QUESTIONS = 107

#: The Shorter Catechism runs unbroken — no division headings, unlike its Larger
#: counterpart. Zero is asserted rather than left implicit: a heading appearing
#: here would be dropped, and this is what makes that a failure instead.
EXPECTED_DIVISIONS = 0

#: The locator that catches a modernised printing: this answer names the Holy
#: Ghost, which is what a modernisation rewrites first. The text itself is not
#: here — it lives in the manifest as a hash, written at bless from what the
#: human read (ADR-0021).
diagnostic = "WSC Q&A 6"

work = WorkFacts(
    work="The Westminster Shorter Catechism",
    # Corporate. The Westminster Assembly drafted it; no individual is an author
    # in the sense the column means.
    author=None,
    # The 1788 revision left this document untouched, which the era records
    # rather than hides.
    era="1647; carried unchanged through the American revision of 1788",
    language="en",
    source_language="en",
    # The TR-versus-critical distinction exists only for biblical text.
    text_form="not-applicable",
    edition="1788 American revision, in which this catechism is unaltered from 1647",
    license="public-domain",
    attribution=(
        "The Westminster Shorter Catechism. Public domain. "
        "Text obtained from the Orthodox Presbyterian Church, https://www.opc.org/sc.html."
    ),
)

#: The terms verbatim as found, with the URL. Hard-wrapped: this string is
#: copied into the committed manifest exactly as written here, and the manifest
#: is meant to be read.
license_terms = """\
Public domain by age: the work is a 1647 document, carried unchanged through the
1788 American revision, and no copyright term reaches it.

The source page, https://www.opc.org/sc.html, makes no statement of terms about
the catechism's text. The only notice it carries is a site-wide footer, quoted
here verbatim as found on the retrieval date recorded in this manifest:

    © 2026 The Orthodox Presbyterian Church

That notice sits in the page furniture rather than beside the text, and it covers
the site rather than the seventeenth-century document reproduced on it. It is
recorded because a licence is evidence, not a label, and because the next person
to ask should be able to see what was actually there rather than what was
concluded from it.
"""


def fetch_plan() -> FetchPlan:
    return FetchPlan(source_url=SOURCE_URL, archive_url=ARCHIVE_URL)


def extract(raw: bytes) -> str:
    """The page's bytes to a plain-text document, one line per block.

    The OPC's page shape is shared with the confession and the Larger Catechism,
    and lives in `_opc`. The one property this corpus depends on is that `<br />`
    starts a new line, so `Q. …<br />A. …` reaches the segmenter as two lines and
    an answer dropped from its question is visible.
    """
    return _opc.extract_main_block(raw, corpus_id)


def segment(document: str) -> Iterator[Segment]:
    """One chunk per question-and-answer pair: `WSC Q&A 1`."""
    return _catechism.segment_qa(
        document,
        corpus_id=corpus_id,
        prefix="WSC",
        expected_questions=EXPECTED_QUESTIONS,
        expected_divisions=EXPECTED_DIVISIONS,
    )
