# The Generation Provider Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four generation providers ship behind one typed protocol, the operator picks one with a
single environment variable, and every trace records which provider answered and what its request
actually enforced of the answer schema.

**Architecture:** `catena.serve.generate` becomes a package: `__init__.py` holds the shared
primitives and a reviewed provider table, `openai_chat.py` speaks the OpenAI chat-completions wire
format over stdlib `urllib`, `messages.py` speaks the Anthropic Messages format through the vendor
SDK. `service.py`, `prompt.py`, `schema.py` and `server.py` do not move; the only contract change is
two new fields on `RetrievalTrace`.

**Tech Stack:** Python 3.12 (`unittest`, run as scripts), the `anthropic` SDK, stdlib `urllib`,
protobuf (buf), Go 1.x, PostgreSQL 17 via golang-migrate.

**Spec:** [GENERATION-PROVIDERS-DESIGN.md](GENERATION-PROVIDERS-DESIGN.md) — read it before Task 1.
The plan argues from it and does not repeat its reasoning. Its dependency,
[GENERATION-FAILURE-CHANNEL-DESIGN.md](GENERATION-FAILURE-CHANNEL-DESIGN.md), has landed: `generate`
already returns `GenerationFailed` rather than raising, and `service.py` already maps it to
`catena_pb2.GenerationFailure`. This plan adds no new failure code.

## Global Constraints

- **The provider table is the specification.** Copy these values verbatim; a test asserts each one.

  | provider | wire | base URL | key env | default model | delivery | probed |
  | --- | --- | --- | --- | --- | --- | --- |
  | `ollama` *(default)* | `openai_chat` | `CATENA_OLLAMA_URL` | — | `qwen3:8b-q4_K_M` | `constrained` | yes |
  | `anthropic` | `messages` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` | `constrained` | no |
  | `openai` | `openai_chat` | `https://api.openai.com` | `OPENAI_API_KEY` | `gpt-6-luna` | `shaped` | no |
  | `deepseek` | `openai_chat` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` | `deepseek-flash` | `shaped` | yes |

  Two cells differ from the design's table and both are recorded in ADR-0026 as plan decisions, not
  silent edits — see **Two decisions the design left to the plan** below.
- **Base URLs are pinned in the table and never read from the environment** for a hosted provider.
  The Anthropic SDK reads `ANTHROPIC_BASE_URL` by itself, so an ambient value would redirect every
  retrieved passage to a third party while the configuration, the trace and CORPUS-POLICY all still
  named Anthropic. The constructor argument is what closes that.
- **The default does not move.** `ollama` and `qwen3:8b-q4_K_M`, with `docker compose up` working
  with no external accounts (SHARED §1) and `make dev-offline` continuing to answer. A hosted
  provider must fail *loudly* under `dev-offline`, never silently degrade.
- **Never ship model introspection** (CLAUDE.md constraint 5, ADR-0003). Three fields are the seam:
  `reasoning` on the OpenAI-compatible wire, `thinking` blocks on the Messages API, and
  `stop_details.explanation` on a Messages refusal. None is read, returned, traced or logged. A
  refusal records the provider's **category** and never its explanation. There must be no path.
- **Nothing in Catena retries** (ADR-0010). This now includes the vendor SDK's own retry loop: the
  `anthropic` client defaults to `max_retries=2`, which would make "attempt" mean two different
  things and hide a failing provider behind a latency spike. `max_retries=0`, asserted by a test.
- **No corpus text in this repository** (ADR-0014). Test fixtures use stubs like `{"position": "p"}`
  and invented prompts. This applies to the schema-delivery tests, which handle prompt text.
- **The schema itself never changes.** It is derived from the proto descriptor and ADR-0023's rules
  hold unaltered — in particular a top-level `required: []`, and no `minItems`. What varies is what
  the provider enforces. Never hand-write a second schema to suit a provider, and never relax
  ADR-0023 to make one accept it.
- **`prompt.py` learns nothing about providers.** Each adapter puts the schema where its wire and
  mode require. The stated cost is that providers receive different prompts, so cross-provider
  quality comparison is confounded — which is why the delivery mode reaches the trace.
- **At most two calls into Python per turn** (ADR-0002, ADR-0010). This change adds none.
- **No token streaming** (CLAUDE.md constraint 4). Every adapter is a single non-streaming call.
- Python line length 100. Test classes are named as sentences about behaviour; a test whose reason
  is not obvious from its name carries a docstring giving the reason.
- Tests are `unittest` run as scripts: `uv run --project services/catena python
  services/catena/tests/test_x.py -q`. Suites: `make test-catena`, `make test-gateway`, `make
  lint-py`, `make check`. Go tests: `go test ./services/gateway/...`. Schema assertions:
  `./tools/db/tests/test_schema.sh` (needs `make dev`).
- **No task in this plan needs a network or an API key.** Adapters keep the injected-transport
  pattern; the Messages adapter takes an injected client. The two probes that do need a key are
  Task 7, which is explicitly optional and blocks nothing.

## Two decisions the design left to the plan

Both are stated here so they are not discovered in review, and both are written into ADR-0026 and
back into the design document in Task 6.

**`openai` ships `shaped`, not "probe decides".** The design's table leaves the cell to a probe that
needs a deployer key, and open question 2 records why: if OpenAI's strict structured outputs require
every property in `required`, then `openai` is `shaped`, because ADR-0023 measured the all-required
shape producing `position: "no_position"` beside empty `arguments` and the contract does not bend to
fit a provider. A table has to hold a value before the probe runs, and the two candidates fail
differently. Shipping `constrained` unprobed risks a 400 on *every* request — a `ServeError` at the
first question, not a generation failure — and the design's own safety net ("an unanswered mode is
recorded as unverified and the failure channel catches what it catches") only holds for requests
that actually reach the model. `shaped` reaches it under either answer to the probe. The probe can
then promote the cell to `constrained`, which is a one-line table edit plus an ADR amendment, and
the trace's delivery mode is what makes the two eras of runs distinguishable — exactly the scenario
the design names.

**Open question 1 is answered from current documentation, and the probe is reduced to confirming
it live.** `output_config.format` documents support for `$ref`/`$defs`, `enum`, `anyOf`, and
`additionalProperties: false` (which it *requires* on every object), and documents as unsupported
only recursive schemas, numeric constraints (`minimum`, `maximum`, `multipleOf`), string constraints
(`minLength`, `maxLength`), and complex array constraints. The derived schema was read against that
list and uses none of them: it is `$defs` plus `$ref`, string enums, `additionalProperties: false`
throughout, and a top-level `required: []`. So the adapter sends the derived schema **verbatim** and
Task 7's probe confirms rather than decides. The design's instruction for a negative answer stands
unchanged: inline the definitions at that adapter's edge, never hand-write a second schema.

---

### Task 1: The package, with no behaviour changed

`generate.py` becomes `generate/`. Nothing about the request or the response handling moves in this
task — it exists so the split is reviewable on its own, and so a later reviewer can see that the
Ollama path was carried across rather than rewritten.

**Files:**
- Create: `services/catena/src/catena/serve/generate/__init__.py`
- Create: `services/catena/src/catena/serve/generate/openai_chat.py`
- Delete: `services/catena/src/catena/serve/generate.py`
- Modify: `services/catena/tests/test_serve_generate.py`

**Interfaces:**
- Consumes: nothing from a previous task.
- Produces:
  - `catena.serve.generate` — `URL_ENV`, `MODEL_ENV`, `DEFAULT_MODEL`, `TIMEOUT_SECONDS`,
    `MAX_TOKENS`, `Transport`, `Generation`, `GenerationFailed`, `Generator`, `connect()`
  - `catena.serve.generate.openai_chat` — `OllamaGenerator`, `_urllib_transport`

- [ ] **Step 1: Clear the stale directory PR #23 left behind**

`services/catena/src/catena/serve/generate/` already exists, holding only a `__pycache__` from the
closed branch. It must be empty before it becomes a package, or a stale `.pyc` shadows the new
module.

```bash
cd /Users/tim/projects/berean
rm -rf services/catena/src/catena/serve/generate/__pycache__ \
       services/catena/src/catena/serve/__pycache__
ls -A services/catena/src/catena/serve/generate/
```

Expected: no output — the directory is empty.

- [ ] **Step 2: Move the file into the package, preserving history**

```bash
git mv services/catena/src/catena/serve/generate.py \
       services/catena/src/catena/serve/generate/openai_chat.py
```

- [ ] **Step 3: Write the package `__init__.py`**

Create `services/catena/src/catena/serve/generate/__init__.py` with exactly this content. Every
comment here is lifted from the module it came from, unchanged; the docstring is new, because the
old one described a single provider.

```python
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
```

Note the local import inside `connect`. `openai_chat` imports the primitives above from this module,
so importing it at module scope is a cycle. Task 3 relies on the same seam to keep the vendor SDK
off the default path's import.

- [ ] **Step 4: Trim `openai_chat.py` to the adapter**

The moved file still holds everything. Delete from it every definition now living in `__init__.py`:
the module docstring, `URL_ENV`, `MODEL_ENV`, `DEFAULT_MODEL`, `default_model`, `TIMEOUT_SECONDS`,
`MAX_TOKENS`, `Transport`, `Generation`, `GenerationFailed`, `Generator`, and `connect`. What remains
is `_urllib_transport` and `OllamaGenerator`, unchanged in body.

Replace the file's header (everything above `def _urllib_transport`) with:

```python
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
from catena.serve.generate import MAX_TOKENS, TIMEOUT_SECONDS, Generation, GenerationFailed, Transport
```

That import line exceeds 100 characters. Split it:

```python
from catena.serve.generate import (
    MAX_TOKENS,
    TIMEOUT_SECONDS,
    Generation,
    GenerationFailed,
    Transport,
)
```

- [ ] **Step 5: Give `_urllib_transport` the headers argument**

`Transport` gained a headers parameter in `__init__.py`. Replace `_urllib_transport` and the one
call site in `OllamaGenerator.generate` accordingly.

```python
def _urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()
```

In `OllamaGenerator.generate`, the call becomes:

```python
        try:
            raw = self._transport(
                self._url, body, {"Content-Type": "application/json"}, self._timeout
            )
```

- [ ] **Step 6: Point the test file at the package**

In `services/catena/tests/test_serve_generate.py`:

Replace the import block:

```python
from catena.serve import ServeError
from catena.serve import generate as generate_module
from catena.serve.generate import openai_chat
```

Replace `FakeTransport.__call__` so it records the headers the new signature carries:

```python
    def __call__(self, url: str, body: bytes, headers: dict[str, str], timeout: float) -> bytes:
        self.url = url
        self.body = json.loads(body)
        self.headers = dict(headers)
        if self.error is not None:
            raise self.error
        return json.dumps(self.response).encode()
```

and add `self.headers: dict[str, str] = {}` to `FakeTransport.__init__`.

Replace the `generator` helper:

```python
def generator(transport: FakeTransport) -> openai_chat.OllamaGenerator:
    return openai_chat.OllamaGenerator(
        "http://ollama:11434", generate_module.DEFAULT_MODEL, transport=transport)
