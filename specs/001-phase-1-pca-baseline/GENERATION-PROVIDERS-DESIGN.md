# The generation provider layer — design

Four generation providers ship with the project. The operator picks one with a single environment
variable and, optionally, a model within it. No code changes to choose; adding a fifth is a small
change plus an ADR.

**Depends on [GENERATION-FAILURE-CHANNEL-DESIGN.md](GENERATION-FAILURE-CHANNEL-DESIGN.md) landing
first.** Two of the four providers cannot be held to the answer schema by their decoder, so they
need somewhere for a malformed generation to go before shipping them is honest.

This supersedes the two-provider work on PR #23, which is closed unmerged. Three of its findings
carry over and are credited where they land: the licence-ordering argument, the
thinking-parameter hazard, and the unanswered schema probe.

## The seam is already right, and that is the finding

`service.py` calls `self._generator.generate(messages, schema.answer_schema())` and depends on the
`Generator` protocol and nothing else. The protocol absorbs all four providers without moving:
`service.py`, `prompt.py`, `schema.py`, `server.py` and the proto contract are untouched by this
design.

What has to change is a claim written in three places. `services/catena/AGENTS.md` and SHARED §1
both say the OpenAI-compatible **wire format** is what makes providers interchangeable. It is not —
the typed protocol is, and the Anthropic Messages API is the case that separates the two claims.
That sentence was written when there was one provider, so it had no way to be wrong yet.

## What ships

Two modules speak HTTP, one per wire format. Everything else is a reviewed table.

    generate/
      __init__.py     Generation, the Generator protocol, connect(), the provider table
      openai_chat.py  the OpenAI chat-completions wire format — stdlib urllib
      messages.py     the Anthropic Messages wire format — the vendor SDK

