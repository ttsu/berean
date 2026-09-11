# BYOK Hosted Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deployer may select the Claude API as the generation provider with their own key, as a
documented, non-default deployment configuration.

**Architecture:** `catena/serve/generate.py` becomes a package holding one module per provider
behind the existing `Generator` protocol. `service.py` and everything above it are untouched — they
already depend on the protocol and nothing else. Selection is an explicit environment variable that
defaults to the local provider and is never inferred from the presence of a key.

**Tech Stack:** Python 3.12, `unittest` (run as scripts, not pytest), the official `anthropic` SDK,
uv for dependency management.

**Spec:** [BYOK-GENERATION-DESIGN.md](BYOK-GENERATION-DESIGN.md) — read it before Task 1. The plan
argues from it and does not repeat its reasoning.

## Global Constraints

Every task's requirements implicitly include all of these.

- **No corpus text in this repository — none, from any source, whatever its licence** (ADR-0014).
  Test fixtures use `{"position": "p"}`-style stubs, never real passages, never real answers.
- **Never ship model introspection** (CLAUDE.md constraint 5). The model's narrative about its own
  reasoning is never read, returned, traced or stored. There must be no path.
- **Nothing renders unverified** (SHARED §3). Nothing in this change touches verification, and no
  failure mode here may produce an answer object that did not come whole from the model.
- **No token streaming** (SHARED §4). Requests in this change are non-streaming.
- **`docker compose up` must give a working system with no external accounts** (SHARED §1). The
  default provider stays `ollama`; `make dev-offline` must continue to pass.
- **Nothing in Catena retries** (ADR-0010). Go owns the single regeneration. The SDK client is
  constructed with `max_retries=0`.
- **The decoding schema is derived from the proto descriptor, never hand-written** (ADR-0023). No
  task may write a second schema or relax the existing one to suit a provider.
- **Third-party API keys MUST be deployer-supplied** (SHARED §2). Ship no key. No key in
  `.env.example`, no key in a test, no key in a default.
- Python `>=3.12`. `ruff` line-length 100.
- Tests are `unittest` and run as scripts: `uv run --project services/catena python
  services/catena/tests/test_x.py -q`. The whole suite is `make test-catena`.
- Test classes are named as sentences about behaviour (`WhatItRefusesToAccept`), and a test whose
  reason is not obvious from its name carries a docstring giving the reason. Match the idiom in
  `services/catena/tests/test_serve_generate.py`.

---

### Task 0: Probe the schema, and record what it answers

The design's one open question: does `output_config.format` accept the proto-derived schema
verbatim, including `$defs`/`$ref`? Everything in Task 2 that touches the schema depends on the
answer, and guessing it would mean discovering it after the adapter exists.

**This task needs an Anthropic API key from the operator.** It is the only task that makes a
network call, and it costs roughly one cent.

**Files:**
- Modify: `specs/001-phase-1-pca-baseline/BYOK-GENERATION-DESIGN.md` (the *Open question* section)

**Interfaces:**
- Consumes: `catena.serve.schema.answer_schema()` — existing, takes no arguments, returns `dict`
- Produces: a recorded yes/no that decides whether Task 3 runs at all

- [ ] **Step 1: Confirm the key is present**

```bash
test -n "$ANTHROPIC_API_KEY" && echo "key present" || echo "ASK THE OPERATOR FOR A KEY — do not proceed"
```

- [ ] **Step 2: Install the SDK into the catena project**

```bash
cd services/catena && uv add anthropic
```

This writes `pyproject.toml` and `uv.lock`. Leave both changes in the working tree; Task 2 commits
them with the justifying comment. Do not commit here.

- [ ] **Step 3: Write the probe as a throwaway script**

Write to the scratchpad, **not** into the repository:

```python
# /tmp/probe_schema.py — throwaway, never committed
import json, os, sys
sys.path.insert(0, "services/catena/src")
sys.path.insert(0, "services/catena/gen")

import anthropic
from catena.serve import schema

s = schema.answer_schema()
print("has $defs:", "$defs" in s)
print("$ref count:", json.dumps(s).count('"$ref"'))

client = anthropic.Anthropic(max_retries=0)
try:
    response = client.messages.create(
        model="claude-opus-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": "Answer with an empty answer object."}],
        output_config={"format": {"type": "json_schema", "schema": s}},
    )
except Exception as error:
    print("REJECTED:", type(error).__name__, error)
else:
    print("ACCEPTED. stop_reason:", response.stop_reason)
    print("block types:", [b.type for b in response.content])
    text = "".join(b.text for b in response.content if b.type == "text")
    print("parses as object:", isinstance(json.loads(text), dict))
```

