"""The Westminster Larger Catechism, 1788 American revision.

The PCA holds this revision, not the 1646 original. The 1788 Synod's changes to
the standards were about the civil magistrate, and the catechism's share of them
is **WLC 109**: the original lists "tolerating a false religion" among the sins
forbidden in the second commandment, and the American revision deletes it. That
is the diagnostic, and it is a deletion — what the verifier confirms at bless is
that the phrase is *absent* from what was acquired.

**Source authority does not rest on the publisher**, for the reason the
confession's adapter records at length: the PCA publishes no fetchable bare text
of the standards. `source_url` is provenance, not warrant. What makes this corpus
`wlc-1788-american` is that a human verified the diagnostic at bless time and the
fingerprints hold run to run.

The OPC's plain HTML edition carries the American revision at 109 and no
proof-text apparatus, which is why it is the source.
"""

from __future__ import annotations

from typing import Iterator

from catena.acquire.corpora import _catechism, _opc
from catena.acquire.fetch import FetchPlan
from catena.acquire.record import Segment, WorkFacts

corpus_id = "wlc-1788-american"

SOURCE_URL = "https://www.opc.org/lc.html"
#: The `id_` form returns the archived bytes without the Wayback toolbar, so a
#: fallback acquisition takes the same path through extraction as a live one.
ARCHIVE_URL = "https://web.archive.org/web/20260803234016id_/https://opc.org/lc.html"

#: The catechism has 196 questions. Asserted rather than assumed, for the reason
#: the confession asserts 33 chapters: a source with a different count is a
#: different edition, and that divergence is structural where WLC 109's is
#: textual. The manifest's hand-blessed `chunk_count` remains the authority;
#: this is a cheaper assertion that fails earlier and names the problem.
EXPECTED_QUESTIONS = 196

#: Two all-caps headings divide the catechism — one before what the Scriptures
#: teach concerning God, one before the duty they require of man. They belong to
#: no Q&A and are dropped. The count is asserted because a dropped line nothing
#: counts is a chunk that can go missing silently.
EXPECTED_DIVISIONS = 2

#: The locator whose text separates 1788 from 1646, by what it does not say.
#: The text itself is not here: it lives in the manifest as a hash, written at
#: bless from what the human read (ADR-0021).
diagnostic = "WLC Q&A 109"

work = WorkFacts(
    work="The Westminster Larger Catechism",
    # Corporate. The Westminster Assembly drafted it and the 1788 Synod revised
    # it; neither is an author in the sense the column means.
    author=None,
    era="1648; American revision 1788",
    language="en",
    source_language="en",
    # The TR-versus-critical distinction exists only for biblical text.
    text_form="not-applicable",
    edition="1788 American revision",
    license="public-domain",
    attribution=(
        "The Westminster Larger Catechism, 1788 American revision. Public domain. "
        "Text obtained from the Orthodox Presbyterian Church, https://www.opc.org/lc.html."
    ),
)

#: The terms verbatim as found, with the URL. Hard-wrapped: this string is
#: copied into the committed manifest exactly as written here, and the manifest
#: is meant to be read.
license_terms = """\
Public domain by age: the work is a 1648 document in a 1788 revision, and no
copyright term reaches either.

The source page, https://www.opc.org/lc.html, makes no statement of terms about
the catechism's text. The only notice it carries is a site-wide footer, quoted
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


def extract(raw: bytes) -> str:
    """The page's bytes to a plain-text document, one line per block.

    The OPC's page shape is shared with the confession and the Shorter
    Catechism, and lives in `_opc`. The one property this corpus depends on is
    that `<br />` starts a new line, so `Q. …<br />A. …` reaches the segmenter as
    two lines and an answer dropped from its question is visible.
    """
    return _opc.extract_main_block(raw, corpus_id)


def segment(document: str) -> Iterator[Segment]:
    """One chunk per question-and-answer pair: `WLC Q&A 109`."""
    return _catechism.segment_qa(
        document,
        corpus_id=corpus_id,
        prefix="WLC",
        expected_questions=EXPECTED_QUESTIONS,
        expected_divisions=EXPECTED_DIVISIONS,
    )
