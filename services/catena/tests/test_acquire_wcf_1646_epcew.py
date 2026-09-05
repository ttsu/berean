"""The 1646 confession in the EPCEW's modernised English, the `contrary` corpus.

It is what makes the 1788 diagnostics mean anything: without it the repository
asserts that the American revision diverges from a 1646 text it does not hold.

Its locators are the *same* as the 1788 corpus's — `WCF 23.3` exists in both,
which is exactly why INTEGRATION-SPEC says a locator alone is not unique and
verification resolves `{corpus_id, locator}`. The two editions differ at 23.3,
and chapter 31 has five sections here against the American revision's four.

The source is published a chapter to a page, so this is the first corpus to use
`FetchPlan.follow`: the adapter reads the chapter URLs out of the contents page
and fetch downloads them into one blob. The URLs are discovered rather than
listed because they carry the confession's chapter titles, and 33 of those in an
adapter is the document's table of contents (ADR-0014).

Invented text throughout, in the source's layout. Nothing here touches the
network.
"""

from __future__ import annotations

import re
import unittest

from catena.acquire import corpora
from catena.acquire.corpora import wcf_1646_epcew_modernised as wcf
from catena.acquire.record import LICENSES, AcquisitionError, stage

LOCATOR = re.compile(r"^WCF (\d+)\.(\d+)$")

ROMAN = [
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII",
    "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX", "XXI", "XXII", "XXIII", "XXIV",
    "XXV", "XXVI", "XXVII", "XXVIII", "XXIX", "XXX", "XXXI", "XXXII", "XXXIII",
]

NAV = (
    '<p align="center">'
    '<a href="http://epcew.example/wcf/chapter-i">Previous</a> | '
    '<a href="http://epcew.example/wcf/chapter-iii">Next</a> | '
    '<a href="http://epcew.example/westminster-confession-of-faith">Contents</a></p>'
)


def section_markup(numeral: str, *, footnote: bool = True) -> str:
    note = (
        f'<a href="http://epcew.example/wcf/chapter-x/footnotes#fn1" name="fn1">[1]</a>'
        if footnote
        else ""
    )
    return (
        f"<p>{numeral}. Invented section {numeral}, standing in for text this "
        f"repository does not carry.{note}</p>"
    )


def chapter_page(chapter: int, sections: int) -> bytes:
    body = "\n".join(section_markup(ROMAN[n]) for n in range(sections))
    return f"""<html><body>
<div class="et_pb_fullwidth_header_container center"><div class="header-content">
<h1 class="et_pb_module_header">Chapter {ROMAN[chapter - 1]} Of Invented Matters</h1>
</div></div>
<div class="et_pb_text_inner">{NAV}
<h1 align="center"></h1>
{body}
{NAV}</div>
</body></html>""".encode("utf-8")


def contents_page(chapters: int = 33) -> bytes:
    links = "\n".join(
        f'<p><a href="http://epcew.example/resources/westminster-confession-of-faith/'
        f'chapter-{ROMAN[n].lower()}-of-invented-matters">Chapter {ROMAN[n]}</a></p>'
        for n in range(chapters)
    )
    return f"<html><body><div class='entry-content'>{links}</div></body></html>".encode("utf-8")


def unnumbered_page(chapter: int) -> bytes:
    """Chapter 12, *Of Adoption*: one paragraph, and the source does not number it."""
    return (
        f"<html><body>"
        f'<h1 class="et_pb_module_header">Chapter {ROMAN[chapter - 1]} Of Adoption</h1>'
        f'<div class="et_pb_text_inner">{NAV}'
        f"<p>An invented single paragraph standing in for a whole chapter.</p>"
        f"{NAV}</div></body></html>"
    ).encode("utf-8")


#: The real document has exactly one, and the adapter asserts it, so the fixture
#: has to carry it too.
UNNUMBERED = 12


def document(shape: list[int], *, unnumbered: tuple[int, ...] = (UNNUMBERED,)) -> bytes:
    return b"\n".join(
        unnumbered_page(n + 1) if n + 1 in unnumbered else chapter_page(n + 1, s)
        for n, s in enumerate(shape)
    )


WHOLE = [3] * 30 + [5, 2, 2]  # chapter 31 has five sections in 1646;
WHOLE[11] = 1                 # chapter 12 is one unnumbered paragraph


def segments(raw: bytes) -> list:
    return list(wcf.segment(wcf.extract(raw)))


