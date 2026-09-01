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
| `previous_failures` | `[ VerificationResult ]` — empty on the first attempt; on a regeneration, exactly what failed and why |
| `attempt` | `1` on the first call, `2` on the regeneration. Nothing else is valid |

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

**`top_k`** is gateway configuration, not a profile field. It is a retrieval tuning knob with no
per-tradition meaning, so it does not belong in a document that records doctrinal commitments — the
mirror image of why the corpus ID *does* belong there. Phase 1 default is 20, overridable with
`--top-k`, and it MUST be recorded in the trace: with Scripture at roughly 90% of the Phase 1 index
and no tier weighting, `top_k` is the only thing determining whether a confessional chunk reaches
the generator at all, and Phase 2 cannot attribute a retrieval change to a constant nobody logged.

**`previous_failures` and `attempt`** exist because ADR-0010 decided the retry carries "the failure
reasons back" and no field carried them. `previous_failures` reuses `VerificationResult` — the same
message Go already produces and persists — so nothing new is defined and Go emits only what it
actually found. It is verification metadata, never instructions: Go MUST NOT compose prose telling
Python how to fix the answer. `confidence.reason` is the only Go-authored string in the system, and
the first exception to that is the one that ends the guarantee.

`attempt` is required for metrics, not for generation. ADR-0010 states that first-attempt and
post-retry verification must be distinguishable, or a regeneration hides a rising fabrication rate.

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
  no_answer_reason: string       # model-authored; only when every content slot is empty; <= 200 chars
  confidence: { level: enum, reason: string }   # BOTH Go-derived, never model-authored

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
  is_contested: bool             # when true, `arguments` MUST be empty (ADR-0019)
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
- `quote` is at least **40 characters** after normalisation. A shorter quote fails. This blocks the
  degenerate citation — "Baptism is a sacrament" cited at `binding` behind a claim the Confession
  denies — without asking what any claim means (ADR-0020).
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
- When `is_contested` is true, `arguments` MUST be empty. A contested answer is a descriptive
  answer: the ruling quoted verbatim, plus what the sources say, attributed to them. `position`
  empties for free under the rule above. Flagging a locus contested and resolving it in the same
  answer otherwise passes every other check, and it is the outcome PRODUCT-SPEC calls the worst
  possible one (ADR-0019).
- `no_answer_reason` is non-empty **only** when `arguments`, `descriptions` and `contrary_positions`
  are all empty and `is_contested` is false, and is at most 200 characters. An answer with every
  slot empty and no `no_answer_reason` FAILS and regenerates — a truncated generation must not
  render as considered silence.
- `confidence.level` and `confidence.reason` are both derived by Go. Python MUST NOT populate
  either, and Go MUST overwrite whatever arrives.

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

### What the four checks do not catch

Stated together, because the guarantee is narrower than the README's phrasing suggests and an
unstated limit reads as an absent one. There are four, and Phase 2's harness measures all four.

1. **Provenance is not entailment.** The checks establish that a citation is *real* — the locator
   resolves, the quote is genuinely in that chunk, the tier is permitted, the licence allows
   serving. None establishes that the quote *supports the claim*. An argument claiming "the PCA
   holds that baptism regenerates the infant", cited to a real `binding` quote from WCF 28, passes
   every check while asserting what the Confession denies. The 40-character floor blocks only the
   degenerate version. Answer faithfulness is a Phase 2 measurement, separate from recall@k
   (SHARED §7).
2. **The omission check needs a citation to fire.** An answer resolving a contested locus while
   citing neither the ruling nor anything reaching it fabricates nothing, so nothing fires.
3. **`position` is uncited prose**, bounded only by the empty-when-descriptive rule.
4. **`no_answer_reason` is uncited prose**, bounded only by the 200-character cap and the
   all-slots-empty precondition. It is the only one of the four deliberately added rather than
   inherited, and it renders with no citation beside it (ADR-0020).

