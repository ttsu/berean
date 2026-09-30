# The Generation-Failure Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A turn whose generation produced no answer object records a trace row and a distinct
outcome instead of dying inside Catena and taking its evidence with it.

**Architecture:** `AnswerResponse` becomes a `oneof` — an answer or a generation failure, with the
trace always present. Catena returns failures instead of raising; Go records them per attempt,
decides a fourth `OverallResult`, and persists a row where today it persists nothing.

**Tech Stack:** protobuf (buf), Python 3.12 (`unittest`, run as scripts), Go 1.x, PostgreSQL 17 via
golang-migrate.

**Spec:** [GENERATION-FAILURE-CHANNEL-DESIGN.md](GENERATION-FAILURE-CHANNEL-DESIGN.md) — read it
before Task 1. The plan argues from it and does not repeat its reasoning.

## Global Constraints

- **No corpus text in this repository — none, from any source, whatever its licence.** Not in
  source, fixtures, test data, or documentation. Test fixtures use stubs like `{"position": "p"}`.
- **Never ship model introspection.** The model's narrative about its own reasoning is never read,
  returned, traced, or stored. `PROVIDER_REFUSED` records the provider's *category* only — never its
  explanation. There must be no path.
- **An empty answer object is the honest-silence shape.** A generation failure must never be able to
  wear it. `answer` is NULL for a generation failure, never `{}` (ADR-0020).
- **Nothing in Catena retries.** Go owns exactly one regeneration (ADR-0010), and a generation
  failure consumes that same one — so `generation_failed` always has `attempts = 2`.
- **At most two calls into Python per turn** (ADR-0002). This change adds none.
- **Nothing renders unverified** (SHARED §3). This change adds an outcome in which nothing renders
  at all; it never adds one in which something unverified does.
- `docker compose up` must work with no external accounts. No task here needs a key or a network.
- Tests are `unittest` run as scripts: `uv run --project services/catena python
  services/catena/tests/test_x.py -q`. Full suites: `make test-catena`, `make test-gateway`,
  `make check`. Do **not** run `ruff` — configured but not installed, and no target invokes it.
- Go tests: `go test ./services/gateway/...`. Schema assertions: `./tools/db/tests/test_schema.sh`
  (needs `make dev`).
- Python line length 100. Test classes are named as sentences about behaviour; a test whose reason is
  not obvious from its name carries a docstring giving the reason.

---

### Task 1: The contract

**Files:**
- Modify: `proto/berean/v1/catena.proto:76-79`
- Modify: `proto/berean/v1/verification.proto:39-51`
- Modify: `gen/` and `services/catena/gen/` (regenerated, committed — ADR-0022)
- Modify: `services/catena/tests/fakes.py`
- Modify: Go and Python sites that construct `AnswerResponse` (Step 5 finds them)

**Interfaces:**
- Produces:
  - `bereanv1.AnswerResponse` with `oneof outcome { AnswerObject answer = 1; GenerationFailure generation_failure = 3; }` and `RetrievalTrace trace = 2`
  - `bereanv1.GenerationFailure` — fields `code`, `detail`, `completion_tokens`
  - `bereanv1.GenerationFailureCode` — 7 values, listed below
  - `bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED` = 4

- [ ] **Step 1: Add the failure message to `catena.proto`**

Replace `message AnswerResponse { ... }` at `proto/berean/v1/catena.proto:76-79` with:

```proto
message AnswerResponse {
  // Exactly one. A response carrying both is not a state this system has a
  // meaning for, and one carrying neither is a turn that did not happen.
  oneof outcome {
    AnswerObject answer = 1;
    GenerationFailure generation_failure = 3;
  }

  // Always present, on both branches. The trace is the evidence of the
  // retrieval that happened, and a failed generation performed one — losing it
  // is the defect this channel exists to fix.
  RetrievalTrace trace = 2;
}

// Why no answer object was produced. The upstream sibling of `AnswerFailure`:
// that one names the slot a rule broke in, and a generation with no object has
// no slots (ADR-0024, ADR-0025).
message GenerationFailure {
  GenerationFailureCode code = 1;

  // What happened, factually. Never the model's account of its own reasoning:
  // for a refusal this is the provider's category and never its explanation,
  // which is exactly the introspection CLAUDE.md constraint 5 forbids and
  // exactly the kind of field it would enter through.
  string detail = 2;

  // How far the attempt got before it failed. Zero when it produced nothing.
  int32 completion_tokens = 3;
}

enum GenerationFailureCode {
  GENERATION_FAILURE_CODE_UNSPECIFIED = 0;
  // The completion hit the token ceiling. Measured as deterministic on the
  // Phase 1 default; raising the ceiling converts it into a timeout and buys
  // nothing (see generate.py, and ACCEPTANCE.md).
  GENERATION_FAILURE_CODE_TRUNCATED = 1;
  // The model ran out of context window rather than out of ceiling.
  GENERATION_FAILURE_CODE_CONTEXT_EXHAUSTED = 2;
  // The content did not parse as JSON.
  GENERATION_FAILURE_CODE_NOT_JSON = 3;
  // It parsed to a JSON value that is not an object.
  GENERATION_FAILURE_CODE_NOT_AN_OBJECT = 4;
  // No content, or no choices at all.
  GENERATION_FAILURE_CODE_EMPTY = 5;
  // The provider declined the request on policy grounds. The category is
  // recorded in `detail`; the explanation is never read.
  GENERATION_FAILURE_CODE_PROVIDER_REFUSED = 6;
}
```

- [ ] **Step 2: Add the outcome to `verification.proto`**

After `OVERALL_RESULT_DEGRADED = 3;` at `proto/berean/v1/verification.proto:50`, add:

```proto
  // The generator produced no answer object across both attempts. Distinct from
  // DEGRADED on purpose: DEGRADED means verification refused to ship something
  // it checked, and the degradation rate ADR-0010 needs kept clean must not mix
  // the two. Nothing was checked here, because nothing was produced.
  OVERALL_RESULT_GENERATION_FAILED = 4;
```

- [ ] **Step 3: Regenerate and lint the contract**

```bash
make proto-lint && make proto
```

Expected: `proto-lint: OK`, then regeneration writes `gen/` and `services/catena/gen/`. Both are
committed (ADR-0022) — commit exactly what it writes, and never hand-edit a generated file.

- [ ] **Step 4: Verify the generated Python and Go surfaces**

```bash
uv run --project services/catena python -c "
import sys; sys.path.insert(0,'services/catena/gen')
from berean.v1 import catena_pb2, verification_pb2
r = catena_pb2.AnswerResponse()
print('oneof fields:', [f.name for f in r.DESCRIPTOR.oneofs[0].fields])
print('codes:', len(catena_pb2.GenerationFailureCode.keys()))
print('new outcome:', verification_pb2.OVERALL_RESULT_GENERATION_FAILED)
"
go build ./... && echo "go build: OK"
```