class TestFollowingTheContentsPage(unittest.TestCase):
    def test_every_chapter_link_is_followed_in_reading_order(self) -> None:
        found = wcf.fetch_plan().follow(contents_page())
        self.assertEqual(len(found), 33)
        self.assertIn("chapter-i-of", found[0])
        self.assertIn("chapter-xxxiii-of", found[-1])

    def test_a_contents_page_missing_chapters_fails(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            wcf.fetch_plan().follow(contents_page(32))
        self.assertIn("33", str(caught.exception))

    def test_links_are_not_duplicated_when_the_page_repeats_them(self) -> None:
        doubled = contents_page().replace(b"</div>", contents_page()[-60:] + b"</div>")
        self.assertEqual(len(wcf.fetch_plan().follow(doubled)), 33)


class TestLocators(unittest.TestCase):
    def test_locators_match_the_1788_corpus_form(self) -> None:
        """`WCF 23.3` exists in both editions; `{corpus_id, locator}` is what
        resolves it, which is why the form must be identical."""
        for segment in segments(document(WHOLE)):
            self.assertRegex(segment.locator, LOCATOR)

    def test_roman_numerals_become_arabic(self) -> None:
        found = [s.locator for s in segments(document(WHOLE))]
        self.assertIn("WCF 31.5", found)
        self.assertIn("WCF 33.2", found)

    def test_every_locator_can_be_written_to_a_fingerprints_file(self) -> None:
        for segment in segments(document(WHOLE)):
            stage(segment.locator, segment.text)


class TestApparatusAndNavigation(unittest.TestCase):
    def test_proof_text_markers_do_not_survive(self) -> None:
        """Taking the apparatus is what turns a public-domain text into
        someone's copyrighted arrangement of it."""
        self.assertNotIn("[1]", " ".join(s.text for s in segments(document(WHOLE))))

    def test_navigation_is_not_text(self) -> None:
        found = " ".join(s.text for s in segments(document(WHOLE)))
        for word in ("Previous", "Next", "Contents"):
            self.assertNotIn(word, found)

    def test_the_legacy_footnote_link_form_is_dropped_too(self) -> None:
        """The site carries two styles. The current one puts `footnotes` in the
        path; the older one is `/wcf/I_fn.html#fn10`. Both are the apparatus,
        and matching only the first left markers in eight chunks."""
        legacy = document(WHOLE).replace(
            b'href="http://epcew.example/wcf/chapter-x/footnotes#fn1"',
            b'href="http://epcew.example/wcf/I_fn.html#fn10"',
        )
        self.assertNotIn("[1]", " ".join(s.text for s in segments(legacy)))

    def test_a_marker_that_survives_extraction_is_an_error(self) -> None:
        """A leaked marker is a fingerprint of text plus apparatus, and it would
        bless and verify clean. Extraction refuses rather than passing it on."""
        leaked = document(WHOLE).replace(
            b"<p>I. Invented section I,", b"<p>I. Invented[9] section I,", 1
        )
        with self.assertRaises(AcquisitionError) as caught:
            segments(leaked)
        self.assertIn("proof-text", str(caught.exception).lower())

    def test_navigation_is_counted_rather_than_dropped_silently(self) -> None:
        """Two per chapter. A change in the count means the page shape moved."""
        broken = document(WHOLE).replace(NAV.encode(), b"", 1)
        with self.assertRaises(AcquisitionError) as caught:
            segments(broken)
        self.assertIn("navigation", str(caught.exception).lower())


class TestTheUnnumberedChapter(unittest.TestCase):
    """Chapter 12, *Of Adoption*, is one paragraph and the source does not
    number it. It is still section 1 -- the 1788 edition numbers the same
    paragraph -- and dropping it would lose `WCF 12.1` entirely."""

    def test_an_unnumbered_single_paragraph_becomes_section_one(self) -> None:
        self.assertIn("WCF 12.1", [s.locator for s in segments(document(WHOLE))])

    def test_its_text_is_the_paragraph(self) -> None:
        found = next(s for s in segments(document(WHOLE)) if s.locator == "WCF 12.1")
        self.assertIn("single paragraph standing in", found.text)

    def test_more_than_one_such_chapter_fails(self) -> None:
        """One is a feature of the document; two is stray text being absorbed."""
        with self.assertRaises(AcquisitionError) as caught:
            segments(document(WHOLE, unnumbered=(12, 13)))
        self.assertIn("unnumbered", str(caught.exception).lower())

    def test_none_at_all_fails_too(self) -> None:
        with self.assertRaises(AcquisitionError):
            segments(document(WHOLE, unnumbered=()))


class TestStructuralAssertions(unittest.TestCase):
    def test_thirty_three_chapters_are_asserted(self) -> None:
        self.assertEqual(wcf.EXPECTED_CHAPTERS, 33)
        with self.assertRaises(AcquisitionError):
            segments(document([3] * 32))

    def test_chapter_thirty_one_must_have_five_sections(self) -> None:
        """The structural half of the edition check: the American revision has
        four there, and this divergence needs no text to detect."""
        four = list(WHOLE)
        four[30] = 4
        with self.assertRaises(AcquisitionError) as caught:
            segments(document(four))
        self.assertIn("31", str(caught.exception))

    def test_non_contiguous_sections_fail(self) -> None:
        page = chapter_page(1, 3).replace(b"II. Invented", b"IV. Invented")
        with self.assertRaises(AcquisitionError):
            segments(page + b"\n" + document(WHOLE)[len(chapter_page(1, 3)) + 1 :])


class TestAdapterContract(unittest.TestCase):
    def test_the_corpus_id_is_edition_specific(self) -> None:
        self.assertEqual(wcf.corpus_id, "wcf-1646-epcew-modernised")

    def test_the_diagnostic_is_the_same_locator_as_the_1788_corpus(self) -> None:
        self.assertEqual(wcf.diagnostic, "WCF 23.3")
        self.assertIn(wcf.diagnostic, [s.locator for s in segments(document(WHOLE))])

    def test_the_licence_is_a_closed_enum_value(self) -> None:
        self.assertIn(wcf.work.license, LICENSES)

    def test_the_adapter_is_registered(self) -> None:
        self.assertIn(wcf.corpus_id, corpora.CORPUS_IDS)
        self.assertIs(corpora.load(wcf.corpus_id), wcf)


if __name__ == "__main__":
    unittest.main()
