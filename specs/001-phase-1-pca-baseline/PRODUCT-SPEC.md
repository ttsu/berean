# Phase 1 — PCA Baseline: Product Specification

Business and functional requirements. No implementation detail. Technical requirements are in
[TECHNICAL-SPEC.md](TECHNICAL-SPEC.md); contracts in [INTEGRATION-SPEC.md](INTEGRATION-SPEC.md).

## Product overview

Berean answers theological and ecclesiological questions in a way that is *accountable to a
tradition*. The user selects a denomination; that selection determines which documents are
authoritative, and every claim resolves to a real source before it is shown.

Phase 1 proves the single hardest and least glamorous part: **that citations verify end to end**.
One tradition, one corpus, no UI, no cleverness in retrieval. If verification does not work on
30,000 words of Westminster with a naive retriever, no amount of hybrid search will save it.

Phase 1 is deliberately not impressive. Its output is a CLI transcript and a stored trace.

## Who this is for

Phase 1 has one user: **the developer**, verifying the core mechanism.

The eventual users — pastors, elders, seminarians, and serious laypeople who want an answer that
is honest about which tradition it is speaking from — are out of scope until Phase 4.

## Scope

**One tradition:** PCA.

**Binding corpus:** Westminster Standards — WCF, WLC, WSC — **1788 American revision**.

**Governing corpus:** *Book of Church Order*, current edition.

**Advisory corpus:** the PCA's 28th General Assembly (2000) creation study committee report, and
Calvin's *Institutes* (1559, Beveridge translation).

**Scripture:** WEB, retrieval only. Locators stored, no display-translation integration.

Everything else — the other seven traditions, the Fathers, original languages, hybrid retrieval,
reranking, a web UI, conversation memory, comparative mode, steelman mode — is out of scope.
Retrieval is naive dense search on purpose, so Phase 2 has a real baseline to measure.

The *Institutes* is in scope because UC-6 requires it. A descriptive answer needs a source that
carries no binding authority, and without one the descriptive slot — half of ADR-0016's design —
ships unexercised. The 2000 report alone would not do it: its expository body is entangled with the
contested machinery UC-4 tests, so a failure there would not distinguish the two.

## Functional requirements

1. **Corpus ingestion.** A developer can ingest the Westminster Standards and BCO from source
   files into the system, with structural chunking and complete metadata.
2. **Profile selection.** The system loads a PCA profile assigning a stance — `binding`,
   `governing`, `advisory`, `contrary`, `excluded` — to each corpus.
3. **Question answering.** A developer submits a theological question via CLI and receives a
   structured answer: a position, arguments with citations, and a confidence with a stated reason.
4. **Citation verification.** Every citation is checked before display. Any citation whose locator
   fails to resolve, whose quote does not match the source, whose tier is not permitted by the
   profile, or whose license does not permit serving, fails the answer.
5. **Graceful degradation.** When verification fails, the system regenerates once. If it fails
   again, it responds "I can't source this adequately" rather than showing unverified content.
6. **Trace output.** Every response produces a stored trace: the retrieval query, candidates
   retrieved with scores, what the profile excluded and why, and each verification check with its
   outcome.
7. **Edition correctness.** The system distinguishes the 1788 American revision from the 1646
   original. A question about the civil magistrate returns the American text.

## Use cases

**UC-1 — A question with a clean confessional answer.**
"What does the Westminster Confession say about assurance of salvation?" Answer cites WCF 18,
tier `binding`, quotes verify verbatim, trace shows the retrieval path.

**UC-2 — A question the corpus cannot answer.**
"What is the PCA's position on cremation?" The Standards are silent. The system says so rather
than assembling a plausible answer from adjacent material. **This is a pass, not a failure.**

Its output is distinct from a degraded one: every content slot empty, `no_answer_reason` carrying
the model's own brief statement of why, and an outcome of `VERIFIED` rather than `DEGRADED`. The
two must not render alike or read alike — the corpus being silent and verification refusing to ship
are opposite events.

**UC-3 — Edition sensitivity.**
"What does the Confession teach about the civil magistrate's authority over the church?" The
answer reflects the 1788 American revision. Returning 1646 text is a correctness failure.

**UC-4 — A contested locus.**
"How long were the days of creation?" The PCA's 2000 study committee permitted multiple views.
The system flags the locus as contested and reports the state of the debate. It does not pick a
side. **Confident resolution here is the worst possible outcome.**

"Does not pick a side" is structural, not a matter of tone: a contested answer carries no
`arguments` at all, so it cannot assert the tradition's position while flagging that the tradition
has none (ADR-0019).

**UC-5 — Verification catches a hallucinated citation.**
The model cites "WCF 33.4" (does not exist) or misquotes WCF 7.2. Verification fails, the system
regenerates once, then degrades. The trace records the failed check.

The fabrication is **prompt-induced, not injected**, so whether it occurs on a given run is not
under the system's control. What is asserted is therefore the invariant — no citation reaches output
unverified, and any failed check produced exactly one regeneration, recorded in the trace — while
the degradation itself is observed and recorded by hand. If the model never fabricates across the
ten questions, that is a finding about the model worth writing down, not a blocked checkbox.

**UC-6 — A descriptive question.**
"What did Calvin teach about the Lord's Supper?" The answer reports what the source says, cited to
the *Institutes* at `advisory` tier, without asserting it as the PCA's position. Descriptive
answers are a first-class capability, not a degraded affirmative one: refusing this question
because Calvin is non-binding would be a wrong answer to a question that was never doctrinal.
The distinction is structural — the claim occupies the descriptive slot, so the tier floor that
governs affirmative claims does not apply (ADR-0016).

UC-5 is the acceptance case for the entire phase.

## Non-goals

- Any user interface. CLI only.
- Conversation memory. Single-turn.
- Any translation display integration. Locators only.
- Retrieval quality. Naive is correct here; Phase 2 measures it, Phase 3 improves it.
- Any tradition other than PCA.

## Definition of done

- Westminster Standards and BCO ingested with complete, edition-specific metadata.
- Ten hand-written questions covering UC-1 through UC-6 run end to end from the CLI, each with a
  declared expected outcome — the `OverallResult` it must produce, and the `corpus_id` + `locator`
  set its citations must include or exclude. Asserted on identifiers and result codes only, never on
  expected text, so no corpus text enters the repository (ADR-0014).
- Every displayed citation verifies. **Zero unverified citations reach output** — this is the
  phase's single hard gate. It is one-sided on its own, since a system that degrades on everything
  satisfies it perfectly; the expectation table above is what makes it mean something.
- UC-2 and UC-4 produce honest non-answers rather than confident ones.
- UC-6 answers descriptively with citations rather than refusing for want of a binding source.
- A trace is persisted for every response, in a shape the Phase 2 eval harness can consume.
- `docker compose up` brings up Postgres, Langfuse, the gateway, and Catena with no external
  accounts.