Expected: oneof fields `['answer', 'generation_failure']`, 7 codes, outcome `4`, and the Go build
either succeeds or fails only at construction sites — which Step 5 fixes.

- [ ] **Step 5: Fix every construction site the oneof broke**

Moving `answer` into a `oneof` keeps every *reader* working (`GetAnswer()` in Go, `.answer` in
Python) and breaks *writers*. In Go a struct literal `&bereanv1.AnswerResponse{Answer: x}` must
become `&bereanv1.AnswerResponse{Outcome: &bereanv1.AnswerResponse_Answer{Answer: x}}`.

Find them all:

```bash
grep -rn "AnswerResponse{" --include=*.go services/ | grep -v "\.pb\.go"
grep -rn "AnswerResponse(" services/catena/ --include=*.py | grep -v "/gen/"
```

Fix each. In Python, prefer `response.answer.CopyFrom(obj)` over constructor keywords. Then rerun
`go build ./...` and `make test-catena` until both are clean — this step is done when the tree
compiles and the existing suites pass **unchanged in behaviour**.

- [ ] **Step 6: Run every existing suite**

```bash
make check
```

Expected: PASS. This task changes no behaviour — it widens the contract. A failing assertion here
means a writer was missed, not that an expectation was wrong.

- [ ] **Step 7: Commit**

```bash
git add proto/ gen/ services/catena/gen/ services/catena/tests/fakes.py services/ 
git commit -m "Contract: a generation failure is a response, not an error

AnswerResponse becomes a oneof so the trace can come back without an answer.
A failed generation performed retrieval, and discarding that evidence is the
defect this channel exists to fix (ACCEPTANCE.md, Q4 and Q10)."
```

---

### Task 2: The schema

**Files:**
- Create: `db/migrations/000006_generation_failed_outcome.up.sql`
- Create: `db/migrations/000006_generation_failed_outcome.down.sql`
- Create: `db/migrations/000007_generation_failures.up.sql`
- Create: `db/migrations/000007_generation_failures.down.sql`
- Modify: `tools/db/tests/test_schema.sh`

**Interfaces:**
- Produces: `trace.overall_result` value `generation_failed`; `trace.generation_failure_code` enum;
  `trace.generation_failures` table; `trace.responses.answer`/`confidence_level`/`confidence_reason`
  nullable with CHECKs binding them to the outcome

**SQL enum labels in this schema are kebab-case, not snake_case.** `enumValue` in
`services/gateway/internal/trace/store.go:291` derives a label from the proto constant by lowercasing
and mapping `_` to `-`, and `trace.answer_failure_code` follows it — `'citations-required'`,
`'argument-lacks-authority'`, twelve of them. So the new labels are `'generation-failed'`,
`'context-exhausted'`, `'not-json'`, `'not-an-object'`, `'provider-refused'`. Every literal below is
written that way. **If the enum-agreement test fails, the label is wrong — never `enumValue` and
never the test**: changing either would break all twelve existing labels.

**Why two migrations and not one.** golang-migrate runs each file in a transaction. PostgreSQL 17
permits `ALTER TYPE ... ADD VALUE` inside a transaction but **forbids using the new value in that
same transaction** — and a CHECK constraint containing the literal `'generation-failed'` casts it at
DDL time. One file would fail at `make dev` on a clean clone. Splitting is the whole fix; do not
merge them back.

- [ ] **Step 1: Write migration 000006 — the enum value only**

`db/migrations/000006_generation_failed_outcome.up.sql`:

```sql
-- The fourth outcome: the generator produced no answer object across both
-- attempts. Alone in its own migration because Postgres forbids using a new
-- enum value in the transaction that added it, and 000007's CHECK constraints
-- cast this literal at DDL time.
ALTER TYPE trace.overall_result ADD VALUE IF NOT EXISTS 'generation-failed';
```

`db/migrations/000006_generation_failed_outcome.down.sql`:

```sql
-- Postgres cannot drop an enum value. The down migration is deliberately empty
-- rather than silently recreating the type: rebuilding `trace.overall_result`
-- would require dropping and recreating every column that uses it, which on a
-- table holding real traces is a data-loss operation dressed as a rollback.
-- Rolling back past 000006 leaves an unused value in the enum, which is inert.
SELECT 1;
```

- [ ] **Step 2: Write migration 000007 — the table and the constraints**

`db/migrations/000007_generation_failures.up.sql`:

```sql
-- Why no answer object was produced, one row per attempt. The upstream sibling
-- of trace.answer_failures: that table names the slot a rule broke in, and a
-- generation with no object has no slots (ADR-0024, ADR-0025).
CREATE TYPE trace.generation_failure_code AS ENUM (
    'truncated',
    'context-exhausted',
    'not-json',
    'not-an-object',
    'empty',
    'provider-refused'
);

CREATE TABLE trace.generation_failures (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    request_id uuid NOT NULL,
    attempt smallint NOT NULL,

    code trace.generation_failure_code NOT NULL,

    -- What happened, factually. Never the model's account of its own
    -- reasoning: for 'provider_refused' this is the provider's category and
    -- never its explanation (CLAUDE.md constraint 5).
    detail text NOT NULL CHECK (btrim(detail) <> ''),

    -- How far the attempt got. Zero when it produced nothing.
    completion_tokens integer NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),

    FOREIGN KEY (request_id, attempt)
        REFERENCES trace.traces (request_id, attempt) ON DELETE CASCADE
);

CREATE INDEX generation_failures_code_idx ON trace.generation_failures (code);

-- A turn that produced no answer object has no answer and no confidence, and
-- both absences have to be recordable as absences.
--
-- `answer` is nullable rather than storing '{}'. An answer object with every
-- slot empty IS the honest-silence shape -- the corpus was asked and had
-- nothing to say -- so writing '{}' here would encode a truncation as
-- considered silence in the one table the Phase 2 harness reads, which is a
-- worse bug than the one being fixed (ADR-0020).
--
-- `confidence` follows it. Go derives confidence from the verification result
-- and there was no verification, so a synthetic 'low' would be a number the
-- harness could average without knowing it was invented.
ALTER TABLE trace.responses
    ALTER COLUMN answer DROP NOT NULL,
    ALTER COLUMN confidence_level DROP NOT NULL,
    ALTER COLUMN confidence_reason DROP NOT NULL;

-- The absences and the outcome are one fact, so they cannot be recorded apart.
ALTER TABLE trace.responses
    ADD CONSTRAINT responses_answer_absent_iff_generation_failed
        CHECK ((answer IS NULL) = (overall_result = 'generation-failed')),
    ADD CONSTRAINT responses_confidence_absent_iff_generation_failed
        CHECK ((confidence_level IS NULL) = (overall_result = 'generation-failed')
               AND (confidence_reason IS NULL) = (overall_result = 'generation-failed')),
    -- Symmetric with responses_degraded_is_second_attempt: a generation failure
    -- consumes the one regeneration ADR-0010 grants, so it always follows two.
    ADD CONSTRAINT responses_generation_failed_is_second_attempt
        CHECK (overall_result <> 'generation-failed' OR attempts = 2);

-- The non-blank check has to stop applying to NULL, which it already does, but
-- the original column carried it as a column constraint on a NOT NULL column.
-- Restated so a blank string is still rejected when a reason is present.
ALTER TABLE trace.responses
    DROP CONSTRAINT IF EXISTS responses_confidence_reason_check,
    ADD CONSTRAINT responses_confidence_reason_not_blank
        CHECK (confidence_reason IS NULL OR btrim(confidence_reason) <> '');
```

