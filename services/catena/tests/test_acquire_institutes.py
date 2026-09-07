"""Calvin's *Institutes*, 1559 edition in the Beveridge translation.

The largest Phase 1 corpus and the only translated one. CCEL serves it as plain
text rather than markup, so this adapter shares nothing with the three
Westminster Standards -- there is no `_opc` here.

ADR-0014 bars corpus text from fixtures, so every document below is invented
text in the source's layout. The layout is the whole point: this source carries
four hazards that a parser gets silently wrong, and each has a test.

1. **Every chapter opens with a numbered synopsis of itself** -- a list of
   one-line section titles numbered 1..N -- and then repeats 1..N as the real
   body. Taken naively a chapter yields 2N chunks, half of them title fragments
   that would hash, bless, and verify clean forever. Six of the eighty chapters
   have no synopsis at all, so its presence cannot be assumed either.
2. **Book IV chapter 18's number is missing from the source**, replaced by a
   footnote anchor: `CHAPTER [653]`. Dropped, it loses a chapter; mishandled, it
   renumbers every chapter after it.
3. **Numbered lists inside the prose** look exactly like section openings.
4. **Footnote anchors** -- 1,283 inside the four books -- are CCEL apparatus.

What is not the corpus is as decided as what is: the CCEL header, John Murray's
20th-century introduction (which is in copyright), Norton's 1581 translator's
preface, the indexes, each book's editorial ARGUMENT, and the One Hundred
Aphorisms appended at the end.

Nothing here touches the network.
"""

from __future__ import annotations

import re
import unittest
from unittest import mock

from catena.acquire import corpora
from catena.acquire.corpora import calvin_institutes_1559_beveridge as inst
from catena.acquire.record import LICENSES, AcquisitionError, stage

LOCATOR = re.compile(r"^Inst\. (\d+)\.(\d+)\.(\d+)\.p(\d+)$")
PREF = re.compile(r"^Inst\. Pref\.(\d+)\.p(\d+)$")


def section(number: int, *, lines: int = 2, paragraphs: int = 1) -> str:
    """A body section: a numbered opener, its continuation lines, and any
    further paragraphs. The source separates paragraphs with a blank line, and
    that blank line is what makes this corpus embeddable."""
    body = "\n".join(
        f"   continuation line {n} of an invented section." for n in range(1, lines)
    )
    opener = f"   {number}. Invented section {number}, standing in for text this repository"
    first = opener + ("\n" + body if body else "")
    rest = [
        f"   Invented paragraph {p} of section {number}, which the source sets off."
        for p in range(2, paragraphs + 1)
    ]
    return "\n\n".join([first] + rest)


def synopsis(count: int) -> str:
    """The chapter's own table of contents, which is not text."""
    return "\n".join(f"   {n}. Invented title of section {n}." for n in range(1, count + 1))


def chapter(
    number: int | None,
    sections: int,
    *,
    with_synopsis: bool = True,
    paragraphs: int = 1,
) -> str:
    head = f"  CHAPTER {number}." if number is not None else "  CHAPTER [653]"
    parts = [head, "", "   OF INVENTED MATTERS.", ""]
    if with_synopsis:
        parts += [synopsis(sections), ""]
    parts += ["\n\n".join(section(n, paragraphs=paragraphs) for n in range(1, sections + 1)), ""]
    return "\n".join(parts)


def book(number: int, chapters: list[str]) -> str:
    name = {1: "FIRST", 2: "SECOND", 3: "THIRD", 4: "FOURTH"}[number]
    return "\n".join([f"  BOOK {name}.", "", "  ARGUMENT.", "",
                      "   An editorial summary of the book, which is not Calvin.", ""] + chapters)


