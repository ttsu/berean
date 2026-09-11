# Bring-your-own-key hosted generation — design

A deployer may point generation at the Claude API with their own key, instead of at the Ollama
the compose stack provides. This is a **supported deployment configuration**, off by default,
selected explicitly, and it changes nothing above the `Generator` protocol.

It is not a fix for anything. Phase 1 acceptance recorded Q4 and Q10 as failures of the pinned
local generator, and that record stands: it is a measurement of the default, and a run against a
different model is a different measurement. See *What this is not*, below.

## Why this is more than a second class

The provider seam already exists and is already the right shape. `services/catena/AGENTS.md`
requires generation to sit behind an interchangeable interface, `service.py` calls
`self._generator.generate(messages, schema.answer_schema())` and knows nothing else about the
model, and `RetrievalTrace.generation_model` already records what answered. A second
implementation of `Generator` gets Langfuse instrumentation, timings and the trace field for free.

What is *not* free is that three project-level commitments say something narrower than the seam
does, and each has to be amended rather than quietly stretched:

- **SHARED §1** requires steady-state operation with no network egress and names the ESV adapter
  "the sole exception". A hosted generator is a second exception.
- **SHARED §1** also requires the provider interface use "the OpenAI-compatible chat-completions
  shape as the internal lingua franca". The Claude API is not that shape.
- **ADR-0018** rejected "a hosted API by default" outright, on the grounds that it breaks the
  no-external-accounts acceptance test. That reasoning is about the *default*, and it survives
  intact — but the rejection is on the record and must be amended to say so.

`services/catena/AGENTS.md` carries the fourth: "The **wire format** is what delivers that, not a
vendor SDK." That sentence is the one this change actually contradicts, and the correction is that
interchangeability is delivered by the **`Generator` protocol** — a typed seam with one method and
a documented return — not by every provider happening to speak one vendor's JSON. The protocol is
what `service.py` depends on; the wire format was only ever how the first provider satisfied it.

## The licence question, and why it is answered the way it is

Licence is enforced by check 4, in Go, at verification — **after** generation. `retrieval.py` does
not filter on it; `prompt.py` mentions it only when composing regeneration feedback. Today that
ordering is harmless because the model is on the same machine, so a `local-only` chunk retrieved
under a deployer who has not opted in never leaves the box. With a hosted generator it does: the
text reaches a third party before the gateway decides whether it may be served.

**The answer is ADR-0017's own answer, applied unchanged.** That ADR settles the same question for
ESV — "each deployer accepts Crossway's non-commercial terms themselves" — and states the project's
posture directly: it "automates nothing around anyone's terms, ships no key and no text, and leaves
the acceptance of terms with the party who can actually accept them." Sending retrieved text to a
model the deployer pays for, under the deployer's own account, is processing on their behalf. It is
not this project publishing anything.

Two consequences follow, and both are load-bearing:

1. **The opt-in is a recorded act**, exactly as `BEREAN_SERVE_LOCAL_ONLY` is. Enabling a hosted
   generator is an explicit configuration, never inferred, so no deployer begins transmitting
   corpus text because a key happened to be in the environment.
2. **CORPUS-POLICY says this in plain words**, so a deployer weighing a `local-only` corpus against
   a hosted generator is deciding with the facts in front of them rather than discovering the
   ordering by reading `service.py`.

The sharpest case needs no rule at all. ESV and NIV are never ingested and are fetched at render
time in the gateway, so they cannot appear in a Catena prompt under any configuration.

**Rejected: filtering the prompt by licence when the generator is remote.** It is the safest
reading, and it is wrong twice over. It puts a licence decision in Python, which `AGENTS.md` lists
under *Does not own*, and it makes the retrieved set differ by provider — so two generators would
no longer be answering the same question, and nothing measured across them would be comparable.

**Rejected: refusing remote generation whenever a `local-only` corpus is indexed.** `pca-bco-2026`
is `local-only` and is in the Phase 1 index, so this is "not yet" wearing a rule's clothes.

## What changes

### `generate.py` becomes a package

Three files, split on the line the protocol already draws:

    generate/__init__.py   Generation, the Generator protocol, connect()
    generate/ollama.py     OllamaGenerator, DEFAULT_MODEL, the measured constants
    generate/claude.py     ClaudeGenerator, its own default and constants

