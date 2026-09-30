# The generation-failure channel — design

When the model returns something that is not an answer object, the turn currently dies inside
Catena and **takes its trace with it**. This gives that failure a channel of its own: a
`GenerationFailure` beside the answer, a `generation_failed` outcome, and a row in the trace where
today there is nothing.

It is the upstream sibling of ADR-0024. That ADR gave *answer-level* failures their own channel on
the reasoning that the four checks are per citation and everything else is per slot. A generation
that produced no object has no slots, so it needs the same treatment one layer further up.

This is a Phase 1 bug fix. It carries no provider work and nothing in it needs an API key.

## What is wrong, and it is already measured

Phase 1 acceptance ran the ten questions. Q4 and Q10 — one contested locus, one ordinary broad
doctrinal question — both **errored with no turn produced**, and ACCEPTANCE.md records what that
cost:

> Q4 and Q10 both died inside Catena with no answer object and **no row in `trace.responses`**.
> […] the consequence is that the failure Task 7 called "a Phase 2 measurement arriving early" is
> the one measurement Phase 2 cannot see, because the harness reads the trace tables and there is
> no row.

Two of ten questions produced no evidence at all. Not a degraded answer, not a failed citation — an
absence. The acceptance table could record the outcome only because a human watched it happen.

### Two causes, and both have to go

**The contract cannot express it.** `AnswerResponse` is `{AnswerObject answer, RetrievalTrace
trace}`. There is no way to return the trace without an answer, so `ServeError` becomes a gRPC
error and the `RetrievalTrace` that Catena had already built — the candidates, the filters, the
timings — is discarded on the floor.

**The schema cannot store it.** `trace.responses.answer` is `jsonb NOT NULL`. Even if the trace
arrived, the row could not be written.

Neither is a provider problem. Both fire on the pinned local default, which is what acceptance
measured.

## The decision

**A generation failure travels beside the trace and persists in a channel of its own.**

### The contract

    message AnswerResponse {
      oneof outcome {
        AnswerObject answer = 1;
        GenerationFailure generation_failure = 3;
      }
      RetrievalTrace trace = 2;   // always present
    }

A `oneof` rather than a nullable second field, because exactly one of the two is always true and a
response carrying both is not a state the system has a meaning for.

`GenerationFailure` carries a closed `GenerationFailureCode`, a factual `detail`, and the
`completion_tokens` the attempt reached before it failed. The codes are the failures that actually
exist in the request path:

| code | what happened |
| --- | --- |
| `TRUNCATED` | the completion hit the token ceiling |
| `CONTEXT_EXHAUSTED` | the model ran out of context window |
| `NOT_JSON` | the content did not parse |
| `NOT_AN_OBJECT` | it parsed to a JSON value that is not an object |
| `EMPTY` | no content, or no choices at all |
| `PROVIDER_REFUSED` | the provider declined the request on policy grounds |

**`detail` is factual and `PROVIDER_REFUSED` records the category only.** A refusal often arrives
with an explanation, and an explanation is the model's account of its own reasoning — which
CLAUDE.md constraint 5 forbids shipping. A new field is exactly how that gets in, so the rule is
stated here rather than left to be noticed: the category is recorded, the explanation is never read.

### The schema

`trace.overall_result` gains `generation_failed`. `trace.generation_failures` mirrors
`trace.answer_failures` — one row per `(request_id, attempt)`, foreign-keyed into `trace.traces`,
`code` and `detail` both non-blank.

Three columns on `trace.responses` become nullable, each tied to the new outcome by a CHECK so an
incoherent row cannot be written:

- **`answer` is NULL exactly when `overall_result = 'generation_failed'`**, and non-NULL otherwise.
- **`confidence_level` and `confidence_reason` go NULL with it.**

Both of those are load-bearing and neither is the obvious choice, so:

**Why not store `{}` for the answer.** It would avoid a nullable column, and it would be a much
worse bug than the one being fixed. An answer object with every slot empty *is* the honest-silence
shape — it means the corpus was asked and had nothing to say. ADR-0020 exists to stop a truncation
wearing that shape, and writing `{}` here would encode a generation failure as considered silence
in the one table Phase 2 reads.

**Why confidence is NULL rather than a synthetic `low`.** Go derives confidence from the
verification result, and there was no verification — nothing was checked, because there was nothing
to check. A synthetic floor value is a number Phase 2 could average without knowing it was
invented. NULL is a fact; `low` would be a fabrication with a plausible face.

### Attempts

A generation failure **consumes the one regeneration ADR-0010 grants.** So `generation_failed`
always follows exactly two attempts, and the invariant is held in the schema the way
`responses_degraded_is_second_attempt` is — symmetric with the rule ADR-0024 settled for
degradation, and the "at most two calls into Python per turn" ceiling (ADR-0002) is untouched.