`db/migrations/000007_generation_failures.down.sql`:

```sql
ALTER TABLE trace.responses
    DROP CONSTRAINT IF EXISTS responses_confidence_reason_not_blank,
    DROP CONSTRAINT IF EXISTS responses_generation_failed_is_second_attempt,
    DROP CONSTRAINT IF EXISTS responses_confidence_absent_iff_generation_failed,
    DROP CONSTRAINT IF EXISTS responses_answer_absent_iff_generation_failed;

-- Rows with a NULL answer cannot survive the NOT NULL coming back, and they are
-- exactly the rows this feature added. Deleting them is correct for a rollback
-- and is stated rather than left to a constraint violation at 3am.
DELETE FROM trace.responses WHERE answer IS NULL;

ALTER TABLE trace.responses
    ADD CONSTRAINT responses_confidence_reason_check
        CHECK (btrim(confidence_reason) <> ''),
    ALTER COLUMN confidence_reason SET NOT NULL,
    ALTER COLUMN confidence_level SET NOT NULL,
    ALTER COLUMN answer SET NOT NULL;

DROP TABLE IF EXISTS trace.generation_failures;
DROP TYPE IF EXISTS trace.generation_failure_code;
```

- [ ] **Step 2a: Verify the original constraint's real name before relying on it**

The `DROP CONSTRAINT IF EXISTS responses_confidence_reason_check` above guesses the name Postgres
generated for the inline `CHECK (btrim(confidence_reason) <> '')`. Confirm it:

```bash
docker compose exec -T postgres psql -U postgres -d berean -c \
  "SELECT conname FROM pg_constraint WHERE conrelid = 'trace.responses'::regclass AND contype = 'c';"
```

Use the name it prints. If it differs, correct both migration files before continuing.

- [ ] **Step 3: Apply the migrations**

```bash
make dev
```

Expected: the `migrate` service completes successfully. If 000007 fails on the enum literal, 000006
did not apply first — check the file numbering rather than merging them.

- [ ] **Step 4: Assert the constraints reject incoherent rows**

Add to `tools/db/tests/test_schema.sh`, in the style of the assertions already there: four cases
that must all be **rejected**, and one that must be accepted.

```sql
-- Rejected: an answer alongside generation_failed
INSERT INTO trace.responses (request_id, profile, query, answer, overall_result,
    confidence_level, confidence_reason, attempts, gateway_version)
VALUES (gen_random_uuid(), 'pca', 'q', '{}'::jsonb, 'generation-failed',
    NULL, NULL, 2, 'test');

-- Rejected: generation_failed at one attempt
INSERT INTO trace.responses (request_id, profile, query, answer, overall_result,
    confidence_level, confidence_reason, attempts, gateway_version)
VALUES (gen_random_uuid(), 'pca', 'q', NULL, 'generation-failed',
    NULL, NULL, 1, 'test');

-- Rejected: a confidence on a failed generation
INSERT INTO trace.responses (request_id, profile, query, answer, overall_result,
    confidence_level, confidence_reason, attempts, gateway_version)
VALUES (gen_random_uuid(), 'pca', 'q', NULL, 'generation-failed',
    'low', 'because', 2, 'test');

-- Rejected: a NULL answer on a degraded turn
INSERT INTO trace.responses (request_id, profile, query, answer, overall_result,
    confidence_level, confidence_reason, attempts, gateway_version)
VALUES (gen_random_uuid(), 'pca', 'q', NULL, 'degraded',
    'low', 'because', 2, 'test');

-- Accepted: the shape this feature writes
INSERT INTO trace.responses (request_id, profile, query, answer, overall_result,
    confidence_level, confidence_reason, attempts, gateway_version)
VALUES (gen_random_uuid(), 'pca', 'q', NULL, 'generation-failed',
    NULL, NULL, 2, 'test');
```

- [ ] **Step 4a: Extend the proto/SQL enum-agreement test, which this task breaks**

`services/gateway/internal/trace/store_test.go:69` has `TestEnumValuesMatchTheSchema` — a
table-driven test that reads a migration file and asserts every proto enum constant has a matching
SQL label. Two things break it:

1. Its `overall result` row reads `000002_trace_schema.up.sql`, which will not contain
   `generation_failed` — that arrives via `ALTER TYPE` in `000006`. The helper `declaredLabels` parses
   `CREATE TYPE ... AS ENUM (...)` and must also pick up `ALTER TYPE ... ADD VALUE`, reading both
   files for that row.
2. There is no row for the new code enum. Add one:

```go
		{"generation failure code", "000007_generation_failures.up.sql", "generation_failure_code",
			"GENERATION_FAILURE_CODE_", bereanv1.GenerationFailureCode_name},
```

Run `go test ./services/gateway/internal/trace/ -run TestEnumValuesMatchTheSchema -v` and expect
PASS. This test is the reason a proto value with no SQL label cannot ship — do not weaken it to get
past this step.

- [ ] **Step 5: Run the schema assertions**

```bash
./tools/db/tests/test_schema.sh
```

Expected: PASS, with the four rejections rejected and the acceptance accepted.

- [ ] **Step 6: Verify the rollback**

```bash
docker compose run --rm migrate down 1 && docker compose run --rm migrate down 1
docker compose run --rm migrate up
./tools/db/tests/test_schema.sh
```

Expected: both downs succeed, the re-up succeeds, assertions pass again. A migration that cannot
roll back is not finished.

- [ ] **Step 7: Commit**

```bash
git add db/migrations/ tools/db/tests/test_schema.sh
git commit -m "Schema: record a turn that produced no answer object

answer, confidence_level and confidence_reason go nullable, each bound to the
new outcome by a CHECK so the absences and the outcome cannot be recorded
apart. Storing '{}' instead would encode a truncation as the honest-silence
shape in the one table the Phase 2 harness reads (ADR-0020).

Two migrations because Postgres forbids using a new enum value in the
transaction that added it, and 000007's CHECKs cast the literal at DDL time."
```

---

### Task 3: Catena returns failures instead of raising

