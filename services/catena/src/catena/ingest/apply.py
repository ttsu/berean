"""Executing a plan, in two phases, with the crash boundary between them.

**Phase one — text.** Upsert the `corpus.works` row, then apply every insert,
update and delete to `corpus.chunks` in a single transaction per corpus. Fast:
the entire Phase 1 corpus is 8.2 MB.

**Phase two — embeddings.** Embed the backlog in batches, one transaction per
batch into `corpus.chunk_embeddings`.

Once phase one commits, the database holds complete, correct, blessed text for
that corpus whether or not phase two ever runs. The schema already put the
boundary here: `corpus.chunk_metadata` inner-joins `corpus.chunk_embeddings`,
so a chunk with no embedding is a half-finished ingestion rather than a row
that view papers over — nothing half-ingested reaches the gateway's read
surface, and restart needs no cleanup step.
"""

from __future__ import annotations

from typing import Callable, ContextManager, Iterable, Mapping, Protocol, Sequence

from catena.acquire.record import StagedRecord, WorkFacts
from catena.ingest import embed as batching
from catena.ingest.embed import DEFAULT_BUDGET, Embedder, Pending
from catena.ingest.plan import ExistingChunk, Plan
from catena.ingest.source import StagedCorpus


class Store(Protocol):
    """The corpus tables, as ingestion writes them.

    One method per statement. The interesting sequencing — an update dropping
    the vector it invalidates, inside the same transaction — lives in `apply`
    below rather than inside a query, because it is invisible and needs to be
    read.
    """

    def transaction(self) -> ContextManager: ...

    def existing_chunks(
        self, corpus_id: str, embedding_model: str
    ) -> Mapping[str, ExistingChunk]: ...

    def upsert_work(self, corpus_id: str, work: WorkFacts) -> None: ...

    def insert_chunks(
        self, corpus_id: str, records: Sequence[StagedRecord], normalisation_version: int
    ) -> None: ...

    def update_chunks(
        self, corpus_id: str, records: Sequence[StagedRecord], normalisation_version: int
    ) -> list[int]:
        """Apply the updates and return the chunk IDs touched."""
        ...

    def delete_chunks(self, corpus_id: str, locators: Sequence[str]) -> None: ...

    def delete_embeddings(self, chunk_ids: Sequence[int]) -> None: ...

    def backlog(self, corpus_id: str, embedding_model: str) -> list[Pending]:
        """Chunks carrying no vector for this model. The resume query."""
        ...

    def write_embeddings(
        self, embedding_model: str, dim: int, vectors: Iterable[tuple[int, Sequence[float]]]
    ) -> None: ...


#: Where progress goes. The default discards it, so a caller that wants silence
#: does not have to arrange for it.
Report = Callable[[str], None]


def apply(
    corpus: StagedCorpus,
    plan: Plan,
    store: Store,
    embedder: Embedder,
    *,
    budget: int = DEFAULT_BUDGET,
    report: Report = lambda line: None,
) -> None:
    """Execute `plan` against `store`. Phase one, then phase two."""
    apply_text(corpus, plan, store)
    embed_backlog(corpus.corpus_id, store, embedder, budget=budget, report=report)


def apply_text(corpus: StagedCorpus, plan: Plan, store: Store) -> None:
    """Phase one: one transaction, after which the text is durable."""
    with store.transaction():
        store.upsert_work(corpus.corpus_id, corpus.work)

        if plan.deletes:
            # Cascades to the vectors, which is the one case the schema handles
            # by itself.
            store.delete_chunks(corpus.corpus_id, plan.deletes)

        if plan.updates:
            touched = store.update_chunks(
                corpus.corpus_id, plan.updates, corpus.normalisation_version
            )
            # Deleting a chunk cascades to its embeddings. **Updating one does
            # not**, and nothing in the schema notices. Left in place, the old
            # vector makes the chunk retrieved for what it used to say and
            # quoted for what it now says — and verification passes, because
            # check 2 matches the quote against `corpus.chunks.text`, which is
            # the new text. Dropping them here returns the chunk to the backlog.
            store.delete_embeddings(touched)

        if plan.inserts:
            store.insert_chunks(
                corpus.corpus_id, plan.inserts, corpus.normalisation_version
            )


def embed_backlog(
    corpus_id: str,
    store: Store,
    embedder: Embedder,
    *,
    budget: int = DEFAULT_BUDGET,
    report: Report = lambda line: None,
) -> int:
    """Phase two: embed what carries no vector, one transaction per batch.

    Returns the number of chunks embedded. The backlog is read once from the
    database rather than derived from the plan: the anti-join is the record of
    what has been done, and it is the only record that cannot disagree with
    what has been done.
    """
    backlog = store.backlog(corpus_id, embedder.name)
    if not backlog:
        return 0

    done = 0
    total = len(backlog)
    for batch in batching.batches(backlog, embedder, budget=budget):
        vectors = embedder.embed([item.text for item in batch])
        if len(vectors) != len(batch):
            raise ValueError(
                f"{embedder.name} returned {len(vectors)} vectors for {len(batch)} chunks"
            )
        # One transaction per batch: the commit granularity is what bounds what
        # a kill destroys, and it is why the batching is ours rather than
        # `encode()`'s.
        with store.transaction():
            store.write_embeddings(
                embedder.name,
                embedder.dim,
                zip((item.chunk_id for item in batch), vectors),
            )
        done += len(batch)
        report(f"  {corpus_id}: {done:,}/{total:,} embedded")
    return done
