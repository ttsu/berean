"""The ingestion plan — the three-way diff, and the refusals that precede it.

The plan is a pure function from staged records and database state to a list of
actions, which is what lets this suite cover every interesting decision with no
database, no model, and no fixtures beyond a few invented records.

Invented text and invented corpus IDs throughout (ADR-0014).
"""

from __future__ import annotations

import unittest

from catena.acquire.record import StagedRecord, fingerprint, stage
from catena.ingest import IngestionError
from catena.ingest import plan as planning
from fakes import FakeEmbedder

CORPUS_ID = "foo-1899-invented"


def record(locator: str, text: str):
    return stage(locator, text)


def existing(chunk_id: int, text: str, *, version: int = 1, embedded: bool = True):
    return planning.ExistingChunk(
        id=chunk_id,
        content_hash=record("x", text).content_hash,
        normalisation_version=version,
        has_embedding=embedded,
    )


class DiffTest(unittest.TestCase):
    """in staging / in database → insert, update, skip, delete."""

    def test_a_locator_the_database_does_not_have_is_an_insert(self):
        staged = [record("FOO 1.1", "The invented text.")]

        result = planning.diff(CORPUS_ID, staged, {})

        self.assertEqual([r.locator for r in result.inserts], ["FOO 1.1"])
        self.assertEqual(result.updates, [])
        self.assertEqual(result.deletes, [])

    def test_the_same_locator_saying_the_same_thing_is_a_skip(self):
        staged = [record("FOO 1.1", "The invented text.")]
        rows = {"FOO 1.1": existing(1, "The invented text.")}

        result = planning.diff(CORPUS_ID, staged, rows)

        self.assertEqual(result.inserts, [])
        self.assertEqual(result.updates, [])
        self.assertEqual(result.deletes, [])
        self.assertEqual(result.unchanged, ["FOO 1.1"])

    def test_the_same_locator_saying_something_else_is_an_update(self):
        staged = [record("FOO 1.1", "The invented text, corrected.")]
        rows = {"FOO 1.1": existing(1, "The invented text.")}

        result = planning.diff(CORPUS_ID, staged, rows)

        self.assertEqual([r.locator for r in result.updates], ["FOO 1.1"])
        self.assertEqual(result.inserts, [])
        self.assertEqual(result.deletes, [])

    def test_a_row_whose_locator_staging_no_longer_has_is_a_delete(self):
        rows = {"FOO 1.1": existing(1, "The invented text.")}

        result = planning.diff(CORPUS_ID, [], rows)

        self.assertEqual(result.deletes, ["FOO 1.1"])
        self.assertEqual(result.inserts, [])
        self.assertEqual(result.updates, [])


class BacklogTest(unittest.TestCase):
    """The embedding backlog is what makes an interrupted run visible."""

    def test_an_unchanged_chunk_with_no_embedding_is_still_backlog(self):
        staged = [record("FOO 1.1", "The invented text.")]
        rows = {"FOO 1.1": existing(1, "The invented text.", embedded=False)}

        result = planning.diff(CORPUS_ID, staged, rows)

        self.assertEqual(result.unchanged, ["FOO 1.1"])
        self.assertEqual(result.embedding_backlog, 1)

    def test_a_fully_converged_corpus_has_nothing_to_do(self):
        staged = [record("FOO 1.1", "The invented text.")]
        rows = {"FOO 1.1": existing(1, "The invented text.", embedded=True)}

        result = planning.diff(CORPUS_ID, staged, rows)

        self.assertEqual(result.embedding_backlog, 0)
        self.assertTrue(result.converged)

    def test_inserts_and_updates_both_need_embedding(self):
        staged = [
            record("FOO 1.1", "The invented text, corrected."),
            record("FOO 1.2", "A second invented saying."),
        ]
        rows = {"FOO 1.1": existing(1, "The invented text.", embedded=True)}

        result = planning.diff(CORPUS_ID, staged, rows)

        # One update, one insert: an update returns its chunk to the backlog
        # because the vector it had describes text the chunk no longer carries.
        self.assertEqual(result.embedding_backlog, 2)
        self.assertFalse(result.converged)


