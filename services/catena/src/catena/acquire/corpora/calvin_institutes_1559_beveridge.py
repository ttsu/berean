"""Calvin's *Institutes of the Christian Religion*, 1559, Beveridge translation.

The largest Phase 1 corpus and the only translated one, so it is what actually
exercises `source_language` and the book/chapter/section locator.

**Beveridge (1845), never Battles (1960).** Battles is in copyright. It is also
the translation a model is most likely to have memorised, which PLAN records as
a consequence for Task 11: UC-6 may fail check 2 on passages the model genuinely
knows. That is a finding about the generator, not a defect in the verifier.

CCEL serves this as plain text rather than markup, so nothing here is shared
with the Westminster adapters and `_opc` does not apply.

The source's shape carries four hazards, each of which fails silently:

1. **Every chapter opens with a numbered synopsis of itself** — one-line section
   titles numbered 1..N — and then repeats 1..N as the body. Taken naively a
   chapter yields 2N chunks, half of them title fragments, and no later stage
   could tell. Six of the eighty chapters carry no synopsis, so its presence
   cannot be assumed either. `_body_of` resolves both cases with one rule.
2. **Book IV chapter 18's number is missing from the source**, replaced by a
   footnote anchor: `CHAPTER [653]`. It is recognised positionally.
3. **Numbered lists inside the prose** open lines that look like sections.
   Matching only the next expected number steps over them.
4. **Footnote anchors** — 1,283 inside the four books — are CCEL apparatus, and
   taking the apparatus is what turns a public-domain text into someone's
   copyrighted arrangement of it.

What is excluded is as decided as what is kept: the CCEL header, **John Murray's
20th-century introduction, which is in copyright**, Norton's 1581 translator's
preface, the scripture and author indexes, each book's editorial ARGUMENT, and
the One Hundred Aphorisms appended at the end.
"""

from __future__ import annotations

import re
from typing import Iterator

from catena.acquire.fetch import FetchPlan
from catena.acquire.record import AcquisitionError, Segment, WorkFacts

corpus_id = "calvin-institutes-1559-beveridge"

SOURCE_URL = "https://www.ccel.org/ccel/c/calvin/institutes/cache/institutes.txt"
ARCHIVE_URL = (
    "https://web.archive.org/web/20260904id_/"
    "https://www.ccel.org/ccel/c/calvin/institutes/cache/institutes.txt"
)

#: Chapters per book. The 1559 edition is four books of 18, 17, 25 and 20; the
#: earlier editions have neither that shape nor that count, so this doubles as
#: the edition check the diagnostic cannot make structurally.
EXPECTED_CHAPTERS = (18, 17, 25, 20)

#: Calvin's prefatory address to Francis I, which opens the work and sits
#: outside the book/chapter scheme.
EXPECTED_PREFATORY_SECTIONS = 7

#: The locator whose text separates Beveridge from Battles. The specs' own
#: example locator, and it sits where Beveridge's Victorian register diverges
#: most visibly from a modern translation.
diagnostic = "Inst. 4.17.10"

work = WorkFacts(
    work="Institutes of the Christian Religion",
    author="John Calvin",
    era="1559; Beveridge translation 1845",
    language="en",
    # The only Phase 1 corpus where these differ.
    source_language="la",
    text_form="not-applicable",
    edition="1559 edition, Henry Beveridge translation (1845)",
    license="public-domain",
    attribution=(
        "John Calvin, Institutes of the Christian Religion, 1559 edition, translated by "
        "Henry Beveridge (1845). Public domain. Text obtained from the Christian Classics "
        "Ethereal Library, https://www.ccel.org/ccel/c/calvin/institutes/."
    ),
)

