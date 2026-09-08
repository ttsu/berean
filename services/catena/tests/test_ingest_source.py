"""Reading the staging directory ingestion loads from, and the order of `--all`.

Invented corpora throughout (ADR-0014).
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from catena.acquire.record import AcquisitionError, WorkFacts, stage, write_jsonl, write_text
from catena.ingest import source

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


def write_corpus(data_dir: pathlib.Path, corpus_id: str, texts: dict[str, str], *, version=1):
    records = [stage(locator, text) for locator, text in texts.items()]
    out = data_dir / "acquire" / corpus_id / "stage"
    write_jsonl(out / "records.jsonl", records)
    write_text(
        out / "work.json",
        json.dumps(
            {
                "corpus_id": corpus_id,
                "normalisation_version": version,
                "chunk_count": len(records),
                "work": WORK.to_dict(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return records


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_it_reads_the_records_and_the_work_facts_beside_them(self):
        write_corpus(self.tmp, "foo-1899-invented", {"FOO 1.1": "The invented text."})

        loaded = source.load("foo-1899-invented", data_dir=self.tmp)

        self.assertEqual(loaded.corpus_id, "foo-1899-invented")
        self.assertEqual(loaded.work, WORK)
        self.assertEqual(loaded.normalisation_version, 1)
        self.assertEqual([r.locator for r in loaded.records], ["FOO 1.1"])
        self.assertEqual(loaded.records[0].text, "The invented text.")

    def test_a_corpus_that_was_never_staged_is_an_error_naming_the_fix(self):
        with self.assertRaises(AcquisitionError) as caught:
            source.load("bar-1900-invented", data_dir=self.tmp)

        self.assertIn("bar-1900-invented", str(caught.exception))

    def test_a_record_count_disagreeing_with_work_json_refuses(self):
        # A half-written records.jsonl beside a complete work.json is exactly
        # the truncation the fingerprint check exists to catch, and this catches
        # it before the fingerprints are even read.
        write_corpus(self.tmp, "foo-1899-invented", {"FOO 1.1": "The invented text."})
        path = self.tmp / "acquire" / "foo-1899-invented" / "stage" / "work.json"
        declared = json.loads(path.read_text())
        declared["chunk_count"] = 7
        write_text(path, json.dumps(declared))

        with self.assertRaises(AcquisitionError) as caught:
            source.load("foo-1899-invented", data_dir=self.tmp)

        self.assertIn("7", str(caught.exception))
        self.assertIn("1", str(caught.exception))


class OrderTest(unittest.TestCase):
    """Smallest first, which puts WEB — 89% of the work — last."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())

    def test_corpora_run_smallest_first(self):
        write_corpus(self.tmp, "big-1900-invented", {f"B {n}": f"Saying {n}." for n in range(30)})
        write_corpus(self.tmp, "small-1901-invented", {"S 1": "One saying."})
        write_corpus(self.tmp, "mid-1902-invented", {f"M {n}": f"Saying {n}." for n in range(5)})

        self.assertEqual(
            source.discover(data_dir=self.tmp),
            ["small-1901-invented", "mid-1902-invented", "big-1900-invented"],
        )

    def test_discovery_of_an_empty_tree_is_empty_rather_than_an_error(self):
        self.assertEqual(source.discover(data_dir=self.tmp), [])


if __name__ == "__main__":
    unittest.main()
