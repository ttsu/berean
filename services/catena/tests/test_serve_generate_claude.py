"""The Claude provider: what it sends, what it refuses to read, what it refuses to accept.

No network here. The client is injected, so these assert the *request* this
provider makes and the handling of each response shape.

The fakes below are hand-rolled rather than SDK objects on purpose: the SDK's
response types are its own to change, and a test that constructs them asserts
the SDK's shape rather than this adapter's handling of it.
"""

from __future__ import annotations

import json
import os
import unittest

from catena.serve import ServeError
from catena.serve import generate as generate_module
from catena.serve.generate import claude as claude_module
from catena.serve.generate import ollama as ollama_module

SCHEMA = {"type": "object", "properties": {"position": {"type": "string"}},
          "required": [], "additionalProperties": False}
MESSAGES = [{"role": "system", "content": "rules"}, {"role": "user", "content": "q"}]


class Block:
    def __init__(self, type_: str, text: str = "") -> None:
        self.type = type_
        self.text = text


class Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class Details:
    def __init__(self, category: str) -> None:
        self.category = category


class Response:
    def __init__(self, blocks, *, stop_reason="end_turn", model="claude-opus-5",
                 stop_details=None) -> None:
        self.content = blocks
        self.stop_reason = stop_reason
        self.model = model
        self.stop_details = stop_details
        self.usage = Usage(11, 22)


class FakeClient:
    """Records the request and returns a canned response."""

    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.kwargs: dict | None = None
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._response


def answered(content: str = '{"position": "p"}', **kwargs) -> Response:
    return Response([Block("text", content)], **kwargs)


def generator(client: FakeClient) -> claude_module.ClaudeGenerator:
    return claude_module.ClaudeGenerator(client, claude_module.DEFAULT_MODEL)


class TheRequestItMakes(unittest.TestCase):
    def test_constrains_decoding_to_the_schema_it_was_given(self) -> None:
        """ADR-0018: a decoding constraint, never a request the prompt makes politely.

        And the schema is the one derived from the proto descriptor, passed
        through — a provider-specific copy would be a second place the contract
        lives (ADR-0023).
        """
        client = FakeClient(answered())
        generator(client).generate(MESSAGES, SCHEMA)
        fmt = client.kwargs["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertIs(fmt["schema"], SCHEMA)

    def test_hoists_the_system_message_out_of_the_turns(self) -> None:
        """`prompt.build` emits an OpenAI-shaped list; this API takes `system` separately.

        The translation is the adapter's whole job at this seam. A system
        message left in `messages` is rejected by the API, and one dropped
        silently would send the rules nowhere.
        """
        client = FakeClient(answered())
        generator(client).generate(MESSAGES, SCHEMA)
        self.assertEqual(client.kwargs["system"], "rules")
        self.assertEqual(client.kwargs["messages"], [{"role": "user", "content": "q"}])

    def test_sends_no_sampling_parameters(self) -> None:
        """They are rejected on this model, and their absence is a recorded consequence.

        The local provider pins `temperature: 0.0` so the Phase 2 baseline is
        not a distribution nobody recorded. That guarantee cannot be had here,
        which is one of the reasons the baseline stays local.
        """
        client = FakeClient(answered())
        generator(client).generate(MESSAGES, SCHEMA)
        for rejected in ("temperature", "top_p", "top_k"):
            self.assertNotIn(rejected, client.kwargs)

    def test_sends_the_pinned_model(self) -> None:
        client = FakeClient(answered())
        generator(client).generate(MESSAGES, SCHEMA)
        self.assertEqual(client.kwargs["model"], "claude-opus-5")

    def test_sends_the_configured_effort(self) -> None:
        """ADR-0018 found reasoning ability "close to irrelevant here".

        The model routes claims into slots and copies text out of context, and
        the trust boundary catches it when it does not. `medium` buys the
        routing judgement without paying for deliberation the task does not use.
        """
        client = FakeClient(answered())
        generator(client).generate(MESSAGES, SCHEMA)
        self.assertEqual(client.kwargs["output_config"]["effort"], "medium")

    def test_does_not_disable_thinking(self) -> None:
        """Disabling it is the setting that looks like compliance and produces the violation.

        On this model family, thinking-off can put tool calls and `<thinking>`
        tags into the *visible* text — reasoning leaking into the answer, which
        is exactly what CLAUDE.md constraint 5 exists to prevent. Left on, the
        narrative is never returned and `_content` has nowhere to put it.
        """
        client = FakeClient(answered())
        generator(client).generate(MESSAGES, SCHEMA)
        self.assertNotIn("thinking", client.kwargs)


class WhatItRefusesToRead(unittest.TestCase):
    def test_thinking_blocks_never_reach_the_caller(self) -> None:
        """Constraint 5, at the one seam where introspection could enter.

        Thinking arrives as its own block type. It is not read, not returned,
        and not stored — there is nowhere for it to go, which is the point.
        """
        client = FakeClient(Response([
            Block("thinking", "First I considered..."),
            Block("text", '{"position": "p"}'),
        ]))
        result = generator(client).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.payload, {"position": "p"})
        self.assertNotIn("considered", json.dumps(result.__dict__))


