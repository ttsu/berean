"""The Anthropic Messages adapter: what it sends, and what it refuses to read.

No network here. The SDK client is injected, so these assert the *request* this
adapter makes and the handling of each response shape.

Three of these assertions are load-bearing rather than thorough.

`thinking` is asserted **positively** as `{"type": "adaptive"}`. A negative
assertion -- that the parameter is absent -- passes against the broken case,
which is how PR #23 carried an omitted `thinking` all the way to its final
review. On this model family, omitting it is not the same as leaving thinking
enabled, and thinking-off can push reasoning into the visible text, which is the
one thing CLAUDE.md constraint 5 forbids.

No sampling parameter is sent. At least one current model family rejects
`temperature` outright, and a 400 on every request is not a failure this
project's channels can report usefully.

`stop_details.explanation` has no path into `detail`. The category is a fact
about the request; the explanation is the provider's account of a judgement, and
that is exactly the class of text constraint 5 keeps out of a persisted field.
"""

from __future__ import annotations

import json
import unittest

from catena.serve import ServeError
from catena.serve import generate as generate_module
from catena.serve.generate import messages as messages_module

SCHEMA = {"type": "object", "properties": {"position": {"type": "string"}},
          "required": [], "additionalProperties": False}
PROMPT = [{"role": "system", "content": "rules"}, {"role": "user", "content": "q"}]


class Block:
    def __init__(self, kind: str, text: str) -> None:
        self.type = kind
        self.text = text


class Usage:
    def __init__(self, input_tokens: int = 11, output_tokens: int = 22) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class StopDetails:
    def __init__(self, category: str, explanation: str) -> None:
        self.type = "refusal"
        self.category = category
        self.explanation = explanation


class Reply:
    def __init__(self, blocks, *, stop_reason="end_turn", stop_details=None,
                 model="claude-sonnet-5-5") -> None:
        self.content = list(blocks)
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        self.model = model
        self.usage = Usage()


class FakeClient:
    """Records the request and returns a canned reply, in the SDK's own shape."""

    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self._reply = reply
        self._error = error
        self.request: dict | None = None
        self.messages = self

    def create(self, **request):
        self.request = request
        if self._error is not None:
            raise self._error
        return self._reply


def text_reply(content: str, **kwargs) -> Reply:
    return Reply([Block("text", content)], **kwargs)


def generator(client: FakeClient) -> messages_module.MessagesGenerator:
    entry = generate_module.PROVIDERS["anthropic"]
    return messages_module.MessagesGenerator(
        entry, entry.default_model, "sk-ant-invented", client=client)


class TheRequestItMakes(unittest.TestCase):
    def test_sends_thinking_as_adaptive(self) -> None:
        """Positively asserted: a `assertNotIn` here passes against the bug."""
        client = FakeClient(text_reply('{"position": "p"}'))
        generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(client.request["thinking"], {"type": "adaptive"})

    def test_downgrades_effort_to_medium(self) -> None:
        """ADR-0018 found reasoning ability close to irrelevant here.

        The task is routing claims into slots and copying text verbatim, and the
        trust boundary catches the model when it does not. Recorded as a choice
        so it is not silently inherited on the next model.
        """
        client = FakeClient(text_reply('{"position": "p"}'))
        generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(client.request["output_config"]["effort"], "medium")

    def test_delivers_the_derived_schema_verbatim(self) -> None:
        """ADR-0023's derivation is not negotiated with a provider."""
        client = FakeClient(text_reply('{"position": "p"}'))
        generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(
            client.request["output_config"]["format"],
            {"type": "json_schema", "schema": SCHEMA},
        )

    def test_the_system_message_becomes_the_system_parameter(self) -> None:
        """The translation this whole design exists to show.

        A system *message* on the OpenAI wire is a top-level `system` parameter
        here, and `prompt.py` knows about neither.
        """
        client = FakeClient(text_reply('{"position": "p"}'))
        generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(client.request["system"], "rules")
        self.assertEqual(client.request["messages"], [{"role": "user", "content": "q"}])

    def test_sends_no_sampling_parameters(self) -> None:
        """`temperature` is rejected outright by this model family."""
        client = FakeClient(text_reply('{"position": "p"}'))
        generator(client).generate(PROMPT, SCHEMA)
        for name in ("temperature", "top_p", "top_k"):
            self.assertNotIn(name, client.request)

    def test_sends_the_pinned_default_model(self) -> None:
        client = FakeClient(text_reply('{"position": "p"}'))
        generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(client.request["model"], "claude-sonnet-5-5")

    def test_does_not_stream(self) -> None:
        """CLAUDE.md constraint 4: answers cannot stream before verification."""
        client = FakeClient(text_reply('{"position": "p"}'))
        generator(client).generate(PROMPT, SCHEMA)
        self.assertNotIn("stream", client.request)


