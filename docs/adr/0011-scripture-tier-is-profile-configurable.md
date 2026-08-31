# ADR-0011: Scripture's authority tier is profile-configurable, defaulting to binding

- **Status:** Accepted (check 3 restated by ADR-0016 — the rule holds, its wording changed)
- **Date:** 2026-08-30
- **Phase:** 1 — decided with the profile engine, cheap now and a migration later

## Context

Resolving Scripture into the corpora list left a question the specs had ducked: which tier it
carries. It cannot be skipped. Tier is one of the four verification checks, and check 3 requires a
doctrinal claim to rest on `binding` or `governing`, so Scripture's tier decides whether a
Scripture-only answer can support a doctrinal claim at all.

The obvious answer is `binding`, and it is correct for every tradition currently in scope. But the
project's whole premise is that a tradition's commitments live in its profile rather than in the
engine, and Scripture is the one corpus every tradition shares — which makes it the worst candidate
for the engine to decide on everyone's behalf.

The distinction between traditions here is subtler than a tier. Sola scriptura and
Scripture-alongside-Tradition both hold Scripture binding; they differ on what *else* is binding.

## Decision

**`scripture.stance` is a profile field, defaulting to `binding` when absent.**

It accepts `binding`, `governing`, or `advisory`. `contrary` and `excluded` are load errors — no
tradition in scope repudiates Scripture, so either value means the profile is wrong, and failing
loudly beats encoding a position nobody holds.

The resolved stance becomes that corpus's tier in the filter spec and is checked at verification
exactly as any other corpus is. Scripture gets no special case in retrieval, citation, or
verification.

A profile setting the stance below `binding` is making a substantive claim, not a cosmetic one:
under check 3 it means Scripture alone cannot carry a doctrinal claim for that tradition. That
should be deliberate and should be covered by a golden-set question.

## Alternatives rejected

- **Hardcode `binding` for every profile.** Simplest, and true for every tradition in scope today.
  Rejected because it puts a theological commitment in the engine, where no other tradition-specific
  claim lives, and makes the one corpus every tradition shares the one corpus no tradition can
  configure. The cost of the field is a default and one validation rule.
- **A dedicated tier above `binding` — `supreme` or similar — reserved for Scripture.** Expresses
  sola scriptura directly. Rejected: a sixth tier used by exactly one corpus, forcing every tier
  comparison, weight table, and filter to carry a special case. The distinction it captures —
  Scripture's *sufficiency* as against its *authority* — is better carried by what else the profile
  marks `binding`, which is where a reader would look for it anyway.
- **Leave Scripture outside the tier system, always retrievable and never tier-checked.** Avoids the
  question entirely and reintroduces the bug this replaces. An untiered corpus is an unchecked
  corpus, and nothing renders unverified.

## Consequences

A profile can now express Scripture-plus-Tradition against sola scriptura through the shape of its
`binding` set, without the engine knowing which is which. That is the intended shape of every
tradition-specific commitment in this system.

The default keeps every existing profile correct with no change, so the field costs nothing until a
tradition needs it. The validation rule is what makes the default safe: a profile that omits the
field gets the right answer, and one that sets it wrongly fails at load rather than at render.

Cross-contamination tests should include the tier Scripture resolves to, or a profile could silently
downgrade it and only surface as unexplained degradation on questions the corpus can answer.
