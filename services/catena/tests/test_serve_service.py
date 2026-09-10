"""`Answer`, end to end, against fakes. No database, no model, no network.

The interesting assertions here are about restraint: what this service records
faithfully, and what it deliberately does NOT repair before handing it to the
trust boundary.

Invented text throughout (ADR-0014).
"""

from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import grpc  # noqa: E402
from berean.v1 import catena_pb2, common_pb2  # noqa: E402
from catena.serve import retrieval  # noqa: E402
from catena.serve.observability import NullObservability  # noqa: E402
from catena.serve.service import CatenaService  # noqa: E402
from fakes import FakeCorpusReader, FakeEmbedder, FakeGenerator  # noqa: E402

QUOTE = "The council of Vethmoor declared that every mariner shall keep the third watch."


def hit(chunk_id=1, corpus_id="aaa-1111-alpha", locator="AAA 1.1", score=0.8, text=QUOTE):
    return retrieval.Hit(chunk_id=chunk_id, corpus_id=corpus_id, locator=locator,
                         text=text, work="The Vethmoor Articles", score=score)


def request(**overrides) -> catena_pb2.AnswerRequest:
    req = catena_pb2.AnswerRequest(
        query=overrides.pop("query", "What does Vethmoor require of mariners?"),
        request_id=overrides.pop("request_id", "req-1"),
        attempt=overrides.pop("attempt", 1),
    )
    req.filter_spec.top_k = overrides.pop("top_k", 20)
    for corpus_id, tier in overrides.pop(
        "corpora", [("aaa-1111-alpha", common_pb2.TIER_BINDING)]
    ):
        req.filter_spec.corpora.add(corpus_id=corpus_id, tier=tier)
    for locus, corpus_id, locator in overrides.pop("loci", []):
        entry = req.contested_loci.add(locus=locus)
        entry.ruling.corpus_id = corpus_id
        entry.ruling.locator = locator
    assert not overrides, overrides
    return req


ANSWER = {
    "position": "Vethmoor requires the third watch of every mariner.",
    "arguments": [{
        "claim": "Every mariner keeps the third watch.",
        "warrant": "The council legislated it directly.",
        "citations": [{"corpus_id": "aaa-1111-alpha", "locator": "AAA 1.1",
                       "tier": "TIER_BINDING", "quote": QUOTE}],
    }],
}


class Context:
    """Enough of a gRPC context to record an abort."""

    def __init__(self) -> None:
        self.code = None
        self.detail = None

    def abort(self, code, detail):
        self.code = code
        self.detail = detail
        raise Aborted(detail)


class Aborted(Exception):
    pass


def service(reader=None, generator=None, embedder=None) -> CatenaService:
    return CatenaService(
        embedder or FakeEmbedder(dim=8),
        generator or FakeGenerator(ANSWER),
        reader or FakeCorpusReader([hit()]),
        NullObservability(),
    )


class TheAnswerItReturns(unittest.TestCase):
    def test_carries_the_parsed_answer_object(self) -> None:
        response = service().Answer(request(), Context())
        self.assertEqual(response.answer.arguments[0].citations[0].locator, "AAA 1.1")
        self.assertEqual(
            response.answer.arguments[0].citations[0].tier, common_pb2.TIER_BINDING)

    def test_never_populates_confidence(self) -> None:
        """Go derives both halves and overwrites whatever arrives (ADR-0020)."""
        response = service().Answer(request(), Context())
        self.assertEqual(response.answer.confidence.level,
                         common_pb2.CONFIDENCE_LEVEL_UNSPECIFIED
                         if hasattr(common_pb2, "CONFIDENCE_LEVEL_UNSPECIFIED") else 0)
        self.assertEqual(response.answer.confidence.reason, "")

    def test_a_confidence_key_in_the_payload_is_a_parse_failure(self) -> None:
        """The schema forbids it; arriving anyway means the schema is wrong.

        Failing loudly beats scrubbing it, which would hide a defect in the
        derivation behind a silently correct answer.
        """
        payload = dict(ANSWER, confidence={"level": "CONFIDENCE_LEVEL_HIGH"})
        context = Context()
        with self.assertRaises(Aborted):
            service(generator=FakeGenerator(payload)).Answer(request(), context)
        self.assertEqual(context.code, grpc.StatusCode.INTERNAL)


class WhatItRefusesToRepair(unittest.TestCase):
    def test_arguments_beside_a_contested_flag_are_passed_through(self) -> None:
        """ADR-0019 routes this badly *on purpose* — it fails loudly in Go.

        Repairing it here would make the check unfireable and the rate
        unmeasurable, and Phase 2 needs that rate. PLAN Task 7 calls the
        resulting regeneration the intended direction.
        """
        payload = dict(ANSWER, contested={
            "is_contested": True, "locus": "creation-days",
            "state_of_debate": "The court left it open.",
        })
        response = service(generator=FakeGenerator(payload)).Answer(request(), Context())
        self.assertTrue(response.answer.contested.is_contested)
        self.assertEqual(len(response.answer.arguments), 1)

    def test_a_locus_that_was_never_sent_is_passed_through(self) -> None:
        payload = {"contested": {"is_contested": True, "locus": "invented-locus"}}
        response = service(generator=FakeGenerator(payload)).Answer(request(), Context())
        self.assertEqual(response.answer.contested.locus, "invented-locus")


