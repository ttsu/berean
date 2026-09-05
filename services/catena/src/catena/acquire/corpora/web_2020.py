"""The World English Bible, 2020 stable text, Protestant 66-book edition.

The Phase 1 Scripture corpus, and by far the largest: 31,098 verses against the
*Institutes*' 1,284. Scripture is not structurally special in the acquisition
contract — chunks are retrieved, cited and verified exactly like any other
corpus, and `scripture.corpus_id` is appended to the profile's corpora list at a
resolved stance (INTEGRATION-SPEC). Only the scale is different.

**The edition is 2020, not 2000, and the publisher is unambiguous about it.**
PLAN and TECHNICAL-SPEC named this corpus `web-2000`; no such edition exists.
eBible.org's FAQ says the translation "started out as just one Bible translation
that was continuously revised until 2020" and that "The World English Bible was
completed in 2020"; the archive's own about file ends "2020 stable text
edition". A `web-2000` ID would assert an edition nobody published, which is the
failure the edition-specific ID rule exists to prevent.

**Why the Protestant edition rather than the Classic.** eBible publishes both.
`eng-web` is the Classic: it carries the Deuterocanon and renders the
Tetragrammaton "Yahweh". `engwebp` is the Updated text restricted to the 66
books — exactly the canon WCF 1.2 enumerates — and renders it "LORD" (6,576
times; "Yahweh" appears nowhere). Both the canon and the divine name make the
Protestant edition the right text under a Westminster profile, and the two are
different corpora rather than two spellings of one.

**The New Testament follows the Majority Text**, on the publisher's own
statement rather than on inference: the WEB "has been edited to conform to the
Greek Majority Text New Testament where there are significant differences in
manuscripts", using "the Biblia Hebraica Stuttgartensia in the Old Testament,
and the Byzantine Majority Text… Robinson-Pierpont and Hodges-Farstad". The text
bears it out — Matthew 17:21, Mark 9:44 and John 5:4 are present where critical
texts omit them, while the Comma Johanneum is not.

**Five verses are placeholders with no text.** Luke 17:36, Acts 8:37, Acts
15:34, Acts 24:7 and Romans 16:25 are absent from that base text, and the source
emits the verse marker anyway. `record.stage` refuses empty text, so acquiring
them aborts the run; they are skipped and their number asserted. Skipping them
leaves real gaps — Acts runs 8:36 then 8:38 — so verse numbering is deliberately
*not* asserted contiguous, unlike chapter numbering elsewhere in this package.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Iterator

from catena.acquire.fetch import FetchPlan
from catena.acquire.record import AcquisitionError, Segment, WorkFacts

corpus_id = "web-2020"

SOURCE_URL = "https://ebible.org/Scriptures/engwebp_vpl.zip"
ARCHIVE_URL = "https://web.archive.org/web/2id_/https://ebible.org/Scriptures/engwebp_vpl.zip"

#: The verse-per-line member. eBible's VPL archive is "BIBLE TEXT ONLY. All
#: formatting, paragraph breaks, notes, introductions, noncanonical section
#: titles, etc., have been removed" — which is precisely the bare text this
#: project wants and never the apparatus it refuses.
MEMBER = "engwebp_vpl.txt"

#: Verses the Majority Text omits, emitted by the source as a marker with no
#: text. Named rather than counted alone, because *which* verses are absent is
#: evidence about the base text: a source that blanked a different set would be
#: a different Greek text wearing this one's name, and the count alone would not
#: notice.
EXPECTED_BLANKS = ("LUK 17:36", "ACT 8:37", "ACT 15:34", "ACT 24:7", "ROM 16:25")

#: The source's book codes, in canonical order, mapped to the locator's. The
#: codes are the older BibleWorks-style forms rather than USFM — `SOL` not
#: `SNG`, `JOH` not `JHN` — so this table is also what pins the source's own
#: dialect. Book names are identifiers, not text (ADR-0014).
BOOKS: dict[str, str] = {
    "GEN": "Gen", "EXO": "Ex", "LEV": "Lev", "NUM": "Num", "DEU": "Deut",
    "JOS": "Josh", "JDG": "Judg", "RUT": "Ruth", "1SA": "1 Sam", "2SA": "2 Sam",
    "1KI": "1 Kings", "2KI": "2 Kings", "1CH": "1 Chr", "2CH": "2 Chr",
    "EZR": "Ezra", "NEH": "Neh", "EST": "Esth", "JOB": "Job", "PSA": "Ps",
    "PRO": "Prov", "ECC": "Eccl", "SOL": "Song", "ISA": "Isa", "JER": "Jer",
    "LAM": "Lam", "EZE": "Ezek", "DAN": "Dan", "HOS": "Hos", "JOE": "Joel",
    "AMO": "Amos", "OBA": "Obad", "JON": "Jonah", "MIC": "Mic", "NAH": "Nah",
    "HAB": "Hab", "ZEP": "Zeph", "HAG": "Hag", "ZEC": "Zech", "MAL": "Mal",
    "MAT": "Matt", "MAR": "Mark", "LUK": "Luke", "JOH": "John", "ACT": "Acts",
    "ROM": "Rom", "1CO": "1 Cor", "2CO": "2 Cor", "GAL": "Gal", "EPH": "Eph",
    "PHI": "Phil", "COL": "Col", "1TH": "1 Thess", "2TH": "2 Thess",
    "1TI": "1 Tim", "2TI": "2 Tim", "TIT": "Titus", "PHM": "Phlm",
    "HEB": "Heb", "JAM": "Jas", "1PE": "1 Pet", "2PE": "2 Pet", "1JO": "1 John",
    "2JO": "2 John", "3JO": "3 John", "JUD": "Jude", "REV": "Rev",
}

#: The locator whose text separates this edition from the ones it is most likely
#: to be confused with, and it does so on one word. The Classic WEB reads
#: "Yahweh" here, the ASV this translation revises reads "Jehovah", and the KJV
#: reads "the LORD our God is one LORD". A verifier who reads this line knows
#: which of the four is in front of them.
diagnostic = "Deut 6:4"

work = WorkFacts(
    work="The World English Bible",
    # Corporate: a volunteer translation project, edited by Michael Paul Johnson.
    author=None,
    era="2020; a revision of the American Standard Version of 1901",
    language="en",
    source_language="en",
    # The publisher's own statement, not an inference from the text.
    text_form="majority",
    edition="2020 stable text, Protestant edition (66 books, 'LORD')",
    license="public-domain",
    attribution=(
        "The World English Bible, 2020 stable text, Protestant edition. Public domain. "
        "Text obtained from eBible.org, https://ebible.org/Scriptures/engwebp_vpl.zip. "
        "'World English Bible' is a trademark of eBible.org."
    ),
)

#: The terms verbatim as found, in the archive's own about file.
license_terms = """\
Public domain by dedication, stated by the publisher in the archive itself
(engwebp_about.htm) and quoted here verbatim as found on the retrieval date
recorded in this manifest:

    The World English Bible is in the Public Domain. That means that it is not
    copyrighted. However, "World English Bible" is a Trademark of eBible.org.
    You may copy, publish, proclaim, distribute, redistribute, sell, give away,
    quote, memorize, read publicly, broadcast, transmit, share, back up, post on
    the Internet, print, reproduce, preach, teach from, and use the World English
    Bible as much as you want, and others may also do so. All we ask is that if
    you CHANGE the actual text of the World English Bible in any way, you not
    call the result the World English Bible any more. This is to avoid confusion,
    not to limit your freedom.

