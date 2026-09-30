# ADR-0025: Generation failures are their own channel

- **Status:** Accepted
- **Date:** 2026-09-30
- **Phase:** 1 — decided after Phase 1 acceptance measured the gap, and before the provider work
  that depends on it

## Context

Phase 1 acceptance ran the ten questions. Eight produced a turn. Q4 — the contested locus — and Q10
— "What does the Westminster Confession teach about justification?", an ordinary broad doctrinal
question with no contested machinery in play — produced nothing at all. Not a degraded answer, not a
failed citation: an absence. ACCEPTANCE.md records both as **error — no turn produced**, and states
what that cost:

> Q4 and Q10 both died inside Catena with no answer object and **no row in `trace.responses`**.
> […] the consequence is that the failure Task 7 called "a Phase 2 measurement arriving early" is
> the one measurement Phase 2 cannot see, because the harness reads the trace tables and there is
> no row.

Two of ten turns left no evidence. The acceptance table could name the outcome only because a human
watched it happen, and that is the whole problem: SHARED §4 makes the trace tables the eval dataset
as well as the audit log, so a failure mode with no row in them is a failure mode Phase 2 cannot
count, cannot attribute to a model or a `top_k`, and cannot show has improved. A 20% failure rate that is
invisible to the measurement apparatus is worse than a 20% failure rate, because the second one can
be worked on.

The rate is also not a tail. Both failures reproduced exactly, on the pinned local default
(ADR-0018), which is what `docker compose up` gives every reader — so this is not a hosted
provider's behaviour that a key and a different vendor would avoid.

### Two structural causes, and neither is the model's

**The contract could not express it.** `AnswerResponse` was `{AnswerObject answer, RetrievalTrace
trace}`, with no way to return the second without the first. Catena's truncation guard therefore
raised, the raise became a gRPC error, and the `RetrievalTrace` the attempt had already built — every
candidate with its real score and its exclusion reason, the embedding and generation models, the
three stage timings — was discarded along with it. The retrieval genuinely happened; Go simply never
saw that it had. SHARED §4 requires a trace for every response, and that requirement was being met
only for turns that produced one.

**The schema could not store it.** `trace.responses.answer` was `jsonb NOT NULL`, and
`confidence_level` and `confidence_reason` beside it. Even had the trace arrived on the wire, the row
recording the turn could not have been written — and `trace.traces` references
`trace.responses (request_id)`, so the per-attempt rows the trace would have filled could not have
existed either. The failure was unrecordable from the top of the schema down.

So the absence had two independent causes one layer apart, which is why it looked like a provider
problem: fixing either alone changes nothing observable.

### The shape is ADR-0024's, one layer upstream

ADR-0024 gave *answer-level* failures their own channel on the reasoning that the four checks are
per citation and every other rule Go enforces is per slot. `AnswerFailure.slot` is the premise that
makes that channel readable — `arguments[2]`, `contested.locus`, `no_answer_reason` — and the
schema holds it `NOT NULL CHECK (btrim(slot) <> '')` precisely so that a rule which broke somewhere
unrecorded is not a finding anyone has to chase.

A generation that produced no object has no slots. It is not a rule the answer broke; it is the
answer not existing. That is a sibling of `AnswerFailure` rather than a member of it, and the same
argument that separated answer-level rules from per-citation checks separates this from both.

## Decision

**A generation attempt that produced no answer object travels and persists in a channel of its
own.**

- **`AnswerResponse.outcome` is a `oneof`** of `AnswerObject answer` and `GenerationFailure
  generation_failure`. `trace` sits *outside* the oneof, so it is present on both branches: a
  response carrying both outcomes is not a state this system has a meaning for, and one carrying
  neither is a turn that did not happen.
- **`GenerationFailure`** carries a closed `GenerationFailureCode`, a factual `detail`, and
  `completion_tokens` — how far the attempt got before it failed, zero when it produced nothing.
- **`OVERALL_RESULT_GENERATION_FAILED`**, a fourth outcome, and `trace.overall_result` gains
  `generation-failed` to match.
- **`trace.generation_failures`**, one row per failed attempt, keyed to `(request_id, attempt)` like
  every other trace table, with `generation_failures_code_idx` so "which way does this generator
  fail" is a `GROUP BY` over a closed set rather than a `LIKE` over prose.
- **`trace.responses.answer`, `.confidence_level` and `.confidence_reason` become nullable**, and
  their absence is bound to the outcome by three CHECK constraints —
  `responses_answer_absent_iff_generation_failed`,
  `responses_confidence_absent_iff_generation_failed`, and
  `responses_generation_failed_is_second_attempt`. Dropping the `NOT NULL` without them would buy
  the row and give up the guarantee that every other outcome carries an answer.
