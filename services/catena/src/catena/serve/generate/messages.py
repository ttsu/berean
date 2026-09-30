"""The Anthropic Messages wire format, through the vendor SDK.

This module is the design's argument in code. `services/catena/AGENTS.md` and
SHARED §1 both used to say the OpenAI-compatible *wire format* was what made
providers interchangeable. It is not -- the typed `Generator` protocol is, and
this is the case that separates the two claims: a different request shape, a
system prompt that is a parameter rather than a message, and a vendor SDK, all
behind the protocol `service.py` already depended on.

Four things about the request are decisions rather than tuning.

**`thinking` is sent explicitly as `{"type": "adaptive"}`.** This model family's
thinking is adaptive-capable but not always-on, so *omitting* the parameter is
not the same as leaving thinking enabled -- and thinking-off on this family can
push reasoning into the visible text, which is the one thing CLAUDE.md
constraint 5 forbids. Omission was the bug PR #23's final review caught; on that
branch's default it was latent, and on this default it would be live. The test
asserts the value positively, because a negative assertion passes against the
broken case.

**`effort` is `medium`, a deliberate downgrade** from this model's default of
`high`. ADR-0018 found reasoning ability "close to irrelevant here": the task is
routing claims into slots and copying text verbatim, and the trust boundary
catches the model when it does not. Recorded as a choice so it is not silently
inherited on the next model.

**No sampling parameter is sent.** `temperature`, `top_p` and `top_k` are
rejected by this model family, and a 400 on every request is not a failure this
project's channels can report usefully. The local default pins `temperature` to
0.0 because the Phase 2 baseline is a measurement; a hosted run is not quotable
as that baseline (ADR-0026), so the asymmetry costs nothing it was buying.

**`base_url` is passed explicitly and `max_retries` is zero.** The SDK reads
`ANTHROPIC_BASE_URL` from the environment when the argument is omitted, and
retries twice by default. The first would silently redirect retrieved corpus
text to a third party; the second would make "attempt" mean two different things
and hide a failing provider behind a latency spike (ADR-0010).

Nothing here reads a `thinking` block, and nothing reads a refusal's
`explanation`. `_text` takes the text blocks and nothing else, and a refusal
records the provider's *category* -- the same closure `openai_chat._content`
makes for `reasoning` (constraint 5, ADR-0003).
"""

from __future__ import annotations

import json
from typing import Any, Sequence

from catena.serve import ServeError
from catena.serve.generate import (
    MAX_TOKENS,
    TIMEOUT_SECONDS,
    Generation,
    GenerationFailed,
    Provider,
)

#: Pinned, and never read from the environment. See the module docstring.
BASE_URL = "https://api.anthropic.com"

#: Explicit rather than omitted. See the module docstring.
THINKING = {"type": "adaptive"}

#: A downgrade from this model's default of `high`, recorded as a choice.
EFFORT = "medium"


def build_client(api_key: str, base_url: str, timeout: float):
    """The SDK client, with the two defaults this project cannot accept.

    Imported here rather than at module scope so a deployment that never selects
    this provider does not load the SDK, and `docker compose up` on the local
    default is unaffected.
    """
    import anthropic

    return anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url,
        max_retries=0,
        timeout=timeout,
    )


def _split(messages: Sequence[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    """The OpenAI-shaped prompt as the Messages API takes it.

    The system message becomes the top-level `system` parameter; the rest stay
    messages. `prompt.py` produces one shape and knows about neither wire.
    """
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("role") != "system"
    ]
    if not turns:
        raise ServeError(
            "the Messages API needs at least one non-system message, and prompt.build sent none"
        )
    return system, turns


def _text(reply: Any) -> str:
    """The text blocks, and deliberately nothing else.

    A `thinking` block is the model's narrative about its own reasoning. It is
    not read here, not returned, and has nowhere in this package to go
    (constraint 5, ADR-0003). `thinking.display` is left at its default; the
    closure does not depend on what that default is.
    """
    return "".join(
        block.text for block in (getattr(reply, "content", None) or [])
        if getattr(block, "type", "") == "text"
    )


class MessagesGenerator:
    """The `anthropic` provider. One non-streaming, constrained completion."""

    def __init__(
        self,
        entry: Provider,
        model: str,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        max_tokens: int = MAX_TOKENS,
        timeout: float = TIMEOUT_SECONDS,
        client: Any | None = None,
    ) -> None:
        self.provider = entry.name
        self.delivery = entry.delivery
        self.model = model
        self._max_tokens = max_tokens
        self._client = client if client is not None else build_client(api_key, base_url, timeout)

    def generate(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> Generation | GenerationFailed:
        system, turns = _split(messages)

        try:
            reply = self._client.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                system=system,
                messages=turns,
                thinking=dict(THINKING),
                output_config={
                    "effort": EFFORT,
                    # The derived schema, verbatim. `$defs`, `$ref`, string
                    # enums and `additionalProperties: false` are all accepted;
                    # ADR-0023's derivation is not negotiated with a provider.
                    "format": {"type": "json_schema", "schema": schema},
                },
            )
        except Exception as error:
            # A transport or API failure teaches nothing about the generator,
            # so there is no attempt worth recording -- the same line
            # `openai_chat` draws.
            raise ServeError(
                f"the {self.provider} provider could not be reached or refused the request: "
                f"{error}. `make dev-offline` blocks egress by design (SHARED §1), and a "
                "hosted provider cannot answer there."
            ) from error

        return self._parse(reply)

    def _parse(self, reply: Any) -> Generation | GenerationFailed:
        usage = getattr(reply, "usage", None)
        prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        stop_reason = getattr(reply, "stop_reason", "")

        if stop_reason == "refusal":
            # The category, and there is no path from the explanation into this
            # string. `detail` is persisted in `trace.generation_failures`.
            details = getattr(reply, "stop_details", None)
            category = getattr(details, "category", "") or "unspecified"
            return GenerationFailed(
                code="provider_refused",
                detail=f"the provider declined the request; category={category}",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        if stop_reason == "max_tokens":
            return GenerationFailed(
                code="truncated",
                detail=f"stop_reason=max_tokens at max_tokens={self._max_tokens}",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        text = _text(reply)
        if not text:
            return GenerationFailed(
                code="empty",
                detail=f"{self.provider} returned no text content",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            return GenerationFailed(
                code="not_json",
                detail=f"the model returned content that is not JSON: {error}",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        if not isinstance(payload, dict):
            return GenerationFailed(
                code="not_an_object",
                detail=f"the model returned a JSON {type(payload).__name__}, not an object",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        return Generation(
            payload=payload,
            model=getattr(reply, "model", "") or self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
