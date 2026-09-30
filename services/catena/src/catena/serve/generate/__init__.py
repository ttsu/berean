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


def default_model() -> str:
    """The pinned tag, or the deployer's override.

    ADR-0018 documents a smaller fallback for low-RAM machines and is explicit
    that it is a degradation rather than a second supported configuration. The
    trace records what actually answered, so a deployment running the fallback
    is visible in the data rather than only in someone's shell history.
    """
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL


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
    """What the request path needs of a model, and nothing more."""

    #: Written to `RetrievalTrace.generation_model`.
    model: str

    def generate(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> Generation | GenerationFailed:
        """One completion, a reported failure, or `ServeError`."""
        ...


def connect(url: str | None = None, model: str | None = None):
    """The generator the server runs with."""
    from catena.serve.generate import openai_chat

    base = url or os.environ.get(URL_ENV)
    if not base:
        raise ServeError(
            f"{URL_ENV} is unset. Generation runs against the Ollama the compose "
            "stack provides -- run the service through `make dev`."
        )
    return openai_chat.OllamaGenerator(base, model or default_model())
