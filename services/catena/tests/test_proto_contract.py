"""The contract in `proto/` says what the specs say it says.

`buf breaking` is deferred to Phase 2 (ADR-0013), so until then nothing
mechanical stops a field being renamed or dropped. This suite is that guard,
narrowed to what the specs single out: the fields that are present-but-unused so
a later phase adds behaviour rather than breaks the contract, the fields that are
used from Phase 1 and easy to leave out by accident, and the enums whose whole
point is that their domain is closed.

It is not a second copy of the proto. Asserting every field would make every
addition a two-file edit and would guard nothing the proto does not already say.

The stubs are generated rather than committed, so this skips on a clean clone
until `make proto` has run.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GEN = REPO_ROOT / "services" / "catena" / "gen"

if GEN.is_dir() and str(GEN) not in sys.path:
    sys.path.insert(0, str(GEN))

try:
    from berean.v1 import answer_pb2, catena_pb2, common_pb2, filter_pb2
    from berean.v1 import trace_pb2, verification_pb2

    STUBS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only on a clean clone
    STUBS_AVAILABLE = False

skip_without_stubs = unittest.skipUnless(
    STUBS_AVAILABLE,
    "generated stubs are absent; run `make proto`",
)


def field_names(message) -> set[str]:
    return set(message.DESCRIPTOR.fields_by_name)


@skip_without_stubs
class TheOneCall(unittest.TestCase):
    def test_catena_exposes_exactly_one_rpc(self) -> None:
        """One gRPC call per generation attempt (ADR-0002, ADR-0010).

        A second RPC on this service is the seam moving, and it should be
        argued in an ADR rather than arriving with a feature.
        """
        methods = [m.name for m in catena_pb2.DESCRIPTOR.services_by_name["CatenaService"].methods]
        self.assertEqual(methods, ["Answer"])

    def test_answer_is_unary(self) -> None:
        method = catena_pb2.DESCRIPTOR.services_by_name["CatenaService"].methods_by_name["Answer"]
        self.assertFalse(method.client_streaming)
        self.assertFalse(
            method.server_streaming,
            "answers cannot stream before verification completes (SHARED, no token streaming)",
        )


@skip_without_stubs
class RequestCarriesWhatTheRetryNeeds(unittest.TestCase):
    def test_request_fields(self) -> None:
        self.assertEqual(
            field_names(catena_pb2.AnswerRequest),
            {
                "query",
                "conversation_context",
                "filter_spec",
                "contested_loci",
                "request_id",
                "previous_failures",
                "attempt",
            },
        )

    def test_previous_failures_reuses_the_verification_result(self) -> None:
        """ADR-0010 decided the retry carries the failure reasons back.

        Reusing the message Go already produces and persists is what keeps Go
        from composing prose about how to fix the answer.
        """
        field = catena_pb2.AnswerRequest.DESCRIPTOR.fields_by_name["previous_failures"]
        self.assertEqual(field.message_type.name, "VerificationResult")
        self.assertTrue(field.is_repeated)

    def test_contested_loci_are_a_sibling_of_the_filter_spec(self) -> None:
        """Retrieval policy and generation context are different things (ADR-0015)."""
        self.assertNotIn("contested_loci", field_names(filter_pb2.FilterSpec))
        locus = filter_pb2.ContestedLocus.DESCRIPTOR.fields_by_name
        self.assertEqual(set(locus), {"locus", "ruling"})
        self.assertEqual(
            locus["ruling"].message_type.name,
            "CitationRef",
            "the request carries a pointer to the ruling, never its prose",
        )

    def test_filter_spec_carries_no_identity(self) -> None:
        """Python serves a search policy, not an identity.

        The gateway has a unit test of its own for this once the profile
        resolves (Task 6); here it is a property of the contract, which is
        where it is cheapest to keep true.
        """
        self.assertEqual(field_names(filter_pb2.FilterSpec), {"corpora", "tier_weights", "top_k"})


@skip_without_stubs
class TheAnswerObject(unittest.TestCase):
    def test_answer_object_fields(self) -> None:
        self.assertEqual(
            field_names(answer_pb2.AnswerObject),
            {
                "position",
                "arguments",
                "descriptions",
                "contrary_positions",
                "contested",
                "no_answer_reason",
                "confidence",
            },
        )

    def test_descriptions_exist_so_the_excluded_tier_has_somewhere_to_live(self) -> None:
        """ADR-0016: affirmative claims are a slot, not a category."""
        self.assertEqual(
            field_names(answer_pb2.Description), {"subject", "content", "citations"}
        )

    def test_contested_fields(self) -> None:
        self.assertEqual(
            field_names(answer_pb2.Contested),
            {"is_contested", "locus", "citations", "state_of_debate"},
        )

    def test_citation_carries_its_tier_and_its_quote(self) -> None:
        self.assertEqual(
            field_names(answer_pb2.Citation), {"corpus_id", "locator", "tier", "quote"}
        )

    def test_confidence_has_both_halves_go_derives(self) -> None:
        """Python populates neither; Go overwrites both (ADR-0020)."""
        self.assertEqual(field_names(answer_pb2.Confidence), {"level", "reason"})

    def test_there_is_no_field_for_the_model_reasoning_about_itself(self) -> None:
        """SHARED section 4, ADR-0003.

        Named fields rather than a pattern match: this is a rule about what may
        be added, and the test's job is to make adding one a deliberate act
        that deletes a line here.
        """
        forbidden = {"reasoning", "thought", "thoughts", "chain_of_thought", "rationale",
                     "self_assessment", "explanation", "introspection"}
        for module in (answer_pb2, catena_pb2, trace_pb2):
            for name, message in module.DESCRIPTOR.message_types_by_name.items():
                with self.subTest(f"{module.DESCRIPTOR.name}:{name}"):
                    self.assertEqual(
                        forbidden & set(message.fields_by_name),
                        set(),
                        "the system explains provenance and argument, never how the "
                        "model arrived at either",
                    )


@skip_without_stubs
class TheTrace(unittest.TestCase):
    def test_trace_records_the_two_settings_that_move_the_phase_2_baseline(self) -> None:
        """A number nobody logged cannot be held constant across a comparison."""
        fields = field_names(trace_pb2.RetrievalTrace)
        self.assertIn("generation_model", fields)
        self.assertIn("top_k", fields)

    def test_trace_fields(self) -> None:
        self.assertEqual(
            field_names(trace_pb2.RetrievalTrace),
            {
                "rewritten_query",
                "candidates",
                "embedding_model",
                "dim",
                "generation_model",
                "top_k",
                "timings",
            },
        )

    def test_every_candidate_records_whether_it_was_used(self) -> None:
        self.assertEqual(
            field_names(trace_pb2.Candidate),
            {"corpus_id", "locator", "score", "included", "exclusion_reason"},
        )


@skip_without_stubs
class TheVerificationResult(unittest.TestCase):
    def test_one_field_per_check(self) -> None:
        self.assertEqual(
            field_names(verification_pb2.VerificationResult),
            {
                "citation_ref",
                "locator_resolved",
                "quote_matched",
                "tier_permitted",
                "license_permitted",
                "failure_detail",
            },
        )


@skip_without_stubs
class ClosedEnums(unittest.TestCase):
    """A closed domain is the whole point of each of these.

    A tier that is not one of the five, or an outcome that is not one of the
    three, is a value nothing downstream knows how to render or count.
    """

    def test_tiers(self) -> None:
        self.assertEqual(
            set(common_pb2.Tier.keys()),
            {
                "TIER_UNSPECIFIED",
                "TIER_BINDING",
                "TIER_GOVERNING",
                "TIER_ADVISORY",
                "TIER_CONTRARY",
                "TIER_EXCLUDED",
            },
        )

    def test_overall_results(self) -> None:
        self.assertEqual(
            set(verification_pb2.OverallResult.keys()),
            {
                "OVERALL_RESULT_UNSPECIFIED",
                "OVERALL_RESULT_VERIFIED",
                "OVERALL_RESULT_REGENERATED",
                "OVERALL_RESULT_DEGRADED",
            },
        )

    def test_confidence_levels(self) -> None:
        self.assertEqual(
            set(answer_pb2.ConfidenceLevel.keys()),
            {
                "CONFIDENCE_LEVEL_UNSPECIFIED",
                "CONFIDENCE_LEVEL_HIGH",
                "CONFIDENCE_LEVEL_MEDIUM",
                "CONFIDENCE_LEVEL_LOW",
            },
        )


@skip_without_stubs
class DeferredFields(unittest.TestCase):
    """Present-but-unused in Phase 1, so a later phase adds behaviour rather
    than breaking the contract. Do not remove them because they are unused."""

    def test_conversation_context_is_present(self) -> None:
        self.assertIn("conversation_context", field_names(catena_pb2.AnswerRequest))

    def test_tier_weights_are_present(self) -> None:
        self.assertIn("tier_weights", field_names(filter_pb2.FilterSpec))

    def test_rewritten_query_is_present(self) -> None:
        self.assertIn("rewritten_query", field_names(trace_pb2.RetrievalTrace))


if __name__ == "__main__":
    unittest.main()
