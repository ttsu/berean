"""The staging directory, read as ingestion needs it.

Acquisition ends at `<data>/acquire/<corpus-id>/stage/`: `records.jsonl` beside
a `work.json` carrying the work facts, the chunk count, and the normalisation
contract version. Ingestion reads exactly those two files. It never parses an
upstream format, never touches the network, and never opens `segment/` — that
is the browser's business, and it is what normalisation already discarded.

Nothing here knows what any corpus says. See ADR-0014.
"""

from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass

from catena.acquire.record import AcquisitionError, StagedRecord, WorkFacts, read_jsonl

#: The bind mounts acquisition writes and ingestion reads.
DATA_DIR_ENV = "CATENA_DATA_DIR"
CORPORA_DIR_ENV = "CATENA_CORPORA_DIR"

STAGE = "stage"
RECORDS = "records.jsonl"
WORK = "work.json"


@dataclass(frozen=True)
class StagedCorpus:
    """One corpus as staging holds it — the whole of ingestion's input."""

    corpus_id: str
    work: WorkFacts
    normalisation_version: int
    records: list[StagedRecord]


def data_dir(override: pathlib.Path | None = None) -> pathlib.Path:
    if override is not None:
        return override
    return pathlib.Path(os.environ.get(DATA_DIR_ENV, "/data"))


def corpora_dir(override: pathlib.Path | None = None) -> pathlib.Path:
    if override is not None:
        return override
    return pathlib.Path(os.environ.get(CORPORA_DIR_ENV, "/corpora"))


def stage_dir(corpus_id: str, *, data_dir: pathlib.Path) -> pathlib.Path:
    return data_dir / "acquire" / corpus_id / STAGE


def load(corpus_id: str, *, data_dir: pathlib.Path) -> StagedCorpus:
    """Read one staged corpus, refusing anything that is not whole."""
    out = stage_dir(corpus_id, data_dir=data_dir)
    work_path = out / WORK
    if not work_path.is_file():
        raise AcquisitionError(
            f"{corpus_id}: no staged output at {work_path}. Ingestion reads what "
            "acquisition staged and never re-acquires it itself — run "
            "`make provision-corpus` first."
        )

    declared = json.loads(work_path.read_text(encoding="utf-8"))
    if not isinstance(declared, dict) or "work" not in declared:
        raise AcquisitionError(f"{work_path}: not a staged work record")

    records = [
        StagedRecord(row["locator"], row["text"], row["content_hash"])
        for row in read_jsonl(out / RECORDS)
    ]

    # `work.json` and `records.jsonl` are written by the same step, so they
    # disagree only when one of them is half-written — and a truncated
    # `records.jsonl` read as complete becomes a plan that deletes every chunk
    # past the truncation.
    count = int(declared["chunk_count"])
    if count != len(records):
        raise AcquisitionError(
            f"{corpus_id}: work.json declares {count:,} chunks and records.jsonl holds "
            f"{len(records):,}. Staging is half-written; re-acquire it."
        )

    return StagedCorpus(
        corpus_id=corpus_id,
        work=WorkFacts.from_dict(declared["work"]),
        normalisation_version=int(declared["normalisation_version"]),
        records=records,
    )


def discover(*, data_dir: pathlib.Path) -> list[str]:
    """Every staged corpus ID, smallest first.

    Smallest first puts a spot-checkable system within minutes and leaves WEB —
    31,098 verses, 89% of the work and the least interesting to watch — as an
    unattended tail. An interrupted first run leaves the corpora a human wants
    to look at already finished.

    The count comes from `work.json` rather than from counting records, so
    ordering costs one small read per corpus rather than parsing every record
    of every corpus before any of them starts.
    """
    root = data_dir / "acquire"
    if not root.is_dir():
        return []

    sized = []
    for entry in sorted(root.iterdir()):
        work_path = entry / STAGE / WORK
        if not work_path.is_file():
            continue
        declared = json.loads(work_path.read_text(encoding="utf-8"))
        sized.append((int(declared["chunk_count"]), entry.name))
    return [corpus_id for _, corpus_id in sorted(sized)]
