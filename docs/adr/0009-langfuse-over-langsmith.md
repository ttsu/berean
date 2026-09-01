# ADR-0009: Langfuse (self-hosted) for tracing and evals

- **Status:** Accepted (the Consequences section understates the cost — self-hosted Langfuse is a five-container stack: web, worker, ClickHouse, Redis, and S3-compatible storage, not "one more container". The decision is unaffected. The real footprint, and the headless bootstrap that keeps the no-external-accounts guarantee, are documented in the README and PLAN Task 1)
- **Date:** 2026-08-29
- **Phase:** 1 — instrument from day one, not retrofitted

## Context

The project needs LLM tracing and an eval harness. Phase 2 (eval harness and golden set) runs
*before* Phase 3 (hybrid retrieval and reranking), because the ability to say "hybrid + rerank
moved faithfulness from 0.71 to 0.89 on a 150-question set" is what makes this an engineering
project rather than a tutorial. That makes the eval tool load-bearing, not optional.

## Decision

**Langfuse, self-hosted**, from day one. OpenTelemetry traces alongside for the non-LLM path.
OTel + Phoenix is an acceptable substitute.

Traces are stored per response in Postgres regardless. They are the eval dataset and the audit
log, and that persistence is ours, not the observability vendor's.

## Alternatives rejected

- **LangSmith.** Proprietary SaaS. Breaks the run-anywhere requirement and the acceptance test.
- **Nothing until Phase 2.** Retrofitting instrumentation means the Phase 1 baseline is
  unmeasured, which defeats the point of measuring the Phase 3 improvement against it.

## Consequences

One more container in the compose file. Acceptable — the alternative is an unfalsifiable claim
that retrieval improved.