class NormalisationChangeTest(unittest.TestCase):
    """A contract change is a lookup, not an investigation."""

    def test_a_contract_change_is_named_rather_than_left_as_noise(self):
        staged = [record("FOO 1.1", "The invented text."), record("FOO 1.2", "A second one.")]
        rows = {
            # Same locators, hashed under a contract this code no longer
            # implements, so every hash differs.
            "FOO 1.1": existing(1, "The invented text .", version=1),
            "FOO 1.2": existing(2, "A second one .", version=1),
        }

        result = planning.diff(CORPUS_ID, staged, rows, normalisation_version=2)

        self.assertEqual(result.normalisation_change, (1, 2))
        # The behaviour is identical; only the report differs.
        self.assertEqual(len(result.updates), 2)

    def test_ordinary_drift_under_one_contract_is_not_a_contract_change(self):
        staged = [record("FOO 1.1", "The invented text, corrected.")]
        rows = {"FOO 1.1": existing(1, "The invented text.", version=1)}

        result = planning.diff(CORPUS_ID, staged, rows, normalisation_version=1)

        self.assertIsNone(result.normalisation_change)
        self.assertEqual(len(result.updates), 1)

    def test_the_report_collapses_a_contract_change_to_one_line(self):
        staged = [record(f"FOO 1.{n}", f"Invented saying number {n}.") for n in range(50)]
        rows = {
            r.locator: existing(n, f"Invented saying number {n} .", version=1)
            for n, r in enumerate(staged)
        }

        result = planning.diff(CORPUS_ID, staged, rows, normalisation_version=2)
        report = result.lines()

        collapsed = [line for line in report if "normalisation contract" in line]
        self.assertEqual(len(collapsed), 1)
        self.assertIn("v1", collapsed[0])
        self.assertIn("v2", collapsed[0])
        self.assertIn("50", collapsed[0])
        # No locator is enumerated: 50 lines of noise is what this replaces.
        self.assertFalse([line for line in report if "FOO 1." in line])


class OverLimitRefusalTest(unittest.TestCase):
    """A chunk the model cannot read whole is refused, not warned about.

    BGE-M3 truncates silently at `max_seq_length` and returns a vector. The
    chunk is then retrieved on its opening fraction and quoted from its whole
    text, and verification passes, because check 2 matches against
    `corpus.chunks.text` rather than against the vector.

    Exercised against an invented over-long record rather than against a corpus:
    all eight now pass this check, and a refusal nobody has seen fire is a
    refusal nobody has seen work.
    """

    def test_a_chunk_over_the_window_refuses_the_corpus(self):
        embedder = FakeEmbedder(max_tokens=10)
        staged = [
            record("FOO 1.1", "Short enough."),
            record("FOO 1.2", " ".join(f"word{n}" for n in range(11))),
        ]

        with self.assertRaises(IngestionError) as caught:
            planning.check_token_limit(CORPUS_ID, staged, embedder)

        message = str(caught.exception)
        self.assertIn("FOO 1.2", message)
        self.assertIn("11", message)
        self.assertIn("10", message)

    def test_a_chunk_exactly_at_the_window_is_allowed(self):
        embedder = FakeEmbedder(max_tokens=10)
        staged = [record("FOO 1.1", " ".join(f"word{n}" for n in range(10)))]

        planning.check_token_limit(CORPUS_ID, staged, embedder)

    def test_the_refusal_names_every_offender_not_just_the_first(self):
        embedder = FakeEmbedder(max_tokens=3)
        staged = [
            record("FOO 1.1", "one two three four"),
            record("FOO 1.2", "one two"),
            record("FOO 1.3", "one two three four five"),
        ]

        with self.assertRaises(IngestionError) as caught:
            planning.check_token_limit(CORPUS_ID, staged, embedder)

        message = str(caught.exception)
        self.assertIn("FOO 1.1", message)
        self.assertIn("FOO 1.3", message)
        self.assertNotIn("FOO 1.2", message)

    def test_the_refusal_never_prints_the_text_it_measured(self):
        embedder = FakeEmbedder(max_tokens=2)
        staged = [record("FOO 1.1", "a distinctive invented phrase here")]

        with self.assertRaises(IngestionError) as caught:
            planning.check_token_limit(CORPUS_ID, staged, embedder)

        # ADR-0014: a diagnostic that quoted the offending chunk would put
        # corpus text into CI logs and terminal scrollback.
        self.assertNotIn("distinctive", str(caught.exception))


