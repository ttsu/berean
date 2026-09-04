"""fetch → extract → segment → normalise → verify → stage.

Only the first three stages know anything about a particular corpus, and they
are the whole of the adapter interface. Everything after `segment` has one
implementation, because none of it cares what the text says.

`extract` and `segment` are separate because they fail differently. Extraction
fails on the shape of a source — wrong element, a JavaScript-rendered page, a
PDF's column order — and its failure is visible as garbage text. Segmentation
fails on the structure of a document — a missed heading, a catechism answer
split from its question — and its failure is visible as a wrong locator set.
Fusing them produces one function that can fail either way and reports both the
same.

**An adapter cannot override normalisation.** `catena.normalise` is applied
here, not by the adapter: a per-corpus normalisation is precisely the drift the
contract exists to prevent, and an interface that permits it invites it.

Each stage writes its output under `<data>/acquire/<corpus-id>/<stage>/` and
reads its predecessor's file rather than receiving a value in memory, which is
what makes a stage independently re-runnable and inspectable. Only `fetch`
consults its output as a cache; the pure stages recompute every run. Reusing a
cached extraction would let an adapter fix land while verification still ran
against the output of the code it replaced — silently, and in the one place
this project can least afford it.
"""

from __future__ import annotations

import json
import pathlib
import sys

import yaml
from dataclasses import dataclass
from typing import Iterator, Protocol, TextIO

from catena import normalise as normalisation
from catena.acquire import fingerprints as fp
from catena.acquire import manifest as mf
from catena.acquire.fetch import Downloader, Fetched, FetchPlan, download, fetch
from catena.acquire.record import (
    AcquisitionError,
    Segment,
    StagedRecord,
    WorkFacts,
    read_jsonl,
    stage,
    write_jsonl,
    write_text,
)

STAGES = ("fetch", "extract", "segment", "normalise", "stage")

DOCUMENT = "document.txt"
SEGMENTS = "segments.jsonl"
RECORDS = "records.jsonl"
WORK = "work.json"


class Adapter(Protocol):
    """Everything corpus-specific, and nothing else.

    Implemented as a module under `catena.acquire.corpora`, named for the
    corpus ID with hyphens replaced by underscores.
    """

    corpus_id: str
    work: WorkFacts
    #: The terms verbatim as found, with the URL they were found at. A licence
    #: is evidence, not a label.
    license_terms: str
    #: The locator whose text distinguishes this edition from the one it is
    #: most likely to be confused with. The text itself lives in the manifest,
    #: written at bless from what the human actually read — it has one home,
    #: and it is the committed record rather than a constant in code.
    diagnostic: str

    def fetch_plan(self) -> FetchPlan: ...

    def extract(self, raw: bytes) -> str: ...

    def segment(self, document: str) -> Iterator[Segment]: ...


@dataclass(frozen=True)
class Acquired:
    corpus_id: str
    work: WorkFacts
    fetched: Fetched
    records: list[StagedRecord]

    @property
    def fingerprints(self) -> dict[str, str]:
        return {record.locator: record.content_hash for record in self.records}

    def record_at(self, locator: str) -> StagedRecord | None:
        for record in self.records:
            if record.locator == locator:
                return record
        return None


@dataclass(frozen=True)
class VerifyReport:
    """What verify found, reported in full rather than one class at a time."""

    corpus_id: str
    diff: fp.Diff
    committed_chunk_count: int
    acquired_chunk_count: int
    edition_ok: bool
    edition_detail: str
    upstream_drifted: bool
    committed_upstream_sha256: str
    acquired_upstream_sha256: str

    @property
    def chunk_count_ok(self) -> bool:
        return self.committed_chunk_count == self.acquired_chunk_count

    @property
    def ok(self) -> bool:
        return self.diff.clean and self.chunk_count_ok and self.edition_ok

    def lines(self) -> list[str]:
        out = [f"{self.corpus_id}: {'OK' if self.ok else 'FAIL'}"]
        out.extend(self.diff.summary())
        out.append(
            f"  chunk_count: committed {self.committed_chunk_count}, "
            f"acquired {self.acquired_chunk_count}"
            + ("" if self.chunk_count_ok else "  ← mismatch")
        )
        out.append(f"  edition check: {self.edition_detail}")
        if self.upstream_drifted:
            # Reported, never fatal. The confession does not change when the
            # publisher's footer year does, and `make corpus-verify` that failed
            # every January would be a check nobody trusted. The fingerprints
            # are what say whether the text moved.
            out.append(
                f"  upstream bytes changed: {self.committed_upstream_sha256[:12]}… → "
                f"{self.acquired_upstream_sha256[:12]}… (not a failure on its own; "
                "the fingerprints above are the authority)"
            )
        return out


