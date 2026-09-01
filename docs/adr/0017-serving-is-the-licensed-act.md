# ADR-0017: Serving is the licensed act; PCA-published corpora are acquired on deployer terms

- **Status:** Accepted
- **Date:** 2026-09-01
- **Phase:** 1 — blocks Task 4, and Task 3 encodes it in the schema

## Context

CORPUS-POLICY records the PCA *Book of Church Order* and the 28th General Assembly (2000) creation
study committee report as unclassified and gating. Neither is on the usable list or the off-limits
one, and the document declines to assume permissiveness: "public availability on a denominational
website is not a licence."

That is the right instinct and it produced an unworkable position, because both corpora are
load-bearing in ways the policy did not weigh:

- The BCO is the PCA profile's **only** `governing` corpus. Without it, check 3's
  `binding | governing` floor is only ever satisfied by `binding`, and the `governing` tier ships
  schema-complete and unexercised alongside `excluded`.
- The 2000 report is the **only** `advisory` corpus and the only document establishing the
  `creation-days` locus. Without it UC-4 is unanswerable and ADR-0015's contested mechanism ships
  untested.
- Worse than either: INTEGRATION-SPEC makes a `contested` entry whose `ruling_source` is absent a
  **load error**. An unclassified report does not degrade UC-4 — it stops the PCA profile loading
  at all, which stops Task 6.

So "unresolved" was not a neutral holding state. It was a decision to block roughly half the phase
on a reply from a denominational agency, measured in weeks and with a real chance of no reply at
all. ADR-0013 already names momentum as the risk this project is most exposed to.

The policy had also conflated two acts that the rest of this repository keeps carefully apart.
ADR-0004 separates *retrieval* from *display* for copyrighted Bibles. ADR-0014 makes the repository
carry no text at all, so **distribution never happens** regardless of licence. What remained
unexamined is that the licence question then bears almost entirely on a third act — serving text
back to a user — and the schema had no way to say "acquired, not servable."

## Decision

**Ingestion is not the licensed act; serving is. Separate them, and default serving to deny.**

Both corpora are acquired and ingested on the same never-distributed footing ADR-0014 already
establishes for every corpus. The deployer, not the repository, decides whether they may be served.

- `chunks.license` stops being free text and becomes a **closed enum**: `public-domain`, `cc-by`,
  `cc-by-sa`, `local-only`, `refused`.
- The BCO and the 2000 report carry `local-only` — acquired lawfully by the deployer for local use,
  with no redistribution claim made by this project or available to it.
- **Verification check 4 permits `local-only` only under an explicit deployer opt-in.** The default
  is deny. A clean clone ingests these corpora and refuses to serve them, so nobody ships PCA text
  by accident and the opt-in is a recorded act rather than an omission.
- `refused` is never servable under any configuration, and exists so a corpus can be recorded as
  examined and rejected rather than merely absent.
- The manifest records the terms **verbatim as found**, with the URL they were found at. A licence
  is evidence, not a label.

The direct precedent is already in this repository and is the reason this is a smaller step than it
first appears: ESV access is bring-your-own-key, where "each deployer accepts Crossway's
non-commercial terms themselves." The same shape applies here — the project automates nothing around
anyone's terms, ships no key and no text, and leaves the acceptance of terms with the party who can
actually accept them.

## Alternatives rejected

- **Block Task 4 until both are classified.** Faithful to the policy as written, and the honest
  reading of "resolve before ingestion." Rejected because it mortgages three acceptance criteria and
  the profile loader to a third party's response time, on the one project variable ADR-0013
  identified as most likely to kill the phase. It also does not actually reduce risk: nothing about
  waiting makes the eventual answer more permissive.
- **Free-text `license`, with check 4 testing non-empty.** The literal reading of the current spec
  and the least work. Rejected outright: it makes check 4 unfalsifiable. A check that reports
  success while evaluating nothing is the exact defect ADR-0016 was written to remove, and shipping
  a second instance of it inside the same verification pipeline would be indefensible.
- **Assume permissive and ingest with a descriptive licence string.** Fastest, and defensible in the
  narrow sense that a denomination publishing its own constitution intends it to be read. Rejected
  because it makes a legal judgement this project has repeatedly refused to make, and because the
  judgement would be invisible: a string in a column, typed once, never reviewed.
- **Substitute a public-domain contested locus so UC-4 survives without the report.** Attractive
  because it would decouple ADR-0015's mechanism from this question entirely. Rejected on the facts:
  the 1788 Westminster corpus contains no ruling that establishes a locus as open, which is exactly
  why ADR-0015 had to add the report to Task 4 in the first place.
- **A per-chunk `servable` boolean instead of an enum.** Simpler to check. Rejected because it
  records the conclusion and discards the reason, so re-deciding a corpus later means re-deriving
  why. The enum is the same check with the evidence retained.

## Consequences

Check 4 becomes a real check with a closed domain, which also makes it testable: the passing and
failing cases are enumerable, and a corpus with an unrecognised licence fails loudly at ingestion
rather than silently at serve time.

The default-deny opt-in has a cost worth stating plainly: **a fresh clone will degrade every
BCO-sourced and report-sourced answer until the deployer opts in**, and that includes UC-4. Task 11
must therefore run with the opt-in set, and the README's clone-to-first-answer path must say so, or
the acceptance run will fail in a way that looks like a verification bug and is not.

This does not weaken CORPUS-POLICY's reasoning about the 500-verse allowance, and it must not be
read as a general licence to ingest first and ask later. ESV and NIV remain barred from ingestion
outright under SHARED §2 — that rule is about ingestion, not serving, and this ADR does not touch
it. What changed is narrower: for a corpus whose terms are *unstated* rather than *restrictive*, the
project now records the uncertainty in the schema and refuses to serve, instead of refusing to
build.

Two things would cause us to revisit. If the PCA responds, the enum value changes to whatever the
answer supports and the opt-in disappears for those corpora — the schema already holds the shape of
either answer. And if `local-only` starts accumulating corpora, that is evidence the project is
using it as a way to avoid licence work rather than to record genuine uncertainty, and the value
should be audited.

**Not legal advice.** CORPUS-POLICY's standing warning applies with full force here.

## Documents updated

- `docs/CORPUS-POLICY.md` — the "Unresolved" section replaced with the `local-only` classification
  and the acquisition/serving split; the licence enum documented; the per-chunk metadata section
  updated
- `specs/SHARED-TECHNICAL-SPEC.md` — §2, the licence enum and the serving opt-in, with the ESV/NIV
  ingestion bar restated so the narrowing is unambiguous
- `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` — chunk metadata contract, the acquisition
  manifest's `license` field, and verification check 4
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — check 4 restated against the enum
- `specs/001-phase-1-pca-baseline/PLAN.md` — Task 3 (enum-constrained column), Task 4 (no longer
  blocked; records terms verbatim), Task 8 (opt-in behaviour), Task 11 (acceptance runs with the
  opt-in set)
- `.agents/skills/ingest-corpus/SKILL.md` — step 2 rewritten around the enum and the serving split
- `README.md` — the opt-in named in the clone-to-first-answer path
