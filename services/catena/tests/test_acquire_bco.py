"""The PCA's Book of Church Order, 2026 edition.

The only corpus whose source is a PDF. `pcaac.org` serves the BCO through a
JavaScript application -- 230 KB of markup over 0.5% text, all of it navigation
-- and no bare-text edition exists anywhere, so the publisher's own 423-page PDF
is the source. That is why this is the one adapter that costs a parser.

Extraction is split so that only a thin shim touches the PDF: `_document` takes
the page texts pypdf produces and does all the shape work, which is what these
tests drive. Nothing here reads a PDF, and nothing here touches the network.

The document's hazards, each with a test:

* **The running head contains a paragraph number, and alternates by page side.**
  `FORM OF GOVERNMENT 5-1` heads a recto and `5-9 THE BOOK OF CHURCH ORDER` the
  facing verso. Either tail looks exactly like a paragraph opener, so leaving
  one in invents chunks and corrupts the numbering. The fixture below builds
  both sides, and did not until a verso head was reported showing up mid-list in
  the finished text: the adapter and the fixture had been written against each
  other, and the suite asserted that the half of the problem it knew about was
  solved.
* **The blank pages carry a notice**, because each chapter opens on a recto.
* **The part dividers are not shaped alike.** The Directory's spells its title in
  full across two lines and carries a preface of ordinary prose, so a divider
  match suspends the document until the next chapter heading.
* **A paragraph opener is split across two lines** by the page break, at `36-8.`
  in the real document. No opener matches, so the paragraph is absorbed into the
  one before it and a chunk is lost rather than merely dirtied.
* **Chapter 44 is `(Vacated)`** -- a real chapter removed by amendment, leaving
  a heading and no paragraphs. Contiguity cannot be asserted across it.
* **Paragraphs are line-wrapped** by the typesetter and must be rejoined.
* **Amendment bullets** are a private-use glyph the publisher puts in the
  margin to mark what changed this year. They are annotation, not text.

`local-only` under ADR-0017, like the 2000 report.
"""

from __future__ import annotations

import re
import unittest

from catena.acquire import corpora
from catena.acquire.corpora import pca_bco_2026 as bco
from catena.acquire.record import LICENSES, AcquisitionError, stage

LOCATOR = re.compile(r"^BCO (\d{1,2})-(\d{1,3})$")

BULLET = ""


#: The book's title, which heads every verso page where the part's name heads
#: every recto one.
TITLE = "THE BOOK OF CHURCH ORDER"

#: The notice the typesetter puts on the empty page that keeps each chapter
#: opening on a recto.
BLANK_PAGE = "This page intentionally left blank."


def header(part: str, first: str, chapter: int, title: str) -> str:
    """The two lines the typesetter puts at the top of a recto page."""
    return f"{part} {first}\nChapter {chapter}: {title}\n"


def verso(first: str, chapter: int, title: str) -> str:
    """The head on the facing page, which a printed book alternates: the book's
    title rather than the part's, and the paragraph number first rather than
    last. The tail of one is the head of the other, so a filter written against
    a single page side leaves every other page's head in the text."""
    return f"{first} {TITLE}\nChapter {chapter}: {title}\n"


def chapter(number: int, paragraphs: int, *, part: str = "FORM OF GOVERNMENT") -> str:
    lines = [
        header(part, f"{number}-1", number, "An Invented Chapter"),
        f"CHAPTER {number}",
        "",
        " An Invented Chapter",
        "",
    ]
    for n in range(1, paragraphs + 1):
        if n > 1:
            # A page break, and pages alternate sides.
            lines.append(verso(f"{number}-{n}", number, "An Invented Chapter"))
        lines.append(f"{number}-{n}. An invented paragraph {n} of chapter {number}, which ")
        lines.append("wraps across a second typeset line and must be rejoined.")
        lines.append("")
    return "\n".join(lines)


def vacated(number: int, *, part: str = "RULES OF DISCIPLINE") -> str:
    return "\n".join(
        [
            header(part, f"{number}-1", number, "(Vacated)"),
            f"CHAPTER {number}",
            "",
            " (Vacated)",
            "",
        ]
    )


def document(*blocks: str) -> str:
    return bco._document(list(blocks))


def part_of(number: int) -> str:
    if number <= 26:
        return "FORM OF GOVERNMENT"
    return "RULES OF DISCIPLINE" if number <= 46 else "DIRECTORY FOR WORSHIP"


#: All 63 chapters, with 44 vacated — the shape the real document has, because
#: the adapter asserts the last chapter is 63 and that exactly one is empty.
WHOLE = document(
    "PART I\nFORM OF GOVERNMENT\n",
    *(
        vacated(n, part=part_of(n))
        if n in bco.VACATED_CHAPTERS
        else chapter(n, 3 if n % 2 else 2, part=part_of(n))
        for n in range(1, 64)
    ),
)


def segments(text: str = WHOLE) -> list:
    return list(bco.segment(text))


