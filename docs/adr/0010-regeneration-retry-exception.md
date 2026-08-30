# ADR-0010: A verification failure permits one regeneration call

- **Status:** Accepted
- **Date:** 2026-08-30
- **Phase:** 1 — clarifies ADR-0002 before the verification engine is built

## Context

ADR-0002 fixes the seam at **exactly one unary gRPC call per user turn**. SHARED §3 independently
requires that on verification failure the system **regenerate once, then degrade**.

Both are load-bearing and, as written, they cannot both hold. Generation lives only in Catena, so a
regeneration is necessarily a second `Answer` call. An implementer reading the two rules together
has to violate one of them — and the contract already anticipates the regeneration, since
`OverallResult` carries a `REGENERATED` state.

The conflict was latent rather than intended. ADR-0002's target is Go orchestrating an agent loop
across the boundary; the bounded retry is not that, and was simply not in view when the rule was
written.

## Decision

**The unit is the generation attempt, not the turn.** One gRPC call per attempt, and a verification
failure permits **exactly one** retry call carrying the failure reasons back. A turn therefore makes
at most two calls, and only ever two.

Everything else ADR-0002 rejects still stands: no per-step orchestration from Go, no multi-hop
retrieval across the boundary, no agent loop split across languages. The retry is not a loop — it is
bounded at one, and a second failure degrades rather than retrying again.

## Alternatives rejected

- **Degrade on first failure, no regeneration.** Preserves ADR-0002 verbatim and is simpler, but
  throws away a cheap recovery: a fabricated locator is frequently fixed once the model is told
  which citation failed and why. It would also leave `REGENERATED` as dead weight in the contract,
  and SHARED §3 would need relaxing — which requires an ADR of its own regardless.
- **Move generation into Go so the retry costs no call.** Puts model orchestration on the trust
  boundary side and inverts ADR-0001. Recorded because it is the obvious way to satisfy both rules
  literally, and it is the wrong one.
- **Let Python retry internally, keeping one call per turn.** Hides the retry from the trust
  boundary. Go would no longer know how many generations produced the answer it is verifying, and
  the retry would run without the verification results that are the entire reason to retry.

## Consequences

Worst-case generation latency for a turn doubles. Acceptable: it happens only on verification
failure, which is by design rare, and the alternative is degrading an answer one retry would have
saved. Metrics must distinguish first-attempt verification from post-retry verification, or the
regeneration will hide a rising fabrication rate.

The "one call per turn" phrasing was load-bearing in several places and is now "one call per
generation attempt" in SHARED §5, `services/gateway/AGENTS.md`, and the Phase 1 INTEGRATION-SPEC.
Anyone reading ADR-0002 alone still sees the stricter rule. This ADR clarifies it rather than
superseding it: ADR-0002's actual decision — where the seam sits, and that the whole loop belongs on
one side — is unchanged.
