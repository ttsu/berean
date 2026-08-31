# ADR-0013: Phase 1 includes a minimal Go CLI, not a Python-only one

- **Status:** Accepted
- **Date:** 2026-08-30
- **Phase:** 1 — blocks Task 1; cheap now, structural after Task 5

## Context

The roadmap describes Phase 1 as "naive RAG, CLI," which reads as Python-only: ingestion,
retrieval, and generation are all Python, so a Python CLI would keep the whole phase in one
language and one process.

But the phase's stated goal is to prove citations verify end to end, and ADR-0001 puts verification
in Go as the trust boundary. A Python-only Phase 1 either proves something other than what the
phase is for, or builds verification twice.

## Decision

**A minimal Go CLI binary.** It resolves the profile, makes one gRPC call, verifies, persists a
trace, and prints. No HTTP server, no auth, no sessions, no SSE.

Two things decided it, neither of which is architectural taste:

- **UC-5 is the acceptance case for the whole phase** — a fabricated citation caught, regenerated,
  and degraded. In a single process, the code that produced the fabrication is the code that catches
  it. That demonstrates the four checks are correct; it does not demonstrate that untrusted output
  is adjudicated by something which does not trust it. The latter is the product claim.
- **The cross-language normalisation contract is the project's most drift-prone integration**, and
  its failure mode is silent: quote-match failures on visually identical text. If ingestion and
  verification are both Python in Phase 1 they agree trivially, and the contract goes untested until
  it is ported — onto a corpus that is by then already ingested.

Scope is fenced deliberately: no CLI framework, one command, hand-rolled flag parsing. Roughly 600
lines of Go, none of it algorithmically hard, since verification is string matching and indexed
lookups.

## Alternatives rejected

- **Python-only CLI, porting verification to Go in Phase 2.** Genuinely cheaper up front, and the
  strongest alternative: Task 2 disappears entirely — proto, buf, two-language codegen — and Phase 1
  stays in one language with one debugger. Rejected for the two reasons above, plus a third that is
  easy to underestimate: the rewrite is not "port a function." It is the profile engine, FilterSpec
  resolution and its no-identity-leak test, verification, trace persistence, and the CLI — four of
  the eleven tasks in the plan.
- **A Go CLI with a throwaway transport** — shelling out to Python, or handing off through a file.
  Preserves the process boundary at lower setup cost. Rejected: it builds a transport that gets
  deleted in Phase 2, and it defers the proto contract, which is one of the three things most
  expensive to retrofit alongside the seam and the boundary itself.
- **A Go HTTP server rather than a CLI.** Everything the CLI does, plus routing, auth, sessions, and
  SSE — none of which Phase 1 needs, and all of which are Phase 4's job. The CLI exercises the same
  three structural things at a fraction of the surface.

## Consequences

Phase 1 gains a second language it would otherwise not need, and the setup cost is real: buf,
codegen for both sides, and a gRPC client. The buf CI machinery — `buf breaking`, and the
commit-or-generate decision — is deferred to Phase 2, since both are CI policy rather than contract
design and the proto has no external consumer yet.

Go writes the trace tables from the first working version, so the disjoint write scope of SHARED §5
holds from Phase 1 rather than being retrofitted, and the Phase 2 eval harness reads a trace schema
that will not move under it.

**The risk this accepts is momentum.** On a solo project the dominant failure mode is not shipping
at all, and this decision spends setup time before the first answer. If Phase 1 stalls on Go
scaffolding rather than on the corpus, that is the signal to revisit — the fallback is a Python-only
CLI with a Phase 2 port, adopted by superseding this ADR rather than by quietly drifting into it.