def corpus_dir(data_dir: pathlib.Path, corpus_id: str) -> pathlib.Path:
    return data_dir / "acquire" / corpus_id


def acquire(
    adapter: Adapter,
    *,
    data_dir: pathlib.Path,
    manifest: mf.Manifest | None,
    from_file: pathlib.Path | None = None,
    refetch: bool = False,
    downloader: Downloader = download,
) -> Acquired:
    """Run fetch → extract → segment → normalise and return what was acquired.

    Staging is deliberately not part of this: `--verify-only` stops here, which
    is what lets drift detection run without disturbing records an ingestion
    may be reading.
    """
    root = data_dir / "acquire"
    work = corpus_dir(data_dir, adapter.corpus_id)

    fetched = fetch(
        root,
        adapter.corpus_id,
        adapter.fetch_plan(),
        expected_digest=manifest.upstream_sha256 if manifest else None,
        refetch=refetch,
        from_file=from_file,
        downloader=downloader,
    )

    document = adapter.extract(fetched.raw)
    if not document.strip():
        raise AcquisitionError(
            f"{adapter.corpus_id}: extraction produced no text from "
            f"{len(fetched.raw)} bytes — the source's shape changed"
        )
    write_text(work / "extract" / DOCUMENT, document)

    segments = list(adapter.segment(_read_document(work / "extract" / DOCUMENT)))
    if not segments:
        raise AcquisitionError(f"{adapter.corpus_id}: segmentation produced no segments")
    write_jsonl(work / "segment" / SEGMENTS, segments)

    records = _normalise(adapter.corpus_id, work / "segment" / SEGMENTS)
    write_jsonl(work / "normalise" / RECORDS, records)

    return Acquired(adapter.corpus_id, adapter.work, fetched, records)


