# ADR-0024: Answer-level failures are their own channel

- **Status:** Accepted
- **Date:** 2026-09-10
- **Phase:** 1 — decided while building the verification engine (PLAN Task 8)

## Context

`VerificationResult` is shaped for the four checks: one citation, four booleans, and a
`failure_detail` that is empty exactly when all four passed. That shape is asserted in the proto's
prose, held as a constraint on `trace.verification_results`, and read by Catena's retry prompt.

Several of the rules the trust boundary actually enforces are not about a citation. An argument
with no citations at all has none to fail. `position` stated where nothing was argued, a
`no_answer_reason` over its cap, an answer with every slot empty and no reason — none of these
names a citation either. The omission check is sharper still: **every one of the four checks
passes and the answer fails**, because a verified citation resolved to a locus's ruling while
`is_contested` was false.

So Task 8 arrived at rules the boundary must enforce, feed back to the regeneration, and persist,
and no field could carry any of them. Writing them as `VerificationResult`s would mean a row whose
four booleans all say "passed" beside a detail saying the answer did not — which
`verification_results_detail_iff_failure` rejects outright, and which
`trace.verification_results`'s non-blank `corpus_id` rejects for the rules that name no citation at
all. The failure would be enforceable and unrecordable: the regeneration would be told nothing, and
Phase 2 would find no row explaining why a turn degraded.

INTEGRATION-SPEC's line that `previous_failures` "reuses `VerificationResult` … so nothing new is
defined" was written before this set of rules was enumerated. It is a good instinct about a
narrower case than the one that exists.

## Decision

**Answer-level failures travel and persist in a channel of their own.**

- `AnswerFailure` in `verification.proto`: a closed `AnswerFailureCode`, the `slot` it broke in
  (`arguments[2]`, `contested.locus`, `no_answer_reason`), an optional `CitationRef` for the rules
  that do name a citation, and a factual `detail`.
- `AnswerRequest.answer_failures`, a sibling of `previous_failures`, carrying them back on the
  regeneration.
- `trace.answer_failures`, one row per broken rule per attempt, keyed to the attempt like every
  other trace table.

The split is by *what the rule is about*, not by severity: the four checks are per citation, and
everything else is per slot. `Confidence.reason` remains the only Go-authored string a user ever
reads — an `AnswerFailure` is verification metadata, the same as a `VerificationResult`, and Go
still composes no prose telling Python how to fix an answer.

Two consequences of Task 8 are settled here because they follow from the same reasoning.

**The tier floor on an argument is answer-level, not per-citation.** An advisory citation inside an
argument is permitted — it corroborates — and only becomes a failure when it is the argument's
whole support. That is a property of the argument, so `ARGUMENT_LACKS_AUTHORITY` is an
`AnswerFailure` and check 3 stays true of each citation on its own. A per-citation encoding would
mark a legitimate corroborating citation failed and send the regeneration hunting for a quote that
is fine.

**Degradation always follows exactly two generation attempts.** Task 3 left `degraded` free on
attempt count, saying the choice was Task 8's. `DEGRADED` means verification refused to ship, which
is a *successful* outcome of the verification system; an unreachable Catena or an unreachable
database is a failure of the system, and the gateway surfaces it as an error rather than laundering
it into the degradation rate ADR-0010 needs kept clean. Nothing else reaches degradation without
two attempts, so `responses_degraded_is_second_attempt` is now holdable and is held.

## Alternatives rejected

- **Synthesise a `VerificationResult` with an empty `citation_ref`.** No proto or schema change,
  and Catena's renderer already tolerates it (`checks or ["failed"]`). Rejected because the row
  cannot be persisted — `corpus_id` and `locator` are non-blank by constraint — so the trace would
  record that a turn failed and never what broke. That is the one thing the trace exists to record.
  It also forces a lie in the four booleans: an argument with no citations has no locator that
  failed to resolve, and telling the regeneration that one did sends it after the wrong mistake.
- **Relax `trace.verification_results` to accept them.** Allow a blank ref and rewrite
  detail-iff-failure. Smaller than a new channel, and it costs the constraint that currently makes
  an unexplained failure unrecordable — the strongest guarantee in that table. It also leaves the
  four booleans meaning "not applicable" for some rows and "failed" for others, with no column
  saying which.
- **Enforce these rules and feed nothing back.** Regenerate on an answer-level failure with an
  empty `previous_failures`. The retry then works blind against a rule it cannot see, and ADR-0010
  bought the retry precisely on the argument that a failure is frequently fixed *once the model is
  told what failed*.
- **Let Go rewrite the answer instead of failing it** — drop the offending argument, empty the
  `position`. Rejected on ADR-0019's and INTEGRATION-SPEC's shared ground: a verifier that edits
  what it verifies is no longer a verifier, and the trust boundary must not become an author.

## Consequences

The retry prompt now renders two lists. Catena's rendering of them is still Python's own wording
over fields Go filled in, which is what keeps `Confidence.reason` the only Go-authored string.

Phase 2 gains a countable question it did not have: *which rule does this generator break most
often?* `answer_failures_code_idx` exists for exactly that, and it is a `GROUP BY` rather than a
`LIKE` because the code set is closed. UC-4's "flagged contested and resolved it anyway" and UC-2's
"truncated to nothing" become separate numbers rather than two shapes of the same degradation.

The cost is a second enum kept in step across three places — the proto, the Postgres type, and the
Go switch. `test_proto_contract.py` names every code, so adding one to the proto without a matching
`trace.answer_failure_code` value fails a unit test rather than an insert in production.

We would revisit this if the set of answer-level rules collapsed to one or two — at which point
folding them back into `VerificationResult` with an explicit "which kind of finding is this" column
would cost less than a table.

## Documents updated

- `proto/berean/v1/verification.proto` — `AnswerFailure` and `AnswerFailureCode` added.
- `proto/berean/v1/catena.proto` — `AnswerRequest.answer_failures` added, field 8.
- `db/migrations/000003_answer_failures.up.sql` / `.down.sql` — `trace.answer_failure_code`,
  `trace.answer_failures`, the gateway grant, and `responses_degraded_is_second_attempt` on
  `trace.responses`.
- `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` — the request table now lists
  `answer_failures`; the verification result contract gains the answer-failure contract; the
  paragraph claiming the retry defines nothing new is corrected; the degradation rule is stated.
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — the Verification section distinguishes the
  four per-citation checks from the answer-level rules, and states where each is recorded.
- `specs/001-phase-1-pca-baseline/PLAN.md` — Task 8's checklist and its decisions section; Task 9's
  note that `answer_failures` is one of the tables it writes.
- `services/gateway/AGENTS.md` — the two kinds of finding, and that an outage is an error rather
  than a degraded answer.
- `services/catena/src/catena/serve/prompt.py` — `render_failures` takes both lists.