def document(shape: dict[int, list[int]], *, prefatory: int = 7, **kw) -> str:
    """A whole file: front matter, the prefatory address, four books, aphorisms."""
    front = [
        "     ____________________", "           Title: The Institutes of the Christian Religion",
        "          Rights: Public Domain", "     ____________________", "",
        "INTRODUCTION", "", "   By The Rev. John Murray, M.A., Th.M.", "",
        "   Twentieth-century matter that is in copyright and is not the work.", "",
        "THE ORIGINAL TRANSLATOR'S PREFACE.", "",
        "   Norton's 1581 preface, which is apparatus.", "",
        "PREFATORY ADDRESS", "", "   TO FRANCIS, KING OF THE FRENCH,", "",
    ]
    front.append("\n\n".join(section(n) for n in range(1, prefatory + 1)))
    front += ["", "GENERAL INDEX OF CHAPTERS.", "", "  BOOK FIRST.", "",
              "INSTITUTES OF THE CHRISTIAN RELIGION", ""]
    books = [
        book(b, [chapter(c + 1, n, **kw) for c, n in enumerate(shape[b])])
        for b in sorted(shape)
    ]
    tail = ["", "                          ONE HUNDRED APHORISMS, [693]", "", "BOOK 1", "",
            "   1. An aphorism, which is a later editor's apparatus.", ""]
    return "\n".join(front + books + tail) + "\n"


WHOLE = {1: [3] * 18, 2: [4] * 17, 3: [2] * 25, 4: [12] * 20}


def segments(text: str) -> list:
    return list(inst.segment(inst.extract(text.encode("utf-8"))))


class TestTheCorpusBoundary(unittest.TestCase):
    def test_the_murray_introduction_is_not_ingested(self) -> None:
        """It is 20th-century apparatus and in copyright."""
        found = " ".join(s.text for s in segments(document(WHOLE)))
        self.assertNotIn("copyright and is not the work", found)

    def test_the_translators_preface_and_indexes_are_not_ingested(self) -> None:
        found = " ".join(s.text for s in segments(document(WHOLE)))
        self.assertNotIn("1581 preface", found)

    def test_each_books_editorial_argument_is_not_ingested(self) -> None:
        found = " ".join(s.text for s in segments(document(WHOLE)))
        self.assertNotIn("editorial summary", found)

    def test_the_appended_aphorisms_are_not_ingested(self) -> None:
        found = " ".join(s.text for s in segments(document(WHOLE)))
        self.assertNotIn("aphorism", found.lower())


class TestLocators(unittest.TestCase):
    def test_body_sections_use_book_chapter_section(self) -> None:
        found = [s.locator for s in segments(document(WHOLE)) if not PREF.match(s.locator)]
        for locator in found:
            self.assertRegex(locator, LOCATOR)

    def test_the_prefatory_address_has_its_own_locator_form(self) -> None:
        found = [s.locator for s in segments(document(WHOLE)) if PREF.match(s.locator)]
        self.assertEqual(found, [f"Inst. Pref.{n}.p1" for n in range(1, 8)])

    def test_every_locator_can_be_written_to_a_fingerprints_file(self) -> None:
        """`Inst. 4.17.10.p1` is two tokens separated by one space, which
        LOCATOR permits and which `WSC Q&A 1` already relies on. The
        fingerprints file is `<locator>  <sha256>` split on the double space, so
        a single internal space has to survive the round trip."""
        for segment in segments(document(WHOLE, paragraphs=3)):
            stage(segment.locator, segment.text)

    def test_locators_are_unique(self) -> None:
        """Across the whole document, not within a chapter. A duplicate locator
        is two chunks claiming one address, and the fingerprints file would keep
        whichever was written last without saying so. This is the assertion that
        would have caught this class of defect on the first pass."""
        found = [s.locator for s in segments(document(WHOLE, paragraphs=4))]
        self.assertEqual(len(found), len(set(found)))


