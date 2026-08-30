# ADR-0004: Split Bible retrieval from Bible display

- **Status:** Accepted
- **Date:** 2026-08-29
- **Phase:** 1 — retrofitting this later means re-ingesting the corpus

## Context

The most useful modern translations (ESV, NIV) are copyrighted. Crossway and Biblica both permit
quoting up to 500 verses without a formal license, subject to limits — but both carve out
"commentary or other biblical reference work," and an AI answering Bible questions with citations
is squarely what that carve-out targets.

Two independent reasons the allowance does not cover this project:

1. **Ingestion is not quotation.** Embedding the full text into a vector database reproduces the
   whole work regardless of how few verses are displayed.
2. **This is a reference work.** Non-commercial status does not waive the carve-out.

Fair use is not a route. Non-commercial is one factor of four, not a safe harbour. Factor three
is the whole Bible; factor four is bad given that licensed Bible APIs are a market rightsholders
actively monetise.

## Decision

- Embed and index a **public-domain** translation (WEB). This is the entire retrieval layer.
- Store only **verse locators** in results. Copyrighted text never enters the database.
- At render time, fetch referenced verses from the translation provider's API and display with
  required attribution.
- Translation providers are **pluggable adapters**. ESV access is **bring-your-own-key** — each
  deployer accepts the provider's terms themselves. Never ship a key.

## Alternatives rejected

- **Ingest ESV under the 500-verse allowance.** See above; the allowance does not reach ingestion
  and the reference-work carve-out applies.
- **Ingest and rely on fair use.** No transformative-use argument for serving text back to users.
- **Public-domain translations only, no modern display.** Usable, but a real product cost for no
  legal benefit once retrieval and display are separated.
- **NIV.** No free public API and no self-service display route. Treat as a v2
  "if permission granted" item, never a Phase 1 dependency.

## Consequences

Better architecture regardless of licensing: translation becomes a presentation-layer concern,
the index stays stable when translations are added, and translation becomes a render option
rather than a re-ingest trigger.

**Open:** the ESV API caching clause constrains what may be stored. Verify before building the
render path.

**Not legal advice.** Get real counsel before publishing.
