"""Reading the acquisition seam back.

Acquisition's stages leave their output under `<data>/acquire/<corpus-id>/`
precisely so it can be re-run and inspected (ACQUISITION-DESIGN, "the seam and
the inspection surface"). This module is the reading half of that: it turns
those files into a `Corpus` a renderer can walk.

It reads `stage/` because that is the seam ingestion reads, so the viewer shows
what Task 5 will load rather than an intermediate nobody consumes. `segment/` is
read as well, for one reason: normalisation collapses the segmenter's newlines,
so once a record is staged its line structure is gone. That structure is where a
missed heading or a table flattened down the wrong axis shows up, and it is
invisible in every other surface.

The committed evidence under `<corpora>/<corpus-id>/` is an overlay and is
optional. A corpus that has been acquired but never blessed is a normal state --
it is the state the Westminster Confession is in as this is written -- and the
viewer's job is to say so, not to refuse.

Nothing here knows what any corpus says. See ADR-0014.
"""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass

from catena import normalise as normalisation
from catena.acquire import fingerprints as fp
from catena.acquire import manifest as mf
from catena.acquire.record import AcquisitionError, WorkFacts, read_jsonl

#: The same two bind mounts acquisition names, read here rather than written.
DATA_DIR_ENV = "CATENA_DATA_DIR"
CORPORA_DIR_ENV = "CATENA_CORPORA_DIR"

#: The deployer opt-in that governs whether `local-only` text may be served
#: (ADR-0017). The viewer is a serving surface like any other, so it reads the
#: same variable the gateway does rather than inventing a browse-only bypass.
SERVE_LOCAL_ONLY_ENV = "BEREAN_SERVE_LOCAL_ONLY"

STAGE = "stage"
SEGMENT = "segment"
RECORDS = "records.jsonl"
SEGMENTS = "segments.jsonl"
WORK = "work.json"

#: Fingerprint status for a corpus as a whole.
BLESSED = "blessed"
UNBLESSED = "unblessed"
DRIFTED = "drifted"


