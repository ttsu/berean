# Phase 1 — PCA Baseline: Integration Specification

Contracts, schemas, and protocols. Implementation-agnostic.

The protobuf definition in `proto/` is the **single normative source** for the Go↔Python contract.
This document describes intent and constraints; where they disagree, the proto wins and this
document is stale and must be fixed.

## The one call

`CatenaService.Answer` — unary. One invocation per generation attempt: once per turn, plus at most
one regeneration on verification failure (ADR-0002, ADR-0010).

### Request: Go → Python

| Field | Notes |
| --- | --- |
| `query` | The user's question, verbatim |
| `conversation_context` | Empty in Phase 1; present in the contract so Phase 4 is not a proto break |
| `filter_spec` | The **resolved** filter — see below |
| `request_id` | Correlates trace, response, and Langfuse span |

**`filter_spec`** carries corpus IDs grouped by tier plus tier weights. It does **not** carry the
profile, profile name, user identity, or session state. Python must be able to serve the request
knowing nothing about who asked or which tradition it is — it receives a search policy, not an
identity.

```
filter_spec:
  corpora: [ { corpus_id, tier }, ... ]
  tier_weights: { binding: float, governing: float, advisory: float, ... }
  top_k: int
```

Tier weights are carried in Phase 1 but unused, since there is no reranker yet. Present in the
contract so Phase 3 is not a proto break.

### Response: Python → Go

Two top-level parts: the **answer object** and the **retrieval trace**.

```
AnswerObject:
  position: string
  arguments: [ Argument ]
  contrary_positions: [ ContraryPosition ]
  contested: { is_contested: bool, state_of_debate: string }
  confidence: { level: enum, reason: string }

Argument:
  claim: string
  warrant: string
  citations: [ Citation ]        # MUST be non-empty

Citation:
  corpus_id: string              # edition-specific, e.g. wcf-1788-american
  locator: string                # e.g. "WCF 18.3"
  tier: Tier
  quote: string                  # verbatim, NFC-normalised

ContraryPosition:
  position: string
  held_by: [ string ]            # traditions
  citations: [ Citation ]        # tier will be `contrary`
```

Constraints Go enforces on receipt — Python's output is untrusted:

- `arguments[].citations` non-empty. An empty list fails the answer.
- `corpus_id` present in the filter spec that was sent. A citation to an unsent corpus is a
  fabrication and fails immediately.
- `quote` appears verbatim in the source chunk text after NFC normalisation — exact substring
  containment, never fuzzy or partial matching.
- `locator` resolves to exactly one chunk.
- `tier` matches the stance the resolved profile assigns that corpus, never the tier Python claims.

**There is no field for the model's reasoning about its own process, and there must never be
one.** `warrant` is the theological justification for a claim — the argumentative link from
citation to claim. It is not introspection. If a proposed field would describe *how the model
arrived at* something, reject it (ADR-0003, SHARED §4).

### RetrievalTrace

```
RetrievalTrace:
  rewritten_query: string        # Phase 1: identical to query
  candidates: [ { corpus_id, locator, score, included: bool, exclusion_reason } ]
  embedding_model: string
  dim: int
  timings: { embed_ms, search_ms, generate_ms }
```

Returned inside the response for storage, not as a live feed. Go persists it.

## Verification result contract

Go produces this; it is stored and surfaces in the "show the work" panel.

```
VerificationResult:
  citation_ref: { corpus_id, locator }
  locator_resolved: bool
  quote_matched: bool
  tier_permitted: bool
  license_permitted: bool
  failure_detail: string
OverallResult: VERIFIED | REGENERATED | DEGRADED
```

`DEGRADED` means the user saw "I can't source this adequately." It is a **successful** outcome of
the verification system, not an error, and metrics must not treat it as a failure rate.

## Profile document schema

YAML, loaded by Go, never sent to Python.

```yaml
profile: string                  # e.g. pca
scripture:
  translation: string            # WEB in Phase 1
corpora:
  - id: string                   # edition-specific, required
    stance: binding | governing | advisory | contrary | excluded
    note: string                 # optional, internal
    label: string                # required when stance is `contrary`; shown to the user
contested:
  - locus: string
    ruling: string
```

Validation: unknown `stance` is an error, not a default. `contrary` without `label` is an error —
an unlabelled contrary citation is exactly the failure mode the tier system exists to prevent.

`scripture.translation` is resolved into the corpora list as an edition-specific corpus ID before
the filter spec is built. It is not a separate channel — Scripture chunks are retrieved, cited, and
verified exactly like any other corpus, and a translation left out of `corpora` makes every verse
citation fail as a fabrication.

## Chunk metadata contract

Every chunk in `chunks`. Ingestion rejects a chunk missing any of these.

| Field | Notes |
| --- | --- |
| `corpus_id` | Edition-specific. The join key to `works`, and half of every citation reference |
| `work` | Human-readable work name |
| `author` | May be null for corporate documents |
| `era` | For filtering and display |
| `tradition` | Originating tradition, not the querying one |
| `locator` | Canonical, resolvable, stable — see GLOSSARY |
| `language` | Required now; used from Phase 3 |
| `text_form` | Required now; TR vs critical is a denominational commitment |
| `edition` | What makes 1788 distinguishable from 1646 |
| `license` | Verification refuses to serve without a permitting value |
| `attribution` | Drives mechanical generation of the attribution page |
| `embedding_model` | Makes a model swap a re-index job |
| `dim` | As above |

## CLI surface

`berean ask --profile pca "question"` — the Phase 1 entry point. Prints the verified answer, then
the trace on `--show-work`.

`catena ingest --corpus <id> --source <path>` — batch ingestion. Idempotent.

## Database roles

Two Postgres roles with disjoint write grants, enforced by grants rather than convention:

- `catena` — write on corpus tables, no access to trace tables.
- `gateway` — write on session and trace tables, read-only on corpus tables.

## Versioning

The proto is versioned from the first commit (`berean.v1`). Fields present-but-unused in Phase 1 —
`conversation_context`, `tier_weights`, `rewritten_query` — exist specifically so later phases add
behaviour rather than break the contract.

Adding a field is cheap. Renaming or removing one is a breaking change requiring a new package
version.
