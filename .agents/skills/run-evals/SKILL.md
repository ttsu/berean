---
name: run-evals
description: Run and interpret Berean's evaluation harness — golden sets, retrieval recall@k, answer faithfulness, cross-contamination tests, and embedding model comparison. Use when measuring a baseline, validating a retrieval change, or re-deciding the embedding model.
---

# Running evals

Phase 2 exists before Phase 3 for one reason: being able to say "hybrid + rerank moved
faithfulness from 0.71 to 0.89 on a 150-question set" is what makes this engineering rather than a
tutorial. **Never make a retrieval change without a before number.**

## Measure the two things separately

**Retrieval recall@k** — did the right sources come back at all? A retrieval failure and a
generation failure need different fixes, and a combined score tells you nothing about which you
have.

**Answer faithfulness** — is every claim actually supported by the cited source?

Report both. Never report only a blended score.

## Golden sets are tradition-parameterised

One per tradition, with expected sources per question. A correct answer under one profile is a
wrong answer under another, so there is no shared set.

**No ESV or NIV text in a golden set.** This is the likeliest place it gets in, because golden sets
naturally contain expected passages. Store locators and public-domain text only.

## Cross-contamination tests are mandatory

Assert that no Tridentine source appears at `binding` tier under a PCA profile, and the equivalent
for every tradition pair. These catch profile-enforcement regressions that faithfulness scores will
not.

## Degradation is not failure — and silence is not degradation

`DEGRADED` — "I can't source this adequately" — is a **successful** outcome of the verification
system. Track it as its own metric.

An honest non-answer is another outcome: `VERIFIED` with `no_answer_reason` set and every content
slot empty. Do not fold it into the degradation rate. The corpus being silent and verification
refusing to ship mean opposite things, and a metric that merges them cannot tell a retrieval problem
from a fabrication problem. Track first-attempt and post-retry verification separately too
(ADR-0010), or a regeneration hides a rising fabrication rate.

Score `no_answer_reason` directly. It is the only model-authored string that renders with no citation
beside it, bounded by 200 characters and the all-slots-empty rule and by nothing else. A substantive
theological claim appearing there is a failure, and a persistent rate is what would send the field
back to a fixed set of reason codes (ADR-0020).

A rising degradation rate on questions the corpus should answer signals a retrieval problem. A
degradation rate near zero on questions the corpus genuinely cannot answer signals the system is
confabulating, which is far worse.

Include questions the corpus cannot answer. Confident answers to them are failures.

## Generation failure is a rate to track, not a bug to file

`GENERATION_FAILED` is a fourth outcome, decided by the turn's final attempt: the generator returned
no usable answer object — truncated, not JSON, not an object, empty, or declined — on the attempt
that decided the outcome, even when an earlier attempt in the same turn was checked and failed
(ADR-0025). Before this channel existed the run left no row at all, so this is the first phase in
which the rate is measurable.

Compute the outcome rate from `trace.responses.overall_result = 'generation-failed'`, not from
`trace.generation_failures`. That table has a row per **failed attempt**, not per failed turn —
`writeGenerationFailure` runs for every attempt that came back with no object, including attempt 1
of a turn that then regenerates and verifies (`REGENERATED`) and attempt 1 of a turn whose attempt 2
then fails verification (`DEGRADED`). A row there does not imply the turn failed. Counting its rows
counts attempts, not outcomes, and over-counts the rate this channel exists to make measurable. Use
`trace.generation_failures` instead for the per-attempt *code* breakdown, per model and per `top_k`
— which way does this generator fail, and how often — which is what that table is for.

Do not fold the outcome rate into the degradation rate: `DEGRADED` means verification refused to
ship something it checked, and `GENERATION_FAILED` means the attempt that decided the outcome
checked nothing, because it produced nothing. A rate that moves when the model or the provider
changes is the signal a provider comparison needs; a rate that never moves at all is the baseline
the next provider has to beat.

## Contested loci

For a contested locus, the correct behaviour is flagging the debate, not resolving it. Score
resolution as a failure even when the resolution is the majority view. An answer carrying both
`is_contested` and `arguments` now fails verification outright (ADR-0019), so what the golden set
measures is the subtler version: a contested answer whose `descriptions` lean uniformly one way.

Things the citation checks cannot catch, so the golden set has to — INTEGRATION-SPEC enumerates all
four. An answer that resolves a contested locus while citing neither the ruling nor anything reaching
it fabricates nothing, so no check fires; measure that rate directly. `position` is prose with no
citations of its own, so score it against the claims beneath it. `no_answer_reason` is the same
problem in a different slot. And most importantly, **the checks prove a citation is real, never that
its quote supports the claim** — a real `binding` quote behind a claim the source contradicts passes
all four. That is what answer faithfulness measures, and it is the reason faithfulness is reported
separately from recall@k rather than blended with it.

## Descriptive questions

A question answerable only from `advisory` sources has a correct answer, and it is not "I can't
source this adequately" (UC-6). Score a refusal as a failure, and score an answer that asserts a
descriptive claim as the tradition's own position as a failure too — the first is the system being
uselessly strict, the second is the failure the tier system exists to prevent.

## Comparing models

Per ADR-0006, the embedding choice is re-decided against the golden set before Phase 3. BGE-M3 vs
Qwen3-Embedding-0.6B. The **generation** model is re-decided on the same terms (ADR-0018): Qwen3-8B
is a pinned default, not a settled one, and a run confirming the incumbent is still a decision worth
recording. Vary one model at a time; both are recorded per response in the trace precisely so a
comparison can hold the other constant.

The golden set is the only evaluation that reflects archaic English and Latin. MTEB does not, and a
0.5-point MTEB gap is noise.

Procedure: re-index with the candidate, run the same golden set, compare recall@k on identical
questions. Vary only the model.

Record the result as a **new ADR superseding ADR-0006**, whether or not the default changes — ADRs
are immutable once accepted, so the result does not go into 0006. A run that confirms the incumbent
is still a decision worth recording, and it is the run most likely to go unwritten.

## Checklist

- [ ] Baseline recorded before the change
- [ ] Recall@k and faithfulness reported separately
- [ ] Cross-contamination tests pass for every tradition pair touched
- [ ] Degradation rate tracked as its own metric
- [ ] Generation-failure rate tracked as its own metric, per model and per `top_k`
- [ ] Unanswerable questions included; confident answers to them counted as failures
- [ ] Contested loci: flagging scored as correct, resolving as failure
- [ ] No ESV or NIV text anywhere in the set
- [ ] Result recorded where the next person will find it
