# ADR-0016: Affirmative claims are a slot, not a category

- **Status:** Accepted
- **Date:** 2026-08-31
- **Phase:** 1 — the answer object is pre-consumer (ADR-0013); breaking after

## Context

Verification check 3 read: "Doctrinal claims require `binding` or `governing`… an `excluded`
citation may never support a doctrinal claim affirmatively." Both clauses turn on whether a claim
is doctrinal. `Argument` is `{claim, warrant, citations}` — nothing marks it, and no document
defines the test. `warrant` does not help; it is the link from citation to claim, not a type.

The specs asked for the classification in one place and rejected it in another: ADR-0003 turned
down streaming non-doctrinal content because classifying claims mid-stream "is the hard problem,
done in the worst possible place." The hard problem does not become easy by moving it into the
verifier.

Only two readings were available to an implementer, and both fail. If every claim is doctrinal,
`advisory`, `contrary` and `excluded` citations can never support anything — Calvin, Bavinck and
Vos become unusable, UC-3's edition contrast breaks, and the `excluded` answer the product is built
around is unexpressible. If no claim is doctrinal, check 3 is a no-op. The second is the dangerous
one: the system reports four checks passing while one evaluates nothing, which is the failure this
whole phase exists to prevent, occurring inside the mechanism meant to prevent it.

The predicate is also load-bearing well beyond check 3. ADR-0011's substance is that Scripture below
`binding` cannot carry a doctrinal claim. ARCHITECTURE's layer 3 — "what makes this an enterprise
system rather than a RAG demo" — is defined in terms of doctrinal assertions. And once the 2000
creation report landed at `advisory` (ADR-0015), UC-4's ruling ran into the same floor.

## Decision

**Delete the category. Make the slot carry the distinction.**

Membership in `arguments` is what makes a claim affirmative. The answer object gains `descriptions`,
for claims *about* sources rather than claims resting on them, and the checks become structural:

- Every `Argument` carries at least one `binding` or `governing` citation.
- `advisory` may corroborate inside an argument; it may never carry one alone.
- `contrary` and `excluded` never appear in `arguments[]`.
- `descriptions` and `contrary_positions` permit any tier; `contrary` and `excluded` carry labels.
- `position` is empty when `arguments` is empty.

Go checks which list a claim occupies and what tiers its citations hold. It never asks what a claim
means. The hard problem is not solved here; it is routed around, and the routing is checkable.

The advisory rule is theologically right rather than merely convenient. "Corroborates but never
establishes" is what `advisory` means in a confessional tradition: Calvin may stand alongside the
Westminster Confession, not in place of it. That falls straight out of the floor with no classifier.

## Alternatives rejected

- **Python declares `doctrinal: bool`; Go enforces the consequence.** One field, and the model is
  best placed to know what it meant. Rejected because setting the flag *is* the verification
  decision, so this delegates verification to the model layer — forbidden by SHARED §6 and the
  reason ADR-0001 exists. There is no partial version: the unsafe direction is a doctrinal claim
  marked `false` to escape the floor, which is exactly the value you would have to trust.
- **Go classifies claims itself**, by heuristic or a side model call. Rejected three times over. It
  is the hard problem ADR-0003 declined. A model call inside the verifier makes the trust boundary
  depend on a model, which inverts ADR-0001. And it does not fit the 200 ms p95 budget for what is
  otherwise indexed lookups and string matching.
- **Keep the wording and let implementers choose a reading.** The status quo. Rejected because the
  cheaper reading — nothing is doctrinal — is silent, and a check that reports success while
  evaluating nothing is worse than no check, which at least fails visibly.
- **Apply the floor to every claim, with no descriptive slot.** Simple and safe, and it is this
  decision minus the escape hatch. Rejected because it makes the system unable to say what a source
  teaches: UC-4's ruling, the `excluded` repudiation, and any question answerable only from advisory
  material all become "I can't source this adequately". That is a wrong answer to a question that
  was never doctrinal, so the slot is not a concession — it is the other half of the design (UC-6).

## Consequences

The `excluded` tier finally has somewhere to live. "Your denomination examined this view and
repudiated it in 2007" is a `Description` carrying a labelled `excluded` citation — a claim about a
source, which is what INTEGRATION-SPEC always said that tier produced without providing a field for
it. The answer object could not express the product's flagship output until now.

Failure modes move in the right direction. A model that routes badly produces an `Argument` with no
binding citation, which fails loudly and regenerates. The rejected alternative's failure was a
`false` that nothing catches. Trading silent false-acceptance for loud false-rejection is the whole
posture of this system.

Descriptive answers become a capability rather than a degradation, which widens Phase 1 acceptance
by one use case and needs its own golden-set question. A tradition's `advisory` corpus stops being
decorative: it can now carry an answer on its own terms without ever carrying a doctrinal one.

One hole stays open, and is recorded rather than papered over. `position` is prose with no citations
of its own, so a model can assert there what the routing rules would reject in `arguments`. The
empty-when-descriptive rule bounds it; nothing checks it semantically, because doing so would
require the classification this ADR just removed. Phase 2's eval harness is where that rate gets
measured, and a persistent rate is what would cause us to revisit — most likely by requiring
`position` to be assembled from cited claims rather than authored.

## Documents updated

- `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` — `descriptions` slot and `Description` type,
  the slot constraints, the `excluded` paragraph, and the recorded `position` gap
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — check 3 restated structurally
- `specs/SHARED-TECHNICAL-SPEC.md` — §6, the affirmative-claim floor and the structural rule
- `specs/001-phase-1-pca-baseline/PRODUCT-SPEC.md` — UC-6 and the definition of done
- `specs/001-phase-1-pca-baseline/PLAN.md` — Tasks 7, 8 and 11
- `docs/ARCHITECTURE.md` — steering layers 2 and 3, and the answer object field list
- `docs/GLOSSARY.md` — the affirmative/descriptive entry
- `services/gateway/AGENTS.md` — the slot rule beside the resolved-profile rule
- `.agents/skills/run-evals/SKILL.md` — descriptive answers scored as a pass, and the two gaps the
  citation checks cannot catch
- `docs/adr/0011-scripture-tier-is-profile-configurable.md` — status marked restated
