# Glossary

Agent-facing. Get these wrong and the output is subtly incorrect in ways tests will not catch.

## Project terms

**Catena** — internal codename for the retrieval and citation service (`services/catena`). A
patristic term for a chain of sourced quotations. Not a user-facing name.

**Profile** — a document assigning a *stance* to each corpus for a tradition. Presets and
fine-grained user control are the same object: a preset is a pre-populated profile, and
fine-grained control is letting the user edit it. **Build the schema once.**

**Resolved filter spec** — what Go sends Python: corpus IDs by tier plus tier weights. Never the
profile itself. Profile resolution is policy and stays in Go.

**Trace** — the record of what happened for one response: rewritten query, candidates retrieved,
reranker behaviour, profile exclusions, checks run. Stored per response. It is simultaneously the
eval dataset and the audit log.

**Show the work panel** — the UI surface for the trace. **A log, not a narrative.**

## Authority tiers

A stance assigned per corpus, not an include/exclude filter.

| Tier | Meaning | PCA example |
| --- | --- | --- |
| `binding` | Confessional standards | WCF, WLC, WSC |
| `governing` | Polity and church order | BCO |
| `advisory` | Respected but non-binding | Calvin, Bavinck, Vos |
| `contrary` | Retrievable, must be labelled as another tradition's position | Council of Trent |
| `excluded` | Explicitly repudiated by the tradition | Federal Vision (2007 report) |

`excluded` is the tier that justifies the whole model: "this view was examined and rejected by
your denomination in 2007" is a valuable answer a naive filter cannot produce.

**Scripture is tiered like any other corpus**, at the stance its profile assigns — `binding` by
default (ADR-0011). It is not a special case in retrieval or verification: a verse citation passes
the same four checks as a confessional one.

**`contested`** is not a tier — it is a flag on a *locus*, marking genuine intramural
disagreement (creation days, women in diaconal service, subscription boundaries in the PCA).
False confidence here is worse than no profile at all. A tradition's contested list is declared
in its profile and bounded by its corpus: each locus points at the ingested document that
establishes the ruling (ADR-0015). **A contested answer carries no `arguments`** — it quotes the
ruling and describes the debate, and cannot assert the tradition's position while flagging that the
tradition has none (ADR-0019).

**Affirmative and descriptive claims** are the split that tier checking rests on. An *affirmative*
claim says what the tradition holds and lives in `arguments`, so it needs a `binding` or
`governing` citation; `advisory` may corroborate one but never carry it alone. A *descriptive*
claim says what a source teaches — "Calvin held X", "the denomination repudiated Y in 2007" — and
lives in `descriptions`, where any tier is permitted because the claim rests on no authority. The
distinction is structural, never a judgement about what a claim means (ADR-0016).

## Corpus IDs

**Edition-specific, always.** Format: `[<tradition>-]<work>-<edition>[-<qualifier>]`. The tradition
prefix is used where the work is denomination-specific, as a church order is.

- `wcf-1788-american` — correct
- `wcf` — **wrong**, and a bug
- `wcf-1646-original` — a different corpus, `contrary` under a PCA profile
- `pca-bco-2024`
- `calvin-institutes-1559-beveridge` — the 1559 edition in Beveridge's 1845 translation. Both halves
  matter: Battles (1960) is a different text and is in copyright

The PCA holds the 1788 American revision, which differs from the 1646 original on the civil
magistrate. OPC and PCA both hold the WCF but permit different exceptions. Retrofitting edition
specificity is painful; there is no grace period on this.

## Locators

Canonical, per-work, resolvable, stable.

- Scripture: `Gen 1:1`, `Rom 8:28-30`
- Confessional: `WCF 7.2`, `WSC Q&A 1`
- Aquinas: `ST I-II q.94 a.2`
- Church order: `BCO 21-4`
- Calvin's *Institutes*: `Inst. 4.17.10` — book.chapter.section

A locator that does not resolve is a verification failure, not a formatting nit.

## Chunk metadata

Fourteen fields on every chunk: `corpus_id`, `work`, `author`, `era`, `tradition`, `locator`,
`language`, `source_language`, `text_form`, `edition`, `license`, `attribution`, `embedding_model`,
`dim`. `author` is the only nullable one.

`corpus_id` is the edition-specific join key — `work` is a display name and resolves nothing.

The fourteen are stored where they are true — ten on `works`, two on `chunk_embeddings`, and
`locator` on `chunks` — and the `corpus.chunk_metadata` view exposes them together, which is
where to read them. See the Phase 1 INTEGRATION-SPEC, **Chunk metadata contract**.

`language`, `source_language` and `text_form` are required **from day one** even though
original-language support is Phase 3–4 — otherwise the corpus needs re-ingesting (ADR-0008).
`language` is the chunk text as ingested and `source_language` is the work's own: `en` and `la` for
Beveridge's *Institutes*, equal for an untranslated work.

`text_form` and `license` are closed enums. `text_form` is `tr | critical | majority |
not-applicable` — the TR-versus-critical distinction exists only for biblical text, so most of the
Phase 1 corpus is `not-applicable`, and WEB is `majority`. `license` is `public-domain | cc-by |
cc-by-sa | local-only | refused`; see CORPUS-POLICY.

`embedding_model` and `dim` make a model swap a re-index job rather than a schema migration
(ADR-0006).

## Theological terms worth not guessing at

**Text-form** — TR (Textus Receptus) vs critical text. Not a technicality: it is itself a
denominational commitment for some traditions in scope.

**Word-study fallacy** — treating etymology as meaning ("the Greek *really* means…"). The most
common abuse of original languages, and an LLM reproduces it fluently. Lexical claims must cite a
lexicon entry; arguments resting solely on etymology get flagged.

**Steelman mode** — arguing another tradition's position from *its own* sources. A system that can
articulate why Trent condemned imputed righteousness, sourced from Trent, will be trusted far more
on Reformed questions than one that only argues its own side.
