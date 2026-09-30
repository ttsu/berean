# ADR-0026: The generation provider layer — four providers, one typed protocol

- **Status:** Accepted
- **Date:** 2026-09-30
- **Phase:** 1 — decided after the generation-failure channel landed, because two of the four
  providers need it

## Context

There was one generation provider, and every convention written around it was written against that
one. `services/catena/AGENTS.md` said generation sits "behind an OpenAI-compatible interface … the
**wire format** is what delivers that, not a vendor SDK." SHARED §1 said the same thing as a MUST:
the provider sits behind "an interface using the OpenAI-compatible chat-completions shape as the
internal lingua franca." The Phase 1 TECHNICAL-SPEC and PLAN repeated it twice more, once as the
reason `response_format` travels on the chat-completions endpoint rather than as Ollama's native
`format` field.

The claim is false, and it was written when it had no way to be wrong. What made the single provider
replaceable was never the shape of its HTTP body; it was that `service.py` calls
`self._generator.generate(messages, schema.answer_schema())` and depends on the `Generator` protocol
and the answer object, and on nothing else. The wire format is an implementation detail of one
adapter behind that protocol.

**The Anthropic Messages API is the case that separates the two claims.** Same protocol — it returns
a `Generation` and a `GenerationFailed` like every other adapter — but a different wire format, a
different place for the schema (`output_config.format` rather than `response_format`), and a vendor
SDK in the request path. Under the old convention that provider is forbidden for a reason that has
nothing to do with whether it works. Under the protocol it is one module.

Three hosted counterparties rather than one also changes arithmetic that a previous decision settled
for a single case. Verification check 4 runs in Go, *after* generation, so a hosted provider receives
retrieved corpus text before the gateway has ruled on whether that text may be served. ADR-0017
settles the principle — the deployer's key, the deployer's terms, and a project that automates
nothing around anyone's terms — and it applies here unchanged. What does not carry over is the
prose: with one recipient, "a third party" was specific enough to be read as a fact. With three, a
deployer weighing a `local-only` corpus against a hosted generator cannot tell from the sentence who
receives the passages, so the recipient is named per provider instead.

## Decision

**Four generation providers ship behind the typed `Generator` protocol, selected by one environment
variable, with one module per wire format.**

`CATENA_GENERATION_PROVIDER` selects the provider; `CATENA_GENERATION_MODEL` optionally selects a
model *within* it and must name a model that provider serves. No code change chooses a provider;
adding a fifth is a table entry plus an ADR.

| provider | wire | base URL | key | default model | price in/out per MTok | schema delivery | probed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ollama` *(default)* | `openai_chat` | `CATENA_OLLAMA_URL` | — | `qwen3:8b-q4_K_M` | — runs locally | **constrained** | yes |
| `anthropic` | `messages` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` | $2 / $10 | **constrained** | no — read from documentation |
| `openai` | `openai_chat` | `https://api.openai.com` | `OPENAI_API_KEY` | `gpt-6-luna` | $0.10 / $0.50 | **shaped** | no |
| `deepseek` | `openai_chat` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `deepseek-flash` | see the provider | **shaped** | yes |

The `probed` column is part of the contract and not a footnote. A mode read from a provider's
documentation is a claim about what the request will be allowed to enforce, and the two sources of
that claim fail differently: a probed mode has been observed, an unprobed one can still turn out to
be a 400 at the first question. Recording which is which in the table means a later reviewer reads
the provenance of the claim rather than inferring it from the confidence of the prose.

Model identifiers were read from each provider's live documentation on 2026-09-30, not recalled. All
three hosted defaults postdate this project's training-era assumptions and two of the three names
would have been wrong if guessed, which is why the pin test that guards `ollama`'s tag against
`models.lock.yaml` was extended to assert each hosted default against the table.