- [ ] **Step 4: Run it**

```bash
uv run --project services/catena python /tmp/probe_schema.py
```

Record verbatim: whether the schema was accepted, the `stop_reason`, and the block types present in
`content`. The block types matter beyond this question — they confirm whether thinking blocks are
returned alongside text, which is what Task 2's `_content` must filter.

- [ ] **Step 5: Record the answer in the design doc**

Replace the *Open question* section's closing sentence with what the probe found. If the schema was
**accepted**, write that it was, with the date, and note that Task 3 is not needed. If it was
**rejected**, quote the error verbatim and name the construct at fault.

- [ ] **Step 6: Commit the recorded answer**

```bash
rm /tmp/probe_schema.py
git add specs/001-phase-1-pca-baseline/BYOK-GENERATION-DESIGN.md
git commit -m "BYOK generation: probe the decoding schema against the Claude API"
```

---

### Task 1: Split `generate.py` into a package

A pure refactor with no behaviour change. It lands alone so that the diff introducing the second
provider contains only the second provider.

**Files:**
- Create: `services/catena/src/catena/serve/generate/__init__.py`
- Create: `services/catena/src/catena/serve/generate/ollama.py`
- Delete: `services/catena/src/catena/serve/generate.py`
- Modify: `services/catena/tests/test_serve_generate.py` (imports only)

**Interfaces:**
- Produces:
  - `catena.serve.generate.Generation` — frozen dataclass, fields `payload: dict[str, Any]`,
    `model: str`, `prompt_tokens: int`, `completion_tokens: int`
  - `catena.serve.generate.Generator` — Protocol with attribute `model: str` and method
    `generate(messages: Sequence[dict[str, str]], schema: dict[str, Any]) -> Generation`
  - `catena.serve.generate.model_override() -> str | None` — reads `CATENA_GENERATION_MODEL`
  - `catena.serve.generate.connect() -> Generator` — unchanged signature, still returns Ollama
  - `catena.serve.generate.ollama.OllamaGenerator`, `.DEFAULT_MODEL`, `.default_model()`,
    `.Transport`, `.MAX_TOKENS`, `.TIMEOUT_SECONDS`

- [ ] **Step 1: Create the package directory and move the file**

```bash
cd services/catena/src/catena/serve
mkdir generate && git mv generate.py generate/ollama.py
```

The directory and the module can coexist during the move — `generate` and `generate.py` are
different names — so this is one step, not a dance through a temporary name.

- [ ] **Step 2: Write `generate/__init__.py`**

Move `Generation`, `Generator` and `connect` out of `ollama.py` into this new file. `MODEL_ENV` is
shared and moves here; `URL_ENV`, `DEFAULT_MODEL`, `MAX_TOKENS`, `TIMEOUT_SECONDS`, `Transport`,
`_urllib_transport` and `OllamaGenerator` all stay in `ollama.py` because they are true of that
provider and of nothing else.

```python
"""Generation: the seam, and the providers behind it.

`services/catena/AGENTS.md` requires the provider be interchangeable. What
delivers that is the `Generator` protocol below — one method, a documented
return, and `service.py` depending on nothing else. A provider satisfies it
however its API is shaped.

The default is local, and selection is explicit. `docker compose up` must give
a working system with no external accounts (SHARED §1), so a hosted provider is
something a deployer turns on by name, never something the environment turns on
by containing a key.

Nothing here retries. ADR-0010 fixes the retry at exactly one regeneration
driven by Go on a *verification* failure; a transport retry hidden underneath
would make "attempt" mean two different things and hide a failing generator
behind a latency spike.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from catena.serve import ServeError

PROVIDER_ENV = "CATENA_GENERATION_PROVIDER"
MODEL_ENV = "CATENA_GENERATION_MODEL"

#: Local. The acceptance test is `docker compose up` with no accounts, and the
#: default has to be the thing that satisfies it.
DEFAULT_PROVIDER = "ollama"


def model_override() -> str | None:
    """The deployer's model override, if any.

    One variable across providers, because a deployment runs one generator. It
    must name a model the *selected* provider serves — an Ollama tag sent to the
    Claude API is a 404 whose cause is not obvious from the error.
    """
    return os.environ.get(MODEL_ENV) or None


@dataclass(frozen=True)
class Generation:
    """One completion. Carries no account of how the model produced it."""

    #: The decoded JSON object. Structurally valid by construction — the
    #: decoder was constrained to the schema — and semantically untrusted.
    payload: dict[str, Any]
    #: What actually answered, as reported by the server rather than as
    #: requested. The trace records this, so it has to be the former.
    model: str
    prompt_tokens: int
    completion_tokens: int


class Generator(Protocol):
    """What the request path needs of a model, and nothing more."""

    #: Written to `RetrievalTrace.generation_model`.
    model: str

    def generate(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> Generation:
        """One constrained completion, or `ServeError`."""
        ...


def connect(provider: str | None = None) -> Generator:
    """The generator the server runs with.

    The provider modules are imported here rather than at module scope so that
    a default deployment never imports a vendor SDK it has no use for.
    """
    name = (provider or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip().lower()

    if name == "ollama":
        from catena.serve.generate import ollama

        return ollama.connect()

    raise ServeError(
        f"{PROVIDER_ENV}={name!r} is not a generation provider. "
        f"Valid values are: 'ollama'."
    )
```

