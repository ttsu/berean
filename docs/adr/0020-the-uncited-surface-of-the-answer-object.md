# ADR-0020: The answer object's uncited surface, and what verification actually guarantees

- **Status:** Accepted
- **Date:** 2026-09-01
- **Phase:** 1 — the answer object is pre-consumer (ADR-0013); breaking after

## Context

Three loose ends in the answer object share one question: **what reaches a user without being
verified, and who wrote it.** They are decided together because deciding them apart is how the
answer object accumulates unverified prose one reasonable field at a time.

**UC-2 has no representation.** "What is the PCA's position on cremation?" — the Standards are
silent, and PRODUCT-SPEC calls the honest non-answer "a pass, not a failure." But work out the
object: `arguments` empty, so `position` must be empty; `descriptions` empty, because there is
nothing to describe; `contested.is_contested` false. That is a completely empty `AnswerObject`,
which passes verification vacuously — no citations to check, no claim lacking one. Three problems
follow. There is no field in which the model can report silence. An empty object cannot be
distinguished from a truncated or malformed generation, which should regenerate. And the user sees
whatever the CLI renders for emptiness, which would be the degraded string — collapsing UC-2 into
UC-5 at exactly the point INTEGRATION-SPEC insists `DEGRADED` "is a successful outcome, not an
error, and metrics must not treat it as a failure rate."

**`confidence.level` has no stated author.** INTEGRATION-SPEC is emphatic that `confidence.reason`
is Go-derived and "never model-authored," warning that a model-authored reason "would be
introspection wearing a structured field's clothes… the likeliest way for §4 to be violated without
anyone noticing." The annotation covers only `reason`. By omission `level` is Python's — a claim
about the model's own certainty, unverifiable by construction, rendered beside citations that *are*
verified. It also lets the two halves of one field contradict each other: Go computing `reason` from
the verification result while Python computes `level` from nothing checkable.

**The guarantee is narrower than the claim.** The four checks establish that a citation is *real*.
None establishes that the quote *supports the claim*. This passes every check:

```
Argument{ claim: "The PCA holds that baptism regenerates the infant.",
          citations: [ { wcf-1788-american, "WCF 28.1", binding,
                         quote: "Baptism is a sacrament" } ] }
```

Locator resolves, quote is verbatim, tier is `binding`, licence permits — while asserting something
the Confession denies. INTEGRATION-SPEC records three known holes with care; this one is larger than
all three and is written down nowhere.

## Decision

**1. A bounded, model-authored `no_answer_reason`.** The model may state why it is silent, in its
own words, subject to structural rules Go enforces:

- It may be non-empty **only** when every content slot is empty — no `arguments`, no `descriptions`,
  no `contrary_positions`, `is_contested` false.
- It is capped at **200 characters**, enforced by Go, and an over-length value fails the answer.
- An answer with every slot empty and no `no_answer_reason` **fails and regenerates** — which
  correctly treats a truncated generation as a failure rather than as considered silence.
- Go renders it distinctly from the degraded string, and the trace records `VERIFIED` with
  `no_answer_reason` set as an outcome separate from `DEGRADED`.

**2. Go derives both halves of `confidence`.** Python MUST NOT populate `level` or `reason`, and Go
MUST overwrite both, by a rule written into INTEGRATION-SPEC rather than left to the implementer.
Confidence then means "what verification found," which is the only thing entitled to sit beside a
verified citation.

**3. Provenance is not entailment — stated, and the degenerate case blocked.** The limit is recorded
in INTEGRATION-SPEC alongside the other three gaps, with Phase 2 faithfulness scoring named as what
measures it. Alongside it, one structural rule with no semantics: **a quote shorter than 40
characters fails check 2.** It kills "Baptism is a sacrament" without pretending to check meaning,
and the floor is a tunable number rather than a judgement about claims.

## Alternatives rejected