**Two modules speak HTTP, one per wire format, not one per provider.** `generate/openai_chat.py` is
a stdlib `urllib` POST serving `ollama`, `openai` and `deepseek`; `generate/messages.py` is the
Anthropic vendor SDK serving `anthropic`. The vendor SDK is a considered reversal of the stdlib
preference and is confined to the one adapter whose wire format requires it: `anthropic>=1.10,<2`,
MIT licensed, so ADR-0007's posture on downstream commercial use is unaffected.

**Base URLs are pinned in the table and never read from the environment.** This is not cosmetic. The
Anthropic SDK reads `ANTHROPIC_BASE_URL` from the environment on its own, so without an explicit
value an ambient variable silently redirects every retrieved passage to a third party while the
configuration, the trace and CORPUS-POLICY all still name Anthropic. Pinning makes the provider
named `anthropic` *be* Anthropic. An ambient variable must not be able to choose who receives
retrieved corpus text.

### The three delivery modes, and the property that earns them

The schema does not change. It is derived from the proto descriptor and ADR-0023's rules hold
unaltered under all three modes. What varies is what the provider's request will *enforce*.

| mode | the request enforces | what can go wrong | which channel catches it |
| --- | --- | --- | --- |
| **constrained** | the decoder is held to the schema | semantic violations only | verification, `trace.answer_failures` |
| **shaped** | JSON-ness only; the schema is requested | fields missing, extra, or wrong-typed | `trace.answer_failures` — the object parses |
| **unconstrained** | nothing | the reply may not be JSON | `trace.generation_failures` |

**The property that earns the modes is that each fails into a channel that already exists.** A
shaped provider still produces a parseable object, so its wrong slots regenerate through ADR-0024's
machinery with no new code. An unconstrained provider's non-JSON reply is
`GENERATION_FAILURE_CODE_NOT_JSON` in ADR-0025's channel, which is why that work landed first. Two
of the four providers cannot be held to the schema by their decoder, and shipping them before there
was somewhere for a malformed generation to go would have been dishonest.

`GENERATION_FAILURE_CODE_NOT_JSON` is rarer than it looks and is **not** a DeepSeek-specific
concession: `deepseek-flash` is shaped rather than unconstrained because `response_format` accepts
`{"type": "json_object"}` — verified — which guarantees JSON without guaranteeing the schema. The
code exists because Phase 1 acceptance measured it firing on the pinned local model, under
constrained decoding, with no hosted provider involved.

Each adapter puts the schema where its own wire and mode require it — in `response_format`, in
`output_config.format`, or appended to the system message as text. `prompt.py` learns nothing about
providers, which keeps the translation at the provider's own edge.

### Two parameters that are decisions, not tuning

**`thinking` is sent explicitly as `{"type": "adaptive"}`** on the Messages API. `claude-sonnet-5-5`
is adaptive-capable but not always-on, so *omitting* the parameter is not the same as leaving
thinking enabled — and thinking-off on this family can push reasoning into the visible text, which
is the one thing CLAUDE.md constraint 5 forbids shipping. Omission was a live bug on this default and
a latent one on the model PR #23 was written against, which is why the test asserts the value
positively rather than asserting the parameter's absence.

**`effort` is `medium`, a deliberate downgrade** from this model's default of `high`. ADR-0018 found
reasoning ability "close to irrelevant here": the task is routing claims into slots and copying text
verbatim, and the trust boundary catches the model when it does not. Recorded as a choice so it is
not silently inherited by the next model.

Neither parameter's output is read. `reasoning` on the OpenAI-compatible wire, `thinking` blocks and
a refusal's `stop_details.explanation` on the Messages API — none of them has a path into a return
value, a trace or a log.

### Two decisions the design left to the plan

**`openai` ships `shaped`, not "probe decides".** The design's table left the cell to a probe that
needs a deployer key, and a table has to hold a value before the probe runs. The two candidates fail
differently: shipping `constrained` unprobed risks a 400 on *every* request — a `ServeError` at the
first question, not a generation failure — and "the failure channel catches what it catches" only
holds for requests that actually reach the model. `shaped` reaches it under either answer. A probe
then promotes the cell, which is a one-line table edit plus an amendment, and the trace's delivery
mode is what keeps the two eras of runs distinguishable. If strict structured outputs do demand every
property in `required`, `openai` stays shaped: ADR-0023 measured the all-required shape producing
`position: "no_position"` beside empty `arguments`, and the contract does not bend to fit a provider.

