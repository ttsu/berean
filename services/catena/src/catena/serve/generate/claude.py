"""The Claude provider: bring-your-own-key, and off unless a deployer names it.

SHARED §1 makes `docker compose up` with no external accounts the acceptance
test, and ADR-0018 rejected a hosted API as the *default* for that reason. This
is not that: it is a configuration a deployer selects and pays for, and the
default path is unchanged.

Three things about the request are load-bearing rather than tuning.

**The system message is hoisted.** `prompt.build` emits an OpenAI-shaped list
because that is what the first provider spoke. This API takes `system` as its
own parameter, and translating is this module's whole job at the seam — which
is the point the design makes about interchangeability living in the protocol
rather than in a shared JSON dialect.

**Thinking is left on, and said so explicitly.** The local provider disables
it, and doing the same here would be the setting that looks like compliance and
produces the violation: thinking-off on this model family can put reasoning and
tool calls into the *visible* text. Left on, the narrative is never returned at
all — `_content` reads `text` blocks and nothing else, so there is nowhere for
it to go (CLAUDE.md constraint 5). The parameter is sent rather than omitted,
because omitting it only means *on* for models whose default it is; the pinned
model is one, but `CATENA_GENERATION_MODEL` is a supported override, and a
safety property that depends on which model a deployer selected is not one.

**There is no `temperature`.** Sampling parameters are rejected on this model.
The local provider pins `0.0` so the Phase 2 baseline is not a distribution
nobody recorded; that guarantee is unavailable here, and its absence is one of
the reasons the baseline stays local.

Nothing here retries — the client is built with `max_retries=0`. ADR-0010 fixes
the retry at exactly one regeneration driven by Go on a *verification* failure.
"""

from __future__ import annotations

import json
import os
from typing import Any, Sequence

from catena.serve import ServeError
from catena.serve.generate import PROVIDER_ENV, Generation, model_override

API_KEY_ENV = "ANTHROPIC_API_KEY"

#: Pinned the way ADR-0018 pins the local tag, and for the same reason: the
#: trace records what answered, so a deployment is legible in the data rather
#: than only in someone's shell history. `CATENA_GENERATION_MODEL` overrides it.
DEFAULT_MODEL = "claude-opus-5"

#: Comfortably clears the SDK's non-streaming HTTP timeout, and roughly eight
#: times what the local provider can reach. Non-streaming is deliberate:
#: CLAUDE.md constraint 4 is the prohibition on streaming tokens to the client
#: before verification — SHARED §9 records only its consequence, that the SSE
#: feed exists because the answer cannot stream. Streaming an HTTP response
#: would not engage that, but not needing the distinction is better than
#: relying on it.
MAX_TOKENS = 16000

#: Both of the SDK's stop reasons that end a generation part-way: this module's
#: own ceiling, and the model's context window when prompt plus completion
#: outgrows it. ADR-0020's argument does not distinguish them — either leaves an
#: incomplete answer object — and a stop reason that fell through here would
#: reach `_content` and be reported as content that is not JSON, which is a real
#: failure given the wrong diagnosis.
TRUNCATION_STOPS = frozenset({"max_tokens", "model_context_window_exceeded"})

#: Generous for a single completion, and far below the local provider's 900 s —
#: that number is what ~3.4 tokens/second on CPU costs, and means nothing here.
TIMEOUT_SECONDS = 600

#: Sent rather than omitted. Thinking is on by default on the pinned model, so
#: omission would read the same there — but not on every model in the family,
#: and `CATENA_GENERATION_MODEL` lets a deployer name one. Stating it makes the
#: configuration ADR-0023's amended fourth rule requires independent of that.
THINKING = {"type": "adaptive"}

#: ADR-0018 found reasoning ability "close to irrelevant here": the model routes
#: claims into slots and copies text out of context, and the trust boundary
#: catches it when it does not. `medium` buys the routing judgement without
#: paying for deliberation the task does not use.
EFFORT = "medium"


def default_model() -> str:
    """The pinned model, or the deployer's override."""
    return model_override() or DEFAULT_MODEL


class ClaudeGenerator:
    """One constrained completion against the Claude API."""

    def __init__(
        self,
        client: Any,
        model: str,
        *,
        max_tokens: int = MAX_TOKENS,
        effort: str = EFFORT,
    ) -> None:
        self._client = client
        self.model = model
        self._max_tokens = max_tokens
        self._effort = effort

    def generate(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> Generation:
        system, turns = _split_system(messages)

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                system=system,
                messages=turns,
                thinking=THINKING,
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except Exception as error:  # transport, auth, rate limit, refusal of the request
            raise ServeError(
                f"the Claude API could not answer: {type(error).__name__}: {error}. "
                f"Generation is running against the hosted provider because "
                f"{PROVIDER_ENV}=anthropic — the key and the account are the deployer's."
            ) from error

        return self._parse(response)

    def _parse(self, response: Any) -> Generation:
        stop = getattr(response, "stop_reason", None)

        if stop in TRUNCATION_STOPS:
            # Never handed upstream as an empty answer. An all-slots-empty
            # answer with no reason is the honest-silence shape, and a
            # truncation must not be able to wear it (ADR-0020).
            cause = (
                f"at this provider's {self._max_tokens}-token ceiling"
                if stop == "max_tokens"
                else "by the model's context window, which the prompt and the "
                "completion together outgrew"
            )
            raise ServeError(
                f"the generation was truncated {cause}; the answer object is "
                "incomplete and must not be presented as considered silence"
            )

        if stop == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise ServeError(
                "the model refused the request "
                f"(category: {category or 'unspecified'}); a policy decline is not an "
                "answer and is not silence either"
            )

        payload = self._content(response)
        usage = getattr(response, "usage", None)
        return Generation(
            payload=payload,
            model=getattr(response, "model", None) or self.model,
            prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )

    @staticmethod
    def _content(response: Any) -> dict[str, Any]:
        """The `text` blocks, and deliberately nothing else.

        A thinking model also returns `thinking` blocks. They are not read here,
        not returned, and not stored anywhere in this package — the one seam
        where model introspection could enter the system, closed by there being
        no path (CLAUDE.md constraint 5, ADR-0003).
        """
        text = "".join(
            block.text
            for block in getattr(response, "content", None) or []
            if getattr(block, "type", None) == "text"
        )
        if not text:
            raise ServeError(
                "the model returned no text block; there is no answer object to verify"
            )

        try:
            payload = json.loads(text)
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


def _split_system(
    messages: Sequence[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    """OpenAI-shaped messages in, this API's `system` + turns out."""
    system = "\n\n".join(
        m["content"] for m in messages if m.get("role") == "system"
    )
    turns = [dict(m) for m in messages if m.get("role") != "system"]
    if not turns:
        raise ServeError("the prompt carried no user turn; there is nothing to answer")
    return system, turns


def connect(api_key: str | None = None, model: str | None = None) -> ClaudeGenerator:
    """The hosted generator, from the environment."""
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
    if not key:
        raise ServeError(
            f"{API_KEY_ENV} is unset, and {PROVIDER_ENV}=anthropic selects the hosted "
            "generator. The key is yours: this project ships none and automates nothing "
            "around anyone's terms (SHARED §2, ADR-0017)."
        )

    import anthropic

    # `max_retries=0` is ADR-0010: Go owns the one regeneration, and a retry
    # hidden here would make "attempt" mean two different things.
    client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=TIMEOUT_SECONDS)
    return ClaudeGenerator(client, model or default_model())
