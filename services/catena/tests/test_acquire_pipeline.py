"""The acquisition pipeline, over an invented corpus.

ADR-0014 bars corpus text from fixtures, and that is not an inconvenience to
work around — it decides the shape of this suite. Every generic stage (cache,
verify, bless, staging, manifest validation) is exercised against a fake
adapter over a document defined in this module, because none of those stages
care what the text says. Real acquisition of the Westminster Confession is
`make provision-corpus`; drift detection is `make corpus-verify`. Neither is
part of `make check`, which runs with nothing started and no network.

No test here touches the network. The one seam that could is injected.
"""

from __future__ import annotations

import contextlib
import io
import os
import pathlib
import tempfile
import unittest
from typing import Iterator

import yaml

from catena import normalise
from catena.acquire import cli, corpora
from catena.acquire import fingerprints as fp
from catena.acquire import manifest as mf
from catena.acquire import pipeline, record
from catena.acquire.fetch import FetchPlan
from catena.acquire.record import AcquisitionError, Segment, WorkFacts

CORPUS_ID = "testcorpus-0001-invented"

#: Invented text, deliberately carrying the characters the normalisation
#: contract removes and collapses: a no-break space, a soft hyphen, and a run of
#: whitespace. If the pipeline ever let an adapter hand text through unchanged,
#: these are what would survive into a fingerprint.
PAGE = (
    "TC 1.1|The first invented saying, made up entirely  for this suite.\n"
    "TC 1.2|The second invented saying, with a soft­hyphen in it.\n"
    "TC 10.1|A tenth-chapter saying, here to make the sort order visible.\n"
    "TC 2.1|A second-chapter saying, which sorts after the tenth bytewise.\n"
).encode("utf-8")

WORK = WorkFacts(
    work="An Invented Corpus",
    author=None,
    era="never",
    language="en",
    source_language="en",
    text_form="not-applicable",
    edition="the only one",
    license="public-domain",
    attribution="Invented for the acquisition suite. Not a real work.",
)

LICENSE_TERMS = "Invented for the acquisition suite; there is no upstream and no licence."


class FakeAdapter:
    """A corpus-specific adapter over a document that says nothing.

    Structurally identical to a real one — the pipeline type-checks nothing at
    run time, which is the point of a Protocol.
    """

    corpus_id = CORPUS_ID
    work = WORK
    license_terms = LICENSE_TERMS
    diagnostic = "TC 1.1"

    def __init__(self) -> None:
        self.extracted = 0
        self.segmented = 0

    def fetch_plan(self) -> FetchPlan:
        return FetchPlan(
            source_url="https://invented.example/corpus.txt",
            archive_url="https://archive.invented.example/corpus.txt",
        )

    def extract(self, raw: bytes) -> str:
        self.extracted += 1
        return raw.decode("utf-8")

    def segment(self, document: str) -> Iterator[Segment]:
        self.segmented += 1
        for line in document.splitlines():
            if line.strip():
                locator, _, text = line.partition("|")
                yield Segment(locator, text)


class CountingDownloader:
    def __init__(self, payload: bytes = PAGE) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return self.payload