class TestPageFurniture(unittest.TestCase):
    def test_the_running_header_is_not_text(self) -> None:
        """Its tail, `5-1`, looks exactly like a paragraph opener."""
        found = " ".join(s.text for s in segments())
        self.assertNotIn("FORM OF GOVERNMENT", found)
        self.assertNotIn("RULES OF DISCIPLINE", found)

    def test_the_chapter_running_line_is_not_text(self) -> None:
        self.assertNotIn("Chapter 1: An Invented Chapter", " ".join(s.text for s in segments()))

    def test_the_running_header_does_not_invent_a_chunk(self) -> None:
        """`FORM OF GOVERNMENT 5-1` repeated on every page of chapter 5 would
        otherwise produce `BCO 5-1` several times over."""
        found = [s.locator for s in segments()]
        self.assertEqual(len(found), len(set(found)))

    def test_a_part_divider_is_not_absorbed_into_the_paragraph_above_it(self) -> None:
        """`PART II / THE RULES OF DISCIPLINE / The Rules of Discipline` sits on
        its own page between the parts. Left in, it becomes the tail of the last
        paragraph of the part before — `BCO 26-6` in the real document."""
        divided = document(
            "PART I\nFORM OF GOVERNMENT\n",
            *(
                vacated(n, part=part_of(n))
                if n in bco.VACATED_CHAPTERS
                else chapter(n, 3 if n % 2 else 2, part=part_of(n))
                for n in range(1, 27)
            ),
            "PART II\nTHE RULES OF DISCIPLINE\nThe Rules of Discipline\n",
            *(
                vacated(n, part=part_of(n))
                if n in bco.VACATED_CHAPTERS
                else chapter(n, 3 if n % 2 else 2, part=part_of(n))
                for n in range(27, 64)
            ),
        )
        found = " ".join(s.text for s in bco.segment(divided))
        self.assertNotIn("RULES OF DISCIPLINE", found)
        self.assertNotIn("PART II", found)

    def test_the_verso_running_head_is_not_text(self) -> None:
        """The head alternates by page side. `FORM OF GOVERNMENT 5-9` on the
        recto was filtered from the first day; `5-9 THE BOOK OF CHURCH ORDER` on
        the facing page was not, and landed in the middle of whatever paragraph
        spanned the break."""
        self.assertNotIn(TITLE, " ".join(s.text for s in segments()))

    def test_the_verso_running_head_does_not_invent_a_chunk(self) -> None:
        found = [s.locator for s in segments()]
        self.assertEqual(len(found), len(set(found)))

    def test_a_blank_page_is_not_text(self) -> None:
        """Chapters open on a recto, so the typesetter pads with an empty page
        carrying a notice. It is furniture, and it lands in the paragraph that
        the padded page break interrupts."""
        padded = document(
            "PART I\nFORM OF GOVERNMENT\n",
            *(
                vacated(n, part=part_of(n))
                if n in bco.VACATED_CHAPTERS
                else chapter(n, 3 if n % 2 else 2, part=part_of(n)) + f"{BLANK_PAGE}\n"
                for n in range(1, 64)
            ),
        )
        self.assertNotIn("intentionally left blank", " ".join(s.text for s in segments(padded)))

    def test_the_worship_divider_is_not_absorbed_into_the_paragraph_above_it(self) -> None:
        """The third part's divider page is not shaped like the second's. It
        spells the title in full and breaks it across two lines --
        `THE DIRECTORY FOR THE WORSHIP` / `OF GOD` -- where `PARTS` carries the
        short form the running head uses, and it carries a preface the other two
        dividers do not have. All of it lands in the last paragraph of the part
        before, `BCO 46-8` in the real document."""
        divided = document(
            "PART I\nFORM OF GOVERNMENT\n",
            *(
                vacated(n, part=part_of(n))
                if n in bco.VACATED_CHAPTERS
                else chapter(n, 3 if n % 2 else 2, part=part_of(n))
                for n in range(1, 47)
            ),
            "PART III\nTHE DIRECTORY FOR THE WORSHIP\nOF GOD\n"
            "The Directory for the Worship of God\n"
            "An invented preface the divider page carries and no paragraph owns.\n",
            *(
                chapter(n, 3 if n % 2 else 2, part=part_of(n))
                for n in range(47, 64)
            ),
        )
        last = next(s for s in bco.segment(divided) if s.locator == "BCO 46-2")
        self.assertNotIn("DIRECTORY", last.text)
        self.assertNotIn("invented preface", last.text)

    def test_the_amendment_bullet_is_not_text(self) -> None:
        """It is stripped in `_document`, so the bullet has to go into the page
        text the PDF yields rather than into the document that comes out."""
        marked = document(
            "PART I\nFORM OF GOVERNMENT\n",
            *(
                vacated(n, part=part_of(n))
                if n in bco.VACATED_CHAPTERS
                else chapter(n, 3 if n % 2 else 2, part=part_of(n)).replace(
                    f"{n}-1. An invented", f"{BULLET} {n}-1. An invented"
                )
                for n in range(1, 64)
            ),
        )
        self.assertNotIn(BULLET, " ".join(s.text for s in segments(marked)))


