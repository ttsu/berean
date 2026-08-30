# ADR-0006: BGE-M3 as the starting embedding model — a tested default, not a locked choice

- **Status:** Accepted (provisional)
- **Date:** 2026-08-29
- **Phase:** re-decided at Phase 2 against the golden set; expensive only from Phase 3

## Context

Leaderboard criteria mostly do not bind here:

- **Multilingual breadth.** Greek and Hebrew are deterministic lemma lookups, not vector search
  (ADR-0008). What actually gets embedded is early modern English (KJV, Westminster, Calvin in
  translation) and Latin (Vulgate, Summa). No leaderboard measures that.
- **Context length.** 32K vs 8K is irrelevant when chunking on verses and Aquinas articles.
  Chunks are hundreds of tokens.
- **MTEB rank.** A 2-point gap is meaningful; 0.5 is noise. The benchmark is modern prose and
  nothing in it resembles 17th-century confessional English.

What binds: local footprint, license, and whether hybrid comes in one pass.

| | BGE-M3 | Qwen3-0.6B | Qwen3-8B |
| --- | --- | --- | --- |
| Local footprint | ~2.3 GB, CPU-tolerable | ~1.5 GB, laptop-fine | ~16 GB VRAM |
| Dimensions | 1024 | 1024 (MRL-truncatable) | 4096 |
| Hybrid in one pass | Yes (dense + sparse + ColBERT) | No | No |
| License | MIT | Apache-2.0 | Apache-2.0 |

## Decision

**Start on BGE-M3.** MIT, proven, comfortable footprint, and its *learned* sparse vectors suit the
vocabulary problem — when a user asks about "the covenant of works" and the source says "first
covenant," lexical BM25 will not close that gap and a learned sparse representation can.

Treat this as a default to be tested, not settled:

- Store `embedding_model` and `dim` on **every chunk** from day one.
- Put the embedder behind an interface. Swapping is a config change plus a re-index job.
- **Benchmark candidates on the Phase 2 golden set** before Phase 3 locks it in.
  **Qwen3-Embedding-0.6B** is the contender to test against.

## Alternatives rejected

- **Qwen3-8B.** Disqualified, not merely a tradeoff: fails the `docker compose up` acceptance test
  on any normal machine, quadruples vector storage, and slows search. Reconsider only if a GPU
  deployment tier is added and breaking local parity is accepted.
- **NV-Embed-v2, jina-embeddings-v3.** Score well, but CC-BY-NC. Shipping an Apache-2.0 project
  that only works with a non-commercial model either poisons the license or forces the model to be
  optional-and-not-default. See ADR-0007.

## Consequences

Irreversibility is phase-dependent. At Phase 1 the corpus is tiny — the Westminster Standards are
roughly 30,000 words, so re-embedding is minutes. The decision only gets expensive around Phase 3,
once the Fathers and Calvin are ingested. That is precisely why the re-evaluation is scheduled
before then.

**Do not treat "the honest scoping" as marketing:** "avoids separate BM25 infrastructure"
overstates the hybrid advantage, since Postgres already has FTS and `pg_search` gives real
in-database BM25. The genuine advantage is the learned term expansion, which is narrower and real.
