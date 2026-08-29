# services/catena — AGENTS.md

Python. The model layer. Codename for the retrieval and citation service.

**Your output is untrusted.** The gateway verifies every citation you emit against the database.
Design accordingly: emitting a plausible-looking citation is worse than emitting none, because the
former fails verification and costs a regeneration.

## Owns

Query rewriting, embedding, hybrid retrieval, reranking, LangGraph orchestration, generation,
ingestion, eval harness, lemma/lexicon tools.

Phase 1 scope: embed, dense-only top-k search, structured generation. **No reranking, no BM25, no
query rewriting.** Naive is the requirement, not a shortcut — Phase 2 measures this baseline and
Phase 3 has to beat it.

## Does not own

Auth, sessions, profile resolution, verification, trace persistence, translation fetch, SSE.

## Rules

- You receive a **FilterSpec**, not a profile. You do not know which tradition asked or who the
  user is, and you do not need to.
- Citations are **first-class structured fields**. Never emit citations as inline prose — prose
  citations cannot be validated, which is the entire reason the answer object exists.
- Every argument must carry at least one citation. An empty list fails the whole answer.
- `corpus_id` must be edition-specific.
- Quotes must be verbatim and NFC-normalised using the shared normalisation function.
- **Never emit anything describing your own reasoning process.** `warrant` is the theological link
  from citation to claim, not introspection. If a proposed field would describe how the model
  arrived at something, it does not belong in the contract.
- Write scope: corpus tables only. No access to trace tables.
- Ingestion is a batch job. Never in the request path.

## Conventions

- Embedder behind an interface. `embedding_model` and `dim` written on every chunk.
- Generation behind an OpenAI-compatible interface so Ollama, vLLM, llama.cpp, and hosted APIs are
  interchangeable. Default to local so the acceptance test holds with no accounts.
- Langfuse instrumentation on every model call, from the first commit that makes one.
- Chunk on structural boundaries. Fixed-token splitting is prohibited.
- No CC-BY-NC models. Ever. See ADR-0007.
