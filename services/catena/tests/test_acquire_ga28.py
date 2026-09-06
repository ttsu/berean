"""The PCA's 2000 creation study committee report.

The corpus that makes UC-4 answerable. Without it the corpus says only "in the
space of six days" (WCF 4.1), and the denomination's actual ruling -- that a
diversity of views on the creation days is acceptable -- appears nowhere.

Two things decide the shape of this adapter.

**The recommendations must be addressable apart from the body.** A profile's
`ruling_source` resolves to `GA28 Rec.2`, and it must never resolve to the
expository body, which argues four interpretations the denomination did not
adopt. Tier is per corpus rather than per chunk (ADR-0015), so the locator is
the only thing separating advocacy from ruling.

**PLAN's "per numbered section" does not survive the document.** Section IV.A,
the Calendar-Day Interpretation, is 40,659 characters with no subsections --
past BGE-M3's token limit, so it could not be embedded at all. Chunks are
paragraphs, and the section path lives in the locator instead.

`local-only` under ADR-0017: acquired and ingested, refused at verification
check 4 unless a deployer opts in.

Invented text throughout. Nothing here touches the network.
"""

from __future__ import annotations

import re
import unittest

from catena.acquire import corpora
from catena.acquire.corpora import pca_ga28_2000_creation_study as ga28
from catena.acquire.record import LICENSES, AcquisitionError, stage

BODY = re.compile(r"^GA28 ([IVX]+(?:\.[A-Z])?(?:\.\d+)?)\.(\d+)$")
REC = re.compile(r"^GA28 Rec\.(\d+)$")


def para(text: str) -> str:
    return f'<p style="x"><font size="2">{text}</font></p>'


def heading(text: str, anchor: str = "a") -> str:
    return f'<p><font size="2"><b><a name="{anchor}" id="{anchor}"></a>{text}</b></font></p>'


def footnoted(text: str, n: int = 1) -> str:
    marker = f'<a href="#_ftn{n}" name="_ftnref{n}" id="_ftnref{n}"><sup>[{n}]</sup></a>'
    return para(f"{text}{marker}")


BODY_MARKER = '<div align="center"><b>REPORT OF THE CREATION STUDY COMMITTEE</b></div>'


def page(*blocks: str) -> bytes:
    """Site furniture, a contents table, the body marker, then the report."""
    return (
        "<html><body>"
        "<div class='nav'><p>PCA HISTORICAL CENTER navigation that is not the report.</p></div>"
        # The marker appears twice: once as the page's title above the contents
        # table, once as the body's own heading below it. The second one starts
        # the report.
        f"<div align='center'><b>REPORT OF THE CREATION STUDY COMMITTEE</b></div>"
        "<p><font size='2'>[27th General Assembly (1999).]</font></p>"
        "<table><tr><td><font size='2'>Table of Contents</font></td></tr>"
        "<tr><td><font size='2'>I. Introductory Statement 2302</font></td></tr>"
        f"<tr><td colspan='12'>{BODY_MARKER}</td></tr></table>"
        + "".join(blocks)
        + "</body></html>"
    ).encode("utf-8")


RECOMMENDATIONS = "".join(
    [
        heading("RECOMMENDATIONS", "f2"),
        para("We, therefore, recommend the following:"),
        para("1.<span> </span>That an invented first thing be done. <i>Adopted</i>"),
        para("2.<span> </span>That an invented second thing be affirmed, at greater "
             "length than the others so that it clears the quote floor. "
             "<i>Adopted</i> <i>as amended</i>"),
        para("3.<span> </span>That this invented committee be dismissed. <i>Adopted</i>"),
    ]
)