**Both halves of `confidence` are derived by Go from the verification result** — citation counts by
tier, contested flags, degraded checks — and state what was found, never how the model felt about
it. Python MUST NOT populate `level` or `reason`, and Go MUST overwrite whatever arrives in either.
A model-authored `reason` would be introspection wearing a structured field's clothes, and it is the
likeliest way for §4 to be violated without anyone noticing; a model-authored `level` is the same
thing compressed into an enum, and it can contradict the `reason` computed beside it (ADR-0020).

The derivation is fixed here rather than left to the implementer, so the enum means the same thing
across runs and Phase 2 can read it:

| `level` | Condition |
| --- | --- |
| `high` | Two or more `binding` or `governing` citations, first attempt, not contested |
| `medium` | One `binding` or `governing` citation, or a regeneration occurred |
| `low` | Descriptive only, or contested, or `no_answer_reason` set |

`reason` states the same finding in words — the tier counts, the attempt number, and whether the
locus was contested. It is verification metadata, not answer content.

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
  generation_model: string       # pinned tag, e.g. qwen3:8b-<tag> (ADR-0018)
  top_k: int                     # the value actually used for this request
  timings: { embed_ms, search_ms, generate_ms }
```

`generation_model` and `top_k` are recorded because they are the two settings most likely to move
the Phase 2 baseline silently. A number nobody logged cannot be held constant across a comparison.

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

An honest non-answer is **not** `DEGRADED`. A response carrying `no_answer_reason` is `VERIFIED`,
rendered with its own text rather than the degraded string, and counted as its own outcome. UC-2 and
UC-5 are the two most important non-answers in Phase 1 and they mean opposite things: one is the
corpus being silent, the other is verification refusing to ship. Collapsing them makes the
degradation rate unreadable, which is the metric ADR-0010 already needs kept clean.

## Profile document schema

YAML, loaded by Go, never sent to Python.

```yaml
profile: string                  # e.g. pca
scripture:
  corpus_id: string              # edition-specific, e.g. web-2000
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

Validation also reaches the database. The loader takes a **corpus registry** — an interface with a
single `Exists(corpus_id)` method, backed by a query over distinct `corpus_id` in `chunks` — and a
profile naming a corpus that is not ingested fails at load. So does a `contested` entry whose
`ruling_source` is not ingested, which is what actually delivers ADR-0015's promise of an honest
"the establishing document is not ingested yet" rather than an invented ruling. Checking only that
the ID appears in the profile's own `corpora` list proves internal consistency and nothing else.

The registry is an interface so the profile unit tests, including the no-identity-leak test, need no
database; the coupling is at wiring time. It does mean profile loading depends on ingestion having
run, which is why Task 6 depends on Tasks 2 **and** 5.

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
`contrary_positions`, never in `arguments`. "Your denomination examined this view and repudiated
it in 2007" is the answer it exists to produce — that is a claim *about* the source, not one
resting on its authority.

`scripture.corpus_id` is appended to the corpora list at the resolved stance before the filter spec
is built. It is not a separate channel — Scripture chunks are retrieved, cited, and verified exactly
like any other corpus, and a translation left out of `corpora` makes every verse citation fail as a
fabrication.

The profile carries the **corpus ID**, not a translation abbreviation. An earlier draft carried
`translation: WEB`, which left the WEB → `web-2000` mapping with no specified home: the engine would
have had to hold an abbreviation table, making every added translation an engine change and putting
a per-tradition corpus commitment outside the profile, which is the thing ADR-0011 exists to
prevent. A corpus ID needs no resolution step and fails loudly when wrong, because an ID absent from
the database is caught at load rather than guessed at.

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
license: string                 # enum value; confirmed, never assumed
license_terms: string           # the terms verbatim as found, with the URL they were found at
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

0. Remove format characters that are invisible and are whitespace in neither language's standard
   library: U+FEFF (BOM), U+200B (zero-width space), U+200C, U+200D, U+00AD (soft hyphen). These
   survive every later step intact and produce a quote mismatch on text that is visually identical —
   the symptom this contract exists to prevent, arriving from ordinary PDF and HTML extraction.
