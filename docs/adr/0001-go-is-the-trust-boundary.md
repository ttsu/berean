# ADR-0001: Go is the trust boundary, Python is the model layer

- **Status:** Accepted
- **Date:** 2026-08-29
- **Phase:** 1 — structural, expensive to reverse after Phase 4

## Context

The system needs Python for the model ecosystem (LangChain, LangGraph, embedding models,
rerankers) and wants Go for the serving edge. "We like both languages" is not an architecture.
Without a principled split, responsibilities drift across the boundary and the polyglot cost
buys nothing.

## Decision

**Python produces claims; Go adjudicates them.** Python's output is untrusted input to Go.

Go owns auth, sessions, rate limiting, profile resolution, citation verification, trace
persistence, translation-API fetch with attribution, and SSE to the client. Python owns query
rewriting, embedding, retrieval, reranking, agent orchestration, generation, ingestion, and the
eval harness.

One Postgres, two clients, disjoint write scope: Python writes corpus tables, Go writes session
and trace tables.

## Alternatives rejected

- **Python end to end.** Simpler, and viable. Rejected because the verification layer is the
  product's core claim, and putting it in the same process and language as the thing it is
  verifying makes the trust boundary rhetorical rather than real. Also gives up the serving
  characteristics Go provides at the edge.
- **Go end to end.** The model ecosystem is not there. Would mean reimplementing or shelling out
  to Python anyway, with a worse boundary.
- **Split by feature rather than by trust.** Rejected as arbitrary — it produces exactly the
  drift this ADR exists to prevent.

## Consequences

Verification becomes ordinary string matching and DB lookups in a language with a strict
compiler, rather than model behaviour. The cost is protobuf codegen discipline and two
toolchains in CI. For contributors this reduces to one line in CONTRIBUTING.md.