**Open question 1 is answered from current documentation, and the probe is reduced to confirming it
live.** Finding: `output_config.format` accepts `$ref`/`$defs`, string enums, `anyOf` and
`additionalProperties: false` — which it in fact *requires* on every object — and documents as
unsupported only recursive schemas, numeric constraints, string constraints and complex array
constraints, none of which the derived schema uses. The derived schema is `$defs` plus `$ref`, string
enums, `additionalProperties: false` throughout, and a top-level `required: []`. So the adapter sends
it **verbatim** and the probe confirms rather than decides. The instruction for a negative answer
stands unchanged: inline the definitions at that adapter's edge, never hand-write a second schema and
never relax ADR-0023 to suit a provider.

## What it amends

**ADR-0018.** Hosted is no longer rejected outright. Its rejection of "a hosted API **by default**"
stands in full and is the reason `ollama` remains the default: the no-external-accounts acceptance
test is the rule a change cannot be worth breaking, and nothing here breaks it. What is amended is
the scope of the pin — it applies to the *default*, not to every run — and the count of candidates:
"re-decided at Phase 2 against the golden set" now has four rather than one.

**ADR-0023.** The derived schema is unchanged, in every particular: `confidence` still subtracted,
the list-only `required` rule intact, no count constraints. What is now provider-dependent is its
*enforcement*. Two providers request the schema and cannot guarantee it, and the difference is
recorded per run rather than assumed globally.

**ADR-0010.** Unchanged: one regeneration on a verification failure, at most two calls into Python
per turn, and a generation failure consumes it as ADR-0025 settled. It now also binds a vendor SDK's
own retry loop to zero. The Anthropic SDK retries on its own by default, and an unbound retry inside
one attempt would make "one gRPC call per generation attempt" a statement about Go's call count and
not about how many times the model was asked.

## Alternatives rejected

- **Provider definitions as operator YAML.** Genuinely attractive: Together, Groq, OpenRouter or a
  local vLLM with no Python at all. Rejected because it moves the capability claim from something
  this project probed to something the operator asserts, and a wrong assertion does not surface as a
  configuration error — it surfaces as a mysterious degradation rate. The `probed` column above is
  exactly what a file format cannot promise.
- **A module per provider.** The repo's shape before this change, and the smallest conceptual step.
  Rejected because three of the four would be near-identical OpenAI POSTs — the duplication the
  review standards flag, and a bug fixed in one would not reach the others.
- **A generic base-URL-plus-key escape hatch as the primary interface.** Maximally flexible, and
  least safe: every unsafe endpoint becomes equally one typo away, the documentation can no longer
  name who receives corpus text, and a model and an endpoint can be paired incoherently.
- **One generator parameterised by strategy objects.** The most factored option, and over-abstract
  for four providers — three indirections to answer "what does DeepSeek send?"
- **Refusing providers that cannot constrain decoding.** The safest reading, and it makes the
  project's own instinct inconsistent: `retrieval.py` leaves its known risk "naive and measured, not
  pre-empted", and the trust boundary means unconstrained output is caught rather than shipped. The
  degradation and generation-failure rates are the measurement; refusing to run is a way of not
  having it.

## Consequences

**The stated cost is that providers receive different prompts, so cross-provider quality comparison
is confounded.** Each adapter delivers the schema where its wire and mode require, which means the
`shaped` providers carry schema text the `constrained` ones do not. The alternative — send the schema
text to every provider so the prompts match — was rejected because the local default is the slowest
component in the system at roughly 3.4 tokens per second and would pay tokens for enforcement it
already has. The confound is not removed; it is made visible. `schema_delivery` is on the trace, so a
comparison that crosses modes can be seen to have crossed them rather than being read as a clean
result.

