"""The corpus browser, over an invented corpus.

ADR-0014 bars corpus text from fixtures, so every fixture here is invented and
the real corpora are never opened. That is not a workaround: a viewer whose
suite needed the Westminster Confession on disk could only run on a machine that
had already acquired it, which is the opposite of what `make check` is for.

No test binds a socket. `route` is separated from the request handler precisely
so the routing can be exercised without one.
"""

from __future__ import annotations

import io
import json
import pathlib
import tempfile
import unittest
import unittest.mock

from catena import normalise
from catena.acquire import fingerprints as fp
from catena.acquire import manifest as mf
from catena.acquire.record import AcquisitionError, fingerprint, write_text
from catena.browse import render, server, staged, verify

CORPUS_ID = "testcorpus-0001-invented"

#: Invented segments carrying what the contract removes and collapses: a line
#: break the segmenter introduced, a no-break space, and a soft hyphen. These are
#: what the "before normalisation" panel exists to show.
SEGMENTS = {
    "TC 1.1": "The first invented section,\nsplit across two lines.",
    "TC 1.2": "A second section with a no break space and a soft­hyphen.",
    "TC 2.1": "A third section, in another invented chapter.",
}

WORK = {
    "work": "An Invented Work",
    "author": None,
    "era": "invented",
    "language": "en",
    "source_language": "en",
    "text_form": "not-applicable",
    "edition": "invented edition",
    "license": "public-domain",
    "attribution": "Invented for this suite. Not a real work.",
}


