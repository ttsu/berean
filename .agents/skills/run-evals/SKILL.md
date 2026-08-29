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

## Degradation is not failure

`DEGRADED` — "I can't source this adequately" — is a **successful** outcome of the verification
system. Track it as its own metric.

A rising degradation rate on questions the corpus should answer signals a retrieval problem. A
degradation rate near zero on questions the corpus genuinely cannot answer signals the system is
confabulating, which is far worse.

Include questions the corpus cannot answer. Confident answers to them are failures.

## Contested loci

For a contested locus, the correct behaviour is flagging the debate, not resolving it. Score
resolution as a failure even when the resolution is the majority view.

## Comparing embedding models

Per ADR-0006, the embedding choice is re-decided against the golden set before Phase 3. BGE-M3 vs
Qwen3-Embedding-0.6B.

The golden set is the only evaluation that reflects archaic English and Latin. MTEB does not, and a
0.5-point MTEB gap is noise.

Procedure: re-index with the candidate, run the same golden set, compare recall@k on identical
questions. Vary only the model. Record the result as an ADR update whether or not the default
changes.

## Checklist

- [ ] Baseline recorded before the change
- [ ] Recall@k and faithfulness reported separately
- [ ] Cross-contamination tests pass for every tradition pair touched
- [ ] Degradation rate tracked as its own metric
- [ ] Unanswerable questions included; confident answers to them counted as failures
- [ ] Contested loci: flagging scored as correct, resolving as failure
- [ ] No ESV or NIV text anywhere in the set
- [ ] Result recorded where the next person will find it
