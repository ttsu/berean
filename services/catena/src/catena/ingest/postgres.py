"""The corpus tables over psycopg. One method per statement.

Everything is schema-qualified, including the `extensions.vector` cast: the
migration runs with `search_path=migration` and nothing in this project relies
on a path.

This module holds no policy. Which chunks are inserted, which are updated, and
that an update drops the vector it invalidates are decided in `apply.py`, where
they can be read; here they are statements. The sequencing is covered by the
unit suite against a fake store, and the SQL by the live-database target, on the
`make test-schema` precedent.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterable, Iterator, Mapping, Sequence

from catena.acquire.record import StagedRecord, WorkFacts
from catena.ingest import IngestionError
from catena.ingest.embed import Pending
from catena.ingest.plan import ExistingChunk

DATABASE_URL_ENV = "CATENA_DATABASE_URL"


def connect(url: str | None = None) -> "PostgresStore":
    """Open the connection ingestion writes through."""
    dsn = url or os.environ.get(DATABASE_URL_ENV)
    if not dsn:
        raise IngestionError(
            f"{DATABASE_URL_ENV} is unset. Ingestion writes the corpus tables, so it "
            "needs the database compose provides — run it through `make ingest`."
        )
    try:
        import psycopg
    except ModuleNotFoundError as error:  # pragma: no cover - a broken image
        raise IngestionError(
            "psycopg is not installed. Ingestion runs in the catena image, which "
            "installs it from the lockfile — run it through `make ingest`."
        ) from error

    # **Autocommit on, deliberately, and it is what makes the writes durable.**
    #
    # With psycopg's default of autocommit off, the first statement on the
    # connection opens an implicit transaction. Ingestion's first statement is a
    # read -- `existing_chunks`, which the plan needs -- so by the time
    # `transaction()` is entered there is already a transaction in progress, and
    # psycopg makes the block a SAVEPOINT rather than the outermost one. Exiting
    # it releases the savepoint and commits nothing; the connection is left
    # INTRANS and the server rolls the whole run back when the process exits.
    #
    # The failure is silent and total: every row is visible to the session that
    # wrote it, so phase two finds its backlog, embeds it, and reports success
    # over rows no other connection will ever see. With autocommit on, each
    # `transaction()` is a real BEGIN/COMMIT and a bare read holds nothing open.
    return PostgresStore(psycopg.connect(dsn, autocommit=True))


class PostgresStore:
    def __init__(self, connection) -> None:
        self._connection = connection

    @contextlib.contextmanager
    def transaction(self) -> Iterator["PostgresStore"]:
        with self._connection.transaction():
            yield self

    def close(self) -> None:
        self._connection.close()

    # -- reads -------------------------------------------------------------

    def existing_chunks(
        self, corpus_id: str, embedding_model: str
    ) -> Mapping[str, ExistingChunk]:
        """Every chunk this corpus holds, and whether it carries a vector.

        The `embedding_model` predicate sits in the join rather than in the
        WHERE clause: on the right-hand side of a LEFT JOIN it filters the
        vectors, and in the WHERE clause it would filter away the very rows —
        those with no vector — that the caller is asking about.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.locator, c.id, c.content_hash, c.normalisation_version,
                       (e.chunk_id IS NOT NULL) AS has_embedding
                  FROM corpus.chunks c
                  LEFT JOIN corpus.chunk_embeddings e
                    ON e.chunk_id = c.id AND e.embedding_model = %s
                 WHERE c.corpus_id = %s
                """,
                (embedding_model, corpus_id),
            )
            return {
                locator: ExistingChunk(
                    id=chunk_id,
                    content_hash=content_hash,
                    normalisation_version=version,
                    has_embedding=has_embedding,
                )
                for locator, chunk_id, content_hash, version, has_embedding in cursor
            }

    def backlog(self, corpus_id: str, embedding_model: str) -> list[Pending]:
        """The resume query. The entire resumption mechanism.

        No progress file, no checkpoint table, no run ledger — nothing to leave
        stale and nothing to reconcile after a hard kill. The database's own
        contents are the record of what has been done, which is the only record
        that cannot disagree with what has been done.
        """
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, c.text
                  FROM corpus.chunks c
                  LEFT JOIN corpus.chunk_embeddings e
                    ON e.chunk_id = c.id AND e.embedding_model = %s
                 WHERE c.corpus_id = %s AND e.chunk_id IS NULL
                 ORDER BY c.id
                """,
                (embedding_model, corpus_id),
            )
            return [Pending(chunk_id, text) for chunk_id, text in cursor]

    # -- writes ------------------------------------------------------------

    def upsert_work(self, corpus_id: str, work: WorkFacts) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.works
                    (corpus_id, work, author, era, language, source_language,
                     text_form, edition, license, attribution)
                VALUES (%s, %s, %s, %s, %s, %s,
                        %s::corpus.text_form, %s, %s::corpus.license, %s)
                ON CONFLICT (corpus_id) DO UPDATE SET
                    work = EXCLUDED.work,
                    author = EXCLUDED.author,
                    era = EXCLUDED.era,
                    language = EXCLUDED.language,
                    source_language = EXCLUDED.source_language,
                    text_form = EXCLUDED.text_form,
                    edition = EXCLUDED.edition,
                    license = EXCLUDED.license,
                    attribution = EXCLUDED.attribution
                """,
                (
                    corpus_id, work.work, work.author, work.era, work.language,
                    work.source_language, work.text_form, work.edition,
                    work.license, work.attribution,
                ),
            )

    def insert_chunks(
        self, corpus_id: str, records: Sequence[StagedRecord], normalisation_version: int
    ) -> None:
        if not records:
            return
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.chunks
                    (corpus_id, locator, text, content_hash, normalisation_version)
                SELECT %s, v.locator, v.text, v.content_hash, %s
                  FROM unnest(%s::text[], %s::text[], %s::text[])
                       AS v(locator, text, content_hash)
                """,
                (
                    corpus_id,
                    normalisation_version,
                    [r.locator for r in records],
                    [r.text for r in records],
                    [r.content_hash for r in records],
                ),
            )

    def update_chunks(
        self, corpus_id: str, records: Sequence[StagedRecord], normalisation_version: int
    ) -> list[int]:
        if not records:
            return []
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE corpus.chunks AS c
                   SET text = v.text,
                       content_hash = v.content_hash,
                       normalisation_version = %s
                  FROM unnest(%s::text[], %s::text[], %s::text[])
                       AS v(locator, text, content_hash)
                 WHERE c.corpus_id = %s AND c.locator = v.locator
                RETURNING c.id
                """,
                (
                    normalisation_version,
                    [r.locator for r in records],
                    [r.text for r in records],
                    [r.content_hash for r in records],
                    corpus_id,
                ),
            )
            return [row[0] for row in cursor]

    def delete_chunks(self, corpus_id: str, locators: Sequence[str]) -> None:
        if not locators:
            return
        with self._connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM corpus.chunks WHERE corpus_id = %s AND locator = ANY(%s)",
                (corpus_id, list(locators)),
            )

    def delete_embeddings(self, chunk_ids: Sequence[int]) -> None:
        if not chunk_ids:
            return
        with self._connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM corpus.chunk_embeddings WHERE chunk_id = ANY(%s)",
                (list(chunk_ids),),
            )

    def write_embeddings(
        self,
        embedding_model: str,
        dim: int,
        vectors: Iterable[tuple[int, Sequence[float]]],
    ) -> None:
        pairs = list(vectors)
        if not pairs:
            return
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO corpus.chunk_embeddings (chunk_id, embedding_model, dim, embedding)
                SELECT v.chunk_id, %s, %s, v.embedding::extensions.vector
                  FROM unnest(%s::bigint[], %s::text[]) AS v(chunk_id, embedding)
                """,
                (
                    embedding_model,
                    dim,
                    [chunk_id for chunk_id, _ in pairs],
                    [_literal(vector) for _, vector in pairs],
                ),
            )


def _literal(vector: Sequence[float]) -> str:
    """pgvector's text input form.

    Written by hand rather than through pgvector's adapter, which would be a
    dependency for one string. `repr` of a Python float round-trips exactly, and
    the values arrive as float32 from the encoder, so nothing is lost.
    """
    return "[" + ",".join(repr(float(component)) for component in vector) + "]"
