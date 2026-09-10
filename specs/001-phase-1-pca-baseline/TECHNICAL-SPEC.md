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
- **Institutes** — one chunk per paragraph (`Inst. 4.17.10.p1`), book, chapter and section as the
  locator path and as metadata. Sections were the chunk until the corpus was measured against
  BGE-M3: four exceeded its 8,192-token window.

Required metadata on every chunk, with one exception — `author` may be null for corporate
documents, which is most of the Phase 1 corpus. Nothing else may be:

```
corpus_id, work, author, era, locator, language, source_language,
text_form, edition, license, attribution, embedding_model, dim
```

`language`, `source_language` and `text_form` are required now even though original-language support
is Phase 3–4 (ADR-0008). `edition` is what makes `wcf-1788-american` distinguishable from
`wcf-1646-epcew-modernised`.

`text_form` and `license` are closed enums, not free text — `tr | critical | majority |
not-applicable` and `public-domain | cc-by | cc-by-sa | local-only | refused`. Most of the Phase 1
corpus is not Scripture, so `text_form` is `not-applicable` for it, and saying so explicitly is
better than five improvised spellings of the same idea. `license` is an enum because check 4 is only
a check if its domain is closed (ADR-0017). `language` is the chunk text as ingested and
`source_language` is the work's own — `en` and `la` respectively for Beveridge's *Institutes*.

Structural chunking happens during **acquisition**, not ingestion (ADR-0014). Acquisition fetches,
extracts, segments on the boundaries above, normalises, and verifies against committed
fingerprints; ingestion reads the staged records, enriches, embeds, and loads. So ingestion never
parses upstream formats and never touches the network — and per-chunk fingerprints are meaningful,
because chunking has already happened when they are computed.

Ingestion is idempotent and re-runnable, keyed on the per-chunk hash. It is a batch job invoked by
hand in Phase 1; it is never in the request path.

Text is normalised during **acquisition** per the normalisation contract in INTEGRATION-SPEC, and
quote comparison at verification applies the identical steps. The staged records ingestion reads are
already post-normalisation, and `corpus.chunks.text` is what acquisition hashed. The two ends run in
different languages, so what is shared is the contract and its test vectors rather than a function. A
mismatch here produces verification failures on visually identical text and is extremely annoying to
diagnose.

### Ingestion converges; it does not insert

`catena ingest (--corpus <id> | --all) [--apply]` makes the database agree with the blessed staging
directory. A database that is behind staging is behind staging, and it does not matter why: a killed
run, a re-bless under a corrected parser, a fresh clone and a half-applied migration all produce the
same disagreement, and one diff resolves all of them. There is no recovery path separate from the
normal path.

`corpus.chunks` is UNIQUE on `(corpus_id, locator)` and idempotence is keyed on `content_hash`.
Those are different keys, and the plan falls out of the difference — **the locator says which chunk
this is, the hash says what it currently says**: a locator with no row is an insert, the same
locator saying something else is an update, the same locator saying the same thing is a skip, and a
row whose locator staging no longer has is a delete.

**An update MUST drop the embeddings it invalidates, in the same transaction.** Deleting a chunk
cascades; updating one does not, and nothing in the schema notices. An update that rewrites `text`
and `content_hash` while leaving the old vector in place produces a chunk retrieved for what it used
to say and quoted for what it now says — and verification passes, because check 2 matches the quote
against `corpus.chunks.text`, which is the new text.

**It writes only under `--apply`**, inverting `catena acquire`, which writes unless told otherwise.
Acquisition writes into gitignored `/data` and a mistake costs minutes of re-fetching; ingestion
updates and deletes rows that cascade to embeddings, and a mistake costs hours of embedding no cache
can return. The plan is recomputed by both paths rather than carried in a file between them, so it
has one implementation and is never stale.

Applying is two phases, and the boundary is load-bearing. Phase one upserts `corpus.works` and
applies every insert, update and delete to `corpus.chunks` in one transaction per corpus; phase two
embeds the backlog in batches, one transaction per batch. Once phase one commits, the database holds
complete, correct, blessed text whether or not phase two ever runs — which is the boundary
`corpus.chunk_metadata`'s inner join already chose.

