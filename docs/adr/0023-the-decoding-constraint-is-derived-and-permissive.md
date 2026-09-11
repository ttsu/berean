# ADR-0023: The decoding constraint is derived, permissive, and unthinking

- **Status:** Accepted
- **Date:** 2026-09-10
- **Phase:** 1 — Task 7; re-measured at Phase 2 alongside the generator

## Context

ADR-0018 decided that `AnswerObject` validity is enforced by JSON-schema-constrained decoding
rather than by asking the model for JSON. It did not say what that schema looks like, and three
questions turn out to have non-obvious answers — each of which changes the *verification failure
rate*, which is the number Phase 1 exists to produce.

The three are: where the schema comes from, what it marks `required`, and what to do about the fact
that the pinned generator thinks before it answers.

Probes against the pinned tag (`qwen3:8b-q4_K_M`, digest `500a1f067a9f`) settled all three, and the
evidence is recorded here because the arguments read as close calls without it.

## Decision

**One: the schema is derived from `AnswerObject.DESCRIPTOR`, minus `confidence`.**

A hand-written schema is a second copy of the contract, and CLAUDE.md forbids hand-maintaining a
struct on one side. `catena.serve.schema` walks the descriptor. The one subtraction — `confidence`,
which Go derives (ADR-0020) — is a named constant, so removing it is a visible act rather than an
absence nobody notices, and `additionalProperties: false` is what makes it *unpopulatable* rather
than merely unpopulated.

**Two: `required` follows the list-only rule.**

> Fields are required in messages reachable ONLY through a repeated field. Nothing is required in
> messages reachable as a singular field, or at the root.

`Citation`, `Argument`, `Description` and `ContraryPosition` are list-only. `Contested` is singular;
`AnswerObject` is the root. The rule is mechanical — computable from the descriptor — rather than a
per-field judgement.

The principle underneath is whether a message has a **meaningful empty state**. One reached only
through a list does not: absence is the list being empty, never a half-filled element. A `Citation`
without `{corpus_id, locator}` is not an absent citation, it is one that cannot resolve — check 1
fails it by construction. `AnswerObject` and `Contested` are the opposite: their emptiness is
exactly what the contract reads as meaning (the honest non-answer; `is_contested: false`; `position`
empty when `arguments` is).

**Three: no count constraints — no `minItems`, anywhere.**

**Four: thinking is disabled** — `reasoning_effort: "none"` on every request. **Amended by
ADR-0025:** the rule is that the model's narrative about its own reasoning is never read, and the
mechanism belongs to the provider. Disabling it is how the local provider gets there, and is not
portable — on the hosted provider's model family, disabling thinking pushes reasoning into the
*visible* text, so that provider leaves it on and reads `text` blocks alone. Neither reads the
narrative, and neither has anywhere to put it.

## Alternatives rejected

- **Mark every field `required`** (the OpenAI `strict` convention). Rejected on evidence. A
  required string cannot be absent, so the decoder must emit something, and a model forced to emit
  something narrates rather than emitting `""`. Against a silent corpus the probe produced
  `position: "no_position"` beside `arguments: []` — a straight violation of the empty-when-
  descriptive rule, and a guaranteed regeneration on the cheapest case in the system. It also
  produced `contested.locus: "no controversy in passage."`, a fabricated locus in the one field
  whose entire contract is "must be one of the loci sent", sitting in a state (`is_contested:
  false`) where nothing checks it. Strict decoding manufactures the failure class the trust
  boundary exists to catch.

- **Require nothing at all, anywhere.** The first form of this decision, and wrong. Against an
  answerable question the probe returned a citation carrying only `tier` and `quote` — unresolvable,
  and check 1 fails it. Absence is meaningful *between* elements of a list, not *within* one.

- **`minItems: 1` on `arguments[].citations`.** Expressible, and the decoder honours it — a probe
  forcing two citations from one passage produced exactly two, the second a fabricated 39-character
  sub-quote. That is the argument against it: a model with a claim it cannot cite would be forced to
  invent a citation, where the unconstrained behaviour is `citations: []`, which Go already fails
  loudly on a path that exists for it. Loud-and-handled beats quiet-and-fabricated. **The constraint
  works, and that is precisely why it is not used.**

- **Leave thinking on and raise the token budget.** Rejected twice over. The `reasoning` field is
  the model's narrative about its own reasoning, which CLAUDE.md constraint 5 forbids shipping —
  and a schema-constrained probe with thinking on spent its *entire* budget in `reasoning` and
  returned `content: ""` with `finish_reason: "length"`. Leaving it on does not slow the answer
  down, it prevents there being one.

- **Put field descriptions in the schema** to fix the model treating `position` as a label. Rejected
  as a layer confusion: the schema is layer 1 and enforces shape; what a field *means* is layer 2's
  and lives in the prompt. Descriptions in the schema would put contract prose back in a second file
  — the thing decision one exists to prevent.

## Consequences

**What it makes easy.** A field added to `proto/` cannot silently go unrequested. The schema and
`json_format.ParseDict` agree on one proposition — *absent means default* — so nothing translates
between them. And the permissive form is 3–4× cheaper in tokens than the strict one on identical
input (135 vs 419 on an answerable question; 21 vs 93 on a silent one), which on CPU is the
difference between a 14-second answer and a 46-second one.

**What it makes hard.** A grammar that admits `{}` lets the model stop immediately. That case is
already specified — every slot empty with no `no_answer_reason` FAILS and regenerates — so the
degenerate output of a permissive schema lands in a designed path. It is nonetheless the empirical
risk this decision carries, and Phase 2's harness is what measures the rate.

**What would cause us to revisit it.** If a specific slot underperforms in Phase 2's golden set, the
ladder is: prompt harder; then constrain **that slot**, with the reason recorded; never restore
`required` globally. A different generator re-opens all four questions, which is why this is
re-measured alongside ADR-0018 rather than treated as settled.

## Documents updated

- `services/catena/src/catena/serve/schema.py` — the derivation, with the probe results in the
  module docstring
- `services/catena/src/catena/serve/generate/ollama.py` — `reasoning_effort: "none"`, and
  `_content` reading `content` alone (the module became a package under ADR-0025)
- `services/catena/tests/test_serve_schema.py` — `test_no_count_constraint_anywhere` guards the
  reintroduction of `minItems`
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — the Generation section records the derived
  schema, the list-only rule, and disabled thinking
- `specs/001-phase-1-pca-baseline/PLAN.md` — Task 7's constrained-decoding checkbox
- `docs/adr/0018-qwen3-8b-as-the-generation-default.md` — "Ollama's schema `format`" is now the
  OpenAI-compatible `response_format`; annotated there