**Files:**
- Modify: `services/catena/src/catena/serve/generate.py`
- Modify: `services/catena/src/catena/serve/service.py:95-122`
- Modify: `services/catena/tests/test_serve_generate.py`
- Modify: `services/catena/tests/test_serve_service.py`

**Interfaces:**
- Consumes: `bereanv1.GenerationFailure`, `bereanv1.GenerationFailureCode` from Task 1
- Produces:
  - `catena.serve.generate.GenerationFailed` — frozen dataclass, fields `code: str`,
    `detail: str`, `completion_tokens: int`. `code` is the enum's short name (`"truncated"`,
    `"not_json"`, …) so this module needs no proto import.
  - `OllamaGenerator.generate(...) -> Generation | GenerationFailed` — no longer raises for the six
    failure classes; still raises `ServeError` for transport failures, which are *not* generation
    failures
  - `CatenaService.Answer` sets `generation_failure` on the response and always sets `trace`

- [ ] **Step 1: Write the failing tests for the generator**

In `services/catena/tests/test_serve_generate.py`, replace the `WhatItRefusesToAccept` class's
four raising assertions with returns. Keep `test_a_transport_failure_is_an_error_naming_the_service`
raising — a transport failure is not a generation failure.

```python
class WhatItReportsRatherThanRaising(unittest.TestCase):
    """The six failures that are the model's, not the transport's.

    Each one used to raise, which killed the turn inside Catena and discarded
    the RetrievalTrace with it — no row in `trace.responses`, and the failure
    invisible to the Phase 2 harness (ACCEPTANCE.md, Q4 and Q10).
    """

    def test_a_truncated_generation_is_reported(self) -> None:
        transport = FakeTransport(completion('{"position": "p"}', finish="length"))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertIsInstance(result, generate_module.GenerationFailed)
        self.assertEqual(result.code, "truncated")

    def test_content_that_is_not_json_is_reported(self) -> None:
        transport = FakeTransport(completion("I'm afraid I can't do that."))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.code, "not_json")

    def test_content_that_is_not_an_object_is_reported(self) -> None:
        transport = FakeTransport(completion('["a list"]'))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.code, "not_an_object")

    def test_a_response_with_no_choices_is_reported(self) -> None:
        transport = FakeTransport({"model": "m", "choices": []})
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.code, "empty")

    def test_a_failure_carries_how_far_it_got(self) -> None:
        """The trace records it, so a deterministic ceiling is visible as one."""
        transport = FakeTransport(completion('{"position": "p"}', finish="length"))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.completion_tokens, 22)

    def test_a_failure_detail_never_carries_the_models_reasoning(self) -> None:
        """Constraint 5, at the field most likely to leak it.

        `reasoning` is present on the response and must not reach `detail`,
        which is a factual description of what broke.
        """
        transport = FakeTransport(
            completion("not json", reasoning="First I considered the passages..."))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertNotIn("considered", result.detail)

    def test_a_transport_failure_still_raises(self) -> None:
        """Not a generation failure. The model never answered, so there is no
        attempt to record and nothing about the generator was learned."""
        transport = FakeTransport(error=OSError("connection refused"))
        with self.assertRaises(ServeError):
            generator(transport).generate(MESSAGES, SCHEMA)
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate.py -q
```

Expected: FAIL with `AttributeError: module ... has no attribute 'GenerationFailed'`.

- [ ] **Step 3: Implement `GenerationFailed` and the return paths**

In `generate.py`, add beside `Generation`:

```python
@dataclass(frozen=True)
class GenerationFailed:
    """No answer object, and why. Returned rather than raised.

    Raising killed the turn inside this service and discarded the
    `RetrievalTrace` with it, so the failure left no row in `trace.responses`
    and was invisible to the harness that reads them (ACCEPTANCE.md, Q4 and
    Q10). The code is the proto enum's short name; this module imports no
    proto — `service.py` maps it.
    """

    code: str
    #: Factual. Never the model's account of its own reasoning: for a refusal
    #: this is the provider's category, never its explanation (constraint 5).
    detail: str
    completion_tokens: int = 0
```

Change `_parse` and `_content` to return `GenerationFailed` instead of raising, for the six classes.
The truncation branch becomes:

```python
        usage = response.get("usage") or {}
        completion_tokens = int(usage.get("completion_tokens", 0))

        if choice.get("finish_reason") == "length":
            return GenerationFailed(
                code="truncated",
                detail=f"finish_reason=length at max_tokens={self._max_tokens}",
                completion_tokens=completion_tokens,
            )
```

and `_content`'s two raises become `GenerationFailed(code="not_json", ...)` and
`GenerationFailed(code="not_an_object", ...)`, each with a factual `detail` that quotes the parse
error or the type name and **never** the content or the `reasoning` field. Update the `generate`
return annotation to `Generation | GenerationFailed`.

Leave the `urllib.error.HTTPError` and generic-exception branches raising `ServeError` unchanged.

- [ ] **Step 4: Run to verify they pass**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate.py -q
```

Expected: PASS.

- [ ] **Step 5: Write the failing test for the service**

In `services/catena/tests/test_serve_service.py`, add a class asserting the response shape. Use the
file's existing fakes; a generator stub returning `GenerationFailed` replaces the one returning
`Generation`.

```python
class WhenTheGenerationProducesNoObject(unittest.TestCase):
    def test_the_response_carries_the_failure_and_the_trace(self) -> None:
        """The trace is the point. A failed generation still did the retrieval,
        and discarding that evidence is the defect this channel fixes."""
        response = self._answer_with_failure()
        self.assertEqual(response.WhichOneof("outcome"), "generation_failure")
        self.assertEqual(
            response.generation_failure.code,
            catena_pb2.GENERATION_FAILURE_CODE_TRUNCATED,
        )
        self.assertTrue(response.HasField("trace"))
        self.assertGreater(len(response.trace.included_candidates), 0)

    def test_no_answer_object_is_set(self) -> None:
        """Not an empty AnswerObject: that is the honest-silence shape and it
        means the opposite thing (ADR-0020)."""
        response = self._answer_with_failure()
        self.assertFalse(response.HasField("answer"))
