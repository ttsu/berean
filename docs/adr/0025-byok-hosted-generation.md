# ADR-0025: Hosted generation is a deployer's configuration, never a default

- **Status:** Accepted
- **Date:** 2026-09-11
- **Phase:** 1 — decided after acceptance, and it changes nothing acceptance measured

## Context

The code needed for a second generator is nearly nothing, and that is the first thing to say
plainly, because it is what makes this a documentation decision rather than an engineering one.
`service.py` calls `self._generator.generate(messages, schema.answer_schema())` and knows nothing
else about the model. `RetrievalTrace.generation_model` already records what answered. Langfuse
instrumentation, timings, and the truncation guarantee all sit above the seam. A second
implementation of the `Generator` protocol inherits every one of them without being asked to.

What is not nearly nothing is that **three commitments this project has in writing say something
narrower than the seam does**, and each of them is a sentence someone would reasonably read as
forbidding this:

- **SHARED §1, the egress rule.** "Steady-state operation MUST require no network egress … The ESV
  adapter is the sole exception and is deployer-enabled, never default." A hosted generator is a
  second exception, and "sole" is not a word that stretches.
- **SHARED §1, the provider rule.** The provider must "sit behind an interface using the
  OpenAI-compatible chat-completions shape as the internal lingua franca, so Ollama, vLLM,
  llama.cpp, and hosted APIs are interchangeable." The Claude API is not that shape, and the
  sentence names hosted APIs as the thing the requirement exists to enable — so the rule as written
  defeats its own stated purpose. `services/catena/AGENTS.md` puts the same claim more sharply
  still: "The **wire format** is what delivers that, not a vendor SDK."
- **ADR-0018.** "A hosted API by default … Rejected outright: it breaks the no-external-accounts
  acceptance test." That reasoning is about the default and survives untouched, but the rejection is
  on the record without that qualifier.

The wire-format claim is the one that was actually wrong, and it was wrong before this change made
it visible. Interchangeability was never delivered by two providers happening to speak one vendor's
JSON dialect; it is delivered by `service.py` depending on one method and a documented return.
Ollama's OpenAI-compatible endpoint is how the *first* provider satisfied the protocol, not what the
protocol is. Writing the accident into a normative spec meant that adding the second provider —
the exact case the rule was written to enable — required amending it.

## Decision

**A hosted generation provider is a deployment configuration a deployer selects by name and pays
for. The default path is unchanged.**

- `CATENA_GENERATION_PROVIDER` selects, defaulting to `ollama`. `connect()` dispatches on it and
  raises on an unknown value, naming the ones that exist.
- **Selection is never inferred from a key.** An `ANTHROPIC_API_KEY` sitting in a developer's shell
  must not be able to start egress. A configuration that turns itself on is the opposite of a
  recorded act, which is the property ADR-0017 relies on everywhere else.
- The key is the deployer's. This project ships none, and with `anthropic` selected and no key the
  failure lands in `connect()` at server startup, beside the existing unset-`CATENA_OLLAMA_URL`
  failure, rather than at the first question a user asks.
- Each provider owns its pinned model and its own constants, and the trace records the model the
  *response* reports rather than the one requested. ADR-0018's requirement that a silent model
  change must not be able to move the Phase 2 baseline binds both providers or neither.
- Truncation and refusal both raise. Neither may be presented as an answer, and specifically neither
  may wear the all-slots-empty shape ADR-0020 reserves for the corpus actually being silent.
- Nothing retries. The SDK client is constructed with `max_retries=0`, because ADR-0010 fixes the
  retry at exactly one regeneration driven by Go on a *verification* failure, and a transport retry
  hidden underneath would make `attempt` mean two different things while hiding a failing provider
  behind a latency spike.

The prompt is still built OpenAI-shaped, and a provider whose API is shaped otherwise translates at
its own edge — here, hoisting the system message out of the turns. That is the whole of what the
seam costs, and it is the right place to pay it.

### The licence ordering, stated rather than discovered

Check 4 runs in Go, at verification, **after** generation. Retrieval does not filter on licence. So
a hosted generator transmits retrieved passages to a third party before the gateway has ruled on
whether the licence permits serving them. Today that ordering is invisible because the model is on
the same machine; with a hosted provider it is the substance of the choice.

**ADR-0017's answer applies unchanged, because it is the same question.** That ADR settles ESV on
the deployer's key, the deployer's account, the deployer's acceptance of terms, and states the
posture directly: this project "automates nothing around anyone's terms, ships no key and no text,
and leaves the acceptance of terms with the party who can actually accept them." Sending retrieved
text to a model the deployer pays for, under their own account, is processing on their behalf. It
is not this project publishing anything. The opt-in being a recorded act is what makes that true
rather than merely arguable, and CORPUS-POLICY now states the ordering in plain words so a deployer
weighing a `local-only` corpus against a hosted generator is deciding with the facts in front of
them instead of inferring them from `service.py`.

