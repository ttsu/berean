# ADR-0003: Stream trace events, not tokens

- **Status:** Accepted
- **Date:** 2026-08-29
- **Phase:** 1 (constrains Phase 4 UI)

## Context

Chat UIs stream tokens. Users expect it. But this system verifies every citation before an
answer is trustworthy, and verification runs on the complete answer object.

## Decision

**No token streaming.** Stream trace events over SSE — dispatched, retrieving, reranking,
verifying, verified — then deliver the verified answer in one piece.

Because the Python call is unary and verification happens after it returns, the live feed is Go
narrating its own stages. Python's trace comes back inside the response, for storage rather than
as a live feed.

## Alternatives rejected

- **Stream tokens, verify after, retract on failure.** Shows the user unverified text. Retraction
  after display is worse than a wait, and directly contradicts the product's core promise.
- **Stream tokens for non-doctrinal content only.** Requires classifying claims mid-stream, which
  is the hard problem, done in the worst possible place.

## Consequences

Perceived latency is higher than a typical chat app. This is arguably better UX here anyway:
watching sources get gathered is the trust-building part, and the "show the work" panel is a
first-class feature rather than a debug view.
