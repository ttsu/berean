"""The OPC page extractor, shared by the three Westminster Standards adapters.

The confession and both catechisms are three documents on one publisher's site,
in one markup shape: a `div.mainBlock` holding the text and nothing else worth
keeping. This suite covers that shape once. What each adapter does with the
lines it gets back — chapters and sections, or questions and answers — is its
own suite's business.

ADR-0014 bars corpus text from fixtures, so every page here is invented text in
the source's layout. Nothing touches the network.
"""

from __future__ import annotations

import unittest

from catena.acquire.corpora import _opc
from catena.acquire.record import AcquisitionError

CORPUS = "invented-corpus"


def page(body: str, *, container: str = "mainBlock") -> bytes:
    """The site's furniture around a body. Only the container is the text."""
    return f"""<html><body>
<div class="header"><p>Navigation that is not the text.</p></div>
<div class="{container}">
<h1>An Invented Title</h1>
{body}
</div>
<div class="opcFooter"><p>&copy; 2026 A footer that is not the text.</p></div>
</body></html>
""".encode("utf-8")


def lines(body: str) -> list[str]:
    return _opc.extract_main_block(page(body), CORPUS).splitlines()


class TestTheCaptureWindow(unittest.TestCase):
    def test_only_the_container_is_extracted(self) -> None:
        found = lines("<p>The invented body.</p>")
        self.assertEqual(found, ["The invented body."])

    def test_the_page_title_is_not_text(self) -> None:
        self.assertNotIn("An Invented Title", lines("<p>The invented body.</p>"))

    def test_a_missing_container_fails_rather_than_yielding_nothing(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            _opc.extract_main_block(page("<p>Body.</p>", container="sideBar"), CORPUS)
        self.assertIn("mainBlock", str(caught.exception))

    def test_a_source_that_is_not_utf8_fails_rather_than_being_guessed_at(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            _opc.extract_main_block(page("<p>Body.</p>").replace(b"Body", b"B\xff\xfedy"), CORPUS)
        self.assertIn("UTF-8", str(caught.exception))


class TestBlockStructure(unittest.TestCase):
    def test_a_line_break_starts_a_new_line(self) -> None:
        """The catechisms depend on this: `Q. …<br />A. …` is one paragraph and
        must reach the segmenter as two lines, so a missing answer is visible."""
        self.assertEqual(
            lines("<p>First half.<br />\nSecond half.</p>"),
            ["First half.", "Second half."],
        )

    def test_inline_markup_is_dropped_and_its_text_kept(self) -> None:
        self.assertEqual(
            lines("<p>A word in <i>italics</i> here.</p>"), ["A word in italics here."]
        )

    def test_an_unclosed_final_paragraph_is_still_emitted(self) -> None:
        """WLC 196's paragraph is never closed — it runs straight into the
        container's `</div>`. Losing it would drop the last chunk."""
        self.assertEqual(
            lines("<p>A closed one.</p>\n<p>An unclosed last one."),
            ["A closed one.", "An unclosed last one."],
        )

    def test_whitespace_inside_a_block_is_collapsed_to_one_line(self) -> None:
        self.assertEqual(
            lines("<p>Spread\n  across   several\n\nlines.</p>"),
            ["Spread across several lines."],
        )


class TestDroppedSubtrees(unittest.TestCase):
    def test_a_table_of_contents_is_not_text(self) -> None:
        body = "<ol><li>An index entry.</li></ol>\n<p>The invented body.</p>"
        self.assertEqual(lines(body), ["The invented body."])

    def test_a_proof_text_apparatus_does_not_survive(self) -> None:
        """Taking the apparatus is what turns a public-domain text into
        someone's copyrighted arrangement of it."""
        self.assertEqual(
            lines("<p>The invented body.<sup>[a] Gen. 1:1</sup></p>"),
            ["The invented body."],
        )

    def test_scripts_and_styles_are_not_text(self) -> None:
        body = "<script>var x = 1;</script><style>p { color: red; }</style><p>The body.</p>"
        self.assertEqual(lines(body), ["The body."])


class TestTablesAreReadDownTheirColumns(unittest.TestCase):
    """WCF 1.2's lists of the canonical books are three-column tables read down
    each column. Read row-major they garble, and no later stage would notice."""

    def test_cells_come_out_in_column_order(self) -> None:
        body = (
            "<table>"
            "<tr><td>First</td><td>Fourth</td></tr>"
            "<tr><td>Second</td><td>Fifth</td></tr>"
            "<tr><td>Third</td><td>Sixth</td></tr>"
            "</table>"
        )
        self.assertEqual(
            lines(body), ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"]
        )


if __name__ == "__main__":
    unittest.main()