- **Go renders a fixed string of its own** (`render.NoAnswer`) and never the refusal.

Six codes are defined — `TRUNCATED`, `CONTEXT_EXHAUSTED`, `NOT_JSON`, `NOT_AN_OBJECT`, `EMPTY`,
`PROVIDER_REFUSED` — of which Phase 1's provider produces four. `CONTEXT_EXHAUSTED` and
`PROVIDER_REFUSED` ship reachable-by-contract and unproduced: the local default neither declines on
policy grounds nor distinguishes an exhausted context window from a hit ceiling. They are defined
now because the enum *is* the contract, and defining the closed set once means the provider work
that follows adds a provider rather than a proto field, a migration and a `store.go` edit. Read them
as reserved, not as dead code.

### `answer` is NULL, and specifically not `{}`

This is the sub-decision the rest of the channel is built to protect.

Storing an empty JSON object would have avoided the migration entirely. It is rejected because in
this system an answer object with every slot empty is not a missing answer — it **is** the honest
non-answer's shape. ADR-0020 decided exactly that: `arguments` empty, `descriptions` empty,
`is_contested` false, `no_answer_reason` stating why, outcome `VERIFIED`, because the corpus being
silent is a pass and not a failure. UC-2 and UC-5 mean opposite things and the specs are emphatic
that collapsing them makes the degradation rate unreadable.

Writing `{}` into `trace.responses.answer` for a truncated generation would put a truncation into
the one table the Phase 2 harness reads, wearing the shape of considered silence. Nothing downstream
could separate them: the harness would see an empty answer beside a `generation-failed` outcome and
have to decide which of the two columns to trust, and a query written against the answer column —
which is where ADR-0020 put the silence — would count a runaway generator as a corpus with nothing
to say. That is a quieter and more damaging bug than the missing row, because a missing row announces
itself and a wrong row does not. NULL is the only value that says *absent* in a column whose empty
value already means something else.

### Confidence is NULL, and specifically not a synthetic `low`

`low` is available, it is the natural floor, and it would have kept two columns `NOT NULL`. It is
rejected on the rule ADR-0020 settled: **both halves of the confidence are derived by Go from the
verification result**, and there was no verification here — no object to check, so no citation
checked, so nothing for a level or a reason to be derived from. A floor value would be a number the
harness could average across a run without anything in the row disclosing that it was invented, and
`confidence_reason` would carry a sentence about a verification that never ran, in the one field
whose entire justification is that it reports what was actually found.

The same reasoning is why Go does not call the verifier with a nil answer to obtain one: a verifier
handed nothing produces findings about an answer that does not exist, and those findings would be
just as fabricated for being mechanically derived.

### A generation failure consumes ADR-0010's one regeneration

So `generation_failed` always follows exactly two attempts, and
`responses_generation_failed_is_second_attempt` holds it the way
`responses_degraded_is_second_attempt` holds the same rule for degradation — symmetric with what
ADR-0024 settled there, and ADR-0002's ceiling of at most two calls into Python per turn is
untouched.

The objection is real and is answered rather than hidden: decoding runs at `temperature: 0`, and
acceptance measured Q4's truncation as deterministic — twice, identically — so for that code the
second call is frequently minutes of generation spent reaching the same outcome. It is spent anyway,
because **the second attempt is what separates deterministic inadequacy from transient noise**, and
that distinction is the finding Phase 2 wants. A failure that reproduces exactly is a fact about the generator; one that does not is
a fact about the run, and a channel that cannot tell them apart records a rate nobody can act on.
The cost is bounded at one call and falls only on turns that were already failing.

### `detail` is factual, and that is a constraint rather than a description

`GenerationFailure.detail` says what happened — `finish_reason=length at max_tokens=2048`, the
decoder's own message, "no choices" — and never the model's account of its own reasoning. For
`PROVIDER_REFUSED` it records the provider's **category** and never its explanation. A refusal's
explanation is precisely the model's narrative about its own reasoning that CLAUDE.md constraint 5
forbids shipping, and a free-text field beside a failure is exactly how it would arrive: plausible,
unfalsifiable, and already in the trace by the time anyone asks where it came from.

This is why the channel adds no field for "why the model thinks it failed", and why `reasoning` is
still read nowhere. The rule is written into the proto, the migration, `services/catena/AGENTS.md`
and the table's own comment, because one of those is the file the next implementer opens first and
we do not know which.

## Alternatives rejected

