"""Applying a plan: the crash boundary, and the trap an update sets.

Two phases. Phase one makes the text durable in a single transaction per
corpus; phase two embeds the backlog in batches, one transaction per batch.
Once phase one commits, the database holds complete, correct, blessed text
whether or not phase two ever runs.

Invented text and invented corpus IDs throughout (ADR-0014). The embedder and
the store are both fakes, which is what lets the resumability claim be covered
by a unit test rather than by a multi-hour manual exercise nobody repeats.
"""

from __future__ import annotations

import unittest

from catena.acquire.record import WorkFacts, stage
from catena.ingest import apply as applying
from catena.ingest import plan as planning
from fakes import FakeEmbedder, FakeStore

CORPUS_ID = "foo-1899-invented"

WORK = WorkFacts(
    work="An Invented Corpus",
    author=None,
    era="never",
    language="en",
    source_language="en",
    text_form="not-applicable",
    edition="the only one",
    license="public-domain",
    attribution="Invented for the ingestion suite. Not a real work.",
)


def corpus(texts: dict[str, str], *, version: int = 1):
    from catena.ingest.source import StagedCorpus

    return StagedCorpus(
        corpus_id=CORPUS_ID,
        work=WORK,
        normalisation_version=version,
        records=[stage(locator, text) for locator, text in texts.items()],
    )


def run(staged, store, embedder, **kwargs):
    """Plan and apply, the way the CLI does — the diff has one implementation."""
    existing = store.existing_chunks(staged.corpus_id, embedder.name)
    plan = planning.diff(
        staged.corpus_id,
        staged.records,
        existing,
        normalisation_version=staged.normalisation_version,
    )
    applying.apply(staged, plan, store, embedder, **kwargs)
    return plan


class PhaseOneTest(unittest.TestCase):
    def test_text_is_durable_before_any_vector_exists(self):
        staged = corpus({"FOO 1.1": "The invented text."})
        store, embedder = FakeStore(), FakeEmbedder()
        embedder.die_after = 0

        with self.assertRaises(KeyboardInterrupt):
            run(staged, store, embedder)

        # Phase one committed; phase two did not. The text is whole.
        self.assertEqual(len(store.chunks), 1)
        self.assertEqual(store.works[CORPUS_ID], WORK)
        self.assertEqual(store.embeddings, [])

    def test_the_work_row_carries_the_facts_staging_declared(self):
        staged = corpus({"FOO 1.1": "The invented text."})
        store, embedder = FakeStore(), FakeEmbedder()

        run(staged, store, embedder)

        self.assertEqual(store.works[CORPUS_ID], WORK)

    def test_a_delete_removes_the_chunk_and_its_vector(self):
        store, embedder = FakeStore(), FakeEmbedder()
        run(corpus({"FOO 1.1": "The invented text.", "FOO 1.2": "A second."}), store, embedder)

        run(corpus({"FOO 1.1": "The invented text."}), store, embedder)

        self.assertEqual([r["locator"] for r in store.chunks.values()], ["FOO 1.1"])
        self.assertEqual(len(store.embeddings), 1)