license_terms = """\
Public domain by age: the work is a 1559 Latin text in an 1845 English
translation, and no copyright term reaches either.

The source file, https://www.ccel.org/ccel/c/calvin/institutes/cache/institutes.txt,
states its terms in its own header, quoted here verbatim as found on the
retrieval date recorded in this manifest:

    Title: The Institutes of the Christian Religion
    Creator(s): Calvin, John (1509-1564)
                Beveridge, Henry (Translator)
    Rights: Public Domain

That statement covers the work and the translation. It does not reach the
twentieth-century introduction by John Murray that the same file carries, which
is why acquisition excludes it: a public-domain statement about a work is not a
statement about the apparatus a later edition wraps around it.
"""


def fetch_plan() -> FetchPlan:
    return FetchPlan(source_url=SOURCE_URL, archive_url=ARCHIVE_URL)


# --- extract ---------------------------------------------------------------

#: A footnote anchor. CCEL apparatus, and it is what swallowed Book IV chapter
#: 18's number.
_ANCHOR = re.compile(r"\[\d+\]")

_PREFATORY = re.compile(r"^\s*PREFATORY ADDRESS\s*$")
_INDEX = re.compile(r"^\s*GENERAL INDEX OF CHAPTERS\.\s*$")
_START = re.compile(r"^\s*INSTITUTES OF THE CHRISTIAN RELIGION\s*$")
_APHORISMS = re.compile(r"^\s*ONE HUNDRED APHORISMS,?\s*$")


def extract(raw: bytes) -> str:
    """The file's bytes to the document, with footnote anchors removed.

    Region selection happens here rather than in `segment` because it is a
    property of this file's shape: extraction fails on the shape of a source,
    and taking the Murray introduction would be exactly that failure.
    """
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise AcquisitionError(
            f"{corpus_id}: the source is not UTF-8 ({error}). Decoding it loosely would "
            "silently change the text the fingerprints are taken over, so acquisition "
            "stops here rather than guessing an encoding."
        ) from error

    lines = [_ANCHOR.sub("", line).rstrip() for line in text.splitlines()]

    prefatory = _find(lines, _PREFATORY, "the prefatory address")
    index = _find(lines, _INDEX, "the general index of chapters", after=prefatory)
    start = _find(lines, _START, "the start of the four books", after=index)
    end = _find_optional(lines, _APHORISMS, after=start) or len(lines)

    kept = lines[prefatory:index] + ["INSTITUTES"] + lines[start:end]
    return "\n".join(kept) + "\n"


def _find(lines: list[str], pattern: re.Pattern[str], what: str, *, after: int = 0) -> int:
    found = _find_optional(lines, pattern, after=after)
    if found is None:
        raise AcquisitionError(
            f"{corpus_id}: {what} was not found in {len(lines)} lines — the source's "
            "shape changed, and acquiring it would take whichever region happened to "
            "follow instead"
        )
    return found


def _find_optional(lines: list[str], pattern: re.Pattern[str], *, after: int = 0) -> int | None:
    for index in range(after, len(lines)):
        if pattern.match(lines[index]):
            return index
    return None


# --- segment ---------------------------------------------------------------

_BOOK = re.compile(r"^\s*BOOK (FIRST|SECOND|THIRD|FOURTH)\.?\s*$")
_CHAPTER = re.compile(r"^\s*CHAPTER\b\s*(\d+)?")
_SECTION = re.compile(r"^\s{3}(\d+)\.\s+\S")
_ARGUMENT = re.compile(r"^\s*ARGUMENT\.\s*$")
_MARKER = re.compile(r"^INSTITUTES$")

_ORDINALS = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4}


def segment(document: str) -> Iterator[Segment]:
    """One chunk per numbered section: `Inst. 4.17.10`, and `Inst. Pref.1`.

    Structural, never fixed-token.
    """
    lines = document.splitlines()
    split = next((i for i, line in enumerate(lines) if _MARKER.match(line)), None)
    if split is None:
        raise AcquisitionError(f"{corpus_id}: the extracted document has no book marker")

    yield from _sections(lines[:split], "Inst. Pref.", EXPECTED_PREFATORY_SECTIONS)
    yield from _books(lines[split + 1 :])


