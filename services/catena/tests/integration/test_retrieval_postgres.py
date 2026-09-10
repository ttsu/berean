"""Retrieval against a live Postgres. Needs `make dev`; run by `make test-catena-db`.

Not under `tests/test_*.py`, so `make test-catena` -- which runs with nothing
started and no network -- does not collect it. Same split as `make test-schema`
and `make test-ingest-db`.

The unit suite covers selection against a fake reader, and a fake cannot model
what is actually at risk here: that the SQL is right. Three things in
particular have no in-process equivalent -- the `extensions.vector` cast, the
`embedding_model` predicate against a table deliberately holding a row per
model, and whether a filtered HNSW scan returns as many rows as it was asked
for. That last one is the reason `hnsw.iterative_scan` is set at all, and it is
invisible to anything but a real index.

Invented text and invented corpus IDs throughout (ADR-0014).
"""

from __future__ import annotations

import os
import sys
import unittest

import psycopg

from catena.serve import postgres
from catena.vectors import literal as vector_literal

DSN = os.environ.get("CATENA_DATABASE_URL")

ALPHA = "probe-1899-alpha"
BETA = "probe-1899-beta"
DIM = 1024
MODEL = "probe-embedder"
OTHER_MODEL = "probe-embedder-mk2"

#: Invented, and deliberately longer than the 40-character floor so a quote cut
#: from it would be a legitimate citation if any of this were real.
TEXTS = {
    "AAA 1.1": "The council of Vethmoor declared that every mariner shall keep the third watch.",
    "AAA 1.2": "No cooper of the harbour district shall be pressed into the night rotation.",
    "AAA 1.3": "The harbourmaster keeps the tide register and answers to the council alone.",
}
BETA_TEXTS = {
    "BBB 1.1": "The free companies of Ostrel keep no watch and answer to no council.",
}


def unit(index: int) -> list[float]:
    """A basis vector, so cosine similarity is exactly predictable."""
    vector = [0.0] * DIM
    vector[index] = 1.0
    return vector


#: Chosen so ordering is unambiguous: the query is nearest AAA 1.1, then 1.2, then 1.3.
VECTORS = {"AAA 1.1": unit(0), "AAA 1.2": unit(1), "AAA 1.3": unit(2), "BBB 1.1": unit(3)}
QUERY = unit(0)


def tilted(primary: int, secondary: int, weight: float) -> list[float]:
    vector = [0.0] * DIM
    vector[primary] = 1.0
    vector[secondary] = weight
    return vector


