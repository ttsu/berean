"""The corpus browser, over an invented corpus.

ADR-0014 bars corpus text from fixtures, so every fixture here is invented and
the real corpora are never opened. That is not a workaround: a viewer whose
suite needed the Westminster Confession on disk could only run on a machine that
had already acquired it, which is the opposite of what `make check` is for.

No test binds a socket. `route` is separated from the request handler precisely
so the routing can be exercised without one.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from catena import normalise
from catena.acquire import fingerprints as fp
from catena.acquire import manifest as mf
from catena.acquire.record import AcquisitionError, fingerprint, write_jsonl, write_text
from catena.browse import render, server, staged

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
) -> tuple[pathlib.Path, pathlib.Path]:
    """Lay out a staged corpus on disk, and optionally its committed evidence."""
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

    write_text(
        acquire / "stage" / "records.jsonl",
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in records),
    )
    work = dict(WORK, license=license)
    write_text(
        acquire / "stage" / "work.json",
        json.dumps(
            {
                "corpus_id": corpus_id,
                "normalisation_version": normalise.NORMALISATION_VERSION,
                "chunk_count": len(records),
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


if __name__ == "__main__":
    unittest.main()
