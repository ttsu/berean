"""Generation: what the request path needs of a model, and who can provide it.

**The typed protocol is the interface, not the wire format.** One `Generator`
absorbs a stdlib `urllib` POST to an OpenAI-compatible endpoint and a vendor SDK
call to the Anthropic Messages API without either leaking past this package.
`service.py` calls `generate(messages, schema)` and depends on nothing else,
which is why adding providers moved no other module (ADR-0026).

Nothing here retries. ADR-0010 fixes the retry at exactly one regeneration
driven by Go on a *verification* failure; a transport retry hidden underneath
would make "attempt" mean two different things and hide a failing generator
behind a latency spike. This constrains the adapters too: a vendor SDK that
retries by default has to be told not to.

A completion that comes back unusable -- truncated, not JSON, not an object, no
choices -- is reported, not raised: `generate` returns a `GenerationFailed`
rather than raising, so the caller still has something to build a response from.
Raising used to discard the retrieval that already happened along with it; see
`MAX_TOKENS` for the acceptance failure that fixed (ADR-0025). A transport
failure (the provider unreachable, a non-2xx response) still raises `ServeError`
-- nothing was learned about the generator there, and there is no attempt worth
recording.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence

from catena.serve import ServeError

URL_ENV = "CATENA_OLLAMA_URL"
MODEL_ENV = "CATENA_GENERATION_MODEL"

#: The tag `make provision` pulls, pinned in `tools/provision/models.lock.yaml`
#: and written into every trace (ADR-0018). Duplicated here rather than read
#: from the lockfile because provisioning state has no business being read at
#: run time -- the build context denies the file -- and a test asserts the two
#: agree, so a bump that touches one and not the other fails in CI rather than
#: at the first answer that quietly used a different model.
DEFAULT_MODEL = "qwen3:8b-q4_K_M"


#: Generous, and measured rather than guessed. Qwen3-8B q4_K_M on the reference
#: machine generates at **~3.4 tokens/second** against a full ~5,900-token
#: prompt -- the KV cache makes each token dearer than the ~9 t/s a bare prompt
#: gets -- so `MAX_TOKENS` at that rate is twenty minutes before prompt
#: evaluation. A first attempt at 300 s cut a live answer off at 404 tokens.
#:
#: **These two constants are one decision, not two.** The ceiling is what a
#: complete answer object costs; the timeout is what that many tokens take to
#: emit. Raising either alone converts one failure into the other -- a ceiling
#: above the timeout's reach truncates at the wall clock instead of at the token
#: count, and a timeout without the ceiling to use it buys nothing. Phase 1
#: acceptance measured exactly that: see `MAX_TOKENS` below.
#:
#: SHARED §9 sets no generation target for Phase 1. The budget it does set is
#: for retrieval, which is measured separately in `Timings` and is three orders
#: of magnitude faster.
TIMEOUT_SECONDS = 900

#: The completion ceiling. High enough that a full answer object with several
#: cited arguments finishes, low enough that a model looping on one token stops
#: being this request's problem within the timeout.
#:
#: **This number is not what blocks UC-4, and raising it does not help.** Task 7
#: said so from the behaviour ("it is not a reason to raise `max_tokens`"); Phase 1
#: acceptance then measured it, and the numbers are recorded here so the argument
#: does not have to be had a third time. On "How long were the days of creation?":
#:
#:   ceiling   timeout   outcome
#:   2048       900 s    truncated, twice, deterministically
#:   4096      1800 s    truncated, after 24 min of generation
#:   8192      3000 s    no truncation -- the 50-minute timeout fired instead
#:
#: Each raise converted one failure into the other and bought nothing. What runs
#: away is the summarising, and it scales with how much source material is in
#: front of the model -- Task 7's diagnosis, unchanged. `RULES` already caps the
#: answer at three arguments and three descriptions with one-sentence claims, and
#: bounding it further was tried twice there without effect.
#:
#: Acceptance added two things Task 7 did not predict. It does **not** degrade:
#: at acceptance time the truncation guard raised, so the turn died inside
#: Catena with no `AnswerObject` to verify and **no row in `trace.responses`**
#: -- invisible to the Phase 2 harness, which reads the trace. It now returns a
#: `GenerationFailed` instead of raising, so the trace that retrieval already
#: built survives the failure and reaches the harness -- the ceiling and the
#: measurements above are unchanged; only what happens at the ceiling is. And
#: it is not confined to the contested locus: "What does the Westminster
#: Confession teach about justification?" ran away the same way, so the
#: trigger is a broad question, not a contested one.
#:
#: See specs/001-phase-1-pca-baseline/ACCEPTANCE.md.
MAX_TOKENS = 2048

#: A callable so tests assert the request without a network. Takes the URL, the
#: encoded body, the headers and a timeout; returns the raw response bytes.
Transport = Callable[[str, bytes, dict[str, str], float], bytes]

#: The wire formats, one module each.
OPENAI_CHAT = "openai_chat"
MESSAGES = "messages"

#: What a provider's request enforces of the answer schema. The schema itself
#: never varies -- it is derived from the proto descriptor and ADR-0023's rules
#: hold unaltered. What varies is enforcement, and each mode fails into a
#: channel that already exists (ADR-0026):
#:
#:   constrained    the decoder is held to the schema; semantic violations only,
#:                  caught by verification and `answer_failures`
#:   shaped         JSON-ness only, and the schema is requested as text. The
#:                  object parses, so a wrong slot regenerates through
#:                  ADR-0024's machinery with no new code
#:   unconstrained  nothing. The reply may not be JSON, which is what
#:                  GENERATION_FAILURE_CODE_NOT_JSON catches (ADR-0025)
CONSTRAINED = "constrained"
SHAPED = "shaped"
UNCONSTRAINED = "unconstrained"
DELIVERY_MODES = (CONSTRAINED, SHAPED, UNCONSTRAINED)

PROVIDER_ENV = "CATENA_GENERATION_PROVIDER"
DEFAULT_PROVIDER = "ollama"


@dataclass(frozen=True)
class Provider:
    """One row of the reviewed table. Every field is a claim a test asserts.

    Operator YAML was considered and rejected (ADR-0026): it would move the
    capability claim from something this project probed to something the
    operator asserts, and a wrong assertion surfaces as a mysterious
    degradation rate rather than as a clear fact.
    """

    name: str
    #: Which module speaks for it.
    wire: str
    #: Absolute and pinned for a hosted provider, empty for a local one. Never
    #: read from the environment when set: the Anthropic SDK reads
    #: ANTHROPIC_BASE_URL by itself, so an ambient value would silently
    #: redirect every retrieved passage to a third party while the
    #: configuration, the trace and CORPUS-POLICY all still named Anthropic.
    #: Pinning is what makes the provider named `anthropic` *be* Anthropic.
    base_url: str
    #: Where a local provider's URL comes from instead. Empty when pinned.
    url_env: str
    #: Empty for a provider that needs no account. The key is read at
    #: `connect()` and never defaulted -- a stack that starts and cannot answer
    #: is a configuration error reported at the worst possible moment.
    key_env: str
    default_model: str
    delivery: str
    #: Whether the delivery mode above was *probed* against the live provider
    #: or read from its documentation. An unprobed mode is not a reason to
    #: refuse the provider -- `retrieval.py` leaves its known risk "naive and
    #: measured, not pre-empted", and the trust boundary means unconstrained
    #: output is caught rather than shipped. It is recorded so the degradation
    #: and generation-failure rates can be read knowing which is which.
    probed: bool
    #: Provider-specific request parameters, as pairs so a frozen entry is
    #: genuinely immutable rather than merely annotated as one.
    params: tuple[tuple[str, Any], ...] = ()


#: The four providers this build ships. Adding a fifth is a small change plus an
#: ADR (ADR-0026); it is deliberately not a file format.
PROVIDERS: dict[str, Provider] = {
    DEFAULT_PROVIDER: Provider(
        name=DEFAULT_PROVIDER,
        wire=OPENAI_CHAT,
        base_url="",
        url_env=URL_ENV,
        key_env="",
        default_model=DEFAULT_MODEL,
        delivery=CONSTRAINED,
        probed=True,
        # `temperature` is pinned only here, and that asymmetry is the point:
        # the Phase 2 baseline is a measurement, and a default temperature makes
        # it a distribution nobody recorded. The hosted providers get no
        # sampling parameters at all -- their parameter surfaces were not
        # probed, a hosted run is not quotable as the baseline anyway, and at
        # least one current model family rejects sampling parameters outright.
        # `reasoning_effort: "none"` is Qwen3's, for the reason openai_chat's
        # docstring gives; it is not a blanket rule.
        params=(("temperature", 0.0), ("reasoning_effort", "none")),
    ),
    "openai": Provider(
        name="openai",
        wire=OPENAI_CHAT,
        base_url="https://api.openai.com",
        url_env="",
        key_env="OPENAI_API_KEY",
        default_model="gpt-6-luna",
        # Shaped until a probe says otherwise. ADR-0023 measured the
        # all-required shape producing `position: "no_position"` beside empty
        # `arguments`, so if strict structured outputs demand every property in
        # `required`, the contract does not bend to fit the provider. Shipping
        # `constrained` unprobed would risk a 400 on every request -- a
        # ServeError at the first question, not a generation failure -- and the
        # failure channel can only catch what actually reaches the model. A
        # probe promotes this cell; see PLAN, "Two decisions the design left to
        # the plan".
        delivery=SHAPED,
        probed=False,
    ),
    "deepseek": Provider(
        name="deepseek",
        wire=OPENAI_CHAT,
        base_url="https://api.deepseek.com",
        url_env="",
        key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-flash",
        # Shaped, not unconstrained: `response_format` accepts
        # `{"type": "json_object"}` -- verified -- which guarantees JSON without
        # guaranteeing the schema.
        delivery=SHAPED,
        probed=True,
    ),
}


@dataclass(frozen=True)
class Generation:
    """One completion. Carries no account of how the model produced it."""

    #: The decoded JSON object. Structurally valid by construction when the
    #: provider constrained its decoder, and structurally *unverified* when it
    #: only shaped the reply -- which is what `AnswerObject` parsing in
    #: `service.py` and ADR-0024's channel are for. Semantically untrusted
    #: under every mode.
    payload: dict[str, Any]
    #: What actually answered, as reported by the server rather than as
    #: requested. The trace records this, so it has to be the former.
    model: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class GenerationFailed:
    """No answer object, and why. Returned rather than raised.

    Raising killed the turn inside this service and discarded the
    `RetrievalTrace` with it, so the failure left no row in `trace.responses`
    and was invisible to the harness that reads them (ACCEPTANCE.md, Q4 and
    Q10). The code is the proto enum's short name; this module imports no
    proto -- `service.py` maps it.
    """

    code: str
    #: Factual. Never the model's account of its own reasoning: for a refusal
    #: this is the provider's category, never its explanation (constraint 5).
    detail: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Generator(Protocol):
    """What the request path needs of a model, and nothing more.

    This protocol is the interface that makes providers interchangeable. The
    wire format is not, and the Anthropic Messages API is the case that
    separates the two claims (ADR-0026).
    """

    #: Written to `RetrievalTrace.generation_model`.
    model: str
    #: Written to `RetrievalTrace.generation_provider`. Present on the adapter
    #: rather than on `Generation`, so a failed attempt still names what
    #: attempted it.
    provider: str
    #: One of `DELIVERY_MODES`, written to `RetrievalTrace.schema_delivery`.
    #: Without it, two runs of one model under different enforcement are
    #: indistinguishable in the data the Phase 2 harness reads.
    delivery: str

    def generate(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> Generation | GenerationFailed:
        """One completion, a reported failure, or `ServeError`."""
        ...


def _base_url(entry: Provider) -> str:
    """Where the request goes. Pinned in the table, or a local deployment's URL.

    Nothing here consults the environment for a provider whose `base_url` is
    set. See `Provider.base_url`.
    """
    if entry.base_url:
        return entry.base_url
    base = os.environ.get(entry.url_env, "").strip()
    if not base:
        raise ServeError(
            f"{entry.url_env} is unset. Provider {entry.name!r} runs against a local "
            "server the compose stack provides -- run the service through `make dev`."
        )
    return base


def _api_key(entry: Provider) -> str:
    """The deployer's key, read once at startup.

    Read here rather than per request so a missing key is a configuration error
    at `connect()` instead of a failure at the first question, which reads to
    whoever sees it like a broken provider.
    """
    if not entry.key_env:
        return ""
    key = os.environ.get(entry.key_env, "").strip()
    if not key:
        raise ServeError(
            f"provider {entry.name!r} needs {entry.key_env}, which is unset. A hosted "
            "provider is deployer-enabled and never default (SHARED §1); see "
            "docs/CORPUS-POLICY.md for who receives retrieved corpus text under it."
        )
    return key


def _model(entry: Provider, model: str | None) -> str:
    """The pinned default, or the deployer's override within this provider.

    `CATENA_GENERATION_MODEL` applies inside the selected provider and must name
    a model that provider serves. ADR-0018 documents a smaller local fallback
    for low-RAM machines and is explicit that it is a degradation rather than a
    second supported configuration. The trace records what actually answered,
    so a deployment running the fallback is visible in the data rather than only
    in someone's shell history.
    """
    return model or os.environ.get(MODEL_ENV) or entry.default_model


def connect(provider: str | None = None, model: str | None = None) -> Generator:
    """The generator the server runs with.

    One environment variable chooses among the providers in `PROVIDERS`, and a
    key in the environment is a credential rather than a selection: an ambient
    `OPENAI_API_KEY` does not move a deployment off the local default.
    """
    # Local: the adapters import this module's primitives, so importing them at
    # module scope is a cycle -- and it keeps a vendor SDK off the import path
    # of a deployment that never selects it.
    from catena.serve.generate import openai_chat

    name = (provider or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip()
    entry = PROVIDERS.get(name)
    if entry is None:
        raise ServeError(
            f"{PROVIDER_ENV}={name!r} names no provider this build ships. "
            f"The providers are: {', '.join(sorted(PROVIDERS))}."
        )

    if entry.wire == OPENAI_CHAT:
        return openai_chat.OpenAIChatGenerator(
            entry, _model(entry, model), _base_url(entry), api_key=_api_key(entry)
        )
    raise ServeError(f"provider {name!r} names wire format {entry.wire!r}, which has no adapter")