class RetrievalSQL(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.connection = psycopg.connect(DSN, autocommit=True)
        _teardown(cls.connection)
        _seed(cls.connection)
        cls.reader = postgres.CorpusReader(psycopg.connect(DSN, autocommit=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.reader.close()
        _teardown(cls.connection)
        cls.connection.close()

    def test_returns_nearest_first(self) -> None:
        hits = self.reader.search(QUERY, [ALPHA], 3, MODEL)
        self.assertEqual([h.locator for h in hits], ["AAA 1.1", "AAA 1.2", "AAA 1.3"])

    def test_score_is_cosine_similarity(self) -> None:
        """1 - distance, so a nearer chunk scores higher. The trace records it."""
        hits = self.reader.search(QUERY, [ALPHA], 1, MODEL)
        self.assertAlmostEqual(hits[0].score, 1.0, places=5)

    def test_carries_the_text_and_the_work(self) -> None:
        hits = self.reader.search(QUERY, [ALPHA], 1, MODEL)
        self.assertEqual(hits[0].text, TEXTS["AAA 1.1"])
        self.assertEqual(hits[0].work, "An Invented Probe")

    def test_filters_to_the_corpora_asked_for(self) -> None:
        hits = self.reader.search(QUERY, [ALPHA], 10, MODEL)
        self.assertNotIn(BETA, {h.corpus_id for h in hits})

    def test_a_second_corpus_is_included_when_asked_for(self) -> None:
        hits = self.reader.search(QUERY, [ALPHA, BETA], 10, MODEL)
        self.assertIn(BETA, {h.corpus_id for h in hits})

    def test_constrains_the_embedding_model(self) -> None:
        """The table holds a row per model so a re-index writes beside the old vectors.

        Without the predicate the single HNSW index spans two vector spaces and
        the same chunk comes back twice, at two different scores.
        """
        hits = self.reader.search(QUERY, [ALPHA], 10, MODEL)
        self.assertEqual(len(hits), len(TEXTS))
        self.assertEqual(len({h.chunk_id for h in hits}), len(TEXTS))

    def test_a_filtered_scan_still_returns_the_full_limit(self) -> None:
        """The reason `hnsw.iterative_scan` is set, and it is invisible to a fake.

        HNSW post-filters. With the default `off`, a scan that finds `ef_search`
        candidates mostly failing the corpus filter returns short — and `top_k`
        would quietly mean "up to top_k, depending which corpora you asked for".
        """
        hits = self.reader.search(QUERY, [BETA], 1, MODEL)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].corpus_id, BETA)

    def test_limit_is_respected(self) -> None:
        self.assertEqual(len(self.reader.search(QUERY, [ALPHA], 2, MODEL)), 2)

    def test_no_corpora_returns_nothing_without_touching_the_database(self) -> None:
        self.assertEqual(self.reader.search(QUERY, [], 10, MODEL), [])


class LocatorLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.connection = psycopg.connect(DSN, autocommit=True)
        _teardown(cls.connection)
        _seed(cls.connection)
        cls.reader = postgres.CorpusReader(psycopg.connect(DSN, autocommit=True))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.reader.close()
        _teardown(cls.connection)
        cls.connection.close()

    def test_resolves_a_citation_reference_to_one_chunk(self) -> None:
        hit = self.reader.by_locator(ALPHA, "AAA 1.2", QUERY, MODEL)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.text, TEXTS["AAA 1.2"])

    def test_carries_the_real_similarity_to_the_query(self) -> None:
        """A pinned ruling enters the trace with this score; a fabricated one would lie."""
        hit = self.reader.by_locator(ALPHA, "AAA 1.2", QUERY, MODEL)
        self.assertAlmostEqual(hit.score, 0.0, places=5)

    def test_a_locator_in_another_corpus_does_not_match(self) -> None:
        """`WCF 7.2` exists in both the 1788 and 1646 editions and they differ."""
        self.assertIsNone(self.reader.by_locator(BETA, "AAA 1.1", QUERY, MODEL))

    def test_an_unknown_locator_is_none_rather_than_an_error(self) -> None:
        """An un-ingested ruling is dropped; Go's profile load is what refuses it honestly."""
        self.assertIsNone(self.reader.by_locator(ALPHA, "AAA 9.9", QUERY, MODEL))

    def test_a_chunk_with_no_vector_for_this_model_does_not_resolve(self) -> None:
        """The metadata contract is incomplete without one — a half-finished ingestion."""
        self.assertIsNone(self.reader.by_locator(ALPHA, "AAA 1.1", QUERY, OTHER_MODEL))


def _seed(connection) -> None:
    with connection.cursor() as cursor:
        for corpus_id, texts in ((ALPHA, TEXTS), (BETA, BETA_TEXTS)):
            cursor.execute(
                """
                INSERT INTO corpus.works (corpus_id, work, author, era, language,
                    source_language, text_form, edition, license, attribution)
                VALUES (%s, 'An Invented Probe', NULL, 'never', 'en', 'en',
                    'not-applicable', 'the only one', 'public-domain',
                    'Invented for the retrieval integration suite. Not a real work.')
                """,
                (corpus_id,),
            )
            for locator, text in texts.items():
                cursor.execute(
                    """
                    INSERT INTO corpus.chunks
                        (corpus_id, locator, text, content_hash, normalisation_version)
                    VALUES (%s, %s, %s, encode(sha256(%s::bytea), 'hex'), 1)
                    RETURNING id
                    """,
                    (corpus_id, locator, text, text),
                )
                chunk_id = cursor.fetchone()[0]
                cursor.execute(
                    """
                    INSERT INTO corpus.chunk_embeddings (chunk_id, embedding_model, dim, embedding)
                    VALUES (%s, %s, %s, %s::extensions.vector)
                    """,
                    (chunk_id, MODEL, DIM, vector_literal(VECTORS[locator])),
                )


def _teardown(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM corpus.works WHERE corpus_id = ANY(%s)", ([ALPHA, BETA],))


if __name__ == "__main__":
    if not DSN:
        print("CATENA_DATABASE_URL is unset; run this through `make test-catena-db`",
              file=sys.stderr)
        raise SystemExit(69)
    unittest.main()
