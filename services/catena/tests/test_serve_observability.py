"""Tracing records what SHARED §6 asks for, and never fails a request.

This suite exists because the first version of this module did neither. It was
written against the Langfuse v3 API — `Langfuse.start_span`, which v4 removed —
suppressed the resulting AttributeError, and reported "langfuse on" at startup
while recording nothing. The unit suite passed, because it only ever exercised
the no-op.

So these assert against a double shaped like the **v4** client, and they assert
the degradation behaviour explicitly: a client that raises must still let the
request through, and must say so once.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr

from catena.serve import observability


class FakeObservation:
    def __init__(self, name, kind, model=None, payload=None) -> None:
        self.name = name
        self.kind = kind
        self.model = model
        self.input = payload
        self.output = None
        self.usage = None
        self.ended = False
        self.children: list["FakeObservation"] = []

    def start_observation(self, *, name, as_type, model=None, input=None):
        child = FakeObservation(name, as_type, model, input)
        self.children.append(child)
        return child

    def update(self, *, output=None, usage_details=None):
        self.output = output
        self.usage = usage_details

    def end(self):
        self.ended = True


class FakeClient:
    """Shaped like the v4 client: `start_observation`, not `start_span`."""

    def __init__(self, explode: bool = False) -> None:
        self.explode = explode
        self.observations: list[FakeObservation] = []
        self.flushed = False

    def start_observation(self, *, name, as_type, input=None):
        if self.explode:
            raise AttributeError("'Langfuse' object has no attribute 'start_observation'")
        observation = FakeObservation(name, as_type, payload=input)
        self.observations.append(observation)
        return observation

    def flush(self):
        self.flushed = True


class WhatItRecords(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.traces = observability.LangfuseObservability(self.client)

    def _run(self):
        with self.traces.request(request_id="req-1", query="q", attempt=1) as span:
            with span.generation(model="qwen3:8b-q4_K_M", messages=[{"role": "user"}]) as gen:
                gen.finish(output={"position": "p"}, usage={"input": 100, "output": 50})

    def test_opens_one_span_per_generation_attempt(self) -> None:
        self._run()
        self.assertEqual(len(self.client.observations), 1)
        self.assertEqual(self.client.observations[0].name, "catena.answer")
        self.assertEqual(self.client.observations[0].kind, "span")

    def test_records_the_generation_beneath_it(self) -> None:
        self._run()
        generation = self.client.observations[0].children[0]
        self.assertEqual(generation.kind, "generation")
        self.assertEqual(generation.model, "qwen3:8b-q4_K_M")

    def test_records_token_counts(self) -> None:
        """SHARED §6 names token count per request explicitly."""
        self._run()
        self.assertEqual(
            self.client.observations[0].children[0].usage, {"input": 100, "output": 50})

    def test_ends_every_observation(self) -> None:
        """An observation left open never arrives."""
        self._run()
        span = self.client.observations[0]
        self.assertTrue(span.ended)
        self.assertTrue(span.children[0].ended)

    def test_carries_the_attempt_so_a_regeneration_is_distinguishable(self) -> None:
        """ADR-0010: a regeneration must not hide a rising fabrication rate."""
        with self.traces.request(request_id="req-1", query="q", attempt=2):
            pass
        self.assertEqual(self.client.observations[0].input["attempt"], 2)


class WhenLangfuseIsBroken(unittest.TestCase):
    def test_the_request_still_runs(self) -> None:
        """The exact failure that shipped: a v3 call against a v4 client."""
        traces = observability.LangfuseObservability(FakeClient(explode=True))
        with redirect_stderr(io.StringIO()):
            with traces.request(request_id="r", query="q", attempt=1) as span:
                with span.generation(model="m", messages=[]) as gen:
                    gen.finish(output={}, usage={"input": 1, "output": 1})

    def test_it_says_so_once(self) -> None:
        """Never failing a request and never mentioning a problem are different promises."""
        traces = observability.LangfuseObservability(FakeClient(explode=True))
        captured = io.StringIO()
        with redirect_stderr(captured):
            for _ in range(3):
                with traces.request(request_id="r", query="q", attempt=1):
                    pass
        lines = [line for line in captured.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn("tracing is degraded", lines[0])


class WhenLangfuseIsUnconfigured(unittest.TestCase):
    def test_connect_returns_a_no_op(self) -> None:
        import os

        saved = {k: os.environ.pop(k, None)
                 for k in (observability.PUBLIC_KEY_ENV, observability.SECRET_KEY_ENV)}
        try:
            traces = observability.connect()
            self.assertFalse(traces.enabled)
            with traces.request(request_id="r", query="q", attempt=1) as span:
                with span.generation(model="m", messages=[]) as gen:
                    gen.finish(output={}, usage={})
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