class ReVerificationTest(unittest.TestCase):
    """Every run re-hashes staging and diffs it against the committed file.

    Under a second across all 8.2 MB, so it runs on every invocation rather
    than only on insert. A check this cheap has no reason to be conditional,
    and a conditional check is one whose skipped path is untested.
    """

    def test_staging_that_matches_the_committed_fingerprints_passes(self):
        staged = [record("FOO 1.1", "The invented text.")]
        committed = {"FOO 1.1": fingerprint("The invented text.")}

        planning.check_fingerprints(CORPUS_ID, staged, committed)

    def test_the_carried_hash_is_not_trusted(self):
        # The record claims a hash its own text does not produce. Trusting the
        # carried value would make the whole check a comparison of a number
        # against itself.
        staged = [StagedRecord("FOO 1.1", "The invented text.", "0" * 64)]
        committed = {"FOO 1.1": fingerprint("The invented text.")}

        planning.check_fingerprints(CORPUS_ID, staged, committed)

    def test_text_that_no_longer_hashes_to_its_fingerprint_refuses(self):
        staged = [StagedRecord("FOO 1.1", "The invented text, tampered.",
                               fingerprint("The invented text."))]
        committed = {"FOO 1.1": fingerprint("The invented text.")}

        with self.assertRaises(IngestionError) as caught:
            planning.check_fingerprints(CORPUS_ID, staged, committed)

        self.assertIn("FOO 1.1", str(caught.exception))

    def test_a_locator_the_fingerprints_file_does_not_have_refuses(self):
        staged = [record("FOO 1.1", "The invented text."),
                  record("FOO 9.9", "An unblessed addition.")]
        committed = {"FOO 1.1": fingerprint("The invented text.")}

        with self.assertRaises(IngestionError) as caught:
            planning.check_fingerprints(CORPUS_ID, staged, committed)

        self.assertIn("FOO 9.9", str(caught.exception))

    def test_a_blessed_locator_missing_from_staging_refuses(self):
        # Left to the diff this would become a *delete* of a blessed chunk —
        # the BCO's truncated bless, executed against the database.
        staged = [record("FOO 1.1", "The invented text.")]
        committed = {
            "FOO 1.1": fingerprint("The invented text."),
            "FOO 1.2": fingerprint("A second invented saying."),
        }

        with self.assertRaises(IngestionError) as caught:
            planning.check_fingerprints(CORPUS_ID, staged, committed)

        self.assertIn("FOO 1.2", str(caught.exception))

    def test_the_refusal_never_prints_the_text_it_hashed(self):
        staged = [StagedRecord("FOO 1.1", "a distinctive invented phrase", "0" * 64)]
        committed = {"FOO 1.1": fingerprint("something else entirely")}

        with self.assertRaises(IngestionError) as caught:
            planning.check_fingerprints(CORPUS_ID, staged, committed)

        self.assertNotIn("distinctive", str(caught.exception))


class UnblessedRefusalTest(unittest.TestCase):
    """Staging is allowed to hold work in progress; the database is not."""

    def test_a_corpus_that_was_never_blessed_refuses(self):
        staged = [record("FOO 1.1", "The invented text.")]

        with self.assertRaises(IngestionError) as caught:
            planning.check_fingerprints(CORPUS_ID, staged, None)

        self.assertIn("blessed", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