class WhatItRefusesToRead(unittest.TestCase):
    def test_a_thinking_block_never_reaches_the_caller(self) -> None:
        client = FakeClient(Reply([
            Block("thinking", "INVENTED-NARRATIVE-ABOUT-ITS-OWN-REASONING"),
            Block("text", '{"position": "p"}'),
        ]))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(result.payload, {"position": "p"})
        self.assertNotIn("INVENTED-NARRATIVE", json.dumps(result.payload))

    def test_a_refusal_records_the_category_and_never_the_explanation(self) -> None:
        """The one seam through which model introspection could enter, closed.

        `category` is a fact about the request. `explanation` is the provider's
        account of a judgement, and `detail` is persisted -- so there must be no
        path, not a policy about one (constraint 5, ADR-0025).
        """
        client = FakeClient(Reply(
            [],
            stop_reason="refusal",
            stop_details=StopDetails("invented_category", "INVENTED-EXPLANATION-TEXT"),
        ))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertIsInstance(result, generate_module.GenerationFailed)
        self.assertEqual(result.code, "provider_refused")
        self.assertIn("invented_category", result.detail)
        self.assertNotIn("INVENTED-EXPLANATION-TEXT", result.detail)

    def test_a_refusal_with_no_category_still_records_one_fact(self) -> None:
        client = FakeClient(Reply([], stop_reason="refusal", stop_details=None))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(result.code, "provider_refused")
        self.assertTrue(result.detail.strip())


class WhatItReportsRatherThanRaising(unittest.TestCase):
    def test_a_truncated_generation_is_reported(self) -> None:
        client = FakeClient(text_reply('{"position": ', stop_reason="max_tokens"))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(result.code, "truncated")

    def test_a_reply_with_no_text_block_is_reported(self) -> None:
        client = FakeClient(Reply([Block("thinking", "")]))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(result.code, "empty")

    def test_text_that_is_not_json_is_reported(self) -> None:
        client = FakeClient(text_reply("I am not JSON."))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(result.code, "not_json")

    def test_text_that_is_not_an_object_is_reported(self) -> None:
        client = FakeClient(text_reply('["a list"]'))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(result.code, "not_an_object")

    def test_a_failure_carries_how_far_it_got(self) -> None:
        """The trace needs the token counts of an attempt that produced nothing."""
        client = FakeClient(text_reply("truncated", stop_reason="max_tokens"))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(result.prompt_tokens, 11)
        self.assertEqual(result.completion_tokens, 22)


class WhatItRaises(unittest.TestCase):
    def test_a_transport_failure_is_an_error_naming_the_provider(self) -> None:
        """Nothing was learned about the generator, so there is no attempt to record."""
        client = FakeClient(error=RuntimeError("invented connection failure"))
        with self.assertRaises(ServeError) as caught:
            generator(client).generate(PROMPT, SCHEMA)
        self.assertIn("anthropic", str(caught.exception))


class WhatItReportsBack(unittest.TestCase):
    def test_carries_usage_and_the_model_that_answered(self) -> None:
        client = FakeClient(text_reply('{"position": "p"}'))
        result = generator(client).generate(PROMPT, SCHEMA)
        self.assertEqual(result.model, "claude-sonnet-5-5")
        self.assertEqual(result.prompt_tokens, 11)
        self.assertEqual(result.completion_tokens, 22)

    def test_names_its_provider_and_its_delivery_mode(self) -> None:
        self.assertEqual(generator(FakeClient()).provider, "anthropic")
        self.assertEqual(generator(FakeClient()).delivery, generate_module.CONSTRAINED)


class TheClientItBuilds(unittest.TestCase):
    """Constructing a client opens no socket, so this needs no network."""

    def test_the_base_url_is_pinned_against_an_ambient_variable(self) -> None:
        """The structural fix for the bug PR #23 found.

        Without a pinned value, `ANTHROPIC_BASE_URL` silently redirects every
        retrieved passage to a third party while the configuration, the trace
        and CORPUS-POLICY all still name Anthropic.
        """
        import os

        saved = os.environ.get("ANTHROPIC_BASE_URL")
        os.environ["ANTHROPIC_BASE_URL"] = "https://invented-exfiltration.example"
        try:
            client = messages_module.build_client(
                "sk-ant-invented", messages_module.BASE_URL, 900)
        finally:
            if saved is None:
                os.environ.pop("ANTHROPIC_BASE_URL", None)
            else:
                os.environ["ANTHROPIC_BASE_URL"] = saved
        self.assertIn("api.anthropic.com", str(client.base_url))
        self.assertNotIn("invented-exfiltration", str(client.base_url))

    def test_the_sdk_is_told_not_to_retry(self) -> None:
        """ADR-0010 fixes the retry at exactly one regeneration, driven by Go.

        The SDK retries twice by default, which would make "attempt" mean two
        different things and hide a failing provider behind a latency spike.
        """
        client = messages_module.build_client("sk-ant-invented", messages_module.BASE_URL, 900)
        self.assertEqual(client.max_retries, 0)


if __name__ == "__main__":
    unittest.main()