ESV and NIV are unaffected under every configuration. They are never ingested and are fetched at
render time by the gateway, so they cannot appear in a Catena prompt at all.

## Alternatives rejected

- **Filter the prompt by licence when the generator is remote.** The safest-looking reading, and
  wrong twice. It puts a licence decision in Python, which `services/catena/AGENTS.md` lists under
  *Does not own* — the trust boundary is in Go precisely so that this class of judgement has one
  home. And it makes the retrieved set differ by provider, so two generators would no longer be
  answering the same question and nothing measured across them would be comparable.
- **Refuse remote generation whenever a `local-only` corpus is indexed.** Superficially the
  conservative choice. `pca-bco-2026` is `local-only` and is in the Phase 1 index, so the rule
  refuses every configuration that exists: it is "not yet" wearing a rule's clothes, and a rule that
  forbids the only case it will ever see teaches nobody anything.
- **Hand-roll `/v1/messages` over stdlib `urllib`** to preserve the convention the local provider
  keeps. Tempting, because the convention is real and `acquire.fetch` earns it. Rejected because the
  two cases are not alike: `acquire.fetch` speaks HTTP to a static file, while this would mean
  hand-maintaining auth, versioning headers, an error taxonomy, and a response schema against an API
  that moves — with nothing in the repository that would notice the drift until an answer failed.
  A dependency whose upgrade is someone else's job is cheaper than a convention held by hand.
- **An OpenAI-compatible shim in front of the hosted API**, preserving the lingua-franca rule
  literally. Rejected because the translation loses exactly the features that motivate the change:
  structured output, thinking, and the refusal stop reason all either vanish or are misrepresented
  through the compatibility layer, and a refusal arriving as an ordinary completion is a failure
  mode invented by the shim. Keeping the letter of a rule by degrading the thing it governs is not
  compliance.
- **Make the hosted provider the default and gate it on a key being present.** Dispatched with
  ADR-0018's argument, which needs no restating: `docker compose up` with no external accounts is
  the acceptance test, and a default that silently changes behaviour depending on what is in the
  environment is worse than either configuration chosen deliberately.

## Consequences

**The first vendor SDK in the request path.** `services/catena/pyproject.toml` has until now been
able to say that the request path speaks HTTP and nothing else. It no longer can, and the honest
framing is that the dependency is confined to a module a default deployment never imports —
`connect()` imports the provider lazily — rather than that the rule is intact.

**A BYOK run has no determinism to record.** Sampling parameters are rejected on this model, so
there is no `temperature: 0.0` to pin and no equivalent of the guarantee the local provider gives.
That is a second, independent reason the Phase 2 baseline stays local, alongside ADR-0018's: a
baseline is a measurement, and a distribution nobody recorded is not one.

**Refusal is a new failure mode with no local analogue.** It raises, naming the category, because a
policy decline is neither an answer nor silence — and an unnamed one would be diagnosed as a
retrieval failure, which is the wrong repair applied to the wrong component.

**Per-answer cost becomes a deployer's concern**, at roughly $0.05–0.08 for a Phase 1 prompt. The
figure is in the README so the choice is made with it visible. Prompt caching is deliberately not
part of this: the stable prefix is the rules block while the passages vary per question, so the win
is small and unmeasured until someone has a bill.

**`make dev-offline` is what keeps the default honest.** The overlay marks the network internal, so
a hosted provider reached from a default configuration fails there loudly. That is the test which
converts this ADR's central claim from an assertion into something checkable, and **a change that
makes a hosted provider reachable under that overlay is a defect**, not a convenience.

What would cause us to revisit: a hosted provider becoming a measured configuration in the eval
harness. That is a Phase 2 decision and it is not taken here — this change adds an option, not a
second thing the project promises about.

## Documents updated

- `specs/SHARED-TECHNICAL-SPEC.md` — §1: the egress exception is no longer sole, and both exceptions
  are named as deployer-enabled with `make dev-offline` as the enforcement; the provider bullet is
  restated around the typed interface, with the OpenAI shape demoted to the internal prompt
  representation
- `services/catena/AGENTS.md` — the Conventions bullet on generation: the `Generator` protocol, not
  a shared wire format, is what delivers interchangeability
- `docs/CORPUS-POLICY.md` — a new section stating that hosted generation transmits retrieved text
  to a third party before check 4 rules on it, and on whose terms
- `docs/adr/0018-qwen3-8b-as-the-generation-default.md` — the status line, and the hosted-API
  bullet in *Alternatives rejected*, narrowed to the default it always argued about
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — the Generation section: provider selection,
  the variables, the default, and the pointers to this ADR and the design
- `README.md` — the option, its non-default status, the deployer-supplied key, the per-answer cost,
  and what it sends
- `specs/001-phase-1-pca-baseline/BYOK-GENERATION-DESIGN.md` — *Status*: implemented