def _books(lines: list[str]) -> Iterator[Segment]:
    starts = [i for i, line in enumerate(lines) if _BOOK.match(line)]
    if len(starts) != len(EXPECTED_CHAPTERS):
        raise AcquisitionError(
            f"{corpus_id}: {len(starts)} books, expected {len(EXPECTED_CHAPTERS)}. The "
            "1559 edition is four books; a different count is a different edition."
        )
    bounds = list(zip(starts, starts[1:] + [len(lines)]))
    for number, (first, last) in enumerate(bounds, start=1):
        found = _ORDINALS[_BOOK.match(lines[first]).group(1)]
        if found != number:
            raise AcquisitionError(
                f"{corpus_id}: book {found} where book {number} was expected; the books "
                "are out of order, so extraction took the wrong region"
            )
        yield from _chapters(lines[first:last], number)


def _chapters(lines: list[str], book: int) -> Iterator[Segment]:
    starts = [i for i, line in enumerate(lines) if _CHAPTER.match(line)]
    expected = EXPECTED_CHAPTERS[book - 1]
    if len(starts) != expected:
        raise AcquisitionError(
            f"{corpus_id}: book {book} has {len(starts)} chapters, expected {expected}. "
            "A different count is a different edition, and the divergence is structural "
            "where the diagnostic's is textual."
        )
    bounds = list(zip(starts, starts[1:] + [len(lines)]))
    for number, (first, last) in enumerate(bounds, start=1):
        found = _CHAPTER.match(lines[first]).group(1)
        # Book IV chapter 18 reads `CHAPTER [653]` — the number was swallowed by
        # a footnote anchor. Positional, because recognising the chapter by its
        # title would commit corpus text (ADR-0014).
        if found is not None and int(found) != number:
            raise AcquisitionError(
                f"{corpus_id}: book {book} chapter {found} where chapter {number} was "
                "expected; the chapter numbering is not contiguous"
            )
        yield from _sections(lines[first:last], f"Inst. {book}.{number}.", None)


def _sections(lines: list[str], prefix: str, expected: int | None) -> Iterator[Segment]:
    """The body sections of one chapter, with its own synopsis discarded.

    A chapter lists its sections by title before setting them out in full, so
    the numbers 1..N run twice. The first ascending run is taken, then a second
    after it; when the two agree the second is the body and the first was the
    synopsis, and when they do not the chapter carries no synopsis and the
    single run is the body. Only the next expected number is ever matched, which
    steps over the numbered lists that appear inside the prose.
    """
    openings = [(i, int(m.group(1))) for i, line in enumerate(lines) if (m := _SECTION.match(line))]
    first = _ascending(openings)
    second = _ascending([(i, n) for i, n in openings if not first or i > first[-1][0]])
    body = second if first and len(second) == len(first) else first

    if expected is not None and len(body) != expected:
        raise AcquisitionError(
            f"{corpus_id}: {len(body)} sections under {prefix.rstrip('.')}, expected "
            f"{expected}"
        )
    if not body:
        raise AcquisitionError(f"{corpus_id}: no sections found under {prefix.rstrip('.')}")

    stops = [i for i, _ in body[1:]] + [len(lines)]
    for (start, number), stop in zip(body, stops):
        text = "\n".join(
            line.strip()
            for line in lines[start:stop]
            if line.strip() and not _ARGUMENT.match(line)
        )
        # The opener carries its own number, which is the locator's.
        text = re.sub(rf"^{number}\.\s+", "", text)
        yield Segment(f"{prefix}{number}", text)


def _ascending(openings: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The greedy run 1, 2, 3, … — matching only the next expected number."""
    run: list[tuple[int, int]] = []
    want = 1
    for index, number in openings:
        if number == want:
            run.append((index, number))
            want += 1
    return run
