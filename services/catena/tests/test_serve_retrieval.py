"""Selection: what fits, what is pinned, and what the trace records either way.

The SQL lives in `catena.serve.postgres` and is asserted against a live
database by `make test-catena-db`, on the `test-ingest-db` precedent. What is
here is the policy — which is where the decisions are.

Invented text throughout (ADR-0014).
"""

from __future__ import annotations

import unittest

from berean.v1 import common_pb2, filter_pb2
from catena.serve import retrieval


def spec(*pairs) -> filter_pb2.FilterSpec:
    out = filter_pb2.FilterSpec(top_k=20)
    for corpus_id, tier in pairs or (("aaa-1111-alpha", common_pb2.TIER_BINDING),):
        out.corpora.add(corpus_id=corpus_id, tier=tier)
    return out


def hit(chunk_id: int, score: float, *, chars: int = 100,
        corpus_id: str = "aaa-1111-alpha", locator: str | None = None) -> retrieval.Hit:
    return retrieval.Hit(
        chunk_id=chunk_id, corpus_id=corpus_id,
        locator=locator or f"AAA {chunk_id}", text="w" * chars,
        work="The Vethmoor Articles", score=score,
    )


class Ordering(unittest.TestCase):
    def test_highest_score_first(self) -> None:
        selection = retrieval.select(
            [hit(1, 0.3), hit(2, 0.9), hit(3, 0.6)], spec(), budget_chars=10_000)
        self.assertEqual([p.chunk_id for p in selection.passages], [2, 3, 1])

    def test_tier_is_joined_from_the_filter_spec_not_the_corpus(self) -> None:
        """Tier is a per-tradition stance; the same chunk is binding or contrary."""
        selection = retrieval.select(
            [hit(1, 0.9, corpus_id="bbb-2222-beta")],
            spec(("bbb-2222-beta", common_pb2.TIER_CONTRARY)), budget_chars=10_000)
        self.assertEqual(selection.passages[0].tier, common_pb2.TIER_CONTRARY)


class TheContextBudget(unittest.TestCase):
    def test_drops_the_lowest_scoring_candidates_that_do_not_fit(self) -> None:
        selection = retrieval.select(
            [hit(1, 0.9, chars=100), hit(2, 0.5, chars=100), hit(3, 0.1, chars=100)],
            spec(), budget_chars=250)
        self.assertEqual([p.chunk_id for p in selection.passages], [1, 2])

    def test_records_every_dropped_candidate_with_its_reason(self) -> None:
        """A trace showing only what survived would hide the drop entirely."""
        selection = retrieval.select(
            [hit(1, 0.9, chars=100), hit(2, 0.1, chars=100)],
            spec(), budget_chars=150)
        dropped = [c for c in selection.candidates if not c["included"]]
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["exclusion_reason"], "context budget")
        self.assertEqual(dropped[0]["locator"], "AAA 2")

    def test_an_excluded_candidate_keeps_its_real_score(self) -> None:
        selection = retrieval.select(
            [hit(1, 0.9, chars=100), hit(2, 0.125, chars=100)],
            spec(), budget_chars=150)
        dropped = [c for c in selection.candidates if not c["included"]][0]
        self.assertAlmostEqual(dropped["score"], 0.125)

    def test_a_passage_is_excluded_whole_never_truncated(self) -> None:
        """Half a passage invites a quote across the cut, which fails check 2."""
        selection = retrieval.select([hit(1, 0.9, chars=500)], spec(), budget_chars=100)
        self.assertEqual(selection.passages, ())
        self.assertFalse(selection.candidates[0]["included"])


class PinnedRulings(unittest.TestCase):
    def test_a_pinned_hit_survives_a_budget_that_excludes_everything(self) -> None:
        """state_of_debate must quote the ruling, so dropping it guarantees ADR-0019's failure."""
        ruling = hit(9, 0.05, chars=400, locator="GG 2")
        selection = retrieval.select(
            [hit(1, 0.9, chars=400)], spec(), pinned=[ruling], budget_chars=100)
        self.assertIn(9, [p.chunk_id for p in selection.passages])

    def test_a_pinned_hit_leads_regardless_of_score(self) -> None:
        ruling = hit(9, 0.05, locator="GG 2")
        selection = retrieval.select(
            [hit(1, 0.9)], spec(), pinned=[ruling], budget_chars=10_000)
        self.assertEqual(selection.passages[0].chunk_id, 9)

    def test_a_pinned_hit_keeps_its_real_similarity_score(self) -> None:
        """The trace is an audit log; a fabricated score is worse than an honest low one."""
        ruling = hit(9, 0.05, locator="GG 2")
        selection = retrieval.select(
            [hit(1, 0.9)], spec(), pinned=[ruling], budget_chars=10_000)
        pinned = [c for c in selection.candidates if c["locator"] == "GG 2"][0]
        self.assertAlmostEqual(pinned["score"], 0.05)

    def test_a_ruling_also_retrieved_by_similarity_appears_once(self) -> None:
        ruling = hit(1, 0.9)
        selection = retrieval.select(
            [hit(1, 0.9)], spec(), pinned=[ruling], budget_chars=10_000)
        self.assertEqual(len(selection.passages), 1)
        self.assertEqual(len(selection.candidates), 1)


class ACorpusOutsideTheFilterSpec(unittest.TestCase):
    def test_is_excluded_and_recorded(self) -> None:
        """Go fails a citation to an unsent corpus, so showing it only invites one."""
        selection = retrieval.select(
            [hit(1, 0.9, corpus_id="zzz-9999-omega")], spec(), budget_chars=10_000)
        self.assertEqual(selection.passages, ())
        self.assertEqual(
            selection.candidates[0]["exclusion_reason"], "corpus not in the filter spec")


class TheBudgetItself(unittest.TestCase):
    def test_derives_from_the_configured_context_window(self) -> None:
        smaller = retrieval.passage_budget_chars(context_tokens=8192)
        larger = retrieval.passage_budget_chars(context_tokens=16384)
        self.assertLess(smaller, larger)

    def test_a_window_smaller_than_the_reservation_yields_no_budget(self) -> None:
        """Not a negative budget: the answer is that nothing fits, and it is said plainly."""
        self.assertEqual(retrieval.passage_budget_chars(context_tokens=512), 0)


if __name__ == "__main__":
    unittest.main()