```

Add `_answer_with_failure` as a helper on the class, building the service with a generator stub
whose `generate` returns `generate.GenerationFailed(code="truncated", detail="d",
completion_tokens=7)` and calling `Answer` exactly as the existing tests do.

- [ ] **Step 6: Run to verify it fails**

```bash
uv run --project services/catena python services/catena/tests/test_serve_service.py -q
```

Expected: FAIL — the service does not yet branch on the result type.

- [ ] **Step 7: Branch in `service.py`**

Around the existing `self._generator.generate(...)` call at `service.py:95-102`, branch on the
result. Add a module-level mapping beside the imports:

```python
#: The short names `generate` reports, mapped to the contract's enum. The
#: mapping lives here because `generate` imports no proto — the wire format is
#: this layer's business, not the provider's.
_FAILURE_CODES = {
    "truncated": catena_pb2.GENERATION_FAILURE_CODE_TRUNCATED,
    "context_exhausted": catena_pb2.GENERATION_FAILURE_CODE_CONTEXT_EXHAUSTED,
    "not_json": catena_pb2.GENERATION_FAILURE_CODE_NOT_JSON,
    "not_an_object": catena_pb2.GENERATION_FAILURE_CODE_NOT_AN_OBJECT,
    "empty": catena_pb2.GENERATION_FAILURE_CODE_EMPTY,
    "provider_refused": catena_pb2.GENERATION_FAILURE_CODE_PROVIDER_REFUSED,
}
```

When the result is a `GenerationFailed`, build the response with `generation_failure` set from the
map and `trace` set from the same `RetrievalTrace` the success path builds, close the Langfuse
observation with the failure recorded as output, and return. Do not set `answer`.

A code absent from the map is a programming error, not a model failure: raise `ServeError` naming
the code rather than defaulting to `UNSPECIFIED`, which would report a bug as a model inadequacy.

- [ ] **Step 8: Run both suites**

```bash
make test-catena
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add services/catena/src/catena/serve/generate.py \
        services/catena/src/catena/serve/service.py \
        services/catena/tests/test_serve_generate.py \
        services/catena/tests/test_serve_service.py
git commit -m "Catena: report a failed generation instead of raising

The six failures that are the model's are returned with the trace beside
them. A transport failure still raises: the model never answered, so nothing
about the generator was learned and there is no attempt to record."
```

---

### Task 4: Go decides the outcome

**Files:**
- Modify: `services/gateway/internal/turn/turn.go:83-190`
- Modify: `services/gateway/internal/turn/turn_test.go`

**Interfaces:**
- Consumes: `bereanv1.AnswerResponse.GetGenerationFailure()`, `bereanv1.GenerationFailure`
- Produces:
  - `turn.Attempt` gains `Failure *bereanv1.GenerationFailure` — nil when the attempt produced an
    answer
  - `turn.Turn.Overall` can be `OVERALL_RESULT_GENERATION_FAILED`, with `Turn.Answer` nil

- [ ] **Step 1: Write the failing tests**

In `turn_test.go`, using the file's existing fake generator and verifier:

```go
// A generation failure on both attempts is its own outcome, not a degradation.
// Degradation means verification refused to ship something it checked; nothing
// was checked here (ADR-0024, ADR-0025).
func TestGenerationFailureOnBothAttempts(t *testing.T) {
	// fake generator returns a GenerationFailure response twice
	result := mustAsk(t, runnerReturningFailures(2))

	if result.Overall != bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED {
		t.Fatalf("Overall = %v, want GENERATION_FAILED", result.Overall)
	}
	if result.Answer != nil {
		t.Fatalf("Answer = %v, want nil — an empty AnswerObject is the honest-silence shape", result.Answer)
	}
	if len(result.Attempts) != 2 {
		t.Fatalf("Attempts = %d, want 2 — a generation failure consumes the one regeneration", len(result.Attempts))
	}
	for i, a := range result.Attempts {
		if a.Failure == nil {
			t.Errorf("attempt %d: Failure = nil, want the recorded failure", i+1)
		}
		if a.Trace == nil {
			t.Errorf("attempt %d: Trace = nil — the trace is the point", i+1)
		}
	}
}

// The regeneration still works: a failed first attempt then a verified second
// is REGENERATED, exactly as a failed verification then a verified second is.
func TestGenerationFailureThenVerified(t *testing.T) {
	result := mustAsk(t, runnerFailingThenVerifying())

	if result.Overall != bereanv1.OverallResult_OVERALL_RESULT_REGENERATED {
		t.Fatalf("Overall = %v, want REGENERATED", result.Overall)
	}
	if result.Answer == nil {
		t.Fatal("Answer = nil, want the verified answer")
	}
}

// The outcome describes the final attempt. A first attempt that failed
// verification and a second that produced no object at all ends as
// GENERATION_FAILED: there was nothing to refuse to ship.
func TestFailedVerificationThenGenerationFailure(t *testing.T) {
	result := mustAsk(t, runnerUnverifiedThenFailing())

	if result.Overall != bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED {
		t.Fatalf("Overall = %v, want GENERATION_FAILED", result.Overall)
	}
}

// A generation failure is never verified. Calling the verifier with a nil
// answer would produce failures about an object that does not exist.
func TestAGenerationFailureIsNotVerified(t *testing.T) {
	spy := &countingVerifier{}
	_ = mustAskWith(t, runnerReturningFailures(2), spy)

	if spy.calls != 0 {
		t.Fatalf("verifier called %d times, want 0", spy.calls)
	}
}
```

Write `runnerReturningFailures`, `runnerFailingThenVerifying`, `runnerUnverifiedThenFailing`,
`countingVerifier`, `mustAsk` and `mustAskWith` as small helpers in the test file, following the
fakes already there. A failure response is built as:

```go
&bereanv1.AnswerResponse{
	Outcome: &bereanv1.AnswerResponse_GenerationFailure{
		GenerationFailure: &bereanv1.GenerationFailure{
			Code:             bereanv1.GenerationFailureCode_GENERATION_FAILURE_CODE_TRUNCATED,
			Detail:           "finish_reason=length at max_tokens=2048",
			CompletionTokens: 2048,
		},
	},
	Trace: &bereanv1.RetrievalTrace{ /* as the existing fakes build it */ },
}
```

- [ ] **Step 2: Run to verify they fail**

```bash
go test ./services/gateway/internal/turn/ -run 'Generation|FailedVerification' -v
```

Expected: FAIL — `Attempt` has no field `Failure`.

- [ ] **Step 3: Implement**

Add to the `Attempt` struct:

```go
	// Why this attempt produced no answer object, or nil when it produced one.
	// Never set alongside Answer: the contract's oneof makes both impossible
	// and this mirrors it.
	Failure *bereanv1.GenerationFailure
```

In `Ask`, immediately after the `err` check on the generator call and **before** `answer :=
response.GetAnswer()`:

```go
		if failure := response.GetGenerationFailure(); failure != nil {
			// Not verified: there is no object to check, and calling the
			// verifier with nil would produce failures about an answer that
			// does not exist. The attempt is still recorded — the trace is the
			// evidence this channel exists to keep (ADR-0025).
			result.Attempts = append(result.Attempts, Attempt{
				Number:  number,
				Trace:   response.GetTrace(),
				Failure: failure,
			})
			continue
		}