Resumption is a query, not a checkpoint: the chunks carrying no `chunk_embeddings` row for the
active `embedding_model`. There is no progress file, no checkpoint table and no run ledger — nothing
to leave stale and nothing to reconcile after a hard kill. The `embedding_model` predicate makes
resumption model-aware, so a re-index under a second model sees a full backlog rather than an empty
one.

Embedding batches are filled to a budget of **padded tokens**, not to a chunk count. A transformer
pads every sequence in a batch to the longest one in it, and the corpus spans roughly 14x by median
chunk length — 34 tokens for a median WEB verse against 408 for a median *Institutes* paragraph — so
a fixed count makes memory, time per batch, and the work a crash destroys all depend on which corpus
the run is in. The backlog is length-sorted in memory before batches are filled, which is ours to do
because the commit granularity is ours: `sentence-transformers`' `encode()` sorts internally and
returns only when the whole input is done, so a kill at 95% would lose everything.

**Ingestion refuses a corpus carrying any chunk over the embedder's context window**, measured with
the model's own tokeniser. Not a warning: BGE-M3 truncates silently at 8,192 tokens and returns a
vector, so the chunk is retrieved on its opening fraction and quoted from its whole text, and
verification passes. This makes ingestion a check on acquisition's chunking, which is where the
defect lives — the fix is always to re-chunk on a smaller structural boundary. All eight Phase 1
corpora pass; the longest chunk is an *Institutes* paragraph at 2,890 tokens.

Ingestion also refuses a corpus that was never blessed, and one whose staging disagrees with
`corpora/<corpus-id>/fingerprints.txt` in any of the three directions. Staging is allowed to hold
work in progress; the database is not.

## Retrieval — deliberately naive

Dense-only vector search over BGE-M3 embeddings, top-k, with a metadata filter on the resolved
corpus IDs. **No reranking, no BM25, no query rewriting, no multi-hop.**

This is the Phase 2 baseline. Making it good now destroys the measurement that justifies Phase 3.

`top_k` is gateway configuration (default 20, `--top-k` to override), not a profile field, and it is
recorded in the trace. Scripture is roughly 90% of the Phase 1 index by chunk count and tier weights
are unused, so nothing balances corpus proportions: it is possible for a confessional question to
retrieve only verses, and since Scripture is `binding` under the PCA profile such an answer passes
check 3 while never citing the Confession the question asked about. **This is left naive and
measured, not pre-empted.** The trace records every candidate with its corpus and score, so UC-1
produces the evidence directly. If WCF 18 does not surface, the fix lands as an ADR with numbers
behind it — most likely a per-corpus retrieval quota, which is policy rather than reranking.

`top_k` candidates do not all reach the generator, and the gap is recorded rather than hidden.
Retrieval fits them to a **context budget** derived from the generator's window; what does not fit
is excluded whole — never truncated, because a quote spanning a cut fails check 2 while looking like
a paraphrase — and appears in the trace as `included: false` with `exclusion_reason: "context
budget"`. On a live Phase 1 query 11 of 20 candidates reached the generator. This is the one
judgement retrieval makes in Phase 1, and it is the reason `exclusion_reason` is not permanently
empty.

A **contested locus's ruling is pinned** ahead of the budget. It is fetched by `(corpus_id,
locator)` rather than by similarity — a pointer resolves to exactly one chunk — because
`state_of_debate` must quote it verbatim, so dropping it would guarantee the failure ADR-0019
exists to prevent. It still enters the trace carrying its real similarity score: the trace is an
audit log, and a fabricated score is worse than an honest low one.

Retrieval sets `hnsw.iterative_scan` per transaction. pgvector's default is `off` and HNSW
post-filters, so a corpus filter can return fewer than `top_k` rows — `top_k` would then quietly
mean "up to `top_k`, depending which corpora you asked for", and Phase 2 cannot attribute a
retrieval change to a number that meant something different per profile.

The embedder sits behind an interface from day one (ADR-0006). Swapping is a config change plus a
re-index job.

BGE-M3 runs **in-process in Catena from weights in `/models/`**, not served by Ollama. Ollama's
`bge-m3` exposes dense vectors only, and the learned sparse representation is the one advantage
ADR-0006 actually cites for this model — serving it over HTTP now would foreclose Phase 3's hybrid
path quietly, which is the kind of decision that is cheap to make correctly and expensive to
discover. Both weights are pinned in `tools/provision/models.lock.yaml` and fetched by
`make provision`; the generator's pin is verified against the upstream registry manifest on every
provision, so a republished tag fails loudly rather than moving the Phase 2 baseline invisibly
(ADR-0018).

## Profile

A YAML document, loaded and resolved by Go. One file per tradition in `profiles/`, named for
the profile it carries — `profiles/pca.yaml` is what `--profile pca` selects:

```yaml
profile: pca
scripture:
  corpus_id: web-2020
  stance: binding              # optional; defaults to binding