Everything provider-independent stays in `__init__.py`, so `service.py`'s import does not move and
the protocol keeps one home. The measured commentary in `ollama.py` — the ceiling/timeout table
from Phase 1 acceptance, the `reasoning_effort` probe — travels with the provider it measures,
because it is true of qwen3-8b on CPU and of nothing else.

This is the only structural change. `prompt.py`, `schema.py`, `service.py`, `server.py` and the
proto contract are untouched.

### Selection is explicit and fails at startup

    CATENA_GENERATION_PROVIDER = ollama | anthropic     default: ollama
    ANTHROPIC_API_KEY          = <deployer's key>       no default, never shipped
    CATENA_GENERATION_MODEL    = <override>             applies to whichever provider is selected

`connect()` dispatches on the provider and raises `ServeError` for an unknown value, naming the
ones that exist. With `anthropic` selected and no key, it raises **in `connect()`** — at server
startup, where the existing unset-`CATENA_OLLAMA_URL` failure already lives — rather than at the
first question a user asks.

**The provider is never inferred from the presence of a key.** An ambient `ANTHROPIC_API_KEY` in a
developer's shell must not be able to start egress, and a configuration that turns itself on is the
opposite of a recorded act.

Each provider module owns its own `DEFAULT_MODEL`: `qwen3:8b-q4_K_M` stays pinned in `ollama.py`
against `tools/provision/models.lock.yaml`, with the existing agreement test unmoved;
`claude.py` pins `claude-opus-5`. `CATENA_GENERATION_MODEL` overrides whichever is selected, and
must name a model that provider serves — documented, because a qwen tag sent to the Claude API is
a 404 whose cause is not obvious.

`make dev-offline` is what keeps all of this honest. The overlay marks the network internal, so a
hosted generator fails loudly there and cannot drift into the default path unnoticed.

### The request, and four decisions inside it

**The schema is the same object.** `output_config={"format": {"type": "json_schema", "schema":
schema}}`, given `schema.answer_schema()` verbatim. No copy, no provider-specific variant.
Everything ADR-0023 decided — `confidence` subtracted, the list-only `required` rule, no count
constraints anywhere — is a property of the schema and carries over untouched.

**Thinking stays on.** Adaptive, with the default `display: "omitted"`. Constraint 5 holds by
construction and for the same reason it holds today: the narrative is never returned, and there is
nowhere in this package for it to go. The response is read by filtering `content` to `text` blocks,
which is `_content`'s discipline unchanged.

It is deliberately **not** `thinking: {"type": "disabled"}`. On this model family, disabling
thinking can put tool calls and `<thinking>` tags into the visible text — a model's reasoning
leaking into the answer is precisely the failure constraint 5 exists to prevent, so the setting
that looks like compliance produces the violation. `output_config.effort` is `medium`, on ADR-0018's
finding that "reasoning ability is close to irrelevant here": the model routes claims into slots and
copies text out of context, and the trust boundary catches it when it does not.

**There is no `temperature`.** Sampling parameters are rejected on this model. Today's constant
carries the note "the Phase 2 baseline is a measurement, and a default temperature makes it a
distribution nobody recorded" — that guarantee cannot be had here, and its absence is a reason the
Phase 2 baseline stays local rather than a detail to be discovered later.

**No server-side refusal fallbacks, and no transport retries.** A fallback re-serves a refused
request on a different model; ADR-0018 requires that "a silent model change must not be able to
move the Phase 2 baseline", and a generator that substitutes itself mid-run is that failure exactly.
The SDK client is constructed with `max_retries=0` for the neighbouring reason ADR-0010 gives:
`attempt` means one generation, and a hidden retry underneath would make it mean two while hiding a
failing provider behind a latency spike.

The request stays **non-streaming**, with `max_tokens` at 16,000 — the largest ceiling that
comfortably clears the SDK's non-streaming HTTP timeout, and roughly eight times what the local
provider can reach. The prohibition on streaming tokens to the client before verification is
**CLAUDE.md hard constraint 4** — SHARED §9 records only its consequence, that the SSE feed exists
because the answer cannot stream — and it would not be engaged by streaming an HTTP response, but
not needing the distinction is better than relying on it.

### Two failure modes, both raising

`stop_reason == "max_tokens"` raises `ServeError`, exactly as `finish_reason == "length"` does now.
ADR-0020's argument is provider-independent: an incomplete answer object must not be presented as
considered silence, and the all-slots-empty shape is reserved for the corpus actually being silent.

