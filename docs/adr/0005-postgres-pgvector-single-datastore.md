# ADR-0005: Postgres + pgvector as the single datastore

- **Status:** Accepted
- **Phase:** 1

## Context

The system needs vector search, lexical search, relational corpus metadata, session state, trace
persistence, and a job queue for ingestion. The default modern answer is a purpose-built vector
DB plus a search engine plus a queue plus a relational database.

The project's acceptance test is `docker compose up` giving a working system with no external
accounts.

## Decision

**One Postgres**, containerised, with pgvector. Lexical search from Postgres FTS or ParadeDB
`pg_search`. Ingestion queue is a Postgres table.

Two clients with disjoint write scope: Python writes corpus tables, Go writes session and trace
tables.

## Alternatives rejected

- **Qdrant / Weaviate / Pinecone.** Better native hybrid, but a second datastore, a second
  operational surface, and no transactional consistency with corpus metadata. Revisit only if
  native hybrid out of the box proves necessary in practice.
- **SQS or any managed queue.** Breaks the acceptance test and adds a datastore for a table.
- **pgvector on RDS.** Breaks cloud-agnosticism.

## Consequences

Boring, transactional, portable to any host. Vector search performance will eventually be the
constraint that forces a revisit; that is a Phase 3+ concern with a real corpus, and should be
driven by measurement rather than anticipation.