```

Leave every test body alone. `generate_module.DEFAULT_MODEL` still resolves, because `DEFAULT_MODEL`
is now the package's.

- [ ] **Step 7: Run the suite — it must pass unchanged in behaviour**

```bash
cd /Users/tim/projects/berean
uv run --project services/catena python services/catena/tests/test_serve_generate.py -q
uv run --project services/catena python services/catena/tests/test_serve_service.py -q
make test-catena
make lint-py
```

Expected: all PASS, `catena: OK`, `lint-py: OK`. This task changes no behaviour. A failing assertion
means a definition was dropped in the split, not that an expectation was wrong.

- [ ] **Step 8: Commit**

```bash
git add services/catena/src/catena/serve/generate.py \
        services/catena/src/catena/serve/generate/ \
        services/catena/tests/test_serve_generate.py
git commit -m "Generation becomes a package, with nothing else changed

One module per wire format is coming; this is the move on its own, so the
Ollama path is visibly carried across rather than rewritten. Transport grows a
headers argument, which a hosted provider needs for its key.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KkRvxYV6p3qJgScTp7if2b"
```

---

### Task 2: The provider table, and the three delivery modes

The three OpenAI-compatible providers, behind one adapter and one reviewed table. The Anthropic row
arrives in Task 3.

**Files:**
- Modify: `services/catena/src/catena/serve/generate/__init__.py`
- Modify: `services/catena/src/catena/serve/generate/openai_chat.py`
- Modify: `services/catena/tests/test_serve_generate.py`

**Interfaces:**
- Consumes: `Generation`, `GenerationFailed`, `Transport`, `MAX_TOKENS`, `TIMEOUT_SECONDS`,
  `DEFAULT_MODEL` from Task 1.
- Produces:
  - `CONSTRAINED`, `SHAPED`, `UNCONSTRAINED`, `DELIVERY_MODES`
  - `OPENAI_CHAT`, `MESSAGES` (wire names)
  - `PROVIDER_ENV`, `DEFAULT_PROVIDER`
  - `Provider` — frozen dataclass, fields `name`, `wire`, `base_url`, `url_env`, `key_env`,
    `default_model`, `delivery`, `probed`, `params`
  - `PROVIDERS: dict[str, Provider]`
  - `connect(provider: str | None = None, model: str | None = None) -> Generator`
  - `Generator` protocol gains `provider: str` and `delivery: str`
  - `openai_chat.OpenAIChatGenerator(entry, model, base_url, api_key="", *, max_tokens, timeout,
    transport)` — replaces `OllamaGenerator`

- [ ] **Step 1: Write the failing tests for the table and selection**

Append to `services/catena/tests/test_serve_generate.py`, above the `if __name__` block:

```python
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
```

Add `import dataclasses` and `import os` to the test file's import block.

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate.py -q
```

Expected: FAIL with `AttributeError: module 'catena.serve.generate' has no attribute 'PROVIDERS'`
and `module 'catena.serve.generate.openai_chat' has no attribute 'OpenAIChatGenerator'`.

- [ ] **Step 3: Add the table and selection to `__init__.py`**

Insert after `Transport` and before `Generation`:

```python
#: The wire formats, one module each.
OPENAI_CHAT = "openai_chat"
MESSAGES = "messages"

#: What a provider's request enforces of the answer schema. The schema itself
#: never varies -- it is derived from the proto descriptor and ADR-0023's rules
#: hold unaltered. What varies is enforcement, and each mode fails into a
#: channel that already exists (ADR-0026):
#:
#:   constrained    the decoder is held to the schema; semantic violations only,
#:                  caught by verification and `answer_failures`
#:   shaped         JSON-ness only, and the schema is requested as text. The
#:                  object parses, so a wrong slot regenerates through
#:                  ADR-0024's machinery with no new code
#:   unconstrained  nothing. The reply may not be JSON, which is what
#:                  GENERATION_FAILURE_CODE_NOT_JSON catches (ADR-0025)
CONSTRAINED = "constrained"
SHAPED = "shaped"
UNCONSTRAINED = "unconstrained"
DELIVERY_MODES = (CONSTRAINED, SHAPED, UNCONSTRAINED)

PROVIDER_ENV = "CATENA_GENERATION_PROVIDER"
DEFAULT_PROVIDER = "ollama"


@dataclass(frozen=True)
class Provider:
    """One row of the reviewed table. Every field is a claim a test asserts.

    Operator YAML was considered and rejected (ADR-0026): it would move the
    capability claim from something this project probed to something the
    operator asserts, and a wrong assertion surfaces as a mysterious
    degradation rate rather than as a clear fact.
    """

    name: str
    #: Which module speaks for it.
    wire: str
    #: Absolute and pinned for a hosted provider, empty for a local one. Never
    #: read from the environment when set: the Anthropic SDK reads
    #: ANTHROPIC_BASE_URL by itself, so an ambient value would silently
    #: redirect every retrieved passage to a third party while the
    #: configuration, the trace and CORPUS-POLICY all still named Anthropic.
    #: Pinning is what makes the provider named `anthropic` *be* Anthropic.
    base_url: str
    #: Where a local provider's URL comes from instead. Empty when pinned.
    url_env: str
    #: Empty for a provider that needs no account. The key is read at
    #: `connect()` and never defaulted -- a stack that starts and cannot answer
    #: is a configuration error reported at the worst possible moment.
    key_env: str
    default_model: str
    delivery: str
    #: Whether the delivery mode above was *probed* against the live provider
    #: or read from its documentation. An unprobed mode is not a reason to
    #: refuse the provider -- `retrieval.py` leaves its known risk "naive and
    #: measured, not pre-empted", and the trust boundary means unconstrained
    #: output is caught rather than shipped. It is recorded so the degradation
    #: and generation-failure rates can be read knowing which is which.
    probed: bool
    #: Provider-specific request parameters, as pairs so a frozen entry is
    #: genuinely immutable rather than merely annotated as one.
    params: tuple[tuple[str, Any], ...] = ()


#: The four providers this build ships. Adding a fifth is a small change plus an
#: ADR (ADR-0026); it is deliberately not a file format.
PROVIDERS: dict[str, Provider] = {
    DEFAULT_PROVIDER: Provider(
        name=DEFAULT_PROVIDER,
        wire=OPENAI_CHAT,
        base_url="",
        url_env=URL_ENV,
        key_env="",
        default_model=DEFAULT_MODEL,
        delivery=CONSTRAINED,
        probed=True,
        # `temperature` is pinned only here, and that asymmetry is the point:
        # the Phase 2 baseline is a measurement, and a default temperature makes
        # it a distribution nobody recorded. The hosted providers get no
        # sampling parameters at all -- their parameter surfaces were not
        # probed, a hosted run is not quotable as the baseline anyway, and at
        # least one current model family rejects sampling parameters outright.
        # `reasoning_effort: "none"` is Qwen3's, for the reason openai_chat's
        # docstring gives; it is not a blanket rule.
        params=(("temperature", 0.0), ("reasoning_effort", "none")),
    ),
    "openai": Provider(
        name="openai",
        wire=OPENAI_CHAT,
        base_url="https://api.openai.com",
        url_env="",
        key_env="OPENAI_API_KEY",
        default_model="gpt-6-luna",
        # Shaped until a probe says otherwise. ADR-0023 measured the
        # all-required shape producing `position: "no_position"` beside empty
        # `arguments`, so if strict structured outputs demand every property in
        # `required`, the contract does not bend to fit the provider. Shipping
        # `constrained` unprobed would risk a 400 on every request -- a
        # ServeError at the first question, not a generation failure -- and the
        # failure channel can only catch what actually reaches the model. A
        # probe promotes this cell; see PLAN, "Two decisions the design left to
        # the plan".
        delivery=SHAPED,
        probed=False,
    ),
    "deepseek": Provider(
        name="deepseek",
        wire=OPENAI_CHAT,
        base_url="https://api.deepseek.com",
        url_env="",
        key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-flash",
        # Shaped, not unconstrained: `response_format` accepts
        # `{"type": "json_object"}` -- verified -- which guarantees JSON without
        # guaranteeing the schema.
        delivery=SHAPED,
        probed=True,
    ),
}
```

Replace the `Generator` protocol with:

```python
class Generator(Protocol):
    """What the request path needs of a model, and nothing more.

    This protocol is the interface that makes providers interchangeable. The
    wire format is not, and the Anthropic Messages API is the case that
    separates the two claims (ADR-0026).
    """

    #: Written to `RetrievalTrace.generation_model`.
    model: str
    #: Written to `RetrievalTrace.generation_provider`. Present on the adapter
    #: rather than on `Generation`, so a failed attempt still names what
    #: attempted it.
    provider: str
    #: One of `DELIVERY_MODES`, written to `RetrievalTrace.schema_delivery`.
    #: Without it, two runs of one model under different enforcement are
    #: indistinguishable in the data the Phase 2 harness reads.
    delivery: str

    def generate(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> Generation | GenerationFailed:
        """One completion, a reported failure, or `ServeError`."""
        ...
```

Replace `default_model` and `connect` with:

```python
def _base_url(entry: Provider) -> str:
    """Where the request goes. Pinned in the table, or a local deployment's URL.

    Nothing here consults the environment for a provider whose `base_url` is
    set. See `Provider.base_url`.
    """
    if entry.base_url:
        return entry.base_url
    base = os.environ.get(entry.url_env, "").strip()
    if not base:
        raise ServeError(
            f"{entry.url_env} is unset. Provider {entry.name!r} runs against a local "
            "server the compose stack provides -- run the service through `make dev`."
        )
    return base


def _api_key(entry: Provider) -> str:
    """The deployer's key, read once at startup.

    Read here rather than per request so a missing key is a configuration error
    at `connect()` instead of a failure at the first question, which reads to
    whoever sees it like a broken provider.
    """
    if not entry.key_env:
        return ""
    key = os.environ.get(entry.key_env, "").strip()
    if not key:
        raise ServeError(
            f"provider {entry.name!r} needs {entry.key_env}, which is unset. A hosted "
            "provider is deployer-enabled and never default (SHARED §1); see "
            "docs/CORPUS-POLICY.md for who receives retrieved corpus text under it."
        )
    return key


def _model(entry: Provider, model: str | None) -> str:
    """The pinned default, or the deployer's override within this provider.

    `CATENA_GENERATION_MODEL` applies inside the selected provider and must name
    a model that provider serves. ADR-0018 documents a smaller local fallback
    for low-RAM machines and is explicit that it is a degradation rather than a
    second supported configuration. The trace records what actually answered,
    so a deployment running the fallback is visible in the data rather than only
    in someone's shell history.
    """
    return model or os.environ.get(MODEL_ENV) or entry.default_model


def connect(provider: str | None = None, model: str | None = None) -> Generator:
    """The generator the server runs with.

    One environment variable chooses among the providers in `PROVIDERS`, and a
    key in the environment is a credential rather than a selection: an ambient
    `OPENAI_API_KEY` does not move a deployment off the local default.
    """
    # Local: the adapters import this module's primitives, so importing them at
    # module scope is a cycle -- and it keeps a vendor SDK off the import path
    # of a deployment that never selects it.
    from catena.serve.generate import openai_chat

    name = (provider or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip()
    entry = PROVIDERS.get(name)
    if entry is None:
        raise ServeError(
            f"{PROVIDER_ENV}={name!r} names no provider this build ships. "
            f"The providers are: {', '.join(sorted(PROVIDERS))}."
        )

    if entry.wire == OPENAI_CHAT:
        return openai_chat.OpenAIChatGenerator(
            entry, _model(entry, model), _base_url(entry), api_key=_api_key(entry)
        )
    raise ServeError(f"provider {name!r} names wire format {entry.wire!r}, which has no adapter")
```

