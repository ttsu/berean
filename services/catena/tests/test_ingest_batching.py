"""Batch filling: a token budget, not a chunk count, over a length-sorted backlog.

A transformer pads every sequence in a batch to the longest one in it, and that
padding is work the model does and discards. The corpus spans roughly 14x by
median chunk length, so a fixed chunk count behaves badly at both ends.

Invented text throughout (ADR-0014). The fake's tokeniser counts whitespace
words, which is not BGE-M3's tokenisation and does not pretend to be — it is
monotonic in length, which is all any of this depends on.
"""

from __future__ import annotations

import unittest

from catena.ingest import embed
from fakes import FakeEmbedder


def pending(chunk_id: int, words: int):
    """A pending chunk of a given token length under the fake's tokeniser."""
    return embed.Pending(chunk_id, " ".join(f"w{n}" for n in range(words)))


class BatchFillingTest(unittest.TestCase):
    def test_a_batch_is_filled_to_the_padded_token_budget(self):
        # Ten tokens each, budget 100: ten per batch, not a chunk count anyone set.
        backlog = [pending(n, 10) for n in range(25)]

        batches = list(embed.batches(backlog, FakeEmbedder(), budget=100))

        self.assertEqual([len(b) for b in batches], [10, 10, 5])

    def test_long_chunks_make_smaller_batches_at_the_same_budget(self):
        # The point of the budget: memory and wall-clock per batch stay flat
        # while the batch size floats.
        short = list(embed.batches([pending(n, 10) for n in range(20)],
                                   FakeEmbedder(), budget=100))
        long = list(embed.batches([pending(n, 50) for n in range(20)],
                                  FakeEmbedder(), budget=100))

        self.assertEqual(len(short[0]), 10)
        self.assertEqual(len(long[0]), 2)

    def test_the_backlog_is_length_sorted_so_padding_is_not_paid_twice(self):
        # Interleaved: unsorted, one long chunk pads a whole batch of short ones.
        backlog = [pending(1, 100), pending(2, 1), pending(3, 100), pending(4, 1)]

        batches = list(embed.batches(backlog, FakeEmbedder(), budget=200))

        # The two short chunks share a batch; the two long ones are not paying
        # to pad them.
        first = batches[0]
        self.assertEqual(sorted(p.chunk_id for p in first), [2, 4])

    def test_no_chunk_is_dropped_or_embedded_twice(self):
        backlog = [pending(n, n % 17 + 1) for n in range(200)]

        batches = list(embed.batches(backlog, FakeEmbedder(), budget=64))

        seen = [p.chunk_id for batch in batches for p in batch]
        self.assertEqual(sorted(seen), list(range(200)))

    def test_no_batch_exceeds_the_budget_in_padded_tokens(self):
        backlog = [pending(n, n % 23 + 1) for n in range(200)]
        embedder = FakeEmbedder()

        for batch in embed.batches(backlog, embedder, budget=64):
            longest = max(embedder.count_tokens([p.text for p in batch]))
            self.assertLessEqual(len(batch) * longest, 64)

    def test_a_chunk_larger_than_the_budget_goes_alone_rather_than_looping(self):
        # The over-limit refusal bounds chunks against the model's window, not
        # against the budget, so a budget below a single chunk is reachable by
        # tuning alone. It must make progress.
        backlog = [pending(1, 500), pending(2, 2)]

        batches = list(embed.batches(backlog, FakeEmbedder(), budget=10))

        self.assertEqual([[p.chunk_id for p in b] for b in batches], [[2], [1]])

    def test_an_empty_backlog_yields_no_batches(self):
        self.assertEqual(list(embed.batches([], FakeEmbedder(), budget=100)), [])


if __name__ == "__main__":
    unittest.main()
