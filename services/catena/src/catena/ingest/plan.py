"""The three-way diff between staged records and the corpus tables.

Pure. No database, no model, no filesystem — every interesting decision lives
here, and it is testable with a few invented records.

`corpus.chunks` is UNIQUE on `(corpus_id, locator)` and ingestion is idempotent
on `content_hash`. Those are different keys, and every action falls out of the
difference: **the locator says which chunk this is, the hash says what it
currently says.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from catena.acquire import fingerprints as fp
from catena.acquire.fingerprints import SAMPLE, sort_key
from catena.acquire.record import StagedRecord, fingerprint
from catena.ingest import IngestionError
from catena.ingest.embed import Embedder
from catena.normalise import NORMALISATION_VERSION


@dataclass(frozen=True)
class ExistingChunk:
    """What the database already holds for one locator."""

    id: int
    content_hash: str
    normalisation_version: int
    has_embedding: bool


@dataclass(frozen=True)
class Plan:
    """What `--apply` will do, and what a dry run prints."""

    corpus_id: str
    inserts: list[StagedRecord] = field(default_factory=list)
    updates: list[StagedRecord] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    #: Unchanged locators carrying no vector for the active model. A killed run
    #: leaves these behind, and so does a fresh model — the anti-join that finds
    #: them is the entire resumption mechanism, and it reads the database's own
    #: contents rather than a ledger that could disagree with them.
    unembedded: list[str] = field(default_factory=list)
    #: `(stored, staged)` when every existing row was hashed under a different
    #: normalisation contract than the staged records were. None otherwise.
    normalisation_change: tuple[int, int] | None = None

    @property
    def embedding_backlog(self) -> int:
        """Chunks that will carry no vector once phase one commits.

        An update counts: the vector it had describes text the chunk no longer
        carries, so phase one drops it and phase two earns it back.
        """
        return len(self.inserts) + len(self.updates) + len(self.unembedded)

    @property
    def writes(self) -> int:
        return len(self.inserts) + len(self.updates) + len(self.deletes)

    @property
    def converged(self) -> bool:
        """The database already agrees with staging. Nothing to do."""
        return self.writes == 0 and self.embedding_backlog == 0

    def lines(self) -> list[str]:
        """The dry run's output, which is also the progress report.

        A confirmation whose content never changes stops being read. This one
        moves every time it is run, which is what keeps `--apply` from becoming
        a flag typed without looking.
        """
        out = [
            f"{self.corpus_id}: {len(self.inserts):,} insert, {len(self.updates):,} update, "
            f"{len(self.deletes):,} delete, "
            f"{self.embedding_backlog:,} embeddings remaining"
        ]
        if self.normalisation_change is not None:
            stored, staged = self.normalisation_change
            # One line, not one per chunk. Every hash in the corpus was computed
            # under different rules, so the diff correctly reports every chunk
            # as an update — and enumerating them buries whatever else changed.
            out.append(
                f"  every chunk re-hashed: normalisation contract "
                f"v{stored} → v{staged} ({len(self.updates):,} chunks)"
            )
        # Deletion is the destructive direction, so it is the one the report
        # names. A bounded sample: a corpus whose every locator moved would
        # otherwise print thousands of lines, and the first ten say the same
        # thing.
        for locator in self.deletes[:SAMPLE]:
            out.append(f"  delete {locator}")
        if len(self.deletes) > SAMPLE:
            out.append(f"  … and {len(self.deletes) - SAMPLE:,} more deletes")
        return out


def diff(
    corpus_id: str,
    staged: Sequence[StagedRecord],
    existing: Mapping[str, ExistingChunk],
    *,
    normalisation_version: int = NORMALISATION_VERSION,
) -> Plan:
    inserts, updates, unchanged, unembedded = [], [], [], []
    for record in sorted(staged, key=lambda r: sort_key(r.locator)):
        row = existing.get(record.locator)
        if row is None:
            inserts.append(record)
        elif row.content_hash != record.content_hash:
            updates.append(record)
        else:
            unchanged.append(record.locator)
            if not row.has_embedding:
                unembedded.append(record.locator)

    staged_locators = {record.locator for record in staged}
    deletes = sorted(existing.keys() - staged_locators, key=sort_key)

    return Plan(
        corpus_id=corpus_id,
        inserts=inserts,
        updates=updates,
        deletes=deletes,
        unchanged=unchanged,
        unembedded=unembedded,
        normalisation_change=_contract_change(existing, normalisation_version),
    )


def _contract_change(
    existing: Mapping[str, ExistingChunk], staged_version: int
) -> tuple[int, int] | None:
    """The stored contract version, when every row disagrees with the staged one.

    Every row, not some: a corpus mid-migration has both, and calling that a
    contract change would explain away real drift. `corpus.chunks` stores the
    version precisely so this is a lookup instead of an investigation.
    """
    if not existing:
        return None
    stored = {row.normalisation_version for row in existing.values()}
    if len(stored) != 1:
        return None
    (version,) = stored
    return None if version == staged_version else (version, staged_version)


def check_token_limit(
    corpus_id: str, staged: Sequence[StagedRecord], embedder: Embedder
) -> None:
    """Refuse the corpus if any chunk exceeds the model's context window.

    Not a warning. A truncated embedding is a chunk that silently is not what
    the index says it is: it is retrieved on its opening fraction and quoted
    from its whole text, and verification passes, because check 2 matches
    against `corpus.chunks.text` rather than against the vector. The project
    does not have a category for that.

    This makes ingestion a check on acquisition's chunking, which is where the
    defect actually lives — the fix is always to re-chunk on a smaller
    structural boundary, never to truncate here.

    Counts, locators and the limit; never the text (ADR-0014).
    """
    counts = embedder.count_tokens([record.text for record in staged])
    over = [
        (record.locator, count)
        for record, count in zip(staged, counts)
        if count > embedder.max_tokens
    ]
    if not over:
        return
    listed = ", ".join(f"{locator} ({count:,} tokens)" for locator, count in over[:SAMPLE])
    if len(over) > SAMPLE:
        listed += f", … and {len(over) - SAMPLE:,} more"
    raise IngestionError(
        f"{corpus_id}: {len(over):,} of {len(staged):,} chunks exceed {embedder.name}'s "
        f"window of {embedder.max_tokens:,} tokens: {listed}. The encoder would truncate "
        "and return a vector, so the chunk would be retrieved on its opening fraction "
        "and quoted from its whole text — and verification would pass. Re-chunk the "
        "corpus on a smaller structural boundary and re-bless it."
    )


def check_fingerprints(
    corpus_id: str,
    staged: Sequence[StagedRecord],
    committed: Mapping[str, str] | None,
) -> None:
    """Re-hash staging and diff it against `corpora/<id>/fingerprints.txt`.

    The hash each record carries is not trusted — recomputing is what makes
    this a check rather than a comparison of a number against itself. It costs
    under a second across the whole Phase 1 corpus, so it runs on every
    invocation rather than only on insert.

    All three classes refuse. `mismatched` and `unexpected` are staging holding
    something nobody blessed. `missing` is subtler and refuses for a sharper
    reason: left to the diff it becomes a *delete* of a blessed chunk, which is
    the BCO's truncated bless executed against the database.

    Counts and locators only; never text.
    """
    if committed is None:
        raise IngestionError(
            f"{corpus_id}: never blessed. Acquisition permits a corpus to stage while "
            "recording that its edition was never verified; ingestion does not. Staging "
            "is allowed to hold work in progress and the database is not — read it and "
            f"bless it: `make browse`, or `make bless CORPUS={corpus_id}`."
        )

    recomputed = {record.locator: fingerprint(record.text) for record in staged}
    # Named `report` rather than `diff`: this module's own `diff` is the
    # three-way plan, and shadowing it here would make the two read as one.
    report = fp.compare(committed, recomputed)
    if report.clean:
        return
    detail = "\n".join(report.summary())
    raise IngestionError(
        f"{corpus_id}: staging disagrees with the committed fingerprints.\n{detail}\n"
        "  The fingerprints are what replace committing the text, so this is the check "
        "that says whether staging is the blessed corpus. Re-acquire "
        f"(`make provision-corpus`); re-bless only once you understand what moved."
    )