`default_model()` is gone: the pin lives in `DEFAULT_MODEL` and the override resolution is
`_model`. The pin test in `ThePinMatchesProvisioning` reads `DEFAULT_MODEL` and is unaffected.

- [ ] **Step 4: Generalise the adapter in `openai_chat.py`**

Rename `OllamaGenerator` to `OpenAIChatGenerator` and replace its `__init__`, `generate`, and the
request construction. `_parse` and `_content` keep their bodies; only the two hardcoded `ollama`
strings in `_parse`/`generate` become `self.provider`.

```python
#: The schema as text, for a provider that will not enforce it. The adapter owns
#: delivery so `prompt.py` learns nothing about providers, which keeps the
#: translation at the provider's own edge. The cost is stated rather than
#: discovered later: providers receive different prompts, so cross-provider
#: quality comparison is confounded -- which is why the trace records the mode,
#: putting the confound in the data rather than hiding it there.
SCHEMA_INSTRUCTION = (
    "Reply with a single JSON object and nothing else -- no prose before or "
    "after it, and no code fence. It must validate against this JSON Schema:"
)

#: `make dev-offline` marks the network internal (SHARED §1), so a hosted
#: provider cannot resolve. That is the intended result and the message says so,
#: rather than reading as a broken deployment.
_LOCAL_HINT = (
    "The generator runs in the compose stack -- check that the `ollama` service is healthy."
)
_HOSTED_HINT = (
    "`make dev-offline` blocks egress by design (SHARED §1), and a hosted provider "
    "cannot answer there. The default provider is local and needs no account."
)


def _with_schema_in_system(
    messages: Sequence[dict[str, str]], schema: dict[str, Any]
) -> list[dict[str, str]]:
    """The prompt with the schema appended to its system message, on a copy.

    A copy because the caller still holds its list and `prompt.py` is not party
    to this; mutating it in place would put provider-specific text into the
    object `service.py` handed to the observability span.
    """
    out = [dict(message) for message in messages]
    for message in out:
        if message.get("role") == "system":
            message["content"] = (
                f"{message['content']}\n\n{SCHEMA_INSTRUCTION}\n\n{json.dumps(schema, indent=2)}"
            )
            return out
    raise ServeError(
        "a shaped or unconstrained provider needs a system message to carry the schema, "
        "and prompt.build sent none"
    )


class OpenAIChatGenerator:
    """Any provider speaking OpenAI chat-completions, under any delivery mode."""

    def __init__(
        self,
        entry: Provider,
        model: str,
        base_url: str,
        api_key: str = "",
        *,
        max_tokens: int = MAX_TOKENS,
        timeout: float = TIMEOUT_SECONDS,
        transport: Transport | None = None,
    ) -> None:
        self.provider = entry.name
        self.delivery = entry.delivery
        self.model = model
        self._params = dict(entry.params)
        self._url = base_url.rstrip("/") + "/v1/chat/completions"
        self._key = api_key
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._transport = transport or _urllib_transport

    def generate(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> Generation | GenerationFailed:
        body = json.dumps(self._request(messages, schema)).encode()

        try:
            raw = self._transport(self._url, body, self._headers(), self._timeout)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            raise ServeError(
                f"{self.provider} refused the generation request ({error.code}): {detail}"
            ) from error
        except Exception as error:  # transport, DNS, timeout
            hint = _LOCAL_HINT if not self._key else _HOSTED_HINT
            raise ServeError(
                f"{self.provider} is unreachable at {self._url}: {error}. {hint}"
            ) from error

        return self._parse(raw)

    def _headers(self) -> dict[str, str]:
        """The key travels in the header, never in the body.

        The body is what the observability span and every debugging aid print.
        """
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        return headers

    def _request(
        self, messages: Sequence[dict[str, str]], schema: dict[str, Any]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": self._max_tokens,
        }
        body.update(self._params)

        if self.delivery == CONSTRAINED:
            # ADR-0018 requires AnswerObject validity to be a decoding
            # constraint rather than a request the prompt makes politely.
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer_object", "strict": True, "schema": schema},
            }
        elif self.delivery == SHAPED:
            # JSON-ness guaranteed, the schema merely requested. The object
            # parses, so a wrong slot regenerates through ADR-0024's machinery.
            body["response_format"] = {"type": "json_object"}
            body["messages"] = _with_schema_in_system(messages, schema)
        else:
            # Nothing enforced. GENERATION_FAILURE_CODE_NOT_JSON is the channel.
            body["messages"] = _with_schema_in_system(messages, schema)

        return body
```

Add `Provider`, `CONSTRAINED` and `SHAPED` to the `from catena.serve.generate import (...)` block.
In `_parse`, replace the three `ollama` strings: `"ollama returned a body that is not JSON"` becomes
`f"{self.provider} returned a body that is not JSON"`, and `detail="ollama returned no choices"`
becomes `detail=f"{self.provider} returned no choices"`. `_parse` must stop being a `@staticmethod`
nowhere — it already is an instance method; `_content` stays a `@staticmethod`.

- [ ] **Step 5: Point the existing tests at the new class**

In `services/catena/tests/test_serve_generate.py`, replace the `generator` helper:

```python
def generator(transport: FakeTransport) -> openai_chat.OpenAIChatGenerator:
    entry = generate_module.PROVIDERS[generate_module.DEFAULT_PROVIDER]
    return openai_chat.OpenAIChatGenerator(
        entry, generate_module.DEFAULT_MODEL, "http://ollama:11434", transport=transport)
```

Every existing test body stays as it is. `test_disables_model_thinking` still asserts
`reasoning_effort == "none"`, which now comes from the table's `params`, and that is the point.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate.py -q
make test-catena
make lint-py
```

Expected: PASS, `catena: OK`, `lint-py: OK`.

- [ ] **Step 7: Commit**

```bash
git add services/catena/src/catena/serve/generate/ services/catena/tests/test_serve_generate.py
git commit -m "Three providers on one wire, and the three delivery modes

The table is the specification and every cell is a test. openai ships shaped
rather than unprobed-constrained: ADR-0023 measured why the contract does not
bend to strict mode's all-required shape, and the failure channel can only
catch what reaches the model.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KkRvxYV6p3qJgScTp7if2b"
```

---

### Task 3: The Anthropic Messages wire format

The second wire format, and the case that makes the design's whole argument: a different request
shape, a vendor SDK, and the same `Generator` protocol.

**Files:**
- Create: `services/catena/src/catena/serve/generate/messages.py`
- Modify: `services/catena/src/catena/serve/generate/__init__.py`
- Modify: `services/catena/pyproject.toml`
- Modify: `uv.lock` (written by `uv add`, committed)
- Create: `services/catena/tests/test_serve_generate_messages.py`

**Interfaces:**
- Consumes: `Provider`, `PROVIDERS`, `CONSTRAINED`, `MESSAGES`, `Generation`, `GenerationFailed`,
  `MAX_TOKENS`, `TIMEOUT_SECONDS` from Tasks 1–2.
- Produces:
  - `PROVIDERS["anthropic"]`
  - `messages.BASE_URL`, `messages.THINKING`, `messages.EFFORT`
  - `messages.MessagesGenerator(entry, model, api_key, *, base_url, max_tokens, timeout, client)`
  - `messages.build_client(api_key, base_url, timeout)`

- [ ] **Step 1: Add the dependency, and record what it resolved to**

```bash
cd /Users/tim/projects/berean
uv add --project services/catena 'anthropic<1'
uv run --project services/catena python -c "
import importlib.metadata as m
print('version:', m.version('anthropic'))
print('licence:', m.metadata('anthropic').get('License-Expression') or m.metadata('anthropic').get('License'))
"
```

Record both values — the next step writes them into `pyproject.toml`, and the licence is stated for
the same reason every other dependency in that file states one.

- [ ] **Step 2: Pin the floor with the reason the SDK is here at all**

In `services/catena/pyproject.toml`, `uv add` appended a bare `"anthropic<1"` to `dependencies`.
Replace that line with the following, substituting the version Step 1 printed for `<RESOLVED>` (as
`>=major.minor`) and the licence for `<LICENCE>`:

```toml
    # The one vendor SDK in the request path, and a considered reversal of this
    # project's own convention (ADR-0026). `catena.serve.generate.openai_chat`
    # is stdlib `urllib` on the reasoning that keeps `acquire.fetch` on stdlib,
    # and the Anthropic Messages API is the case that shows the wire format was
    # never what made providers interchangeable -- the typed `Generator`
    # protocol is. Hand-rolling a second wire format would mean hand-maintaining
    # `thinking`, `output_config` and the refusal shape against a moving API,
    # for no gain the protocol does not already give.
    #
    # <LICENCE>, which permits the commercial downstream use CLAUDE.md tells us
    # to assume. The floor is the `output_config.format` and adaptive-thinking
    # surface this adapter sends; the exact version is pinned in uv.lock. It is
    # imported lazily, so a deployment on the local default never loads it, and
    # `docker compose up` still needs no account.
    "anthropic>=<RESOLVED>,<1",
```

- [ ] **Step 3: Write the failing tests**

Create `services/catena/tests/test_serve_generate_messages.py`:

```python
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
```

- [ ] **Step 4: Run them to verify they fail**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate_messages.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'catena.serve.generate.messages'`.

- [ ] **Step 5: Write `messages.py`**

Create `services/catena/src/catena/serve/generate/messages.py`:

```python
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
```

- [ ] **Step 6: Add the row and the dispatch**

In `services/catena/src/catena/serve/generate/__init__.py`, add to `PROVIDERS`, between the
`DEFAULT_PROVIDER` entry and `"openai"`:

```python
    "anthropic": Provider(
        name="anthropic",
        wire=MESSAGES,
        base_url="https://api.anthropic.com",
        url_env="",
        key_env="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-5-5",
        # `output_config.format` documents support for `$ref`/`$defs`, string
        # enums and `additionalProperties: false` (which it requires on every
        # object), and documents as unsupported only recursive schemas,
        # numeric and string constraints, and complex array constraints -- none
        # of which the derived schema uses. Read from documentation rather than
        # probed against the live provider, hence `probed=False`; Task 7's probe
        # confirms rather than decides.
        delivery=CONSTRAINED,
        probed=False,
    ),
```