class TestParagraphChunking(unittest.TestCase):
    """A chunk is a paragraph. The section is the path in the locator.

    The source's longest section is 16,714 tokens against BGE-M3's window of
    8,192, and a chunk the encoder cannot read whole is retrieved on its
    opening fraction and quoted from its whole text -- which verification
    cannot catch, because check 2 matches the text and not the vector.
    """

    def test_a_multi_paragraph_section_yields_one_chunk_per_paragraph(self) -> None:
        found = [s.locator for s in segments(document(WHOLE, paragraphs=3))
                 if s.locator.startswith("Inst. 1.1.1.")]
        self.assertEqual(found, ["Inst. 1.1.1.p1", "Inst. 1.1.1.p2", "Inst. 1.1.1.p3"])

    def test_a_single_paragraph_section_still_carries_an_ordinal(self) -> None:
        """Uniform: the 1,133 single-paragraph sections take `.p1` too, so the
        locator has one shape rather than two."""
        found = [s.locator for s in segments(document(WHOLE))
                 if s.locator.startswith("Inst. 1.1.1")]
        self.assertEqual(found, ["Inst. 1.1.1.p1"])

    def test_the_paragraphs_of_a_section_do_not_share_text(self) -> None:
        found = {s.locator: s.text for s in segments(document(WHOLE, paragraphs=2))}
        self.assertIn("continuation line", found["Inst. 1.1.1.p1"])
        self.assertNotIn("continuation line", found["Inst. 1.1.1.p2"])
        self.assertIn("Invented paragraph 2", found["Inst. 1.1.1.p2"])

    def test_the_opener_number_is_stripped_from_the_first_paragraph_only(self) -> None:
        """The opener carries the section's own number, which is the locator's.
        Paragraphs after it carry nothing to strip."""
        found = {s.locator: s.text for s in segments(document(WHOLE, paragraphs=2))}
        self.assertTrue(found["Inst. 1.1.1.p1"].startswith("Invented section 1,"))
        self.assertTrue(found["Inst. 1.1.1.p2"].startswith("Invented paragraph 2"))

    def test_a_rule_becomes_a_break_rather_than_nothing(self) -> None:
        """A rule is a divider. Blanking it splits the paragraph it interrupts;
        dropping it would fuse the text on either side into one chunk. On the
        real source the two are indistinguishable, so this pins the behaviour
        that only matters once the source moves a rule."""
        text = document(WHOLE).replace(
            "   continuation line 1 of an invented section.",
            "   __________________________________________\n"
            "   continuation line 1 of an invented section.",
            1,
        )
        found = [s.locator for s in segments(text) if s.locator.startswith("Inst. Pref.1.")]
        self.assertEqual(found, ["Inst. Pref.1.p1", "Inst. Pref.1.p2"])

    def test_a_rule_at_a_sections_end_leaves_no_trailing_chunk(self) -> None:
        """81 of the 172 sit on a section's last line. A blank run that closes a
        section must end nothing, not open an empty chunk."""
        text = document(WHOLE).replace(
            "   continuation line 1 of an invented section.",
            "   continuation line 1 of an invented section.\n"
            "   __________________________________________",
            1,
        )
        found = [s.locator for s in segments(text) if s.locator.startswith("Inst. Pref.1.")]
        self.assertEqual(found, ["Inst. Pref.1.p1"])

    def test_a_section_whose_opener_lost_its_number_fails(self) -> None:
        """The opener strip assumes `_SECTION` guarantees `N. ` at the head of
        the first paragraph. The two patterns are coupled, and this assertion is
        what makes loosening one without the other fail loudly rather than leave
        a stray number at the head of a chunk that would hash, bless and verify
        clean forever. Patched, because the coupling is what is under test:
        through the public seam the two patterns cannot disagree."""
        lines = ["   1 Invented section whose opener lost its full stop.", ""]
        loosened = re.compile(r"^\s{3}(\d+)\s+\S")
        with mock.patch.object(inst, "_SECTION", loosened):
            with self.assertRaises(AcquisitionError) as caught:
                list(inst._sections(lines, "Inst. Pref.", 1))
        self.assertIn("own number", str(caught.exception))

    def test_a_chunk_past_the_ceiling_fails(self) -> None:
        """A canary, not a limit. The longest chunk this source produces is
        11,498 characters; the ceiling is far above that and far below the
        window, so it never argues with a characters-per-token ratio. What it
        catches is a reflow that removes the blank lines."""
        self.assertEqual(inst.MAX_CHUNK_CHARACTERS, 20_000)
        long_line = "   " + "invented words " * 2_000
        text = document(WHOLE).replace(
            "   continuation line 1 of an invented section.", long_line, 1
        )
        with self.assertRaises(AcquisitionError) as caught:
            segments(text)
        self.assertIn("20000", str(caught.exception).replace(",", ""))