- **A reason-code enum instead of free text for silence** — `NOT_ADDRESSED`,
  `RETRIEVAL_INSUFFICIENT`, `OUT_OF_SCOPE`, with Go rendering fixed prose per code. Strictly safer:
  nothing model-authored reaches the screen uncited, and it is the option most consistent with the
  rest of this repository. Rejected because the codes cannot say the useful thing. "The Standards
  address burial practice only incidentally, in the context of church discipline" is a genuinely
  better non-answer than any enum value, and UC-2 is a *first-class answer* rather than a
  degradation — the product spec is explicit that it is a pass. The 200-character cap and the
  all-slots-empty precondition are what make the risk bounded enough to accept.
- **No field at all; treat an empty object as silence.** Zero contract change. Rejected because a
  malformed generation then renders as an honest non-answer — a silent false-accept, which is the
  posture this system inverts everywhere else.
- **Keep `confidence.level` model-authored but label it as the model's own self-report.** Preserves
  a signal the model has some access to, honestly attributed. Rejected: SHARED §4 bans shipping
  introspection *in any form*, not merely unlabelled introspection, and this is precisely the case
  INTEGRATION-SPEC predicts gets missed.
- **Drop `level` entirely and render only the derived reason.** The cleanest reading of §4, and a
  real contender. Rejected narrowly: an enum is load-bearing for Phase 2 metrics and for the Phase 4
  UI, and adding it back is a proto break. Deriving it costs nothing once `reason` is derived from
  the same result.
- **Require cited chunks to appear in the RetrievalTrace candidate list**, catching citations
  recalled from training rather than read from context. Useful signal, and it was tempting as a fifth
  check. Rejected because the candidate list is Python-authored and therefore untrusted — Python can
  simply add the chunk — so it would sit beside four enforceable checks looking like a fifth, which
  is the defect ADR-0016 exists to prevent.
- **Solve entailment properly, by checking that the quote supports the claim.** Rejected on the same
  grounds as every other semantic check in this system: it is claim classification, it needs a model
  in the verifier, and SHARED §7 already assigns answer faithfulness to Phase 2 as a measurement
  separate from recall@k.

## Consequences

UC-2 gets an honest, distinguishable output and the `DEGRADED` metric stays clean, which matters
because ADR-0010 already requires metrics to distinguish first-attempt from post-retry verification
and a third confounder would make the rate unreadable.

**The accepted risk is stated plainly: `no_answer_reason` is uncited prose that renders on its own,
with no citation beside it to constrain it.** Nothing prevents 200 characters of unverified
theological assertion in the one answer shape most likely to be produced. The cap bounds the blast
radius; it does not remove it. This is now the fourth documented uncited-prose surface — after
`position`, the omission blind spot, and entailment — and it is the only one deliberately added
rather than inherited. Phase 2's golden set must score it directly, and a nonzero rate of
substantive claims appearing there is what would cause us to revisit, most likely by falling back to
the reason-code enum.

The 40-character quote floor will occasionally reject a legitimately short citation — a catechism
answer of a few words, or a locator whose whole content is brief. That is a loud, diagnosable
failure with a known cause, and it is the right direction to fail in. Revisit the number if it fires
on real Westminster content during Task 11.

## Documents updated

- `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` — `no_answer_reason` on `AnswerObject` and its
  constraints; `confidence` authorship; the quote-length floor on check 2; the provenance/entailment
  gap recorded beside the existing three
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — checks 2 and 3 restated; the confidence rule
- `specs/001-phase-1-pca-baseline/PRODUCT-SPEC.md` — UC-2's output described as a distinct outcome
- `specs/001-phase-1-pca-baseline/PLAN.md` — Tasks 7, 8, 10 and 11
- `specs/SHARED-TECHNICAL-SPEC.md` — §3, the quote floor; §4, confidence as verification metadata
- `services/gateway/AGENTS.md` — Go derives both confidence fields; the quote floor
- `services/catena/AGENTS.md` — MUST NOT populate confidence; `no_answer_reason` rules
- `.agents/skills/run-evals/SKILL.md` — `no_answer_reason` scored directly; entailment named as a
  faithfulness target
- `docs/ARCHITECTURE.md` — the answer object field list
- `proto/README.md` — `no_answer_reason` listed among the fields used from Phase 1