In `connect`, extend the local import and the dispatch:

```python
    from catena.serve.generate import messages as messages_wire
    from catena.serve.generate import openai_chat

    ...

    if entry.wire == OPENAI_CHAT:
        return openai_chat.OpenAIChatGenerator(
            entry, _model(entry, model), _base_url(entry), api_key=_api_key(entry)
        )
    if entry.wire == MESSAGES:
        return messages_wire.MessagesGenerator(
            entry,
            _model(entry, model),
            _api_key(entry),
            base_url=_base_url(entry),
        )
    raise ServeError(f"provider {name!r} names wire format {entry.wire!r}, which has no adapter")
```

- [ ] **Step 7: Extend the table tests to cover the fourth row**

In `services/catena/tests/test_serve_generate.py`, `TheHostedDefaultsArePinned` now has three
entries. Replace the assertion:

```python
        self.assertEqual(
            {n: e.default_model for n, e in generate_module.PROVIDERS.items() if e.key_env},
            {
                "anthropic": "claude-sonnet-5-5",
                "openai": "gpt-6-luna",
                "deepseek": "deepseek-flash",
            },
        )
```

And add to `HowTheProviderIsChosen`:

```python
    def test_an_ambient_base_url_does_not_change_where_requests_go(self) -> None:
        """Pinned in the table, so the provider named `anthropic` *is* Anthropic."""
        entry = generate_module.PROVIDERS["anthropic"]
        os.environ["ANTHROPIC_BASE_URL"] = "https://invented-exfiltration.example"
        self.addCleanup(os.environ.pop, "ANTHROPIC_BASE_URL", None)
        self.assertEqual(generate_module._base_url(entry), "https://api.anthropic.com")
```

Add `"ANTHROPIC_API_KEY"` to the names `setUp` pops.

- [ ] **Step 8: Run the tests to verify they pass**

```bash
uv run --project services/catena python services/catena/tests/test_serve_generate_messages.py -q
uv run --project services/catena python services/catena/tests/test_serve_generate.py -q
make test-catena
make lint-py
```

Expected: PASS, `catena: OK`, `lint-py: OK`.

- [ ] **Step 9: Prove the default path still loads without touching the SDK**

The lazy import is a constraint, not an optimisation: a deployment on the local default must not
depend on the vendor SDK being importable.

```bash
uv run --project services/catena python -c "
import sys
sys.path.insert(0, 'services/catena/src'); sys.path.insert(0, 'services/catena/gen')
import os
os.environ['CATENA_OLLAMA_URL'] = 'http://ollama:11434'
from catena.serve import generate
g = generate.connect()
print('provider:', g.provider, '| delivery:', g.delivery, '| model:', g.model)
print('anthropic imported:', 'anthropic' in sys.modules)
"
```

Expected: `provider: ollama | delivery: constrained | model: qwen3:8b-q4_K_M` and
`anthropic imported: False`.

- [ ] **Step 10: Commit**

```bash
git add services/catena/pyproject.toml uv.lock \
        services/catena/src/catena/serve/generate/ \
        services/catena/tests/test_serve_generate.py \
        services/catena/tests/test_serve_generate_messages.py
git commit -m "The Messages wire format, and the claim it corrects

A vendor SDK in the request path, reversing this project's own convention, and
the reason the convention was stated wrong: the wire format was never what made
providers interchangeable -- the typed protocol is.

thinking is asserted positively; the base URL is pinned against an ambient
variable; the SDK is told not to retry, because ADR-0010 owns the one retry.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KkRvxYV6p3qJgScTp7if2b"
```

---

### Task 4: The trace learns which provider answered

Two fields on `RetrievalTrace`, and the Python side that fills them. Without the delivery mode, two
runs of one model under different enforcement are indistinguishable in the only data the Phase 2
harness reads — and that becomes a live scenario the moment Task 7's probe reclassifies `openai`.

**Files:**
- Modify: `proto/berean/v1/trace.proto:13-34`
- Modify: `gen/` and `services/catena/gen/` (regenerated, committed — ADR-0022)
- Modify: `services/catena/src/catena/serve/service.py:36-47,125-147`
- Modify: `services/catena/tests/fakes.py:296-317`
- Modify: `services/catena/tests/test_proto_contract.py:246-265`
- Modify: `services/catena/tests/test_serve_service.py`

**Interfaces:**
- Consumes: `Generator.provider`, `Generator.delivery` from Tasks 2–3.
- Produces:
  - `bereanv1.RetrievalTrace.generation_provider` (string, field 8)
  - `bereanv1.RetrievalTrace.schema_delivery` (`SchemaDelivery`, field 9)
  - `bereanv1.SchemaDelivery` — `UNSPECIFIED`, `CONSTRAINED`, `SHAPED`, `UNCONSTRAINED`
  - `service._DELIVERY_MODES: dict[str, int]`

- [ ] **Step 1: Add the fields to `trace.proto`**

After `Timings timings = 7;` inside `message RetrievalTrace` (`proto/berean/v1/trace.proto:33`),
add:

```proto

  // Which provider answered, or which was asked when the attempt produced
  // nothing. A string for the same reason `generation_model` is one: it is an
  // identifier, and the set is closed by the provider table in
  // `catena.serve.generate` rather than by this contract -- adding a fifth
  // provider is a code change and an ADR, not a contract change (ADR-0026).
  string generation_provider = 8;

  // What that provider's request actually enforced of the answer schema. An
  // enum rather than a string, because this is the classification the Phase 2
  // harness groups by: two runs of one model under different enforcement are
  // otherwise indistinguishable, and that becomes live the moment a probe
  // reclassifies a provider (ADR-0026).
  SchemaDelivery schema_delivery = 9;
```

After the `RetrievalTrace` message's closing brace, add:

```proto
// What a provider's request enforced of the answer schema. The schema itself
// never varies -- it is derived from the proto descriptor and ADR-0023's rules
// hold unaltered. Each mode fails into a channel that already exists.
enum SchemaDelivery {
  SCHEMA_DELIVERY_UNSPECIFIED = 0;
  // The decoder was held to the schema. Only semantic violations get through,
  // and verification and `answer_failures` catch those.
  SCHEMA_DELIVERY_CONSTRAINED = 1;
  // JSON-ness was enforced and the schema was requested as text. Fields can be
  // missing, extra or wrong-typed, but the object parses -- so a wrong slot
  // regenerates through ADR-0024's machinery with no new code.
  SCHEMA_DELIVERY_SHAPED = 2;
  // Nothing was enforced. The reply may not be JSON at all, which is what
  // GENERATION_FAILURE_CODE_NOT_JSON catches (ADR-0025).
  SCHEMA_DELIVERY_UNCONSTRAINED = 3;
}
```

- [ ] **Step 2: Regenerate and lint the contract**

```bash
make proto-lint && make proto
```

Expected: `proto-lint: OK`, then regeneration writes `gen/` and `services/catena/gen/`. Both are
committed (ADR-0022) — commit exactly what it writes, and never hand-edit a generated file.

- [ ] **Step 3: Write the failing contract and service tests**

In `services/catena/tests/test_proto_contract.py`, replace `TheTrace.test_trace_fields`'s expected
set with:

```python
            {
                "rewritten_query",
                "candidates",
                "embedding_model",
                "dim",
                "generation_model",
                "generation_provider",
                "schema_delivery",
                "top_k",
                "timings",
            },
```

and add to `TheTrace`:

```python
    def test_trace_records_what_the_provider_enforced(self) -> None:
        """A model name alone cannot tell two enforcement regimes apart."""
        fields = field_names(trace_pb2.RetrievalTrace)
        self.assertIn("generation_provider", fields)
        self.assertIn("schema_delivery", fields)
```

and to the `ClosedEnums` class:

```python
    def test_schema_delivery_modes(self) -> None:
        """Three modes and an unspecified zero. A fourth would need an ADR."""
        self.assertEqual(
            set(trace_pb2.SchemaDelivery.keys()),
            {
                "SCHEMA_DELIVERY_UNSPECIFIED",
                "SCHEMA_DELIVERY_CONSTRAINED",
                "SCHEMA_DELIVERY_SHAPED",
                "SCHEMA_DELIVERY_UNCONSTRAINED",
            },
        )

    def test_every_delivery_mode_the_generator_can_report_has_a_contract_value(self) -> None:
        """The table's short names and the enum cannot drift apart silently."""
        from catena.serve import generate as generate_module
        from catena.serve import service

        for mode in generate_module.DELIVERY_MODES:
            with self.subTest(mode=mode):
                self.assertIn(mode, service._DELIVERY_MODES)
```

In `services/catena/tests/test_serve_service.py`, extend the existing
`WhenTheGenerationProducesNoObject._FailingGenerator` (line 251) so it satisfies the widened
protocol — without this it reports no delivery mode and Step 5's guard fires:

```python
    class _FailingGenerator:
        """Stands in for a real adapter when the model answered uselessly.

        Not `FakeGenerator`: that fake's `generate` returns `Generation` or
        raises, matching the old contract. This one returns `GenerationFailed`,
        matching the new one.
        """

        model = "fake-generator"
        provider = "fake-provider"
        delivery = "constrained"

        def generate(self, messages, schema):
            return generate.GenerationFailed(code="truncated", detail="d", completion_tokens=7)
```

Then add to the existing `TheTrace` class (line 139), which already owns the
`test_records_both_model_identifiers` test this sits beside:

```python
    def test_records_the_provider_and_what_it_enforced(self) -> None:
        """A hosted run is legitimate and must be labelled (SHARED §7, ADR-0026).

        `generation_model` alone cannot tell two enforcement regimes apart, and
        that becomes live the moment a probe reclassifies a provider.
        """
        response = service().Answer(request(), Context())
        self.assertEqual(response.trace.generation_provider, "fake-provider")
        self.assertEqual(
            response.trace.schema_delivery, trace_pb2.SCHEMA_DELIVERY_CONSTRAINED)

    def test_an_unmapped_delivery_mode_is_a_bug_not_a_mode(self) -> None:
        """Defaulting to UNSPECIFIED would write a programming error into the
        column the Phase 2 harness groups by, where it would average cleanly."""
        from catena.serve import ServeError

        generator = FakeGenerator(ANSWER)
        generator.delivery = "invented-mode"
        with self.assertRaises(ServeError) as caught:
            service(generator=generator)._answer(request())
        self.assertIn("invented-mode", str(caught.exception))
```

and to `WhenTheGenerationProducesNoObject`:

```python
    def test_a_failed_attempt_still_names_what_attempted_it(self) -> None:
        """The provider is read off the adapter, not off a `Generation` there isn't."""
        response = self._answer_with_failure()
        self.assertEqual(response.trace.generation_provider, "fake-provider")
        self.assertEqual(
            response.trace.schema_delivery, trace_pb2.SCHEMA_DELIVERY_CONSTRAINED)
```

