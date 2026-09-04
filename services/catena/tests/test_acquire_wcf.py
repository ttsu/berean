"""The Westminster Confession adapter, tested structurally.

ADR-0014 bars corpus text from fixtures, so this suite asserts the *shape* the
parser produces over invented text laid out the way the source lays it out:
that a chapter heading becomes one line, that a numbered section becomes one
chunk with a `WCF <chapter>.<section>` locator, that the numbering is
contiguous in both dimensions, that the table of contents is not mistaken for
text, that a proof-text apparatus does not survive extraction, and that the
three-column list of canonical books is read down its columns rather than
across its rows.

That last one is not hypothetical. Read row-major, the source's Old Testament
list opens "Genesis, II Chronicles, Daniel" — a fingerprint of garbled text
that would verify clean forever after.

The 33 is checked rather than assumed. The 1903 PCUSA revision added chapters
34 and 35, and a source carrying them is the wrong edition in a way WCF 23.3
does not detect, because the divergence is structural rather than textual.

Real acquisition of the confession is `make provision-corpus`. It is not a unit
test, and nothing here touches the network.
"""

from __future__ import annotations

import re
import unittest

from catena.acquire.corpora import wcf_1788_american as wcf
from catena.acquire.record import LICENSES, AcquisitionError

LOCATOR = re.compile(r"^WCF (\d+)\.(\d+)$")


def chapter_markup(number: int, sections: int) -> str:
    """One chapter, in the source's shape: an `h3` and numbered paragraphs."""
    body = "\n".join(
        f"<p>{n}. Invented sentence number {n} of chapter {number}, standing in for "
        f"text this repository does not carry.</p>"
        for n in range(1, sections + 1)
    )
    return (
        f'<h3><a name="Chapter_{number:02d}"></a>CHAPTER {number}<br />'
        f"<i>Of Invented Matters {number}</i></h3>\n{body}"
    )


def chapters_markup(chapters: int, sections: int) -> str:
    return "\n".join(chapter_markup(n, sections) for n in range(1, chapters + 1))


def page(chapters: int = wcf.EXPECTED_CHAPTERS, *, sections: int = 2, extra: str = "") -> bytes:
    """The page's shape: navigation, a table of contents, then the chapters.

    Only `div.mainBlock` is the confession. Everything before and after it here
    is the kind of furniture the real page carries.
    """
    contents = "\n".join(
        f'<li><a href="#Chapter_{n:02d}">Of Invented Matters {n}</a></li>'
        for n in range(1, chapters + 1)
    )
    return f"""<html><body>
<div class="header"><p>Navigation that is not the confession.</p></div>
<div class="mainBlock">
<h1>Confession of Faith</h1>
<ol type="1">
{contents}
</ol>
{chapters_markup(chapters, sections)}
{extra}
</div>
<div class="opcFooter"><p>A footer that is not the confession.</p></div>
</body></html>
""".encode("utf-8")


def segments(raw: bytes) -> list:
    return list(wcf.segment(wcf.extract(raw)))


class Constants(unittest.TestCase):
    def test_thirty_three_chapters_is_the_pca_confession(self) -> None:
        self.assertEqual(
            wcf.EXPECTED_CHAPTERS,
            33,
            "the PCA's confession ends at chapter 33, 'Of the Last Judgment'. The 1903 "
            "PCUSA revision added 34 and 35, and that divergence is structural rather "
            "than textual, so WCF 23.3 does not catch it",
        )

    def test_the_corpus_id_is_edition_specific(self) -> None:
        self.assertEqual(wcf.corpus_id, "wcf-1788-american")

    def test_the_diagnostic_is_the_civil_magistrate_chapter(self) -> None:
        self.assertEqual(
            wcf.diagnostic,
            "WCF 23.3",
            "chapter 23 is where the 1788 American revision parts from the 1646 "
            "original, and that divergence is the whole of what makes this corpus "
            "distinguishable from wcf-1646-original",
        )

    def test_the_adapter_carries_no_corpus_text(self) -> None:
        with open(wcf.__file__, encoding="utf-8") as handle:
            body = handle.read()
        self.assertNotIn(
            "nursing fathers",
            body,
            "the diagnostic's text lives in the committed manifest, written at bless "
            "from what the human read. One home, and it is the record (ADR-0014)",
        )

    def test_the_work_facts_are_complete_and_closed(self) -> None:
        self.assertIsNone(wcf.work.author, "a confession is a corporate document")
        self.assertEqual(wcf.work.license, "public-domain")
        self.assertIn(wcf.work.license, LICENSES)
        self.assertEqual(wcf.work.text_form, "not-applicable")
        self.assertEqual(wcf.work.language, wcf.work.source_language)
        self.assertIn("1788", wcf.work.edition)

    def test_the_licence_terms_quote_the_source_rather_than_summarise_it(self) -> None:
        self.assertIn("The Orthodox Presbyterian Church", wcf.license_terms)
        self.assertIn(wcf.SOURCE_URL, wcf.license_terms)

    def test_the_fetch_plan_carries_a_source_and_an_archive_fallback(self) -> None:
        plan = wcf.fetch_plan()
        self.assertTrue(plan.source_url.startswith("https://"))
        self.assertTrue(plan.archive_url.startswith("https://"))
        self.assertNotEqual(plan.source_url, plan.archive_url)


