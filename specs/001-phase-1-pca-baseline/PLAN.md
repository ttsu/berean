# Phase 1 — PCA Baseline: Execution Plan

**Volatile.** This file is a delta, not a blueprint. It can be discarded once the phase is done.
The specifications are the durable artefacts.

Each task should be implementable and testable within a single agent session. Check boxes as
acceptance criteria are met. **When implementation reveals something the spec did not anticipate,
update the spec in the same change.**

---

## Task 0: Resolve the Go-in-Phase-1 question

**Depends on:** —

Decide whether Phase 1 includes the Go CLI or is Python-only. See the open decision at the top of
TECHNICAL-SPEC.md. Every task below assumes the Go CLI.

**Resolved: Phase 1 includes the Go CLI** (ADR-0013).

- [x] Decision recorded as an ADR — ADR-0013
- [x] TECHNICAL-SPEC.md open-decision section replaced with the outcome
- [x] Not Python-only, so tasks 6, 7, 8 and 10 stand as written

---

## Task 1: Repository skeleton and `docker compose up`

**Depends on:** Task 0

Compose stack with Postgres + pgvector, Langfuse, and empty service containers. Nothing does
anything yet; the acceptance test passes.

- [ ] `docker compose up` succeeds with no external accounts
- [ ] `make provision` pulls images, the **pinned** Qwen3-8B tag and BGE-M3 into `/models/`, and
      invokes corpus acquisition into `/data/` — neither ships in the repo. Task 1 asserts the target
      exists and is documented; Task 11 is where it is run clean-clone end to end, which is why this
      does not make Task 1 wait on Task 4
- [ ] After provisioning, the stack comes up and serves with egress blocked
- [ ] Postgres reachable with pgvector extension available
- [ ] Langfuse reachable, with its organisation, project and API keys provisioned **headlessly from
      environment**. It is a five-container stack — web, worker, ClickHouse, Redis, and the MinIO
      SHARED §1 already requires — and a first boot that asks a human to sign up fails the
      no-external-accounts test as surely as a hosted service would (ADR-0009 status note)
- [ ] README states the RAM and disk floor and the expected provisioning duration. The
      clone-to-first-answer path is the acceptance test, and an acceptance test that silently needs a
      well-specified machine is not one
- [ ] The `local-only` serving opt-in is documented as an environment setting, default off (ADR-0017)
- [ ] Two DB roles created, with schema-level grants and `ALTER DEFAULT PRIVILEGES` per
      INTEGRATION-SPEC — no tables exist yet, so table grants are re-asserted by the DDL task
- [ ] Makefile defines every target the documentation names — `provision` and `dev` here,
      `corpus-verify` from Task 4 — and README documents `make provision` and `make dev`
- [ ] Check that fails when a `make <target>` named in any Markdown file has no Makefile rule.
      The README's clone-to-first-answer path is the project's acceptance test, so a target that is
      renamed or never written breaks it silently and only for new contributors
- [ ] Guard that fails on any staged file containing corpus text — a bright line that nothing
      checks will erode (ADR-0014)

---

## Task 2: Proto contract and codegen

**Depends on:** Task 1

`proto/berean/v1/` per INTEGRATION-SPEC, with buf generating both Go and Python.

- [ ] `Answer` RPC, `FilterSpec`, `AnswerObject`, `Citation`, `Description`, `Contested`,
      `VerificationResult`, `RetrievalTrace` defined
- [ ] Deferred fields present: `conversation_context`, `tier_weights`, `rewritten_query`
- [ ] Request carries `previous_failures` (`[VerificationResult]`) and `attempt`. ADR-0010 decided
      the retry carries failure reasons back and no field carried them — without this, Task 8's
      recovery path is inexpressible. Free now, a break after Task 7
- [ ] `AnswerObject.no_answer_reason` present; `confidence` documented as wholly Go-derived
- [ ] `RetrievalTrace` carries `generation_model` and `top_k`
- [ ] **Shared normalisation fixture committed here and asserted by both the Python and Go suites.**
      It cannot wait for Task 5 and Task 8: fingerprints are hashes of post-normalisation text, so an
      ambiguity found when Go first implements the contract invalidates every fingerprint file and
      forces a re-bless of every corpus — including Task 4's by-hand edition verification. Vectors
      cover each `White_Space` code point, each format character stripped in step 0, an NFC-unstable
      sequence, curly and straight apostrophes, and an em dash. Invented text only (ADR-0014)
