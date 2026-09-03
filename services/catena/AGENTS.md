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
- When you set `is_contested`, emit **no** `arguments`. A contested answer is descriptive: quote the
  ruling, describe the debate, take no side (ADR-0019).
- **Never populate `confidence`** — neither `level` nor `reason`. Go derives both from the
  verification result and overwrites anything you send. A self-assessed confidence is introspection
  wearing a structured field's clothes (ADR-0020).
- When the corpus is silent, say so in `no_answer_reason` — at most 200 characters, and only with
  every content slot empty. It is the one thing you write that renders with no citation beside it,
  so it states *that* the sources are silent and never what you think the answer would be. An empty
  answer with no reason is treated as a malformed generation and regenerated.
- Quotes must be at least 40 characters. A short quote that technically appears in the source
  supports nothing, and it fails.
- `corpus_id` must be edition-specific.
- Quotes must be verbatim and NFC-normalised by following the normalisation steps in
  INTEGRATION-SPEC and asserting the shared test vectors. There is no shared normalisation
  function and the specs must not ask for one — ingestion is Python and verification is Go, so
  the contract is the steps and the vectors, not a call. This side is `catena.normalise`; the
  vectors are `testdata/normalisation/vectors.json` and Go's half reads that same file. Change
  either implementation only by changing the fixture first, and remember that a change to the
  contract re-blesses every corpus.
- **Never emit anything describing your own reasoning process.** `warrant` is the theological link
  from citation to claim, not introspection. If a proposed field would describe how the model
  arrived at something, it does not belong in the contract.
- Write scope: corpus tables only. No access to trace tables.
- Ingestion is a batch job. Never in the request path.

## Conventions

- Embedder behind an interface. `embedding_model` and `dim` written on every chunk, and every
  metadata field populated — `text_form` and `license` are closed enums, and `source_language` is
  the work's own language rather than the chunk's.
- Generation behind an OpenAI-compatible interface so Ollama, vLLM, llama.cpp, and hosted APIs are
  interchangeable. Default to local so the acceptance test holds with no accounts.
- Langfuse instrumentation on every model call, from the first commit that makes one.
- Chunk on structural boundaries. Fixed-token splitting is prohibited.
- No CC-BY-NC models. Ever. See ADR-0007.