Add `trace_pb2` to that file's `from berean.v1 import ...` line. `_answer` is called directly in the
unmapped-mode test because `Answer` converts a `ServeError` into a gRPC abort — the existing
`WhatItRefuses` class (line 209) uses the same approach, so follow whichever form it takes.

- [ ] **Step 4: Run them to verify they fail**

```bash
uv run --project services/catena python services/catena/tests/test_proto_contract.py -q
uv run --project services/catena python services/catena/tests/test_serve_service.py -q
```

Expected: FAIL — `_DELIVERY_MODES` does not exist and `trace.generation_provider` is empty.

- [ ] **Step 5: Teach `service.py` and the fake**

In `services/catena/src/catena/serve/service.py`, after `_FAILURE_CODES`, add:

```python
#: The short names the provider table uses, mapped to the contract's enum. Here
#: for the same reason `_FAILURE_CODES` is: `generate` imports no proto, so the
#: wire format is this layer's business and not the provider's.
_DELIVERY_MODES = {
    generate.CONSTRAINED: trace_pb2.SCHEMA_DELIVERY_CONSTRAINED,
    generate.SHAPED: trace_pb2.SCHEMA_DELIVERY_SHAPED,
    generate.UNCONSTRAINED: trace_pb2.SCHEMA_DELIVERY_UNCONSTRAINED,
}
```

In `_answer`, immediately before the `trace = trace_pb2.RetrievalTrace(` assignment, add:

```python
        delivery = _DELIVERY_MODES.get(self._generator.delivery)
        if delivery is None:
            # A programming error, not a provider's property: defaulting to
            # UNSPECIFIED would write a bug into the column the Phase 2 harness
            # groups by, and it would average cleanly.
            raise ServeError(
                f"the generator reports an unmapped delivery mode: {self._generator.delivery!r}"
            )
```

and inside the `RetrievalTrace(...)` call, after the `generation_model=(...)` argument:

```python
            # Read off the adapter rather than off the result, so a failed
            # attempt still names what attempted it and under what enforcement.
            generation_provider=self._generator.provider,
            schema_delivery=delivery,
```

In `services/catena/tests/fakes.py`, `FakeGenerator` (line 296) gains the two attributes the widened
protocol requires. Replace its `__init__` signature and the three assignments at the top of the
body:

```python
    def __init__(
        self,
        payload=None,
        error=None,
        model="fake-generator",
        provider="fake-provider",
        delivery="constrained",
    ) -> None:
        self.model = model
        #: The widened `Generator` protocol (ADR-0026). Present on the adapter
        #: rather than on `Generation`, so a failed attempt still names what
        #: attempted it.
        self.provider = provider
        self.delivery = delivery
        self._payload = payload if payload is not None else {}
        self._error = error
        self.messages = None
        self.schema = None
```

Its `generate` body is unchanged, except that the local import moves with the package:
`from catena.serve.generate import Generation`.

- [ ] **Step 6: Run every Python suite**

```bash
uv run --project services/catena python services/catena/tests/test_proto_contract.py -q
uv run --project services/catena python services/catena/tests/test_serve_service.py -q
make test-catena
make lint-py
```

Expected: PASS, `catena: OK`, `lint-py: OK`.

- [ ] **Step 7: Confirm the Go build still compiles against the widened trace**

Adding fields breaks no reader. This step is here because it is cheap and because Task 5 assumes it.

```bash
go build ./... && echo "go build: OK"
```

Expected: `go build: OK`.

- [ ] **Step 8: Commit**

```bash
git add proto/ gen/ services/catena/gen/ \
        services/catena/src/catena/serve/service.py \
        services/catena/tests/fakes.py \
        services/catena/tests/test_proto_contract.py \
        services/catena/tests/test_serve_service.py
git commit -m "The trace says which provider answered, and what it enforced

generation_model alone cannot tell two enforcement regimes apart, which becomes
live the moment a probe reclassifies a provider. The mode is an enum because it
is what the Phase 2 harness groups by; the provider is a string because it is an
identifier, like the model beside it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KkRvxYV6p3qJgScTp7if2b"
```

---

### Task 5: Go persists the attribution

The gateway writes the two new fields, refuses a trace that omits them, and shows them in the CLI's
trace output. `trace.traces` is the table the Phase 2 harness reads; a field that reaches the proto
and stops there attributes nothing.

**Files:**
- Create: `db/migrations/000008_generation_provider.up.sql`
- Create: `db/migrations/000008_generation_provider.down.sql`
- Modify: `services/gateway/internal/trace/store.go:222-232,392-403`
- Modify: `services/gateway/internal/render/trace.go:52-69`
- Modify: `services/gateway/internal/trace/store_test.go:167-180,229-300`
- Modify: `services/gateway/internal/trace/store_integration_test.go:105-120,235-258`
- Modify: `services/gateway/internal/render/trace_test.go:20-40,60,182`
- Modify: `tools/db/tests/gateway_assertions.sql:34-42,404-411`

**Interfaces:**
- Consumes: `RetrievalTrace.GetGenerationProvider()`, `RetrievalTrace.GetSchemaDelivery()` from
  Task 4.
- Produces:
  - `trace.traces.generation_provider text NOT NULL`
  - `trace.traces.schema_delivery trace.schema_delivery NOT NULL`
  - `trace.schema_delivery` enum — `'constrained'`, `'shaped'`, `'unconstrained'`

- [ ] **Step 1: Write the migration**

Create `db/migrations/000008_generation_provider.up.sql`:

```sql
-- Which provider answered, and what its request enforced of the answer schema.
--
-- ADR-0018 pinned the generator because "an unpinned generator makes the Phase 2
-- number unreproducible." Four providers do not break that, on the condition
-- that a run can be attributed: `generation_model` alone cannot tell two
-- enforcement regimes of one model apart, and that becomes live the moment a
-- probe reclassifies a provider (ADR-0026).
--
-- One migration, unlike 000006/000007. That pair was split because Postgres
-- forbids using a new enum *value* in the transaction that added it; creating a
-- type and using it in the same transaction is fine.
CREATE TYPE trace.schema_delivery AS ENUM (
    'constrained',
    'shaped',
    'unconstrained'
);

ALTER TABLE trace.traces
    ADD COLUMN generation_provider text,
    ADD COLUMN schema_delivery trace.schema_delivery;

-- Every row that already exists was written by the one provider this project
-- shipped before this migration, under the one mode that provider enforces.
-- Backfilling the fact is what lets these be NOT NULL without inventing history
-- the Phase 2 harness would go on to average.
UPDATE trace.traces
   SET generation_provider = 'ollama',
       schema_delivery = 'constrained'
 WHERE generation_provider IS NULL;

ALTER TABLE trace.traces
    ALTER COLUMN generation_provider SET NOT NULL,
    ALTER COLUMN schema_delivery SET NOT NULL,
    -- A provider of three spaces satisfies NOT NULL while recording exactly the
    -- unattributed run the column exists to prevent, which is why both sides
    -- trim.
    ADD CONSTRAINT traces_generation_provider_not_blank
        CHECK (btrim(generation_provider) <> '');

-- Re-asserted for the same reason every other grant in this schema is.
GRANT SELECT, INSERT, UPDATE, DELETE ON trace.traces TO gateway;

-- catena is granted nothing here and is never granted USAGE on this schema.
```

Create `db/migrations/000008_generation_provider.down.sql`:

```sql
-- Dropping the columns loses the attribution and nothing else: no row depends on
-- them, so unlike 000007 this rollback destroys no turns.
ALTER TABLE trace.traces
    DROP CONSTRAINT IF EXISTS traces_generation_provider_not_blank,
    DROP COLUMN IF EXISTS schema_delivery,
    DROP COLUMN IF EXISTS generation_provider;

DROP TYPE IF EXISTS trace.schema_delivery;
```

- [ ] **Step 2: Write the failing Go tests**

In `services/gateway/internal/trace/store_test.go`, add the two fields to the `retrievalTrace()`
fixture (line 167), after `GenerationModel`:

```go
		GenerationProvider: "probe-provider",
		SchemaDelivery:     bereanv1.SchemaDelivery_SCHEMA_DELIVERY_CONSTRAINED,
```

and add two cases to the table-driven refusal test (the slice at line 229), beside the
`generation_model` case:

```go
		{
			// A trace the harness cannot attribute is the same contract
			// violation as one that does not arrive: a hosted run must be
			// labelled, and an unlabelled one is indistinguishable from a
			// baseline run (SHARED §7, ADR-0026).
			name: "a retrieval trace naming no provider",
			breaks: func(t *turn.Turn) {
				t.Attempts[0].Trace.GenerationProvider = "   "
			},
			says: "generation_provider",
		},
		{
			// Defaulting an unset mode would write UNSPECIFIED into the column
			// the Phase 2 harness groups by, where it would average cleanly.
			name: "a retrieval trace reporting no schema delivery mode",
			breaks: func(t *turn.Turn) {
				t.Attempts[0].Trace.SchemaDelivery =
					bereanv1.SchemaDelivery_SCHEMA_DELIVERY_UNSPECIFIED
			},
			says: "schema_delivery",
		},
```

In `services/gateway/internal/trace/store_integration_test.go`, add the same two fields to
`probeTrace()` (line 105), and extend the read-back assertion (line 240) so the columns are checked
by a second connection rather than only written:

```go
	var (
		rewritten, embedding, generation, provider, delivery string
		dim, topK                                            int
		embedMS, searchMS, generateMS                        int64
		storedVerifyUS                                       int64
	)
	err := db.QueryRow(
		`SELECT rewritten_query, embedding_model, dim, generation_model, top_k,
		        generation_provider, schema_delivery,
		        embed_ms, search_ms, generate_ms, verify_us
		   FROM trace.traces WHERE request_id = $1 AND attempt = $2`, requestID, attempt).
		Scan(&rewritten, &embedding, &dim, &generation, &topK,
			&provider, &delivery,
			&embedMS, &searchMS, &generateMS, &storedVerifyUS)
	if err != nil {
		t.Fatalf("attempt %d trace: %v", attempt, err)
	}

	if provider != "probe-provider" || delivery != "constrained" {
		t.Errorf("attempt %d recorded generation_provider=%q schema_delivery=%q — a run the"+
			" harness cannot attribute is a run it cannot compare", attempt, provider, delivery)
	}
```

In `services/gateway/internal/render/trace_test.go`, add the two fields to each of the three
`RetrievalTrace` literals (lines 25, 60, 182):

```go
			GenerationProvider: "invented-provider",
			SchemaDelivery:     bereanv1.SchemaDelivery_SCHEMA_DELIVERY_SHAPED,
```

and extend the existing `TestTheTraceLogsEveryCandidateAndTheSettingsItRanUnder` (line 99) — the
test that already asserts the settings an attempt ran under — by adding the two values to its
`want` slice, beside `"invented-generator:1b"`:

