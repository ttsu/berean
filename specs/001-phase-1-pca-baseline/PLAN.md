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

- [ ] Decision recorded as an ADR
- [ ] TECHNICAL-SPEC.md open-decision section replaced with the outcome
- [ ] If Python-only: tasks 3, 6, 7, 8 rewritten before starting

---

## Task 1: Repository skeleton and `docker compose up`

**Depends on:** Task 0

Compose stack with Postgres + pgvector, Langfuse, and empty service containers. Nothing does
anything yet; the acceptance test passes.

- [ ] `docker compose up` succeeds with no external accounts and no network egress
- [ ] Postgres reachable with pgvector extension available
- [ ] Langfuse reachable
- [ ] Two DB roles created, with schema-level grants and `ALTER DEFAULT PRIVILEGES` per
      INTEGRATION-SPEC — no tables exist yet, so table grants are re-asserted by the DDL task
- [ ] `make dev` documented in README

---

## Task 2: Proto contract and codegen

**Depends on:** Task 1

`proto/berean/v1/` per INTEGRATION-SPEC, with buf generating both Go and Python.

- [ ] `Answer` RPC, `FilterSpec`, `AnswerObject`, `Citation`, `RetrievalTrace` defined
- [ ] Deferred fields present: `conversation_context`, `tier_weights`, `rewritten_query`
- [ ] `buf generate` produces Go and Python stubs
- [ ] Generated code is gitignored and regenerated in CI, or committed — decide and document
- [ ] `buf breaking` runs in CI against main

---

## Task 3: Corpus and trace schema, and migrations

**Depends on:** Task 1

All DDL lands here. Task 8 writes `VerificationResult` rows and Task 9 writes traces, so both need
their tables before either starts — splitting the DDL across Tasks 3 and 9 makes the two circular.

- [ ] `works`, `chunks`, `chunk_embeddings` tables
- [ ] `responses`, `traces`, `verification_results` tables
- [ ] All thirteen required metadata fields NOT NULL where the spec requires it (`author` nullable)
- [ ] pgvector index on embeddings
- [ ] Migration is reversible
- [ ] Insert without `license` or `attribution` fails at the database level, not in application code
- [ ] Table grants applied for both roles, disjoint per INTEGRATION-SPEC

---

## Task 4: Source acquisition and provenance

**Depends on:** —

Obtain the 1788 American revision of WCF/WLC/WSC and the current BCO in a parseable form.

- [ ] Source files acquired with recorded provenance URL and retrieval date
- [ ] **Verified as the 1788 American revision** — check WCF ch. 23 against the 1646 text
- [ ] License and attribution confirmed for each source
- [ ] Sources committed or a fetch script provided, whichever the license permits

Getting the edition wrong here silently poisons everything downstream. Verify by hand.

---

## Task 5: Ingestion — parse, chunk, enrich, embed

**Depends on:** Tasks 3, 4

- [ ] WCF chunked per numbered section; WLC/WSC per Q&A pair, never split
- [ ] BCO chunked per numbered paragraph
- [ ] WEB Scripture chunked per verse
- [ ] All thirteen metadata fields populated on every chunk
- [ ] Corpus IDs edition-specific (`wcf-1788-american`)
- [ ] Text NFC-normalised at ingestion, via a single shared function
- [ ] BGE-M3 behind an embedder interface; `embedding_model` and `dim` written per chunk
- [ ] Re-running ingestion is idempotent
- [ ] Spot-check: `WCF 7.2` and `WSC Q&A 1` retrieve and read correctly

---

## Task 6: Profile engine (Go)

**Depends on:** Task 2

- [ ] PCA profile YAML per INTEGRATION-SPEC
- [ ] Loader validates: unknown stance is an error; `contrary` without `label` is an error
- [ ] Resolves to a `FilterSpec` carrying corpus IDs, tiers, weights — **and nothing else**
- [ ] Unit test asserts no profile name, user identity, or session state appears in the FilterSpec
- [ ] Schema handles N profiles though only one is populated

---

## Task 7: Catena service — retrieval and generation (Python)

**Depends on:** Tasks 2, 5

- [ ] gRPC server implementing `Answer`
- [ ] Dense-only top-k search filtered to the corpus IDs in the FilterSpec
- [ ] **No reranking, no BM25, no query rewriting** — naive is the requirement
- [ ] Generation behind an OpenAI-compatible interface, default Ollama
- [ ] Structured output conforming to `AnswerObject`
- [ ] `RetrievalTrace` populated including excluded candidates with reasons
- [ ] Langfuse instrumentation on every model call
- [ ] Never writes to trace tables

---

## Task 8: Verification engine (Go)

**Depends on:** Tasks 3, 6, 7

The phase's reason for existing.

- [ ] Locator resolution: corpus ID + locator → exactly one chunk
- [ ] Quote match: exact substring containment after NFC normalisation, same function as ingestion
- [ ] Tier check against the **resolved profile**, not the tier Python claimed
- [ ] License check refuses non-permitting chunks
- [ ] Citation to a corpus not in the sent FilterSpec fails immediately
- [ ] Empty `citations` on any argument fails the answer
- [ ] Regenerate once on failure with reasons fed back; degrade on second failure
- [ ] Degraded output is "I can't source this adequately" with no partial unverified content
- [ ] `VerificationResult` persisted per citation
- [ ] p95 under 200 ms on the Phase 1 corpus

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
- [ ] Citations render with corpus, edition, locator, and tier
- [ ] `contrary` citations render with their label
- [ ] `catena ingest` documented

---

## Task 11: Phase 1 acceptance

**Depends on:** all

- [ ] Ten questions covering UC-1 to UC-5 run end to end
- [ ] **Zero unverified citations in output** — the phase's hard gate
- [ ] UC-2 (silent corpus) produces an honest non-answer
- [ ] UC-3 (civil magistrate) returns 1788 American text
- [ ] UC-4 (creation days) flags contested, does not resolve
- [ ] UC-5 (fabricated citation) caught, regenerated, degraded, and logged
- [ ] `docker compose up` from a clean clone reproduces all of the above
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
