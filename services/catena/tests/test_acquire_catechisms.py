"""The Westminster catechism adapters, tested structurally.

ADR-0014 bars corpus text from fixtures, so this suite asserts the *shape* the
parser produces over invented text laid out the way the OPC lays it out: that a
`Q.`/`A.` paragraph becomes exactly one chunk with a `WLC Q&A n` or `WSC Q&A n`
locator, that an answer is never split from its question, that a multi-line
answer stays whole, and that the Larger Catechism's two division headings are
dropped rather than swallowed into the answer above them.

Those headings are matched structurally — an all-caps line between Q&As — and
not by their text, because hard-coding the strings would commit corpus text to
this repository. The rule holds on the real sources: the two headings are the
only all-caps lines in either document, and every continuation line inside
WLC 99 and WLC 151 carries lowercase.

The question counts are checked rather than assumed, for the reason the
confession's chapter count is: a source carrying a different number of
questions is a different edition, and the divergence is structural where a
diagnostic locator's is textual.

Real acquisition is `make provision-corpus`. Nothing here touches the network.
"""

from __future__ import annotations

import re
import unittest

from catena.acquire import corpora
from catena.acquire.corpora import _catechism
from catena.acquire.corpora import wlc_1788_american as wlc
from catena.acquire.corpora import wsc_1788_american as wsc
from catena.acquire.record import LICENSES, AcquisitionError, stage

CORPUS = "invented-catechism"
PREFIX = "IC"


def answer(number: int) -> str:
    return (
        f"A. Invented answer number {number}, standing in for text this "
        "repository does not carry."
    )


def pair(number: int, *, continuations: tuple[str, ...] = ()) -> list[str]:
    """One Q&A as the extractor hands it over: a `Q.` line then `A.` lines."""
    return [f"Q. {number}. Invented question number {number}?", answer(number)] + list(
        continuations
    )


def document(count: int, *, start: int = 1) -> str:
    lines: list[str] = []
    for number in range(start, start + count):
        lines.extend(pair(number))
    return "\n".join(lines) + "\n"


def segments(document: str, *, questions: int, divisions: int = 0) -> list:
    return list(
        _catechism.segment_qa(
            document,
            corpus_id=CORPUS,
            prefix=PREFIX,
            expected_questions=questions,
            expected_divisions=divisions,
        )
    )


class TestQuestionAndAnswerPairing(unittest.TestCase):
    def test_each_pair_becomes_one_chunk(self) -> None:
        self.assertEqual(len(segments(document(3), questions=3)), 3)

    def test_locator_is_the_prefix_and_the_question_number(self) -> None:
        self.assertEqual(
            [segment.locator for segment in segments(document(3), questions=3)],
            ["IC Q&A 1", "IC Q&A 2", "IC Q&A 3"],
        )

    def test_the_answer_is_never_split_from_its_question(self) -> None:
        first = segments(document(2), questions=2)[0]
        self.assertIn("Invented question number 1?", first.text)
        self.assertIn("Invented answer number 1", first.text)

    def test_the_q_and_a_markers_are_not_carried_into_the_text(self) -> None:
        """Chunk text is what check 2 substring-matches a quote against, so a
        marker sitting between the question and the answer fails any quote that
        spans the boundary. The number is the locator, which is the same reason
        the confession's adapter drops its section number."""
        first = segments(document(1), questions=1)[0]
        self.assertTrue(first.text.startswith("Invented question number 1?"), first.text)
        self.assertNotIn("Q.", first.text)
        self.assertNotIn("A.", first.text)


class TestMultiLineAnswers(unittest.TestCase):
    """WLC 99 lists eight rules and WLC 151 four aggravations, each a `<br>`
    inside the answer. They are one chunk, not nine and five."""

    def test_continuation_lines_stay_in_the_same_chunk(self) -> None:
        lines = pair(1, continuations=("1. First invented rule.", "2. Second invented rule."))
        found = segments("\n".join(lines) + "\n", questions=1)
        self.assertEqual(len(found), 1)
        self.assertIn("First invented rule.", found[0].text)
        self.assertIn("Second invented rule.", found[0].text)