```go
	for _, want := range []string{
		"invented-embedder",
		"invented-generator:1b",
		// Who answered and what the request enforced. A trace a reader cannot
		// attribute is one they cannot interpret, and the mode is what tells
		// two enforcement regimes of one model apart (ADR-0026).
		"invented-provider",
		"shaped",
		"0.8125",
		bindingID + " A 4.2",
		"below the retrieval depth",
	} {
```

That test renders through the file's own `work(t, regenerated())` helper (line 87), so no new
harness is needed — the three `RetrievalTrace` literals edited above are what feed it.

- [ ] **Step 3: Run the Go tests to verify they fail**

```bash
go test ./services/gateway/internal/trace/ ./services/gateway/internal/render/
```

Expected: compile failure — `unknown field GenerationProvider` is impossible (Task 4 generated it),
so expect the assertions to fail: `generation_provider=""`, `schema_delivery=""`, and the render
test reporting the two strings absent.

- [ ] **Step 4: Write the two columns in `store.go`**

In `writeAttempt` (line 214), before the `INSERT`, resolve the enum to its SQL literal the way
`writeResponse` resolves `confidence_level`:

```go
	delivery, err := enumValue("SCHEMA_DELIVERY_", trace.GetSchemaDelivery().String())
	if err != nil {
		return fmt.Errorf("trace %s attempt %d: schema_delivery: %w", requestID, attempt.Number, err)
	}
```

Then extend the statement and its arguments:

```go
	_, err = tx.ExecContext(ctx,
		`INSERT INTO trace.traces
		     (request_id, attempt, rewritten_query, embedding_model, dim,
		      generation_model, generation_provider, schema_delivery, top_k,
		      embed_ms, search_ms, generate_ms, verify_us)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)`,
		requestID, attempt.Number, trace.GetRewrittenQuery(), trace.GetEmbeddingModel(),
		trace.GetDim(), trace.GetGenerationModel(), trace.GetGenerationProvider(), delivery,
		trace.GetTopK(),
		timings.GetEmbedMs(), timings.GetSearchMs(), timings.GetGenerateMs(),
		attempt.Verify.Microseconds())
```

Note the `err` shadowing: the existing line declares `_, err := tx.ExecContext(...)`. With `err`
already declared by the `enumValue` call above, that becomes `_, err = tx.ExecContext(...)`.

- [ ] **Step 5: Refuse a trace that cannot be attributed**

In `validate` (line 392), add the provider to the required-non-blank loop:

```go
			{"rewritten_query", attempt.Trace.GetRewrittenQuery()},
			{"embedding_model", attempt.Trace.GetEmbeddingModel()},
			{"generation_model", attempt.Trace.GetGenerationModel()},
			{"generation_provider", attempt.Trace.GetGenerationProvider()},
```

and after that loop, add the mode check:

```go
		// The mode is what makes two runs of one model under different
		// enforcement distinguishable, so an unset one is a missing field
		// rather than a default. `enumValue` refuses UNSPECIFIED already;
		// wrapping it here names the column, because a message reading
		// "unset" sends whoever reads it to the wrong service.
		if _, err := enumValue(
			"SCHEMA_DELIVERY_", attempt.Trace.GetSchemaDelivery().String(),
		); err != nil {
			return fmt.Errorf("trace %s attempt %d: %w: catena's retrieval trace reports no"+
				" schema_delivery", t.RequestID, attempt.Number, ErrIncomplete)
		}
```

- [ ] **Step 6: Show them in the CLI trace**

In `services/gateway/internal/render/trace.go`, inside `settings` (line 52), after the
`generation_model` line:

```go
	out.indented("generation_model", trace.GetGenerationModel())
	// Who answered, and what the request enforced. A reader attributing a slow
	// or odd turn wants these beside the model, not derived from it.
	out.indented("generation_provider", trace.GetGenerationProvider())
	out.indented("schema_delivery", strings.ToLower(strings.TrimPrefix(
		trace.GetSchemaDelivery().String(), "SCHEMA_DELIVERY_")))
	out.indented("top_k", fmt.Sprint(trace.GetTopK()))
```

Add `"strings"` to that file's imports if it is not already there.

- [ ] **Step 7: Extend the SQL assertions**

In `tools/db/tests/gateway_assertions.sql`, update both `trace.traces` inserts (lines 34 and 404) to
carry the new columns, and add a refusal probe.

The well-formed insert at line 34 becomes:

```sql
INSERT INTO trace.traces
    (request_id, attempt, rewritten_query, embedding_model, dim,
     generation_model, generation_provider, schema_delivery, top_k,
     embed_ms, search_ms, generate_ms, verify_us)
VALUES
    ('00000000-0000-4000-8000-000000000001', 1, 'An invented question?',
     'probe-embedder', 1024, 'probe-generator:tag', 'probe-provider', 'constrained',
     20, 1, 2, 3, 4),
    ('00000000-0000-4000-8000-000000000001', 2, 'An invented question?',
     'probe-embedder', 1024, 'probe-generator:tag', 'probe-provider', 'constrained',
     20, 1, 2, 3, 4);
```

The negative-`verify_us` probe at line 404 gains the same two columns in the same positions.

Inside the `DO $$` block that holds the other refusal probes, add:

```sql
    -- A run the Phase 2 harness cannot attribute is a run it cannot compare,
    -- and a mode outside the three is a provider nobody probed (ADR-0026).
    BEGIN
        INSERT INTO trace.traces
            (request_id, attempt, rewritten_query, embedding_model, dim,
             generation_model, generation_provider, schema_delivery, top_k,
             embed_ms, search_ms, generate_ms, verify_us)
        VALUES ('00000000-0000-4000-8000-000000000001', 1, 'q',
                'probe-embedder', 1024, 'probe-generator:tag', '   ', 'constrained',
                20, 1, 2, 3, 4);
        RAISE EXCEPTION 'a blank generation_provider was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;

    BEGIN
        INSERT INTO trace.traces
            (request_id, attempt, rewritten_query, embedding_model, dim,
             generation_model, generation_provider, schema_delivery, top_k,
             embed_ms, search_ms, generate_ms, verify_us)
        VALUES ('00000000-0000-4000-8000-000000000001', 1, 'q',
                'probe-embedder', 1024, 'probe-generator:tag', 'probe-provider', 'invented-mode',
                20, 1, 2, 3, 4);
        RAISE EXCEPTION 'a schema_delivery outside the enum was accepted';
    EXCEPTION WHEN invalid_text_representation THEN NULL;
    END;
```

- [ ] **Step 8: Run the Go tests to verify they pass**

```bash
go build ./... && go test ./services/gateway/...
make test-gateway
```

Expected: `ok` for every package.

- [ ] **Step 9: Apply the migration and run the schema assertions**

This needs a live database, so it is the one step in the plan that requires `make dev`.

```bash
make dev
make migrate
make migrate-version
./tools/db/tests/test_schema.sh
make test-gateway-db
```

Expected: `make migrate-version` prints `8` and not `dirty`; `test_schema.sh` and
`test-gateway-db` pass.

- [ ] **Step 10: Verify the rollback, then reapply**

A down migration nobody ran is a down migration that does not work.

```bash
make migrate-down
make migrate-version   # expect 7
make migrate
make migrate-version   # expect 8
```

- [ ] **Step 11: Commit**

```bash
git add db/migrations/000008_generation_provider.up.sql \
        db/migrations/000008_generation_provider.down.sql \
        services/gateway/internal/trace/store.go \
        services/gateway/internal/trace/store_test.go \
        services/gateway/internal/trace/store_integration_test.go \
        services/gateway/internal/render/trace.go \
        services/gateway/internal/render/trace_test.go \
        tools/db/tests/gateway_assertions.sql
git commit -m "The gateway persists and shows the attribution

Two columns, and a trace that omits either is refused as incomplete rather than
stored unattributable. Existing rows are backfilled with the fact -- ollama,
constrained -- because that is what every one of them was.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KkRvxYV6p3qJgScTp7if2b"
```

---

### Task 6: The documents, and the claim that was written in three places

The design's finding: `services/catena/AGENTS.md` and SHARED §1 both say the OpenAI-compatible wire
format is what makes providers interchangeable. It is not — and that sentence was written when there
was one provider, so it had no way to be wrong yet. This task corrects it everywhere it appears and
records the decision.

**Files:**
- Create: `docs/adr/0026-the-generation-provider-layer.md`
- Modify: `docs/adr/README.md` (the 0018, 0023 and new 0026 rows)
- Modify: `specs/SHARED-TECHNICAL-SPEC.md:17-24,133-148`
- Modify: `services/catena/AGENTS.md:74-84`
- Modify: `docs/CORPUS-POLICY.md:113-126`
- Modify: `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md:337-365`
- Modify: `specs/001-phase-1-pca-baseline/PLAN.md:693-694,724-725`
- Modify: `specs/001-phase-1-pca-baseline/GENERATION-PROVIDERS-DESIGN.md` (the `openai` cell, open
  question 1, and Status)
- Modify: `.env.example`
- Modify: `compose.yaml:260-266`
- Modify: `README.md` (the cost table section)

**Interfaces:**
- Consumes: the provider table as implemented in Tasks 2–3, and the trace fields from Tasks 4–5.
- Produces: no code.

- [ ] **Step 1: Write ADR-0026**

Create `docs/adr/0026-the-generation-provider-layer.md`. It must carry, at minimum:

- The header block in the house form: `**Status:** Accepted`, `**Date:** 2026-09-30`, `**Phase:** 1
  — decided after the generation-failure channel landed, because two of the four providers need it`.
- **Context.** One provider existed, and the convention written around it said the wire format was
  what made providers interchangeable. The Anthropic Messages API is the counterexample: same
  protocol, different wire, vendor SDK. Three hosted counterparties rather than one changes the
  licence arithmetic ADR-0017 settled for the ESV.
- **Decision.** Four providers, one environment variable, the table reproduced in full including
  the `probed` column. One module per wire format, not per provider. Base URLs pinned. The typed
  `Generator` protocol is the interface.