- [ ] **Step 3: Trim `ollama.py` to the provider**

Delete from `ollama.py` the `Generation` dataclass, the `Generator` protocol, the `MODEL_ENV`
constant and the `dataclasses`/`Protocol` imports — they now live in `__init__.py`. Add the import:

```python
from catena.serve.generate import Generation, model_override
```

Change `default_model` to use the shared override, keeping its docstring as it stands:

```python
def default_model() -> str:
    return model_override() or DEFAULT_MODEL
```

Rewrite the module docstring's opening line to name the provider — `"""The Ollama provider, over
its OpenAI-compatible endpoint."""` — and keep every paragraph below it. The `reasoning_effort`
probe, the `response_format` note, and the measured ceiling/timeout table are findings about
qwen3-8b and belong with it.

Keep `connect()` in `ollama.py`, renaming nothing:

```python
def connect(url: str | None = None, model: str | None = None) -> OllamaGenerator:
    """The Ollama generator, from the environment."""
    base = url or os.environ.get(URL_ENV)
    if not base:
        raise ServeError(
            f"{URL_ENV} is unset. Generation runs against the Ollama the compose "
            "stack provides — run the service through `make dev`."
        )
    return OllamaGenerator(base, model or default_model())
```

- [ ] **Step 4: Update the test imports**

In `services/catena/tests/test_serve_generate.py`, replace the import and the two references:

```python
from catena.serve.generate import ollama as ollama_module
```

Then `generate_module.OllamaGenerator` becomes `ollama_module.OllamaGenerator` and
`generate_module.DEFAULT_MODEL` becomes `ollama_module.DEFAULT_MODEL` (two sites: the `generator`
helper and `ThePinMatchesProvisioning`). Change the module docstring's first line to
`"""The Ollama generation client: an OpenAI-compatible POST, and what it refuses to read."""`.
Change nothing else — no assertion moves in this task.

- [ ] **Step 5: Run the suite and verify nothing changed**

```bash
make test-catena
```

Expected: PASS, every suite, with the same number of tests as before the split.

- [ ] **Step 6: Verify the server still wires up**

```bash
uv run --project services/catena python -c "
from catena.serve import generate
print(generate.connect.__module__, generate.Generation, generate.Generator)
"
```

Expected: prints `catena.serve.generate` and the two types. `server.py` calls `generate.connect()`
and is untouched by this task; this confirms that import path still resolves.

- [ ] **Step 7: Commit**

```bash
git add -A services/catena/src/catena/serve/generate services/catena/tests/test_serve_generate.py
git rm --cached services/catena/src/catena/serve/generate.py 2>/dev/null || true
git commit -m "Generation: split the provider out from the seam

A pure refactor ahead of a second provider. The protocol, the Generation
record and connect() are provider-independent and move to the package root;
OllamaGenerator and every measured constant stay with the provider they are
true of."
```

---

### Task 2: The Claude adapter

**Files:**
- Create: `services/catena/src/catena/serve/generate/claude.py`
- Create: `services/catena/tests/test_serve_generate_claude.py`
- Modify: `services/catena/pyproject.toml` (the `anthropic` dependency and its comment)
- Modify: `services/catena/uv.lock` (written by uv, committed)

**Interfaces:**
- Consumes: `catena.serve.generate.Generation`, `catena.serve.generate.model_override`,
  `catena.serve.ServeError`
- Produces:
  - `catena.serve.generate.claude.ClaudeGenerator(client, model, *, max_tokens=MAX_TOKENS,
    effort=EFFORT)` — satisfies the `Generator` protocol
  - `catena.serve.generate.claude.DEFAULT_MODEL` = `"claude-opus-5"`
  - `catena.serve.generate.claude.default_model() -> str`
  - `catena.serve.generate.claude.connect(api_key: str | None = None, model: str | None = None)
    -> ClaudeGenerator`
  - `catena.serve.generate.claude.API_KEY_ENV` = `"ANTHROPIC_API_KEY"`

- [ ] **Step 1: Write the failing tests**

Create `services/catena/tests/test_serve_generate_claude.py`:

```python
"""The Claude provider: what it sends, what it refuses to read, what it refuses to accept.