WHOLE = page(
    heading("I. Introductory Statement"),
    para("An invented first paragraph of the introduction."),
    para("An invented second paragraph of the introduction."),
    heading("IV. Description of the main interpretations", "d"),
    heading("E. A Lettered Subsection Past D", "de"),
    para("An invented paragraph under subsection E."),
    heading("A. The Invented Interpretation", "d1"),
    footnoted("An invented paragraph carrying a footnote marker."),
    heading("B. The Other Invented Interpretation", "d2"),
    heading("1. An invented question?", "d2a"),
    para("An invented answer paragraph."),
    heading("VI. Advice and Counsel of the Committee", "f"),
    para("An invented paragraph of advice."),
    para("Nevertheless, an invented paragraph with <b>bold emphasis</b> inside it, "
         "which is not a heading."),
    heading("Conclusion", "f0"),
    para("An invented paragraph under an unnumbered sub-heading."),
    para("<b>An invented paragraph that is set entirely in bold and runs well past the "
         "length any heading in this document reaches, which makes it body text rather "
         "than a heading however it is styled.</b>"),
    RECOMMENDATIONS,
    # The appendices follow the recommendations, as in the source.
    heading("VII. Appendices", "g"),
    para("An invented appendix paragraph."),
    # Then the endnote apparatus: 173 of these, each in its own `div id="ftnN"`.
    '<hr align="left" size="1" width="33%" />'
    '<div id="ftn1"><p><font size="2"><a href="#_ftnref1" name="_ftn1" id="_ftn1">'
    '<sup><span>[1]</span></sup></a><span>An invented footnote body.</span></font></p></div>',
)


def segments(raw: bytes = WHOLE) -> list:
    return list(ga28.segment(ga28.extract(raw)))


class TestTheCorpusBoundary(unittest.TestCase):
    def test_site_navigation_is_not_the_report(self) -> None:
        self.assertNotIn("HISTORICAL CENTER", " ".join(s.text for s in segments()))

    def test_the_table_of_contents_is_not_the_report(self) -> None:
        self.assertNotIn("2302", " ".join(s.text for s in segments()))

    def test_the_filing_label_above_the_contents_is_not_the_report(self) -> None:
        """The title appears above the contents table as well as below it, and
        starting at the first swallows the label and the whole index."""
        self.assertNotIn("27th General Assembly", " ".join(s.text for s in segments()))

    def test_footnote_markers_do_not_survive(self) -> None:
        self.assertNotIn("[1]", " ".join(s.text for s in segments()))

    def test_footnote_bodies_are_not_the_report(self) -> None:
        """173 endnotes sit after the text, each in a `div id="ftnN"`. Chunked,
        they become paragraphs of a corpus that claims to be the report."""
        self.assertNotIn("An invented footnote body", " ".join(s.text for s in segments()))

    def test_a_bracketed_year_in_a_citation_is_kept(self) -> None:
        """The report cites `Works [1822]`. A blanket rule against bracketed
        numbers would strip the document's own bibliography."""
        page_with_year = WHOLE.replace(
            b"An invented first paragraph of the introduction.",
            b"An invented citation of Works [1822], page 64.",
        )
        self.assertIn("[1822]", " ".join(s.text for s in segments(page_with_year)))


class TestBodyLocators(unittest.TestCase):
    def test_a_paragraph_carries_its_section_path(self) -> None:
        found = [s.locator for s in segments()]
        self.assertIn("GA28 I.1", found)
        self.assertIn("GA28 I.2", found)

    def test_a_lettered_subsection_appears_in_the_path(self) -> None:
        self.assertIn("GA28 IV.A.1", [s.locator for s in segments()])

    def test_a_numbered_sub_subsection_appears_in_the_path(self) -> None:
        self.assertIn("GA28 IV.B.1.1", [s.locator for s in segments()])

    def test_every_body_locator_has_the_documented_form(self) -> None:
        for segment in segments():
            self.assertTrue(
                BODY.match(segment.locator) or REC.match(segment.locator), segment.locator
            )

    def test_paragraph_numbering_restarts_in_each_section(self) -> None:
        found = [s.locator for s in segments()]
        self.assertIn("GA28 VI.1", found)


