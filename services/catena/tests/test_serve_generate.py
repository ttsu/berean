"""The generation client: an OpenAI-compatible POST, and what it refuses to read.

No network here. The transport is injected, so these assert the *request* this
service makes and the handling of each response shape — which is the part that
has to be right before anything is pointed at a real model.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import unittest

from catena.serve import ServeError
from catena.serve import generate as generate_module
from catena.serve.generate import openai_chat

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
        self.headers: dict[str, str] = {}

    def __call__(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
        self.url = url
        self.body = json.loads(body)
        self.headers = dict(headers)
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


def generator(transport: FakeTransport) -> openai_chat.OpenAIChatGenerator:
    entry = generate_module.PROVIDERS[generate_module.DEFAULT_PROVIDER]
    return openai_chat.OpenAIChatGenerator(
        entry, generate_module.DEFAULT_MODEL, "http://ollama:11434", transport=transport)


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
    def test_a_transport_failure_is_an_error_naming_the_service(self) -> None:
        transport = FakeTransport(error=OSError("connection refused"))
        with self.assertRaises(ServeError) as caught:
            generator(transport).generate(MESSAGES, SCHEMA)
        self.assertIn("ollama", str(caught.exception).lower())


class WhatItReportsRatherThanRaising(unittest.TestCase):
    """The six failures that are the model's, not the transport's.

    Each one used to raise, which killed the turn inside Catena and discarded
    the RetrievalTrace with it — no row in `trace.responses`, and the failure
    invisible to the Phase 2 harness (ACCEPTANCE.md, Q4 and Q10).
    """

    def test_a_truncated_generation_is_reported(self) -> None:
        transport = FakeTransport(completion('{"position": "p"}', finish="length"))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertIsInstance(result, generate_module.GenerationFailed)
        self.assertEqual(result.code, "truncated")

    def test_content_that_is_not_json_is_reported(self) -> None:
        transport = FakeTransport(completion("I'm afraid I can't do that."))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.code, "not_json")

    def test_content_that_is_not_an_object_is_reported(self) -> None:
        transport = FakeTransport(completion('["a list"]'))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.code, "not_an_object")

    def test_a_response_with_no_choices_is_reported(self) -> None:
        transport = FakeTransport({"model": "m", "choices": []})
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.code, "empty")

    def test_a_failure_carries_how_far_it_got(self) -> None:
        """The trace records it, so a deterministic ceiling is visible as one."""
        transport = FakeTransport(completion('{"position": "p"}', finish="length"))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertEqual(result.completion_tokens, 22)

    def test_a_failure_detail_never_carries_the_models_reasoning(self) -> None:
        """Constraint 5, at the field most likely to leak it.

        `reasoning` is present on the response and must not reach `detail`,
        which is a factual description of what broke.
        """
        transport = FakeTransport(
            completion("not json", reasoning="First I considered the passages..."))
        result = generator(transport).generate(MESSAGES, SCHEMA)
        self.assertNotIn("considered", result.detail)


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


class TheProviderTable(unittest.TestCase):
    """Every claim in the table is a claim a test makes, not a comment."""

    def test_every_entry_is_complete(self) -> None:
        for name, entry in generate_module.PROVIDERS.items():
            with self.subTest(provider=name):
                self.assertEqual(entry.name, name)
                self.assertIn(entry.wire, (generate_module.OPENAI_CHAT, generate_module.MESSAGES))
                self.assertIn(entry.delivery, generate_module.DELIVERY_MODES)
                self.assertTrue(entry.default_model)

    def test_a_hosted_base_url_is_absolute_and_pinned(self) -> None:
        """An ambient variable must not be able to choose who receives corpus text."""
        for name, entry in generate_module.PROVIDERS.items():
            with self.subTest(provider=name):
                if entry.key_env:
                    self.assertTrue(entry.base_url.startswith("https://"))
                    self.assertEqual(entry.url_env, "")
                else:
                    self.assertEqual(entry.base_url, "")
                    self.assertTrue(entry.url_env)

    def test_key_variables_are_distinct(self) -> None:
        keys = [e.key_env for e in generate_module.PROVIDERS.values() if e.key_env]
        self.assertEqual(len(keys), len(set(keys)))

    def test_no_two_providers_share_a_default_model(self) -> None:
        """A shared default makes `generation_model` alone ambiguous in the trace."""
        models = [e.default_model for e in generate_module.PROVIDERS.values()]
        self.assertEqual(len(models), len(set(models)))

    def test_the_default_is_local_and_needs_no_account(self) -> None:
        """SHARED §1: `docker compose up` gives a working system with no external accounts."""
        entry = generate_module.PROVIDERS[generate_module.DEFAULT_PROVIDER]
        self.assertEqual(generate_module.DEFAULT_PROVIDER, "ollama")
        self.assertEqual(entry.key_env, "")
        self.assertEqual(entry.default_model, generate_module.DEFAULT_MODEL)


class TheHostedDefaultsArePinned(unittest.TestCase):
    def test_each_hosted_default_is_the_identifier_the_table_names(self) -> None:
        """Two of the three names would have been wrong if guessed.

        They were read from each provider's live documentation, so a silent edit
        has to fail here rather than at a 404 in front of a deployer.
        """
        self.assertEqual(
            {n: e.default_model for n, e in generate_module.PROVIDERS.items() if e.key_env},
            {"openai": "gpt-6-luna", "deepseek": "deepseek-flash"},
        )


class HowTheProviderIsChosen(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            name: os.environ.pop(name, None)
            for name in (
                generate_module.PROVIDER_ENV,
                generate_module.MODEL_ENV,
                generate_module.URL_ENV,
                "OPENAI_API_KEY",
                "DEEPSEEK_API_KEY",
            )
        }
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_the_default_provider_is_local(self) -> None:
        os.environ[generate_module.URL_ENV] = "http://ollama:11434"
        chosen = generate_module.connect()
        self.assertEqual(chosen.provider, "ollama")
        self.assertEqual(chosen.model, generate_module.DEFAULT_MODEL)

    def test_an_ambient_key_does_not_select_a_hosted_provider(self) -> None:
        """A key in the environment is a credential, never a configuration decision."""
        os.environ[generate_module.URL_ENV] = "http://ollama:11434"
        os.environ["OPENAI_API_KEY"] = "sk-invented-not-a-real-key"
        self.assertEqual(generate_module.connect().provider, "ollama")

    def test_an_unknown_provider_names_the_valid_ones(self) -> None:
        os.environ[generate_module.PROVIDER_ENV] = "togetherai"
        with self.assertRaises(ServeError) as caught:
            generate_module.connect()
        message = str(caught.exception)
        self.assertIn("togetherai", message)
        for name in generate_module.PROVIDERS:
            self.assertIn(name, message)

    def test_a_missing_key_fails_at_connect_not_at_the_first_question(self) -> None:
        """A stack that starts and cannot answer is a configuration error told late."""
        os.environ[generate_module.PROVIDER_ENV] = "deepseek"
        with self.assertRaises(ServeError) as caught:
            generate_module.connect()
        self.assertIn("DEEPSEEK_API_KEY", str(caught.exception))

    def test_the_model_override_applies_within_the_chosen_provider(self) -> None:
        os.environ[generate_module.PROVIDER_ENV] = "deepseek"
        os.environ["DEEPSEEK_API_KEY"] = "dk-invented-not-a-real-key"
        os.environ[generate_module.MODEL_ENV] = "deepseek-invented"
        chosen = generate_module.connect()
        self.assertEqual(chosen.provider, "deepseek")
        self.assertEqual(chosen.model, "deepseek-invented")


class HowTheSchemaIsDelivered(unittest.TestCase):
    """Each mode puts the schema where its wire format requires."""

    def _request(self, provider: str) -> dict:
        entry = generate_module.PROVIDERS[provider]
        transport = FakeTransport(completion('{"position": "p"}'))
        openai_chat.OpenAIChatGenerator(
            entry, entry.default_model, "https://invented.example",
            # A key only where the table says one is needed, so the local
            # provider is exercised as it actually runs.
            api_key="k-invented" if entry.key_env else "",
            transport=transport,
        ).generate(MESSAGES, SCHEMA)
        return transport.body

    def test_constrained_holds_the_decoder_to_the_schema(self) -> None:
        body = self._request("ollama")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(body["response_format"]["json_schema"]["schema"], SCHEMA)

    def test_constrained_leaves_the_prompt_alone(self) -> None:
        """The local default is the slowest component here; it pays no tokens for
        enforcement it already has."""
        body = self._request("ollama")
        self.assertEqual(body["messages"], list(MESSAGES))

    def test_shaped_guarantees_json_without_guaranteeing_the_schema(self) -> None:
        body = self._request("deepseek")
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_shaped_appends_the_schema_to_the_system_message(self) -> None:
        body = self._request("deepseek")
        system = body["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertIn("rules", system["content"])
        self.assertIn('"position"', system["content"])
        self.assertEqual(body["messages"][1], dict(MESSAGES[1]))

    def test_unconstrained_enforces_nothing_and_still_asks(self) -> None:
        entry = generate_module.PROVIDERS["deepseek"]
        loose = dataclasses.replace(entry, delivery=generate_module.UNCONSTRAINED)
        transport = FakeTransport(completion('{"position": "p"}'))
        openai_chat.OpenAIChatGenerator(
            loose, loose.default_model, "https://invented.example",
            api_key="k-invented", transport=transport,
        ).generate(MESSAGES, SCHEMA)
        self.assertNotIn("response_format", transport.body)
        self.assertIn('"position"', transport.body["messages"][0]["content"])

    def test_the_adapter_does_not_mutate_the_prompt_it_was_given(self) -> None:
        """`prompt.py` learns nothing about providers, and this is the provable half:
        delivery happens at the provider's own edge, on a copy."""
        messages = [dict(m) for m in MESSAGES]
        entry = generate_module.PROVIDERS["deepseek"]
        openai_chat.OpenAIChatGenerator(
            entry, entry.default_model, "https://invented.example", api_key="k-invented",
            transport=FakeTransport(completion('{"position": "p"}')),
        ).generate(messages, SCHEMA)
        self.assertEqual(messages, [dict(m) for m in MESSAGES])


class TheKeyTravelsInTheHeader(unittest.TestCase):
    def test_a_hosted_request_carries_a_bearer_token_and_the_body_does_not(self) -> None:
        entry = generate_module.PROVIDERS["deepseek"]
        transport = FakeTransport(completion('{"position": "p"}'))
        openai_chat.OpenAIChatGenerator(
            entry, entry.default_model, "https://invented.example",
            api_key="dk-invented", transport=transport,
        ).generate(MESSAGES, SCHEMA)
        self.assertEqual(transport.headers["Authorization"], "Bearer dk-invented")
        self.assertNotIn("dk-invented", json.dumps(transport.body))

    def test_the_local_provider_sends_no_authorization_header(self) -> None:
        entry = generate_module.PROVIDERS["ollama"]
        transport = FakeTransport(completion('{"position": "p"}'))
        openai_chat.OpenAIChatGenerator(
            entry, entry.default_model, "http://ollama:11434", transport=transport,
        ).generate(MESSAGES, SCHEMA)
        self.assertNotIn("Authorization", transport.headers)


if __name__ == "__main__":
    unittest.main()