- [ ] `buf generate` produces Go and Python stubs
- [ ] Generated code gitignored and regenerated locally; the commit-or-generate decision is
      **deferred to Phase 2** (ADR-0013) — it is CI policy, not contract design
- [ ] `buf breaking` in CI **deferred to Phase 2**; the proto is pre-consumer in Phase 1

---

## Task 3: Corpus and trace schema, and migrations

**Depends on:** Task 1

All DDL lands here. Task 8 writes `VerificationResult` rows and Task 9 writes traces, so both need
their tables before either starts — splitting the DDL across Tasks 3 and 9 makes the two circular.

- [ ] `works`, `chunks`, `chunk_embeddings` tables
- [ ] `responses`, `traces`, `verification_results` tables
- [ ] All fourteen required metadata fields NOT NULL where the spec requires it (`author` nullable)
- [ ] `license` and `text_form` are database-level enums, not free-text columns. An unrecognised
      value fails at insert, which is what makes check 4 a check with a closed domain (ADR-0017)
- [ ] `source_language` present alongside `language` — the *Institutes* is English text of a Latin
      work, and one column cannot carry both (ADR-0008's backfill argument applies to the split)
- [ ] pgvector index on embeddings
- [ ] Migration is reversible
- [ ] Insert without `license` or `attribution` fails at the database level, not in application code
- [ ] Table grants applied for both roles, disjoint per INTEGRATION-SPEC

---

## Task 4: Corpus acquisition pipeline and provenance

**Depends on:** —

Build the acquisition pipeline, then use it to acquire the 1788 American revision of WCF/WLC/WSC,
the current BCO, the 1646 original (needed for the edition check, and the profile's only `contrary`
corpus), the WEB text, the 28th General Assembly (2000) creation study committee report
(`pca-ga28-2000-creation-study`) — the document that establishes the contested status of
`creation-days`, without which the corpus says only "in the space of six days" (WCF 4.1) and UC-4
cannot be answered from any ingested text — and Calvin's *Institutes*
(`calvin-institutes-1559-beveridge`), 1559 edition in the Beveridge 1845 translation, which is what
makes UC-6 runnable at all.

Seven corpora. The *Institutes* is the largest by far and the only translated work, so it is the one
that exercises `source_language` and the book/chapter/section locator.

**No corpus text enters the repository** (ADR-0014). The repo carries manifests, fingerprints, and
scripts; text lands in gitignored `/data/`.

Pipeline:

- [ ] `catena acquire --corpus <id>` runs fetch → extract → segment → normalise → verify → stage
- [ ] Each stage independently re-runnable and idempotent; fetch caches on `upstream_sha256`
- [ ] Structural chunking lives in the segment stage — WCF per numbered section, WLC/WSC per Q&A
      pair never split, BCO per numbered paragraph, WEB per verse, the *Institutes* per numbered
      section (`Inst. 4.17.10`), the 2000 report per numbered section with its recommendations
      segmented separately from the expository body
- [ ] The 2000 report's recommendations are independently addressable, so a profile's
      `ruling_source` resolves to the ruling and never to the expository body. The body argues
      four views the denomination did not adopt; tier is per corpus, not per chunk, so nothing
      else separates advocacy from ruling
- [ ] `--bless` writes a new manifest after human edition verification; the default mode verifies
      against the committed manifest and fails loudly, never silently, on any mismatch
- [ ] `--from-file` accepts a local copy, so a dead or moved upstream does not block a deployer
- [ ] `make corpus-verify` re-acquires every corpus and diffs against committed fingerprints —
      this is how upstream drift gets noticed

Provenance and licensing:

- [ ] **Resolved (ADR-0017):** BCO and `pca-ga28-2000-creation-study` are ingested as `local-only`.
      Ingestion and serving are separate acts — the repository distributes nothing (ADR-0014), and
      check 4 refuses to serve `local-only` chunks unless the deployer has opted in, defaulting to
      deny. This no longer blocks acquisition. It does mean the manifest must record the terms
      **verbatim as found**, with the URL, in `license_terms`: a licence is evidence, not a label
- [ ] Manifest per corpus: source URL, archive fallback URL, retrieval date, licence enum,
      `license_terms` verbatim, attribution, edition diagnostic with its expected text, normalisation
      contract version (`1`), chunk count
- [ ] Fingerprints file: one `<locator>  <sha256-of-normalised-text>` per line, sorted
- [ ] **Verified as the 1788 American revision** — WCF ch. 23 checked by hand against the 1646
      text, with the divergence recorded in the manifest as quoted text rather than a checkbox
- [ ] Licence and attribution confirmed per source and recorded, never assumed. `public-domain` for
      WCF/WLC/WSC, WEB and the Beveridge *Institutes*; `local-only` for the two PCA-published corpora
- [ ] The *Institutes* is taken in the Beveridge 1845 translation, not Battles (1960), which is in
      copyright. Note the practical consequence for Task 11: Battles is the translation a model is
      most likely to have memorised, so UC-6 may fail check 2 on passages the model genuinely knows.
      That is a finding about the generator, not a defect in the verifier
- [ ] Bare text only, never a modern edition's apparatus — footnotes, cross-references, modernised
      spelling, and proof-text selections can carry fresh copyright over public-domain text

Getting the edition wrong here silently poisons everything downstream. Verify by hand.

---

## Task 5: Ingestion — enrich, embed, load

**Depends on:** Tasks 3, 4

Chunking and normalisation happen in acquisition, so ingestion never parses an upstream format and
never touches the network. It reads staged records, enriches, embeds, and loads.

- [ ] Reads staged records from gitignored `/data/staged/<corpus-id>/`; no network in this path
- [ ] Records re-verified against committed fingerprints before insert — ingestion refuses text
      that does not match what was blessed
- [ ] WEB ingested as `web-2000`, the corpus ID the PCA profile names
- [ ] `calvin-institutes-1559-beveridge` ingested at `advisory`, so UC-6 has a source that carries
      no binding authority. Roughly 1,700 section chunks, and the largest embedding job after WEB
- [ ] `wcf-1646-original` ingested, so the profile's `contrary` entry resolves and UC-3 has a
      counterpart to contrast against
- [ ] All fourteen metadata fields populated on every chunk, including `source_language` (`la` for
      the *Institutes*, equal to `language` elsewhere) and `text_form` (`majority` for WEB, whose NT
      follows the Majority Text; `not-applicable` for every non-Scripture corpus)
- [ ] Corpus IDs edition-specific (`wcf-1788-american`)
- [ ] The Python suite asserts the shared normalisation fixture committed in Task 2 — it is not
      created here, because Task 4 blesses fingerprints against it
- [ ] Ingestion is resumable per corpus. Roughly 35,000 chunks embed on a clean clone, dominated by
      WEB's ~31,100 verses, and an interrupted multi-hour run must continue rather than restart
- [ ] BGE-M3 behind an embedder interface; `embedding_model` and `dim` written per chunk
- [ ] Re-running ingestion is idempotent, keyed on the per-chunk hash
- [ ] Spot-check: `WCF 7.2` and `WSC Q&A 1` retrieve and read correctly

---

## Task 6: Profile engine (Go)

**Depends on:** Tasks 2, 5

The dependency on Task 5 is real, not bookkeeping: the loader validates corpus IDs against the
database, and there is nothing to validate against until a corpus is ingested. The task header
previously said Task 2 while the parallelisation table said Tasks 2 and 5; the table was right.

- [ ] PCA profile YAML per INTEGRATION-SPEC, including `calvin-institutes-1559-beveridge` at
      `advisory`
- [ ] Loader validates: unknown stance is an error; `contrary` or `excluded` without `label` is an error
- [ ] `scripture.stance` defaults to `binding` when absent; `contrary`/`excluded` rejected (ADR-0011)
- [ ] `scripture.corpus_id` appended to the corpora list carrying that stance as its tier
- [ ] `contested` entries validated: `ruling_source.corpus_id` absent from `corpora` is a load error
- [ ] Loader takes a `CorpusRegistry` interface (`Exists(corpus_id)`, backed by distinct `corpus_id`
      in `chunks`). A profile naming an un-ingested corpus fails at load, as does a `contested` entry
      whose `ruling_source` is not ingested — which is what delivers ADR-0015's honest "the
      establishing document is not ingested yet" instead of an invented ruling. Checking only the
      profile's own `corpora` list proves internal consistency and nothing more
- [ ] The registry is an interface, so the profile unit tests — including the no-identity-leak
      test — need no database
- [ ] Resolves to a `FilterSpec` carrying corpus IDs, tiers, weights — **and nothing else**
- [ ] Unit test asserts no profile name, user identity, or session state appears in the FilterSpec
- [ ] Contested loci resolve to a **sibling** request field, never into the FilterSpec — pointers
      only (`locus`, `corpus_id`, `locator`), never resolved prose (ADR-0015)
- [ ] Schema handles N profiles though only one is populated

---

## Task 7: Catena service — retrieval and generation (Python)

**Depends on:** Tasks 2, 5

- [ ] gRPC server implementing `Answer`
- [ ] Dense-only top-k search filtered to the corpus IDs in the FilterSpec
- [ ] **No reranking, no BM25, no query rewriting** — naive is the requirement
- [ ] Resolves a sent locus's `ruling` pointer through ordinary retrieval and grounds
      `state_of_debate` in that passage; populates `contested.locus` only from the loci sent
- [ ] When it sets `is_contested`, it emits **no** `arguments` — a contested answer is descriptive
      (ADR-0019). Routing this badly fails loudly in Go and costs a regeneration, which is the
      intended direction
- [ ] Emits `no_answer_reason` (≤ 200 chars) when the corpus is silent, with every content slot
      empty. An empty answer with no reason is a malformed generation and Go regenerates it
- [ ] Populates neither `confidence.level` nor `confidence.reason`. Go derives both (ADR-0020)
- [ ] Consumes `previous_failures` and `attempt` on a regeneration
- [ ] Routes claims into `arguments` or `descriptions` per the slot rules, so a descriptive answer
      is expressible without an affirmative claim behind it
- [ ] Generation behind an OpenAI-compatible interface, default Ollama running the pinned Qwen3-8B
      tag (ADR-0018)
- [ ] Structured output conforming to `AnswerObject`, enforced by JSON-schema-constrained decoding
      rather than by asking the model for JSON
- [ ] `RetrievalTrace` populated including excluded candidates with reasons, plus `generation_model`
      and the `top_k` actually used
- [ ] Langfuse instrumentation on every model call
- [ ] Never writes to trace tables

---

## Task 8: Verification engine (Go)

**Depends on:** Tasks 3, 6, 7

The phase's reason for existing.

- [ ] Locator resolution: corpus ID + locator → exactly one chunk
- [ ] Quote match: exact substring containment after normalisation, with a **40-character floor**.
      The four checks prove a citation is real, never that its quote supports the claim; the floor
      blocks the degenerate case without any semantic judgement (ADR-0020)
- [ ] Go asserts the same shared normalisation vectors the Python ingestion suite asserts
- [ ] Tier check against the **resolved profile**, not the tier Python claimed
- [ ] Every `Argument` carries a `binding` or `governing` citation; advisory-only fails
- [ ] `contrary` or `excluded` appearing in `arguments[]` fails; both permitted in the descriptive
      slots with their labels
- [ ] `descriptions[].citations` non-empty; `position` empty when `arguments` is empty
- [ ] License check reads the enum: `public-domain`, `cc-by`, `cc-by-sa` pass; `local-only` passes
      only under the deployer opt-in; `refused` never passes (ADR-0017)
- [ ] Citation to a corpus not in the sent FilterSpec fails immediately
- [ ] `contested.locus` not among the loci sent fails immediately, as an unsent corpus does
- [ ] When `is_contested`, the locus's ruling is cited and quoted verbatim in `state_of_debate`
- [ ] When `is_contested`, `arguments` is empty. Flagging a locus contested and resolving it in the
      same answer otherwise passes every check, and WCF 4.1 is the most retrievable chunk for the
      UC-4 question while reading as settled (ADR-0019)
- [ ] A verified citation resolving to a locus's ruling while `is_contested` is false fails — the
      system's only omission check
- [ ] `no_answer_reason` non-empty only when every content slot is empty, and ≤ 200 characters.
      Every slot empty with no reason FAILS and regenerates — a truncated generation must not render
      as considered silence
- [ ] `confidence.level` and `confidence.reason` both derived from the verification result by the
      rule in INTEGRATION-SPEC, overwriting whatever Python sent
- [ ] Go never rewrites the answer; contested failures regenerate then degrade like any other
- [ ] Empty `citations` on any argument fails the answer
- [ ] Regenerate once on failure, sending `previous_failures` and `attempt = 2`; degrade on the
      second failure. Go sends verification results, never composed prose instructions
- [ ] Degraded output is "I can't source this adequately" with no partial unverified content
- [ ] `VerificationResult` persisted per citation
- [ ] An honest non-answer is recorded as `VERIFIED` with `no_answer_reason` set, tracked separately
      from `DEGRADED`. UC-2 and UC-5 mean opposite things and must not share a metric
- [ ] Unit tests use **invented text only**, never corpus text — substring containment and NFC are
      indifferent to provenance, and pasting WCF 7.2 into a fixture is the ADR-0014 violation the
      policy specifically warns about
- [ ] Latency measured against synthetic load, not the ten acceptance questions — ten hand-run
      queries do not produce a p95. Target remains ≤ 200 ms

---

## Task 9: Trace persistence

**Depends on:** Tasks 7, 8

Tables come from Task 3; this task is the persistence path that writes them.

- [ ] Trace persisted for every response including degraded ones
- [ ] Schema reviewed against Phase 2's needs before merge — revise the Task 3 migration if short
- [ ] Gateway role only; Catena has no write access

---

## Task 10: CLI

**Depends on:** Tasks 6, 8

- [ ] `berean ask --profile pca "question"` returns a verified answer
- [ ] `--show-work` prints the trace as a **log, not a narrative**
- [ ] `--top-k` overrides the configured default
- [ ] Citations render with corpus, edition, locator, and tier
- [ ] `contrary` citations render with their label
- [ ] An honest non-answer renders `no_answer_reason` in text visibly distinct from the degraded
      string. A reader must be able to tell "the corpus is silent" from "I could not source this"
- [ ] `catena ingest` documented

---

## Task 11: Phase 1 acceptance

**Depends on:** all

- [ ] Ten questions covering UC-1 to UC-6 run end to end
- [ ] **Zero unverified citations in output** — the phase's hard gate. On its own this gate is
      one-sided: a system that degrades on every question satisfies it perfectly, and so does one
      whose retriever returns nothing. The expectation table below is what makes it mean something
- [ ] **Expected-outcome table**, one row per question, declaring the `OverallResult` it must
      produce and the `corpus_id` + `locator` set its citations must include or exclude. Asserted on
      identifiers and result codes **only, never on expected text** — that is how a golden set
      normally smuggles corpus text into the repository (ADR-0014)
- [ ] UC-1 (assurance) returns `VERIFIED` including a `wcf-1788-american` citation in WCF 18. If it
      returns only proof-texts, that is a real finding: Scripture is ~90% of the index, it is
      `binding` under this profile, so a verse-only answer passes every check while never citing the
      Confession the question asked about. Record the candidate tier mix from the trace and raise an
      ADR rather than quietly adding a quota
- [ ] UC-2 (silent corpus) returns `VERIFIED` with `no_answer_reason` set and every content slot
      empty — **not** `DEGRADED`, and rendered differently
- [ ] UC-3 (civil magistrate) cites `wcf-1788-american` and **no** `wcf-1646-original` citation
- [ ] UC-4 (creation days) flags contested, cites the 2000 report's ruling, carries **no**
      `arguments`, and does not resolve
- [ ] UC-5 (fabricated citation) — the fabrication is prompt-induced, so the assertion is the
      **invariant**: no citation reached output unverified, and any failed check produced exactly one
      regeneration recorded in the trace. Separately, record by hand at least one transcript where a
      real fabrication was caught and degraded. If the model never obliges across all ten questions,
      write that down as a finding about the generator rather than leaving a checkbox blocked
- [ ] UC-6 (descriptive question) answers from `calvin-institutes-1559-beveridge` at `advisory` with
      citations, does not refuse, and states no `position`
- [ ] Run with the `local-only` serving opt-in **set**. Without it the BCO and the 2000 report are
      ingested but refused at check 4, so UC-4 degrades for a configuration reason that looks exactly
      like a verification bug (ADR-0017)
- [ ] Clean clone → `make provision` (models + `catena acquire`) → `docker compose up`
      reproduces all of the above, with acquisition verifying against committed fingerprints
- [ ] Wall-clock provisioning time measured on the reference machine and recorded in the README
      alongside the RAM floor — roughly 35,000 chunks embed on a clean clone
- [ ] Record the first-attempt verification rate separately from the post-retry rate (ADR-0010), and
      the rate at which check 2 failed on near-miss quotes rather than bad locators. The second
      number is the Phase 2 baseline for how much verbatim quoting this generator can do
- [ ] README documents the full path from clone to first answer

---

## Parallelisation

| Can run together | After |
| --- | --- |
| Tasks 3, 4 | Task 1 |
| Tasks 6, 7 | Tasks 2, 5 |
| Tasks 9, 10 | Task 8 |

## Out of scope — do not drift into these

Reranking, BM25, query rewriting, LangGraph, HTTP, SSE, auth, sessions, web UI, conversation
memory, translation display, additional traditions, original languages.

If a task starts to require one of these, stop and revise the spec instead.
