# ADR-0019: A contested locus admits no affirmative arguments

- **Status:** Accepted
- **Date:** 2026-09-01
- **Phase:** 1 — amends ADR-0015 while the answer object is still pre-consumer (ADR-0013)

## Context

ADR-0015 made contested handling verifiable, and closed the direction it could see: a verified
citation that resolves to a locus's ruling while `is_contested` is false fails the answer. It calls
that the system's only omission check, added because every other check catches fabrication instead.

The opposite direction was left open, and it is the more likely one. Nothing in INTEGRATION-SPEC
prevents this:

```
contested:  { is_contested: true, locus: "creation-days",
              citations: [ruling], state_of_debate: "<ruling quoted verbatim>" }
arguments:  [ { claim: "The PCA holds these were ordinary days.",
                citations: [ { wcf-1788-american, "WCF 4.1", binding,
                               quote: "in the space of six days" } ] } ]
position:   "The days of creation were ordinary days."
```

Every constraint passes. The locus was sent. The ruling is cited and quoted verbatim. WCF 4.1
resolves, its quote matches, its tier is `binding`, its licence permits. Check 3 is satisfied. The
answer flags the locus as contested **and resolves it in the same breath** — which PRODUCT-SPEC
calls "the worst possible outcome" and SHARED §8 calls worse than having no profile at all.

This is not a corner case. ADR-0015 says so itself, in the course of rejecting a different option:
WCF 4.1's "in the space of six days" reads as settled and points the wrong way. It is also the most
retrievable chunk in the corpus for the UC-4 question. The naive retriever will hand the model
exactly the material needed to produce this failure, in the one use case the product's
trustworthiness rests on.

The gap survived review because ADR-0015 framed the risk as *omission* — a model failing to notice
a locus is contested. The model noticing and then resolving anyway is a different failure with the
same cost, and the checks written for the first do not touch the second.

## Decision

**When `is_contested` is true, `arguments` MUST be empty.**

One structural rule, checked in Go, with no semantics — ADR-0016's move applied to the case
ADR-0015 left open. Go asks which slot a claim occupies, never what it means.

Two things follow without further machinery. Affirmative material about the locus routes to
`descriptions`, where it belongs anyway: "the Confession says 'in the space of six days'" is a claim
*about* a source, not one resting on its authority, and `descriptions` permits any tier. And
`position` empties for free, because the existing rule already requires `position` to be empty when
`arguments` is empty — which closes, for the contested case only, the uncited-prose hole ADR-0016
recorded and could not otherwise reach.

A contested answer is therefore a **purely descriptive** answer: the ruling, quoted verbatim, plus
whatever the sources say, attributed to them. Failures take the ordinary path — regenerate once with
reasons fed back, degrade on the second. Go does not rewrite the answer.

## Alternatives rejected

- **Require only `position` to be empty when contested.** Narrower, and it targets the field that
  most visibly does the resolving. Rejected because an `Argument`'s `claim` is also prose: the model
  simply resolves the locus there instead, with a `binding` citation beside it making it look
  *better* sourced than the `position` version. This closes the loudest half of the hole and leaves
  the more dangerous half open.
- **Record it as a known gap and measure it in Phase 2.** Consistent with how the other three
  documented holes are handled, and genuinely tempting for that reason. Rejected because those three
  have no cheap structural fix and this one does. Accepting it would mean shipping UC-4 knowing the
  acceptance run can pass while the behaviour is exactly wrong — and UC-4's whole point is that a
  confident answer is worse than none.
- **Check semantically whether an argument resolves the locus.** The complete fix. Rejected for the
  third time in this repository: it is the claim classification ADR-0016 deleted, it would put a
  model call inside the verifier and invert ADR-0001, and it does not fit the 200 ms budget for what
  is otherwise indexed lookups and string matching.
- **Let Go strip `arguments` when contested and render the rest.** Produces a good answer from a bad
  one with no regeneration. Rejected on ADR-0015's own ground: a verifier that edits what it
  verifies is no longer a verifier, and `confidence.reason` remains the only Go-authored field.

## Consequences

UC-4 becomes checkable rather than hoped-for. The rule is one comparison in Go and needs no new
verification machinery.

The cost is over-suppression, and it is real: a compound question that touches a contested locus
alongside settled material loses its affirmative half entirely. "What does the Confession teach
about creation, and how long were the days?" returns a descriptive answer where half of it could
have been affirmative. That is the right trade where the product says confident resolution is the
worst possible outcome, and it fails in the safe direction — visibly strict rather than silently
wrong.

What would cause us to revisit: if Phase 2 shows contested loci being flagged on questions only
tangentially related to them, the suppression is landing on answers it was not aimed at, and the
fix is narrowing when `is_contested` is set rather than loosening what it suppresses.

## Documents updated

- `docs/adr/0015-contested-loci-cross-the-boundary.md` — status line amended to reference this ADR
- `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` — the contested constraint list, and the
  `Contested` type's note on what a contested answer may contain
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — verification check 3's slot rules
- `specs/001-phase-1-pca-baseline/PLAN.md` — Tasks 7, 8 and 11
- `services/gateway/AGENTS.md` — the slot rule beside the resolved-profile rule
- `.agents/skills/run-evals/SKILL.md` — a contested answer carrying arguments scored as a failure
- `.agents/skills/add-tradition-profile/SKILL.md` — what a contested golden-set question expects
- `docs/GLOSSARY.md` — the `contested` entry
