# ADR-0002: Exactly one gRPC call per user turn

- **Status:** Accepted (amended by ADR-0010 — the rule is one call per *generation attempt*, not per user turn; the title and Decision below predate that)
- **Date:** 2026-08-29
- **Phase:** 1

## Context

Given the Go/Python split, the question is where the seam sits and how often it is crossed.

## Decision

**Exactly one unary gRPC call from Go into Python per user turn.**

Go sends the query, conversation context, and a *resolved filter spec* — corpus IDs by tier plus
tier weights, not the profile itself. Python returns the structured answer object plus the
retrieval trace. Go then verifies and renders.

Protobuf defines the contract once and generates for both sides.

## Alternatives rejected

- **Go orchestrating the agent loop, calling Python per step.** Chatty, leaks agent state across
  the language boundary, and makes multi-hop retrieval miserable to debug. The whole loop belongs
  on one side.
- **Server-streaming RPC from the start.** More granular progress, but a materially more complex
  contract for a benefit that is speculative until the unary version is observed in use.
- **REST/JSON.** No generated types, so the answer object gets hand-maintained in two places.
  That is the classic polyglot drift bug and the exact failure this design is avoiding.

## Consequences

More than one cross-language call per turn is a signal the seam is in the wrong place, and
should trigger a design conversation rather than a workaround.

Server-streaming remains the escape hatch if the wait feels dead in practice. Start unary;
switch only on evidence.