class TestTheSynopsisHazard(unittest.TestCase):
    """A chapter's own numbered contents list is not text."""

    def test_a_chapter_yields_its_sections_and_not_twice_that(self) -> None:
        found = [s for s in segments(document(WHOLE))
                 if s.locator.startswith("Inst. 1.1.")]
        self.assertEqual([s.locator for s in found],
                         ["Inst. 1.1.1.p1", "Inst. 1.1.2.p1", "Inst. 1.1.3.p1"])

    def test_the_synopsis_titles_are_not_the_chunk_text(self) -> None:
        found = segments(document(WHOLE))[7]
        self.assertNotIn("Invented title of", found.text)
        self.assertIn("Invented section", found.text)

    def test_a_chapter_with_no_synopsis_still_yields_its_sections(self) -> None:
        """Six of the eighty chapters carry none."""
        found = [s.locator for s in segments(document(WHOLE, with_synopsis=False))
                 if s.locator.startswith("Inst. 1.1.")]
        self.assertEqual(found, ["Inst. 1.1.1.p1", "Inst. 1.1.2.p1", "Inst. 1.1.3.p1"])


class TestStructuralAssertions(unittest.TestCase):
    def test_the_expected_book_and_chapter_shape_is_asserted(self) -> None:
        self.assertEqual(inst.EXPECTED_CHAPTERS, (18, 17, 25, 20))
        self.assertEqual(sum(inst.EXPECTED_CHAPTERS), 80)

    def test_a_missing_chapter_fails(self) -> None:
        short = dict(WHOLE)
        short[4] = [5] * 19
        with self.assertRaises(AcquisitionError) as caught:
            segments(document(short))
        self.assertIn("chapter", str(caught.exception).lower())

    def test_a_chapter_whose_number_the_source_lost_takes_the_next_one(self) -> None:
        """Book IV chapter 18 reads `CHAPTER [653]`. Recognised positionally,
        because recognising it by its title would commit corpus text."""
        chapters = [chapter(c + 1, 2) for c in range(17)]
        chapters.append(chapter(None, 2))
        chapters += [chapter(c, 2) for c in (19, 20)]
        text = document({1: [3] * 18, 2: [4] * 17, 3: [2] * 25, 4: []})
        text = text.replace("  BOOK FOURTH.\n", "  BOOK FOURTH.\n" + "\n".join(chapters))
        found = [s.locator for s in segments(text) if s.locator.startswith("Inst. 4.18.")]
        self.assertEqual(found, ["Inst. 4.18.1.p1", "Inst. 4.18.2.p1"])


class TestApparatus(unittest.TestCase):
    def test_footnote_anchors_do_not_survive(self) -> None:
        text = document(WHOLE).replace("Invented section 1,", "Invented section 1,[653]")
        self.assertNotIn("[653]", " ".join(s.text for s in segments(text)))

    def test_horizontal_rules_do_not_survive(self) -> None:
        """172 of them, 66 underscores each. CCEL's apparatus, not Calvin's text,
        and live in verification -- a quote spanning one would have to reproduce
        sixty-six underscores to pass check 2."""
        text = document(WHOLE).replace(
            "   continuation line 1 of an invented section.",
            "   __________________________________________\n"
            "   continuation line 1 of an invented section.",
        )
        self.assertNotIn("__", " ".join(s.text for s in segments(text)))


class TestAdapterContract(unittest.TestCase):
    def test_the_corpus_id_is_edition_and_translation_specific(self) -> None:
        self.assertEqual(inst.corpus_id, "calvin-institutes-1559-beveridge")

    def test_it_is_the_corpus_that_exercises_translation(self) -> None:
        self.assertEqual(inst.work.source_language, "la")
        self.assertEqual(inst.work.language, "en")

    def test_the_licence_is_a_closed_enum_value(self) -> None:
        self.assertIn(inst.work.license, LICENSES)

    def test_the_diagnostic_is_among_the_locators(self) -> None:
        self.assertIn(inst.diagnostic, [s.locator for s in segments(document(WHOLE))])

    def test_the_adapter_is_registered(self) -> None:
        self.assertIn(inst.corpus_id, corpora.CORPUS_IDS)
        self.assertIs(corpora.load(inst.corpus_id), inst)


if __name__ == "__main__":
    unittest.main()