- **The three delivery modes**, and the property that earns them: each fails into a channel that
  already exists (ADR-0024 for a shaped provider's wrong slots, ADR-0025 for an unconstrained
  provider's non-JSON). `GENERATION_FAILURE_CODE_NOT_JSON` is rarer than it looks and is not a
  DeepSeek-specific concession: acceptance measured it firing on the pinned local model.
- **What it amends.** ADR-0018: hosted is no longer rejected outright, and the pin now applies to
  the *default* — "re-decided at Phase 2 against the golden set" now has four candidates rather than
  one. ADR-0023: the derived schema is unchanged; its *enforcement* is now provider-dependent.
  ADR-0010: unchanged, and now also binds a vendor SDK's own retry loop to zero.
- **The two parameters that are decisions**: `thinking: {"type": "adaptive"}` sent explicitly, and
  `effort: "medium"` as a deliberate downgrade — both with the reasoning from the design.
- **The two plan decisions**, verbatim from this plan's "Two decisions the design left to the plan":
  `openai` ships `shaped`, and open question 1 is answered from documentation with the probe reduced
  to confirmation. Record the answer to question 1 as a finding: `output_config.format` accepts
  `$ref`/`$defs`, string enums and `additionalProperties: false`, and rejects only constructs the
  derived schema does not use.
- **The stated cost**: providers receive different prompts, so cross-provider quality comparison is
  confounded. The trace records the mode, so the confound is visible in the data rather than hidden
  in it.
- **What protects the Phase 2 baseline**: the default does not move, the trace attributes the run,
  and a hosted run is labelled but not quotable as the baseline.
- **Alternatives rejected**, all five from the design with their reasons: operator YAML, a module
  per provider, a generic base-URL-plus-key escape hatch, one generator parameterised by strategy
  objects, and refusing providers that cannot constrain decoding.

- [ ] **Step 2: Index it and annotate what it amends**

In `docs/adr/README.md`, append:

```markdown
| [0026](0026-the-generation-provider-layer.md) | The generation provider layer: four providers, one typed protocol | Accepted (amends 0018 and 0023) |
```

and amend two existing rows' Status cells:

```markdown
| [0018](0018-qwen3-8b-as-the-generation-default.md) | Qwen3-8B as the Phase 1 generation default | Accepted (provisional; amended by 0026 — the pin applies to the default, and hosted is no longer refused) |
| [0023](0023-the-decoding-constraint-is-derived-and-permissive.md) | The decoding constraint is derived, permissive, and unthinking | Accepted (amended by 0026 — the schema is unchanged; its enforcement is provider-dependent) |
```

- [ ] **Step 3: Correct SHARED §1 and add §7's attribution requirement**

In `specs/SHARED-TECHNICAL-SPEC.md`, replace the wire-format bullet (line 22) with:

```markdown
- The generation provider MUST sit behind a **typed interface** — the `Generator` protocol and the
  answer object it returns — so Ollama, vLLM, llama.cpp and hosted APIs are interchangeable. The
  OpenAI-compatible chat-completions shape is the lingua franca of the providers that speak it and
  is **not** what delivers interchangeability: the Anthropic Messages API is a different wire format
  behind the same protocol, and a vendor SDK in the request path is permitted where that is what the
  format costs (ADR-0026).
- A hosted generation provider MUST NOT be the default, MUST require a deployer-supplied key, and
  MUST fail loudly under egress-blocked operation rather than degrading quietly. Its base URL MUST
  be pinned in code, never read from the environment — an ambient variable must not be able to
  choose who receives retrieved corpus text.
```

and extend the steady-state egress bullet (line 17) so the exception list is accurate:

```markdown
- First run MAY fetch container images and model weights. **Steady-state operation MUST require no
  network egress**: once provisioned, the system runs fully offline, and any code path that reaches
  the public internet to answer a question is a defect. The ESV adapter and the hosted generation
  providers are the only exceptions; both are deployer-enabled, never default, and both send data to
  a third party only under a deployer's explicit configuration (ADR-0017, ADR-0026).
```

In §7, after the "A turn that produced no answer object…" bullet (line 141), add:

```markdown
- Every trace MUST attribute its run to a generation **provider** and a **schema-delivery mode**, not
  only to a model. Two runs of one model under different enforcement are otherwise
  indistinguishable in the tables the harness reads. A hosted-provider run is legitimate and MUST be
  labelled; it is **not** quotable as the baseline, which is the pinned local default (ADR-0018,
  ADR-0026).
```

- [ ] **Step 4: Correct `services/catena/AGENTS.md`**

Replace the generation bullet (lines 74–77) with:

```markdown
- Generation behind the **typed `Generator` protocol**, so Ollama, vLLM, llama.cpp and hosted APIs
  are interchangeable. Default to local so the acceptance test holds with no accounts. The wire
  format is *not* what delivers that — `generate/openai_chat.py` is a stdlib `urllib` POST and
  `generate/messages.py` is the Anthropic vendor SDK, behind one protocol (ADR-0026). Base URLs are
  pinned in the provider table and never read from the environment.
- **What a provider enforces of the schema varies; the schema does not.** Three modes —
  `constrained`, `shaped`, `unconstrained` — and each fails into a channel that already exists
  (ADR-0024, ADR-0025). The adapter puts the schema where its wire and mode require; `prompt.py`
  learns nothing about providers. The trace records the mode, because that is what tells two
  enforcement regimes of one model apart.
```

Replace the thinking bullet (lines 82–84) with:

```markdown
- **The model's narrative about its own reasoning is never read**: `reasoning` on the
  OpenAI-compatible wire, `thinking` blocks and a refusal's `stop_details.explanation` on the
  Messages API. None of them has a path into a return value, a trace or a log. *How* thinking is
  configured is per-provider and not a blanket rule — `reasoning_effort: "none"` is Qwen3's, where a
  schema-constrained probe spent its whole budget inside `reasoning` and returned nothing, while on
  `claude-sonnet-5-5` thinking is sent explicitly as `{"type": "adaptive"}` because thinking-off on
  that family can push reasoning into the visible text.
```

- [ ] **Step 5: Name the counterparty per provider in CORPUS-POLICY**

In `docs/CORPUS-POLICY.md`, after "The approach" section's "Never ship a key" paragraph (line 122),
add a new section:

```markdown
## Who receives corpus text — per generation provider

Verification check 4 runs in Go, **after** generation. So a hosted generation provider receives
retrieved corpus text *before* the gateway has ruled on whether that text may be served. ADR-0017
already settles the principle for the ESV — the deployer's key, the deployer's terms, and a project
that automates nothing around anyone's terms — and it applies unchanged here. What changes is
arithmetic: there are three hosted counterparties, not one, so the recipient is named per provider
rather than in prose. A deployer weighing a `local-only` corpus against a hosted generator should be
able to read who receives the text (ADR-0026).

| provider | who receives the retrieved passages | terms accepted by |
| --- | --- | --- |
| `ollama` *(default)* | nobody outside the deployment | — |
| `anthropic` | Anthropic | the deployer, by setting `ANTHROPIC_API_KEY` |
| `openai` | OpenAI | the deployer, by setting `OPENAI_API_KEY` |
| `deepseek` | DeepSeek | the deployer, by setting `DEEPSEEK_API_KEY` |

The default sends nothing anywhere, and `make dev-offline` proves it by blocking egress entirely.

**ESV and NIV remain unaffected under every configuration.** They are never ingested, are fetched at
render time in Go, and are therefore unable to appear in a Catena prompt at all — no provider
setting changes that.
```

- [ ] **Step 6: Update the Phase 1 specs**

In `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md`, the generation section (lines 337–365):

- Line 337: "The provider sits behind an OpenAI-compatible interface" becomes "The provider sits
  behind the typed `Generator` protocol, with one module per wire format (ADR-0026). Four providers
  ship; `ollama` is the default." Add the provider table.
- Lines 345–346: the claim that `response_format` "keeps the provider interchangeable" is the
  reversed one. Replace with the three delivery modes and the statement that the schema is unchanged
  under all three while enforcement varies.
- Line 360: retitle "**Thinking is disabled**" to "**Thinking is configured per provider**",
  keeping the Qwen3 measurement as the local default's case and adding the Messages API's adaptive
  setting and `effort: medium`.
- Add the two new trace fields wherever the section enumerates what the trace records.

In `specs/001-phase-1-pca-baseline/PLAN.md`, replace the acceptance item at lines 693–695 — the
`[x]` stays, because the item was delivered and only its rationale was misstated:

```markdown
- [x] Generation behind the typed `Generator` protocol, default Ollama running the pinned Qwen3-8B
      tag (ADR-0018). The protocol is what makes providers interchangeable, not the wire format —
      three providers speak OpenAI chat-completions over stdlib `urllib` and one speaks the
      Anthropic Messages API through its vendor SDK (ADR-0026). A test asserts the local constant
      matches `models.lock.yaml`, and one asserts each hosted default
```

and replace the finding at lines 724–727:

```markdown
- **The pinned generator thinks, and its thinking is unconstrained.** `reasoning_effort: "none"` is
  required for Qwen3, not tuning: with thinking on, a schema-constrained probe spent its whole
  budget inside `reasoning` and returned empty content. The field is also model introspection,
  which SHARED §4 forbids emitting — so nothing reads it. **This is Qwen3's mechanism and not a
  blanket rule:** on `claude-sonnet-5-5` thinking is sent explicitly as `{"type": "adaptive"}`,
  because omitting it there is not the same as leaving thinking on, and thinking-off on that family
  can push reasoning into the visible text (ADR-0026)
```

Also extend the trace item at line 699–700 so it names what the trace now records:

```markdown
- [x] `RetrievalTrace` populated including excluded candidates with reasons, plus
      `generation_model`, `generation_provider`, `schema_delivery` and the `top_k` actually used
```

- [ ] **Step 7: Update the design document with the plan's two decisions**

CLAUDE.md: "When you make a decision during implementation that the spec did not anticipate, update
the spec in the same change."

In `specs/001-phase-1-pca-baseline/GENERATION-PROVIDERS-DESIGN.md`:

- The `openai` row's "schema delivery" cell: `**probe decides**` becomes
  `**shaped** — probe may promote`.
- Open question 1: mark it answered from current documentation — `output_config.format` accepts
  `$ref`/`$defs`, string enums and `additionalProperties: false`, and rejects only constructs the
  derived schema does not use — leaving the live confirmation as the remaining work. The instruction
  for a negative answer stays.
- Open question 2: note that the layer ships `shaped` pending the probe, and why.
- The Status section: `Design approved. Plan to follow, after the failure channel lands.` becomes
  `Design approved. Failure channel landed. Plan: GENERATION-PROVIDERS-PLAN.md.`

- [ ] **Step 8: Update the operator-facing files**

In `.env.example`, after the "Models" section, add:

```
# ---------------------------------------------------------------------------
# Generation provider -- one variable, four providers (ADR-0026)
# ---------------------------------------------------------------------------
# `ollama` is the default and the Phase 2 baseline. It needs no account and no
# key, and `make dev-offline` proves the stack answers with egress blocked.
#
# The three hosted providers receive retrieved corpus text *before* verification
# check 4 has ruled on whether it may be served (ADR-0017). Read
# docs/CORPUS-POLICY.md, "Who receives corpus text", before setting one. A
# hosted run is legitimate and is labelled in the trace; it is not quotable as
# the Phase 2 baseline.
#
#   provider    key variable         default model        cost in/out per MTok
#   ollama      --                   qwen3:8b-q4_K_M      -- (local)
#   anthropic   ANTHROPIC_API_KEY    claude-sonnet-5-5    $2 / $10
#   openai      OPENAI_API_KEY       gpt-6-luna           $0.10 / $0.50
#   deepseek    DEEPSEEK_API_KEY     deepseek-flash       see the provider
CATENA_GENERATION_PROVIDER=ollama

# Optional. Applies *within* the selected provider and must name a model that
# provider serves. Unset means the provider's default above.
# CATENA_GENERATION_MODEL=

# Never committed with a value. A hosted provider fails at startup without its
# key, rather than at the first question (SHARED §10 for real secrets).
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
# DEEPSEEK_API_KEY=
```

In `compose.yaml`, inside the `catena` service's `environment` block (after `CATENA_MODELS_DIR`):

```yaml
      # The provider selection and the three keys. Empty by default and empty is
      # correct: `connect()` refuses a hosted provider whose key is unset, which
      # is a configuration error reported at startup rather than a stack that
      # comes up healthy and cannot answer.
      CATENA_GENERATION_PROVIDER: ${CATENA_GENERATION_PROVIDER:-ollama}
      CATENA_GENERATION_MODEL: ${CATENA_GENERATION_MODEL:-}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
      DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}
```

In `README.md`, after the "An answer takes minutes, not seconds" paragraph, add:

```markdown
**A GPU is not the only way out of that, and the alternative is one environment variable.** Four
generation providers ship; `CATENA_GENERATION_PROVIDER` picks one and `CATENA_GENERATION_MODEL`
optionally picks a model within it (ADR-0026).

| provider | key | default model | cost, in / out per MTok |
| --- | --- | --- | --- |
| `ollama` *(default)* | none | `qwen3:8b-q4_K_M` | — runs locally |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5-5` | $2 / $10 |
| `openai` | `OPENAI_API_KEY` | `gpt-6-luna` | $0.10 / $0.50 |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-flash` | see the provider's pricing |

Three things are worth knowing before setting one. The default needs **no account and no key**, and
`make dev-offline` proves the stack answers with egress blocked — that is the acceptance test, and
it does not move. A hosted provider **receives retrieved corpus text** before the gateway's fourth
verification check has ruled on whether that text may be served, so read
[docs/CORPUS-POLICY.md](docs/CORPUS-POLICY.md) — "Who receives corpus text" names the recipient per
provider. And a hosted run is legitimate and is labelled in the trace, but it is **not** the
quotable baseline: that is the pinned local default (ADR-0018).
```

- [ ] **Step 9: Verify every check, including the ones that read documentation**

`make guard-make-targets` fails when documentation names a make target with no rule, and this task
edited seven documents.

```bash
make check
```

Expected: `corpus-guard: OK`, `make-targets: OK`, proto freshness OK, `lint-go: OK`,
`lint-py: OK`, `catena: OK`, Go suites `ok`, `compose: OK`.

- [ ] **Step 10: Confirm the acceptance test still holds with no accounts**

The whole design rests on the default not moving. This is the assertion.

```bash
make dev-offline
docker compose -f compose.yaml -f compose.offline.yaml \
    run --rm gateway ask --profile pca "What does the Westminster Confession teach about assurance?"
```

Expected: a turn — an answer, a refusal, or a generation failure — with no key set anywhere, and the
trace naming `generation_provider: ollama` and `schema_delivery: constrained`. All three outcomes
exit 0; an *error* is a failure of this step.

- [ ] **Step 11: Commit**

```bash
git add docs/adr/0026-the-generation-provider-layer.md docs/adr/README.md \
        specs/SHARED-TECHNICAL-SPEC.md services/catena/AGENTS.md docs/CORPUS-POLICY.md \
        specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md \
        specs/001-phase-1-pca-baseline/PLAN.md \
        specs/001-phase-1-pca-baseline/GENERATION-PROVIDERS-DESIGN.md \
        .env.example compose.yaml README.md
git commit -m "The claim was written in three places, and it was wrong in all three

The wire format never made providers interchangeable -- the typed protocol does,
and the Messages API is the case that separates the two. SHARED §1, catena's
AGENTS.md and the Phase 1 specs said otherwise, which was harmless while there
was one provider and had no way to be wrong yet.

CORPUS-POLICY now names the recipient per provider rather than in prose: check 4
runs after generation, so a hosted provider sees retrieved text before the
gateway rules on it, and there are three counterparties now.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KkRvxYV6p3qJgScTp7if2b"
```

---

### Task 7 (optional, needs a deployer key): the two probes

**Neither probe blocks the layer** — that is the whole reason the failure channel landed first. Both
are one cheap call and both are recorded in ADR-0026 as findings. Do not run this task without the
user's explicit go-ahead: it spends money and it sends a prompt to a third party.

**Files:**
- Modify: `docs/adr/0026-the-generation-provider-layer.md` (the findings)
- Modify: `services/catena/src/catena/serve/generate/__init__.py` (`probed`, and `delivery` if a
  probe reclassifies)
- Modify: `services/catena/tests/test_serve_generate.py` (if a mode changes)
- Modify: `specs/001-phase-1-pca-baseline/GENERATION-PROVIDERS-DESIGN.md` (the open questions)

**Interfaces:**
- Consumes: the table from Tasks 2–3.
- Produces: a resolved `probed` flag per hosted provider, and possibly a changed `delivery`.

- [ ] **Step 1: Probe the Messages API's schema acceptance**

Confirms what Step 2 of "Two decisions" read from documentation. The prompt below carries no corpus
text (ADR-0014).

```bash
cd /Users/tim/projects/berean
ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" uv run --project services/catena python -c "
import sys, json
sys.path.insert(0, 'services/catena/src'); sys.path.insert(0, 'services/catena/gen')
from catena.serve import schema
from catena.serve.generate import messages
client = messages.build_client(__import__('os').environ['ANTHROPIC_API_KEY'], messages.BASE_URL, 120)
reply = client.messages.create(
    model='claude-sonnet-5-5', max_tokens=512,
    system='Answer with the JSON object only.',
    messages=[{'role': 'user', 'content': 'An invented question with no answer in any corpus.'}],
    thinking=dict(messages.THINKING),
    output_config={'effort': messages.EFFORT,
                   'format': {'type': 'json_schema', 'schema': schema.answer_schema()}},
)
print('stop_reason:', reply.stop_reason)
print('text parses as an object:', isinstance(json.loads(messages._text(reply)), dict))
"
```

Expected: no 400, `stop_reason: end_turn`, and `True`. If instead the API rejects the schema, the fix
is to inline the `$defs` at that adapter's edge — never to hand-write a second schema, and never to
relax ADR-0023 to suit a provider.

- [ ] **Step 2: Probe OpenAI's strict structured outputs**

This decides whether `openai` can be promoted from `shaped` to `constrained`.

```bash
OPENAI_API_KEY="$OPENAI_API_KEY" uv run --project services/catena python -c "
import json, os, sys, urllib.request, urllib.error
sys.path.insert(0, 'services/catena/src'); sys.path.insert(0, 'services/catena/gen')
from catena.serve import schema
body = json.dumps({
    'model': 'gpt-6-luna', 'max_tokens': 512,
    'messages': [{'role': 'system', 'content': 'Answer with the JSON object only.'},
                 {'role': 'user', 'content': 'An invented question with no answer in any corpus.'}],
    'response_format': {'type': 'json_schema', 'json_schema': {
        'name': 'answer_object', 'strict': True, 'schema': schema.answer_schema()}},
}).encode()
request = urllib.request.Request(
    'https://api.openai.com/v1/chat/completions', data=body, method='POST',
    headers={'Content-Type': 'application/json',
             'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY']})
try:
    with urllib.request.urlopen(request, timeout=120) as response:
        print('accepted strict with required: []')
        print(json.loads(response.read())['choices'][0]['finish_reason'])
except urllib.error.HTTPError as error:
    print('rejected:', error.code, error.read().decode('utf-8', 'replace')[:600])
"
```

Two outcomes, and both are actionable:
- **Accepted** — promote `PROVIDERS["openai"].delivery` to `CONSTRAINED`, set `probed=True`, update
  the shaped-mode test to cover a different provider, and amend ADR-0026 with the finding.
- **Rejected because strict mode requires every property in `required`** — `openai` stays `shaped`,
  `probed=True`, and ADR-0026 records the confirmed reason. ADR-0023 measured the all-required shape
  producing `position: "no_position"` beside empty `arguments`; the contract does not bend.

- [ ] **Step 3: Record the findings and set `probed`**

Whatever the two probes returned, set each hosted entry's `probed` flag to `True` and write the
finding into ADR-0026. An unprobed mode was never a blocker; a probed one that nobody recorded is
worse than either.

- [ ] **Step 4: Run the suites and commit**

```bash
make test-catena && make lint-py
git add services/catena/src/catena/serve/generate/__init__.py \
        services/catena/tests/test_serve_generate.py \
        docs/adr/0026-the-generation-provider-layer.md \
        specs/001-phase-1-pca-baseline/GENERATION-PROVIDERS-DESIGN.md
git commit -m "The probes answered, and the table says so

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KkRvxYV6p3qJgScTp7if2b"
```

---

## Spec coverage

Every section of the design, and where it lands.

| Design section | Task |
| --- | --- |
| "The seam is already right" — `service.py`, `prompt.py`, `schema.py`, `server.py`, proto untouched | 1–3 (no task modifies them except `service.py`'s trace fields in 4) |
| The claim written in three places | 6 |
| What ships — the three-module layout | 1 (split), 2 (`openai_chat`), 3 (`messages`) |
| The provider table — all four rows | 2 (three rows), 3 (`anthropic`) |
| `CATENA_GENERATION_PROVIDER` / `CATENA_GENERATION_MODEL` | 2 |
| Base URLs pinned, against an ambient `ANTHROPIC_BASE_URL` | 2 (`_base_url`), 3 (the SDK client) |
| Schema delivery: three modes | 2 |
| The adapter owns delivery, never `prompt.py` | 2 |
| `thinking` explicit, `effort` medium | 3 |
| Licence ordering, three counterparties | 6 (CORPUS-POLICY) |
| What protects the Phase 2 baseline — default, trace, labelling | 2 (default), 4–5 (trace), 6 (SHARED §7) |
| Open questions 1 and 2 | The plan's "Two decisions" (interim), 7 (probes) |
| Alternatives rejected | 6 (ADR-0026) |
| Testing: table, pin, modes, positive `thinking`, selection, failure mapping | 2 (table, pin, modes, selection), 3 (`thinking`, failure mapping) |
| Documents updated — all eight rows | 3 (pyproject), 6 (the other seven) |

Two things the design mentions that no task implements, stated so their absence is a decision:

- **`context_exhausted` stays unmapped.** The enum value exists from ADR-0025 and nothing emits it
  today. Emitting it would mean string-matching a provider's 400 body for a token-limit phrase, and
  the design's own test list names truncation, refusal and unparseable content — not this. A
  narrower signal is not worth a fragile match.
- **The Langfuse span still carries only the model.** SHARED §6 requires the model and `top_k` per
  response and the design's attribution requirement is §7's, which is the trace tables. Adding the
  provider to the observability span would change `observability.generation`'s signature for no
  requirement that asked.
