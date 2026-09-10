"""The generation client: an OpenAI-compatible POST, and what it refuses to read.

No network here. The transport is injected, so these assert the *request* this
service makes and the handling of each response shape — which is the part that
has to be right before anything is pointed at a real model.
"""

from __future__ import annotations

import json
import pathlib
import unittest

from catena.serve import ServeError
from catena.serve import generate as generate_module

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

SCHEMA = {"type": "object", "properties": {"position": {"type": "string"}},
          "required": [], "additionalProperties": False}
MESSAGES = [{"role": "system", "content": "rules"}, {"role": "user", "content": "q"}]


class FakeTransport:
    """Records the request and returns a canned response body."""

    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.url: str | None = None
        self.body: dict | None = None

    def __call__(self, url: str, body: bytes, timeout: float) -> bytes:
        self.url = url
        self.body = json.loads(body)
        if self.error is not None:
            raise self.error
        return json.dumps(self.response).encode()


def completion(content: str, *, finish: str = "stop", reasoning: str = "") -> dict:
    message = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning"] = reasoning
    return {"model": "qwen3:8b-q4_K_M",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}}


def generator(transport: FakeTransport) -> generate_module.OllamaGenerator:
    return generate_module.OllamaGenerator(
        "http://ollama:11434", generate_module.DEFAULT_MODEL, transport=transport)


class TheRequestItMakes(unittest.TestCase):
    def test_posts_to_the_openai_compatible_path(self) -> None:
        """The wire format is the interface, so vLLM or a hosted API is a URL change."""
        transport = FakeTransport(completion('{"position": "p"}'))
        generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(transport.url, "http://ollama:11434/v1/chat/completions")

    def test_disables_model_thinking(self) -> None:
        """Qwen3 thinks by default, and its thinking is unconstrained.

        Two reasons this is not a tuning knob. The thinking is the model's
        narrative about its own reasoning, which CLAUDE.md constraint 5 forbids
        shipping; and a probe with a schema attached spent its entire token
        budget in `reasoning` and returned `content: ""` with
        `finish_reason: "length"` — so leaving it on does not degrade the
        answer, it prevents there being one.
        """
        transport = FakeTransport(completion('{"position": "p"}'))
        generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(transport.body["reasoning_effort"], "none")

    def test_constrains_decoding_to_the_schema(self) -> None:
        """ADR-0018: a decoding constraint, never a request the prompt makes politely."""
        transport = FakeTransport(completion('{"position": "p"}'))
        generator(transport).generate(MESSAGES, SCHEMA)
        response_format = transport.body["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertEqual(response_format["json_schema"]["schema"], SCHEMA)

    def test_sends_the_pinned_tag(self) -> None:
        transport = FakeTransport(completion('{"position": "p"}'))
        generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(transport.body["model"], "qwen3:8b-q4_K_M")


class WhatItRefusesToRead(unittest.TestCase):
    def test_reasoning_never_reaches_the_caller(self) -> None:
        """Constraint 5, at the one seam where introspection could enter.

        The field is discarded unread. It is not stored, not traced, and not
        returned — there is nowhere for it to go, which is the point.
        """
        transport = FakeTransport(
            completion('{"position": "p"}', reasoning="First I considered..."))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.payload, {"position": "p"})
        self.assertNotIn("reasoning", json.dumps(result.__dict__))


class WhatItRefusesToAccept(unittest.TestCase):
    def test_a_truncated_generation_is_an_error(self) -> None:
        """`finish_reason: length` means the object is incomplete.

        Not passed upstream as an empty answer: an all-slots-empty answer with
        no reason is the honest-silence shape, and a truncation must never be
        able to wear it (ADR-0020).
        """
        transport = FakeTransport(completion('{"position": "p"}', finish="length"))
        with self.assertRaises(ServeError) as caught:
            generator(transport).generate(MESSAGES, SCHEMA)
        self.assertIn("truncated", str(caught.exception).lower())

    def test_content_that_is_not_json_is_an_error(self) -> None:
        transport = FakeTransport(completion("I'm afraid I can't do that."))
        with self.assertRaises(ServeError):
            generator(transport).generate(MESSAGES, SCHEMA)

    def test_content_that_is_not_an_object_is_an_error(self) -> None:
        transport = FakeTransport(completion('["a list"]'))
        with self.assertRaises(ServeError):
            generator(transport).generate(MESSAGES, SCHEMA)

    def test_a_transport_failure_is_an_error_naming_the_service(self) -> None:
        transport = FakeTransport(error=OSError("connection refused"))
        with self.assertRaises(ServeError) as caught:
            generator(transport).generate(MESSAGES, SCHEMA)
        self.assertIn("ollama", str(caught.exception).lower())

    def test_a_response_with_no_choices_is_an_error(self) -> None:
        transport = FakeTransport({"model": "m", "choices": []})
        with self.assertRaises(ServeError):
            generator(transport).generate(MESSAGES, SCHEMA)


class WhatItReportsBack(unittest.TestCase):
    def test_carries_usage_and_the_model_that_answered(self) -> None:
        """The trace records the generator; Langfuse records the tokens (SHARED §6)."""
        transport = FakeTransport(completion('{"position": "p"}'))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.model, "qwen3:8b-q4_K_M")
        self.assertEqual(result.prompt_tokens, 11)
        self.assertEqual(result.completion_tokens, 22)


class ThePinMatchesProvisioning(unittest.TestCase):
    def test_default_model_is_the_tag_make_provision_pulls(self) -> None:
        """A generator nobody pinned makes the Phase 2 baseline unreproducible.

        The lockfile is the pin (ADR-0018) and it is not in the image — the
        build context denies it, because nothing at run time should be reading
        provisioning state. So the constant is the runtime copy and this is what
        stops the two drifting: bumping one without the other fails here rather
        than at the first answer that silently used a different model.
        """
        import re

        text = (REPO_ROOT / "tools" / "provision" / "models.lock.yaml").read_text()
        section = text[text.index("generation:"):text.index("embedding:")]
        pinned = re.search(r"^\s+reference:\s*(\S+)", section, re.M).group(1)
        self.assertEqual(generate_module.DEFAULT_MODEL, pinned)


if __name__ == "__main__":
    unittest.main()
