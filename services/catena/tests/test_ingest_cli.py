"""`catena ingest` — the argument surface and the `--apply` inversion.

`catena acquire` writes unless told otherwise; `catena ingest` is the other way
round. The asymmetry is about what a wrong run costs: acquisition writes into
gitignored `/data` and a mistake costs minutes of re-fetching, while ingestion
updates and deletes rows that cascade to embeddings, and a wrong run costs
hours no cache can return.

Invented corpora throughout (ADR-0014).
"""

from __future__ import annotations

import io
import pathlib
import tempfile
import unittest

from catena.acquire import fingerprints as fp
from catena.ingest import cli
from fakes import FakeEmbedder, FakeStore
from test_ingest_source import write_corpus


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        self.corpora = self.tmp / "corpora"
        self.store = FakeStore()
        self.embedder = FakeEmbedder()
        self.stream = io.StringIO()

    def bless(self, corpus_id, records):
        fp.write(
            self.corpora / corpus_id / "fingerprints.txt",
            {r.locator: r.content_hash for r in records},
        )

    def stage_blessed(self, corpus_id, texts):
        records = write_corpus(self.data, corpus_id, texts)
        self.bless(corpus_id, records)
        return records

    def run_cli(self, *argv):
        return cli.main(
            list(argv),
            stream=self.stream,
            data_dir=self.data,
            corpora_dir=self.corpora,
            open_store=lambda: self.store,
            load_embedder=lambda: self.embedder,
        )

    # -- the argument surface ---------------------------------------------

    def test_a_target_is_required(self):
        self.assertEqual(self.run_cli(), cli.EX_USAGE)

    def test_corpus_and_all_are_mutually_exclusive(self):
        self.assertEqual(self.run_cli("--corpus", "foo-1899-invented", "--all"), cli.EX_USAGE)

    # -- the default is a dry run -----------------------------------------

    def test_without_apply_it_writes_nothing(self):
        self.stage_blessed("foo-1899-invented", {"FOO 1.1": "The invented text."})

        code = self.run_cli("--corpus", "foo-1899-invented")

        self.assertEqual(code, cli.EX_OK)
        self.assertEqual(self.store.chunks, {})
        self.assertEqual(self.store.commits, 0)
        self.assertEqual(self.embedder.batches, [])

    def test_the_dry_run_prints_the_tally(self):
        self.stage_blessed("foo-1899-invented", {"FOO 1.1": "The invented text."})

        self.run_cli("--corpus", "foo-1899-invented")

        printed = self.stream.getvalue()
        self.assertIn("1 insert", printed)
        self.assertIn("1 embeddings remaining", printed)

    def test_the_dry_run_says_how_to_execute_it(self):
        self.stage_blessed("foo-1899-invented", {"FOO 1.1": "The invented text."})

        self.run_cli("--corpus", "foo-1899-invented")

        self.assertIn("--apply", self.stream.getvalue())

    # -- --apply ----------------------------------------------------------

    def test_apply_executes_and_prints_the_plan_it_executed(self):
        self.stage_blessed("foo-1899-invented", {"FOO 1.1": "The invented text."})

        code = self.run_cli("--corpus", "foo-1899-invented", "--apply")

        self.assertEqual(code, cli.EX_OK)
        self.assertEqual(len(self.store.chunks), 1)
        self.assertEqual(len(self.store.embeddings), 1)
        # `--apply` recomputes and prints the plan it is about to execute, so
        # the log records what happened even where it differed from the dry run.
        self.assertIn("1 insert", self.stream.getvalue())

    def test_a_second_apply_is_a_no_op(self):
        self.stage_blessed("foo-1899-invented", {"FOO 1.1": "The invented text."})
        self.run_cli("--corpus", "foo-1899-invented", "--apply")
        commits = self.store.commits

        self.run_cli("--corpus", "foo-1899-invented", "--apply")

        self.assertEqual(len(self.store.chunks), 1)
        self.assertEqual(len(self.store.embeddings), 1)
        self.assertEqual(self.store.commits, commits + 1, "phase one only")

    # -- refusals ---------------------------------------------------------

    def test_an_unblessed_corpus_refuses_and_writes_nothing(self):
        write_corpus(self.data, "foo-1899-invented", {"FOO 1.1": "The invented text."})

        code = self.run_cli("--corpus", "foo-1899-invented", "--apply")

        self.assertEqual(code, cli.EX_FAIL)
        self.assertEqual(self.store.chunks, {})
        self.assertIn("blessed", self.stream.getvalue())

    def test_a_corpus_drifted_from_its_fingerprints_refuses(self):
        records = write_corpus(self.data, "foo-1899-invented", {"FOO 1.1": "The invented text."})
        self.bless("foo-1899-invented", records)
        # Re-stage different text without re-blessing.
        write_corpus(self.data, "foo-1899-invented", {"FOO 1.1": "Something else entirely."})

        code = self.run_cli("--corpus", "foo-1899-invented", "--apply")

        self.assertEqual(code, cli.EX_FAIL)
        self.assertEqual(self.store.chunks, {})

    def test_an_over_long_chunk_refuses_before_anything_is_written(self):
        self.embedder = FakeEmbedder(max_tokens=3)
        self.stage_blessed("foo-1899-invented", {"FOO 1.1": "one two three four five"})

        code = self.run_cli("--corpus", "foo-1899-invented", "--apply")

        self.assertEqual(code, cli.EX_FAIL)
        self.assertEqual(self.store.chunks, {})

    # -- --all ------------------------------------------------------------

    def test_all_runs_every_staged_corpus_smallest_first(self):
        self.stage_blessed("big-1900-invented", {f"B {n}": f"Saying {n}." for n in range(6)})
        self.stage_blessed("small-1901-invented", {"S 1": "One saying."})

        code = self.run_cli("--all", "--apply")

        self.assertEqual(code, cli.EX_OK)
        self.assertEqual(len(self.store.chunks), 7)
        printed = self.stream.getvalue()
        self.assertLess(printed.index("small-1901-invented"), printed.index("big-1900-invented"))

    def test_one_corpus_refusing_does_not_stop_the_others(self):
        self.stage_blessed("good-1901-invented", {"G 1": "One saying."})
        write_corpus(self.data, "bad-1900-invented", {"B 1": "Never blessed."})

        code = self.run_cli("--all", "--apply")

        self.assertEqual(code, cli.EX_FAIL)
        self.assertEqual([r["locator"] for r in self.store.chunks.values()], ["G 1"])
        self.assertIn("bad-1900-invented", self.stream.getvalue())


if __name__ == "__main__":
    unittest.main()
