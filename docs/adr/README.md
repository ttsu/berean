# Architecture Decision Records

One file per decision, numbered, **immutable once merged to `main`**. To change a decision after
that, write a new ADR that supersedes the old one and update the old one's status — do not edit
history.

Merge is the line because it is a fact anyone can check, and "accepted" is not: it is a word the
author types, so it cannot distinguish a decision the project has lived with from a draft finished
ten minutes ago. Before merge, an ADR is a proposal and ordinary editing applies — fix the typo,
reword the decision, renumber if you must. After merge it is the record, and the only way to change
it is another ADR.

The distinction that matters is between a **superseded decision** and an **error**. A decision that
genuinely changed keeps both documents: ADR-0010 says in as many words that everything ADR-0002
rejects still stands, and it cannot be read without the ADR it amends. An error — a wrong list, a
stale reference, a sentence contradicted elsewhere in the same file — is not history and is not
worth preserving. Before merge, correct it. After merge, annotate it, and accept that the cost of
the bright line is the occasional wrong sentence carrying a note.

**From ADR-0015 onward**, every ADR MUST list the documents it changes, under **Documents
updated**. The most common defect in this repository is a decision that lands in the specs and
leaves a stale copy of the old rule in the file an implementer reads first. That is a review
problem, not a discipline problem, and the list is what makes it reviewable.

ADRs 0001–0014 predate the requirement and are exempt. Reconstructing their propagation lists after
the fact would mean inferring, from a diff, what each decision was meant to touch — and a plausible
list nobody verified is worse in the record than an honest cutoff, because it reads as evidence.
Anyone tracing what an early ADR changed should search for its number instead.

The **Alternatives rejected** section is the point of the document. A decision without its
rejected alternatives is just a note, and six months later nobody remembers why the obvious
option was not taken.

Use [0000-template.md](0000-template.md).

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-go-is-the-trust-boundary.md) | Go is the trust boundary, Python is the model layer | Accepted |
| [0002](0002-one-grpc-call-per-turn.md) | Exactly one gRPC call per user turn | Accepted (amended by 0010) |
| [0003](0003-trace-streaming-not-token-streaming.md) | Stream trace events, not tokens | Accepted |
| [0004](0004-split-retrieval-from-display.md) | Split Bible retrieval from Bible display | Accepted |
| [0005](0005-postgres-pgvector-single-datastore.md) | Postgres + pgvector as the single datastore | Accepted |
| [0006](0006-bge-m3-as-a-tested-default.md) | BGE-M3 as a tested default, re-decided at Phase 2 | Accepted (provisional) |
| [0007](0007-apache-2-0.md) | Apache-2.0, and what it forbids depending on | Accepted |
| [0008](0008-original-languages-as-a-tool.md) | Hebrew/Greek as a deterministic tool | Accepted (amended by 0012) |
| [0009](0009-langfuse-over-langsmith.md) | Langfuse (self-hosted) for tracing and evals | Accepted |
| [0010](0010-regeneration-retry-exception.md) | A verification failure permits one regeneration call | Accepted |
| [0011](0011-scripture-tier-is-profile-configurable.md) | Scripture's tier is profile-configurable, defaulting to binding | Accepted (check 3 restated by 0016) |
| [0012](0012-drop-tyndale-house-gnt.md) | Drop Tyndale House GNT; SBLGNT and OSHB are the base texts | Accepted |
| [0013](0013-go-cli-in-phase-1.md) | Phase 1 includes a minimal Go CLI, not a Python-only one | Accepted |
| [0014](0014-no-corpus-text-in-the-repository.md) | No corpus text in the repository, from any source | Accepted |
| [0015](0015-contested-loci-cross-the-boundary.md) | Contested loci cross the boundary; profile identity does not | Accepted |
| [0016](0016-affirmative-claims-are-a-slot.md) | Affirmative claims are a slot, not a category | Accepted |