@dataclass(frozen=True)
class Chunk:
    """One staged record, with what is known about it.

    `text` is post-normalisation text -- the same rule `corpus.chunks.text`
    follows. `raw` is the pre-normalisation segment when `segment/` is readable
    *and* is from the same acquisition, and `None` when it is not; it exists to
    show what normalisation did, never to be served as an alternative reading
    text.

    `blessed` is `None` rather than `False` when the corpus carries no committed
    fingerprints. "Nobody has checked" and "the check failed" are different
    answers and the viewer must not render them the same way.
    """

    locator: str
    text: str
    content_hash: str
    raw: str | None
    blessed: bool | None

    @property
    def length(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class Corpus:
    """A staged corpus, with its provenance overlay when there is one.

    `missing` is the committed locators with no staged record at all. They carry
    no chunk and so cannot carry a flag, which is why they are held here: a
    section the segmenter stopped producing leaves every surviving chunk
    matching, and without this the corpus renders as blessed.

    `overlay_error` is why the committed evidence could not be read, when there
    is one. An unreadable overlay is not the same as an absent one and must not
    render as it.
    """

    corpus_id: str
    work: WorkFacts
    normalisation_version: int
    chunk_count: int
    chunks: list[Chunk]
    manifest: mf.Manifest | None
    fingerprint_status: str
    missing: list[str]
    overlay_error: str | None

    @property
    def drifted(self) -> list[Chunk]:
        return [chunk for chunk in self.chunks if chunk.blessed is False]

    @property
    def count_matches(self) -> bool:
        """Whether the staged record count matches what `work.json` declared."""
        return self.chunk_count == len(self.chunks)


def data_dir(override: pathlib.Path | None = None) -> pathlib.Path:
    if override is not None:
        return override
    return pathlib.Path(os.environ.get(DATA_DIR_ENV, "/data"))


def corpora_dir(override: pathlib.Path | None = None) -> pathlib.Path:
    if override is not None:
        return override
    return pathlib.Path(os.environ.get(CORPORA_DIR_ENV, "/corpora"))


def serve_local_only(environ: dict[str, str] | None = None) -> bool:
    """Whether the deployer has opted in to serving `local-only` text.

    Anything but an affirmative is a no. The default is deny, so nobody serves
    PCA text by accident (ADR-0017).
    """
    source = os.environ if environ is None else environ
    return source.get(SERVE_LOCAL_ONLY_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def discover(*, data_dir: pathlib.Path) -> list[str]:
    """Every corpus ID with staged output, sorted.

    Scans what was actually acquired rather than `CORPUS_IDS` (what has an
    adapter) or `<corpora>/` (what was blessed). Those three disagree routinely
    -- a corpus can have an adapter and no acquisition, or an acquisition and no
    blessing -- and showing what is on disk is the whole point of the tool.
    """
    root = data_dir / "acquire"
    if not root.is_dir():
        return []
    found = [
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and (entry / STAGE / WORK).is_file()
    ]
    return sorted(found)


def load(corpus_id: str, *, data_dir: pathlib.Path, corpora_dir: pathlib.Path) -> Corpus:
    """Read one staged corpus and its provenance overlay."""
    stage_dir = data_dir / "acquire" / corpus_id / STAGE
    work_path = stage_dir / WORK
    if not work_path.is_file():
        raise AcquisitionError(
            f"{corpus_id}: no staged output at {work_path}. Acquire it first: "
            f"`make bless CORPUS={corpus_id}` for a corpus that has never been "
            "blessed, `make provision-corpus` afterwards."
        )

    declared = _read_work(work_path)
    records = list(read_jsonl(stage_dir / RECORDS))
    raw_by_locator = _read_segments(data_dir / "acquire" / corpus_id / SEGMENT / SEGMENTS)

    committed_dir = corpora_dir / corpus_id
    manifest, manifest_problem = _read_manifest(committed_dir / mf.FILENAME)
    committed, fingerprints_problem = _read_fingerprints(
        committed_dir / mf.FINGERPRINTS_FILENAME
    )

    chunks = [
        Chunk(
            locator=record["locator"],
            text=record["text"],
            content_hash=record["content_hash"],
            raw=_raw_for(raw_by_locator, record),
            blessed=(
                None
                if committed is None
                else committed.get(record["locator"]) == record["content_hash"]
            ),
        )
        for record in records
    ]

    if committed is None:
        missing: list[str] = []
        status = UNBLESSED
    else:
        # The whole diff, not a per-chunk comparison. A locator the segmenter
        # stopped producing leaves nothing behind to mismatch, so walking the
        # staged records alone reports a swallowed section as clean -- and a
        # swallowed section is the failure this viewer exists to reveal.
        # `unexpected` needs no separate handling: a staged locator the committed
        # file does not carry is already a chunk whose `blessed` is False.
        diff = fp.compare(committed, {chunk.locator: chunk.content_hash for chunk in chunks})
        missing = diff.missing
        status = BLESSED if diff.clean else DRIFTED

    return Corpus(
        corpus_id=corpus_id,
        work=declared.work,
        normalisation_version=declared.normalisation_version,
        chunk_count=declared.chunk_count,
        chunks=chunks,
        manifest=manifest,
        fingerprint_status=status,
        missing=missing,
        overlay_error=_overlay_error(manifest_problem, fingerprints_problem),
    )


@dataclass(frozen=True)
class _Declared:
    work: WorkFacts
    normalisation_version: int
    chunk_count: int


def _read_work(path: pathlib.Path) -> _Declared:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "work" not in raw:
        raise AcquisitionError(f"{path}: not a staged work record")
    return _Declared(
        work=WorkFacts.from_dict(raw["work"]),
        normalisation_version=int(raw["normalisation_version"]),
        chunk_count=int(raw["chunk_count"]),
    )


def _read_segments(path: pathlib.Path) -> dict[str, str]:
    """Pre-normalisation text by locator, empty when the stage is absent.

    Absent is not an error: a `<data>` tree restored from elsewhere may carry
    `stage/` alone. The viewer degrades to normalised text rather than refusing
    to open the corpus.
    """
    if not path.is_file():
        return {}
    return {record["locator"]: record["text"] for record in read_jsonl(path)}


def _raw_for(raw_by_locator: dict[str, str], record: dict) -> str | None:
    """The pre-normalisation segment, but only when it is the same acquisition.

    `stage/` and `segment/` are written by different steps. `pipeline.acquire`
    rewrites `segment/segments.jsonl` on every run; only `write_stage` writes
    `stage/`. So a run that acquired without staging -- `--verify-only` -- leaves
    the two describing different fetches, and a normalisation panel reporting on
    text the reader is not looking at is worse than no panel at all.

    The test is the invariant the panel asserts rather than a run identifier the
    files do not carry: what is shown as "before" must normalise to what is
    shown as "after".
    """
    raw = raw_by_locator.get(record["locator"])
    if raw is None or normalisation.normalise(raw) != record["text"]:
        return None
    return raw


def _read_manifest(path: pathlib.Path) -> tuple[mf.Manifest | None, str | None]:
    """The committed manifest, or None and why it could not be read.

    `mf.read` raises on a manifest it cannot parse, which is right for
    acquisition -- verifying against a manifest nobody can read is not
    verification. Here it would take away the reader's only view of the text
    over a defect in an optional overlay, so it is caught. It is then *reported*,
    because a page that silently drops the provenance rows is indistinguishable
    from a corpus that was never blessed.
    """
    try:
        return mf.read(path), None
    except AcquisitionError as error:
        return None, f"The committed manifest cannot be read: {error}"


def _read_fingerprints(path: pathlib.Path) -> tuple[dict[str, str] | None, str | None]:
    """The committed fingerprints, or None and why they could not be read.

    The more dangerous of the two to swallow: with nothing to check against,
    every chunk falls back to "not checked" and the corpus reads as unblessed.
    Silence would turn a corrupt file into a downgrade nobody was told about.
    """
    try:
        return fp.read(path), None
    except AcquisitionError as error:
        return None, f"The committed fingerprints cannot be read: {error}"


def _overlay_error(*problems: str | None) -> str | None:
    """Both overlay problems in one line, or None when there are none."""
    reported = [problem for problem in problems if problem]
    return " ".join(reported) if reported else None


def text_withheld_reason(work: WorkFacts, *, serve_local_only: bool) -> str | None:
    """Why this corpus's text must not be rendered, or None when it may be.

    The same rule as verification check 4, applied to the same enum, because a
    viewer that rendered everything on disk would be a second serving surface
    with its own licence policy -- which is how the one in the gateway stops
    being the answer to "may this be shown".
    """
    if work.license == "refused":
        return (
            "This corpus is recorded as refused: examined, and rejected on its terms. "
            "It is never servable, under any configuration. The record is kept so the "
            "reason stays available the next time someone asks."
        )
    if work.license == "local-only" and not serve_local_only:
        return (
            "This corpus is licensed local-only: acquired lawfully for local use, with no "
            f"redistribution claim available. Set {SERVE_LOCAL_ONLY_ENV}=true to read it "
            "here. The default is deny, so nobody serves it by accident (ADR-0017)."
        )
    return None