**Three things protect the Phase 2 baseline**, and they are the conditions on which four providers
do not undo ADR-0018's reason for pinning one. The **default does not move**: `ollama` and the
pinned tag, `docker compose up` working with no external accounts, and `make dev-offline` continuing
to prove it with egress blocked — a hosted provider fails loudly there rather than degrading
quietly. The **trace attributes the run**: `generation_provider` and `schema_delivery` beside
`generation_model`, persisted by migration `000008` in `trace.traces`, because without the mode two
runs of one model under different enforcement are indistinguishable in the tables the harness reads.
And **the baseline is the default**: a hosted run is legitimate and is labelled, but it is not
quotable as the baseline. Phase 2's harness does not exist yet, so this guarantees only that the
trace *can* attribute a run; it does not design the harness.

**Egress has a second exception, and the spec now says so.** SHARED §1's steady-state rule listed the
ESV adapter as the sole exception. The hosted providers are the second, on the same terms —
deployer-enabled, never default, sending data to a third party only under a deployer's explicit
configuration.

**A hosted provider's key is a startup concern, not a request-time one.** `connect()` refuses a
hosted provider whose key is unset, so a misconfiguration is a configuration error reported at
startup rather than a stack that comes up healthy and cannot answer. The three key variables are
present and empty in `compose.yaml`, and empty is correct.

**What it makes harder.** The provider table is now a fact that six documents reproduce, and a table
that contradicts `.env.example` is worse than either alone — the guard against that is that the
table in code is the source and the pin test fails in CI rather than at a 404. Two unprobed cells
ship, and the honest reading of an unprobed `constrained` is that it may turn out to be a startup
error for the deployer who tries it first.

**What would cause us to revisit it.** A probe that promotes `openai` to `constrained`, which is the
expected next move and is a table edit plus an amendment. A fifth provider whose wire format is
neither of the two — that is a third module, and if it is also a third vendor SDK the stdlib
preference is worth re-arguing rather than eroding twice. And if Phase 2 finds that a hosted
provider's quality difference is large enough to matter, the question ADR-0018 deferred becomes a
real decision rather than a hypothetical one, with four candidates and a trace that can tell them
apart.

## Documents updated

- `docs/adr/README.md` — the 0026 row, and the 0018 and 0023 rows' Status cells annotated with what
  0026 amends.
- `specs/SHARED-TECHNICAL-SPEC.md` — §1's generation-provider requirement becomes the typed
  interface rather than the wire format, with a second bullet stating what a hosted provider MUST
  NOT be and that its base URL is pinned in code; §1's steady-state egress bullet gains the hosted
  providers as an exception; §7 gains the requirement that every trace attribute its run to a
  provider and a delivery mode.
- `services/catena/AGENTS.md` — the generation convention rewritten around the typed protocol, with
  what a provider enforces separated from what the schema is; the thinking bullet restated as
  per-provider rather than as a blanket rule.
- `docs/CORPUS-POLICY.md` — a new section naming who receives retrieved corpus text per provider,
  and the check-4 ordering that makes the question live.
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — the generation section: the typed protocol and
  the provider table, the three delivery modes in place of the reversed `response_format` claim, the
  thinking paragraph scoped to the local default, and the two new trace fields.
- `specs/001-phase-1-pca-baseline/PLAN.md` — the acceptance item's rationale corrected (the item was
  delivered; only its reason was misstated), the trace item's field list extended, and the thinking
  finding marked as Qwen3's mechanism rather than a blanket rule.
- `specs/001-phase-1-pca-baseline/GENERATION-PROVIDERS-DESIGN.md` — the `openai` delivery cell, open
  questions 1 and 2, and Status, per CLAUDE.md's rule that a decision the spec did not anticipate is
  written back into the spec in the same change.
- `.env.example`, `compose.yaml`, `README.md` — the two provider variables, the three keys commented
  out with no value, and the per-provider cost table with what to read before setting one.
- `services/catena/pyproject.toml` — `anthropic>=1.10,<2`, and why a vendor SDK in the request path
  is a considered reversal. Landed with the Messages adapter, ahead of these documents, rather than
  with them.