```

Then replace the fall-through after the loop. The outcome describes the final attempt:

```go
	// The outcome describes how the last attempt ended. A final attempt that
	// produced no object is GENERATION_FAILED — there was nothing to refuse to
	// ship — and `Answer` stays nil, because an empty AnswerObject is the
	// honest-silence shape and means the opposite thing (ADR-0020).
	if last := result.Attempts[len(result.Attempts)-1]; last.Failure != nil {
		result.Overall = bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED
		return result, nil
	}

	// Degraded. Nothing from either attempt survives into what renders: not a
	// partial answer, not a warning beside one, and specifically not
	// `no_answer_reason`, which is the honest non-answer and means the
	// opposite thing.
	result.Answer = &bereanv1.AnswerObject{Confidence: verify.DegradedConfidence()}
	result.Overall = bereanv1.OverallResult_OVERALL_RESULT_DEGRADED
	return result, nil
```

- [ ] **Step 4: Run to verify they pass**

```bash
go test ./services/gateway/internal/turn/ -v
```

Expected: PASS, including every pre-existing test unchanged.

- [ ] **Step 5: Commit**

```bash
git add services/gateway/internal/turn/
git commit -m "Gateway: a generation failure is its own outcome

Recorded per attempt with its trace, never verified — there is no object to
check — and never rendered as an empty answer, which is the honest-silence
shape. The outcome describes the final attempt, so an unverified first
attempt followed by no object at all is GENERATION_FAILED."
```

---

### Task 5: Go persists it

**Files:**
- Modify: `services/gateway/internal/trace/store.go:166-190`
- Modify: `services/gateway/internal/trace/store_test.go`
- Modify: `services/gateway/internal/trace/store_integration_test.go`

**Interfaces:**
- Consumes: `turn.Attempt.Failure`, `turn.Turn.Overall`, the schema from Task 2
- Produces: a `trace.responses` row with NULL answer/confidence for a failed generation, and one
  `trace.generation_failures` row per failed attempt

- [ ] **Step 1: Write the failing test for `validate`, which currently blocks this entirely**

`store.go:313` rejects a turn with no answer — *"A nil answer here means the turn never finished."*
That is now false for one outcome, and until it changes, persistence fails with `ErrIncomplete`
before any INSERT runs. `store_test.go` mocks no SQL; its unit surface is `validate`, `enumValue` and
`answerJSON`, with real SQL covered by `store_integration_test.go`. Work with that split.

Add to `store_test.go`, following `TestValidateAcceptsAWellFormedTurn` and `TestValidateRefusals`:

```go
// A generation failure is the one outcome with no answer object, and it must be
// persistable — the missing row is the whole defect (ACCEPTANCE.md, Q4 and Q10).
func TestValidateAcceptsAGenerationFailureWithNoAnswer(t *testing.T) {
	turned := generationFailedTurn()

	if err := validate(turned); err != nil {
		t.Fatalf("validate() = %v, want nil", err)
	}
}

// Every other outcome still requires one. The nil-answer allowance is bound to
// the outcome, not opened generally.
func TestValidateStillRefusesANilAnswerOnEveryOtherOutcome(t *testing.T) {
	for _, overall := range []bereanv1.OverallResult{
		bereanv1.OverallResult_OVERALL_RESULT_VERIFIED,
		bereanv1.OverallResult_OVERALL_RESULT_REGENERATED,
		bereanv1.OverallResult_OVERALL_RESULT_DEGRADED,
	} {
		turned := generationFailedTurn()
		turned.Overall = overall
		if err := validate(turned); err == nil {
			t.Errorf("validate() with %v and no answer = nil, want ErrIncomplete", overall)
		}
	}
}

// And the converse: an answer alongside GENERATION_FAILED is incoherent, and the
// schema CHECK would reject it — so it must not reach the database.
func TestValidateRefusesAnAnswerOnAGenerationFailure(t *testing.T) {
	turned := generationFailedTurn()
	turned.Answer = &bereanv1.AnswerObject{}

	if err := validate(turned); err == nil {
		t.Error("validate() = nil, want ErrIncomplete for an answer on a failed generation")
	}
}
```

Write `generationFailedTurn()` as a helper returning a `turn.Turn` with `Overall` set to
`OVERALL_RESULT_GENERATION_FAILED`, `Answer` nil, and two `turn.Attempt` values each carrying a
`Trace` (built as the file's existing helpers build one) and a `Failure`.

- [ ] **Step 2: Run to verify they fail**

```bash
go test ./services/gateway/internal/trace/ -run TestValidate -v
```

Expected: FAIL — `TestValidateAcceptsAGenerationFailureWithNoAnswer` gets `ErrIncomplete`.

- [ ] **Step 3: Implement `validate` and the write path**

In `validate`, replace the unconditional nil-answer rejection at `store.go:313-317`:

```go
	failedGeneration := t.Overall == bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED
	if t.Answer == nil && !failedGeneration {
		// Including a degraded turn, which carries the derived confidence and
		// nothing else. A nil answer on any other outcome means the turn never
		// finished.
		return fmt.Errorf("trace %s: %w: no answer object", t.RequestID, ErrIncomplete)
	}
	if t.Answer != nil && failedGeneration {
		// The schema's CHECK would reject this; failing here names the reason
		// instead of surfacing a constraint violation.
		return fmt.Errorf("trace %s: %w: a generation failure carries no answer object",
			t.RequestID, ErrIncomplete)
	}
```

In `writeResponse`, make the three values nullable and derive them from the outcome:

```go
	// A failed generation has no answer and no confidence, and both absences are
	// recorded as absences. The schema's CHECKs make the incoherent combinations
	// unwritable; this is the code that respects them.
	var (
		answerArg any = string(answer)
		levelArg  any
		reasonArg any
	)
	if t.Overall == bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED {
		answerArg = nil
	} else {
		level, err := enumValue("CONFIDENCE_LEVEL_", t.Answer.GetConfidence().GetLevel().String())
		if err != nil {
			return fmt.Errorf("trace %s: confidence.level: %w", t.RequestID, err)
		}
		levelArg = level
		reasonArg = t.Answer.GetConfidence().GetReason()
	}
