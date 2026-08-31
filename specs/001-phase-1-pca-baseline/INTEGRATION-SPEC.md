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
| `contested_loci` | `[ { locus, ruling: { corpus_id, locator } } ]` — see below |
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

**`contested_loci`** is a sibling of `filter_spec`, not part of it. `filter_spec` is retrieval
policy; contested loci are generation context, and mixing them would make the filter mean two
things. The FilterSpec resolution rule and its unit test are unchanged.

It carries, per locus the tradition holds open, a stable ID and the location of the ruling that
establishes it — **a pointer, never prose**. Python resolves that pointer through ordinary
retrieval, reads the passage, and grounds `state_of_debate` in it. Go does not resolve the quote
before sending: Python owns retrieval, Go owns verification, and having Go fetch chunk text to
build a request would invert that for no gain.

This does not reintroduce identity. Python still learns nothing about who asked, and the resolved
`corpora` list already fingerprints a tradition more precisely than a locus list does — a
`filter_spec` naming `wcf-1788-american` at `binding` alongside the BCO is unmistakably the PCA.
What the boundary refuses is a profile *identity* Python could branch on, key state to, or log as
a user attribute. A locus and a locator are neither (ADR-0015).

### Response: Python → Go

Two top-level parts: the **answer object** and the **retrieval trace**.

```
AnswerObject:
  position: string               # empty when `arguments` is empty
  arguments: [ Argument ]        # affirmative — tier floor enforced
  descriptions: [ Description ]  # descriptive — no floor, labels required
  contrary_positions: [ ContraryPosition ]
  contested: Contested
  confidence: { level: enum, reason: string }   # reason is Go-derived, never model-authored

Argument:
  claim: string
  warrant: string
  citations: [ Citation ]        # MUST be non-empty

Citation:
  corpus_id: string              # edition-specific, e.g. wcf-1788-american
  locator: string                # e.g. "WCF 18.3"
  tier: Tier
  quote: string                  # verbatim, NFC-normalised

Description:
  subject: string                # what is described — a person, document, or tradition
  content: string                # what that source says, not whether it is true
  citations: [ Citation ]        # MUST be non-empty; any tier

ContraryPosition:
  position: string
  held_by: [ string ]            # traditions
  citations: [ Citation ]        # tier will be `contrary`

Contested:
  is_contested: bool
  locus: string                  # MUST be one of the loci sent, when is_contested
  citations: [ Citation ]        # MUST include the locus's ruling, when is_contested
  state_of_debate: string        # MUST quote the ruling verbatim
```

Constraints Go enforces on receipt — Python's output is untrusted:

- `arguments[].citations` non-empty. An empty list fails the answer.
- `corpus_id` present in the filter spec that was sent. A citation to an unsent corpus is a
  fabrication and fails immediately.
- `quote` appears verbatim in the source chunk text after NFC normalisation — exact substring
  containment, never fuzzy or partial matching.
- `{corpus_id, locator}` resolves to exactly one chunk. A locator alone is not unique — `WCF 7.2`
  exists in both the 1788 and 1646 editions.
- `tier` matches the stance the resolved profile assigns that corpus, never the tier Python claims.
- Every `Argument` carries at least one `binding` or `governing` citation. An argument resting only
  on `advisory` fails — advisory corroborates, it never establishes.
- `contrary` and `excluded` citations never appear in `arguments[].citations`. They appear in
  `descriptions` and `contrary_positions`, and carry their label there.
- `descriptions[].citations` is non-empty and may draw on any tier. A `contrary` or `excluded`
  citation here MUST carry its label at render time.
- `position` is empty when `arguments` is empty. A purely descriptive answer reports what sources
  say and states no position of its own.
- `contested.locus` is one of the loci sent in the request. An unsent locus is a fabrication and
  fails immediately, exactly as an unsent `corpus_id` does.
- When `is_contested`, `contested.citations` includes the ruling named for that locus, and
  `state_of_debate` contains its quote verbatim under the same NFC substring rule as any other
  quote. A contested claim is a cited claim or it is not shown.
