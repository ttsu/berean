"""The Python half of the normalisation contract.

Ingestion runs here and verification runs in Go, so there is no shared function
and the specs must not ask for one. What is shared is the contract and the
vectors in `testdata/normalisation/vectors.json`, which this suite and
`services/gateway/internal/normalise` both read.

Drift between the two implementations surfaces as quote-match failures on
visually identical text. That is miserable to diagnose from the symptom, and it
is expensive to fix late: fingerprints are hashes of post-normalisation text, so
an ambiguity found after a corpus is blessed invalidates every fingerprint file.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from catena import normalise

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
VECTORS = REPO_ROOT / "testdata" / "normalisation" / "vectors.json"


def load_fixture() -> dict:
    return json.loads(VECTORS.read_text(encoding="utf-8"))


def code_points(labels: list[str]) -> frozenset[str]:
    """`["U+00A0", ...]` -> the characters themselves."""
    return frozenset(chr(int(label[2:], 16)) for label in labels)


class NormalisationContract(unittest.TestCase):
    """The parts of the contract that are sets rather than behaviour.

    Asserting the sets directly is what catches the failure the contract was
    written to prevent. "Collapse runs of whitespace" is two different functions
    in the two languages -- Python's `\\s` and `str.isspace` match U+001C-U+001F
    and Go's `unicode.IsSpace` does not -- so an implementation that reaches for
    the standard library instead of the named set passes almost every vector.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture()

    def test_version_matches_the_fixture(self) -> None:
        self.assertEqual(
            normalise.NORMALISATION_VERSION,
            self.fixture["normalisation_version"],
            "the implementation and the vectors disagree about which contract "
            "version this is; a bump re-blesses every corpus and must be deliberate",
        )

    def test_format_characters_match_the_fixture(self) -> None:
        self.assertEqual(
            normalise.FORMAT_CHARACTERS_REMOVED,
            code_points(self.fixture["format_characters_removed"]),
        )

    def test_whitespace_matches_the_fixture(self) -> None:
        self.assertEqual(
            normalise.WHITESPACE,
            code_points(self.fixture["whitespace"]),
        )


class Vectors(unittest.TestCase):
    """Every failure message here escapes to ASCII.

    The strings being compared differ by characters that are invisible by
    construction, and Python's repr leaves most of them printable. A report of
    `\u00e1` against `a\u0301` rendered as two identical words is how this
    becomes a day of debugging.
    """

    def test_every_vector(self) -> None:
        fixture = load_fixture()
        self.assertTrue(fixture["vectors"], "the fixture carries no vectors")
        for vector in fixture["vectors"]:
            with self.subTest(vector["name"]):
                got = normalise.normalise(vector["input"])
                self.assertEqual(
                    got,
                    vector["expected"],
                    "normalise({}) = {}, want {}\n  {}".format(
                        ascii(vector["input"]),
                        ascii(got),
                        ascii(vector["expected"]),
                        vector["why"],
                    ),
                )

    def test_normalising_twice_changes_nothing(self) -> None:
        """Chunks are re-normalised on re-ingestion; a second pass must be a no-op.

        Not idempotent means a fingerprint depends on how many times the text
        has been through the pipeline, which is not a property anything records.
        """
        for vector in load_fixture()["vectors"]:
            with self.subTest(vector["name"]):
                once = normalise.normalise(vector["input"])
                twice = normalise.normalise(once)
                self.assertEqual(
                    twice,
                    once,
                    "normalise({}) = {}, want {}".format(
                        ascii(once), ascii(twice), ascii(once)
                    ),
                )


class FixtureCoverage(unittest.TestCase):
    """The fixture is the contract's only executable form, so it has to stay whole.

    A code point added to a set without a vector beside it is a silent hole:
    both implementations would agree about a character neither had been tested
    on.
    """

    def setUp(self) -> None:
        self.fixture = load_fixture()
        self.inputs = "".join(v["input"] for v in self.fixture["vectors"])

    def test_every_whitespace_code_point_appears_in_a_vector(self) -> None:
        for char in sorted(code_points(self.fixture["whitespace"])):
            with self.subTest("U+%04X" % ord(char)):
                self.assertIn(char, self.inputs)

    def test_every_stripped_format_character_appears_in_a_vector(self) -> None:
        for char in sorted(code_points(self.fixture["format_characters_removed"])):
            with self.subTest("U+%04X" % ord(char)):
                self.assertIn(char, self.inputs)


if __name__ == "__main__":
    unittest.main()