The trademark is the only live obligation and this project satisfies it by
construction: normalisation does not change the text, the fingerprints prove it
was not changed, and the attribution names the translation and its source.
"""


def fetch_plan() -> FetchPlan:
    return FetchPlan(source_url=SOURCE_URL, archive_url=ARCHIVE_URL)


# --- extract ---------------------------------------------------------------


def extract(raw: bytes) -> str:
    """The archive's verse-per-line member, as text.

    A zip is a new shape for this stage, and it is the right one here: the
    alternative single-document forms eBible publishes are HTML per book, which
    would need `FetchPlan.follow` and a parser, to arrive at exactly the lines
    this member already contains.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as error:
        raise AcquisitionError(
            f"{corpus_id}: the source is not a readable zip archive ({error}). The "
            f"download was truncated, or {SOURCE_URL} no longer serves an archive."
        ) from error
    try:
        payload = archive.read(MEMBER)
    except KeyError as error:
        raise AcquisitionError(
            f"{corpus_id}: the archive has no {MEMBER!r} — it holds "
            f"{sorted(archive.namelist())}. The source's shape changed."
        ) from error
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise AcquisitionError(
            f"{corpus_id}: {MEMBER} is not UTF-8 ({error}). Decoding it loosely would "
            "silently change the text the fingerprints are taken over, so acquisition "
            "stops here rather than guessing an encoding."
        ) from error


