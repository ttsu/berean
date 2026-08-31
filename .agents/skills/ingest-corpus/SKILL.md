---
name: ingest-corpus
description: Add a new corpus to Berean — acquiring sources, verifying the edition, structural chunking, metadata enrichment, and embedding. Use when adding any confessional document, church order, patristic work, or Scripture translation to the index.
---

# Ingesting a corpus

Ingestion is where correctness is won or lost. A wrong edition or a missing license field
propagates silently into every answer that cites the corpus.

## 0. The rule that has no exceptions

**No corpus text is ever committed to this repository** — not public-domain text, not permissively
licensed text, not a fixture, not a golden set (ADR-0014). If you are about to `git add` something
containing corpus text, stop.

What is committed, per corpus:

```
corpora/<corpus-id>/manifest.yaml       provenance, licence, edition check
corpora/<corpus-id>/fingerprints.txt    <locator>  <sha256-of-normalised-text>
tools/acquire/<corpus-id>.py            the acquisition script
```

Text lives in gitignored `/data/`. All of `/data/` is ignored, with no negation patterns, so
there is no path by which a stray file becomes committable.

## The pipeline

Acquisition and ingestion are separate, and the split matters: acquisition is messy, one-time, and
human-supervised; ingestion is deterministic and repeatable.

```
fetch → extract → segment → normalise → verify → stage   (acquisition, Task 4)
                                                  ↓
                                    enrich → embed → load  (ingestion, Task 5)
```

Each acquisition stage is independently re-runnable and idempotent. Ingestion reads staged records
only — it never parses an upstream format and never touches the network.

**First acquisition of a corpus uses `--bless`:** run the pipeline, verify the edition by hand,
then write the manifest and fingerprints. Every run after that verifies against them, and a
mismatch is a hard failure with a diff summary. Never bless your way past a mismatch you have not
understood — that is the one action in this process that discards a human verification.

## 1. Verify the edition before anything else

Confirm which edition the tradition actually holds. This is not a formality.

The PCA holds the **1788 American revision** of the WCF, not the 1646 original; they differ on the
civil magistrate. OPC and PCA both hold the WCF but permit different exceptions.

Verify by checking a known point of divergence by hand against a reference. For the Westminster
Confession, WCF ch. 23 is the diagnostic. Do not trust a source's own label.

Record the divergence in the manifest as **quoted text**, not a checkbox. A checkbox records that
someone once believed the edition was right; the quoted text lets the next person check.

**Take the bare text, never a modern edition's apparatus.** A 17th-century confession is public
domain, but a contemporary edition's additions may not be: footnotes, cross-references, modernised
spelling, and especially the selection and arrangement of proof texts can carry a fresh copyright
over public-domain material. Record which edition you took from.

Record the provenance URL, an archive fallback URL, and the retrieval date.

## 2. Confirm the license permits ingestion

Check [docs/CORPUS-POLICY.md](../../../docs/CORPUS-POLICY.md).

**Ingestion is not quotation.** A quoting allowance does not authorise embedding — that reproduces
the whole work regardless of how little is displayed. If the text is under copyright, it does not
go in the database. Full stop.

Determine the `license` and `attribution` values now. They are required fields.

## 3. Assign an edition-specific corpus ID

Format: `[<tradition>-]<work>-<edition>[-<qualifier>]` — prefix the tradition where the work is
denomination-specific (`pca-bco-2024`), omit it where it is not (`wcf-1788-american`).

- `wcf-1788-american` ✓
- `wcf` ✗ — this is a bug, not a shorthand

## 4. Segment on structural boundaries

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

## 6. Normalise — the segment and normalise stages

Segmentation and normalisation both happen in acquisition, before fingerprints are computed. That
ordering is why per-chunk fingerprints mean anything: they are hashes of the exact normalised text
that will be inserted.



Follow the normalisation contract in INTEGRATION-SPEC and assert the shared test vectors. Ingestion
is Python and verification is Go, so there is no single shared function — the vectors are what keep
the two implementations honest. A mismatch produces quote-match failures on visually identical text,
and that is genuinely miserable to diagnose from the symptom.

For Hebrew, store both pointed and unpointed forms.

## 7. Verify, then embed

Ingestion re-checks every staged record against the committed fingerprints before insert, and
refuses anything that does not match what was blessed. A fingerprint mismatch means the text
changed, the normalisation changed, or the segmentation changed — all three are worth stopping for.

Embedder is behind an interface. Write `embedding_model` and `dim` on every chunk.

Then check by hand:

- Retrieve two known locators and read them. Do they read correctly and completely?
- Is a catechism answer attached to its question?
- Does a distinctive phrase from the edition-specific text appear?
- Re-run ingestion: is it idempotent?

## Checklist

- [ ] **No corpus text staged for commit** — manifest, fingerprints, and script only
- [ ] Edition verified by hand at a known point of divergence, recorded as quoted text
- [ ] Bare text taken; no modern edition's apparatus or proof-text selection
- [ ] Licence permits ingestion, not merely quotation, and is recorded rather than assumed
- [ ] Archive fallback URL recorded alongside the source URL
- [ ] Corpus ID is edition-specific
- [ ] Segmented on structural boundaries
- [ ] All thirteen metadata fields populated
- [ ] Normalised per the contract, at the recorded `normalisation_version`
- [ ] Fingerprints written on `--bless`, and a plain re-run verifies clean
- [ ] Idempotent on re-run
- [ ] Two locators spot-checked by reading them