class TestSegmentationFailsLoudly(unittest.TestCase):
    def test_a_question_with_no_answer_fails(self) -> None:
        broken = f"Q. 1. Invented question number 1?\n{answer(1)}\nQ. 2. Invented question 2?\n"
        with self.assertRaises(AcquisitionError) as caught:
            segments(broken, questions=2)
        self.assertIn("never split", str(caught.exception).lower())

    def test_an_answer_before_any_question_fails(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            segments(answer(1) + "\n" + "\n".join(pair(1)) + "\n", questions=1)
        self.assertIn("before any question", str(caught.exception))

    def test_a_second_answer_under_one_question_fails(self) -> None:
        broken = "\n".join(pair(1) + [answer(1)]) + "\n"
        with self.assertRaises(AcquisitionError) as caught:
            segments(broken, questions=1)
        self.assertIn("second answer", str(caught.exception))

    def test_non_contiguous_numbering_fails(self) -> None:
        broken = "\n".join(pair(1) + pair(3)) + "\n"
        with self.assertRaises(AcquisitionError) as caught:
            segments(broken, questions=2)
        self.assertIn("contiguous", str(caught.exception))

    def test_text_before_the_first_question_is_never_dropped_silently(self) -> None:
        """A line after an answer cannot be told from a continuation of it, and
        must not be: WLC 99's eight rules are exactly that. The case this
        catches is prose preceding the first question."""
        broken = "A stray block belonging to nothing.\n" + "\n".join(pair(1)) + "\n"
        with self.assertRaises(AcquisitionError) as caught:
            segments(broken, questions=1)
        self.assertIn("outside any question", str(caught.exception))

    def test_a_short_document_fails_the_expected_question_count(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            segments(document(3), questions=4)
        self.assertIn("expected 4", str(caught.exception))

    def test_a_long_document_fails_the_expected_question_count(self) -> None:
        with self.assertRaises(AcquisitionError):
            segments(document(5), questions=4)


class TestDivisionHeadings(unittest.TestCase):
    """The Larger Catechism's two all-caps headings divide the catechism and
    belong to no Q&A. They are dropped, counted, and the count is asserted."""

    HEADING = "AN INVENTED DIVISION OF THIS CATECHISM"

    def test_a_division_heading_is_not_a_chunk(self) -> None:
        text = "\n".join(pair(1) + [self.HEADING] + pair(2)) + "\n"
        found = segments(text, questions=2, divisions=1)
        self.assertEqual([segment.locator for segment in found], ["IC Q&A 1", "IC Q&A 2"])

    def test_a_division_heading_is_not_swallowed_by_the_answer_above_it(self) -> None:
        text = "\n".join(pair(1) + [self.HEADING] + pair(2)) + "\n"
        self.assertNotIn("INVENTED DIVISION", segments(text, questions=2, divisions=1)[0].text)

    def test_an_unexpected_division_heading_fails(self) -> None:
        text = "\n".join(pair(1) + [self.HEADING] + pair(2)) + "\n"
        with self.assertRaises(AcquisitionError) as caught:
            segments(text, questions=2, divisions=0)
        self.assertIn("division", str(caught.exception))

    def test_a_missing_division_heading_fails(self) -> None:
        with self.assertRaises(AcquisitionError):
            segments(document(2), questions=2, divisions=1)

    def test_a_heading_interrupting_a_pair_fails(self) -> None:
        broken = "\n".join(
            [f"Q. 1. Invented question number 1?", self.HEADING, answer(1)]
        ) + "\n"
        with self.assertRaises(AcquisitionError):
            segments(broken, questions=1, divisions=1)


# --- the adapters, over pages in the source's shape -------------------------


def markup(number: int, *, continuations: tuple[str, ...] = ()) -> str:
    """One Q&A as the OPC lays it out: a single paragraph, `<br />` between."""
    tail = "".join(f"<br />\n{line}" for line in continuations)
    return (
        f"<p>Q. {number}. <i>Invented question number {number}?</i><br />\n"
        f"{answer(number)}{tail}</p>"
    )


def catechism_page(count: int, *, divisions: tuple[int, ...] = ()) -> bytes:
    """A whole catechism, with division headings after the given questions."""
    blocks = []
    for number in range(1, count + 1):
        blocks.append(markup(number))
        if number in divisions:
            blocks.append("<p>AN INVENTED DIVISION OF THIS CATECHISM</p>")
    body = "\n".join(blocks)
    return f"""<html><body>
<div class="header"><p>Navigation that is not the catechism.</p></div>
<div class="mainBlock">
<h1>An Invented Catechism</h1>
{body}
</div>
<div class="opcFooter"><p>&copy; 2026 A footer that is not the catechism.</p></div>
</body></html>
""".encode("utf-8")


class AdapterContract:
    """The assertions both catechisms owe, run against each."""

    adapter: object
    prefix: str
    questions: int
    divisions: int

    def acquire(self, raw: bytes) -> list:
        return list(self.adapter.segment(self.adapter.extract(raw)))

    def whole(self) -> list:
        spread = sorted({self.questions // 3, 2 * self.questions // 3})
        after = tuple(spread)[: self.divisions] if self.divisions else ()
        return self.acquire(catechism_page(self.questions, divisions=after))

    def test_every_question_becomes_one_chunk(self) -> None:
        self.assertEqual(len(self.whole()), self.questions)

    def test_every_locator_has_the_catechism_form(self) -> None:
        pattern = re.compile(rf"^{self.prefix} Q&A (\d+)$")
        for segment in self.whole():
            self.assertRegex(segment.locator, pattern)

    def test_the_edition_diagnostic_is_among_the_locators(self) -> None:
        """A diagnostic that segmentation never produces cannot be blessed and
        cannot be verified, so it is checked here rather than at a terminal."""
        self.assertIn(self.adapter.diagnostic, [s.locator for s in self.whole()])

    def test_every_locator_can_be_written_to_a_fingerprints_file(self) -> None:
        for segment in self.whole():
            stage(segment.locator, segment.text)

    def test_a_page_with_the_wrong_number_of_questions_fails(self) -> None:
        with self.assertRaises(AcquisitionError):
            self.acquire(catechism_page(self.questions - 1))

    def test_the_corpus_id_is_edition_specific(self) -> None:
        self.assertIn("1788", self.adapter.corpus_id)

    def test_the_licence_is_a_closed_enum_value(self) -> None:
        self.assertIn(self.adapter.work.license, LICENSES)

    def test_the_source_is_the_opc_and_the_fallback_is_an_archive(self) -> None:
        plan = self.adapter.fetch_plan()
        self.assertIn("opc.org", plan.source_url)
        self.assertIn("id_/", plan.archive_url)

    def test_the_adapter_is_registered(self) -> None:
        self.assertIn(self.adapter.corpus_id, corpora.CORPUS_IDS)
        self.assertIs(corpora.load(self.adapter.corpus_id), self.adapter)


class TestShorterCatechism(AdapterContract, unittest.TestCase):
    adapter = wsc
    prefix = "WSC"
    questions = 107
    divisions = 0


class TestLargerCatechism(AdapterContract, unittest.TestCase):
    adapter = wlc
    prefix = "WLC"
    questions = 196
    divisions = 2

    def test_the_two_division_headings_are_dropped(self) -> None:
        self.assertNotIn("INVENTED DIVISION", " ".join(s.text for s in self.whole()))

    def test_a_page_with_no_division_headings_fails(self) -> None:
        with self.assertRaises(AcquisitionError):
            self.acquire(catechism_page(self.questions))


if __name__ == "__main__":
    unittest.main()
