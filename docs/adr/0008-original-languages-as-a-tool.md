# ADR-0008: Hebrew and Greek are a deterministic tool, not a retrieval corpus

- **Status:** Accepted
- **Phase:** implemented 3–4, but **metadata implications are Phase 1**

## Context

Original-language support looks like "add another corpus." It is not, and treating it that way
fails in four ways that are hard to detect:

- **Embeddings are weak.** Multilingual models are trained on modern Greek and Hebrew, not Koine
  and Biblical Hebrew. Similarity degrades badly and silently.
- **Morphology defeats lexical search.** Greek is heavily inflected; Hebrew is root-and-pattern.
  λόγος / λόγου / λόγῳ are three unrelated tokens to BM25.
- **Unicode normalisation will bite.** Greek diacritics have multiple encodings, final sigma
  varies, Hebrew has consonants, pointing, and cantillation as separate codepoints. Quote-match
  verification fails on visually identical text.
- **Hallucination risk is much higher** — plausible Greek that is not in the text, confident false
  lexical ranges.

## Decision

Ingest morphologically tagged texts — **OSHB** (CC-BY, Leningrad) and **SBLGNT** — where every
word carries lemma, parsing, and Strong's number. Original-language queries become
**deterministic lookups keyed on lemma and locator**, never vector search. Pair with
public-domain lexica (BDB, LSJ, Thayer's) so word meanings are retrieved, never generated.

The LLM composes the argument. It never supplies the linguistic data.

Normalise to NFC; store pointed and unpointed forms. Handle BiDi properly in mixed-direction UI.

**Theological guardrail:** the word-study fallacy — etymology as meaning, "the Greek *really*
means…" — is the most common abuse of original languages and an LLM reproduces it fluently.
Validation must require lexical claims to cite a lexicon entry and flag arguments resting solely
on etymology.

## Alternatives rejected

- **Treat original-language text as another RAG corpus.** Fails silently on all four counts above.
  Silent failure in the component whose job is preventing confident nonsense is the worst possible
  outcome.
- **NA28 / BHS as base texts.** Copyrighted. SBLGNT, Tyndale House GNT, and OSHB are usable.

## Consequences

Turns the worst hallucination surface into a database query. Roughly a two-week addition once
Phase 1 works.

**Phase 1 obligation:** tag `language` and `text_form` in chunk metadata from day one, or the
corpus needs re-ingesting. TR vs critical text is itself a denominational commitment for some
traditions in scope, so text-form is not a technicality.