`stop_reason == "refusal"` is new and has no local analogue. It also raises, naming the category
from `stop_details`. A policy decline is not an answer, and it is not silence either; making it
legible in the error is what keeps it from being diagnosed as a retrieval failure.

Each provider carries its own `MAX_TOKENS` and timeout. The 2048/900 pair is a measured property of
qwen3-8b generating at ~3.4 tokens/second on CPU and means nothing here.

### What a deployer is choosing, in numbers

Phase 1 prompts run around 5,900 tokens. At Claude Opus 5's published rates that is an **estimated
$0.05–0.08 per answer**, against a local generator that costs a machine and several minutes.

The estimate is marked as one deliberately, because every other number in this repository's
performance prose is measured and the two must not be read alike. It prices the prompt plus a
completion and **nothing else**: thinking is left on at `effort: medium` and those tokens are billed
as output, so they are absent from the arithmetic and a real bill runs higher. Measuring it needs a
deployer's account and a run nobody here has done. Stated in the README, and in `.env.example`, as
an estimate with that exclusion named, so the choice is made with the figure visible and its
limits visible too.

Prompt caching is **not** part of this change. The stable prefix is the rules block and the passages
vary per question, so the win is small and unmeasured, and YAGNI applies until someone has a bill.

## What this is not

- **Not an acceptance fix.** `ACCEPTANCE.md` is not touched. Q4 and Q10 record what the pinned
  local default does, and Phase 1's numbers — 12.1% check-2 failure, 62.5% first-attempt verified —
  are measurements of that generator. A BYOK run may well answer both questions; overwriting the
  record with it would destroy the thing the record exists for.
- **Not a Phase 2 baseline.** Phase 2 measures the local default, for the reasons ADR-0018 gives
  and one more this change adds: without `temperature` there is no determinism to record.
- **Not a change to the default path.** `docker compose up` with no accounts stays the acceptance
  test, unmodified, and `make dev-offline` proves it.

## Testing

TDD, and the seam moves. The SDK replaces the `Transport` callable, so `ClaudeGenerator` takes an
injected client — a fake exposing `messages.create` — mirroring how `transport` is injected today,
and every assertion below runs without a network.

- the request carries the derived schema, no `temperature`, and the configured effort
- the schema passed is `schema.answer_schema()` itself, not a second copy
- `stop_reason == "max_tokens"` raises `ServeError` and does not return a payload
- `stop_reason == "refusal"` raises `ServeError` naming the category
- content that is not JSON, and JSON that is not an object, raise — the existing rules, reused
- `Generation.model` is the model the response reports, not the one requested
- thinking blocks in `content` are not read and cannot reach the payload
- `connect()`: default is `ollama`; unknown provider raises naming the valid ones; `anthropic`
  without a key raises at connect time
- `claude.DEFAULT_MODEL` is pinned, mirroring the existing lockfile-agreement test in `ollama.py`

## Spec changes in the same change

| File | Change |
| --- | --- |
| `docs/adr/0025-byok-hosted-generation.md` | New. Amends ADR-0018's hosted-API rejection and records the licence-ordering decision |
| `specs/SHARED-TECHNICAL-SPEC.md` | §1: the egress exception is no longer sole; the provider bullet becomes about the interface rather than the wire format |
| `services/catena/AGENTS.md` | The "wire format, not a vendor SDK" convention |
| `docs/CORPUS-POLICY.md` | Remote generation transmits retrieved text under the deployer's own terms |
| `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` | Generation section: provider selection and the hosted option |
| `.env.example` | `CATENA_GENERATION_PROVIDER`, `ANTHROPIC_API_KEY`, documented and defaulting to local |
| `README.md` | The option, its non-default status, and the per-answer cost |
| `services/catena/pyproject.toml` | `anthropic`, justified in the comment idiom the file already uses |

## Open question, to be answered by probe before the adapter is written

Whether `output_config.format` accepts the derived schema **verbatim**. `schema.py` emits `$defs`
and `$ref` (lines 108, 191), `additionalProperties: false`, and string enums, and deliberately emits
no `minItems` anywhere. If `$ref` is not accepted there, the fix is to inline the definitions inside
the adapter — never to hand-write a second schema, and never to relax ADR-0023's rules to suit a
provider. One cheap call answers it, and it needs a deployer key.

## Status

Implemented. See ADR-0025. (2026-09-11)
