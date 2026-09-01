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
- NET Bible — unusually permissive terms, but the free-use allowance is verse-limited (check
  before ingestion), plus roughly 60,000 translators' notes covering
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

## Local-only — acquired and ingested, served only on the deployer's say-so

- **PCA *Book of Church Order*** — published by the PCA Administrative Committee.
- **PCA 28th General Assembly (2000) creation study committee report** — same publisher.

Neither is assumed permissive, and nothing below retracts the reasoning above: public availability
on a denominational website is not a licence, and a permission to read or quote is not a permission
to ingest. What changed is which act that reasoning governs (ADR-0017).

**Ingestion and serving are separate acts, and serving is the licensed one.** The repository
distributes no text at all (ADR-0014), so the question of redistribution does not arise for this
project. What remains is whether a deployer may serve these documents from their own machine, and
that is the deployer's call to make — exactly as it already is for the ESV, where each deployer
accepts Crossway's terms themselves rather than having this project accept them on their behalf.

So both carry `license: local-only`. They are acquired, ingested, and **refused at verification
check 4 unless the deployer sets an explicit opt-in**, which defaults to off. A clean clone ingests
them and serves nothing from them. The manifest records the terms verbatim as found, with the URL,
in `license_terms` — a licence is evidence, not a label.

The alternative was to block acquisition until the PCA replied, which would have stopped the BCO
(the profile's only `governing` corpus), the 2000 report (its only `advisory` corpus and the
document establishing `creation-days`), and — because a `contested` entry whose `ruling_source` is
absent is a load error — the PCA profile itself. That is most of Phase 1 waiting on correspondence.

If the PCA answers, the enum value changes to whatever the answer supports and the opt-in disappears
for these corpora. **This is not a general licence to ingest first and ask later.** It applies to a
corpus whose terms are *unstated*, never to one whose terms are *restrictive* — ESV and NIV remain
barred from ingestion outright, and no deployer setting changes that.

## Licence values

`license` is a closed enum, not free text. A free-text licence reduces check 4 to "the string is
non-empty", which is a check that reports success while evaluating nothing.

| Value | Meaning | Servable |
| --- | --- | --- |
| `public-domain` | Out of copyright, or dedicated to the public domain | Always |
| `cc-by` | Attribution required; carried in `attribution` | Always |
| `cc-by-sa` | Attribution and share-alike | Always |
| `local-only` | Terms unstated; the deployer decides | Only under the opt-in |
| `refused` | Examined and rejected | Never |

`refused` exists so a corpus can be recorded as considered-and-rejected rather than merely absent.
An unrecognised value fails at insert.

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
enforced by the staged-file guard in PLAN Task 1. The `.gitignore` entry on `/data/` is the first
line of defence, not the enforcement: the rule also covers fixtures, test data and golden sets,
which live outside `/data/`, and the golden set is the likeliest place a licensed text gets in.

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

Every chunk carries `license` (from the enum above) and `attribution`. This makes the attribution
page generate mechanically and lets verification refuse unlicensed content programmatically.

Adding a corpus without these fields populated is a blocking review failure.

## Naming note — the BSB

The Berean Standard Bible was placed in the public domain in April 2023 and is otherwise an
attractive choice. Given the product name, embedding it invites an assumed affiliation with
berean.bible. Either pick a different translation (WEB is the current default) or ship a clear
disclaimer.