class ResumabilityTest(unittest.TestCase):
    """The test that proves the design.

    Apply, kill mid-embed, re-apply. Nothing recorded that a run had previously
    reached this corpus, because nothing needed to.
    """

    def test_a_run_killed_mid_embed_resumes_and_converges(self):
        staged = corpus({f"FOO 1.{n}": f"Invented saying number {n}." for n in range(20)})
        store = FakeStore()
        killed = FakeEmbedder()
        killed.die_after = 7

        with self.assertRaises(KeyboardInterrupt):
            run(staged, store, killed, budget=16)

        # Some vectors survived, in whole batches. The rest are simply absent.
        self.assertGreater(len(store.embeddings), 0)
        self.assertLess(len(store.embeddings), 20)
        done = len(store.embeddings)

        # Re-run. No cleanup step, no checkpoint to reconcile.
        resumed = FakeEmbedder()
        plan = run(staged, store, resumed, budget=16)

        self.assertEqual(plan.writes, 0, "nothing to insert, update or delete")
        self.assertEqual(plan.embedding_backlog, 20 - done)
        self.assertEqual(len(store.embeddings), 20)

    def test_no_chunk_gains_a_duplicate_embedding_row(self):
        staged = corpus({f"FOO 1.{n}": f"Invented saying number {n}." for n in range(20)})
        store = FakeStore()
        killed = FakeEmbedder()
        killed.die_after = 7

        with self.assertRaises(KeyboardInterrupt):
            run(staged, store, killed, budget=16)
        run(staged, store, FakeEmbedder(), budget=16)

        keys = [(r["chunk_id"], r["embedding_model"]) for r in store.embeddings]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_converged_corpus_re_runs_to_nothing(self):
        staged = corpus({"FOO 1.1": "The invented text."})
        store, embedder = FakeStore(), FakeEmbedder()
        run(staged, store, embedder)

        second = FakeEmbedder()
        plan = run(staged, store, second)

        self.assertTrue(plan.converged)
        self.assertEqual(second.batches, [], "a converged corpus loads no model work")

    def test_resumption_is_model_aware(self):
        # A re-index under a second model sees a full backlog rather than an
        # empty one. The `embedding_model` predicate is what makes that true.
        staged = corpus({f"FOO 1.{n}": f"Invented saying number {n}." for n in range(5)})
        store = FakeStore()
        run(staged, store, FakeEmbedder())

        second = FakeEmbedder()
        second.name = "another-embedder"
        plan = run(staged, store, second)

        self.assertEqual(plan.embedding_backlog, 5)
        self.assertEqual(len(store.embeddings), 10, "new vectors beside the old ones")


class UpdateDropsItsEmbeddingTest(unittest.TestCase):
    """The one that proves the trap.

    An update that rewrites `text` and `content_hash` while leaving the old
    vector in place produces a chunk retrieved for what it used to say and
    quoted for what it now says. Verification does not catch it: check 2
    substring-matches the quote against `corpus.chunks.text`, which is the new
    text, and it passes.

    The buggy implementation passes every other check in the system, so this is
    the only place it is caught.
    """

    def test_a_changed_record_has_its_vector_deleted_and_re_created(self):
        store, embedder = FakeStore(), FakeEmbedder()
        run(corpus({"FOO 1.1": "The invented text."}), store, embedder)
        before = store.vectors_for(CORPUS_ID, "FOO 1.1")[0]["embedding"][0]

        run(corpus({"FOO 1.1": "The invented text, corrected and made longer."}),
            store, embedder)

        vectors = store.vectors_for(CORPUS_ID, "FOO 1.1")
        self.assertEqual(len(vectors), 1, "exactly one vector, not two")
        # Compared on one component, so a failure reads as two numbers rather
        # than as 2,048 of them.
        self.assertNotEqual(
            vectors[0]["embedding"][0], before,
            "the vector still describes the text the chunk no longer carries",
        )

    def test_an_unchanged_neighbour_keeps_the_vector_it_had(self):
        store, embedder = FakeStore(), FakeEmbedder()
        run(corpus({"FOO 1.1": "The invented text.", "FOO 1.2": "A second saying."}),
            store, embedder)
        untouched = store.vectors_for(CORPUS_ID, "FOO 1.2")[0]["embedding"][0]

        run(corpus({"FOO 1.1": "Corrected, and quite a lot longer than before.",
                    "FOO 1.2": "A second saying."}), store, embedder)

        self.assertEqual(store.vectors_for(CORPUS_ID, "FOO 1.2")[0]["embedding"][0], untouched)
        self.assertEqual(len(store.embeddings), 2)


class DryRunTest(unittest.TestCase):
    """It computes and prints its plan, and writes only under `--apply`."""

    def test_planning_alone_writes_nothing(self):
        staged = corpus({"FOO 1.1": "The invented text."})
        store, embedder = FakeStore(), FakeEmbedder()

        existing = store.existing_chunks(CORPUS_ID, embedder.name)
        plan = planning.diff(CORPUS_ID, staged.records, existing)

        self.assertEqual(len(plan.inserts), 1)
        self.assertEqual(store.chunks, {})
        self.assertEqual(store.commits, 0)
        self.assertEqual(embedder.batches, [])


if __name__ == "__main__":
    unittest.main()