- **Keep raising, and have Go persist the trace itself.** No contract change and no migration: let
  the gRPC error stand, and record the attempt from the gateway side. Rejected because Go cannot —
  the `RetrievalTrace` is built in Python out of the retrieval Python performed, and on the error
  path it does not exist on the wire. Go would be writing a row about candidates, scores and
  timings it never received, which is a fabricated audit record in the table whose purpose is to be
  the audit record. The evidence has to travel with the failure or it does not exist.
- **Reuse `trace.answer_failures` with an empty `slot`.** The smallest change of all: one more
  `AnswerFailureCode`, no new table, no nullable columns. Rejected because it destroys the premise
  that makes ADR-0024's channel readable. Every answer failure names the slot it broke in, and
  `slot` is non-blank by constraint precisely so that a rule breaking somewhere unrecorded is
  impossible; relaxing it to fit a failure that legitimately has no slot pays that guarantee away
  for every consumer of the table, in order to record something that is not an answer-level rule at
  all. It also mislabels the event: `answer_failures` presupposes an answer.
- **Fold it into `DEGRADED`, distinguished by a code column.** The user-visible outcome is close
  enough and the outcome enum stays at three. Rejected on the ground ADR-0024 already took for an
  unreachable Catena: `DEGRADED` means verification refused to ship something it checked, which is a
  *successful* outcome of the verification system, and laundering anything else into it makes the
  degradation rate ADR-0010 needs kept clean unreadable. Here the attempt that decided the outcome
  checked nothing, because it produced nothing — even when an earlier attempt in the same turn was
  checked and failed. A code column would mean the degradation rate could only be read correctly by
  queries that knew to filter on it, and the queries that matter are the ones nobody has written
  yet.
- **Raise the token ceiling and treat this as tuning.** Rejected on measurement, three times:
  2048/900 s truncated deterministically, 4096/1800 s truncated after 24 minutes of generation, and
  8192/3000 s stopped truncating only because the 50-minute timeout fired instead. Each raise
  converted one failure into the other. The constants were restored to 2048/900 and the numbers
  written into `generate.py` so the argument is not had again; what runs away is the
  summarising, and it scales with how much source material is in front of the model rather than with
  the ceiling.
- **Carry the failure back to Python on the regeneration**, as `AnswerRequest.answer_failures` does
  for answer-level rules. Rejected as speculative. ADR-0024 carries answer failures back because a
  model can act on them — a named slot and a named rule — whereas "your output was not JSON" is
  feedback with no evidence attached, and the failure acceptance actually measured was deterministic,
  so there is no reason to believe a note would change the second attempt. The new rows are what
  would justify adding it later, which is the right order.

## Consequences

**A fourth outcome now exists, and every document that enumerates outcomes has to carry it.** That
cost is paid once per enumerating file and is listed below; the guard against paying it wrong is that
`enumValue` derives the Postgres label from the proto constant rather than mapping it by hand, and a
unit test reads the migrations and asserts the correspondence in both directions without a database.

**The trace's central table now has nullable columns.** `trace.responses` was entirely `NOT NULL` on
the answer and the confidence, and that was a real guarantee. What replaces it is narrower but
stated: the three CHECKs make the absence and the outcome one fact, so the incoherent rows — an
answer beside `generation-failed`, a confidence beside it, a `generation-failed` at one attempt — are
unwritable rather than merely unwritten. `validate` in `internal/trace` refuses the answer-shaped
half of that a statement earlier, so a contract violation arrives as `ErrIncomplete` naming the
attempt and the field rather than as a constraint name naming a column.

**Two failure rates become countable for the first time.** How often the generator returns no usable
object, and which way — and both per model and per `top_k`, because `trace.traces` already records
those beside the failure. This is the measurement Phase 2 needs and the reason the ordering in
CLAUDE.md puts the eval harness before hybrid retrieval: a Phase 3 improvement claim is only
falsifiable against a Phase 1 number, and for this failure mode there was no number.

**`DEGRADED` keeps exactly one meaning**, and so does the honest non-answer. Three outcomes that a
user might loosely call "no answer" are now three rows a query can tell apart: the corpus was silent
(`VERIFIED` with `no_answer_reason`), verification refused to ship (`DEGRADED`), the generator
produced nothing (`GENERATION_FAILED`). The renderer says three different things for the same
reason.

**What it makes harder.** Every future consumer of `trace.responses.answer` has to handle NULL, and
a Phase 2 query that joins the answer column without an `overall_result` filter will silently drop
the failed turns — the opposite of the bug this fixes, and the one to watch for. A second closed
enum is now kept in step across the proto, the Postgres type and Go's derivation.

