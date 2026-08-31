# Architecture Decision Records

One file per decision, numbered, immutable once accepted. To change a decision, write a new ADR
that supersedes the old one and update the old one's status — do not edit history.

The **Alternatives rejected** section is the point of the document. A decision without its
rejected alternatives is just a note, and six months later nobody remembers why the obvious
option was not taken.

Use [0000-template.md](0000-template.md).

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-go-is-the-trust-boundary.md) | Go is the trust boundary, Python is the model layer | Accepted |
| [0002](0002-one-grpc-call-per-turn.md) | Exactly one gRPC call per user turn | Accepted |
| [0003](0003-trace-streaming-not-token-streaming.md) | Stream trace events, not tokens | Accepted |
| [0004](0004-split-retrieval-from-display.md) | Split Bible retrieval from Bible display | Accepted |
| [0005](0005-postgres-pgvector-single-datastore.md) | Postgres + pgvector as the single datastore | Accepted |
| [0006](0006-bge-m3-as-a-tested-default.md) | BGE-M3 as a tested default, re-decided at Phase 2 | Accepted (provisional) |
| [0007](0007-apache-2-0.md) | Apache-2.0, and what it forbids depending on | Accepted |
| [0008](0008-original-languages-as-a-tool.md) | Hebrew/Greek as a deterministic tool | Accepted (amended by 0012) |
| [0009](0009-langfuse-over-langsmith.md) | Langfuse (self-hosted) for tracing and evals | Accepted |
| [0010](0010-regeneration-retry-exception.md) | A verification failure permits one regeneration call | Accepted |
| [0011](0011-scripture-tier-is-profile-configurable.md) | Scripture's tier is profile-configurable, defaulting to binding | Accepted |
| [0012](0012-drop-tyndale-house-gnt.md) | Drop Tyndale House GNT; SBLGNT and OSHB are the base texts | Accepted |
| [0013](0013-go-cli-in-phase-1.md) | Phase 1 includes a minimal Go CLI, not a Python-only one | Accepted |
| [0014](0014-no-corpus-text-in-the-repository.md) | No corpus text in the repository, from any source | Accepted |