The objection is real and is answered rather than hidden: at `temperature: 0` the second attempt is
frequently identical, and acceptance measured truncation as deterministic — so for that code the
retry is a wasted call. It is spent anyway, because **the second attempt is what separates
deterministic inadequacy from transient noise**, and that distinction is the finding. A failure
that reproduces exactly is a fact about the generator; one that does not is a fact about the run.

### What the user sees

A fixed string that claims nothing about the sources, because nothing was learned about them.

It is deliberately **not** "I can't source this adequately." That sentence means citations were
checked and did not hold, and constraint 3 forbids softening it. Here no citation was ever
produced, so saying it would be a false report of what the system did. Describing a different
failure honestly is not a softening of that rule.

Like the degradation text, this is a fixed string in Go's render layer, not composed prose.
ADR-0024's rule that `Confidence.reason` is the only Go-authored string a user reads was about Go
never composing prose that tells Python how to fix an answer; a constant is not that.

## Deliberately omitted

**Generation failures are not carried back to Python on the regeneration.** `AnswerRequest`
gains no sibling to `answer_failures`. ADR-0024 carries answer failures back because the model can
act on them — a named slot, a named rule. "Your output was not JSON" is feedback with no evidence
behind it, and the failure acceptance actually measured was deterministic, so there is no reason to
believe a note would change the second attempt. It is addable later if the rates say otherwise,
which is what the new trace rows are for.

## Alternatives rejected

**Keep raising, and have Go persist a trace it never received.** Go cannot: the `RetrievalTrace`
is built in Python from the retrieval it performed, and on the error path it does not exist on the
wire. Go would be inventing a row about work it did not observe.

**Reuse `answer_failures` with an empty `slot`.** The smallest change, and it breaks the premise
that makes ADR-0024 readable — every answer failure names the slot it broke, and `slot` is
`NOT NULL CHECK (btrim(slot) <> '')` precisely so that "a rule that broke somewhere unrecorded is a
finding nobody can chase." Making it optional to fit a failure that has no slot would cost every
consumer that guarantee.

**Fold it into `DEGRADED` with a distinguishing code.** The user-visible outcome is similar, and
the degradation rate stops meaning one thing. ADR-0024 was explicit that an unreachable Catena is
surfaced as an error rather than "laundering it into the degradation rate ADR-0010 needs kept
clean." The same argument forbids laundering this in.

**Raise the token ceiling instead.** Acceptance measured this three times — 2048/900s, 4096/1800s,
8192/3000s — and each raise converted truncation into timeout and bought nothing. The numbers are
in `generate.py` so the argument is not had again.

## Testing

- Each failure code returns a `GenerationFailure` rather than raising, and the `oneof` is honoured:
  never both, never neither.
- A `RetrievalTrace` is present on the failure response and carries the candidates the attempt
  actually retrieved.
- The CHECK constraints reject every incoherent row — an answer beside `generation_failed`, a
  `generation_failed` at one attempt, a non-NULL confidence on a failed generation — asserted
  through the existing `tools/db/tests/test_schema.sh` pattern.
- Go renders the fourth outcome, and persists a row for a turn that today persists nothing.
- The regeneration path: a first-attempt generation failure produces a second call, and a second
  failure produces `generation_failed` at `attempts = 2`.
- No test asserts the model's reasoning reaches any field, and a test asserts a refusal's
  explanation does not.

## Documents updated

| File | Change |
| --- | --- |
| `docs/adr/0025-generation-failures-are-their-own-channel.md` | New. Extends ADR-0024 one layer upstream; annotates ADR-0010 on what consumes the regeneration; cites ADR-0020 as the rule it protects |
| `proto/berean/v1/catena.proto` | The `oneof`, `GenerationFailure`, `GenerationFailureCode` |
| `proto/berean/v1/verification.proto` | `OVERALL_RESULT_GENERATION_FAILED` |
| `proto/README.md` | The new fields, and which are used from Phase 1 |
| `db/migrations/000006_generation_failures.*.sql` | The enum value, the table, the nullable columns and their CHECKs |
| `specs/SHARED-TECHNICAL-SPEC.md` | §3 and §7: the fourth outcome, and that a turn producing no answer still records |
| `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` | The response contract and the trace tables |
| `specs/001-phase-1-pca-baseline/ACCEPTANCE.md` | Q4 and Q10 gain a note that the invisibility is fixed — **the recorded results are not rewritten** |
| `services/catena/AGENTS.md`, `services/gateway/AGENTS.md` | Catena returns failures rather than raising; Go renders and persists the fourth outcome |

## Status

Implemented. See ADR-0025. (2026-09-30)

`specs/001-phase-1-pca-baseline/GENERATION-PROVIDERS-DESIGN.md` was waiting on this and is now
unblocked.