def build(
    root: pathlib.Path,
    *,
    corpus_id: str = CORPUS_ID,
    license: str = "public-domain",
    segments: dict[str, str] | None = None,
    bless: bool = True,
    drift: bool = False,
    write_segment_stage: bool = True,
    drop_from_stage: tuple[str, ...] = (),
    declared_count: int | None = None,
    corrupt_manifest: bool = False,
    corrupt_fingerprints: bool = False,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Lay out a staged corpus on disk, and optionally its committed evidence.

    `drop_from_stage` blesses every locator and stages all but those, which is
    what a segmenter that stopped producing a section leaves behind.
    """
    segments = SEGMENTS if segments is None else segments
    data_dir = root / "data"
    corpora_dir = root / "corpora"
    acquire = data_dir / "acquire" / corpus_id

    records = [
        {
            "locator": locator,
            "text": normalise.normalise(text),
            "content_hash": fingerprint(normalise.normalise(text)),
        }
        for locator, text in segments.items()
    ]
    staged_records = [row for row in records if row["locator"] not in drop_from_stage]

    write_text(
        acquire / "stage" / "records.jsonl",
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in staged_records
        ),
    )
    work = dict(WORK, license=license)
    write_text(
        acquire / "stage" / "work.json",
        json.dumps(
            {
                "corpus_id": corpus_id,
                "normalisation_version": normalise.NORMALISATION_VERSION,
                "chunk_count": (
                    len(staged_records) if declared_count is None else declared_count
                ),
                "work": work,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    if write_segment_stage:
        write_text(
            acquire / "segment" / "segments.jsonl",
            "".join(
                json.dumps({"locator": locator, "text": text}, ensure_ascii=False, sort_keys=True)
                + "\n"
                for locator, text in segments.items()
            ),
        )

    if bless:
        prints = {row["locator"]: row["content_hash"] for row in records}
        if drift:
            first = records[0]["locator"]
            prints[first] = "0" * 64
        fp.write(corpora_dir / corpus_id / mf.FINGERPRINTS_FILENAME, prints)
        manifest = mf.Manifest(
            corpus_id=corpus_id,
            source_url="https://invented.example/source",
            archive_url="https://invented.example/archive",
            retrieved="2026-01-01",
            upstream_sha256="a" * 64,
            license=license,
            license_terms="Invented terms.",
            attribution=work["attribution"],
            normalisation_version=normalise.NORMALISATION_VERSION,
            chunk_count=len(records),
            edition_check=mf.EditionCheck(
                diagnostic=records[0]["locator"],
                expected_sha256=records[0]["content_hash"],
                verified_by="the suite",
                verified="2026-01-01",
            ),
        )
        mf.write(corpora_dir / corpus_id / mf.FILENAME, manifest)

    if corrupt_manifest:
        write_text(corpora_dir / corpus_id / mf.FILENAME, "corpus_id: [unclosed\n")
    if corrupt_fingerprints:
        write_text(
            corpora_dir / corpus_id / mf.FINGERPRINTS_FILENAME, "TC 1.1  not-a-sha256\n"
        )

    return data_dir, corpora_dir


class TempCorpus(unittest.TestCase):
    def build(self, **kwargs) -> tuple[pathlib.Path, pathlib.Path]:
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(_rmtree, root)
        return build(root, **kwargs)


def _rmtree(path: pathlib.Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


class TestReading(TempCorpus):
    def test_reads_a_blessed_corpus(self) -> None:
        data_dir, corpora_dir = self.build()
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        self.assertEqual(corpus.corpus_id, CORPUS_ID)
        self.assertEqual(len(corpus.chunks), len(SEGMENTS))
        self.assertTrue(corpus.count_matches)
        self.assertEqual(corpus.fingerprint_status, staged.BLESSED)
        self.assertTrue(all(chunk.blessed for chunk in corpus.chunks))
        self.assertIsNotNone(corpus.manifest)

    def test_staged_order_is_preserved(self) -> None:
        data_dir, corpora_dir = self.build()
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        self.assertEqual(
            [chunk.locator for chunk in corpus.chunks],
            list(SEGMENTS),
            "chunks render in document order, which is the order they were staged in",
        )

    def test_text_is_post_normalisation(self) -> None:
        data_dir, corpora_dir = self.build()
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        chunk = corpus.chunks[0]
        self.assertNotIn("\n", chunk.text, "normalisation collapsed the segmenter's line break")
        self.assertIn("\n", chunk.raw, "the pre-normalisation segment kept it")

    def test_unblessed_corpus_opens_and_says_so(self) -> None:
        """A corpus acquired but never verified by hand is a normal state."""
        data_dir, corpora_dir = self.build(bless=False)
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        self.assertEqual(corpus.fingerprint_status, staged.UNBLESSED)
        self.assertIsNone(corpus.manifest)
        self.assertTrue(
            all(chunk.blessed is None for chunk in corpus.chunks),
            "'nobody has checked' is not 'the check failed'",
        )

    def test_drift_is_reported_per_chunk(self) -> None:
        data_dir, corpora_dir = self.build(drift=True)
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        self.assertEqual(corpus.fingerprint_status, staged.DRIFTED)
        self.assertEqual([chunk.locator for chunk in corpus.drifted], [list(SEGMENTS)[0]])

    def test_a_committed_section_missing_from_the_stage_is_drift(self) -> None:
        """The class a per-chunk check cannot see: a section that stopped existing.

        Every surviving chunk still matches its fingerprint, so a comparison that
        walks the staged records reports the corpus as blessed. What is on disk
        is one section short of what was approved.
        """
        dropped = "TC 2.1"
        data_dir, corpora_dir = self.build(drop_from_stage=(dropped,))
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        self.assertEqual(len(corpus.chunks), len(SEGMENTS) - 1)
        self.assertTrue(all(chunk.blessed for chunk in corpus.chunks))
        self.assertEqual(corpus.missing, [dropped])
        self.assertEqual(corpus.fingerprint_status, staged.DRIFTED)

    def test_a_staged_section_that_was_never_committed_is_drift(self) -> None:
        """The mirror case, already covered per chunk. Both stay reported."""
        data_dir, corpora_dir = self.build(bless=False)
        fp.write(
            corpora_dir / CORPUS_ID / mf.FINGERPRINTS_FILENAME,
            {"TC 1.1": fingerprint(normalise.normalise(SEGMENTS["TC 1.1"]))},
        )
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        self.assertEqual(corpus.missing, [])
        self.assertEqual(
            [chunk.locator for chunk in corpus.drifted], ["TC 1.2", "TC 2.1"]
        )
        self.assertEqual(corpus.fingerprint_status, staged.DRIFTED)

    def test_a_declared_count_that_does_not_match_the_stage(self) -> None:
        data_dir, corpora_dir = self.build(declared_count=99)
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        self.assertFalse(corpus.count_matches)

    def test_an_unreadable_manifest_is_reported_not_swallowed(self) -> None:
        """Silently dropping the provenance rows looks exactly like never blessed."""
        data_dir, corpora_dir = self.build(corrupt_manifest=True)
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        self.assertIsNone(corpus.manifest)
        self.assertIsNotNone(corpus.overlay_error)
        self.assertIn("manifest", corpus.overlay_error)
        self.assertEqual(
            corpus.fingerprint_status,
            staged.BLESSED,
            "the fingerprints are still readable, and they are what checks the text",
        )

    def test_unreadable_fingerprints_do_not_read_as_never_checked(self) -> None:
        data_dir, corpora_dir = self.build(corrupt_fingerprints=True)
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        self.assertEqual(corpus.fingerprint_status, staged.UNBLESSED)
        self.assertIsNotNone(corpus.overlay_error)
        self.assertIn("fingerprints", corpus.overlay_error)

    def test_raw_is_dropped_when_the_two_stages_disagree(self) -> None:
        """`pipeline.acquire` rewrites segment/ every run; only write_stage writes stage/.

        A panel reporting on a different run's segmentation than the text above
        it is worse than no panel: it is wrong and says nothing about being wrong.
        """
        data_dir, corpora_dir = self.build()
        write_text(
            data_dir / "acquire" / CORPUS_ID / "segment" / "segments.jsonl",
            "".join(
                json.dumps(
                    {"locator": locator, "text": text + " Revised by a later run."},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
                for locator, text in SEGMENTS.items()
            ),
        )
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        self.assertTrue(all(chunk.raw is None for chunk in corpus.chunks))
        self.assertTrue(all(chunk.text for chunk in corpus.chunks), "the text still renders")

    def test_missing_segment_stage_degrades(self) -> None:
        """`--verify-only` stages nothing, so segment output can legitimately be absent."""
        data_dir, corpora_dir = self.build(write_segment_stage=False)
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        self.assertTrue(all(chunk.raw is None for chunk in corpus.chunks))
        self.assertTrue(all(chunk.text for chunk in corpus.chunks))

    def test_unknown_corpus_raises(self) -> None:
        data_dir, corpora_dir = self.build()
        with self.assertRaises(AcquisitionError):
            staged.load("testcorpus-0002-absent", data_dir=data_dir, corpora_dir=corpora_dir)


class TestDiscovery(TempCorpus):
    def test_finds_staged_corpora_only(self) -> None:
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(_rmtree, root)
        data_dir, _ = build(root)
        # Acquired as far as fetch, never staged: not browsable.
        (data_dir / "acquire" / "testcorpus-0003-partial" / "fetch").mkdir(parents=True)

        self.assertEqual(staged.discover(data_dir=data_dir), [CORPUS_ID])

    def test_empty_data_dir(self) -> None:
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(_rmtree, root)
        self.assertEqual(staged.discover(data_dir=root / "nothing"), [])


class TestLicenceGate(TempCorpus):
    def test_public_domain_renders(self) -> None:
        data_dir, corpora_dir = self.build()
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        self.assertIsNone(staged.text_withheld_reason(corpus.work, serve_local_only=False))

    def test_refused_is_never_servable(self) -> None:
        data_dir, corpora_dir = self.build(license="refused")
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        self.assertIsNotNone(
            staged.text_withheld_reason(corpus.work, serve_local_only=True),
            "the opt-in does not reach a refused corpus",
        )

    def test_local_only_needs_the_opt_in(self) -> None:
        data_dir, corpora_dir = self.build(license="local-only")
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        self.assertIsNotNone(staged.text_withheld_reason(corpus.work, serve_local_only=False))
        self.assertIsNone(staged.text_withheld_reason(corpus.work, serve_local_only=True))

    def test_withheld_text_is_absent_from_the_markup(self) -> None:
        """Not hidden, not truncated: absent. The page is the serving act."""
        data_dir, corpora_dir = self.build(license="local-only")
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        reason = staged.text_withheld_reason(corpus.work, serve_local_only=False)
        page = render.corpus_page(corpus, withheld=reason)

        for chunk in corpus.chunks:
            self.assertNotIn(chunk.text, page)
            self.assertNotIn(chunk.raw, page)
        self.assertIn(staged.SERVE_LOCAL_ONLY_ENV, page)

    def test_the_opt_in_defaults_to_deny(self) -> None:
        for value in ("", "false", "0", "no", "off", "maybe"):
            self.assertFalse(staged.serve_local_only({staged.SERVE_LOCAL_ONLY_ENV: value}), value)
        for value in ("true", "TRUE", "1", "yes", "on"):
            self.assertTrue(staged.serve_local_only({staged.SERVE_LOCAL_ONLY_ENV: value}), value)
        self.assertFalse(staged.serve_local_only({}))


class TestRendering(TempCorpus):
    def page(self, **kwargs) -> str:
        data_dir, corpora_dir = self.build(**kwargs)
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        return render.corpus_page(corpus)

    def test_every_chunk_and_locator_appears(self) -> None:
        page = self.page()
        for locator, text in SEGMENTS.items():
            self.assertIn(locator, page)
            self.assertIn(render._e(normalise.normalise(text)), page)

    def test_metadata_is_present(self) -> None:
        page = self.page()
        for value in (WORK["work"], WORK["edition"], WORK["era"], WORK["attribution"]):
            self.assertIn(render._e(value), page)
        self.assertIn(CORPUS_ID, page)

    def test_markup_is_escaped(self) -> None:
        hostile = {'TC <1.1> & "x"': 'text with <script>alert("x")</script> & an ampersand'}
        page = self.page(segments=hostile)

        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&amp;", page)

    def test_drift_flag_appears_only_when_drifted(self) -> None:
        self.assertNotIn("does not match fingerprint", self.page())
        self.assertIn("does not match fingerprint", self.page(drift=True))

    def test_a_missing_section_is_named_in_the_banner(self) -> None:
        page = self.page(drop_from_stage=("TC 2.1",))
        self.assertIn("Drifted", page)
        self.assertIn("not in the staged output", page)
        self.assertIn("TC 2.1", page)

    def test_a_count_mismatch_is_shown(self) -> None:
        page = self.page(declared_count=99)
        self.assertIn("Staged output is inconsistent", page)
        self.assertIn("99", page)
        self.assertIn("3 staged, 99 declared", page)

    def test_a_clean_count_says_nothing_about_counts(self) -> None:
        self.assertNotIn("Staged output is inconsistent", self.page())

    def test_an_unreadable_overlay_is_shown(self) -> None:
        page = self.page(corrupt_fingerprints=True)
        self.assertIn("committed fingerprints cannot be read", page)
        self.assertNotIn(
            "Blessed. All", page, "an unreadable overlay is not a verdict on the text"
        )

    def test_the_raw_panel_says_why_it_is_absent(self) -> None:
        page = self.page(write_segment_stage=False)
        self.assertIn("No usable segment output", page)

    def test_unblessed_banner(self) -> None:
        page = self.page(bless=False)
        self.assertIn("Unblessed", page)
        self.assertIn("not checked", page)

    def test_no_external_asset_and_no_script(self) -> None:
        """`make dev-offline` blocks egress; the page must not need it."""
        page = self.page()
        for forbidden in ("<script", "http://", "src=", "@import", "cdn"):
            self.assertNotIn(forbidden, page.lower().replace("https://invented.example", ""))

    def test_index_anchors_match_chunk_ids(self) -> None:
        page = self.page()
        for locator in SEGMENTS:
            slug = render._slug(locator)
            self.assertIn(f'id="{slug}"', page)
            self.assertIn(f'href="#{slug}"', page)

    def test_paging_splits_and_bounds(self) -> None:
        data_dir, corpora_dir = self.build()
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)

        first = render.corpus_page(corpus, page=0, page_size=2)
        self.assertIn("Page 1 of 2", first)
        self.assertIn(list(SEGMENTS)[0], first)

        second = render.corpus_page(corpus, page=1, page_size=2)
        self.assertIn("Page 2 of 2", second)

        # Out of range clamps rather than rendering an empty document.
        self.assertIn("Page 2 of 2", render.corpus_page(corpus, page=99, page_size=2))
        self.assertIn("Page 1 of 2", render.corpus_page(corpus, page=-5, page_size=2))

    def test_index_page_lists_corpora(self) -> None:
        data_dir, corpora_dir = self.build()
        corpus = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        page = render.index_page([corpus])
        self.assertIn(CORPUS_ID, page)
        self.assertIn(f'href="/c/{CORPUS_ID}"', page)

    def test_empty_index_page(self) -> None:
        self.assertIn("No corpora acquired", render.index_page([]))


class TestNormalisationView(unittest.TestCase):
    def test_reports_the_steps_that_fired(self) -> None:
        lines = " ".join(render.normalisation_report("a soft­hyphen and\na break"))
        self.assertIn("format character", lines)
        self.assertIn("U+00AD", lines)
        self.assertIn("line break", lines)

    def test_reports_nothing_to_do(self) -> None:
        lines = render.normalisation_report("already normalised text")
        self.assertEqual(len(lines), 1)
        self.assertIn("already normalised", lines[0])

    def test_invisible_characters_are_made_visible(self) -> None:
        markup = render.visible("one\ntwo three­four")
        self.assertIn(render.PILCROW, markup, "the segmenter's line break is shown")
        self.assertIn(render.OPEN_BOX, markup, "the no-break space is shown")
        self.assertIn("U+00AD", markup, "the soft hyphen is named where it was removed")

    def test_visible_escapes_markup(self) -> None:
        self.assertNotIn("<b>", render.visible("a <b> tag"))
        self.assertIn("&lt;b&gt;", render.visible("a <b> tag"))

    def test_uses_the_contract_sets_rather_than_its_own(self) -> None:
        """Every character the contract removes is named by the view."""
        for character in normalise.FORMAT_CHARACTERS_REMOVED:
            self.assertIn(f"U+{ord(character):04X}", render.visible(f"a{character}b"))


class TestRouting(TempCorpus):
    def route(self, path: str, query=None, *, serve_local_only: bool = False, **kwargs):
        data_dir, corpora_dir = self.build(**kwargs)
        return server.route(
            path,
            query or {},
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            serve_local_only=serve_local_only,
        )

    def test_index(self) -> None:
        status, body = self.route("/")
        self.assertEqual(status, 200)
        self.assertIn(CORPUS_ID, body)

    def test_corpus_page(self) -> None:
        status, body = self.route(f"/c/{CORPUS_ID}")
        self.assertEqual(status, 200)
        self.assertIn(list(SEGMENTS)[0], body)

    def test_unknown_corpus_is_404(self) -> None:
        status, body = self.route("/c/testcorpus-0002-absent")
        self.assertEqual(status, 404)

    def test_unknown_path_is_404(self) -> None:
        self.assertEqual(self.route("/nope")[0], 404)
        self.assertEqual(self.route("/c/")[0], 404)

    def test_path_traversal_is_refused(self) -> None:
        status, _ = self.route("/c/../../etc/passwd")
        self.assertEqual(status, 404, "a corpus ID is one path segment")

    def test_bad_page_number_does_not_crash(self) -> None:
        status, _ = self.route(f"/c/{CORPUS_ID}", {"page": ["not-a-number"]})
        self.assertEqual(status, 200)

    def test_route_honours_the_licence_gate(self) -> None:
        status, body = self.route(f"/c/{CORPUS_ID}", license="local-only")
        self.assertEqual(status, 200)
        self.assertIn(staged.SERVE_LOCAL_ONLY_ENV, body)
        self.assertNotIn(normalise.normalise(SEGMENTS["TC 1.1"]), body)


class FakeAdapter:
    """Stands in for a registered adapter. Invented text only (ADR-0014)."""

    corpus_id = CORPUS_ID
    diagnostic = "TC 1.2"

    def __init__(self, segments: dict[str, str] | None = None) -> None:
        self._segments = SEGMENTS if segments is None else segments
        from catena.acquire.record import WorkFacts

        self.work = WorkFacts(**WORK)
        self.license_terms = "Invented terms."

    def fetch_plan(self):
        from catena.acquire.fetch import FetchPlan

        return FetchPlan(
            source_url="https://invented.example/source",
            archive_url="https://invented.example/archive",
        )

    def extract(self, raw: bytes) -> str:
        return raw.decode("utf-8")

    def segment(self, document: str):
        from catena.acquire.record import Segment

        for locator, text in self._segments.items():
            yield Segment(locator, text)


class VerifyCase(TempCorpus):
    """Blessing from the browser, with the adapter and the network both faked."""

    def setUp(self) -> None:
        self.adapter = FakeAdapter()
        patched = unittest.mock.patch.object(
            verify.corpora, "load", side_effect=self._load
        )
        patched.start()
        self.addCleanup(patched.stop)
        self.downloads = 0

    def _load(self, corpus_id: str):
        if corpus_id != CORPUS_ID:
            raise KeyError(f"unknown corpus {corpus_id!r}")
        return self.adapter

    def fake_download(self, url: str) -> bytes:
        self.downloads += 1
        return b"invented source document"

    def corpus(self, **kwargs) -> tuple[staged.Corpus, pathlib.Path, pathlib.Path]:
        data_dir, corpora_dir = self.build(**kwargs)
        return (
            staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir),
            data_dir,
            corpora_dir,
        )


class TestVerifyOffer(VerifyCase):
    def test_offered_for_an_unblessed_corpus(self) -> None:
        corpus, _, _ = self.corpus(bless=False)
        offer = verify.offer(corpus)

        self.assertEqual(offer.diagnostic, "TC 1.2")
        self.assertEqual(offer.text, normalise.normalise(SEGMENTS["TC 1.2"]))
        self.assertEqual(offer.content_hash, corpus.chunks[1].content_hash)

    def test_refused_for_a_blessed_corpus(self) -> None:
        corpus, _, _ = self.corpus(bless=True)
        with self.assertRaises(verify.NotVerifiable) as caught:
            verify.offer(corpus)
        self.assertIn("terminal", str(caught.exception))

    def test_refused_for_a_drifted_corpus(self) -> None:
        """Drift is where 'never bless past a mismatch' bites hardest."""
        corpus, _, _ = self.corpus(drift=True)
        with self.assertRaises(verify.NotVerifiable):
            verify.offer(corpus)

    def test_refused_when_the_committed_evidence_cannot_be_read(self) -> None:
        """Unreadable fingerprints leave the status at UNBLESSED, which this path accepts.

        Offering a bless there would invite someone to overwrite committed
        evidence nobody has managed to read.
        """
        corpus, _, _ = self.corpus(corrupt_fingerprints=True)
        self.assertEqual(corpus.fingerprint_status, staged.UNBLESSED)
        with self.assertRaises(verify.NotVerifiable) as caught:
            verify.offer(corpus)
        self.assertIn("cannot be read", str(caught.exception))

    def test_refused_when_the_diagnostic_is_not_staged(self) -> None:
        corpus, _, _ = self.corpus(bless=False)
        self.adapter.diagnostic = "TC 9.9"
        with self.assertRaises(verify.NotVerifiable) as caught:
            verify.offer(corpus)
        self.assertIn("not among", str(caught.exception))


class TestVerifyApply(VerifyCase):
    def apply(self, data_dir, corpora_dir, *, name="A Verifier", read_hash=None, **kwargs):
        if read_hash is None:
            read_hash = fingerprint(normalise.normalise(SEGMENTS["TC 1.2"]))
        return verify.apply(
            CORPUS_ID,
            name=name,
            read_hash=read_hash,
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            downloader=self.fake_download,
            **kwargs,
        )

    def test_blesses_and_writes_the_committed_evidence(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        manifest = self.apply(data_dir, corpora_dir)

        self.assertEqual(manifest.edition_check.verified_by, "A Verifier")
        self.assertEqual(manifest.edition_check.diagnostic, "TC 1.2")
        self.assertEqual(
            manifest.edition_check.expected_sha256,
            fingerprint(normalise.normalise(SEGMENTS["TC 1.2"])),
            "the manifest records the hash of the text, never the text (ADR-0021)",
        )
        self.assertTrue((corpora_dir / CORPUS_ID / mf.FILENAME).is_file())
        self.assertTrue((corpora_dir / CORPUS_ID / mf.FINGERPRINTS_FILENAME).is_file())

        reread = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        self.assertEqual(reread.fingerprint_status, staged.BLESSED)

    def test_manifest_carries_no_corpus_text(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        self.apply(data_dir, corpora_dir)
        written = (corpora_dir / CORPUS_ID / mf.FILENAME).read_text(encoding="utf-8")
        for text in SEGMENTS.values():
            self.assertNotIn(normalise.normalise(text), written)

    def test_refuses_an_empty_name(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        for name in ("", "   ", "\t"):
            with self.assertRaises(verify.NotVerifiable) as caught:
                self.apply(data_dir, corpora_dir, name=name)
            self.assertIn("name", str(caught.exception))
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists())

    def test_refuses_when_the_text_changed_since_it_was_read(self) -> None:
        """The condition a terminal gets for free and a form does not."""
        _, data_dir, corpora_dir = self.corpus(bless=False)
        with self.assertRaises(verify.NotVerifiable) as caught:
            self.apply(data_dir, corpora_dir, read_hash="b" * 64)

        self.assertIn("read the text again", str(caught.exception))
        self.assertFalse(
            (corpora_dir / CORPUS_ID / mf.FILENAME).exists(), "nothing written"
        )

    def test_refuses_a_malformed_hash_before_reaching_the_network(self) -> None:
        """The body is decoded with errors="replace", so U+FFFD arrives here.

        `secrets.compare_digest` raises on non-ASCII str, and the comparison is
        downstream of a re-fetch — so an unvalidated hash costs a network round
        trip and then crashes the handler instead of being refused.
        """
        _, data_dir, corpora_dir = self.corpus(bless=False)
        for read_hash in ("caf\ufffds", "", "A" * 64, "a" * 63, "z" * 64, "caf\u00e9"):
            with self.assertRaises(verify.NotVerifiable) as caught:
                self.apply(data_dir, corpora_dir, read_hash=read_hash)
            self.assertIn("sha256", str(caught.exception))
        self.assertEqual(self.downloads, 0, "refused before the fetch, not after it")
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists())

    def test_refuses_when_the_committed_manifest_cannot_be_read(self) -> None:
        """`mf.read` raises on a manifest it cannot parse. Blessing past that overwrites it."""
        _, data_dir, corpora_dir = self.corpus(corrupt_manifest=True)
        with self.assertRaises(verify.NotVerifiable) as caught:
            self.apply(data_dir, corpora_dir)
        self.assertIn("cannot be read", str(caught.exception))
        self.assertEqual(
            (corpora_dir / CORPUS_ID / mf.FILENAME).read_text(encoding="utf-8"),
            "corpus_id: [unclosed\n",
            "the unreadable manifest is left exactly as it was found",
        )

    def test_a_stale_hash_is_not_a_dead_end(self) -> None:
        """The refusal asks the reader to read the text again, so it has to stage it.

        An unblessed corpus carries no upstream digest, so every submission
        re-fetches. Leaving `stage/` on the previous run would mean the page went
        on showing the passage whose hash was just rejected, and every
        resubmission carried that same rejected hash — a permanent 409.
        """
        _, data_dir, corpora_dir = self.corpus(bless=False)
        stale = fingerprint(normalise.normalise(SEGMENTS["TC 1.2"]))

        # Upstream moves between the page being rendered and the form arriving.
        self.adapter._segments = dict(
            SEGMENTS, **{"TC 1.2": "A second section, revised upstream."}
        )

        with self.assertRaises(verify.NotVerifiable) as caught:
            self.apply(data_dir, corpora_dir, read_hash=stale)
        self.assertIn("read the text again", str(caught.exception))
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists(), "nothing written")

        reread = staged.load(CORPUS_ID, data_dir=data_dir, corpora_dir=corpora_dir)
        offer = verify.offer(reread)
        self.assertEqual(
            offer.text,
            normalise.normalise("A second section, revised upstream."),
            "the reload shows the passage that is upstream now",
        )
        self.assertNotEqual(offer.content_hash, stale)
        self.assertIsNotNone(
            reread.chunks[1].raw, "stage/ and segment/ are from the same run again"
        )

        manifest = self.apply(data_dir, corpora_dir, read_hash=offer.content_hash)
        self.assertEqual(manifest.edition_check.expected_sha256, offer.content_hash)

    def test_refuses_to_re_bless(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=True)
        before = (corpora_dir / CORPUS_ID / mf.FILENAME).read_text(encoding="utf-8")

        with self.assertRaises(verify.NotVerifiable) as caught:
            self.apply(data_dir, corpora_dir, name="Someone Else")

        self.assertIn("terminal", str(caught.exception))
        self.assertEqual(
            (corpora_dir / CORPUS_ID / mf.FILENAME).read_text(encoding="utf-8"),
            before,
            "an existing human verification is not replaced from a browser",
        )

    def test_refuses_a_corpus_with_no_adapter(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        self.adapter.corpus_id = "testcorpus-0004-unregistered"
        with self.assertRaises(verify.NotVerifiable) as caught:
            verify.apply(
                "testcorpus-0004-unregistered",
                name="A Verifier",
                read_hash="a" * 64,
                data_dir=data_dir,
                corpora_dir=corpora_dir,
            )
        self.assertIn("no registered adapter", str(caught.exception))


class TestBlessRouting(VerifyCase):
    TOKEN = "a-test-token"

    def post(self, data_dir, corpora_dir, form, *, token=TOKEN, path=None):
        return server.bless_route(
            path or f"/bless/{CORPUS_ID}",
            form,
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            serve_local_only=False,
            token=token,
            downloader=self.fake_download,
        )

    def good_form(self) -> dict[str, list[str]]:
        return {
            "token": [self.TOKEN],
            "name": ["A Verifier"],
            "read_sha256": [fingerprint(normalise.normalise(SEGMENTS["TC 1.2"]))],
        }

    def test_a_valid_submission_blesses_and_redirects(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        status, _, redirect = self.post(data_dir, corpora_dir, self.good_form())

        self.assertEqual(status, 303)
        self.assertEqual(redirect, f"/c/{CORPUS_ID}")
        self.assertTrue((corpora_dir / CORPUS_ID / mf.FILENAME).is_file())

    def test_a_missing_token_is_refused(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        form = self.good_form()
        del form["token"]
        status, _, _ = self.post(data_dir, corpora_dir, form)

        self.assertEqual(status, 403)
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists())

    def test_a_wrong_token_is_refused(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        form = dict(self.good_form(), token=["not-the-token"])
        status, _, _ = self.post(data_dir, corpora_dir, form)

        self.assertEqual(status, 403)
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists())

    def test_an_unset_server_token_refuses_everything(self) -> None:
        """An empty configured token must not make an empty submitted one valid."""
        _, data_dir, corpora_dir = self.corpus(bless=False)
        form = dict(self.good_form(), token=[""])
        status, _, _ = self.post(data_dir, corpora_dir, form, token="")

        self.assertEqual(status, 403)
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists())

    def test_a_stale_hash_re_renders_the_passage(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        form = dict(self.good_form(), read_sha256=["c" * 64])
        status, body, redirect = self.post(data_dir, corpora_dir, form)

        self.assertEqual(status, 409)
        self.assertIsNone(redirect)
        self.assertIn("read the text again", body)
        self.assertIn(render._e(normalise.normalise(SEGMENTS["TC 1.2"])), body)
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists())

    def test_a_non_ascii_token_is_refused_rather_than_raising(self) -> None:
        """`secrets.compare_digest` raises TypeError on non-ASCII str operands.

        The body is decoded with errors="replace", so a garbled or hostile
        submission reliably arrives holding U+FFFD — at the first check on the
        only write path, where the intended answer is a terse 403.
        """
        _, data_dir, corpora_dir = self.corpus(bless=False)
        for submitted in ("caf\u00e9s", "\ufffd" * 8, "t\u00f6ken"):
            form = dict(self.good_form(), token=[submitted])
            status, _, _ = self.post(data_dir, corpora_dir, form)
            self.assertEqual(status, 403, submitted)
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists())

    def test_a_non_ascii_hash_is_refused_rather_than_raising(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        form = dict(self.good_form(), read_sha256=["caf\u00e9" + "a" * 59])
        status, body, _ = self.post(data_dir, corpora_dir, form)

        self.assertEqual(status, 409)
        self.assertIn("sha256", body)
        self.assertEqual(self.downloads, 0)

    def test_unreadable_staged_output_answers_rather_than_crashing(self) -> None:
        """GET renders a 500 page for this; POST must not be the one that raises."""
        _, data_dir, corpora_dir = self.corpus(bless=False)
        write_text(
            data_dir / "acquire" / CORPUS_ID / "stage" / "records.jsonl", "{not json\n"
        )
        status, _, _ = self.post(data_dir, corpora_dir, self.good_form())
        self.assertEqual(status, 500)

    def test_withheld_text_cannot_be_blessed(self) -> None:
        """You cannot verify an edition you are not permitted to read."""
        _, data_dir, corpora_dir = self.corpus(bless=False, license="local-only")
        status, _, _ = self.post(data_dir, corpora_dir, self.good_form())

        self.assertEqual(status, 403)
        self.assertFalse((corpora_dir / CORPUS_ID / mf.FILENAME).exists())

    def test_path_traversal_is_refused(self) -> None:
        _, data_dir, corpora_dir = self.corpus(bless=False)
        status, _, _ = self.post(
            data_dir, corpora_dir, self.good_form(), path="/bless/../../etc/passwd"
        )
        self.assertEqual(status, 404)


class TestBodyDraining(unittest.TestCase):
    """`protocol_version` is HTTP/1.1, so an unread body desyncs the connection.

    No socket: the handler is instantiated without one and given the two
    attributes the drain touches, which is the whole of what it needs.
    """

    def handler(self, headers: dict[str, str], body: bytes, path: str = "/bless/x"):
        cls = server.make_handler(
            data_dir=pathlib.Path("/nonexistent"),
            corpora_dir=pathlib.Path("/nonexistent"),
            serve_local_only=False,
        )
        instance = cls.__new__(cls)
        instance.headers = headers
        instance.rfile = io.BytesIO(body)
        instance.close_connection = False
        instance.path = path
        return instance

    def test_the_body_is_drained_and_the_next_request_survives(self) -> None:
        instance = self.handler({"Content-Length": "5"}, b"helloGET / HTTP/1.1\r\n")
        instance._discard_body()

        self.assertEqual(
            instance.rfile.read(),
            b"GET / HTTP/1.1\r\n",
            "the next request line is what is left on the connection",
        )
        self.assertFalse(instance.close_connection)

    def test_an_oversized_or_unparseable_length_ends_the_connection(self) -> None:
        for headers in (
            {"Content-Length": str(server.MAX_FORM_BYTES + 1)},
            {"Content-Length": "not-a-number"},
            {},  # chunked, or no body at all: nothing to drain against
        ):
            instance = self.handler(headers, b"")
            instance._discard_body()
            if headers.get("Content-Length") is None:
                self.assertFalse(instance.close_connection, "an empty body is drained")
            else:
                self.assertTrue(instance.close_connection, headers)

    def test_an_early_refusal_drains_before_answering(self) -> None:
        """Every early return in do_POST, exercised through the real method."""
        for path, expected in (("/nope", 404), ("/bless/x", 403)):
            with self.subTest(path=path):
                instance = self.handler({"Content-Length": "5"}, b"tokenLEFTOVER", path=path)
                answered: list[int] = []
                instance._respond = (
                    lambda status, body, _out=answered, **kwargs: _out.append(status)
                )

                instance.do_POST()

                self.assertEqual(answered, [expected])
                self.assertEqual(instance.rfile.read(), b"LEFTOVER")


class TestOriginCheck(unittest.TestCase):
    def test_same_origin_is_accepted(self) -> None:
        for origin in ("http://127.0.0.1:8730", "http://localhost:8730"):
            self.assertTrue(
                server.origin_ok(origin, None, host="127.0.0.1", port=8730), origin
            )

    def test_cross_site_is_refused(self) -> None:
        for origin in (
            "http://evil.example",
            "https://127.0.0.1:8730",
            "http://127.0.0.1:9999",
            "null",
        ):
            self.assertFalse(
                server.origin_ok(origin, "cross-site", host="127.0.0.1", port=8730), origin
            )

    def test_absent_origin_needs_same_site_metadata(self) -> None:
        self.assertTrue(server.origin_ok(None, "same-origin", host="127.0.0.1", port=8730))
        for site in (None, "cross-site", "same-site"):
            self.assertFalse(server.origin_ok(None, site, host="127.0.0.1", port=8730), site)


class TestVerifyPanelMarkup(VerifyCase):
    def panel(self, **kwargs) -> str:
        corpus, _, _ = self.corpus(bless=False, **kwargs)
        return render.corpus_page(
            corpus, offer=verify.offer(corpus), token="tok-123"
        )

    def test_panel_shows_the_passage_and_carries_the_hash(self) -> None:
        page = self.panel()
        self.assertIn("Verify this edition", page)
        self.assertIn(render._e(normalise.normalise(SEGMENTS["TC 1.2"])), page)
        self.assertIn(
            f'value="{fingerprint(normalise.normalise(SEGMENTS["TC 1.2"]))}"', page
        )
        self.assertIn('value="tok-123"', page)
        self.assertIn(f'action="/bless/{CORPUS_ID}"', page)
        self.assertIn('method="post"', page)

    def test_panel_absent_without_an_offer(self) -> None:
        corpus, _, _ = self.corpus(bless=True)
        self.assertNotIn("Verify this edition", render.corpus_page(corpus))

    def test_panel_still_needs_no_javascript(self) -> None:
        self.assertNotIn("<script", self.panel().lower())

    def test_banner_does_not_send_you_to_the_terminal_past_the_panel(self) -> None:
        page = self.panel()
        self.assertIn("Read the edition diagnostic to verify it", page)
        self.assertNotIn("at a terminal", page)

    def test_banner_names_the_terminal_when_no_panel_is_offered(self) -> None:
        corpus, _, _ = self.corpus(bless=False)
        page = render.corpus_page(corpus)
        self.assertIn("at a terminal", page)
        self.assertIn(f"make bless CORPUS={CORPUS_ID}", page)

    def test_banner_gives_the_reason_rather_than_advice_that_cannot_work(self) -> None:
        """A corpus with staged output and no adapter cannot be blessed anywhere.

        `data/` is gitignored, so an acquisition survives a branch switch that
        takes its adapter away -- and the browser lists what is on disk. Sending
        the reader to `make bless` points them at the same wall with none of the
        explanation: it exits 64 with the very message being discarded.
        """
        unregistered = "testcorpus-0005-noadapter"
        data_dir, corpora_dir = self.build(corpus_id=unregistered, bless=False)
        status, body = server.route(
            f"/c/{unregistered}",
            {},
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            serve_local_only=False,
        )

        self.assertEqual(status, 200)
        self.assertIn("no registered adapter", body)
        self.assertNotIn("at a terminal", body)
        self.assertNotIn("make bless", body)

    def test_banner_gives_the_reason_when_the_diagnostic_is_not_staged(self) -> None:
        corpus, data_dir, corpora_dir = self.corpus(bless=False)
        self.adapter.diagnostic = "TC 9.9"
        status, body = server.route(
            f"/c/{CORPUS_ID}",
            {},
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            serve_local_only=False,
        )

        self.assertEqual(status, 200)
        self.assertIn("not among", body)
        self.assertNotIn("make bless", body)

    def test_a_withheld_corpus_still_names_the_terminal(self) -> None:
        """The licence gate stops the panel, not the bless. The CLI can still do it."""
        _, data_dir, corpora_dir = self.corpus(bless=False, license="local-only")
        status, body = server.route(
            f"/c/{CORPUS_ID}",
            {},
            data_dir=data_dir,
            corpora_dir=corpora_dir,
            serve_local_only=False,
        )

        self.assertEqual(status, 200)
        self.assertIn(f"make bless CORPUS={CORPUS_ID}", body)


if __name__ == "__main__":
    unittest.main()