class TheTrace(unittest.TestCase):
    def test_records_the_top_k_actually_used(self) -> None:
        response = service().Answer(request(top_k=7), Context())
        self.assertEqual(response.trace.top_k, 7)

    def test_falls_back_to_the_documented_default_when_none_was_sent(self) -> None:
        """A zero would retrieve nothing and read as an empty corpus."""
        response = service().Answer(request(top_k=0), Context())
        self.assertEqual(response.trace.top_k, 20)

    def test_records_both_model_identifiers(self) -> None:
        """The two settings most likely to move the Phase 2 baseline silently."""
        response = service().Answer(request(), Context())
        self.assertEqual(response.trace.generation_model, "fake-generator")
        self.assertEqual(response.trace.embedding_model, "fake-embedder")
        self.assertEqual(response.trace.dim, 8)

    def test_rewritten_query_is_the_query_in_phase_1(self) -> None:
        response = service().Answer(request(query="A question."), Context())
        self.assertEqual(response.trace.rewritten_query, "A question.")

    def test_records_every_candidate_including_the_excluded(self) -> None:
        reader = FakeCorpusReader([hit(1, score=0.9), hit(2, locator="AAA 1.2", score=0.1)])
        response = service(reader=reader).Answer(request(), Context())
        self.assertEqual(len(response.trace.candidates), 2)
        self.assertTrue(all(c.included for c in response.trace.candidates))

    def test_carries_a_timing_per_stage(self) -> None:
        response = service().Answer(request(), Context())
        for value in (response.trace.timings.embed_ms, response.trace.timings.search_ms,
                      response.trace.timings.generate_ms):
            self.assertGreaterEqual(value, 0)


class Retrieval(unittest.TestCase):
    def test_constrains_the_embedding_model(self) -> None:
        """One HNSW index spans every model; without this a re-index trades recall."""
        reader = FakeCorpusReader([hit()])
        service(reader=reader).Answer(request(), Context())
        self.assertEqual(reader.searches[0][2], "fake-embedder")

    def test_filters_to_the_corpora_in_the_filter_spec(self) -> None:
        reader = FakeCorpusReader([hit()])
        service(reader=reader).Answer(
            request(corpora=[("aaa-1111-alpha", common_pb2.TIER_BINDING),
                             ("bbb-2222-beta", common_pb2.TIER_ADVISORY)]), Context())
        self.assertEqual(reader.searches[0][0], ("aaa-1111-alpha", "bbb-2222-beta"))


class ContestedRulings(unittest.TestCase):
    def test_resolves_a_sent_locus_pointer_through_retrieval(self) -> None:
        """Go sends a pointer and never the prose (ADR-0015)."""
        ruling = hit(9, corpus_id="ccc-3333-gamma", locator="GG 2", score=0.02,
                     text="The court declined to bind the conscience of its members here.")
        reader = FakeCorpusReader([hit()], {("ccc-3333-gamma", "GG 2"): ruling})
        response = service(reader=reader).Answer(
            request(corpora=[("aaa-1111-alpha", common_pb2.TIER_BINDING),
                             ("ccc-3333-gamma", common_pb2.TIER_ADVISORY)],
                    loci=[("creation-days", "ccc-3333-gamma", "GG 2")]), Context())
        self.assertEqual(reader.locator_lookups, [("ccc-3333-gamma", "GG 2", "fake-embedder")])
        self.assertIn("GG 2", [c.locator for c in response.trace.candidates])

    def test_a_ruling_that_does_not_resolve_is_dropped_not_fatal(self) -> None:
        """Go's profile load is what refuses an un-ingested ruling, honestly."""
        reader = FakeCorpusReader([hit()], {})
        response = service(reader=reader).Answer(
            request(loci=[("creation-days", "ccc-3333-gamma", "GG 2")]), Context())
        self.assertEqual(len(response.trace.candidates), 1)


class WhatItRefuses(unittest.TestCase):
    def test_an_attempt_other_than_one_or_two(self) -> None:
        """ADR-0010 fixes the retry at exactly one regeneration."""
        context = Context()
        with self.assertRaises(Aborted):
            service().Answer(request(attempt=3), context)
        self.assertIn("ADR-0010", context.detail)

    def test_a_filter_spec_naming_no_corpora(self) -> None:
        context = Context()
        with self.assertRaises(Aborted):
            service().Answer(request(corpora=[]), context)
        self.assertIn("no corpora", context.detail)

    def test_a_generator_failure_becomes_an_rpc_error_not_a_degraded_answer(self) -> None:
        """Degradation is the trust boundary's decision, made after verification."""
        from catena.serve import ServeError

        context = Context()
        with self.assertRaises(Aborted):
            service(generator=FakeGenerator(error=ServeError("ollama is unreachable"))
                    ).Answer(request(), context)
        self.assertEqual(context.code, grpc.StatusCode.INTERNAL)


class PreviousFailures(unittest.TestCase):
    def test_reach_the_prompt_on_a_regeneration(self) -> None:
        req = request(attempt=2)
        failure = req.previous_failures.add(
            locator_resolved=True, quote_matched=False, tier_permitted=True,
            license_permitted=True, failure_detail="quote not found in chunk")
        failure.citation_ref.corpus_id = "aaa-1111-alpha"
        failure.citation_ref.locator = "AAA 1.1"

        generator = FakeGenerator(ANSWER)
        service(generator=generator).Answer(req, Context())
        user = generator.messages[1]["content"]
        self.assertIn("quote not found in chunk", user)
        self.assertIn("attempt 2", user)


if __name__ == "__main__":
    unittest.main()
