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
- Vatican.va documents (permissive)
- Vulgate
- KJV, ASV, WEB
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
- NA28, BHS (use SBLGNT, Tyndale House GNT, OSHB instead)

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

## Per-chunk license metadata

Every chunk carries `license` and `attribution`. This makes the attribution page generate
mechanically and lets verification refuse unlicensed content programmatically.

Adding a corpus without these fields populated is a blocking review failure.

## Naming note — the BSB

The Berean Standard Bible was placed in the public domain in April 2023 and is otherwise an
attractive choice. Given the product name, embedding it invites an assumed affiliation with
berean.bible. Either pick a different translation (WEB is the current default) or ship a clear
disclaimer.