class TestHeadings(unittest.TestCase):
    def test_inline_emphasis_does_not_make_a_paragraph_a_heading(self) -> None:
        """A heading is a paragraph that is entirely bold. The body is full of
        bold emphasis mid-sentence, and treating those as headings puts chunks
        under locators that do not describe them."""
        found = [s for s in segments() if "bold emphasis" in s.text]
        self.assertEqual(len(found), 1)
        self.assertTrue(BODY.match(found[0].locator), found[0].locator)


class TestUnnumberedHeadings(unittest.TestCase):
    """The document has 36 fully-bold paragraphs that carry no number. Most are
    short sub-headings -- `Conclusion`, `Strengths:` -- and open no path. Some
    are whole paragraphs the source set in bold, and those are text."""

    def test_a_short_unnumbered_heading_opens_no_path(self) -> None:
        found = next(s for s in segments() if "under an unnumbered sub-heading" in s.text)
        self.assertTrue(found.locator.startswith("GA28 VI."), found.locator)

    def test_a_short_unnumbered_heading_is_not_a_chunk(self) -> None:
        self.assertNotIn("Conclusion", [s.text for s in segments()])

    def test_a_long_fully_bold_paragraph_is_text(self) -> None:
        found = [s for s in segments() if "set entirely in bold" in s.text]
        self.assertEqual(len(found), 1)
        self.assertTrue(BODY.match(found[0].locator), found[0].locator)

    def test_lettered_subsections_past_d_are_recognised(self) -> None:
        self.assertIn("GA28 IV.E.1", [s.locator for s in segments()])


class TestTheRecommendations(unittest.TestCase):
    """The ruling. A profile's `ruling_source` resolves here and never to the
    body, which argues views the denomination did not adopt."""

    def test_each_recommendation_is_its_own_chunk(self) -> None:
        found = [s.locator for s in segments() if REC.match(s.locator)]
        self.assertEqual(found, ["GA28 Rec.1", "GA28 Rec.2", "GA28 Rec.3"])

    def test_a_recommendation_is_not_also_a_body_paragraph(self) -> None:
        """It would otherwise be reachable at two locators, and the check that
        a ruling was cited could pass on the wrong one."""
        texts = [s.text for s in segments() if BODY.match(s.locator)]
        self.assertNotIn("That an invented second thing be affirmed", " ".join(texts))

    def test_the_recommendation_number_is_not_repeated_in_the_text(self) -> None:
        second = next(s for s in segments() if s.locator == "GA28 Rec.2")
        self.assertTrue(second.text.startswith("That an invented second"), second.text)

    def test_the_outcome_survives_in_the_text(self) -> None:
        """`Adopted as amended` is what makes it a ruling rather than a proposal."""
        second = next(s for s in segments() if s.locator == "GA28 Rec.2")
        self.assertIn("Adopted", second.text)

    def test_the_expected_number_of_recommendations_is_asserted(self) -> None:
        self.assertEqual(ga28.EXPECTED_RECOMMENDATIONS, 3)
        broken = WHOLE.replace(
            b"<p style=\"x\"><font size=\"2\">3.<span> </span>That this invented "
            b"committee be dismissed. <i>Adopted</i></font></p>", b""
        )
        with self.assertRaises(AcquisitionError):
            segments(broken)


class TestAdapterContract(unittest.TestCase):
    def test_the_corpus_is_local_only(self) -> None:
        """PCA-published (ADR-0017): ingested, and refused at check 4 unless a
        deployer opts in."""
        self.assertEqual(ga28.work.license, "local-only")
        self.assertIn(ga28.work.license, LICENSES)

    def test_the_diagnostic_is_the_ruling(self) -> None:
        self.assertEqual(ga28.diagnostic, "GA28 Rec.2")
        self.assertIn(ga28.diagnostic, [s.locator for s in segments()])

    def test_every_locator_can_be_written_to_a_fingerprints_file(self) -> None:
        for segment in segments():
            stage(segment.locator, segment.text)

    def test_the_adapter_is_registered(self) -> None:
        self.assertIn(ga28.corpus_id, corpora.CORPUS_IDS)
        self.assertIs(corpora.load(ga28.corpus_id), ga28)


if __name__ == "__main__":
    unittest.main()
