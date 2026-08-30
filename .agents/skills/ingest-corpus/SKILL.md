---
name: ingest-corpus
description: Add a new corpus to Berean — acquiring sources, verifying the edition, structural chunking, metadata enrichment, and embedding. Use when adding any confessional document, church order, patristic work, or Scripture translation to the index.
---

# Ingesting a corpus

Ingestion is where correctness is won or lost. A wrong edition or a missing license field
propagates silently into every answer that cites the corpus.

## 1. Verify the edition before anything else

Confirm which edition the tradition actually holds. This is not a formality.

The PCA holds the **1788 American revision** of the WCF, not the 1646 original; they differ on the
civil magistrate. OPC and PCA both hold the WCF but permit different exceptions.

Verify by checking a known point of divergence by hand against a reference. For the Westminster
Confession, WCF ch. 23 is the diagnostic. Do not trust a source's own label.

Record the provenance URL and retrieval date.

## 2. Confirm the license permits ingestion

Check [docs/CORPUS-POLICY.md](../../../docs/CORPUS-POLICY.md).

**Ingestion is not quotation.** A quoting allowance does not authorise embedding — that reproduces
the whole work regardless of how little is displayed. If the text is under copyright, it does not
go in the database. Full stop.

Determine the `license` and `attribution` values now. They are required fields.

## 3. Assign an edition-specific corpus ID

Format: `<work>-<edition>-<qualifier>`.

- `wcf-1788-american` ✓
- `wcf` ✗ — this is a bug, not a shorthand

## 4. Chunk on structural boundaries

**Never naive fixed-token splitting.** The structure is the semantics.

| Document type | Chunk unit | Locator |
| --- | --- | --- |
| Confession | Numbered section | `WCF 7.2` |
| Catechism | Question + answer, never split | `WSC Q&A 1` |
| Church order | Numbered paragraph | `BCO 21-4` |
| Scripture | Verse | `Gen 1:1` |
| Aquinas | Question / objection / reply | `ST I-II q.94 a.2` |

If a document's structure does not fit these, work out the right unit and document it here before
writing the parser.

## 5. Populate all thirteen metadata fields

```
corpus_id, work, author, era, tradition, locator, language,
text_form, edition, license, attribution, embedding_model, dim
```

`language` and `text_form` are required even for English-only corpora and even though
original-language support is Phase 3–4. Backfilling means re-ingesting (ADR-0008).

`author` may be null for corporate documents. Nothing else may be.

## 6. Normalise to NFC

Use the shared normalisation function — the same one verification uses. A mismatch between
ingestion and verification normalisation produces quote-match failures on visually identical text,
and that is genuinely miserable to diagnose.

For Hebrew, store both pointed and unpointed forms.

## 7. Embed and verify

Embedder is behind an interface. Write `embedding_model` and `dim` on every chunk.

Then check by hand:

- Retrieve two known locators and read them. Do they read correctly and completely?
- Is a catechism answer attached to its question?
- Does a distinctive phrase from the edition-specific text appear?
- Re-run ingestion: is it idempotent?

## Checklist

- [ ] Edition verified by hand at a known point of divergence
- [ ] License permits ingestion, not merely quotation
- [ ] Corpus ID is edition-specific
- [ ] Chunked on structural boundaries
- [ ] All thirteen metadata fields populated
- [ ] NFC-normalised with the shared function
- [ ] Idempotent on re-run
- [ ] Two locators spot-checked by reading them