```

Pass `answerArg, overall, levelArg, reasonArg` in place of the current arguments. The existing
`level` lookup moves *inside* the else: on the failure path there is no confidence, and calling
`enumValue` on `CONFIDENCE_LEVEL_UNSPECIFIED` would fail for the wrong reason. Check whether the
caller marshals `answer` before calling `writeResponse` and skip that too when it would marshal nil.

Add `writeGenerationFailure` beside `writeAttempt`, called per attempt from the same place:

```go
func writeGenerationFailure(ctx context.Context, tx *sql.Tx, requestID string, attempt turn.Attempt) error {
	failure := attempt.Failure
	if failure == nil {
		return nil
	}
	code, err := enumValue("GENERATION_FAILURE_CODE_", failure.GetCode().String())
	if err != nil {
		return fmt.Errorf("trace %s attempt %d: generation failure code: %w",
			requestID, attempt.Number, err)
	}
	_, err = tx.ExecContext(ctx,
		`INSERT INTO trace.generation_failures
		     (request_id, attempt, code, detail, completion_tokens)
		 VALUES ($1, $2, $3, $4, $5)`,
		requestID, attempt.Number, code, failure.GetDetail(), failure.GetCompletionTokens())
	if err != nil {
		return fmt.Errorf("trace %s attempt %d: generation failure: %w",
			requestID, attempt.Number, err)
	}
	return nil
}
```

`writeAttempt` must still run for a failed attempt: the `trace.traces` row is what
`generation_failures` foreign-keys into, so skipping it makes the insert fail.

- [ ] **Step 4: Add the integration assertion**

In `store_integration_test.go`, following its existing pattern, persist a `GENERATION_FAILED` turn
with two failed attempts against the live database and read back: one `trace.responses` row with
`answer IS NULL`, `confidence_level IS NULL`, `attempts = 2`; two `trace.generation_failures` rows
with the right codes and attempt numbers.

- [ ] **Step 5: Run both**

```bash
go test ./services/gateway/internal/trace/ -v
make test-gateway-db
```

Expected: PASS. The integration target needs `make dev` running.

- [ ] **Step 6: Commit**

```bash
git add services/gateway/internal/trace/
git commit -m "Gateway: persist the turn that produced no answer object

NULL answer and NULL confidence, one generation_failures row per failed
attempt, and the traces row still written — it is what the failure rows
foreign-key into. This is the row ACCEPTANCE.md recorded as missing."
```

---

### Task 6: Go renders it

**Files:**
- Modify: `services/gateway/internal/render/render.go:27-70`
- Modify: `services/gateway/internal/render/render_test.go`

**Interfaces:**
- Consumes: `turn.Turn.Overall`
- Produces: `render.NoAnswer` — the fixed string a `GENERATION_FAILED` turn prints

- [ ] **Step 1: Write the failing test**

```go
// A generation failure is not a sourcing failure, and must not claim to be.
// "I can't source this adequately" means citations were checked and did not
// hold; here none was produced, so saying it would misreport what happened.
func TestGenerationFailedDoesNotClaimASourcingFailure(t *testing.T) {
	out := renderTurn(t, turn.Turn{
		Overall: bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED,
	})

	if strings.Contains(out, render.Refusal) {
		t.Errorf("printed the sourcing refusal for a generation failure:\n%s", out)
	}
	if !strings.Contains(out, render.NoAnswer) {
		t.Errorf("did not print NoAnswer:\n%s", out)
	}
}

// Nothing else. No partial answer, no citations, no confidence — there was no
// answer object and no verification.
func TestGenerationFailedPrintsNothingElse(t *testing.T) {
	out := renderTurn(t, turn.Turn{
		Overall: bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED,
	})

	if strings.TrimSpace(out) != render.NoAnswer {
		t.Errorf("printed more than the fixed string:\n%q", out)
	}
}
```

The entry point is `render.Answer(&out, turned, sources())` — see
`TestADegradedTurnRendersTheRefusalAndNothingElse` at `render_test.go:155`, which is the exact
precedent for both tests above. Use that call and that file's `sources()` helper; `renderTurn` in
the sketches above stands for it.

- [ ] **Step 2: Run to verify it fails**

```bash
go test ./services/gateway/internal/render/ -run GenerationFailed -v
```

Expected: FAIL — `render.NoAnswer` undefined.

- [ ] **Step 3: Implement**

Beside `Refusal` and `Silence` in `render.go`:

```go
// NoAnswer is what a turn prints when the generator produced no answer object
// across both attempts, and the whole of what it prints.
//
// It shares no words with Refusal deliberately. Refusal means citations were
// checked and did not hold; this means none was produced and nothing was
// learned about the sources, so claiming a sourcing failure would misreport
// what the system did. Fixed here for the same reason Refusal is: a renderer
// free to phrase it is one that can imply something about the corpus.
const NoAnswer = "I couldn't produce an answer for this question."
```

and in the render function, beside the `DEGRADED` branch at line 64:

```go
	if t.Overall == bereanv1.OverallResult_OVERALL_RESULT_GENERATION_FAILED {
		out.line(NoAnswer)
		return out.err
	}
```

Place it **before** the `DEGRADED` branch so the ordering reads as most-specific-first, and note
there is no `confidence(...)` call — there is no confidence.

- [ ] **Step 4: Run to verify it passes**

```bash
go test ./services/gateway/... && make check
```

Expected: PASS throughout.

- [ ] **Step 5: Commit**

```bash
git add services/gateway/internal/render/
git commit -m "Gateway: print what happened, not a sourcing failure

