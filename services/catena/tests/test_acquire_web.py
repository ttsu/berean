"""The World English Bible, the Phase 1 Scripture corpus.

Scripture is not structurally special in the acquisition contract — chunks are
retrieved, cited and verified exactly like any other corpus, and
`scripture.corpus_id` is appended to the profile's corpora list at a resolved
stance (INTEGRATION-SPEC). What is special is the scale: 31,098 verses, an order
of magnitude past anything else acquired here.

ADR-0014 bars corpus text from fixtures, and a Bible is the sharpest case for
that rule, so every verse below is invented. The book codes are not text — they
are identifiers, in the same category as `WCF` or `Inst.`.

Two source facts decide this adapter:

1. **Five verses are versification placeholders with no text** — LUK 17:36,
   ACT 8:37, ACT 15:34, ACT 24:7 and ROM 16:25 are absent from the Majority Text
   this translation follows, and the source emits the verse marker anyway.
   `record.stage` refuses empty text, so acquiring them aborts. They are skipped
   and counted.
2. **Skipping them leaves gaps in the verse numbering**, so verse contiguity
   cannot be asserted the way chapter numbering is elsewhere. Acts runs 8:36 then
   8:38, and that is correct.
"""

from __future__ import annotations

import io
import re
import unittest
import zipfile

from catena.acquire import corpora
from catena.acquire.corpora import web_2020 as web
from catena.acquire.record import LICENSES, AcquisitionError, stage

LOCATOR = re.compile(r"^(\d )?[A-Za-z]+ (\d+):(\d+)$")


