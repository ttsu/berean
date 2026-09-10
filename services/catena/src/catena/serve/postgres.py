"""The corpus tables, read. One method per statement, no policy.

The mirror of `catena.ingest.postgres`, and the same division: which candidates
survive and which are pinned is decided in `retrieval.py` where it can be read;
here there are only statements. The sequencing is covered by the unit suite
against a fake store, the SQL by `make test-catena-db`.

Three things about these queries are not incidental.

**`embedding_model` is constrained on every one.** `chunk_embeddings` holds a
row per model so a re-index can write new vectors beside the old ones, and there
is a single HNSW index spanning them. Without the predicate the index spans two
vector spaces and a re-index window silently trades recall.

**`hnsw.iterative_scan` is set per transaction.** It defaults to `off`, and HNSW
post-filters: with a corpus filter, a plain scan can return fewer than `top_k`
rows having found `ef_search` candidates that mostly failed the filter. Then
`top_k` would quietly mean "up to top_k, depending on which corpora you asked
for" — and Phase 2 cannot attribute a retrieval change to a number that meant
something different per profile. `strict_order` keeps the ordering exact.

**Connections are per request, and closed.** A long-lived server holding one
connection has to handle its death; opening one per request costs a few
milliseconds against a generation measured in tens of seconds, and it cannot go
stale. Boring, and one Postgres (CLAUDE.md).
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator, Sequence

from catena.serve import ServeError
from catena.serve.retrieval import Hit
from catena.vectors import literal as vector_literal

DATABASE_URL_ENV = "CATENA_DATABASE_URL"

#: `strict_order` rather than `relaxed_order`: the trace records a score per
#: candidate and the selection drops the lowest, so an ordering that is only
#: approximately by distance would make both subtly wrong.
ITERATIVE_SCAN = "strict_order"

#: Raised from pgvector's default of 40 because the filter is applied after the
#: index scan. At Phase 1 corpus size the cost is negligible and the failure it
#: prevents — a short result set that looks like a thin corpus — is not.
EF_SEARCH = 200


def connect(url: str | None = None) -> "CorpusReader":
    dsn = url or os.environ.get(DATABASE_URL_ENV)
    if not dsn:
        raise ServeError(
            f"{DATABASE_URL_ENV} is unset. Retrieval reads the corpus tables, so it "
            "needs the database compose provides — run the service through `make dev`."
        )
    try:
        import psycopg
    except ModuleNotFoundError as error:  # pragma: no cover - a broken image
        raise ServeError(
            "psycopg is not installed. The service runs in the catena image, which "
            "installs it from the lockfile."
        ) from error
    return CorpusReader(psycopg.connect(dsn, autocommit=True))


@contextlib.contextmanager
def reader(url: str | None = None) -> Iterator["CorpusReader"]:
    """One connection for one request, closed however the request ends."""
    store = connect(url)
    try:
        yield store
    finally:
        store.close()


class CorpusReader:
    def __init__(self, connection) -> None:
        self._connection = connection

    def close(self) -> None:
        self._connection.close()

    def search(
        self,
        vector: Sequence[float],
        corpus_ids: Sequence[str],
        limit: int,
        embedding_model: str,
    ) -> list[Hit]:
        """Dense-only top-k over the corpora in the filter spec.

        No reranking, no BM25, no query rewriting. Phase 2 measures this and
        Phase 3 has to beat it, so making it better here would destroy the
        measurement that justifies Phase 3 (TECHNICAL-SPEC).
        """
        if not corpus_ids or limit <= 0:
            return []
        query = vector_literal(vector)
        with self._connection.transaction(), self._connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL hnsw.iterative_scan = '{ITERATIVE_SCAN}'")
            cursor.execute(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}")
            cursor.execute(
                """
                SELECT c.id, c.corpus_id, c.locator, c.text, w.work,
                       1 - (e.embedding <=> %s::extensions.vector) AS score
                  FROM corpus.chunk_embeddings e
                  JOIN corpus.chunks c ON c.id = e.chunk_id
                  JOIN corpus.works w USING (corpus_id)
                 WHERE e.embedding_model = %s
                   AND c.corpus_id = ANY(%s)
                 ORDER BY e.embedding <=> %s::extensions.vector
                 LIMIT %s
                """,
                (query, embedding_model, list(corpus_ids), query, limit),
            )
            return [_hit(row) for row in cursor]

    def by_locator(
        self,
        corpus_id: str,
        locator: str,
        vector: Sequence[float],
        embedding_model: str,
    ) -> Hit | None:
        """One chunk by its citation reference, carrying its similarity to the query.

        A pointer resolves to exactly one chunk — `(corpus_id, locator)` is
        unique by constraint — so this is a lookup rather than a search. The
        score is computed anyway because the trace records it, and a pinned
        candidate with an invented score would make the audit log lie.
        """
        query = vector_literal(vector)
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, c.corpus_id, c.locator, c.text, w.work,
                       1 - (e.embedding <=> %s::extensions.vector) AS score
                  FROM corpus.chunks c
                  JOIN corpus.works w USING (corpus_id)
                  JOIN corpus.chunk_embeddings e
                    ON e.chunk_id = c.id AND e.embedding_model = %s
                 WHERE c.corpus_id = %s AND c.locator = %s
                """,
                (query, embedding_model, corpus_id, locator),
            )
            row = cursor.fetchone()
            return _hit(row) if row else None


def _hit(row) -> Hit:
    chunk_id, corpus_id, locator, text, work, score = row
    return Hit(
        chunk_id=chunk_id, corpus_id=corpus_id, locator=locator,
        text=text, work=work, score=float(score),
    )