| provider | wire | base URL | key | default model | price in/out per MTok | schema delivery |
| --- | --- | --- | --- | --- | --- | --- |
| `ollama` *(default)* | openai_chat | `CATENA_OLLAMA_URL` | — | `qwen3:8b-q4_K_M` | — | **constrained** ✓ verified |
| `anthropic` | messages | `api.anthropic.com` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` | $2 / $10 | **constrained** — probe pending |
| `openai` | openai_chat | `api.openai.com` | `OPENAI_API_KEY` | `gpt-6-luna` | $0.10 / $0.50 | **probe decides** |
| `deepseek` | openai_chat | `api.deepseek.com` | `DEEPSEEK_API_KEY` | `deepseek-flash` | — | **shaped** ✓ verified |

Model identifiers were read from each provider's live documentation on 2026-09-30, not recalled.
All three hosted defaults postdate this project's training-era assumptions, and two of the three
names would have been wrong if guessed — which is why the pin test extends to cover them.

The operator sets `CATENA_GENERATION_PROVIDER` and optionally `CATENA_GENERATION_MODEL`, which
applies within the selected provider and must name a model that provider serves.

**Base URLs are pinned in the table.** This is not cosmetic. The Anthropic SDK reads
`ANTHROPIC_BASE_URL` from the environment, so without a pinned value an ambient variable silently
redirects every retrieved passage to a third party while the configuration, the trace and
CORPUS-POLICY all still name Anthropic. Pinning makes the provider named `anthropic` *be*
Anthropic. Found on PR #23 and fixed structurally here rather than patched.

## Schema delivery: three modes

The schema itself never changes — it is derived from the proto descriptor and ADR-0023's rules hold
unaltered. What varies is what the provider will *enforce*.

| mode | the request enforces | what can go wrong | which channel catches it |
| --- | --- | --- | --- |
| **constrained** | the decoder is held to the schema | semantic violations only | verification, `answer_failures` |
| **shaped** | JSON-ness only; the schema is requested | fields missing, extra, or wrong-typed | `answer_failures` — the object parses |
| **unconstrained** | nothing | the reply may not be JSON | `generation_failures` |

The useful property is that each mode fails into a channel that already exists. A **shaped**
provider still produces a parseable object, so its wrong slots regenerate through ADR-0024's
machinery with no new code. `deepseek-flash` is shaped, not unconstrained: `response_format`
accepts `{"type": "json_object"}` — verified — which guarantees JSON without guaranteeing the
schema.

`GENERATION_FAILURE_CODE_NOT_JSON` is therefore rarer than it first appears, and it is not a
DeepSeek-specific concession: acceptance measured it firing on the pinned local model.

### The adapter owns delivery, never `prompt.py`

Each adapter puts the schema where its wire and mode require: in `response_format`, in
`output_config`, or appended to the system message as text. `prompt.py` learns nothing about
providers, which keeps the translation at the provider's own edge.

**The cost is stated rather than discovered later: providers receive different prompts, so
cross-provider quality comparison is confounded.** The alternative — send the schema text to every
provider so the prompts match — was rejected because the local default is the slowest component in
the system at roughly 3.4 tokens/second and would pay tokens for enforcement it already has. The
trace records the delivery mode, so the confound is visible in the data rather than hidden in it.

### Two parameters that are decisions, not tuning

**`thinking` is sent explicitly as `{"type": "adaptive"}`.** `claude-sonnet-5-5`'s thinking is
adaptive-capable but not always-on, so *omitting* the parameter is not the same as leaving thinking
enabled — and thinking-off on this family can push reasoning into the visible text, which is the
one thing constraint 5 forbids. Omission was the bug PR #23's final review caught; on the Opus
default it was latent, and on this default it would be live.

**`effort` is `medium`, a deliberate downgrade** from `claude-sonnet-5-5`'s default of `high`.
ADR-0018 found reasoning ability "close to irrelevant here": the task is routing claims into slots
and copying text verbatim, and the trust boundary catches the model when it does not. Recorded as a
choice so it is not silently inherited on the next model.

## Licence ordering, now with three counterparties

Verification check 4 runs in Go, after generation, so a hosted provider receives retrieved corpus
text *before* the gateway rules on whether it may be served. ADR-0017 already settles the
principle for ESV — the deployer's key, the deployer's terms, and a project that "automates nothing
around anyone's terms" — and it applies unchanged here.

What changes from PR #23 is arithmetic: there are three hosted counterparties now, not one, so
CORPUS-POLICY names the recipient **per provider** rather than in prose. A deployer weighing a
`local-only` corpus against a hosted generator should be able to read who receives the text.

ESV and NIV remain unaffected under every configuration: never ingested, fetched at render time in
Go, and therefore unable to appear in a Catena prompt.

## What protects the Phase 2 baseline

ADR-0018 pinned the generator because "an unpinned generator makes the Phase 2 number
unreproducible." Four providers do not break that, on three conditions:

- **The default does not move.** `ollama` and the pinned tag, with `docker compose up` working
  with no external accounts. `make dev-offline` continues to prove it, and a hosted provider must
  fail loudly there.
- **The trace records the provider and the delivery mode**, not only `generation_model`. Without
  the mode, two runs of one model under different enforcement are indistinguishable — which becomes
  a live scenario the moment a probe reclassifies `openai`.
- **The baseline is the default.** A hosted run is legitimate and must be labelled; it is not
  quotable as the baseline. Phase 2's harness does not exist yet, so this design guarantees only
  that the trace can attribute a run — it does not design the harness.

ADR-0018's "re-decided at Phase 2 against the golden set" now has four candidates rather than one.

## Open questions, to be answered by probe

Both need a deployer key, both are one cheap call, and both are recorded in ADR-0026 as findings.

1. **Does `output_config.format` accept the derived schema verbatim** — `$defs`, `$ref`,
   `additionalProperties: false`, string enums? Inherited unanswered from PR #23. If not, the fix is
   to inline the definitions at that adapter's edge, never to hand-write a second schema and never
   to relax ADR-0023 to suit a provider.
2. **Does `gpt-6-luna` support strict structured outputs, and does strict mode require every
   property in `required`?** This decides whether `openai` is *constrained* or *shaped*. The
   requirement was asserted from training-era knowledge during design and could not be confirmed
   against current documentation, so it is an open question rather than a settled constraint. If
   strict mode does demand all-required, `openai` is shaped: ADR-0023 measured the all-required
   shape producing `position: "no_position"` beside empty `arguments`, and the contract does not
   bend to fit a provider.

Neither probe blocks the layer. An unanswered mode is recorded as unverified and the failure
channel catches what it catches — which is the whole reason that work lands first.

## Alternatives rejected

**Provider definitions as operator YAML.** Adding Together, Groq, OpenRouter or a local vLLM with
no Python is genuinely attractive. Rejected because it moves the capability claim from something the
project probed to something the operator asserts, and a wrong assertion surfaces as a mysterious
degradation rate rather than a clear fact. The claims in the table above are verified; a file format
cannot promise that.

**A module per provider.** The repo's current shape, and three of the four would be near-identical
OpenAI POSTs — duplication the review standards flag, and a bug fixed in one would not reach the
others.

**A generic base-URL-plus-key escape hatch as the primary interface.** Maximally flexible and
least safe: every unsafe endpoint becomes equally one typo away, the documentation can no longer
name who receives corpus text, and model and endpoint can be paired incoherently.

**One generator parameterised by strategy objects.** Most factored, and over-abstract for four
providers — three indirections to answer "what does DeepSeek send?"

**Refusing providers that cannot constrain decoding.** The safest reading, and it makes the
project's own instinct inconsistent: `retrieval.py` leaves its known risk "naive and measured, not
pre-empted", and the trust boundary means unconstrained output is caught rather than shipped. The
degradation and generation-failure rates are the measurement; refusing to run is a way of not
having it.

## Testing

Adapters keep the injected-transport pattern, so all of this runs with no network.

- **The table:** every entry complete; base URLs absolute and pinned; key variables distinct; no
  two providers sharing a default model.
- **The pin:** `ollama`'s default still matches `tools/provision/models.lock.yaml`, and each hosted
  default is asserted against the table so a silent edit fails in CI rather than at a 404.
- **Delivery modes:** each mode puts the schema where its wire format requires; prompted text
  appends to the system message; `prompt.py` is provably unchanged.
- **`thinking` is asserted positively** as `{"type": "adaptive"}` — a negative assertion that the
  parameter is absent passes against the broken case, which is how PR #23 shipped the bug to its
  final review.
- **Selection:** the default is local; an ambient key does not select a hosted provider; an unknown
  provider names the valid ones; a missing key fails at `connect()` rather than at the first
  question; an ambient `ANTHROPIC_BASE_URL` does not change where requests go.
- **Failure mapping:** each provider's truncation, refusal and unparseable-content paths map to the
  right `GenerationFailureCode`.

## Documents updated

| File | Change |
| --- | --- |
| `docs/adr/0026-the-generation-provider-layer.md` | New. Amends ADR-0018 (hosted is no longer rejected outright; the pin applies to the default) and ADR-0023 (the derived schema is unchanged; its enforcement is now provider-dependent) |
| `specs/SHARED-TECHNICAL-SPEC.md` | §1: the egress exceptions, and the provider requirement becomes about the typed interface rather than the wire format. §7: provider attribution |
| `services/catena/AGENTS.md` | The wire-format convention; the thinking bullet, which currently states a local-only mechanism as a blanket rule |
| `docs/CORPUS-POLICY.md` | The counterparty per provider, and the check-4 ordering |
| `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md`, `PLAN.md` | The generation section; the acceptance item carrying the reversed wire-format claim |
| `.env.example`, `compose.yaml`, `README.md` | The provider variables, the three keys, and per-provider cost |
| `services/catena/pyproject.toml` | `anthropic`, and why a vendor SDK in the request path is a considered reversal |

## Status

Design approved. Plan to follow, after the failure channel lands.
