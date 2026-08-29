# Phase 1 — PCA Baseline: Technical Specification

Architecture and quality requirements for Phase 1. Project-wide NFRs are in
[../SHARED-TECHNICAL-SPEC.md](../SHARED-TECHNICAL-SPEC.md) and are not repeated here; this
document only adds or tightens.

## Open decision — resolve before Task 1

**Does Phase 1 include the Go gateway, or is it a Python-only CLI?**

The roadmap says "naive RAG, CLI," which reads as Python-only. But the phase's stated goal is to
prove citations verify, and verification lives in Go by ADR-0001. A Python-only Phase 1 either
proves the wrong thing or builds verification twice.

**Recommendation: a minimal Go CLI binary**, not an HTTP server. It resolves the profile, makes
one gRPC call, verifies, and prints. No auth, no sessions, no SSE, no HTTP. That is a few hundred
lines beyond a Python CLI and it exercises the seam, the proto contract, and the trust boundary —
the three things most expensive to retrofit.

The rest of this spec assumes that recommendation. **If it is rejected, revise this document
before implementation rather than diverging from it.**

## Components in scope

| Component | Language | Phase 1 scope |
| --- | --- | --- |
| `berean` CLI | Go | Profile resolution, gRPC call, verification, render |
| Verification engine | Go | Locator, quote, tier, license checks |
| Trace writer | Go | Persist trace per response |
| Catena service | Python | Embed, dense search, generate structured answer |
| Ingestion CLI | Python | Parse, chunk, enrich, embed, load |
| Postgres + pgvector | — | Corpus, chunks, vectors, traces |
| Langfuse | — | LLM tracing, self-hosted |

Explicitly **not** in Phase 1: HTTP server, SSE, auth, sessions, rate limiting, translation
adapter, reranker, BM25/hybrid, LangGraph, conversation memory.

## Ingestion

Structural chunking only:

- **WCF** — one chunk per numbered section (`WCF 7.2`). Chapters are metadata, not chunks.
- **WLC / WSC** — one chunk per question and answer pair (`WSC Q&A 1`). Never split a Q from its A.
- **BCO** — one chunk per numbered paragraph (`BCO 21-4`).
- **WEB Scripture** — one chunk per verse. Proof texts in the Standards resolve to these.

Required metadata on every chunk, no exceptions:

```
work, author, era, tradition, locator, language, text_form,
edition, license, attribution, embedding_model, dim
```

`language` and `text_form` are required now even though original-language support is Phase 3–4
(ADR-0008). `edition` is what makes `wcf-1788-american` distinguishable from `wcf-1646-original`.

Ingestion is idempotent and re-runnable. It is a batch job invoked by hand in Phase 1; it is never
in the request path.

Text is normalised to NFC at ingestion. Quote comparison at verification uses the same
normalisation. A mismatch here produces verification failures on visually identical text and is
extremely annoying to diagnose, so normalise once, centrally, and test it.

## Retrieval — deliberately naive

Dense-only vector search over BGE-M3 embeddings, top-k, with a metadata filter on the resolved
corpus IDs. **No reranking, no BM25, no query rewriting, no multi-hop.**

This is the Phase 2 baseline. Making it good now destroys the measurement that justifies Phase 3.

The embedder sits behind an interface from day one (ADR-0006). Swapping is a config change plus a
re-index job.

## Profile

A YAML document, loaded and resolved by Go:

```yaml
profile: pca
scripture:
  translation: WEB
corpora:
  - id: wcf-1788-american
    stance: binding
    note: American revision, ch. 23 revised
  - id: wlc-1788-american
    stance: binding
  - id: wsc-1788-american
    stance: binding
  - id: pca-bco-2024
    stance: governing
  - id: wcf-1646-original
    stance: contrary
    label: "original Westminster, not PCA's text"
contested:
  - locus: creation-days
    ruling: "2000 study committee permitted multiple views"
```

Go resolves this into the filter spec sent to Python. **The profile itself never crosses the
boundary.**

Even with one profile, the schema is built as if there were eight — presets and fine-grained user
control are the same object, and building the schema twice is the avoidable version of this
mistake.

## Verification

Four checks per citation, all in Go, all ordinary software:

1. **Locator resolves** — the corpus ID and locator identify exactly one chunk.
2. **Quote matches** — the verbatim quote appears in that chunk's text after NFC normalisation.
3. **Tier permitted** — the chunk's corpus is in the active profile at a tier the claim allows.
   Doctrinal claims require `binding` or `governing`. Any `contrary` citation must carry a label.
4. **License permits serving** — the chunk's `license` allows display.

Answer-level: **any claim without a citation fails.**

On failure: regenerate once with the failure reasons fed back. On second failure, degrade to "I
can't source this adequately." Never render with a warning.

Target ≤ 200 ms p95. It is indexed lookups and string matching; if it is slower, something is
structurally wrong.

## Generation

Structured output. Citations are first-class fields, never inline prose — prose citations cannot
be validated, which is the whole reason for the answer object.

The provider sits behind an OpenAI-compatible interface. Default local via Ollama so the
acceptance test holds with no accounts.

The prompt injects the profile summary and citation rules. Prompting is layer 2 of 3 and is not
trusted on its own; layer 3 is what makes it real.

## Data model

Corpus tables (Python writes, Go reads): `works`, `chunks`, `chunk_embeddings`.
Trace tables (Go writes, Python does not touch): `responses`, `traces`, `verification_results`.

Disjoint write scope is enforced by separate database roles, not by convention.

## Observability

Langfuse self-hosted, instrumented from the first commit that calls a model. Retrofitting means
the Phase 1 baseline is unmeasured, which defeats the purpose of measuring Phase 3 against it.

Traces persist to Postgres independently of Langfuse, in a shape the Phase 2 eval harness can
consume. Design the trace schema with that consumer in mind now — it is cheap now and a migration
later.

## Explicitly deferred

| Deferred | Phase | Phase 1 obligation |
| --- | --- | --- |
| Hybrid + reranking | 3 | Leave retrieval naive; do not optimise |
| Eval harness | 2 | Trace schema must be consumable by it |
| Original languages | 3–4 | Tag `language` and `text_form` now |
| Web UI, SSE | 4 | Answer object must already be render-ready |
| Other traditions | v1 | Profile schema built for N, populated with 1 |
| Translation display | 2+ | Store locators only; no display text in DB |
| LangGraph | 5 | Do not introduce; hit the wall first |