1. Unicode NFC.
2. Collapse runs of whitespace to a single space. **Whitespace means exactly the Unicode
   `White_Space` property**: U+0009–U+000D, U+0020, U+0085, U+00A0, U+1680, U+2000–U+200A, U+2028,
   U+2029, U+202F, U+205F, U+3000. Naming the set is load-bearing — Python's `\s` also matches
   U+001C–U+001F, which Go's `unicode.IsSpace` does not, so "collapse whitespace" alone is two
   different functions.
3. Trim leading and trailing whitespace.
4. Nothing else. No case folding, no quote or dash folding, no punctuation stripping — a quote that
   differs from source by a curly apostrophe is a genuine mismatch and must fail.

The current contract is `normalisation_version: 1`.

The vectors live in one committed fixture file, and both the Python ingestion suite and the Go
verification suite read that same file. Drift between the two implementations is the failure this
prevents, and it surfaces as quote-match failures on visually identical text, which is miserable to
diagnose from the symptom.

**The fixture is committed in Task 2 and asserted by both suites before any corpus is blessed.**
Fingerprints are hashes of post-normalisation text, so an ambiguity discovered when Go first
implements the contract would invalidate every fingerprint file and force a re-bless of every
corpus — including the by-hand 1788 edition verification that Task 4 calls the thing which silently
poisons everything downstream if it is wrong. Blessing a corpus against an implementation only one
language has ever run is the sequencing that makes that expensive.

The vectors MUST cover, at minimum: every `White_Space` code point named above, each stripped format
character from step 0, an NFC-unstable sequence, a curly apostrophe and a straight one, and an
em dash. All of it is invented text, never corpus text (ADR-0014).

## Chunk metadata contract

Every chunk in `chunks`. Ingestion rejects a chunk missing any of these. **Fourteen fields**;
`author` is the only nullable one.

| Field | Notes |
| --- | --- |
| `corpus_id` | Edition-specific. The join key to `works`, and half of every citation reference |
| `work` | Human-readable work name |
| `author` | May be null for corporate documents |
| `era` | For filtering and display |
| `tradition` | Originating tradition, not the querying one |
| `locator` | Canonical, resolvable, stable — see GLOSSARY |
| `language` | The language of the chunk text **as ingested** — `en` for a translation |
| `source_language` | The language of the work itself — `la` for the *Institutes*. Equal to `language` for an untranslated work |
| `text_form` | Enum: `tr`, `critical`, `majority`, `not-applicable` |
| `edition` | What makes 1788 distinguishable from 1646 |
| `license` | Enum: `public-domain`, `cc-by`, `cc-by-sa`, `local-only`, `refused` |
| `attribution` | Drives mechanical generation of the attribution page |
| `embedding_model` | Makes a model swap a re-index job |
| `dim` | As above |

`text_form` is a closed enum because the TR-versus-critical distinction exists only for biblical
text, and most of the Phase 1 corpus is not Scripture. `not-applicable` says that honestly; a free
text column would have collected five different improvised spellings of it. WEB is `majority` — its
New Testament follows the Majority Text.

`language` and `source_language` are split because the *Institutes* is an English translation of a
Latin work, and one column cannot carry both without meaning different things per row. ADR-0008
requires these fields from day one precisely because backfilling means re-ingesting, and that
argument applies to the distinction as much as to the field.

`license` is an enum for the same reason it is checked at all: a free-text value reduces check 4 to
"the string is non-empty", which is a check that reports success while evaluating nothing (ADR-0017).
`local-only` is servable only under an explicit deployer opt-in; `refused` is never servable.

## CLI surface

`berean ask --profile pca "question"` — the Phase 1 entry point. Prints the verified answer, then
the trace on `--show-work`. `--top-k` overrides the configured default.

Serving `local-only` corpora requires the deployer opt-in (ADR-0017). Without it the BCO and the
2000 creation report are ingested but refused at check 4, so UC-4 degrades — Task 11 runs with the
opt-in set, and the README says so.

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
