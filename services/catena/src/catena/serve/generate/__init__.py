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
