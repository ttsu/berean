"""Langfuse spans, and what happens when Langfuse is not there.

SHARED §6 requires instrumentation from Phase 1 rather than retrofitted: an
unmeasured Phase 1 baseline defeats the point of measuring Phase 3 against it,
and ADR-0009 picked Langfuse over LangSmith. Token counts per request are a
named requirement, so the generation observation carries `usage_details`.

**Observability never fails a request.** Langfuse is five containers, and a
request path that died because a trace could not be recorded would make the
observability stack a dependency of answering — which inverts what it is for.
So every entry point here degrades to a no-op.

**But it says so, once.** The first version of this module suppressed every
exception silently, and it was written against the v3 SDK — `Langfuse.start_span`
does not exist in v4. The result was a service that logged "langfuse on" at
startup and recorded nothing, and no test caught it because the unit suite only
ever exercised the no-op. Silent degradation and silent breakage are
indistinguishable to everyone except the person who eventually needs the data,
so a failure is reported to stderr the first time it happens and suppressed
after that. Never failing a request and never mentioning a problem are different
promises, and only the first one is worth making.

The v4 API this is written against, confirmed against Langfuse 4.15.2 and the
pinned 4.27.0 server:

    client.start_observation(name=..., as_type="span", input=...)
    span.start_observation(name=..., as_type="generation", model=..., input=...)
    observation.update(output=..., usage_details={"input": n, "output": n})
    observation.end()
    propagate_attributes(session_id=...)   # trace-level correlation

Nothing recorded here describes the model's reasoning. Observations carry
inputs, outputs, timings and token counts — what happened, never a narrative
about how (CLAUDE.md constraint 5).
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import Any, Iterator

HOST_ENV = "LANGFUSE_HOST"
PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"
SECRET_KEY_ENV = "LANGFUSE_SECRET_KEY"
DEFAULT_HOST = "http://langfuse-web:3000"


class _Reporter:
    """Reports the first failure of each kind, then goes quiet.

    A trace that cannot be recorded must not fail a request and must not fill
    the log with one line per turn — but it must be *findable*.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def report(self, what: str, error: BaseException) -> None:
        if what in self._seen:
            return
        self._seen.add(what)
        print(
            f"catena: langfuse {what} failed and tracing is degraded for this process: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr, flush=True,
        )


class NullObservability:
    """What the service uses when Langfuse is absent or unconfigured."""

    enabled = False

    @contextlib.contextmanager
    def request(self, **_: Any) -> Iterator["NullSpan"]:
        yield NullSpan()

    def flush(self) -> None:
        return None


class NullSpan:
    """Stands in for both the request span and the generation observation."""

    @contextlib.contextmanager
    def generation(self, **_: Any) -> Iterator["NullSpan"]:
        yield self

    def finish(self, **_: Any) -> None:
        return None


class LangfuseObservability:
    enabled = True

    def __init__(self, client) -> None:
        self._client = client
        self._reporter = _Reporter()

    @contextlib.contextmanager
    def request(self, *, request_id: str, query: str, attempt: int) -> Iterator[Any]:
        """One span per generation attempt, or a no-op that says why.

        Written out rather than wrapped in a guarding context manager: if
        `start_observation` raises inside one, the generator never reaches its
        `yield` and the caller gets a RuntimeError instead of a degraded trace —
        which would make observability fail the request after all.
        """
        from langfuse import propagate_attributes

        scope = None
        span = None
        try:
            # v4's way of putting trace-level fields on everything started
            # inside. `request_id` is what correlates this with the trace row Go
            # persists and with the response the user saw.
            scope = propagate_attributes(session_id=request_id or None)
            scope.__enter__()
            span = self._client.start_observation(
                name="catena.answer", as_type="span",
                input={"query": query, "attempt": attempt},
            )
        except Exception as error:
            self._reporter.report("span start", error)

        try:
            yield _Span(span, self._reporter) if span is not None else NullSpan()
        finally:
            if span is not None:
                try:
                    span.end()
                except Exception as error:
                    self._reporter.report("span end", error)
            if scope is not None:
                try:
                    scope.__exit__(None, None, None)
                except Exception as error:
                    self._reporter.report("scope exit", error)

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as error:
            self._reporter.report("flush", error)


class _Span:
    def __init__(self, span, reporter: _Reporter) -> None:
        self._span = span
        self._reporter = reporter

    @contextlib.contextmanager
    def generation(self, *, model: str, messages: Any) -> Iterator[Any]:
        observation = None
        try:
            observation = self._span.start_observation(
                name="generate", as_type="generation", model=model, input=messages,
            )
        except Exception as error:
            self._reporter.report("generation start", error)

        try:
            yield _Generation(observation, self._reporter) if observation is not None \
                else NullSpan()
        finally:
            if observation is not None:
                try:
                    observation.end()
                except Exception as error:
                    self._reporter.report("generation end", error)


class _Generation:
    def __init__(self, observation, reporter: _Reporter) -> None:
        self._observation = observation
        self._reporter = reporter

    def finish(self, *, output: Any = None, usage: dict[str, int] | None = None) -> None:
        """Token counts per request, which SHARED §6 names explicitly."""
        try:
            self._observation.update(output=output, usage_details=usage or {})
        except Exception as error:
            self._reporter.report("generation update", error)


def connect() -> Any:
    """Langfuse if it is configured and importable, a no-op otherwise."""
    if not (os.environ.get(PUBLIC_KEY_ENV) and os.environ.get(SECRET_KEY_ENV)):
        return NullObservability()
    try:
        from langfuse import Langfuse
    except ModuleNotFoundError:  # pragma: no cover - a broken image
        print("catena: langfuse is not installed; tracing is off", file=sys.stderr, flush=True)
        return NullObservability()
    try:
        return LangfuseObservability(Langfuse(
            public_key=os.environ[PUBLIC_KEY_ENV],
            secret_key=os.environ[SECRET_KEY_ENV],
            host=os.environ.get(HOST_ENV) or DEFAULT_HOST,
        ))
    except Exception as error:
        print(f"catena: langfuse would not start, tracing is off: {error}",
              file=sys.stderr, flush=True)
        return NullObservability()
