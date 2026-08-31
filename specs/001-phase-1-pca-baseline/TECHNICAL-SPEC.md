# Phase 1 — PCA Baseline: Technical Specification

Architecture and quality requirements for Phase 1. Project-wide NFRs are in
[../SHARED-TECHNICAL-SPEC.md](../SHARED-TECHNICAL-SPEC.md) and are not repeated here; this
document only adds or tightens.

## Resolved — Phase 1 includes the Go CLI

**Phase 1 is a minimal Go CLI binary, not a Python-only CLI** (ADR-0013). It resolves the profile,
makes one gRPC call, verifies, persists a trace, and prints. No auth, no sessions, no SSE, no HTTP.

The roadmap's "naive RAG, CLI" reads as Python-only, but the phase exists to prove citations verify,
and UC-5 — a fabricated citation caught, regenerated, and degraded — is the acceptance case for the
whole phase. In a single-process Python CLI the code that produced the fabrication is the code that
catches it: that demonstrates the four checks are correct without demonstrating there is a trust
boundary, and the boundary is the product claim. It would also leave the cross-language
normalisation contract untested until it is ported onto an already-ingested corpus.

Scope discipline is what keeps this affordable: no CLI framework, one command, hand-rolled flags,
and the buf CI machinery deferred to Phase 2. Roughly 600 lines of Go, none of it algorithmically
hard — verification is string matching and indexed lookups.

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

Required metadata on every chunk, with one exception — `author` may be null for corporate
documents, which is most of the Phase 1 corpus. Nothing else may be:

```
corpus_id, work, author, era, tradition, locator, language,
text_form, edition, license, attribution, embedding_model, dim
```

`language` and `text_form` are required now even though original-language support is Phase 3–4
(ADR-0008). `edition` is what makes `wcf-1788-american` distinguishable from `wcf-1646-original`.

Structural chunking happens during **acquisition**, not ingestion (ADR-0014). Acquisition fetches,
extracts, segments on the boundaries above, normalises, and verifies against committed
fingerprints; ingestion reads the staged records, enriches, embeds, and loads. So ingestion never
parses upstream formats and never touches the network — and per-chunk fingerprints are meaningful,
because chunking has already happened when they are computed.

Ingestion is idempotent and re-runnable, keyed on the per-chunk hash. It is a batch job invoked by
hand in Phase 1; it is never in the request path.

Text is normalised at ingestion per the normalisation contract in INTEGRATION-SPEC, and quote
comparison at verification applies the identical steps. The two run in different languages, so what
is shared is the contract and its test vectors rather than a function. A mismatch here produces
verification failures on visually identical text and is extremely annoying to diagnose.

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
  stance: binding              # optional; defaults to binding
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
  - id: pca-ga28-2000-creation-study
    stance: advisory
    note: GA study committee reports are advice to the courts, not constitutional
contested:
  - locus: creation-days
    ruling_source:
      corpus_id: pca-ga28-2000-creation-study
      locator: "Recommendations 1"
```

Go resolves this into the filter spec sent to Python, plus the contested loci carried alongside it
(ADR-0015). **The profile document itself never crosses the boundary** — what crosses is the
resolved filter and, per locus, a stable ID and the locator of the ruling. No profile name, user
identity, or session state, and no prose the profile authored.

The report is `advisory` because that is what the PCA holds study committee reports to be: advice
to the courts, not constitutional. That stance interacts with verification check 3, which requires
an `Argument` to rest on `binding` or `governing`. Reporting that the denomination permitted
multiple views is a claim *about* the denomination's action, so it lives in `Contested` rather than
in `arguments`, where the advisory tier is no obstacle — the same routing that lets an `excluded`
citation carry "your denomination repudiated this" from `descriptions` (ADR-0016).

Resolution injects `scripture.translation` into the corpora list as an edition-specific corpus ID
(`web-2000` for the WEB text in Phase 1). Scripture is not a parallel channel: a verse citation is
verified by the same four checks as a confessional one, and a `corpus_id` absent from the filter
spec is treated as a fabrication. Leaving Scripture outside `corpora` makes every proof text in the
Standards unverifiable.

**Scripture's tier is profile-configurable, defaulting to `binding`** (ADR-0011). Scripture is
authoritative in every tradition in scope, so `binding` is the default and the PCA profile takes it.
It is a profile field rather than a constant because traditions differ on what stands *alongside*
Scripture, not on whether Scripture binds — and that difference is carried by what else the profile
marks `binding`, which is exactly the kind of commitment that belongs in a profile rather than in
the engine. `contrary` and `excluded` are rejected at load: no tradition in scope repudiates
Scripture, so either value means the profile is wrong.

Even with one profile, the schema is built as if there were eight — presets and fine-grained user
control are the same object, and building the schema twice is the avoidable version of this
mistake.

**The Phase 1 profile has no `excluded` entry, deliberately.** Populating it means acquiring the
PCA's 2007 Federal Vision report, whose copyright status is unchecked, and Phase 1 does not widen
for it. The consequence is worth stating plainly: the tier the product is differentiated on is
schema-complete but unexercised end to end until it is populated. **Phase 2 obligation** — acquire
the report, confirm its licence, populate `excluded`, and add a golden-set question that expects a
repudiation answer.

## Verification

Four checks per citation, all in Go, all ordinary software:

1. **Locator resolves** — the corpus ID and locator identify exactly one chunk.
2. **Quote matches** — the verbatim quote appears in that chunk's text after NFC normalisation.
3. **Tier permitted** — the chunk's corpus is in the active profile at a tier the claim's *slot*
   allows. Every `Argument` needs at least one `binding` or `governing` citation; `advisory` may
   corroborate inside an argument but never carry one alone; `contrary` and `excluded` never appear
   in an argument at all. They appear in `descriptions` and `contrary_positions`, where any tier is
   permitted and `contrary`/`excluded` must carry a label. Go checks which slot a claim occupies,
   never what the claim means (ADR-0016).
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