class Workspace(unittest.TestCase):
    """A data directory, a corpora directory, and a fake adapter."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = pathlib.Path(self._tmp.name)
        self.data_dir = root / "data"
        self.corpora_dir = root / "corpora"
        self.corpora_dir.mkdir(parents=True)
        self.adapter = FakeAdapter()

    def acquire(self, **kwargs) -> pipeline.Acquired:
        kwargs.setdefault("downloader", CountingDownloader())
        kwargs.setdefault("manifest", None)
        return pipeline.acquire(self.adapter, data_dir=self.data_dir, **kwargs)

    def bless(self, *, name: str = "A Verifier", **kwargs) -> mf.Manifest:
        acquired = kwargs.pop("acquired", None) or self.acquire()
        return pipeline.bless(
            self.adapter,
            acquired,
            corpora_dir=self.corpora_dir,
            retrieved="2026-09-04",
            verified="2026-09-04",
            existing=kwargs.pop("existing", None),
            stream=io.StringIO(),
            prompt=kwargs.pop("prompt", lambda _: name),
            interactive=True,
        )

    @property
    def manifest_path(self) -> pathlib.Path:
        return self.corpora_dir / CORPUS_ID / mf.FILENAME

    @property
    def fingerprints_path(self) -> pathlib.Path:
        return self.corpora_dir / CORPUS_ID / mf.FINGERPRINTS_FILENAME


class Fingerprints(unittest.TestCase):
    def test_round_trips(self) -> None:
        original = {"TC 1.1": "a" * 64, "TC 10.1": "b" * 64, "TC 2.1": "c" * 64}
        self.assertEqual(fp.parse(fp.render(original)), original)

    def test_order_is_bytewise_on_utf8(self) -> None:
        rendered = fp.render({"TC 2.1": "a" * 64, "TC 10.1": "b" * 64, "TC 1.1": "c" * 64})
        locators = [line.rpartition(fp.SEPARATOR)[0] for line in rendered.splitlines()]
        self.assertEqual(
            locators,
            ["TC 1.1", "TC 10.1", "TC 2.1"],
            "the order is bytewise on the UTF-8 encoding of the locator, so "
            "`TC 10.1` sorts before `TC 2.1`. A numeric-aware sort would need a "
            "locator grammar this file format does not have",
        )

    def test_a_locator_twice_is_rejected(self) -> None:
        with self.assertRaises(AcquisitionError):
            fp.parse(f"TC 1.1  {'a' * 64}\nTC 1.1  {'b' * 64}\n")

    def test_a_malformed_line_is_rejected(self) -> None:
        with self.assertRaises(AcquisitionError):
            fp.parse("TC 1.1  not-a-sha256\n")

    def test_the_three_classes_report_together(self) -> None:
        committed = {"TC 1.1": "a" * 64, "TC 1.2": "b" * 64, "TC 2.1": "c" * 64}
        acquired = {"TC 1.1": "a" * 64, "TC 1.2": "d" * 64, "TC 3.1": "e" * 64}
        diff = fp.compare(committed, acquired)
        self.assertEqual(diff.missing, ["TC 2.1"])
        self.assertEqual(diff.unexpected, ["TC 3.1"])
        self.assertEqual(diff.mismatched, ["TC 1.2"])
        self.assertFalse(diff.clean)
        summary = "\n".join(diff.summary())
        for label in ("missing", "unexpected", "mismatched"):
            self.assertIn(label, summary, "all three classes are reported, never one at a time")

    def test_the_summary_carries_locators_and_never_text(self) -> None:
        diff = fp.compare({"TC 1.1": "a" * 64}, {"TC 1.1": "b" * 64})
        summary = "\n".join(diff.summary())
        self.assertIn("TC 1.1", summary)
        self.assertNotIn(
            "a" * 64,
            summary,
            "a diff prints counts and locators. Printing the differing passage would "
            "put corpus text into CI logs, and text has exactly one home (ADR-0014)",
        )


class ManifestValidation(unittest.TestCase):
    def payload(self, **overrides) -> dict:
        base = {
            "corpus_id": CORPUS_ID,
            "source_url": "https://invented.example/corpus.txt",
            "archive_url": "https://archive.invented.example/corpus.txt",
            "retrieved": "2026-09-04",
            "upstream_sha256": "0" * 64,
            "license": "public-domain",
            "license_terms": LICENSE_TERMS,
            "attribution": WORK.attribution,
            "normalisation_version": 1,
            "chunk_count": 4,
            "edition_check": {
                "diagnostic": "TC 1.1",
                "expected_sha256": "e" * 64,
                "verified_by": "A Verifier",
                "verified": "2026-09-04",
            },
        }
        base.update(overrides)
        return base

    def test_round_trips_through_yaml(self) -> None:
        manifest = mf.parse(self.payload())
        self.assertEqual(mf.parse(yaml.safe_load(manifest.to_yaml())), manifest)

    def test_an_unknown_licence_is_rejected(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            mf.parse(self.payload(license="probably-fine"))
        self.assertIn("license", str(caught.exception))

    def test_a_missing_required_field_is_rejected(self) -> None:
        payload = self.payload()
        del payload["attribution"]
        with self.assertRaises(AcquisitionError) as caught:
            mf.parse(payload)
        self.assertIn("attribution", str(caught.exception))

    def test_a_missing_edition_check_field_is_rejected(self) -> None:
        payload = self.payload()
        del payload["edition_check"]["expected_sha256"]
        with self.assertRaises(AcquisitionError):
            mf.parse(payload)

    def test_the_edition_check_records_a_hash_and_never_text(self) -> None:
        payload = self.payload()
        payload["edition_check"]["expected_sha256"] = "The first invented saying."
        with self.assertRaises(AcquisitionError) as caught:
            mf.parse(payload)
        self.assertIn(
            "ADR-0021",
            str(caught.exception),
            "the manifest records that a human verified the edition and what they "
            "verified against; the text they read is never committed",
        )

    def test_a_manifest_that_is_not_yaml_is_a_message_not_a_traceback(self) -> None:
        path = pathlib.Path(tempfile.mkdtemp()) / mf.FILENAME
        path.write_text("corpus_id: [unclosed\n", encoding="utf-8")
        with self.assertRaises(AcquisitionError) as caught:
            mf.read(path)
        self.assertIn("not valid YAML", str(caught.exception))

    def test_an_unknown_field_is_rejected(self) -> None:
        with self.assertRaises(AcquisitionError):
            mf.parse(self.payload(licence_terms="a plausible misspelling"))

    def test_a_bare_corpus_id_is_rejected(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            mf.parse(self.payload(corpus_id="wcf"))
        self.assertIn("edition-specific", str(caught.exception))

    def test_multi_line_terms_stay_readable(self) -> None:
        manifest = mf.parse(self.payload(license_terms="Line one.\n\nLine two, quoted.\n"))
        self.assertIn(
            "license_terms: |",
            manifest.to_yaml(),
            "terms quoted verbatim are written as a literal block; a folded copy is "
            "no longer verbatim in any way a reader can check",
        )


class WorkFactsValidation(unittest.TestCase):
    def test_an_unknown_text_form_is_rejected(self) -> None:
        with self.assertRaises(AcquisitionError):
            WorkFacts(**{**WORK.to_dict(), "text_form": "probably-prose"})

    def test_an_empty_author_is_rejected(self) -> None:
        with self.assertRaises(AcquisitionError):
            WorkFacts(**{**WORK.to_dict(), "author": "  "})

    def test_a_null_author_is_allowed(self) -> None:
        self.assertIsNone(WorkFacts(**{**WORK.to_dict(), "author": None}).author)


class Fetching(Workspace):
    def test_from_file_matches_a_fetch_of_the_same_bytes(self) -> None:
        local = pathlib.Path(self._tmp.name) / "local-copy.txt"
        local.write_bytes(PAGE)

        downloaded = self.acquire()
        from_file = self.acquire(from_file=local)

        self.assertEqual(from_file.records, downloaded.records)
        self.assertEqual(from_file.fetched.digest, downloaded.fetched.digest)

    def test_from_file_never_touches_the_network(self) -> None:
        local = pathlib.Path(self._tmp.name) / "local-copy.txt"
        local.write_bytes(PAGE)
        downloader = CountingDownloader()
        self.acquire(from_file=local, downloader=downloader)
        self.assertEqual(downloader.calls, [])

    def test_a_cache_hit_skips_the_network(self) -> None:
        downloader = CountingDownloader()
        first = self.acquire(downloader=downloader)
        manifest = self.bless(acquired=first)

        second = self.acquire(manifest=manifest, downloader=downloader)
        self.assertEqual(len(downloader.calls), 1, "the second run read the cached blob")
        self.assertTrue(second.fetched.from_cache)

    def test_verify_only_always_refetches(self) -> None:
        downloader = CountingDownloader()
        manifest = self.bless(acquired=self.acquire(downloader=downloader))
        self.acquire(manifest=manifest, refetch=True, downloader=downloader)
        self.assertEqual(
            len(downloader.calls),
            2,
            "noticing upstream drift is the entire job of --verify-only, and a cache "
            "hit would report success while evaluating nothing",
        )

    def test_a_dead_source_falls_back_to_the_archive(self) -> None:
        plan = self.adapter.fetch_plan()

        def downloader(url: str) -> bytes:
            if url == plan.source_url:
                raise OSError("upstream is gone")
            return PAGE

        acquired = self.acquire(downloader=downloader)
        self.assertEqual(acquired.fetched.origin, plan.archive_url)

    def test_both_sources_dead_names_from_file(self) -> None:
        def downloader(url: str) -> bytes:
            raise OSError("gone")

        with self.assertRaises(AcquisitionError) as caught:
            self.acquire(downloader=downloader)
        self.assertIn("--from-file", str(caught.exception))


class Normalising(Workspace):
    def test_the_pipeline_normalises_what_the_adapter_yields(self) -> None:
        acquired = self.acquire()
        staged = acquired.record_at("TC 1.1")
        self.assertIsNotNone(staged)
        text = staged.text
        self.assertNotIn(" ", text)
        self.assertNotIn("  ", text)
        self.assertEqual(
            text,
            normalise.normalise(text),
            "normalisation is applied by the pipeline, never by the adapter — a "
            "per-corpus normalisation is the drift the contract exists to prevent",
        )

    def test_the_hash_is_over_normalised_text(self) -> None:
        acquired = self.acquire()
        for staged in acquired.records:
            self.assertEqual(staged.content_hash, record.fingerprint(staged.text))

    def test_a_locator_segmented_twice_is_an_error(self) -> None:
        class Duplicating(FakeAdapter):
            def segment(self, document: str) -> Iterator[Segment]:
                yield Segment("TC 1.1", "one")
                yield Segment("TC 1.1", "two")

        self.adapter = Duplicating()
        with self.assertRaises(AcquisitionError) as caught:
            self.acquire()
        self.assertIn("check 1", str(caught.exception))

    def test_every_stage_leaves_its_output_on_disk(self) -> None:
        self.acquire()
        work = pipeline.corpus_dir(self.data_dir, CORPUS_ID)
        for stage, name in (
            ("extract", pipeline.DOCUMENT),
            ("segment", pipeline.SEGMENTS),
            ("normalise", pipeline.RECORDS),
        ):
            self.assertTrue((work / stage / name).exists(), f"{stage} wrote nothing")


class Staging(Workspace):
    def test_staging_is_idempotent(self) -> None:
        acquired = self.acquire()
        out = pipeline.write_stage(acquired, data_dir=self.data_dir)
        first = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
        pipeline.write_stage(self.acquire(), data_dir=self.data_dir)
        second = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
        self.assertEqual(first, second)

    def test_the_work_facts_are_staged_beside_the_records(self) -> None:
        out = pipeline.write_stage(self.acquire(), data_dir=self.data_dir)
        staged = yaml.safe_load((out / pipeline.WORK).read_text(encoding="utf-8"))
        self.assertEqual(staged["work"], WORK.to_dict())
        self.assertEqual(staged["normalisation_version"], normalise.NORMALISATION_VERSION)
        self.assertEqual(
            staged["chunk_count"],
            4,
            "ingestion reads the work facts from here rather than re-deriving them "
            "from a source it is forbidden to parse",
        )


class Verifying(Workspace):
    def setUp(self) -> None:
        super().setUp()
        self.acquired = self.acquire()
        self.manifest = self.bless(acquired=self.acquired)
        self.committed = fp.read(self.fingerprints_path)

    def test_a_clean_acquisition_verifies(self) -> None:
        report = pipeline.verify(self.adapter, self.acquire(), self.manifest, self.committed)
        self.assertTrue(report.ok, "\n".join(report.lines()))

    def test_a_chunk_count_mismatch_fails(self) -> None:
        manifest = mf.parse({**yaml.safe_load(self.manifest.to_yaml()), "chunk_count": 3})
        report = pipeline.verify(self.adapter, self.acquired, manifest, self.committed)
        self.assertFalse(report.chunk_count_ok)
        self.assertFalse(report.ok, "a recorded number nothing checks is a comment")

    def test_a_normalisation_version_mismatch_fails_hard(self) -> None:
        manifest = mf.parse(
            {**yaml.safe_load(self.manifest.to_yaml()), "normalisation_version": 99}
        )
        with self.assertRaises(AcquisitionError) as caught:
            pipeline.verify(self.adapter, self.acquired, manifest, self.committed)
        self.assertIn("re-blessing", str(caught.exception))

    def test_a_changed_edition_diagnostic_fails(self) -> None:
        payload = yaml.safe_load(self.manifest.to_yaml())
        payload["edition_check"]["expected_sha256"] = "e" * 64
        report = pipeline.verify(
            self.adapter, self.acquired, mf.parse(payload), self.committed
        )
        self.assertFalse(report.edition_ok)
        self.assertFalse(report.ok)

    def test_a_missing_diagnostic_locator_fails(self) -> None:
        class Truncating(FakeAdapter):
            def segment(self, document: str) -> Iterator[Segment]:
                for segment in FakeAdapter.segment(self, document):
                    if segment.locator != "TC 1.1":
                        yield segment

        self.adapter = Truncating()
        report = pipeline.verify(
            self.adapter, self.acquire(), self.manifest, self.committed
        )
        self.assertFalse(report.edition_ok)
        self.assertIn("gone", report.edition_detail)

    def test_a_manifest_edited_away_from_the_adapter_is_caught(self) -> None:
        payload = yaml.safe_load(self.manifest.to_yaml())
        payload["source_url"] = "https://somewhere.else.example/corpus.txt"
        with self.assertRaises(AcquisitionError) as caught:
            pipeline.verify(self.adapter, self.acquired, mf.parse(payload), self.committed)
        self.assertIn("re-blessing", str(caught.exception))

    def test_upstream_drift_is_reported_and_is_not_a_failure_on_its_own(self) -> None:
        payload = yaml.safe_load(self.manifest.to_yaml())
        payload["upstream_sha256"] = "f" * 64
        report = pipeline.verify(
            self.adapter, self.acquired, mf.parse(payload), self.committed
        )
        self.assertTrue(report.upstream_drifted)
        self.assertTrue(
            report.ok,
            "the confession does not change when a publisher's footer year does; the "
            "fingerprints are the authority",
        )
        self.assertIn("upstream bytes changed", "\n".join(report.lines()))


class Blessing(Workspace):
    def test_aborts_when_stdin_is_not_a_terminal(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            pipeline.bless(
                self.adapter,
                self.acquire(),
                corpora_dir=self.corpora_dir,
                retrieved="2026-09-04",
                verified="2026-09-04",
                existing=None,
                stream=io.StringIO(),
                prompt=lambda _: "A Verifier",
                interactive=False,
            )
        self.assertIn("terminal", str(caught.exception))
        self.assertFalse(self.manifest_path.exists(), "an aborted bless writes nothing")

    def test_writes_a_manifest_and_fingerprints(self) -> None:
        manifest = self.bless()
        self.assertEqual(mf.read(self.manifest_path), manifest)
        committed = fp.read(self.fingerprints_path)
        self.assertEqual(sorted(committed), ["TC 1.1", "TC 1.2", "TC 10.1", "TC 2.1"])
        self.assertEqual(manifest.chunk_count, 4)
        self.assertEqual(manifest.edition_check.verified_by, "A Verifier")

    def test_the_hash_recorded_is_of_the_text_that_was_printed(self) -> None:
        stream = io.StringIO()
        acquired = self.acquire()
        manifest = pipeline.bless(
            self.adapter,
            acquired,
            corpora_dir=self.corpora_dir,
            retrieved="2026-09-04",
            verified="2026-09-04",
            existing=None,
            stream=stream,
            prompt=lambda _: "A Verifier",
            interactive=True,
        )
        staged = acquired.record_at(self.adapter.diagnostic)
        self.assertEqual(manifest.edition_check.expected_sha256, staged.content_hash)
        self.assertIn(
            staged.text,
            stream.getvalue(),
            "the verifier decides on a full reading; the manifest records only the hash "
            "of what they read (ADR-0021)",
        )

    def test_a_manifest_the_adapter_would_make_invalid_fails_at_bless(self) -> None:
        class Unattributed(FakeAdapter):
            license_terms = "   "

        self.adapter = Unattributed()
        with self.assertRaises(AcquisitionError) as caught:
            self.bless()
        self.assertIn("license_terms", str(caught.exception))
        self.assertFalse(
            self.manifest_path.exists(),
            "validation belongs at bless, while the human is still standing there — a "
            "committed manifest every later read rejects is repairable only by another "
            "bless",
        )

    def test_an_empty_name_writes_nothing(self) -> None:
        with self.assertRaises(AcquisitionError) as caught:
            self.bless(name="   ")
        self.assertIn("verifier name", str(caught.exception))
        self.assertFalse(self.manifest_path.exists())

    def test_reblessing_demands_an_explicit_confirmation(self) -> None:
        self.bless()
        existing = fp.read(self.fingerprints_path)

        with self.assertRaises(AcquisitionError) as caught:
            self.bless(existing=existing, prompt=lambda _: "yes")
        self.assertIn("not confirmed", str(caught.exception))

        answers = iter([f"re-bless {CORPUS_ID}", "A Second Verifier"])
        manifest = self.bless(existing=existing, prompt=lambda _: next(answers))
        self.assertEqual(manifest.edition_check.verified_by, "A Second Verifier")

    def test_reblessing_shows_the_diff_before_asking_anything(self) -> None:
        self.bless()
        stream = io.StringIO()
        asked: list[str] = []

        def prompt(question: str) -> str:
            asked.append(stream.getvalue())
            return f"re-bless {CORPUS_ID}" if not asked[1:] else "A Second Verifier"

        pipeline.bless(
            self.adapter,
            self.acquire(),
            corpora_dir=self.corpora_dir,
            retrieved="2026-09-04",
            verified="2026-09-04",
            existing={"TC 1.1": "a" * 64},
            stream=stream,
            prompt=prompt,
            interactive=True,
        )
        self.assertIn("mismatched", asked[0])
        self.assertIn("missing", asked[0])
        self.assertIn("unexpected", asked[0])


class AtomicWrites(unittest.TestCase):
    """An interrupted bless must leave the previous file intact.

    A half-written fingerprint file is worse than no file: the next run verifies
    against it and reports on a corpus nobody blessed.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pathlib.Path(self._tmp.name) / "fingerprints.txt"
        self.path.write_text("previous contents\n", encoding="utf-8")

    def test_a_failed_write_leaves_the_previous_file_and_no_debris(self) -> None:
        original = os.replace

        def failing(src, dst):
            raise OSError("interrupted")

        os.replace = failing
        try:
            with self.assertRaises(OSError):
                record.write_text(self.path, "half a blessing\n")
        finally:
            os.replace = original

        self.assertEqual(self.path.read_text(encoding="utf-8"), "previous contents\n")
        self.assertEqual(
            [p.name for p in self.path.parent.iterdir()],
            ["fingerprints.txt"],
            "a rename that never happened leaves a temp file the next run would not "
            "know to reuse",
        )

    def test_a_successful_write_replaces_the_file(self) -> None:
        record.write_text(self.path, "new contents\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "new contents\n")


class CommandLine(Workspace):
    """The flag combinations, and what each one is allowed to do."""

    def run_cli(self, *argv: str) -> tuple[int, str]:
        stream = io.StringIO()
        environ = dict(os.environ)
        os.environ[cli.DATA_DIR_ENV] = str(self.data_dir)
        os.environ[cli.CORPORA_DIR_ENV] = str(self.corpora_dir)
        try:
            code = cli.main(list(argv), stream=stream)
        finally:
            os.environ.clear()
            os.environ.update(environ)
        return code, stream.getvalue()

    def test_bless_and_verify_only_are_incompatible(self) -> None:
        code, _ = self.run_cli("--corpus", CORPUS_ID, "--bless", "--verify-only")
        self.assertEqual(code, cli.EX_USAGE)

    def test_bless_refuses_all(self) -> None:
        code, out = self.run_cli("--all", "--bless")
        self.assertEqual(code, cli.EX_USAGE)
        self.assertIn("one --corpus", out)

    def test_neither_corpus_nor_all_is_a_usage_error(self) -> None:
        # argparse writes its own usage to the real stderr before raising, and a
        # suite that prints it on every green run trains people to skim output.
        with contextlib.redirect_stderr(io.StringIO()):
            code, _ = self.run_cli("--bless")
        self.assertEqual(code, cli.EX_USAGE)

    def test_an_unknown_corpus_is_a_usage_error(self) -> None:
        code, out = self.run_cli("--corpus", "not-a-corpus")
        self.assertEqual(code, cli.EX_USAGE)
        self.assertIn("unknown corpus", out)

    def test_an_unblessed_corpus_stages_so_it_can_be_read_before_blessing(self) -> None:
        """The browser hosts the first bless, and can only show what is staged.

        Refusing to stage an unblessed corpus made that feature unreachable: a
        corpus reaches `make browse` by being staged, staging required a
        successful verify, and verifying required the blessing the browser
        exists to perform. There is no committed record to drift from, so
        verification has nothing to do and staging is safe.
        """
        stream = io.StringIO()
        ok = cli.run_one(
            self.adapter,
            data_dir=self.data_dir,
            corpora_dir=self.corpora_dir,
            bless=False,
            verify_only=False,
            from_file=None,
            stream=stream,
            downloader=CountingDownloader(),
        )
        self.assertTrue(ok)
        staged = pipeline.corpus_dir(self.data_dir, CORPUS_ID) / "stage" / pipeline.RECORDS
        self.assertTrue(staged.is_file(), "an unblessed corpus must still stage")

    def test_staging_an_unblessed_corpus_says_nothing_was_verified(self) -> None:
        """Loudly, because a staged corpus otherwise looks like a checked one."""
        stream = io.StringIO()
        cli.run_one(
            self.adapter,
            data_dir=self.data_dir,
            corpora_dir=self.corpora_dir,
            bless=False,
            verify_only=False,
            from_file=None,
            stream=stream,
            downloader=CountingDownloader(),
        )
        self.assertIn("UNVERIFIED", stream.getvalue())

    def test_verify_only_refuses_an_unblessed_corpus(self) -> None:
        """Drift detection against no committed record is not a check that
        passes -- it is a check with nothing to evaluate."""
        with self.assertRaises(AcquisitionError) as caught:
            cli.run_one(
                self.adapter,
                data_dir=self.data_dir,
                corpora_dir=self.corpora_dir,
                bless=False,
                verify_only=True,
                from_file=None,
                stream=io.StringIO(),
                downloader=CountingDownloader(),
            )
        self.assertIn("nothing to compare", str(caught.exception))

    def test_a_manifest_without_fingerprints_is_half_a_blessing(self) -> None:
        manifest = self.bless()
        self.fingerprints_path.unlink()
        with self.assertRaises(AcquisitionError) as caught:
            cli.run_one(
                self.adapter,
                data_dir=self.data_dir,
                corpora_dir=self.corpora_dir,
                bless=False,
                verify_only=False,
                from_file=None,
                stream=io.StringIO(),
                downloader=CountingDownloader(),
            )
        self.assertIn("Half a blessing", str(caught.exception))
        self.assertEqual(manifest.corpus_id, CORPUS_ID)

    def test_a_default_run_verifies_and_stages(self) -> None:
        self.bless()
        stream = io.StringIO()
        ok = cli.run_one(
            self.adapter,
            data_dir=self.data_dir,
            corpora_dir=self.corpora_dir,
            bless=False,
            verify_only=False,
            from_file=None,
            stream=stream,
            downloader=CountingDownloader(),
        )
        self.assertTrue(ok, stream.getvalue())
        staged = pipeline.corpus_dir(self.data_dir, CORPUS_ID) / "stage" / pipeline.RECORDS
        self.assertTrue(staged.exists())

    def test_verify_only_stages_nothing(self) -> None:
        self.bless()
        ok = cli.run_one(
            self.adapter,
            data_dir=self.data_dir,
            corpora_dir=self.corpora_dir,
            bless=False,
            verify_only=True,
            from_file=None,
            stream=io.StringIO(),
            downloader=CountingDownloader(),
        )
        self.assertTrue(ok)
        self.assertFalse(
            (pipeline.corpus_dir(self.data_dir, CORPUS_ID) / "stage").exists(),
            "drift detection must not disturb records an ingestion may be reading",
        )

    def test_a_mismatch_exits_non_zero(self) -> None:
        self.bless()
        fp.write(self.fingerprints_path, {"TC 1.1": "a" * 64})
        stream = io.StringIO()
        ok = cli.run_one(
            self.adapter,
            data_dir=self.data_dir,
            corpora_dir=self.corpora_dir,
            bless=False,
            verify_only=True,
            from_file=None,
            stream=stream,
            downloader=CountingDownloader(),
        )
        self.assertFalse(ok)
        self.assertIn("FAIL", stream.getvalue())


class Registry(unittest.TestCase):
    def test_the_module_name_underscores_the_corpus_id(self) -> None:
        self.assertEqual(
            corpora.module_name("wcf-1788-american"),
            "catena.acquire.corpora.wcf_1788_american",
            "a hyphenated filename is not an importable module name",
        )

    def test_an_unknown_corpus_lists_what_is_registered(self) -> None:
        with self.assertRaises(KeyError) as caught:
            corpora.load("wcf")
        self.assertIn("wcf-1788-american", str(caught.exception))

    def test_every_registered_corpus_loads(self) -> None:
        for adapter in corpora.load_all():
            self.assertIn(adapter.corpus_id, corpora.CORPUS_IDS)
            self.assertIsInstance(adapter.work, WorkFacts)
            self.assertTrue(adapter.license_terms.strip())
            self.assertTrue(adapter.diagnostic.strip())


class ShowingTheDiagnostic(Workspace):
    """What replaces quoting the diagnostic into the manifest (ADR-0021)."""

    def test_it_prints_the_text_and_its_hash(self) -> None:
        acquired = self.acquire()
        stream = io.StringIO()
        pipeline.show_diagnostic(self.adapter, acquired, stream=stream)
        staged = acquired.record_at(self.adapter.diagnostic)
        printed = stream.getvalue()
        self.assertIn(staged.text, printed)
        self.assertIn(staged.content_hash, printed)

    def test_it_works_before_a_corpus_has_ever_been_blessed(self) -> None:
        stream = io.StringIO()
        ok = cli.run_one(
            self.adapter,
            data_dir=self.data_dir,
            corpora_dir=self.corpora_dir,
            bless=False,
            verify_only=False,
            show_diagnostic=True,
            from_file=None,
            stream=stream,
            downloader=CountingDownloader(),
        )
        self.assertTrue(ok, "the first bless is when someone most needs to read this")
        self.assertIn("TC 1.1", stream.getvalue())

    def test_it_stages_nothing(self) -> None:
        cli.run_one(
            self.adapter,
            data_dir=self.data_dir,
            corpora_dir=self.corpora_dir,
            bless=False,
            verify_only=False,
            show_diagnostic=True,
            from_file=None,
            stream=io.StringIO(),
            downloader=CountingDownloader(),
        )
        self.assertFalse((pipeline.corpus_dir(self.data_dir, CORPUS_ID) / "stage").exists())

    def test_a_missing_diagnostic_locator_says_so(self) -> None:
        class Truncating(FakeAdapter):
            def segment(self, document: str) -> Iterator[Segment]:
                for segment in FakeAdapter.segment(self, document):
                    if segment.locator != "TC 1.1":
                        yield segment

        self.adapter = Truncating()
        with self.assertRaises(AcquisitionError) as caught:
            pipeline.show_diagnostic(self.adapter, self.acquire(), stream=io.StringIO())
        self.assertIn("not among", str(caught.exception))


class CacheIntegrity(Workspace):
    """The cache is a plain directory in a bind mount, so its name is a claim."""

    def test_a_tampered_blob_is_refused_rather_than_extracted(self) -> None:
        manifest = self.bless(acquired=self.acquire())
        blob = (
            self.data_dir / "acquire" / CORPUS_ID / "fetch" / manifest.upstream_sha256
        )
        blob.write_bytes(PAGE.replace(b"first invented", b"tampered invented"))

        with self.assertRaises(AcquisitionError) as caught:
            self.acquire(manifest=manifest)
        message = str(caught.exception)
        self.assertIn("hashes to", message)
        self.assertIn(
            manifest.upstream_sha256,
            message,
            "trusting the filename would extract the altered bytes while the report "
            "line asserting the upstream is unchanged stayed green",
        )


class TransportFailures(Workspace):
    def test_a_truncated_response_falls_back_rather_than_escaping(self) -> None:
        import http.client

        plan = self.adapter.fetch_plan()

        def downloader(url: str) -> bytes:
            if url == plan.source_url:
                raise http.client.IncompleteRead(b"half a page")
            return PAGE

        acquired = self.acquire(downloader=downloader)
        self.assertEqual(
            acquired.fetched.origin,
            plan.archive_url,
            "HTTPException descends from neither URLError nor OSError, and a truncated "
            "response is exactly when an archive copy is worth reaching for",
        )


class Locators(unittest.TestCase):
    """A locator has to survive the round trip through fingerprints.txt."""

    def test_a_locator_with_a_newline_is_refused_at_staging(self) -> None:
        with self.assertRaises(AcquisitionError):
            record.stage("TC 1.1\nTC 1.2", "some invented text")

    def test_a_locator_with_a_doubled_space_is_refused(self) -> None:
        with self.assertRaises(AcquisitionError):
            record.stage("TC  1.1", "some invented text")

    def test_an_empty_locator_is_refused(self) -> None:
        with self.assertRaises(AcquisitionError):
            record.stage("   ", "some invented text")

    def test_single_internal_spaces_are_fine(self) -> None:
        self.assertEqual(record.stage("WSC Q&A 1", "some invented text").locator, "WSC Q&A 1")


class CommittedArtefacts(unittest.TestCase):
    """Every committed manifest, against the adapter that would re-acquire it.

    This is the check that ties `corpora/<id>/` to the code, and it is offline
    and needs no corpus text. Without it a manifest and its adapter can drift
    apart in a commit that passes `make check` and fails at provision time --
    which is exactly what happened once.
    """

    def setUp(self) -> None:
        self.corpora_dir = pathlib.Path(__file__).resolve().parents[3] / "corpora"

    def blessed(self, corpus_id: str) -> mf.Manifest | None:
        """The committed manifest, or None when the corpus is unblessed.

        A corpus with exactly one of the two files is not unblessed — it is half
        blessed, which verifies nothing, so it fails here rather than skipping.
        """
        manifest_path = self.corpora_dir / corpus_id / mf.FILENAME
        fingerprints_path = self.corpora_dir / corpus_id / mf.FINGERPRINTS_FILENAME
        if manifest_path.exists() != fingerprints_path.exists():
            self.fail(
                f"{corpus_id} has one of manifest.yaml and fingerprints.txt and not the "
                "other; half a blessing verifies nothing"
            )
        return mf.read(manifest_path)

    def test_every_committed_manifest_agrees_with_its_adapter(self) -> None:
        for corpus_id in corpora.CORPUS_IDS:
            with self.subTest(corpus_id):
                manifest = self.blessed(corpus_id)
                if manifest is None:
                    self.skipTest(f"{corpus_id} has not been blessed yet")
                pipeline._require_contract_version(manifest)
                pipeline._require_manifest_matches_adapter(corpora.load(corpus_id), manifest)

    def test_every_committed_fingerprint_file_matches_its_chunk_count(self) -> None:
        for corpus_id in corpora.CORPUS_IDS:
            with self.subTest(corpus_id):
                manifest = self.blessed(corpus_id)
                if manifest is None:
                    self.skipTest(f"{corpus_id} has not been blessed yet")
                committed = fp.read(self.corpora_dir / corpus_id / mf.FINGERPRINTS_FILENAME)
                self.assertEqual(len(committed), manifest.chunk_count)
                self.assertIn(
                    manifest.edition_check.diagnostic,
                    committed,
                    "the diagnostic locator is one of the corpus's own chunks",
                )
                self.assertEqual(
                    committed[manifest.edition_check.diagnostic],
                    manifest.edition_check.expected_sha256,
                    "the edition check and the fingerprint file describe the same chunk",
                )


if __name__ == "__main__":
    unittest.main()
