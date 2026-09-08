"""The embedder interface, and the batching that bounds what a crash destroys.

ADR-0006 requires the embedder be swappable, and that interface is what lets
the whole apply path be tested against a fake rather than against 2.3 GB of
BGE-M3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Protocol, Sequence


class Embedder(Protocol):
    """What ingestion needs of an embedding model, and nothing more."""

    #: Written to `corpus.chunk_embeddings.embedding_model`, and the predicate
    #: the resume query and retrieval both filter on.
    name: str
    #: Written to `corpus.chunk_embeddings.dim`, which has to be the width
    #: actually stored rather than the width the caller believed it stored.
    dim: int
    #: The model's own context window. A longer chunk does not fail — the
    #: encoder truncates and returns a vector, and nothing downstream can tell.
    max_tokens: int

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        """Token counts under this model's own tokeniser, never an estimate."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in the order given."""
        ...


#: Padded tokens per batch. A tunable, measured on the reference machine rather
#: than asserted here: the ceiling is the 16 GB host floor with Ollama holding
#: Qwen3-8B resident, and attention cost grows with the square of sequence
#: length, so the safe budget is lower for long chunks than a token count alone
#: suggests. At 16k, roughly 470 median WEB verses or 39 median *Institutes*
#: paragraphs.
DEFAULT_BUDGET = 16_384


@dataclass(frozen=True)
class Pending:
    """One chunk awaiting a vector — what the resume query returns."""

    chunk_id: int
    text: str


def batches(
    backlog: Sequence[Pending],
    embedder: Embedder,
    *,
    budget: int = DEFAULT_BUDGET,
) -> Iterator[list[Pending]]:
    """Length-sorted batches, each filled to `budget` padded tokens.

    The budget is tokens rather than chunks because a transformer pads every
    sequence in a batch to the longest one in it. A fixed chunk count makes
    memory, time per batch, and the amount of work a crash destroys all depend
    on which corpus the run happened to be in; a token budget holds all three
    flat while the batch size floats.

    The sorting is ours because the commit granularity is ours.
    `sentence-transformers`' `encode()` sorts internally and returns only when
    the whole input is done, so handing it a 31,098-chunk backlog buys efficient
    batching and zero commit granularity — a kill at 95% loses everything.

    Batches therefore complete out of `id` order, and that is safe: the resume
    query's anti-join asks only which chunks lack a vector, so any completion
    order resumes correctly.
    """
    if not backlog:
        return

    counts = dict(zip(
        (p.chunk_id for p in backlog),
        embedder.count_tokens([p.text for p in backlog]),
    ))
    ordered = sorted(backlog, key=lambda p: (counts[p.chunk_id], p.chunk_id))

    batch: list[Pending] = []
    for item in ordered:
        # Ascending, so this item's own count is the padded width of the batch
        # it would join — every earlier member is shorter and pads up to it.
        padded = (len(batch) + 1) * counts[item.chunk_id]
        if batch and padded > budget:
            yield batch
            batch = []
        batch.append(item)
    if batch:
        yield batch