def vpl(*lines: str) -> bytes:
    """A VPL archive in the source's shape: one `BOOK C:V text` line per verse."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(web.MEMBER, "\n".join(lines) + "\n")
        archive.writestr("engwebp_about.htm", "<html>About, which is not text.</html>")
    return buffer.getvalue()


def verse(code: str, chapter: int, number: int, text: str | None = None) -> str:
    body = text if text is not None else f"Invented verse {chapter}:{number} of {code}."
    return f"{code} {chapter}:{number} {body}"


def whole(*, extra: tuple[str, ...] = (), omit: tuple[str, ...] = ()) -> bytes:
    """Every book in canonical order, two verses each, plus the five blanks."""
    lines: list[str] = []
    for code in web.BOOKS:
        for number in (1, 2):
            lines.append(verse(code, 1, number))
    # The diagnostic verse, so the adapter's own locator resolves in the fixture.
    lines.append(verse("DEU", 6, 4))
    lines.extend(f"{ref} " for ref in web.EXPECTED_BLANKS if ref not in omit)
    lines.extend(extra)
    return vpl(*_ordered(lines))


def _ordered(lines: list[str]) -> list[str]:
    """Blank placeholders belong beside their book, as the source has them."""
    order = {code: index for index, code in enumerate(web.BOOKS)}
    def key(line: str) -> tuple:
        code = line.split()[0]
        chapter, _, number = line.split()[1].partition(":")
        return (order.get(code, 999), int(chapter), int(number))
    return sorted(lines, key=key)


def segments(raw: bytes | None = None) -> list:
    return list(web.segment(web.extract(raw if raw is not None else whole())))


class TestTheArchive(unittest.TestCase):
    def test_the_verse_per_line_member_is_read(self) -> None:
        self.assertTrue(segments())

    def test_an_archive_without_the_member_fails(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("something_else.txt", "GEN 1:1 Invented.")
        with self.assertRaises(AcquisitionError) as caught:
            web.extract(buffer.getvalue())
        self.assertIn(web.MEMBER, str(caught.exception))

    def test_bytes_that_are_not_a_zip_fail(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            web.extract(b"not a zip archive at all")
        self.assertIn("zip", str(caught.exception).lower())


class TestLocators(unittest.TestCase):
    def test_a_verse_becomes_a_chunk_named_book_chapter_verse(self) -> None:
        found = [s.locator for s in segments()]
        self.assertIn("Gen 1:1", found)
        self.assertIn("Rev 1:2", found)

    def test_a_numbered_book_keeps_its_number(self) -> None:
        self.assertIn("1 Sam 1:1", [s.locator for s in segments()])

    def test_every_locator_has_the_documented_form(self) -> None:
        for segment in segments():
            self.assertRegex(segment.locator, LOCATOR)

    def test_every_locator_can_be_written_to_a_fingerprints_file(self) -> None:
        for segment in segments():
            stage(segment.locator, segment.text)

    def test_the_verse_reference_is_not_repeated_in_the_text(self) -> None:
        first = next(s for s in segments() if s.locator == "Gen 1:1")
        self.assertFalse(first.text.startswith("GEN"), first.text)

    def test_an_unknown_book_code_fails(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            segments(whole(extra=("ZZZ 1:1 An invented verse of no book.",)))
        self.assertIn("ZZZ", str(caught.exception))


class TestTheBlankVerses(unittest.TestCase):
    """Five verses the Majority Text omits, emitted as markers with no text."""

    def test_a_blank_verse_is_not_a_chunk(self) -> None:
        self.assertNotIn("Acts 8:37", [s.locator for s in segments()])

    def test_the_verse_around_a_blank_still_acquires(self) -> None:
        """Acts runs 8:36 then 8:38, and the gap is correct."""
        found = [s.locator for s in segments(whole(extra=("ACT 8:36 An invented verse.",)))]
        self.assertIn("Acts 8:36", found)

    def test_the_number_of_blanks_is_asserted(self) -> None:
        self.assertEqual(len(web.EXPECTED_BLANKS), 5)
        with self.assertRaises(AcquisitionError) as caught:
            segments(whole(omit=("ACT 8:37",)))
        self.assertIn("blank", str(caught.exception).lower())

    def test_an_unexpected_blank_fails(self) -> None:
        with self.assertRaises(AcquisitionError):
            segments(whole(extra=("GEN 5:1 ",)))


class TestStructuralAssertions(unittest.TestCase):
    def test_the_protestant_canon_is_asserted(self) -> None:
        """66 books — the canon WCF 1.2 lists. The Classic edition carries the
        Deuterocanon as well, and is a different corpus."""
        self.assertEqual(len(web.BOOKS), 66)

    def test_a_missing_book_fails(self) -> None:
        lines = [verse(code, 1, 1) for code in web.BOOKS if code != "OBA"]
        lines.extend(f"{ref} " for ref in web.EXPECTED_BLANKS)
        with self.assertRaises(AcquisitionError) as caught:
            segments(vpl(*_ordered(lines)))
        self.assertIn("66", str(caught.exception))

    def test_books_out_of_canonical_order_fail(self) -> None:
        lines = [verse("EXO", 1, 1), verse("GEN", 1, 1)]
        lines += [verse(c, 1, 1) for c in web.BOOKS if c not in ("GEN", "EXO")]
        lines.extend(f"{ref} " for ref in web.EXPECTED_BLANKS)
        with self.assertRaises(AcquisitionError) as caught:
            segments(vpl(*lines))
        self.assertIn("order", str(caught.exception).lower())


class TestAdapterContract(unittest.TestCase):
    def test_the_new_testament_follows_the_majority_text(self) -> None:
        """The publisher's own statement: edited to conform to the Greek
        Majority Text, referencing Robinson-Pierpont and Hodges-Farstad."""
        self.assertEqual(web.work.text_form, "majority")

    def test_the_licence_is_a_closed_enum_value(self) -> None:
        self.assertEqual(web.work.license, "public-domain")
        self.assertIn(web.work.license, LICENSES)

    def test_the_diagnostic_is_among_the_locators(self) -> None:
        self.assertIn(web.diagnostic, [s.locator for s in segments()])

    def test_the_corpus_id_names_the_edition(self) -> None:
        self.assertEqual(web.corpus_id, "web-2020")

    def test_the_adapter_is_registered(self) -> None:
        self.assertIn(web.corpus_id, corpora.CORPUS_IDS)
        self.assertIs(corpora.load(web.corpus_id), web)


if __name__ == "__main__":
    unittest.main()
