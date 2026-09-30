"""The OpenAI chat-completions wire format, over stdlib `urllib`.

Three of the four providers speak this, so there is one adapter rather than
three near-identical POSTs -- a bug fixed in one would not have reached the
others. stdlib rather than a client library for the reason that keeps
`acquire.fetch` on stdlib, and it costs the one image that has to fit alongside
2.3 GB of BGE-M3 nothing at all.

**`reasoning_effort: "none"` is Qwen3's, not a blanket rule.** Qwen3 is a
thinking model and its thinking is not covered by the decoding constraint. A
probe against the pinned tag with a schema attached spent all 200 tokens of its
budget inside `reasoning` and returned `content: ""` with
`finish_reason: "length"` -- so leaving thinking on does not merely slow the
answer down, it prevents there being one. And the field is the model's narrative
about its own reasoning, which CLAUDE.md constraint 5 forbids shipping. Hence
`_content`, which reads `content` and nothing else: the thinking is discarded
unread, and there is nowhere in this package for it to go.

**`response_format`.** ADR-0018 requires `AnswerObject` validity to be a
decoding constraint rather than a request the prompt makes politely. Ollama's
OpenAI-compatible endpoint honours a full JSON Schema here, `$defs` and `$ref`
and enums included -- verified against the pinned tag before this was written.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Sequence

from catena.serve import ServeError
from catena.serve.generate import (
    MAX_TOKENS,
    TIMEOUT_SECONDS,
    Generation,
    GenerationFailed,
    Transport,
)


def _urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
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
    ) -> Generation | GenerationFailed:
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
            raw = self._transport(
                self._url, body, {"Content-Type": "application/json"}, self._timeout
            )
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

    def _parse(self, raw: bytes) -> Generation | GenerationFailed:
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ServeError(f"ollama returned a body that is not JSON: {error}") from error

        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        choices = response.get("choices") or []
        if not choices:
            return GenerationFailed(
                code="empty", detail="ollama returned no choices", prompt_tokens=prompt_tokens
            )
        choice = choices[0]

        if choice.get("finish_reason") == "length":
            return GenerationFailed(
                code="truncated",
                detail=f"finish_reason=length at max_tokens={self._max_tokens}",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        result = self._content(choice)
        if isinstance(result, GenerationFailed):
            return GenerationFailed(
                code=result.code, detail=result.detail,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            )
        return Generation(
            payload=result,
            model=response.get("model") or self.model,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=completion_tokens,
        )

    @staticmethod
    def _content(choice: dict[str, Any]) -> dict[str, Any] | GenerationFailed:
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
            return GenerationFailed(
                code="not_json",
                detail=f"the model returned content that is not JSON: {error}",
            )
        if not isinstance(payload, dict):
            return GenerationFailed(
                code="not_an_object",
                detail=f"the model returned a JSON {type(payload).__name__}, not an object",
            )
        return payload
