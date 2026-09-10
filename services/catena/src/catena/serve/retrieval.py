"""Dense-only top-k, and the budget that decides what reaches the generator.

Phase 1 retrieval is deliberately naive — no reranking, no BM25, no query
rewriting, no multi-hop. TECHNICAL-SPEC is explicit that making it good now
destroys the measurement that justifies Phase 3, so the only judgement this
module makes is which candidates *fit*.

That judgement is real, though, and it is why `Candidate.exclusion_reason` is
not permanently empty in Phase 1. The generator's context is finite and smaller
than `top_k` chunks of *Institutes* prose, so something has to be dropped, and
a trace that recorded only what survived would hide the drop entirely. Every
candidate is recorded either way, with its score and its fate.

Two things are pinned against the budget rather than ranked by it:

* **A contested locus's ruling.** It is fetched by locator rather than by
  similarity — a pointer resolves to exactly one chunk — and `state_of_debate`
  has to quote it verbatim, so dropping it would guarantee the failure ADR-0019
  exists to prevent. It still enters the trace as a candidate carrying its real
  similarity score, because the trace is an audit log and a fabricated score is
  worse than an honest low one.

* Nothing else. Scripture is roughly 90% of the Phase 1 index and no tier
  weighting balances corpus proportions, so a confessional question can retrieve
  only verses. **That is left naive and measured, not pre-empted** — the trace
  is what makes it visible, and the fix, if the numbers ask for one, is an ADR
  with evidence behind it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from berean.v1 import common_pb2, filter_pb2

#: The generator's context window, in tokens. Set on the `ollama` service as
#: `OLLAMA_CONTEXT_LENGTH`; mirrored here because the OpenAI-compatible endpoint
#: has no per-request equivalent, so the client cannot ask and must be told.
#: Ollama's own default is 4096 and it truncates *silently* past it, which would
#: degrade the Phase 2 baseline invisibly — the failure this constant exists to
#: prevent.
CONTEXT_TOKENS_ENV = "CATENA_CONTEXT_TOKENS"
DEFAULT_CONTEXT_TOKENS = 8192

#: Held back from the window for the completion itself, plus the system prompt,
#: the schema and the framing around each passage.
RESERVED_TOKENS = 2048 + 768

#: Deliberately pessimistic. Early modern English with archaic spelling and
#: unusual proper nouns tokenises worse than the ~4 chars/token that ordinary
#: prose gets, and overrunning the window costs a silent truncation while
#: undershooting costs one dropped candidate. Phase 2 measures this properly;
#: until then it is an approximation that says so.
CHARS_PER_TOKEN = 3.5


def passage_budget_chars(context_tokens: int | None = None) -> int:
    tokens = context_tokens or int(
        os.environ.get(CONTEXT_TOKENS_ENV) or DEFAULT_CONTEXT_TOKENS
    )
    return max(0, int((tokens - RESERVED_TOKENS) * CHARS_PER_TOKEN))


@dataclass(frozen=True)
class Hit:
    """One chunk as the database returns it. No tier: tier is not in the corpus."""

    chunk_id: int
    corpus_id: str
    locator: str
    text: str
    work: str
    score: float


@dataclass(frozen=True)
class Passage:
    """A hit with the stance the *asking tradition* takes toward its corpus.

    Tier is a per-tradition stance rather than a property of the corpus, so it
    arrives on the FilterSpec and is joined here. The same chunk is `binding`
    under one profile and `contrary` under another.
    """

    chunk_id: int
    corpus_id: str
    locator: str
    tier: int
    text: str
    work: str
    score: float

    @property
    def tier_name(self) -> str:
        return common_pb2.Tier.Name(self.tier)


@dataclass(frozen=True)
class Selection:
    """What reaches the generator, and the whole candidate list for the trace."""

    passages: tuple[Passage, ...]
    candidates: tuple[dict[str, Any], ...]


class CorpusStore(Protocol):
    """What retrieval needs of the corpus tables, and nothing more."""

    def search(
        self, vector: Sequence[float], corpus_ids: Sequence[str], limit: int,
        embedding_model: str,
    ) -> list[Hit]:
        """Top-k by cosine similarity, filtered to these corpora."""
        ...

    def by_locator(
        self, corpus_id: str, locator: str, vector: Sequence[float], embedding_model: str,
    ) -> Hit | None:
        """One chunk by its citation reference, with its similarity to the query."""
        ...


def tiers_by_corpus(spec: filter_pb2.FilterSpec) -> dict[str, int]:
    return {entry.corpus_id: entry.tier for entry in spec.corpora}


def select(
    hits: Sequence[Hit],
    spec: filter_pb2.FilterSpec,
    *,
    pinned: Sequence[Hit] = (),
    budget_chars: int | None = None,
) -> Selection:
    """Fit the hits to the context budget, recording every candidate's fate.

    Highest score first, pinned hits ahead of all of them. A candidate that does
    not fit is excluded rather than truncated: half a passage in the prompt is
    an invitation to quote across the cut, and a quote that spans a truncation
    fails check 2 while looking like a paraphrase.
    """
    budget = passage_budget_chars() if budget_chars is None else budget_chars
    tiers = tiers_by_corpus(spec)

    seen: set[int] = set()
    ordered: list[tuple[Hit, bool]] = []
    for hit in pinned:
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            ordered.append((hit, True))
    for hit in sorted(hits, key=lambda h: -h.score):
        if hit.chunk_id not in seen:
            seen.add(hit.chunk_id)
            ordered.append((hit, False))

    passages: list[Passage] = []
    candidates: list[dict[str, Any]] = []
    used = 0
    for hit, is_pinned in ordered:
        # A corpus absent from the spec cannot be cited — Go fails a citation to
        # an unsent corpus immediately — so putting it in front of the model
        # only invites the fabrication. It should not happen: the search filters
        # on exactly these IDs. Recorded rather than assumed away.
        tier = tiers.get(hit.corpus_id)
        if tier is None:
            candidates.append(_candidate(hit, False, "corpus not in the filter spec"))
            continue

        cost = len(hit.text)
        if not is_pinned and used + cost > budget:
            candidates.append(_candidate(hit, False, "context budget"))
            continue

        used += cost
        passages.append(Passage(
            chunk_id=hit.chunk_id, corpus_id=hit.corpus_id, locator=hit.locator,
            tier=tier, text=hit.text, work=hit.work, score=hit.score,
        ))
        candidates.append(_candidate(hit, True, ""))

    return Selection(passages=tuple(passages), candidates=tuple(candidates))


def _candidate(hit: Hit, included: bool, reason: str) -> dict[str, Any]:
    return {
        "corpus_id": hit.corpus_id,
        "locator": hit.locator,
        "score": hit.score,
        "included": included,
        "exclusion_reason": reason,
    }