**What would cause us to revisit it.** If the failure rate goes to zero on a better provider and
stays there, the channel is machinery for an event that no longer happens — though the row it writes
is cheap and the measurement is the point, so the likelier revision is the other direction: if
`detail` starts being parsed by anything, it wants to become structure rather than remain prose. And
if generation failures turn out to be worth feeding back to the regeneration, that is an added field
on the request, decided by the rates these rows now record.

## Documents updated

- `proto/berean/v1/catena.proto` — `AnswerResponse.outcome` as a `oneof`, `trace` outside it,
  `GenerationFailure` and `GenerationFailureCode` added.
- `proto/berean/v1/verification.proto` — `OVERALL_RESULT_GENERATION_FAILED` added, with why it is
  distinct from `DEGRADED`.
- `proto/README.md` — the new messages listed against `catena.proto` and `verification.proto`, and
  which fields are used from Phase 1.
- `db/migrations/000006_generation_failed_outcome.up.sql` / `.down.sql` — the
  `trace.overall_result` value, alone in its own migration because Postgres forbids using a new enum
  value in the transaction that added it.
- `db/migrations/000007_generation_failures.up.sql` / `.down.sql` —
  `trace.generation_failure_code`, `trace.generation_failures`, the gateway grant, the three
  nullable columns with their CHECKs, and `responses_confidence_reason_not_blank` restating the
  non-blank rule now that the column admits NULL.
- `specs/SHARED-TECHNICAL-SPEC.md` — §3 gains the fourth outcome and the rule that a turn producing
  no answer object still records a trace row; §7 gains the requirement that the outcome be
  distinguishable from degradation in the data.
- `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` — the response contract records the `oneof`
  and that the trace is present on both branches; `OverallResult` gains its fourth value; the trace
  tables section gains `generation_failures` and the nullable columns.
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — the failure-then-regenerate-then-degrade
  paragraph is scoped to an attempt that produced an answer object, with the fourth outcome carved
  out; the retry rule restated to cover a generation failure as well as a verification failure.
- `docs/ARCHITECTURE.md` — the same failure-then-regenerate-then-degrade sentence gets the same
  scoping, so the architecture detail and the spec agree.
- `README.md` — the CLI section's outcome table gains the fourth row and its fixed string; the exit
  status paragraph covers all four outcomes.
- `.agents/skills/run-evals/SKILL.md` — a new section on tracking the generation-failure rate per
  model and per `top_k`, and a checklist item for it, matching how ADR-0020 added `no_answer_reason`
  scoring to this same file.
- `specs/001-phase-1-pca-baseline/ACCEPTANCE.md` — the UC-4/UC-10 section gains a note that the
  invisibility is fixed. **Its recorded results are untouched**: they are what one build did on one
  day, and editing them to match later code would destroy the phase's only evidence.
- `specs/001-phase-1-pca-baseline/GENERATION-FAILURE-CHANNEL-DESIGN.md` — Status closed to
  implemented.
- `docs/adr/0010-regeneration-retry-exception.md` — annotated: the single regeneration is also
  consumed by a generation failure.
- `docs/adr/0024-answer-level-failures-are-their-own-channel.md` — annotated: a generation that
  produced no object has no slot to name and travels in a sibling channel one layer upstream.
- `services/catena/src/catena/serve/generate.py` — an unusable completion returns `GenerationFailed`
  instead of raising; a transport failure still raises. The ceiling measurements were already here and
  are unchanged; what is annotated is what now happens at the ceiling. **Annotated by ADR-0026:**
  that module is now the package `services/catena/src/catena/serve/generate/`; this behaviour lives
  in both `generate/openai_chat.py` and `generate/messages.py`, one per wire format, and
  `GenerationFailed` itself is defined in `generate/__init__.py`.
- `services/catena/src/catena/serve/service.py` — the short-name-to-enum map for all six codes, and
  the failure response carrying the trace the attempt built. An unmapped code raises, because a
  programming error reported as `UNSPECIFIED` reads as a model inadequacy.
- `services/gateway/internal/turn/turn.go` — `Attempt.Failure`, the skipped verification, and the
  outcome decision: a final attempt with no object is `GENERATION_FAILED` and `Answer` stays nil.
- `services/gateway/internal/trace/store.go` — `writeGenerationFailure`, the NULL answer and
  confidence on that outcome, and `validate`'s refusal of an answer object beside it.
- `services/gateway/internal/render/render.go` — the `NoAnswer` constant, and why it shares no words
  with `Refusal`.
- `docs/adr/README.md` — the 0025 row, and the 0010 and 0024 rows annotated.
- `services/catena/AGENTS.md` — an unusable completion is reported rather than raised, and `detail`
  never carries the model's reasoning.
- `services/gateway/AGENTS.md` — the fourth outcome is rendered and persisted, and an attempt that
  produced no object is never verified.