No network here. The client is injected, so these assert the *request* this
provider makes and the handling of each response shape.

The fakes below are hand-rolled rather than SDK objects on purpose: the SDK's
response types are its own to change, and a test that constructs them asserts
the SDK's shape rather than this adapter's handling of it.
"""

from __future__ import annotations

import json
import unittest

from catena.serve import ServeError
from catena.serve.generate import claude as claude_module

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate_claude.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'catena.serve.generate.claude'`.

- [ ] **Step 3: Write the adapter**

Create `services/catena/src/catena/serve/generate/claude.py`:

```python
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

**Thinking is left on.** The local provider disables it, and doing the same here
would be the setting that looks like compliance and produces the violation:
thinking-off on this model family can put reasoning and tool calls into the
*visible* text. Left on, the narrative is never returned at all — `_content`
reads `text` blocks and nothing else, so there is nowhere for it to go
(CLAUDE.md constraint 5).

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
#: times what the local provider can reach. Non-streaming is deliberate: SHARED
#: §4 prohibits streaming tokens to the client before verification, and while
#: streaming an HTTP response would not engage that, not needing the
#: distinction is better than relying on it.
MAX_TOKENS = 16000

#: Generous for a single completion, and far below the local provider's 900 s —
#: that number is what ~3.4 tokens/second on CPU costs, and means nothing here.
TIMEOUT_SECONDS = 600

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

        if stop == "max_tokens":
            # Never handed upstream as an empty answer. An all-slots-empty
            # answer with no reason is the honest-silence shape, and a
            # truncation must not be able to wear it (ADR-0020).
            raise ServeError(
                f"the generation was truncated at {self._max_tokens} tokens; the answer "
                "object is incomplete and must not be presented as considered silence"
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate_claude.py -q
```

Expected: PASS, 15 tests.

- [ ] **Step 5: Document the dependency in `pyproject.toml`**

`uv add anthropic` in Task 0 appended a bare entry. Replace it with a justified one, in the comment
idiom every other dependency in this file uses, placed last in the list:

```toml
    # The hosted generation provider (BYOK-GENERATION-DESIGN.md). MIT.
    #
    # This is the first vendor SDK in the request path, and it is a considered
    # reversal: the comment on langfuse above says the OpenAI-compatible *wire
    # format* is what makes providers interchangeable, "not a vendor SDK". That
    # was written when there was one provider and so had no way to be tested.
    # What actually delivers interchangeability is the `Generator` protocol --
    # `service.py` depends on that and on nothing else -- and the Claude API is
    # not OpenAI-shaped, so a second provider is exactly the case that
    # distinguishes the two claims.
    #
    # It is not in the default path: `CATENA_GENERATION_PROVIDER` defaults to
    # `ollama`, the module is imported only when a deployer selects it, and
    # `make dev-offline` fails loudly if it is ever reached by accident.
    "anthropic>=0.75",
```

Also amend the langfuse comment's closing paragraph, which asserts the claim this change reverses.
Replace its last sentence — "Generation itself is stdlib `urllib` ... keeps `acquire.fetch` on
stdlib." — with:

```
    # The local generator is stdlib `urllib` (see catena/serve/generate/ollama.py),
    # on the same reasoning that keeps `acquire.fetch` on stdlib. The hosted
    # provider is not; see the `anthropic` entry below for why that is a
    # reversal rather than an inconsistency.
```

- [ ] **Step 6: Verify the whole suite and the lint**

```bash
make test-catena && uv run --project services/catena ruff check services/catena/src
```

Expected: both PASS. `ruff` line-length is 100.

- [ ] **Step 7: Verify the adapter satisfies the protocol**

```bash
uv run --project services/catena python -c "
from catena.serve.generate import Generator, claude
g = claude.ClaudeGenerator(object(), 'claude-opus-5')
print('satisfies protocol:', isinstance(g, Generator) or hasattr(g, 'generate') and hasattr(g, 'model'))
print('default model:', claude.DEFAULT_MODEL)
"
```

Expected: `satisfies protocol: True` and `default model: claude-opus-5`.

- [ ] **Step 8: Commit**

```bash
git add services/catena/src/catena/serve/generate/claude.py \
        services/catena/tests/test_serve_generate_claude.py \
        services/catena/pyproject.toml services/catena/uv.lock
git commit -m "Generation: the Claude provider

Bring-your-own-key, behind the same protocol, reachable only once Task 3
wires selection. Thinking stays on and text blocks are the only thing read,
so the narrative has nowhere to go; truncation and refusal both raise rather
than reaching Go as an answer that would read as considered silence."
```

---

### Task 3: Inline the schema definitions — **only if Task 0 found `$ref` rejected**

If Task 0 recorded that the schema was accepted verbatim, **skip this task entirely** and do not
write the code below. It exists so that the rejecting branch is not improvised.

**Files:**
- Modify: `services/catena/src/catena/serve/generate/claude.py`
- Modify: `services/catena/tests/test_serve_generate_claude.py`

**Interfaces:**
- Produces: `catena.serve.generate.claude.inline_defs(schema: dict[str, Any]) -> dict[str, Any]`

- [ ] **Step 1: Write the failing test**

Append to `test_serve_generate_claude.py`:

```python
class TheSchemaItSends(unittest.TestCase):
    def test_inlines_definitions_the_api_will_not_take(self) -> None:
        """A `$ref` the provider rejects is flattened here, never in `schema.py`.

        `schema.py` derives the schema from the proto descriptor and is the one
        place the contract lives (ADR-0023). A provider that cannot read one
        construct gets it rewritten at its own edge; the contract does not bend
        to suit it, and nothing about `required` or count constraints changes.
        """
        nested = {
            "type": "object",
            "properties": {"citations": {"type": "array",
                                         "items": {"$ref": "#/$defs/Citation"}}},
            "$defs": {"Citation": {"type": "object",
                                   "properties": {"locator": {"type": "string"}},
                                   "required": ["locator"],
                                   "additionalProperties": False}},
        }
        flattened = claude_module.inline_defs(nested)
        self.assertNotIn("$defs", flattened)
        self.assertNotIn("$ref", json.dumps(flattened))
        item = flattened["properties"]["citations"]["items"]
        self.assertEqual(item["required"], ["locator"])
        self.assertIs(item["additionalProperties"], False)

    def test_sends_the_flattened_schema(self) -> None:
        client = FakeClient(answered())
        schema = {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}},
                  "$defs": {"A": {"type": "string"}}}
        generator(client).generate(MESSAGES, schema)
        sent = client.kwargs["output_config"]["format"]["schema"]
        self.assertNotIn("$ref", json.dumps(sent))
```

The earlier `test_constrains_decoding_to_the_schema_it_was_given` asserts `assertIs(fmt["schema"],
SCHEMA)`. Change that one assertion to `assertEqual`, and add a line to its docstring: "Passed
through by value — `inline_defs` rewrites constructs this provider rejects, and changes nothing
else." A schema with no `$defs` must come out equal to what went in.

- [ ] **Step 2: Run to verify it fails**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate_claude.py -q
```

Expected: FAIL with `AttributeError: module ... has no attribute 'inline_defs'`.

- [ ] **Step 3: Implement**

Add to `claude.py`, above `ClaudeGenerator`:

```python
def inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """`$defs`/`$ref` flattened, because this provider will not take them.

    The rewrite happens here rather than in `schema.py`: that module derives the
    schema from the proto descriptor and is the one place the contract lives
    (ADR-0023). A provider's limitation is the provider's edge to absorb.

    `AnswerObject` has no recursive messages — `Citation`, `Argument`,
    `Description`, `ContraryPosition` and `Contested` all bottom out in scalars —
    so a straight substitution terminates. A recursive contract would not, and a
    future one would need a depth guard here rather than a deeper walk.
    """
    defs = schema.get("$defs")
    if not defs:
        return schema

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            return resolve(defs[ref.split("/")[-1]])
        return {key: resolve(value) for key, value in node.items() if key != "$defs"}

    return resolve({key: value for key, value in schema.items() if key != "$defs"})
```

Then, in `generate`, replace the `format` line with:

```python
                    "format": {"type": "json_schema", "schema": inline_defs(schema)},
```

- [ ] **Step 4: Run to verify it passes**

```bash
make test-catena
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/catena/src/catena/serve/generate/claude.py \
        services/catena/tests/test_serve_generate_claude.py
git commit -m "Claude provider: flatten \$defs at the provider's edge

The contract does not bend to suit a provider — schema.py still derives from
the proto descriptor, and required and the absent count constraints are
unchanged. The rewrite lives where the limitation does."
```

---

### Task 4: Wire selection, and the deployer-facing configuration

**Files:**
- Modify: `services/catena/src/catena/serve/generate/__init__.py` (`connect` dispatch)
- Modify: `services/catena/tests/test_serve_generate_claude.py` (dispatch tests)
- Modify: `.env.example`
- Modify: `compose.yaml` (the `catena` service environment)

**Interfaces:**
- Consumes: `catena.serve.generate.claude.connect`
- Produces: `CATENA_GENERATION_PROVIDER` as a supported deployment variable

- [ ] **Step 1: Write the failing tests**

Append to `test_serve_generate_claude.py`:

```python
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
```

Add to that file's imports:

```python
import os

from catena.serve import generate as generate_module
from catena.serve.generate import ollama as ollama_module
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate_claude.py -q
```

Expected: FAIL — `test_naming_the_provider_selects_it` raises `ServeError` because `connect` does
not know `anthropic` yet.

- [ ] **Step 3: Add the dispatch**

In `generate/__init__.py`, replace the body of `connect` after the `ollama` branch:

```python
    if name == "anthropic":
        from catena.serve.generate import claude

        return claude.connect()

    raise ServeError(
        f"{PROVIDER_ENV}={name!r} is not a generation provider. Valid values are "
        "'ollama' (the default: local, what `docker compose up` provides) and "
        "'anthropic' (bring-your-own-key, billed to the deployer)."
    )
```

- [ ] **Step 4: Run to verify they pass**

```bash
make test-catena
```

Expected: PASS.

- [ ] **Step 5: Document it in `.env.example`**

Insert after the `BEREAN_TOP_K` block, matching the file's existing commentary style:

```bash
# ---------------------------------------------------------------------------
# Generation provider
# ---------------------------------------------------------------------------
# `ollama` (default) runs the pinned local model the compose stack provides, and
# is what `docker compose up` with no external accounts means (SHARED §1).
#
# `anthropic` sends generation to the Claude API with your own key. It is a
# supported deployment option, off by default, and selecting it is a recorded
# act — a key in the environment does not turn it on by itself.
#
# Know what it means before you set it. Retrieved corpus text is sent to
# Anthropic as part of the prompt, and that happens *before* the gateway's
# licence check (check 4) runs, because verification is downstream of
# generation. With `local-only` corpora, that decision is yours to take under
# your own account and Anthropic's terms — the same footing ADR-0017 puts
# the ESV key on: this project ships no key and automates nothing around
# anyone's terms. See docs/CORPUS-POLICY.md.
#
# Roughly $0.05-0.08 per answer at current rates.
CATENA_GENERATION_PROVIDER=ollama

# Yours. Required only when the provider above is `anthropic`. Never committed.
ANTHROPIC_API_KEY=
```

- [ ] **Step 6: Pass the variables through compose**

In `compose.yaml`, in the `catena` service's `environment:` block, after `CATENA_OLLAMA_URL`:

```yaml
      # Defaults to the local provider, so a deployer who sets neither gets the
      # stack's own Ollama and no egress (SHARED §1). `make dev-offline` marks
      # the network internal, so a hosted provider fails loudly there rather
      # than drifting into the default path unnoticed.
      CATENA_GENERATION_PROVIDER: ${CATENA_GENERATION_PROVIDER:-ollama}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
```

- [ ] **Step 7: Verify compose still resolves and the default is unchanged**

```bash
docker compose config --quiet && echo "compose: OK"
docker compose config | grep -A 2 CATENA_GENERATION_PROVIDER
```

Expected: `compose: OK`, and the rendered value is `ollama` with a `.env` that does not set it.

- [ ] **Step 8: Commit**

```bash
git add services/catena/src/catena/serve/generate/__init__.py \
        services/catena/tests/test_serve_generate_claude.py .env.example compose.yaml
git commit -m "Generation: select the provider by name, never by ambient key

The default stays local and a key in the environment does not change it. A
missing key with the hosted provider selected fails at startup, where the
unset-CATENA_OLLAMA_URL failure already lives, rather than at the first
question a user asks."
```

---

### Task 5: The record — ADR and the specs it amends

The spec changes land last so they describe what was built rather than what was planned, but they
are not optional: CLAUDE.md requires a decision the spec did not anticipate to update the spec in
the same change, and this change contradicts three documents in writing.

**Files:**
- Create: `docs/adr/0025-byok-hosted-generation.md`
- Modify: `specs/SHARED-TECHNICAL-SPEC.md` (§1, two bullets)
- Modify: `services/catena/AGENTS.md` (the Conventions bullet on generation)
- Modify: `docs/CORPUS-POLICY.md`
- Modify: `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` (the Generation section)
- Modify: `README.md`
- Modify: `specs/001-phase-1-pca-baseline/BYOK-GENERATION-DESIGN.md` (Status)
- Modify: `docs/adr/0018-qwen3-8b-as-the-generation-default.md` (amendment pointer)

**Interfaces:**
- Consumes: everything built in Tasks 1-4
- Produces: nothing importable

- [ ] **Step 1: Read the template and a recent ADR for the house shape**

```bash
cat docs/adr/0000-template.md
sed -n '1,40p' docs/adr/0024-answer-level-failures-are-their-own-channel.md
```

- [ ] **Step 2: Write ADR-0025**

`docs/adr/0025-byok-hosted-generation.md`, following the template's sections exactly: Context,
Decision, Alternatives rejected, Consequences, Documents updated. It must cover, in the repository's
argued style rather than as a list:

- **Status:** Accepted. **Date:** the day it is written. **Phase:** 1.
- **Context.** The seam already exists and `service.py` depends only on the protocol. Three written
  commitments say something narrower: SHARED §1's sole-exception egress rule and its
  OpenAI-lingua-franca bullet, and ADR-0018's outright rejection of a hosted API. Name each.
- **Decision.** A hosted provider is a deployer-selected configuration, never the default;
  selection is explicit and never inferred from a key; the key is deployer-supplied; the trace
  records what answered; truncation and refusal both raise rather than degrading; nothing retries.
- **Decision, licence ordering.** Check 4 runs in Go after generation, so a hosted generator
  transmits retrieved text before the gateway rules on it. ADR-0017's answer applies unchanged —
  the deployer's key, the deployer's terms, the opt-in a recorded act, the ordering stated in
  CORPUS-POLICY. ESV and NIV are unaffected: never ingested, fetched at render time in Go.
- **Alternatives rejected.** Filtering the prompt by licence when the generator is remote (puts a
  decision in Python that AGENTS.md says Python does not own; makes two generators stop answering
  the same question). Refusing remote generation whenever a `local-only` corpus is indexed
  (`pca-bco-2026` is `local-only` and indexed, so this is "not yet" wearing a rule's clothes).
  Hand-rolling `/v1/messages` over `urllib` to preserve the stdlib convention (keeps a convention
  by hand-maintaining auth and an error taxonomy against a moving API, with nothing to catch the
  drift). An OpenAI-compatible shim (misrepresents exactly the features that matter here —
  structured output, thinking, the refusal stop reason).
- **Consequences.** The first vendor SDK in the request path. No `temperature`, so a BYOK run has
  no determinism to record — a second reason the Phase 2 baseline stays local. A new failure mode,
  refusal, with no local analogue. Per-answer cost is now a deployer's concern. `make dev-offline`
  is what keeps the default honest, and a change that makes a hosted provider reachable there is a
  defect.
- **Documents updated.** The list in Step 3 below.

- [ ] **Step 3: Amend the four documents that say otherwise**

**`specs/SHARED-TECHNICAL-SPEC.md` §1** — the egress bullet currently ends "The ESV adapter is the
sole exception and is deployer-enabled, never default." Replace that sentence with:

```
  Two exceptions exist, both deployer-enabled and never default: the ESV adapter, and a hosted
  generation provider selected by name (ADR-0025). Neither may be reached by a default
  configuration, and `make dev-offline` MUST fail loudly if either is.
```

The provider bullet currently reads "The generation provider MUST sit behind an interface using the
OpenAI-compatible chat-completions shape as the internal lingua franca, so Ollama, vLLM, llama.cpp,
and hosted APIs are interchangeable." Replace with:

```
- The generation provider MUST sit behind a typed interface — one constrained-completion method
  with a documented return — so Ollama, vLLM, llama.cpp, and hosted APIs are interchangeable. The
  request path MUST depend on that interface and on nothing provider-specific. The
  OpenAI-compatible chat-completions shape is the internal prompt representation and what local
  providers speak; a provider whose API is shaped otherwise translates at its own edge (ADR-0025).
```

**`services/catena/AGENTS.md`** — the Conventions bullet beginning "Generation behind an
OpenAI-compatible interface". Replace its last sentence — "The **wire format** is what delivers
that, not a vendor SDK ... on the same reasoning that keeps `acquire.fetch` on stdlib." — with:

```
  What delivers that is the **`Generator` protocol**, not a shared wire format: `service.py`
  depends on one method and a documented return. The local provider is a stdlib `urllib` POST on
  the same reasoning that keeps `acquire.fetch` on stdlib; the hosted provider uses its vendor's
  SDK and translates at its own edge (ADR-0025). Prompts are built OpenAI-shaped and a provider
  that needs another shape converts them.
```

**`docs/CORPUS-POLICY.md`** — add a section after the `local-only` section:

```markdown
## Hosted generation sends retrieved text to a third party

A deployer may select a hosted generation provider (ADR-0025). When they do, the passages
retrieved for a question travel to that provider as part of the prompt — and they travel
**before** verification check 4 has ruled on whether the licence permits serving them, because
verification is downstream of generation by design.

This is the deployer's decision to make, on exactly the footing ADR-0017 puts the ESV key on:
their key, their account, their acceptance of the provider's terms. This project ships no key,
sends nothing itself, and automates nothing around anyone's terms. It is off by default and
selecting it is an explicit, recorded act.

It bears most directly on `local-only` corpora, whose terms are unstated rather than permissive.
A deployer running `local-only` corpora against a hosted generator should satisfy themselves that
doing so is consistent with the terms they acquired that text under.

ESV and NIV are unaffected under every configuration. They are never ingested and are fetched at
render time by the gateway, so they cannot appear in a prompt.
```

**`docs/adr/0018-qwen3-8b-as-the-generation-default.md`** — in *Alternatives rejected*, the bullet
"**A hosted API by default.**" Append to it:

```
  Amended by ADR-0025, which does not disturb this: a hosted API remains rejected as the *default*,
  and is available as a deployer-selected configuration that leaves the acceptance test untouched.
```

- [ ] **Step 4: Update TECHNICAL-SPEC and README**

In `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md`, find the Generation section and add the
provider-selection variables, the default, and a pointer to ADR-0025 and the design doc. Match the
section's existing level of detail — do not restate the design.

In `README.md`, near where the RAM and disk floor is documented, add a short paragraph: the hosted
provider exists, it is off by default, it needs a key the deployer supplies, it costs roughly
$0.05-0.08 per answer, and it sends retrieved corpus text to Anthropic. Link CORPUS-POLICY.

- [ ] **Step 5: Close the design doc**

In `BYOK-GENERATION-DESIGN.md`, replace the *Status* section body with `Implemented. See
ADR-0025.` plus the date.

- [ ] **Step 6: Verify the repository guards and the full check**

```bash
make check
```

Expected: PASS. This runs `guard-corpus` (no corpus text — the new docs quote no passages),
`guard-make-targets`, `guard-proto-fresh`, the full unit suite and `config`.

- [ ] **Step 7: Verify the default path still holds end to end**

```bash
make dev-offline
docker compose -f compose.yaml -f compose.offline.yaml run --rm gateway ask --profile pca \
  --show-work "What does the Westminster Shorter Catechism say is the chief end of man?"
```

Expected: a verified answer citing `wsc-1788-american` at `WSC Q&A 1` — Q6 of the acceptance table,
the cheapest row that proves the stack works. The point of running it here is that the offline
overlay proves this change did not put egress in the default path.

- [ ] **Step 8: Commit**

```bash
git add docs/adr/0025-byok-hosted-generation.md docs/adr/0018-qwen3-8b-as-the-generation-default.md \
        specs/SHARED-TECHNICAL-SPEC.md services/catena/AGENTS.md docs/CORPUS-POLICY.md \
        specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md README.md \
        specs/001-phase-1-pca-baseline/BYOK-GENERATION-DESIGN.md
git commit -m "BYOK hosted generation: the decision, and the three documents that said otherwise

ADR-0025 records it. SHARED §1 gains a second deployer-enabled egress
exception and loses the claim that one wire format is what makes providers
interchangeable; AGENTS.md loses the same claim in its own words; ADR-0018's
rejection of a hosted API is narrowed to the default, which is what it always
argued. CORPUS-POLICY states the licence ordering plainly, because a deployer
weighing a local-only corpus against a hosted generator should be deciding
with the facts in front of them."
```

---

## What this plan does not do

Stated so an executor does not helpfully add them.

- **`ACCEPTANCE.md` is not touched.** Q4 and Q10 record what the pinned local default does. A BYOK
  run may answer both; overwriting the record with it would destroy what the record is for.
- **No eval harness work.** Phase 2 measures the local default, and this plan does not make the
  hosted provider a measured configuration.
- **No prompt caching.** The stable prefix is the rules block and the passages vary per question,
  so the win is small and unmeasured. YAGNI until someone has a bill.
- **No streaming**, no `thinking` display configuration, no refusal fallbacks. Each is argued
  against in the design; adding one is a spec change, not an implementation detail.
- **No change to `prompt.py`, `schema.py`, `service.py`, `server.py`, `proto/`, or any Go.**  If a
  task seems to need one, stop — the seam is in the wrong place and that is worth raising.
