"""The Ollama provider, over its OpenAI-compatible endpoint.

What makes providers interchangeable is the **`Generator` protocol** —
`service.py` depends on one method and a documented return — and not this
endpoint's wire format. The claim that used to stand here said the opposite,
and ADR-0025 names it as the sentence that was wrong: this shape is how the
*first* provider satisfied the protocol, not what the protocol is. The hosted
provider speaks its vendor's own API and translates at its own edge.

What the OpenAI-compatible endpoint earns on its own terms is this client: a
single POST over stdlib `urllib`, no SDK, the same reasoning that keeps
`acquire.fetch` on stdlib — and it costs the one image that has to fit
alongside 2.3 GB of BGE-M3 nothing at all.

Two things about the request are load-bearing rather than tuning.

**`reasoning_effort: "none"`.** Qwen3 is a thinking model and its thinking is
not covered by the decoding constraint. A probe against the pinned tag with a
schema attached spent all 200 tokens of its budget inside `reasoning` and
returned `content: ""` with `finish_reason: "length"` — so leaving thinking on
does not merely slow the answer down, it prevents there being one. And the
field is the model's narrative about its own reasoning, which CLAUDE.md
constraint 5 forbids shipping. Hence `_content`, which reads `content` and
nothing else: the thinking is discarded unread, and there is nowhere in this
package for it to go.

**`response_format`.** ADR-0018 requires `AnswerObject` validity to be a
decoding constraint rather than a request the prompt makes politely. Ollama's
OpenAI-compatible endpoint honours a full JSON Schema here, `$defs` and `$ref`
and enums included — verified against the pinned tag before this was written.

Nothing here retries. ADR-0010 fixes the retry at exactly one regeneration
driven by Go on a *verification* failure; a transport retry hidden underneath
would make "attempt" mean two different things and hide a failing generator
behind a latency spike.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Sequence

from catena.serve import ServeError
from catena.serve.generate import Generation, model_override

URL_ENV = "CATENA_OLLAMA_URL"

#: The tag `make provision` pulls, pinned in `tools/provision/models.lock.yaml`
#: and written into every trace (ADR-0018). Duplicated here rather than read
#: from the lockfile because provisioning state has no business being read at
#: run time — the build context denies the file — and a test asserts the two
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
    return model_override() or DEFAULT_MODEL


#: Generous, and measured rather than guessed. Qwen3-8B q4_K_M on the reference
#: machine generates at **~3.4 tokens/second** against a full ~5,900-token
#: prompt — the KV cache makes each token dearer than the ~9 t/s a bare prompt
#: gets — so `MAX_TOKENS` at that rate is twenty minutes before prompt
#: evaluation. A first attempt at 300 s cut a live answer off at 404 tokens.
#:
#: **These two constants are one decision, not two.** The ceiling is what a
#: complete answer object costs; the timeout is what that many tokens take to
#: emit. Raising either alone converts one failure into the other — a ceiling
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
#:   8192      3000 s    no truncation — the 50-minute timeout fired instead
#:
#: Each raise converted one failure into the other and bought nothing. What runs
#: away is the summarising, and it scales with how much source material is in
#: front of the model — Task 7's diagnosis, unchanged. `RULES` already caps the
#: answer at three arguments and three descriptions with one-sentence claims, and
#: bounding it further was tried twice there without effect.
#:
#: Acceptance added two things Task 7 did not predict. It does **not** degrade:
#: the truncation guard raises, so the turn dies inside Catena with no
#: `AnswerObject` to verify and **no row in `trace.responses`** — invisible to the
#: Phase 2 harness, which reads the trace. And it is not confined to the contested
#: locus: "What does the Westminster Confession teach about justification?" ran
#: away the same way, so the trigger is a broad question, not a contested one.
#:
#: See specs/001-phase-1-pca-baseline/ACCEPTANCE.md.
MAX_TOKENS = 2048

#: A callable so tests assert the request without a network. Takes the URL, the
#: encoded body and a timeout; returns the raw response bytes.
Transport = Callable[[str, bytes, float], bytes]


def _urllib_transport(url: str, body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


class OllamaGenerator:
    """The default provider: Ollama, over its OpenAI-compatible endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        max_tokens: int = MAX_TOKENS,
        timeout: float = TIMEOUT_SECONDS,
        transport: Transport | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/v1/chat/completions"
        self.model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._transport = transport or _urllib_transport

    def generate(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> Generation:
        body = json.dumps({
            "model": self.model,
            "messages": list(messages),
            "max_tokens": self._max_tokens,
            # Deterministic-ish: the Phase 2 baseline is a measurement, and a
            # default temperature makes it a distribution nobody recorded.
            "temperature": 0.0,
            "reasoning_effort": "none",
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer_object", "strict": True, "schema": schema},
            },
        }).encode()

        try:
            raw = self._transport(self._url, body, self._timeout)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            raise ServeError(
                f"ollama refused the generation request ({error.code}): {detail}"
            ) from error
        except Exception as error:  # transport, DNS, timeout
            raise ServeError(
                f"ollama is unreachable at {self._url}: {error}. The generator runs in "
                "the compose stack — check that the `ollama` service is healthy."
            ) from error

        return self._parse(raw)

    def _parse(self, raw: bytes) -> Generation:
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ServeError(f"ollama returned a body that is not JSON: {error}") from error

        choices = response.get("choices") or []
        if not choices:
            raise ServeError("ollama returned no choices; there is no answer to verify")
        choice = choices[0]

        if choice.get("finish_reason") == "length":
            # Never handed upstream as an empty answer. An all-slots-empty
            # answer with no reason is the honest-silence shape, and a
            # truncation must not be able to wear it (ADR-0020).
            raise ServeError(
                f"the generation was truncated at {self._max_tokens} tokens; the answer "
                "object is incomplete and must not be presented as considered silence"
            )

        payload = self._content(choice)
        usage = response.get("usage") or {}
        return Generation(
            payload=payload,
            model=response.get("model") or self.model,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )

    @staticmethod
    def _content(choice: dict[str, Any]) -> dict[str, Any]:
        """`content`, and deliberately nothing else.

        A thinking model also returns `reasoning`. It is not read here, not
        returned, and not stored anywhere in this package — the one seam where
        model introspection could enter the system, closed by there being no
        path (CLAUDE.md constraint 5, ADR-0003).
        """
        content = (choice.get("message") or {}).get("content") or ""
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as error:
            raise ServeError(
                "the model returned content that is not JSON despite constrained "
                f"decoding: {error}"
            ) from error
        if not isinstance(payload, dict):
            raise ServeError(
                f"the model returned a JSON {type(payload).__name__} where the answer "
                "object requires an object"
            )
        return payload


def connect(url: str | None = None, model: str | None = None) -> OllamaGenerator:
    """The Ollama generator, from the environment."""
    base = url or os.environ.get(URL_ENV)
    if not base:
        raise ServeError(
            f"{URL_ENV} is unset. Generation runs against the Ollama the compose "
            "stack provides — run the service through `make dev`."
        )
    return OllamaGenerator(base, model or default_model())