- When a verified citation resolves to a locus's ruling and `is_contested` is false, the answer
  fails. This is the one omission check in the system, and it exists because every other check
  catches fabrication instead.

Contested failures take the ordinary path: regenerate once with reasons fed back, degrade on the
second failure (ADR-0010). **Go does not rewrite the answer.** Substituting the ruling for a
model-authored `position` would make the trust boundary an author, and a verifier that edits what
it verifies is no longer a verifier. `confidence.reason` remains the only Go-authored field, and it
is verification metadata rather than answer content — a distinction worth holding, because the
first exception to it is the one that ends the guarantee.

A residual gap, stated rather than papered over: the omission check fires only when the model cites
the ruling. An answer that resolves a contested locus while citing neither the ruling nor anything
that reaches it is still possible, and nothing here catches it. Phase 2's eval harness is what
measures that rate; UC-4 in the golden set is not a substitute for measuring it.

**Affirmative and descriptive claims are separated structurally, not semantically** (ADR-0016).
An earlier draft made check 3 turn on whether a claim was "doctrinal", a predicate no field carried
and no document defined — so it could only be read as "everything", which makes `advisory` and
`contrary` unusable, or as "nothing", which makes the check a silent no-op. Membership in
`arguments` now *is* the affirmative claim: Go checks which list a claim is in and what tiers its
citations carry, never what the claim means.

This is what makes an `excluded` citation expressible. "Your denomination examined this view and
repudiated it in 2007" is a `Description` whose citation sits at `excluded` tier and carries its
label — a claim *about* a source, which is what that tier was always for.

One hole this does not close: `position` is prose with no citations of its own, so a model could
state affirmatively there what the routing rules would have rejected in `arguments`. The empty-when-
descriptive rule bounds it, and nothing checks it semantically. Phase 2's eval harness is where that
rate gets measured.

`confidence.reason` is **derived by Go from the verification result** — citation counts by tier,
contested flags, degraded checks — and states what was found, never how the model felt about it.
Python MUST NOT populate it, and Go MUST overwrite anything Python puts there. A model-authored
`reason` would be introspection wearing a structured field's clothes, and it is the likeliest way
for §4 to be violated without anyone noticing.

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
  stance: string                 # optional; binding | governing | advisory, default binding
corpora:
  - id: string                   # edition-specific, required
    stance: binding | governing | advisory | contrary | excluded
    note: string                 # optional, internal
    label: string                # required when stance is `contrary` or `excluded`; shown to the user
contested:
  - locus: string                # stable ID, e.g. creation-days
    ruling_source:               # required; the corpus document that establishes the ruling
      corpus_id: string
      locator: string
