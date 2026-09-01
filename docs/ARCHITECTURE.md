# Architecture

## The seam

Two languages are only coherent if the boundary between them means something. Here it does:
**Python produces claims, Go adjudicates them.**

Python's output is untrusted input to Go. The verification layer is the trust boundary, and it
lives in Go where it is ordinary string matching and database lookups — not model behaviour.

```
client ──HTTP/SSE──> gateway (Go) ──gRPC (1 call)──> catena (Python)
                        │                                  │
                        │  verify · persist · render       │  retrieve · rerank · generate
                        ▼                                  ▼
                    Postgres (sessions, traces)      Postgres (corpus, chunks, vectors)
```

**Go → Python:** the query, conversation context, and a *resolved filter spec* — corpus IDs by
tier, plus tier weights. Not the profile itself. Profile resolution is policy and stays in Go.

**Python → Go:** the structured answer object plus the retrieval trace.

**Go then verifies:** resolves every citation against Postgres, checks quote match, checks tier
against the active profile, checks license permits serving. Renders or rejects.

## Responsibility split

| Go — policy and trust boundary | Python — mechanism and models |
| --- | --- |
| Auth, sessions, rate limiting | Query rewrite, embedding |
| Profile engine → resolved filter spec | Hybrid retrieval + rerank |
| **Citation verification** | LangGraph agent loop |
| Trace persistence | Generation |
| Translation API fetch + attribution | Lemma / lexicon tools (agent-callable) |
| SSE to the client | Ingestion, eval harness |

One Postgres, two clients, **disjoint write scope**: Python writes corpus tables, Go writes
session and trace tables. Neither writes the other's.

## Transport

gRPC with protobuf, one unary call per generation attempt (ADR-0002, amended by ADR-0010). The answer object is defined once in `proto/` and
generated for both sides. This is the entire contract between the languages; hand-maintaining
it in two places is the classic polyglot drift bug.

**Failure mode to avoid:** Go orchestrating the agent loop by calling Python per step. Chatty,
leaks state across the boundary, makes multi-hop retrieval miserable to debug. The whole loop
belongs on one side. Beyond the bounded regeneration retry (ADR-0010), more than one
cross-language call per turn means the seam is wrong.

If the wait turns out to feel dead in practice, the escape hatch is making the Python call a
server-streaming RPC so Python emits retrieval progress live. More granular, more complex
contract. **Start unary; switch only on evidence.**

## Profile enforcement — three layers

Prompt-only tradition steering produces confident nonsense. All three layers are required.

1. **Retrieval** — metadata filter on the active profile, then rerank with tier weighting so
   binding sources outrank advisory.
2. **Prompting** — inject profile summary plus citation rules; an affirmative claim must cite
   binding or governing tier, and anything else belongs in a descriptive slot.
3. **Validation** — programmatically verify each affirmative claim resolves to an in-profile
   `binding` or `governing` source, that no `contrary` or `excluded` citation appears in one, and
   that every such citation is labelled. Reject and regenerate on failure. The check is structural:
   which slot a claim occupies, never what it means (ADR-0016).

Layer 3 is what makes this an enterprise system rather than a RAG demo, and it is the layer
almost nobody builds.

## Answer object

The LLM emits structured output; the app renders it. Citations are first-class fields, never
inline prose — prose citations cannot be validated.

- `position`
- `argument[]` — each with `claim`, `citations[]` (corpus ID, locator, tier, verbatim quote),
  `warrant`
- `contrary_positions[]` — with the traditions that hold them
- `contested` — flag plus state of intramural debate
- `confidence` — with reason

## Verification pipeline

For every citation: the locator must resolve, the quote must match source text, the tier must
match the active profile, the license must permit serving. Any claim without a citation fails.

On failure: regenerate once, then degrade to "I can't source this adequately" rather than
shipping unverified.

This is ordinary software. It is also the most valuable component in the system.

## Streaming

Verification breaks naive token streaming — you cannot stream an answer you have not validated.
Stream **trace events** over SSE instead — dispatched, received, verifying, verified. Then deliver
the verified answer.

Because the Python call is unary and verification happens after it returns, the live SSE feed
is **Go narrating its own stages** — dispatched, received, verifying, verified. Python's trace
comes back inside the response, for storage rather than as a live feed.

Arguably better UX regardless: watching sources get gathered is the trust-building part.

## Ingestion and retrieval

**Ingestion is a separate service from retrieval**, and a batch job, never in the request path.
Parse → normalise → chunk on structural boundaries → enrich metadata → embed.

Chunk on structural boundaries: verse, article, question/objection/reply for Aquinas. **Never
naive 512-token splits.**

**Metadata is the product.** Every chunk carries its edition-specific corpus ID, work, author, era,
tradition, canonical locator, language, text-form, edition, license, attribution, and
`embedding_model` + `dim`. The last two
make a model swap a re-index job rather than a schema migration.

Retrieval is hybrid BM25 + dense, then a cross-encoder reranker. Theological vocabulary is
precise — "hypostatic", "perichoresis" — so the lexical side matters. Generation uses structured
output with mandatory citations and refuses rather than guesses.

Storage is Postgres + pgvector, containerised. Qdrant only if native hybrid out of the box
proves necessary.

## Original languages

Hebrew and Greek are a **deterministic lookup tool, not a retrieval corpus**. Embeddings are
trained on modern Greek and Hebrew, not Koine and Biblical Hebrew, and degrade silently.
Morphology defeats lexical search. Unicode normalisation breaks quote-match verification on
visually identical text.

Ingest morphologically tagged texts (OSHB, SBLGNT) where every word carries lemma, parsing, and
Strong's number, and make original-language queries lookups keyed on lemma and locator. Pair
with public-domain lexica so word meanings are retrieved, never generated.

Deferred to Phase 3–4, but **tag `language` and `text_form` in chunk metadata from day one** or
the corpus needs re-ingesting. See [ADR-0008](adr/0008-original-languages-as-a-tool.md).

## Infrastructure posture

| Avoid | Use |
| --- | --- |
| pgvector on RDS | Postgres + pgvector, containerised |
| EKS | Helm chart, any k8s; k3s or kind locally |
| LangSmith | Langfuse (self-hosted), or OTel + Phoenix |
| AWS SDK | S3-compatible client; MinIO locally |
| SQS | Postgres as the queue — keeps one datastore |
| Secrets Manager | env + SOPS/age, or Vault |

The translation provider is a pluggable adapter for the same reason: the ESV API is simply
unavailable in offline mode, and WEB or NET serves instead.
