# ADR-0021: The edition diagnostic is verified, not quoted

- **Status:** Accepted
- **Date:** 2026-09-04
- **Phase:** 1 — before a second corpus is blessed, and before any manifest reaches a published branch

## Context

ADR-0014 drew a bright line — no corpus text in this repository, from any source, whatever its
licence — and then carved a single exception into the same decision: the manifest carries "the
edition diagnostic with its divergent text quoted". The reason was good, and the ingest skill states
it plainly. A checkbox records that someone once believed the edition was right; quoted text lets
the next person check.

Task 4 made the exception's cost concrete, because implementing `--bless` forces the question the
contract left open: how much text is `expected`?

Two answers were available and both are bad. An excerpt someone curates has to live somewhere before
the bless can write it, which means a constant in the adapter — corpus text in a *second* committed
place, and code rather than the record becoming the thing that says what a human approved. The
diagnostic locator's whole normalised text avoids that, and was what Task 4 first implemented: 1,254
characters of WCF 23.3 in a public repository.

The second escalates rather than settles. Two Phase 1 corpora are PCA-published and `local-only`
(ADR-0017), so under that rule each manifest commits a full section of a copyrighted document into a
public Apache-2.0 repository — publishing, which ADR-0014 identifies as the act copyright actually
restricts, in the repository ADR-0007 makes a grant from. And choosing between the two answers per
corpus is exactly the per-corpus licensing judgement ADR-0014 exists to remove: made by whoever is
adding a corpus, at the moment they are focused on parsing it rather than on licensing.

The exception was small enough to look free and is not.

## Decision

**The manifest records that a human verified the edition, and what they verified against. It commits
none of the text.**

`edition_check` becomes:

```yaml
edition_check:
  diagnostic: WCF 23.3            # the locator whose text distinguishes this edition
  expected_sha256: <64 hex>       # the hash of the normalised text the verifier read
  verified_by: string
  verified: YYYY-MM-DD
```

What replaces the quoted text is not a checkbox. It is a command:

```
catena acquire --corpus <id> --show-diagnostic
```

which acquires and prints the diagnostic locator's normalised text and its hash, and stages nothing.
`--bless` prints the same thing before it prompts for a name, so the verifier decides on a full
reading rather than on a label. The next person runs the command and reads exactly what the verifier
read.

That is what the quoted text was for, and it is achieved without the repository distributing
anything. Acquiring is a local act; committing is distribution. The difference between them is the
whole of ADR-0014, and it is the difference this decision uses.

## Alternatives rejected

- **Keep the diagnostic locator's whole normalised text.** What Task 4 implemented, and the reason
  this ADR exists. It is a full section per corpus, and for the two `local-only` PCA corpora it is a
  full section of a copyrighted document in a public repository. Rejected on the escalation, not on
  the WCF case, which is public domain and would have been survivable on its own — which is exactly
  how a per-corpus judgement gets made wrong.
- **A curated excerpt of the divergence.** The smallest thing that still reads as a check. It has to
  exist before the bless writes it, so it lives as a constant in the adapter: corpus text in a
  second committed place, and the adapter rather than the manifest becoming the record of what a
  human approved. Rejected for putting the text in two places to reduce it in one.
- **A bounded leading window written by `--bless`** — say the first 400 characters. Mechanical, needs
  no adapter constant, and bounds the exposure. Rejected because it is still text and still
  distribution, because 400 is a number nobody can justify as a principle, and because it fails on
  its own terms for any corpus whose divergence is not in the opening sentence — which would need a
  per-corpus offset, and the per-corpus judgement is back.
- **A hash, and nothing else — drop `edition_check`.** The diagnostic locator's fingerprint already
  catches a swapped edition mechanically, so the check is arguably redundant. Rejected because the
  fingerprint file carries no verifier, no date, and no statement of which locator was the
  diagnostic, and because it reports a changed edition as "WCF 23.3 mismatched" rather than as "the
  edition diagnostic changed". Who checked, when, against what, and a failure that names itself are
  worth four fields.
- **Encrypt or encode the quoted text in the manifest.** Same act, worse diffs, and ADR-0014 already
  rejected it in its own terms.

## Consequences

CLAUDE.md's first hard constraint needs no exception and gets none. The bright line is bright again,
which matters most for the rule's stated property: it needs no per-corpus judgement. The corpus
guard's structural allowance for `manifest.yaml` no longer admits text through the one door it had.

Reading the diagnostic now needs the network, or `--from-file` and a local copy, where before it
needed only a checkout. That is the trade this decision makes, and it is the same trade ADR-0014
already made for every other byte of every corpus.

Every corpus blessed under the old shape must be re-blessed, because the manifest schema changed and
a manifest is written only by `--bless`. Exactly one exists, and this lands before it reaches `main`.

Revisit if a corpus's edition turns out not to be diagnosable at a single locator. The structural
assertions an adapter can make — the WCF's 33 chapters against the 1903 revision's 35 — already
cover the case where the divergence has no single home, and they cost no text either.

## Documents updated

- **`docs/adr/0014-no-corpus-text-in-the-repository.md`** — status becomes
  `Accepted (edition_check amended by 0021)`; the manifest bullet in **Decision** and the closing
  line of **Consequences** no longer say the divergent text is quoted.
- **`CLAUDE.md`** — hard constraint 1 keeps its absolute form, with the manifest named as carrying
  evidence about text rather than text.
- **`specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md`** — the `edition_check` block in the corpus
  acquisition contract, and the paragraph describing what `expected` asserted.
- **`specs/001-phase-1-pca-baseline/ACQUISITION-DESIGN.md`** — the `edition_check` section, which
  argued for the whole-text form.
- **`specs/001-phase-1-pca-baseline/PLAN.md`** — Task 4's manifest and edition-verification items.
- **`.agents/skills/ingest-corpus/SKILL.md`** — step 1's "record it as quoted text" instruction and
  the checklist line that repeats it.
- **`services/catena/src/catena/acquire/manifest.py`** — `EditionCheck` and its validation.
- **`services/catena/src/catena/acquire/pipeline.py`** — the edition check, and what `--bless`
  prints and writes.
- **`services/catena/src/catena/acquire/cli.py`** — `--show-diagnostic`.
- **`Makefile`** — `make bless CORPUS=<id>` and `make show-diagnostic CORPUS=<id>`, so the command
  this decision leans on is as reachable as the one that writes.