corpora:
  - id: wcf-1788-american
    stance: binding
    note: American revision, ch. 23 revised
  - id: wlc-1788-american
    stance: binding
  - id: wsc-1788-american
    stance: binding
  - id: pca-bco-2026
    stance: governing
  - id: wcf-1646-epcew-modernised
    stance: contrary
    label: "1646 Westminster in modern English, not PCA's text"
  - id: pca-ga28-2000-creation-study
    stance: advisory
    note: GA study committee reports are advice to the courts, not constitutional
  - id: calvin-institutes-1559-beveridge
    stance: advisory
    note: 1559 edition, Beveridge 1845 translation; respected, not constitutional
contested:
  - locus: creation-days
    ruling_source:
      corpus_id: pca-ga28-2000-creation-study
      locator: "GA28 Rec.2"
```

The locator is `GA28 Rec.2` rather than the `Recommendations 1` this document first drew: Task 4
made the report's recommendations independently addressable as `GA28 Rec.1`–`Rec.3`, and **Rec.2 is
the ruling** — the Assembly affirming that a diversity of views on the creation days is acceptable.
Pointing at Rec.1 or at the expository body would cite advocacy as though it were the finding.

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

Resolution appends `scripture.corpus_id` to the corpora list at the resolved stance. The profile
names the edition directly, so there is no abbreviation to translate and no engine-side table to
keep in step. Scripture is not a parallel channel: a verse citation is
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
2. **Quote matches** — the verbatim quote appears in that chunk's text after NFC normalisation, and
   is at least 40 characters long. The floor blocks the degenerate citation that satisfies every
   check while supporting nothing (ADR-0020).
3. **Tier permitted** — the chunk's corpus is in the active profile at a tier the claim's *slot*
   allows. Every `Argument` needs at least one `binding` or `governing` citation; `advisory` may
   corroborate inside an argument but never carry one alone; `contrary` and `excluded` never appear
   in an argument at all. They appear in `descriptions` and `contrary_positions`, where any tier is
   permitted and `contrary`/`excluded` must carry a label. Go checks which slot a claim occupies,
   never what the claim means (ADR-0016).
4. **License permits serving** — the chunk's `license` enum permits display. `local-only` requires
   the deployer opt-in; `refused` never passes (ADR-0017).

Answer-level: **any claim without a citation fails.** And when `is_contested` is true, `arguments`
MUST be empty — a contested answer is descriptive, or it is flagging a debate while settling it
(ADR-0019).

**The checks prove a citation is real, never that its quote supports the claim.** That limit, and
the three other uncited surfaces, are enumerated in INTEGRATION-SPEC and measured by Phase 2.

On failure: regenerate once with the failure reasons fed back — carried as `previous_failures`, a
list of `VerificationResult`, alongside `attempt`. On second failure, degrade to "I can't source
this adequately." Never render with a warning.

`confidence.level` and `confidence.reason` are both derived by Go from the verification result;
Python populates neither. A model-authored confidence is introspection in a structured field, which
SHARED §4 forbids in any form (ADR-0020).

An honest non-answer is not a degraded one. When the corpus is silent the model sets
`no_answer_reason` with every content slot empty, and the result is `VERIFIED` with its own rendered
text — tracked separately from `DEGRADED`, because UC-2 and UC-5 mean opposite things.

Target ≤ 200 ms p95. It is indexed lookups and string matching; if it is slower, something is
structurally wrong.

## Generation

Structured output. Citations are first-class fields, never inline prose — prose citations cannot
be validated, which is the whole reason for the answer object.

The provider sits behind an OpenAI-compatible interface. Default local via Ollama so the
acceptance test holds with no accounts. **The default model is Qwen3-8B** (Apache-2.0), with
`AnswerObject` validity enforced by JSON-schema-constrained decoding rather than by asking the model
for JSON. The exact tag is pinned in provisioning and written into every trace: the generator is the
largest single variable in the Phase 2 baseline, and a silent change to it would move that number
invisibly. Provisional on the same terms as the embedder — re-decided at Phase 2 against the golden
set (ADR-0018, ADR-0006).

The constraint travels as `response_format: {type: json_schema}` on the OpenAI-compatible endpoint
rather than as Ollama's native `format` field, so the provider stays interchangeable. **The schema
is derived from `AnswerObject`'s protobuf descriptor, never hand-written** — a hand-written copy is
a second place the contract lives. It departs from a naive translation in three ways, each measured
rather than assumed (ADR-0023):

- `confidence` is subtracted, so Go's field is *unpopulatable* rather than merely unpopulated.
- `required` follows the **list-only rule**: fields are required in messages reachable only through
  a repeated field, and nothing is required in messages reachable as a singular field or at the
  root. Requiring everything makes the decoder narrate into slots whose correct value is nothing —
  a live probe produced `position: "no_position"` beside empty `arguments`, which fails the
  empty-when-descriptive rule outright.
- **No count constraints.** `minItems` is honoured by the decoder, and what it buys is a fabricated
  citation to pad the count. An uncitable argument emits `citations: []`, which Go fails loudly.

**Thinking is disabled** (`reasoning_effort: "none"`). Qwen3's reasoning trace is not covered by the
decoding constraint, and it is the model's narrative about its own reasoning — SHARED §4 forbids
emitting that, and nothing in Catena reads the field. It is also not optional in practice: with
thinking on, a schema-constrained probe spent its entire token budget inside `reasoning` and
returned empty content.

The generator's context window is set on the Ollama service (`OLLAMA_CONTEXT_LENGTH`, 8192).
Ollama's own default is 4096 and it **truncates silently** past it, which would drop most of what
retrieval found while recording nothing — so Catena fits candidates to a budget derived from that
window and records what did not fit.

**A measured Phase 1 limit.** On a broad question — UC-4, the creation days — the generator answers
21 retrieved passages with a single argument whose `warrant` summarises a dozen sources in one
string, and runs past the completion ceiling. The truncation is refused rather than shown, so the
guarantee holds and the answer degrades; but the answer degrades. Prompting is the prescribed
response and did not bind: neither a limit on the number of claims nor a per-field sentence limit
changed the output, and the same instructions on a two-passage prompt produce a compact, correctly
routed answer. The runaway scales with how much source material is in front of the model, which
points at a per-corpus retrieval quota — policy, not reranking — as the first thing Phase 2 should
cost. It is recorded here rather than fixed, because fixing it before Phase 2 measures it is the
optimisation the phase ordering exists to prevent.

The live risk is verbatim quoting. Check 2 is exact substring containment with no case, quote or
dash folding, and Westminster is dense with archaic spelling and curly apostrophes. A model that
paraphrases by one character fails every citation it emits. That rate is measured in Phase 1 for
free, and the response is a better generator or better prompting — **never a looser check 2.**

The prompt injects the **filter spec** summary — the corpora in scope and the stance taken toward
each — and the citation rules. Not the profile: Python never receives one, and the corpora list is
the whole of what can be said there about who asked (ADR-0015). An earlier draft of this line said
"profile summary", which was never implementable.

Prompting is layer 2 of 3 and is not trusted on its own; layer 3 is what makes it real. One thing
layer 2 must get right, because no later layer can: **passage text is delimited by whole lines, never
wrapped in quotation marks.** A probe that wrapped passages in `"` got the quotation marks back
inside the quote, which fails exact substring containment while reading exactly like a paraphrase
failure.

## Data model

Corpus tables (Python writes, Go reads): `works`, `chunks`, `chunk_embeddings`, plus the
`chunk_metadata` view that exposes the chunk metadata contract over the three.
Trace tables (Go writes, Python does not touch): `responses`, `traces`, `candidates`,
`verification_results`.

Disjoint write scope is enforced by separate database roles, not by convention.

All DDL lives in `db/migrations/` and is applied by a pinned golang-migrate container running as
`berean_owner`. Column-level detail, the constraints that hold the proto's prose invariants, and
the reasoning behind each is in INTEGRATION-SPEC, **Schema and migrations**.

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
