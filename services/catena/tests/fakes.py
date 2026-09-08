"""Test doubles shared by the ingestion suites.

The embedder sits behind an interface (ADR-0006, which requires it for
swappability anyway), so a fake returning deterministic vectors exercises the
whole apply path without loading 2.3 GB of BGE-M3.

Not named `test_*`, so `make test-catena` does not run it as a suite.
"""

from __future__ import annotations

from typing import Sequence


class FakeEmbedder:
    """Deterministic vectors, and a tokeniser that counts whitespace words.

    The word count is not BGE-M3's tokenisation and does not pretend to be. It
    is monotonic in length, which is all the batching and the over-limit refusal
    actually depend on.
    """

    def __init__(self, *, dim: int = 1024, max_tokens: int = 8192) -> None:
        self.name = "fake-embedder"
        self.dim = dim
        self.max_tokens = max_tokens
        #: Every batch handed to `embed`, in order. Batching asserts on this.
        self.batches: list[list[str]] = []
        #: Raise from `embed` once this many texts have been embedded, to stand
        #: in for the kill that the resumability test needs.
        self.die_after: int | None = None
        self.embedded = 0

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        return [len(text.split()) for text in texts]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        vectors = []
        for text in texts:
            if self.die_after is not None and self.embedded >= self.die_after:
                raise KeyboardInterrupt("killed mid-embed")
            self.embedded += 1
            # Deterministic and distinct per text, so a vector written for the
            # wrong chunk is visible rather than plausible.
            seed = (len(text) % 97) / 100.0
            vectors.append([seed] * self.dim)
        return vectors


class Violation(Exception):
    """What the fake store raises where Postgres would raise."""