class TestFrontMatter(unittest.TestCase):
    """The pages before the constitution include an amendment summary listing
    cross-references — `4-21.d.5; 11-5; 16-3.e.5` — which match a paragraph
    opener exactly. Without a start boundary they abort the run, and with a
    careless one they become chunks."""

    FRONT = (
        "THE BOOK OF CHURCH ORDER\n"
        "PART I -- FORM OF GOVERNMENT\n"
        "PART II -- THE RULES OF DISCIPLINE\n"
        "4-21. d.5; 11-5; 16-3.e.5 and renumber; OMSJC 4\n"
        "16-6. c.1 (editorial); 16-11; 17-3 and renumber\n"
    )

    def whole(self) -> str:
        return document(
            self.FRONT,
            "PART I\nFORM OF GOVERNMENT\n",
            *(
                vacated(n, part=part_of(n))
                if n in bco.VACATED_CHAPTERS
                else chapter(n, 3 if n % 2 else 2, part=part_of(n))
                for n in range(1, 64)
            ),
        )

    def test_front_matter_does_not_abort_the_run(self) -> None:
        self.assertTrue(list(bco.segment(self.whole())))

    def test_the_amendment_summary_is_not_a_chunk(self) -> None:
        found = [s for s in bco.segment(self.whole()) if s.locator == "BCO 4-21"]
        self.assertEqual(found, [])

    def test_a_contents_entry_is_not_the_body_marker(self) -> None:
        """`PART I -- FORM OF GOVERNMENT` is the table of contents; the body
        opens with a bare `PART I`."""
        self.assertNotIn(
            "THE BOOK OF CHURCH ORDER", " ".join(s.text for s in bco.segment(self.whole()))
        )


class TestParagraphs(unittest.TestCase):
    def test_a_wrapped_paragraph_is_rejoined(self) -> None:
        first = next(s for s in segments() if s.locator == "BCO 1-1")
        self.assertIn("wraps across a second typeset line and must be rejoined.", first.text)

    def test_the_paragraph_number_is_not_repeated_in_the_text(self) -> None:
        first = next(s for s in segments() if s.locator == "BCO 1-1")
        self.assertTrue(first.text.startswith("An invented paragraph 1"), first.text)

    def test_locators_have_the_documented_form(self) -> None:
        for segment in segments():
            self.assertRegex(segment.locator, LOCATOR)

    def test_every_locator_can_be_written_to_a_fingerprints_file(self) -> None:
        for segment in segments():
            stage(segment.locator, segment.text)

    def test_an_opener_split_by_the_page_break_still_opens_a_chunk(self) -> None:
        """`36-8.` in the real document is emitted as `36` and `-8. When members`
        on two lines, so no opener matches and the paragraph is swallowed by the
        one before it. Being the last paragraph of its chapter, nothing after it
        re-anchors the count, and the contiguity check below cannot see it."""
        opener = "2-2. An invented paragraph 2"
        split = document(
            "PART I\nFORM OF GOVERNMENT\n",
            *(
                vacated(n, part=part_of(n))
                if n in bco.VACATED_CHAPTERS
                else chapter(n, 3 if n % 2 else 2, part=part_of(n)).replace(
                    opener, "2\n-2. An invented paragraph 2"
                )
                for n in range(1, 64)
            ),
        )
        found = [s.locator for s in bco.segment(split)]
        self.assertIn("BCO 2-2", found)
        self.assertEqual(found, [s.locator for s in segments()])

    def test_paragraph_numbering_is_contiguous_within_a_chapter(self) -> None:
        broken = WHOLE.replace("1-2. An invented paragraph 2", "1-4. An invented paragraph 4")
        with self.assertRaises(AcquisitionError) as caught:
            segments(broken)
        self.assertIn("contiguous", str(caught.exception))


class TestTheVacatedChapter(unittest.TestCase):
    """Chapter 44 was removed by amendment and left a placeholder. It has a
    heading and no paragraphs, so contiguity cannot be asserted across it."""

    def test_a_vacated_chapter_yields_no_chunks(self) -> None:
        self.assertNotIn("BCO 44-1", [s.locator for s in segments()])

    def test_the_word_vacated_is_not_a_chunk(self) -> None:
        self.assertNotIn("(Vacated)", [s.text for s in segments()])

    def test_the_next_chapter_still_parses(self) -> None:
        self.assertIn("BCO 45-1", [s.locator for s in segments()])

    def test_the_vacated_chapters_are_asserted(self) -> None:
        self.assertEqual(bco.VACATED_CHAPTERS, (44,))


class TestAdapterContract(unittest.TestCase):
    def test_the_corpus_id_names_the_edition_the_source_serves(self) -> None:
        """The source's title page says the 53rd General Assembly, 2026. A
        `pca-bco-2024` ID would name a constitution two assemblies old."""
        self.assertEqual(bco.corpus_id, "pca-bco-2026")

    def test_the_corpus_is_local_only(self) -> None:
        self.assertEqual(bco.work.license, "local-only")
        self.assertIn(bco.work.license, LICENSES)

    def test_the_adapter_is_registered(self) -> None:
        self.assertIn(bco.corpus_id, corpora.CORPUS_IDS)
        self.assertIs(corpora.load(bco.corpus_id), bco)


if __name__ == "__main__":
    unittest.main()