def _read_document(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalise(corpus_id: str, segments_path: pathlib.Path) -> list[StagedRecord]:
    records: list[StagedRecord] = []
    seen: set[str] = set()
    for row in read_jsonl(segments_path):
        locator = row["locator"]
        if locator in seen:
            raise AcquisitionError(
                f"{corpus_id}: locator {locator!r} segmented twice — a locator resolves "
                "to exactly one chunk, and the database enforces it as a constraint "
                "(verification check 1)"
            )
        seen.add(locator)
        records.append(stage(locator, normalisation.normalise(row["text"])))
    return records


def write_stage(acquired: Acquired, *, data_dir: pathlib.Path) -> pathlib.Path:
    """Write the records ingestion reads, and the work facts beside them.

    Ingestion never parses an upstream format and never touches the network, so
    the work-level metadata has to arrive here rather than be re-derived from a
    source Task 5 is forbidden to open.
    """
    out = corpus_dir(data_dir, acquired.corpus_id) / "stage"
    write_jsonl(out / RECORDS, acquired.records)
    write_text(
        out / WORK,
        json.dumps(
            {
                "corpus_id": acquired.corpus_id,
                "normalisation_version": normalisation.NORMALISATION_VERSION,
                "chunk_count": len(acquired.records),
                "work": acquired.work.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    return out


def verify(
    adapter: Adapter,
    acquired: Acquired,
    manifest: mf.Manifest,
    committed: dict[str, str],
) -> VerifyReport:
    """Compare what was acquired against what was blessed."""
    _require_contract_version(manifest)
    _require_manifest_matches_adapter(adapter, manifest)

    diff = fp.compare(committed, acquired.fingerprints)
    edition_ok, edition_detail = _check_edition(manifest, acquired)

    return VerifyReport(
        corpus_id=adapter.corpus_id,
        diff=diff,
        committed_chunk_count=manifest.chunk_count,
        acquired_chunk_count=len(acquired.records),
        edition_ok=edition_ok,
        edition_detail=edition_detail,
        upstream_drifted=manifest.upstream_sha256 != acquired.fetched.digest,
        committed_upstream_sha256=manifest.upstream_sha256,
        acquired_upstream_sha256=acquired.fetched.digest,
    )


def _require_contract_version(manifest: mf.Manifest) -> None:
    if manifest.normalisation_version != normalisation.NORMALISATION_VERSION:
        raise AcquisitionError(
            f"{manifest.corpus_id}: blessed under normalisation contract "
            f"v{manifest.normalisation_version}, this code implements "
            f"v{normalisation.NORMALISATION_VERSION}. The contract moved, so every "
            "fingerprint in the file is a hash of text this code no longer produces. "
            "The corpus needs re-blessing; verifying against it would mean nothing."
        )


def _require_manifest_matches_adapter(adapter: Adapter, manifest: mf.Manifest) -> None:
    plan = adapter.fetch_plan()
    for name, committed, current in (
        ("source_url", manifest.source_url, plan.source_url),
        ("archive_url", manifest.archive_url, plan.archive_url),
        ("license", manifest.license, adapter.work.license),
        ("license_terms", manifest.license_terms, adapter.license_terms),
        ("attribution", manifest.attribution, adapter.work.attribution),
        ("diagnostic", manifest.edition_check.diagnostic, adapter.diagnostic),
    ):
        if committed != current:
            raise AcquisitionError(
                f"{manifest.corpus_id}: the manifest and the adapter disagree about "
                f"{name}. The manifest is the blessed record and the adapter is code; "
                "one of them was changed without the other, and re-blessing is what "
                "reconciles them."
            )


def _check_edition(manifest: mf.Manifest, acquired: Acquired) -> tuple[bool, str]:
    check = manifest.edition_check
    staged = acquired.record_at(check.diagnostic)
    if staged is None:
        return False, (
            f"{check.diagnostic} was not acquired at all — the diagnostic locator is gone"
        )
    if staged.content_hash != check.expected_sha256:
        return False, (
            f"{check.diagnostic} does not hash to what {check.verified_by} verified on "
            f"{check.verified}. This is the check that catches a silently swapped "
            f"edition. Read what was acquired — `catena acquire --corpus "
            f"{manifest.corpus_id} --show-diagnostic` — before doing anything else."
        )
    return True, (
        f"{check.diagnostic} matches what {check.verified_by} verified on {check.verified}"
    )


def show_diagnostic(adapter: Adapter, acquired: Acquired, *, stream: TextIO = sys.stderr) -> str:
    """Print the diagnostic locator's normalised text, and return it.

    This is what replaces quoting the text into the manifest (ADR-0021). A
    checkbox records that someone once believed the edition was right; the
    quoted text let the next person check, and so does a command that prints it
    on demand — without the repository distributing anything.
    """
    staged = acquired.record_at(adapter.diagnostic)
    if staged is None:
        raise AcquisitionError(
            f"{adapter.corpus_id}: the edition diagnostic {adapter.diagnostic!r} is not among "
            f"the {len(acquired.records)} locators acquired. Nothing can be verified by hand "
            "until segmentation produces it."
        )
    print(f"{adapter.corpus_id} — edition diagnostic {staged.locator}", file=stream)
    print(f"  sha256 {staged.content_hash}", file=stream)
    print(file=stream)
    print(staged.text, file=stream)
    print(file=stream)
    return staged.text


def bless(
    adapter: Adapter,
    acquired: Acquired,
    *,
    corpora_dir: pathlib.Path,
    retrieved: str,
    verified: str,
    existing: dict[str, str] | None,
    stream: TextIO = sys.stderr,
    prompt=input,
    interactive: bool | None = None,
) -> mf.Manifest:
    """Record a human's edition verification. The one step nothing automates.

    Blessing discards a previous human verification, so it is the one action in
    this process that cannot be reached past. It aborts when stdin is not a
    terminal and no flag overrides that: an unattended CI run cannot bless.
    """
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        raise AcquisitionError(
            "--bless needs a terminal. Blessing records that a human read the edition "
            "diagnostic and approved it, and there is no flag that says a human did "
            "something they did not do. Run it interactively."
        )

    staged = acquired.record_at(adapter.diagnostic)
    if staged is None:
        raise AcquisitionError(
            f"{adapter.corpus_id}: the edition diagnostic {adapter.diagnostic!r} is not among "
            f"the {len(acquired.records)} locators acquired. Nothing can be blessed until "
            "segmentation produces it."
        )

    say = lambda line="": print(line, file=stream)  # noqa: E731
    say()
    say(f"Blessing {adapter.corpus_id}")
    say(f"  source        {acquired.fetched.origin}")
    say(f"  upstream      sha256 {acquired.fetched.digest}")
    say(f"  chunks        {len(acquired.records)}")
    say(f"  contract      normalisation v{normalisation.NORMALISATION_VERSION}")
    say(f"  licence       {adapter.work.license}")
    say()
    say("Read this in full. It is the edition verification, and the manifest will record")
    say("only its hash — the text is never committed (ADR-0021).")
    say()
    show_diagnostic(adapter, acquired, stream=stream)

    if existing is not None:
        diff = fp.compare(existing, acquired.fingerprints)
        say(f"{adapter.corpus_id} has been blessed before. Against the committed fingerprints:")
        for line in diff.summary():
            say(line)
        say()
        say(
            "Re-blessing replaces a verification someone already made. Never bless your "
            "way past a mismatch you have not understood."
        )
        confirmation = f"re-bless {adapter.corpus_id}"
        typed = prompt(f"Type '{confirmation}' to continue: ").strip()
        if typed != confirmation:
            raise AcquisitionError("re-bless not confirmed; nothing written")

    name = prompt(
        "Read the text above. If it is the edition this corpus claims to be, "
        "type your name to record the verification: "
    ).strip()
    if not name:
        raise AcquisitionError(
            "no verifier name given; nothing written. A name passed as a flag would "
            "record that someone typed a name, not that anyone read the text."
        )

    plan = adapter.fetch_plan()
    manifest = mf.Manifest(
        corpus_id=adapter.corpus_id,
        source_url=plan.source_url,
        archive_url=plan.archive_url,
        retrieved=retrieved,
        upstream_sha256=acquired.fetched.digest,
        license=adapter.work.license,
        license_terms=adapter.license_terms,
        attribution=adapter.work.attribution,
        normalisation_version=normalisation.NORMALISATION_VERSION,
        chunk_count=len(acquired.records),
        edition_check=mf.EditionCheck(
            diagnostic=adapter.diagnostic,
            expected_sha256=staged.content_hash,
            verified_by=name,
            verified=verified,
        ),
    )

    # Validate before writing, not on the next read. Every rule in `mf.parse`
    # lives on the read path, so an adapter with an empty `attribution` or a
    # corpus ID that is not edition-specific would otherwise produce a committed
    # manifest that every later run rejects — repairable only by another bless,
    # which needs the human who has just walked away.
    mf.parse(
        yaml.safe_load(manifest.to_yaml()),
        where=f"the manifest being blessed for {adapter.corpus_id}",
    )

    out = corpora_dir / adapter.corpus_id
    # Both temp-then-rename. An interrupted bless must not leave a half-written
    # fingerprint file that the next run silently verifies against.
    mf.write(out / mf.FILENAME, manifest)
    fp.write(out / mf.FINGERPRINTS_FILENAME, acquired.fingerprints)
    say()
    say(f"wrote {out / mf.FILENAME}")
    say(f"wrote {out / mf.FINGERPRINTS_FILENAME}")
    return manifest