# --- segment ---------------------------------------------------------------

_VERSE = re.compile(r"^([A-Z0-9]{3})\s+(\d+):(\d+)(?:\s+(.*))?$")


def segment(document: str) -> Iterator[Segment]:
    """One chunk per verse: `Gen 1:1`, `1 Cor 13:4`.

    Structural, never fixed-token — the verse is the unit Scripture is cited by,
    and a citation that did not resolve to one would be unusable however well it
    retrieved.
    """
    seen_books: list[str] = []
    blanks: list[str] = []

    for line in document.splitlines():
        if not line.strip():
            continue

        found = _VERSE.match(line)
        if not found:
            raise AcquisitionError(
                f"{corpus_id}: line is not a verse: {line[:60]!r}… — the verse-per-line "
                "member holds one 'BOOK chapter:verse text' per line and nothing else, "
                "so anything else means the source's format changed"
            )

        code, chapter, number, text = found.groups()
        if code not in BOOKS:
            raise AcquisitionError(
                f"{corpus_id}: unknown book code {code!r}. The Protestant edition holds "
                f"the {len(BOOKS)} books of the Westminster canon; a code outside them "
                "means the Deuterocanon crept in or the source changed its dialect."
            )
        if not seen_books or seen_books[-1] != code:
            if code in seen_books:
                raise AcquisitionError(
                    f"{corpus_id}: book {code} appears in two runs — the verses are out "
                    "of order, and a Bible acquired out of order would stage and bless "
                    "as though whole"
                )
            seen_books.append(code)

        reference = f"{code} {chapter}:{number}"
        if text is None or not text.strip():
            blanks.append(reference)
            continue

        yield Segment(f"{BOOKS[code]} {chapter}:{number}", text.strip())

    _require_canon(seen_books)
    _require_blanks(blanks)


def _require_canon(seen: list[str]) -> None:
    if len(seen) != len(BOOKS):
        raise AcquisitionError(
            f"{corpus_id}: {len(seen)} books, expected {len(BOOKS)}. The Protestant "
            "edition is the 66 books WCF 1.2 enumerates; a different count is a "
            "different edition, most likely the Classic with its Deuterocanon."
        )
    if seen != list(BOOKS):
        first = next(
            (a for a, b in zip(seen, BOOKS) if a != b), "an unplaced book"
        )
        raise AcquisitionError(
            f"{corpus_id}: the books are not in canonical order — {first} is out of "
            "place. Order is part of the edition, and a reordered Bible is a different "
            "book set wearing this one's name."
        )


def _require_blanks(blanks: list[str]) -> None:
    if tuple(blanks) != EXPECTED_BLANKS:
        raise AcquisitionError(
            f"{corpus_id}: blank verses {tuple(blanks)}, expected {EXPECTED_BLANKS}. "
            "These are the verses the Majority Text omits and the source emits as empty "
            "markers. A different set is a different Greek text, and the difference is "
            "invisible to the edition diagnostic because every remaining verse reads "
            "exactly the same."
        )
