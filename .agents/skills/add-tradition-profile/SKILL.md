---
name: add-tradition-profile
description: Add or modify a tradition profile in Berean — assigning authority tiers to corpora, modelling contested loci, and validating for cross-contamination. Use when adding a denomination or changing which documents a tradition treats as authoritative.
---

# Adding a tradition profile

A profile is not an include/exclude filter. It assigns a **stance** to each corpus, and the
stances that are not "include" are where the value is.

## 1. Assign tiers

| Tier | Meaning |
| --- | --- |
| `binding` | Confessional standards the tradition subscribes to |
| `governing` | Polity and church order |
| `advisory` | Respected but non-binding theologians |
| `contrary` | Retrievable, must be labelled as another tradition's position |
| `excluded` | Explicitly repudiated by this tradition |

**`excluded` is the tier that justifies the model.** "This view was examined and rejected by your
denomination in 2007" is a valuable answer a naive filter cannot produce. Populate it — a profile
with no `excluded` entries has probably not been thought through.

`contrary` and `excluded` entries **require** a `label`. An unlabelled citation at either tier is
exactly the failure the tier system exists to prevent, so the loader treats a missing label as an
error.

**Scripture carries the stance the profile gives it, defaulting to `binding`** (ADR-0011). Set it
explicitly only where the tradition needs something other than the default, and never to `contrary`
or `excluded` — the loader rejects both. What distinguishes traditions here is rarely Scripture's
own stance but what stands alongside it: a profile that marks a magisterium or a confession
`binding` is making that claim through those entries, not by moving Scripture down.

## 2. Get the editions right

Corpus IDs are edition-specific. Two traditions holding "the Westminster Confession" may hold
different texts, or the same text with different permitted exceptions. Check.

## 3. Model contested loci explicitly

Where the tradition genuinely disputes something internally, say so.

```yaml
contested:
  - locus: creation-days
    ruling_source:
      corpus_id: pca-ga28-2000-creation-study
      locator: "Recommendations 1"
```

Point at the document, do not paraphrase it. The entry declares only that the locus is open and
where the ruling lives; the wording the user sees is quoted from the corpus and verified verbatim.
A hand-typed ruling is corpus text copied into a profile — it goes stale silently and can be
checked against nothing.

This means a contested locus requires its establishing document to be ingested. If it is not, the
entry cannot be added; the tradition's `contested` list is bounded by its corpus, and saying "the
establishing document is not ingested yet" is an honest answer where inventing a ruling is not.

For the PCA: creation days, women in diaconal service, subscription boundaries.

**False confidence on a contested locus is worse than having no profile at all.** This is also the
product's best differentiating feature — resolving what the denomination itself has not resolved
destroys the thing that makes it trustworthy.

## 4. Be honest about corpus depth

Coverage is uneven and the UI must not imply parity.

- Reformed, Lutheran, Catholic, Anglican — deep public-domain corpora
- Eastern Orthodox — thinner in English
- SBC — BF&M 2000 is about ten pages, then copyright
- Non-denominational evangelicalism — no confessional corpus at all

If a tradition's corpus is thin, the profile should carry that fact and the UI should surface it.

## 5. Add a golden set

Every tradition needs its own. **A correct Catholic answer on justification is a wrong PCA
answer**, so a shared golden set is not merely insufficient — it is incoherent.

Include cross-contamination tests: assert no Tridentine source appears at `binding` tier under a
PCA profile, and the equivalent for every pair.

## 6. Validate

- [ ] Every corpus ID is edition-specific and exists in the database
- [ ] Every `contrary` and `excluded` entry has a `label`
- [ ] Scripture stance set deliberately, or knowingly left at the `binding` default
- [ ] `excluded` is populated where the tradition has actually repudiated something
- [ ] Contested loci modelled, each pointing at an ingested `ruling_source`
- [ ] Corpus depth honestly represented
- [ ] Golden set added with cross-contamination tests
- [ ] FilterSpec resolution carries no profile name or user identity