class WhatItRefusesToAccept(unittest.TestCase):
    def test_a_truncated_generation_is_an_error(self) -> None:
        """The object is incomplete, and must not be presented as considered silence.

        An all-slots-empty answer with no reason is the honest-silence shape,
        and a truncation must never be able to wear it (ADR-0020).
        """
        client = FakeClient(answered(stop_reason="max_tokens"))
        with self.assertRaises(ServeError) as caught:
            generator(client).generate(MESSAGES, SCHEMA)
        self.assertIn("truncated", str(caught.exception).lower())

    def test_a_refusal_is_an_error_naming_the_category(self) -> None:
        """New here, with no local analogue, and not silence either.

        A policy decline that reached Go as an empty answer would be recorded
        as the corpus having nothing to say. Naming the category is what keeps
        it from being diagnosed as a retrieval failure.
        """
        client = FakeClient(Response([], stop_reason="refusal",
                                     stop_details=Details("cyber")))
        with self.assertRaises(ServeError) as caught:
            generator(client).generate(MESSAGES, SCHEMA)
        self.assertIn("refus", str(caught.exception).lower())
        self.assertIn("cyber", str(caught.exception))

    def test_content_that_is_not_json_is_an_error(self) -> None:
        client = FakeClient(answered("I'm afraid I can't do that."))
        with self.assertRaises(ServeError):
            generator(client).generate(MESSAGES, SCHEMA)

    def test_content_that_is_not_an_object_is_an_error(self) -> None:
        client = FakeClient(answered('["a list"]'))
        with self.assertRaises(ServeError):
            generator(client).generate(MESSAGES, SCHEMA)

    def test_a_response_with_no_text_block_is_an_error(self) -> None:
        client = FakeClient(Response([Block("thinking", "...")]))
        with self.assertRaises(ServeError):
            generator(client).generate(MESSAGES, SCHEMA)

    def test_an_api_failure_is_an_error_naming_the_service(self) -> None:
        client = FakeClient(error=OSError("connection reset"))
        with self.assertRaises(ServeError) as caught:
            generator(client).generate(MESSAGES, SCHEMA)
        self.assertIn("claude", str(caught.exception).lower())

    def test_a_prompt_with_no_user_turn_is_an_error(self) -> None:
        """A system message alone is not a question.

        `prompt.build` always emits a user turn, so this is a guard against a
        future caller rather than a live failure — but it raises rather than
        sending a turnless request the API would reject less legibly.
        """
        client = FakeClient(answered())
        with self.assertRaises(ServeError):
            generator(client).generate([{"role": "system", "content": "rules"}], SCHEMA)


class WhatItReportsBack(unittest.TestCase):
    def test_carries_usage_and_the_model_that_answered(self) -> None:
        """The trace records the generator; Langfuse records the tokens (SHARED §6)."""
        client = FakeClient(answered(model="claude-opus-5-something-else"))
        result = generator(client).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.model, "claude-opus-5-something-else")
        self.assertEqual(result.prompt_tokens, 11)
        self.assertEqual(result.completion_tokens, 22)


class HowItConnects(unittest.TestCase):
    def test_a_missing_key_is_an_error_that_says_whose_key_it_is(self) -> None:
        """SHARED §2: the key is deployer-supplied and this project ships none."""
        with self.assertRaises(ServeError) as caught:
            claude_module.connect(api_key="")
        self.assertIn("ANTHROPIC_API_KEY", str(caught.exception))


class HowTheProviderIsSelected(unittest.TestCase):
    """Explicit, and never inferred from the environment containing a key."""

    def setUp(self) -> None:
        self._saved = {k: os.environ.get(k) for k in
                       (generate_module.PROVIDER_ENV, claude_module.API_KEY_ENV,
                        "CATENA_OLLAMA_URL")}
        for key in self._saved:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_the_default_is_local(self) -> None:
        """SHARED §1: `docker compose up` must work with no external accounts."""
        os.environ["CATENA_OLLAMA_URL"] = "http://ollama:11434"
        self.assertIsInstance(generate_module.connect(), ollama_module.OllamaGenerator)

    def test_a_key_in_the_environment_does_not_select_the_hosted_provider(self) -> None:
        """The opt-in is a recorded act, as `BEREAN_SERVE_LOCAL_ONLY` is.

        A developer with a key exported in their shell must not start sending
        corpus text to a third party because of it.
        """
        os.environ[claude_module.API_KEY_ENV] = "sk-ant-not-a-real-key"
        os.environ["CATENA_OLLAMA_URL"] = "http://ollama:11434"
        self.assertIsInstance(generate_module.connect(), ollama_module.OllamaGenerator)

    def test_naming_the_provider_selects_it(self) -> None:
        os.environ[generate_module.PROVIDER_ENV] = "anthropic"
        os.environ[claude_module.API_KEY_ENV] = "sk-ant-not-a-real-key"
        self.assertIsInstance(generate_module.connect(), claude_module.ClaudeGenerator)

    def test_an_unknown_provider_is_an_error_naming_the_valid_ones(self) -> None:
        os.environ[generate_module.PROVIDER_ENV] = "openai"
        with self.assertRaises(ServeError) as caught:
            generate_module.connect()
        self.assertIn("ollama", str(caught.exception))
        self.assertIn("anthropic", str(caught.exception))

    def test_the_hosted_provider_without_a_key_fails_at_connect(self) -> None:
        """At startup, where the unset-CATENA_OLLAMA_URL failure already lives.

        Not at the first question a user asks.
        """
        os.environ[generate_module.PROVIDER_ENV] = "anthropic"
        with self.assertRaises(ServeError) as caught:
            generate_module.connect()
        self.assertIn(claude_module.API_KEY_ENV, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