```

Validation: unknown `stance` is an error, not a default. `contrary` or `excluded` without `label`
is an error — an unlabelled citation at either tier is exactly the failure mode the tier system
exists to prevent. A `contested` entry whose `ruling_source.corpus_id` is absent from `corpora` is
a load error: a locus the profile cannot cite is a locus it cannot defend.

A `contested` entry asserts a **status** — this locus is open within this tradition — and points at
the document that establishes it. It carries no prose of its own. Every word shown to a user comes
from the corpus and is verified verbatim like any other quote, so `state_of_debate` is a citation,
not an assertion the profile makes on the corpus's behalf.

The status is the part that cannot be derived from text, which is why it is declared rather than
inferred. Three things block inference. Sparse retrieval is three-way ambiguous — "genuinely
contested", "never addressed", and "our corpus is thin" all look identical, yet UC-2 and UC-4
require different behaviour from that same signal. A document's standing within a tradition is a
polity fact that no document self-declares, exactly as the BCO does not call itself `governing`
and Trent does not call itself `contrary`; declaring stance is what the profile is *for*. And every
verification check in this system catches fabrication — an unsent corpus, a quote that does not
match, a locator that resolves twice — while none catches **omission**. A model that quietly fails
to notice a locus is contested has fabricated nothing, so nothing fires. SHARED §8 calls false
confidence on intramural disagreement worse than having no profile, which makes it the one failure
mode with no verification story. The declared list is what supplies one.

`excluded` is the tier the product is built around, so its handling is specified rather than left
to fall out of the others. An `excluded` corpus is retrievable and citable; its citations MUST
carry their label at render time, exactly as `contrary` does; and they appear in `descriptions` or
`contrary_positions`, never in `arguments`. "Your denomination examined this view and repudiated it in 2007" is the
answer it exists to produce — that is a claim *about* the source, not one resting on its
authority.

`scripture.translation` is resolved into the corpora list as an edition-specific corpus ID before
the filter spec is built. It is not a separate channel — Scripture chunks are retrieved, cited, and
verified exactly like any other corpus, and a translation left out of `corpora` makes every verse
citation fail as a fabrication.

`scripture.stance` defaults to `binding` when absent and accepts `binding`, `governing`, or
`advisory` only. `contrary` and `excluded` are load errors: no tradition in scope repudiates
Scripture, so either value means the profile is wrong (ADR-0011). The stance becomes that corpus's
tier in the filter spec and is checked at verification like any other. Setting it below `binding` is
a substantive claim — under check 3 it means Scripture alone cannot carry an `Argument` for that
tradition — so it is a behavioural change, not a labelling one.

## Corpus acquisition contract

No corpus text is committed (ADR-0014). What the repository carries instead, per corpus:

```
corpora/<corpus-id>/manifest.yaml
corpora/<corpus-id>/fingerprints.txt
tools/acquire/<corpus-id>.py
```

```yaml
corpus_id: wcf-1788-american    # edition-specific
source_url: string              # where the text was obtained
archive_url: string             # snapshot fallback, for when upstream moves
retrieved: YYYY-MM-DD
upstream_sha256: string         # detects upstream drift on re-acquisition
license: string                 # confirmed, never assumed
attribution: string
normalisation_version: int      # fingerprints are over normalised text; see below
chunk_count: int
edition_check:
  diagnostic: string            # e.g. WCF 23.3
  expected: string              # the actual divergent text, quoted
  verified_by: string
  verified: YYYY-MM-DD
```

`fingerprints.txt` is one `<locator>  <sha256-of-normalised-text>` per line, sorted by locator.

The fingerprints are the mechanism that replaces committing the text. On acquisition, a corpus is
fetched, segmented, normalised, and hashed, and every hash must match the committed value. That is a
stronger guarantee than a committed copy would give: it proves the text was reconstructed exactly as
hand-verified **and** that normalisation is deterministic across runs and machines.

The hashes are over post-normalisation text, so **a change to the normalisation contract invalidates
every fingerprint file**. `normalisation_version` records which contract version a manifest was
blessed under; bumping the contract means re-blessing every corpus, and that is intended to be
visible and deliberate.

First acquisition of a corpus has nothing to verify against. `--bless` covers that case: it runs the
pipeline, presents the output for human edition verification, and writes the manifest. Every run
after that verifies, and a mismatch is a hard failure with a diff summary — never a silent update.

## Normalisation contract

Ingestion runs in Python and verification runs in Go, so a single shared function is not available
and the specs must not ask for one. What is shared is the **contract** — the same ordered steps,
pinned by test vectors both sides assert against:

1. Unicode NFC.
2. Collapse runs of whitespace, including newlines, to a single space.
3. Trim leading and trailing whitespace.
4. Nothing else. No case folding, no quote or dash folding, no punctuation stripping — a quote that
   differs from source by a curly apostrophe is a genuine mismatch and must fail.

The vectors live in one committed fixture file, and both the Python ingestion suite and the Go
verification suite read that same file. Drift between the two implementations is the failure this
prevents, and it surfaces as quote-match failures on visually identical text, which is miserable to
diagnose from the symptom.

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
