"""Ingestion against a live Postgres. Needs `make dev`; run by `make test-ingest-db`.

Not under `tests/test_*.py`, so `make test-catena` -- which runs with nothing
started and no network -- does not collect it. Same split as `make test-schema`.

The unit suite covers the plan and the apply sequencing against a fake store,
and a fake cannot model the one thing that matters here: whether psycopg
actually *commits*. A store whose writes are visible to its own session and to
nobody else passes every in-process assertion ever written about it, so
durability has to be asserted from a second connection.

Invented text and invented corpus IDs throughout (ADR-0014).
"""

from __future__ import annotations

import os
import sys
import unittest

import psycopg

from catena.acquire.record import WorkFacts, stage
from catena.ingest import apply as applying
from catena.ingest import plan as planning
from catena.ingest import postgres
from catena.ingest.source import StagedCorpus

DSN = os.environ.get("CATENA_DATABASE_URL")

CORPUS_ID = "probe-1899-invented"

WORK = WorkFacts(
    work="An Invented Probe",
    author=None,
    era="never",
    language="en",
    source_language="en",
    text_form="not-applicable",
    edition="the only one",
    license="public-domain",
    attribution="Invented for the ingestion integration suite. Not a real work.",
)


class FixedEmbedder:
    """Deterministic vectors of the real width, without loading 2.3 GB."""

    name = "probe-embedder"
    dim = 1024
    max_tokens = 8192

    def count_tokens(self, texts):
        return [len(text.split()) for text in texts]

    def embed(self, texts):
        return [[(len(text) % 97) / 100.0] * self.dim for text in texts]


def corpus(texts: dict[str, str]) -> StagedCorpus:
    return StagedCorpus(
        corpus_id=CORPUS_ID,
        work=WORK,
        normalisation_version=1,
        records=[stage(locator, text) for locator, text in texts.items()],
    )


@unittest.skipIf(not DSN, "CATENA_DATABASE_URL unset; needs `make dev`")
class LivePostgresTest(unittest.TestCase):
    def setUp(self):
        self.store = postgres.connect(DSN)
        self.embedder = FixedEmbedder()
        self._wipe()
        # LIFO, so the store's connection is closed before the wipe runs. A
        # connection left holding an uncommitted transaction holds locks on the
        # rows the wipe deletes, and without this the suite's own teardown
        # blocks on the very defect it exists to catch.
        self.addCleanup(self._wipe)
        self.addCleanup(self.store.close)

    def _wipe(self):
        with psycopg.connect(DSN, autocommit=True) as connection, connection.cursor() as cursor:
            # Fail fast rather than block: an uncommitted writer elsewhere is a
            # result this suite wants reported, not waited on.
            cursor.execute("SET lock_timeout = '10s'")
            cursor.execute("DELETE FROM corpus.works WHERE corpus_id = %s", (CORPUS_ID,))

    def _run(self, staged):
        """Plan then apply, in the CLI's order — the read comes first."""
        existing = self.store.existing_chunks(staged.corpus_id, self.embedder.name)
        plan = planning.diff(
            staged.corpus_id, staged.records, existing,
            normalisation_version=staged.normalisation_version,
        )
        applying.apply(staged, plan, self.store, self.embedder, budget=4096)
        return plan

    def _count(self, sql, *args):
        """Counted from a SEPARATE connection, so only committed rows are seen."""
        with psycopg.connect(DSN) as connection, connection.cursor() as cursor:
            cursor.execute(sql, args)
            return cursor.fetchone()[0]

    def test_applied_rows_are_durable_to_another_connection(self):
        self._run(corpus({"P 1.1": "The first invented probe line.",
                          "P 1.2": "The second invented probe line."}))

        self.assertEqual(
            self._count("SELECT count(*) FROM corpus.chunks WHERE corpus_id=%s", CORPUS_ID), 2)
        self.assertEqual(
            self._count("SELECT count(*) FROM corpus.works WHERE corpus_id=%s", CORPUS_ID), 1)
        self.assertEqual(
            self._count("""SELECT count(*) FROM corpus.chunk_embeddings e
                             JOIN corpus.chunks c ON c.id = e.chunk_id
                            WHERE c.corpus_id=%s""", CORPUS_ID), 2)

    def test_the_connection_is_left_idle_rather_than_holding_a_transaction(self):
        # A connection still INTRANS after apply is one whose work the server
        # will roll back, and it is the shape the in-process assertions cannot
        # see: the rows are visible to this session and to nobody else.
        self._run(corpus({"P 1.1": "The first invented probe line."}))

        self.assertEqual(
            self.store._connection.info.transaction_status,
            psycopg.pq.TransactionStatus.IDLE,
        )

    def test_a_second_run_converges_to_nothing(self):
        staged = corpus({"P 1.1": "The first invented probe line.",
                         "P 1.2": "The second invented probe line."})
        self._run(staged)

        plan = self._run(staged)

        self.assertTrue(plan.converged, plan.lines())
        self.assertEqual(plan.embedding_backlog, 0)

    def test_an_update_drops_and_re_creates_its_vector(self):
        self._run(corpus({"P 1.1": "The first invented probe line."}))
        before = self._count(
            """SELECT count(*) FROM corpus.chunk_embeddings e
                 JOIN corpus.chunks c ON c.id = e.chunk_id WHERE c.corpus_id=%s""", CORPUS_ID)

        self._run(corpus({"P 1.1": "The first invented probe line, corrected and longer."}))

        self.assertEqual(before, 1)
        self.assertEqual(
            self._count("""SELECT count(*) FROM corpus.chunk_embeddings e
                             JOIN corpus.chunks c ON c.id = e.chunk_id
                            WHERE c.corpus_id=%s""", CORPUS_ID), 1)
        self.assertEqual(
            self._count("""SELECT count(*) FROM corpus.chunk_metadata
                            WHERE corpus_id=%s""", CORPUS_ID), 1)

    def test_a_delete_cascades_to_the_vector(self):
        self._run(corpus({"P 1.1": "The first invented probe line.",
                          "P 1.2": "The second invented probe line."}))

        self._run(corpus({"P 1.1": "The first invented probe line."}))

        self.assertEqual(
            self._count("SELECT count(*) FROM corpus.chunks WHERE corpus_id=%s", CORPUS_ID), 1)
        self.assertEqual(
            self._count("""SELECT count(*) FROM corpus.chunk_embeddings e
                             JOIN corpus.chunks c ON c.id = e.chunk_id
                            WHERE c.corpus_id=%s""", CORPUS_ID), 1)


if __name__ == "__main__":
    if not DSN:
        print("CATENA_DATABASE_URL unset; needs `make dev`", file=sys.stderr)
    unittest.main()
