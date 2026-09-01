# ADR-0018: Qwen3-8B as the Phase 1 generation default — pinned, not locked

- **Status:** Accepted (provisional)
- **Date:** 2026-09-01
- **Phase:** 1 — `make provision` needs a name; re-decided at Phase 2 against the golden set

## Context

ADR-0006 spends a page justifying the *embedding* model. Nothing names the **generation** model.
PLAN Task 1 says `make provision` "pulls the Ollama model," TECHNICAL-SPEC says "default local via
Ollama," and no document anywhere says which one. It would have been chosen during Task 1 or Task 7
by whoever got there first, with no decision behind it and no record of it.

That is worse here than it looks, because the generator is the largest single variable in the
Phase 2 baseline. Phase 2 exists to produce a number that Phase 3 must beat (SHARED §7). An unpinned
or undocumented generator makes that number unreproducible, which defeats the ordering the project
calls non-negotiable.

What actually binds the choice is narrower than a leaderboard:

- **Licence.** ADR-0007's posture is that downstream commercial use must be permitted and
  restrictive licences are disqualifying rather than a tradeoff. That rules out bespoke
  model licences with their own acceptable-use policies, not merely non-commercial ones.
- **Footprint.** SHARED §1 makes `docker compose up` the acceptance test. The generator shares a
  machine with Postgres, BGE-M3 (~2.3 GB), and a five-container Langfuse stack.
- **Schema adherence.** `AnswerObject` is deep — `arguments`, `descriptions`, `contrary_positions`,
  `contested`, each carrying citation lists. This needs constrained decoding, not a prompt asking
  nicely for JSON.
- **Verbatim copying.** This is the skill Phase 1 actually depends on and the one no benchmark
  reports. Check 2 is exact substring containment after normalisation, with no case, quote, or dash
  folding. A model that paraphrases 17th-century English by a single curly apostrophe fails every
  citation it emits.

Reasoning ability is close to irrelevant here. Phase 1 asks the model to route claims into slots and
copy text out of context, and the trust boundary catches it when it does not.

## Decision

**Qwen3-8B, Apache-2.0, served by Ollama with JSON-schema-constrained decoding.**

- The exact tag is pinned in the provisioning manifest, and the model identifier is **written into
  every trace**. A silent model change must not be able to move the Phase 2 baseline.
- `AnswerObject` validity is a decoding constraint via Ollama's schema `format`, not a prompt
  request. Structural validity is then free and the interesting failures are semantic.
- The provider stays behind the OpenAI-compatible interface SHARED §1 requires, so this is a
  configuration default rather than a coupling.
- A smaller fallback is documented for low-RAM machines. It is a documented degradation, not a
  second supported configuration.

Treat this exactly as ADR-0006 treats BGE-M3: **a tested default, re-decided at Phase 2 against the
golden set.** A run that confirms the incumbent is still a decision worth recording.

## Alternatives rejected

- **Qwen2.5-7B-Instruct.** Same licence, smaller, and notably steady at both JSON adherence and
  copying from context — which is the skill that matters most here, so this is the closest call.
  Rejected on the margin: Qwen3 is stronger at the slot-routing judgement that ADR-0016 pushed onto
  the model, and routing errors cost a regeneration each.
- **Phi-4 14B (MIT).** The most permissive licence of the candidates and the best reasoning.
  Rejected on footprint: roughly 9 GB quantised, on top of everything else in the compose stack, and
  slow enough on CPU to make the acceptance test unpleasant on an ordinary laptop. Portability is
  the acceptance criterion; answer quality is Phase 2's.
- **Llama 3.1 8B.** Strong and widely available. Rejected on licence: a bespoke community licence
  with its own acceptable-use policy is not an OSI licence, and ADR-0007's instruction is to pick
  dependencies assuming downstream commercial use, not to assess whether a particular restriction
  happens to bind us today.
- **Gemma.** Rejected for the same reason, with a use policy that is more restrictive still.
- **A hosted API by default.** Better output, no provisioning. Rejected outright: it breaks the
  no-external-accounts acceptance test, which SHARED §1 states as the rule a change cannot be worth
  breaking.
- **Specify capabilities and let the deployer choose.** Documents what is needed — constrained
  decoding, context window, licence class — without naming a model. Rejected because `make provision`
  must pull something concrete, and because an unpinned generator makes the Phase 2 number
  unreproducible, which is the one thing the phase ordering exists to protect.

## Consequences

The RAM floor becomes real and must be documented: roughly 5 GB resident for the generator on top of
BGE-M3, Postgres, and the Langfuse stack. The README's clone-to-first-answer path is a portability
promise, and a promise nobody has checked on a modest machine is not one.

Verbatim quoting of early modern English is the live risk to Phase 1 producing anything at all, and
it is now measured for free: every failed check 2 is recorded per citation in `VerificationResult`,
and Task 11's expectation table distinguishes a verified answer from a degraded one. If the
degradation rate is dominated by near-miss quotes rather than fabricated locators, that is a finding
about the model, not about the verifier, and the fallback is a larger or better-instructed
generator rather than a looser check. **Loosening check 2 is not on the table** — SHARED §3 fixes
exact substring containment, and a fuzzy quote match would silently reintroduce the failure this
whole phase exists to prevent.

Pinning the tag means provisioning breaks when the tag is withdrawn upstream. Acceptable, and the
same exposure `make corpus-verify` already accepts for corpora.

## Documents updated

- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — the Generation section names the model, the
  pinned tag, and constrained decoding
- `specs/001-phase-1-pca-baseline/PLAN.md` — Task 1 (`make provision` pulls a named, pinned model),
  Task 7 (constrained decoding; model identifier recorded in the trace)
- `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` — `RetrievalTrace` carries the generation
  model alongside `embedding_model`
- `proto/README.md` — `generation_model` listed among the fields used from Phase 1
- `README.md` — RAM and disk floor, and the expected provisioning duration
- `.agents/skills/run-evals/SKILL.md` — the generator is re-decided at Phase 2 alongside the
  embedder, and a confirming run is still recorded