A generation failure prints its own fixed string. Refusal means citations
were checked and did not hold; here none was produced, and borrowing that
sentence would claim something about the corpus that was never tested."
```

---

### Task 7: The record

**Files:**
- Create: `docs/adr/0025-generation-failures-are-their-own-channel.md`
- Modify: `docs/adr/README.md`
- Modify: `docs/adr/0010-regeneration-retry-exception.md`
- Modify: `docs/adr/0024-answer-level-failures-are-their-own-channel.md`
- Modify: `specs/SHARED-TECHNICAL-SPEC.md`
- Modify: `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md`
- Modify: `specs/001-phase-1-pca-baseline/ACCEPTANCE.md`
- Modify: `proto/README.md`
- Modify: `services/catena/AGENTS.md`, `services/gateway/AGENTS.md`
- Modify: `specs/001-phase-1-pca-baseline/GENERATION-FAILURE-CHANNEL-DESIGN.md` (Status)

- [ ] **Step 1: Read the house style before writing**

```bash
cat docs/adr/0000-template.md
sed -n '1,60p' docs/adr/0024-answer-level-failures-are-their-own-channel.md
```

This repository's ADRs argue: they name what actually binds the decision, give each rejected
alternative its own specific reason, and state costs. A correct but flat, listy ADR is a failed
deliverable here.

- [ ] **Step 2: Write ADR-0025**

Following the template's sections exactly. Status Accepted, Phase 1. It must cover:

- **Context.** Q4 and Q10 produced no row in `trace.responses`, and ACCEPTANCE.md's own words for
  what that cost — "the one measurement Phase 2 cannot see". Two structural causes: `AnswerResponse`
  cannot carry a trace without an answer, and `trace.responses.answer` was `NOT NULL`. Both fire on
  the pinned local default; this is not a provider problem.
- **Decision.** The `oneof`; `GenerationFailure` with its six codes; the fourth `OverallResult`;
  `generation_failures` per attempt; the three nullable columns bound by CHECKs.
- **Decision, and the two sub-decisions that carry the weight.** Why `answer` is NULL rather than
  `{}` (ADR-0020's silence shape, in the one table the harness reads). Why confidence is NULL rather
  than a synthetic `low` (a fabricated number the harness could average).
- **Decision, attempts.** A generation failure consumes ADR-0010's single regeneration, so
  `generation_failed` always follows two attempts — symmetric with what ADR-0024 settled for
  degradation. State the objection honestly: at `temperature: 0` the second attempt is often
  identical, and it is spent anyway because it separates deterministic inadequacy from transient
  noise.
- **Decision, introspection.** `detail` is factual; `PROVIDER_REFUSED` records the category and
  never the explanation. A new field is how introspection gets in.
- **Alternatives rejected**, each with its specific reason: having Go persist a trace it never
  received (it cannot — the trace is built in Python and is not on the wire); reusing
  `answer_failures` with an empty `slot` (breaks the premise that makes ADR-0024 readable, and
  `slot` is `NOT NULL` precisely so an unrecorded failure is impossible); folding into `DEGRADED`
  (launders the rate ADR-0010 needs kept clean, which ADR-0024 already refused for unreachable
  Catena); raising the ceiling (measured three times, each raise converting truncation into timeout).
- **Consequences.** A fourth outcome every enumerating document must carry. Nullable columns in the
  trace's central table. The failure rates become measurable for the first time, which is what Phase
  2 needs. `DEGRADED` keeps one meaning.
- **Documents updated** — the list in Step 3.

- [ ] **Step 3: Amend the documents that are now incomplete or wrong**

**`docs/adr/README.md`** — add the 0025 row in the table's existing format, and annotate the 0010
and 0024 rows as amended, matching how 0015 and 0024 already record amendment.

**`docs/adr/0010-regeneration-retry-exception.md`** — add an inline `**Amended by ADR-0025:**`
annotation in the house form, recording that the single regeneration is also consumed by a
generation failure, and that `generation_failed` therefore always follows two attempts.

**`docs/adr/0024-answer-level-failures-are-their-own-channel.md`** — add an inline
`**Extended by ADR-0025:**` annotation noting that a generation producing no object has no slot to
name and travels in a sibling channel one layer upstream.

**`specs/SHARED-TECHNICAL-SPEC.md`** — §3 gains the fourth outcome and the rule that a turn
producing no answer object still records a trace row. §7 gains the requirement that the outcome be
distinguishable from degradation in the data.

**`specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md`** — the response contract (`oneof`, trace
always present) and the new trace table.

**`proto/README.md`** — `GenerationFailure`, `GenerationFailureCode`,
`OVERALL_RESULT_GENERATION_FAILED`, and which are used from Phase 1.

**`services/catena/AGENTS.md`** — Catena returns a generation failure rather than raising, and the
rule that `detail` never carries the model's reasoning.

**`services/gateway/AGENTS.md`** — Go renders and persists a fourth outcome, and never verifies an
attempt that produced no object.

- [ ] **Step 4: Annotate ACCEPTANCE.md without rewriting its results**

Add a note to the UC-4/UC-10 section recording that the invisibility is fixed by ADR-0025 and that a
re-run would now produce a row and a `generation_failed` outcome.

**Do not change any recorded number, outcome or verdict in that file.** It records what a specific
run of a specific build did, and editing results to match later code destroys the only evidence the
phase produced.

- [ ] **Step 5: Close the design doc**

In `GENERATION-FAILURE-CHANNEL-DESIGN.md`, replace the Status body with `Implemented. See
ADR-0025.` plus the date.

- [ ] **Step 6: Verify**

```bash
make guard-make-targets && make check
```

Expected: both PASS. Run `guard-make-targets` explicitly: it reads the literal text `make <word>` in
prose as a target reference, and ordinary English containing "make" as a verb has already cost this
line of work two fixes.

- [ ] **Step 7: Commit**

```bash
# Explicit paths, never `git add docs/`: the working tree carries unrelated
# untracked work under docs/agents/ that is not part of this branch.
git add docs/adr/0025-generation-failures-are-their-own-channel.md \
        docs/adr/README.md \
        docs/adr/0010-regeneration-retry-exception.md \
        docs/adr/0024-answer-level-failures-are-their-own-channel.md \
        specs/SHARED-TECHNICAL-SPEC.md \
        specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md \
        specs/001-phase-1-pca-baseline/ACCEPTANCE.md \
        specs/001-phase-1-pca-baseline/GENERATION-FAILURE-CHANNEL-DESIGN.md \
        proto/README.md services/catena/AGENTS.md services/gateway/AGENTS.md
git commit -m "The generation-failure channel: the decision, and the record

ADR-0025 records it and annotates the two ADRs whose reasoning it extends:
0010, whose single regeneration is now also consumed by a generation failure,
and 0024, whose per-slot premise a generation with no object cannot meet.

ACCEPTANCE.md gains a note that Q4 and Q10's invisibility is fixed. Its
recorded results are untouched — they are what one build did on one day, and
editing them to match later code would destroy the phase's only evidence."
```

---

## Two codes ship unreachable, deliberately

`GENERATION_FAILURE_CODE_CONTEXT_EXHAUSTED` and `GENERATION_FAILURE_CODE_PROVIDER_REFUSED` are
defined in the proto, the SQL enum and `service.py`'s map, and **nothing in this plan produces
them**: the Phase 1 provider neither refuses on policy grounds nor distinguishes an exhausted
context window from a hit ceiling.

That is intended, and it is why the map in Task 3 covers all six. The enum is the contract, and
defining it once here means the provider work adds providers without a proto change, a migration and
a `store.go` edit. A reviewer should read these two as reserved, not as dead code — but if you prefer
them added when first produced, that is a defensible call and the place to make it is now, not after
the migration has shipped.

The design's testing list asks for a test that a refusal's explanation never reaches `detail`. There
is no refusal path in this plan, so the nearest assertable thing is covered instead: Task 3's
`test_a_failure_detail_never_carries_the_models_reasoning`, which uses the `reasoning` field the
Phase 1 provider does return. The refusal-specific test belongs to the provider plan.

## What this plan does not do

Stated so an executor does not helpfully add them.

- **No provider work.** `GENERATION-PROVIDERS-DESIGN.md` is a separate plan that depends on this
  one. No new provider, no `base_url` change, no vendor SDK, no API key.
- **No feedback to Python on the regeneration.** `AnswerRequest` gains no sibling to
  `answer_failures`. The design rejects it as speculative: the failure acceptance measured was
  deterministic, so there is no evidence a note would change the second attempt.
- **No change to the token ceiling or the timeout.** Measured three times; each raise converted
  truncation into timeout. The constants stay at 2048/900.
- **No rewriting of ACCEPTANCE.md's results.** Only an added note.
- **No change to `prompt.py`, `schema.py`, `retrieval.py`, or the verification checks.** If a task
  seems to need one, stop — the failure channel does not touch what an answer means, only what
  happens when there isn't one.
