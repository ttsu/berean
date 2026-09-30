# proto/

The Go↔Python contract. **Normative** — where this and any prose document disagree, the proto
wins and the prose is stale.

Versioned from the first commit. Layout is `berean/v1/`, and every file carries:

```proto
option go_package = "github.com/ttsu/berean/gen/berean/v1;bereanv1";
```

## What is where

| File | Holds |
| --- | --- |
| `catena.proto` | `CatenaService.Answer`, `AnswerRequest`, `AnswerResponse`, `GenerationFailure`, `GenerationFailureCode` |
| `filter.proto` | `FilterSpec`, `CorpusFilter`, `TierWeight`, `ContestedLocus` |
| `answer.proto` | `AnswerObject` and everything under it, `Citation`, `Confidence` |
| `trace.proto` | `RetrievalTrace`, `Candidate`, `Timings` |
| `verification.proto` | `VerificationResult`, `AnswerFailure`, `AnswerFailureCode`, `OverallResult` (four values — `GENERATION_FAILED` is the fourth) |
| `common.proto` | `Tier` and `CitationRef` — used by both sides, owned by neither |

## Generating

```
make proto        # lint, then generate both sides
make proto-lint   # lint only
```

Go output lands in `gen/`, under the root module. Python output goes to `services/catena/gen/`.
Both are **gitignored and regenerated locally**; whether to commit them instead is CI policy
rather than contract design, and is deferred to Phase 2 (ADR-0013). Run `make test` after
regenerating — the contract suite in `services/catena/tests/test_proto_contract.py` skips itself
when the stubs are absent, so a clean clone that has never generated reports green.

`buf` runs in a pinned container, so it is not a host prerequisite. Plugin versions are pinned in
`buf.gen.yaml` for the same reason the images and the model weights are.

`go.mod` requires `google.golang.org/grpc` and `google.golang.org/protobuf` even though nothing in
the committed tree imports them yet — the generated code does, and `protodeps.go` is what keeps
`go mod tidy` from dropping them on a clean clone. gRPC is pinned at the newest release that still
builds under the pinned Go image, which is now 1.25 — the toolchain was raised in its own commit
so the dependency bump did not carry a stack change along with it.

## Fields it is easy to get wrong

Present-but-unused in Phase 1 — `conversation_context`, `tier_weights`, `rewritten_query`. They
exist so later phases add behaviour rather than break the contract. **Do not remove them because
they are unused.**

Used from Phase 1 and easy to leave out by accident: `previous_failures` and `attempt` on the
request (the regeneration carries verification results back — ADR-0010 decided the retry and
nothing carried its reasons), `no_answer_reason` on the answer object (ADR-0020), and
`generation_model` plus `top_k` on the trace.

Both are asserted by `services/catena/tests/test_proto_contract.py`, which exists because
`buf breaking` is deferred: until Phase 2, that suite is the only mechanical thing standing
between a field and its quiet removal.

**`AnswerResponse.trace` is outside the `oneof`, and that placement is the contract.** The outcome is
exactly one of `answer` or `generation_failure`; the trace is present on both branches, because a
generation that failed still performed the retrieval and losing that evidence is the defect the
channel exists to fix (ADR-0025). Moving `trace` inside the `oneof`, or adding a third outcome that
omits it, reopens it.

`GenerationFailure` and `GenerationFailureCode` are used from Phase 1, and **four of the six codes
are produced by it**: `TRUNCATED`, `NOT_JSON`, `NOT_AN_OBJECT` and `EMPTY`. `CONTEXT_EXHAUSTED` and
`PROVIDER_REFUSED` are **reserved, not dead** — the local default neither declines on policy grounds
nor distinguishes an exhausted context window from a hit ceiling, and the closed set is defined here
so that adding a provider adds a provider rather than a proto field, a migration and a gateway
change. Do not remove them because nothing produces them.

`GenerationFailure.detail` is factual and never the model's account of its own reasoning; for
`PROVIDER_REFUSED` it carries the provider's category and never its explanation. That is the field a
new sibling would most plausibly be added beside, and it is the one place model introspection could
enter the contract.

## Two shapes that differ from how INTEGRATION-SPEC draws them

Recorded here because the proto is normative and the difference is deliberate.

**`tier_weights` is a repeated `TierWeight`, not a map.** The spec draws it as
`{ binding: float, … }`. proto3 map keys cannot be enums, so a map would have keyed the closed
tier set by string and reopened it. Repeated pairs keep `Tier`.

**`conversation_context` is a `repeated ConversationTurn`, and `ConversationTurn` is empty.** The
spec says only that the field is empty in Phase 1. A bare `string` would have had to be replaced in
Phase 4 rather than added to, which defeats the reason the field is here at all. What is fixed now
is only that context is a list of turns; Phase 4 decides what a turn carries, and does so by adding
fields.

## Changing it

Adding a field is cheap. Renaming or removing one is breaking and needs a new package version.
`buf lint` runs in `make check`. `buf breaking` is **deferred to Phase 2** (PLAN Task 2,
ADR-0013) — the proto is pre-consumer in Phase 1, and the answer object is still gaining fields.
The configuration for it is already written in `buf.yaml`, so turning it on is a CI change rather
than a design question.
