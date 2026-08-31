# Corpus and licensing policy

**Not legal advice.** Get real counsel before publishing anything.

This document is agent-facing and enforcement-relevant. The verification layer refuses to serve
any chunk whose `license` does not permit it, using the same mechanism as tier checking.

## Usable — public domain or permissive

- CCEL: Schaff's *Ante-Nicene Fathers* and *Nicene and Post-Nicene Fathers* (terms vary per text —
  check each)
- Aquinas, *Summa Theologiae*
- Calvin, *Institutes*
- *Book of Concord*
- Westminster Standards (WCF, WLC, WSC)
- Vatican.va documents (terms vary — Libreria Editrice Vaticana asserts copyright over much of
  the corpus; check each before ingestion)
- Vulgate
- ASV, WEB
- KJV (public domain in the US; in the UK under perpetual Crown copyright, printed under letters
  patent — check before shipping to UK deployers)
- OSHB (CC-BY — **requires attribution**)
- SBLGNT (own terms — check before ingestion)
- NET Bible — unusually permissive terms, plus roughly 60,000 translators' notes covering
  text-critical and lexical decisions. For a system that must defend its answers, that note
  apparatus is arguably more valuable than the translation itself, and it is a source the
  verification layer can actually resolve against.

## Off-limits for ingestion

- ESV, NIV
- Most modern critical commentaries
- Most 20th-century systematics
- NA28, BHS (use SBLGNT or OSHB instead)
- Tyndale House GNT — CC BY-NC-ND. The NC term is disqualifying under ADR-0007, and ND is a second,
  independent problem: chunking, embedding, and serving excerpts is plausibly a derivative work.
  See ADR-0012

## Unresolved — acquired by Phase 1, not yet classified

Neither of these appears above, and both are gating. Task 3 makes an insert without `license` fail
at the database level, and the verification layer refuses to serve any chunk whose licence does not
permit it — so an unclassified corpus cannot be ingested at all, and Task 4 cannot complete until
these are resolved.

- **PCA *Book of Church Order*** — published by the PCA Administrative Committee. Task 4 already
  acquires it; the policy has never said on what terms. Resolve before ingestion.
- **PCA 28th General Assembly (2000) creation study committee report** — same publisher, same
  question. UC-4 depends on it (ADR-0015), which makes the answer load-bearing rather than
  academic.

Neither is assumed permissive here. Public availability on a denominational website is not a
licence, and this document's own reasoning on the 500-verse allowance applies: a permission to read
or quote is not a permission to ingest.

## The rule that gets violated first

**No ESV or NIV text anywhere in this repository.** Not in source, not in fixtures, not in test
data, and specifically **not in the eval golden set** — that is the likeliest place it gets in,
because golden sets naturally contain expected passages.

Crossway's terms also bar ESV text from anything published under a Creative Commons license,
which is live the moment docs or datasets are CC-licensed.

## Why the 500-verse allowance does not apply

Crossway permits quoting the ESV up to 500 verses without a formal license, provided the quoted
verses do not exceed half of any one book, do not account for 25% or more of the total work, and
are **not quoted in a commentary or other biblical reference work**. Biblica's NIV terms are
near-identical.

1. **Ingestion is not quotation.** Embedding the full text into a vector database is reproduction
   of the whole work regardless of how few verses are displayed. Biblica explicitly prohibits
   reproduction, modification, distribution, or derivative works beyond the granted permission.
2. **This is a reference work.** An AI answering Bible questions with citations is squarely what
   the carve-out targets. Non-commercial status does not waive it.

**Fair use is not a route.** Non-commercial is one factor of four, not a safe harbour. Factor
three is the whole Bible; factor four is bad given that licensed Bible APIs are a market
rightsholders actively monetise. There is a plausible transformative-use argument for
intermediate copying during embedding, none for serving text back to users. Do not build on it.

## The approach

Retrieval on public-domain text (WEB). Store only verse locators in results. Fetch display text
at render time from a pluggable translation adapter.

**ESV access is bring-your-own-key.** Each deployer accepts Crossway's non-commercial terms
themselves: non-commercial use, primarily personal/church/ministry, standard copyright notice
displayed, an esv.org link on each page, and no sharing or publishing of the access key.

**Never ship a key.** Document the setup; do not automate around the terms.

**Open question:** the ESV API caching clause constrains what may be stored. Resolve before
building the render path.

## No corpus text in the repository

**This repository contains no corpus text, from any source, whatever its licence** (ADR-0014). Not
public-domain text, not permissively licensed text, not fixtures, not golden sets.

The rule is deliberately unconditional. A per-corpus rule would be more permissive and would keep
public-domain text committed for reproducibility, but it requires a licensing judgement on every
corpus addition, forever — and those judgements get made in a hurry by whoever is adding a corpus.
An unconditional rule needs no judgement, holds for corpora nobody has considered yet, and can be
enforced mechanically by a single `.gitignore` entry.

It also means the repository never becomes a distribution channel. Everything in this document about
what may be redistributed applies to publication; with nothing published, the question does not
arise for the repository itself, and the remaining licensing questions are about what a deployer may
ingest and serve locally.

Acquisition is a pipeline (see the acquisition contract in the Phase 1 INTEGRATION-SPEC): the repo
carries manifests, per-chunk fingerprints, and acquisition scripts, and text is fetched to
gitignored local storage. The fingerprints preserve reproducibility without carrying expression.

This generalises what ADR-0004 already established for copyrighted Bible translations — store
locators, fetch text — and applies it to every corpus rather than only the ones that force it.

## Per-chunk license metadata

Every chunk carries `license` and `attribution`. This makes the attribution page generate
mechanically and lets verification refuse unlicensed content programmatically.

Adding a corpus without these fields populated is a blocking review failure.

## Naming note — the BSB

The Berean Standard Bible was placed in the public domain in April 2023 and is otherwise an
attractive choice. Given the product name, embedding it invites an assumed affiliation with
berean.bible. Either pick a different translation (WEB is the current default) or ship a clear
disclaimer.