class Extraction(unittest.TestCase):
    def test_only_the_confession_container_is_extracted(self) -> None:
        document = wcf.extract(page())
        self.assertNotIn("Navigation that is not the confession", document)
        self.assertNotIn("A footer that is not the confession", document)

    def test_the_table_of_contents_is_not_text(self) -> None:
        document = wcf.extract(page())
        self.assertNotIn(
            "Confession of Faith",
            document,
            "the h1 is the page's title and the ol is an index; neither is the text",
        )
        self.assertEqual(
            document.count("Of Invented Matters 1\n"),
            1,
            "a chapter title appears once, inside its heading line, and not again as "
            "a table-of-contents entry",
        )

    def test_a_chapter_heading_is_one_line(self) -> None:
        first = wcf.extract(page()).splitlines()[0]
        self.assertEqual(
            first,
            "CHAPTER 1 Of Invented Matters 1",
            "the heading is `CHAPTER n<br /><i>Title</i>`, and the br is a line break "
            "everywhere except here",
        )

    def test_a_proof_text_apparatus_does_not_survive(self) -> None:
        marked = page().replace(
            b"<p>1. Invented sentence number 1 of chapter 1,",
            b"<p>1.<sup>proof-text-marker</sup> Invented sentence number 1 of chapter 1,",
        )
        document = wcf.extract(marked)
        self.assertNotIn(
            "proof-text-marker",
            document,
            "a modern edition's selection and arrangement of proof texts can carry a "
            "fresh copyright over public-domain text, so the apparatus is never taken",
        )

    def test_an_unrecognisable_page_fails_loudly(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            wcf.extract(b"<html><body><p>Not the confession.</p></body></html>")
        self.assertIn("mainBlock", str(caught.exception))

    def test_a_table_is_read_down_its_columns(self) -> None:
        table = (
            '<p><b>An invented list:</b></p><center><table class="wcf"><tbody>'
            "<tr><td>alpha</td><td>delta</td></tr>"
            "<tr><td>beta</td><td>epsilon</td></tr>"
            "<tr><td>gamma</td><td>zeta</td></tr>"
            "</tbody></table></center></p>"
        )
        raw = page().replace(
            b'<h3><a name="Chapter_02">',
            table.encode("utf-8") + b'<h3><a name="Chapter_02">',
        )
        chunks = {segment.locator: segment.text for segment in segments(raw)}
        body = " ".join(chunks["WCF 1.2"].split())
        self.assertIn(
            "alpha beta gamma delta epsilon zeta",
            body,
            "the source lays its lists of canonical books out in three columns read "
            "downward; row-major reading interleaves them and splits book names "
            "across cells",
        )
        self.assertIn("An invented list:", body)


class Segmentation(unittest.TestCase):
    def test_one_chunk_per_numbered_section(self) -> None:
        self.assertEqual(len(segments(page(sections=3))), wcf.EXPECTED_CHAPTERS * 3)

    def test_every_locator_has_the_contract_s_shape(self) -> None:
        for segment in segments(page()):
            with self.subTest(segment.locator):
                self.assertRegex(segment.locator, LOCATOR)

    def test_locators_run_contiguously_from_one_in_both_dimensions(self) -> None:
        pairs = [
            tuple(int(part) for part in LOCATOR.match(segment.locator).groups())
            for segment in segments(page(sections=2))
        ]
        self.assertEqual(
            pairs,
            [(chapter, section) for chapter in range(1, 34) for section in (1, 2)],
        )

    def test_the_section_number_is_the_locator_and_not_the_text(self) -> None:
        first = segments(page())[0]
        self.assertTrue(
            first.text.startswith("Invented sentence number 1"),
            "the section number is the locator; repeating it inside the text would "
            "put it into every quote verification too",
        )

    def test_an_unnumbered_block_continues_the_section_above_it(self) -> None:
        raw = page().replace(
            b'<h3><a name="Chapter_02">',
            b"<p>A closing sentence that carries no number of its own.</p>"
            b'<h3><a name="Chapter_02">',
        )
        chunks = {segment.locator: segment.text for segment in segments(raw)}
        self.assertIn("A closing sentence that carries no number of its own.", chunks["WCF 1.2"])

    def test_a_gap_in_the_chapter_numbering_fails(self) -> None:
        full = chapters_markup(33, 2).encode("utf-8")
        without_seven = "\n".join(
            chapter_markup(n, 2) for n in range(1, 34) if n != 7
        ).encode("utf-8")
        raw = page().replace(full, without_seven)
        self.assertNotEqual(raw, page(), "the fixture edit has to actually land")
        with self.assertRaises(AcquisitionError) as caught:
            segments(raw)
        self.assertIn("not contiguous", str(caught.exception))

    def test_a_gap_in_the_section_numbering_fails(self) -> None:
        broken = page().replace(
            b"<p>2. Invented sentence number 2 of chapter 1,",
            b"<p>3. Invented sentence number 3 of chapter 1,",
        )
        with self.assertRaises(AcquisitionError) as caught:
            segments(broken)
        self.assertIn("not contiguous", str(caught.exception))

    def test_thirty_four_chapters_is_the_wrong_edition(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            segments(page(chapters=34))
        self.assertIn("1903", str(caught.exception))

    def test_thirty_two_chapters_fails_too(self) -> None:
        with self.assertRaises(AcquisitionError):
            segments(page(chapters=32))

    def test_text_outside_any_section_is_never_dropped_silently(self) -> None:
        raw = page().replace(
            b'<h3><a name="Chapter_01"></a>',
            b"<p>A stray block with no section number.</p>"
            b'<h3><a name="Chapter_01"></a>',
        )
        with self.assertRaises(AcquisitionError) as caught:
            segments(raw)
        self.assertIn("outside any numbered section", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