class FakeStore:
    """An in-memory stand-in for the corpus tables.

    It enforces the constraints the migration enforces — the
    `(corpus_id, locator)` unique key, the `(chunk_id, embedding_model)` primary
    key, and the cascade from `corpus.chunks` to `corpus.chunk_embeddings` — and
    it is atomic per transaction. A fake that absorbed a duplicate insert
    silently would make the resumability assertions vacuous, which is the one
    thing this double must not do.

    It stands in for the SQL, not for Postgres. The SQL itself is covered by the
    live-database target, on the `make test-schema` precedent.
    """

    def __init__(self) -> None:
        self.works: dict[str, object] = {}
        #: chunk_id -> {corpus_id, locator, text, content_hash, normalisation_version}
        self.chunks: dict[int, dict] = {}
        #: A list, not a dict: a duplicate must be visible rather than absorbed.
        self.embeddings: list[dict] = []
        self._next_id = 1
        self._depth = 0
        self._snapshot: tuple | None = None
        #: Every committed transaction, for asserting the crash boundary.
        self.commits = 0

    # -- transactions ------------------------------------------------------

    def transaction(self):
        return _Transaction(self)

    def _begin(self) -> None:
        if self._depth == 0:
            self._snapshot = (
                dict(self.works),
                {cid: dict(row) for cid, row in self.chunks.items()},
                [dict(row) for row in self.embeddings],
                self._next_id,
            )
        self._depth += 1

    def _commit(self) -> None:
        self._depth -= 1
        if self._depth == 0:
            self._snapshot = None
            self.commits += 1

    def _rollback(self) -> None:
        self._depth -= 1
        if self._depth == 0 and self._snapshot is not None:
            self.works, self.chunks, self.embeddings, self._next_id = self._snapshot
            self._snapshot = None

    # -- reads -------------------------------------------------------------

    def existing_chunks(self, corpus_id: str, embedding_model: str) -> dict:
        from catena.ingest.plan import ExistingChunk

        embedded = {
            row["chunk_id"]
            for row in self.embeddings
            if row["embedding_model"] == embedding_model
        }
        return {
            row["locator"]: ExistingChunk(
                id=chunk_id,
                content_hash=row["content_hash"],
                normalisation_version=row["normalisation_version"],
                has_embedding=chunk_id in embedded,
            )
            for chunk_id, row in self.chunks.items()
            if row["corpus_id"] == corpus_id
        }

    def backlog(self, corpus_id: str, embedding_model: str) -> list:
        """The resume query: chunks with no vector for the active model."""
        from catena.ingest.embed import Pending

        embedded = {
            row["chunk_id"]
            for row in self.embeddings
            if row["embedding_model"] == embedding_model
        }
        return [
            Pending(chunk_id, row["text"])
            for chunk_id, row in sorted(self.chunks.items())
            if row["corpus_id"] == corpus_id and chunk_id not in embedded
        ]

    # -- writes ------------------------------------------------------------

    def upsert_work(self, corpus_id: str, work) -> None:
        self.works[corpus_id] = work

    def insert_chunks(self, corpus_id: str, records, normalisation_version: int) -> None:
        taken = {
            row["locator"] for row in self.chunks.values() if row["corpus_id"] == corpus_id
        }
        for record in records:
            if record.locator in taken:
                raise Violation(
                    f"chunks_corpus_locator_unique: ({corpus_id}, {record.locator})"
                )
            taken.add(record.locator)
            self.chunks[self._next_id] = {
                "corpus_id": corpus_id,
                "locator": record.locator,
                "text": record.text,
                "content_hash": record.content_hash,
                "normalisation_version": normalisation_version,
            }
            self._next_id += 1

    def update_chunks(self, corpus_id: str, records, normalisation_version: int) -> list[int]:
        by_locator = {
            row["locator"]: chunk_id
            for chunk_id, row in self.chunks.items()
            if row["corpus_id"] == corpus_id
        }
        touched = []
        for record in records:
            chunk_id = by_locator[record.locator]
            self.chunks[chunk_id].update(
                text=record.text,
                content_hash=record.content_hash,
                normalisation_version=normalisation_version,
            )
            touched.append(chunk_id)
        return touched

    def delete_chunks(self, corpus_id: str, locators) -> None:
        wanted = set(locators)
        doomed = [
            chunk_id
            for chunk_id, row in self.chunks.items()
            if row["corpus_id"] == corpus_id and row["locator"] in wanted
        ]
        for chunk_id in doomed:
            del self.chunks[chunk_id]
        # ON DELETE CASCADE.
        self.embeddings = [
            row for row in self.embeddings if row["chunk_id"] not in set(doomed)
        ]

    def delete_embeddings(self, chunk_ids) -> None:
        doomed = set(chunk_ids)
        self.embeddings = [row for row in self.embeddings if row["chunk_id"] not in doomed]

    def write_embeddings(self, embedding_model: str, dim: int, vectors) -> None:
        held = {
            (row["chunk_id"], row["embedding_model"])
            for row in self.embeddings
        }
        for chunk_id, vector in vectors:
            key = (chunk_id, embedding_model)
            if key in held:
                raise Violation(f"chunk_embeddings_pkey: {key}")
            if len(vector) != dim:
                raise Violation(
                    f"chunk_embeddings_dim_matches_vector: {len(vector)} != {dim}"
                )
            held.add(key)
            self.embeddings.append(
                {
                    "chunk_id": chunk_id,
                    "embedding_model": embedding_model,
                    "dim": dim,
                    "embedding": list(vector),
                }
            )

    # -- assertions the suites make ---------------------------------------

    def vectors_for(self, corpus_id: str, locator: str) -> list[dict]:
        chunk_id = next(
            cid
            for cid, row in self.chunks.items()
            if row["corpus_id"] == corpus_id and row["locator"] == locator
        )
        return [row for row in self.embeddings if row["chunk_id"] == chunk_id]


class _Transaction:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def __enter__(self):
        self.store._begin()
        return self.store

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.store._commit()
        else:
            self.store._rollback()
        return False
