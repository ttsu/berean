# ADR-0015: Contested loci cross the boundary; profile identity does not

- **Status:** Accepted (amended by ADR-0019 — a contested locus additionally requires `arguments` to be empty. The omission check decided here is unchanged; ADR-0019 closes the opposite direction, which this ADR did not consider)
- **Date:** 2026-08-31
- **Phase:** 1 — cheap while the proto is pre-consumer (ADR-0013), a breaking change after

## Context

UC-4 requires the system to flag a contested locus and report the state of the debate without
picking a side. SHARED §8 calls false confidence on genuine intramural disagreement worse than
having no profile at all, and the product spec calls confident resolution here "the worst possible
outcome". It is the use case the product's trustworthiness rests on.

It was also unimplementable as specified. `AnswerObject.contested` was authored by Python;
`filter_spec` was spec'd to resolve to corpus IDs, tiers and weights **and nothing else**, with a
unit test enforcing it; and Go's post-receipt overwrite list covered only `confidence.reason`. The
profile's `contested` block therefore never crossed the boundary in any direction. `is_contested`
could only ever be a model guess, and the denomination's ruling could never appear in an answer.
No task implemented it, and Task 11 asserted the use case passes.

Fixing it forces a question the specs had ducked: what is `filter_spec` actually protecting? The
stated rule is that Python "must be able to serve the request knowing nothing about who asked or
which tradition it is". Read literally that forbids contested loci, because a tradition's open
questions identify it. But read literally it also forbids the field as it already stands: a
`corpora` list naming `wcf-1788-american` at `binding` alongside the BCO and Trent at `contrary`
fingerprints the PCA more precisely than any locus list would. The rule cannot mean what it says,
so what it means has to be decided.

## Decision

**Contested loci cross the boundary as a sibling of `filter_spec`. Profile identity does not.**

The boundary refuses a profile *identity* — a name, a user, a session — that Python could branch
on, key state to, or log as a user attribute. It does not refuse tradition-shaped *content*, which
it already carries in every corpus ID. A locus and a locator are content.

Three consequences follow, and they are the decision as much as the sentence above is.

**Pointers, not prose.** The request carries `{ locus, ruling: { corpus_id, locator } }`. Python
resolves the pointer through ordinary retrieval and grounds `state_of_debate` in the passage it
reads. The profile's `contested` entry likewise holds a `ruling_source` rather than a hand-typed
ruling — that string was corpus text copied into a profile, which duplicates a document the system
can already quote, goes stale silently, and is checkable against nothing.

**The status is declared; the content is retrieved.** What cannot be derived from text is that a
locus is open. Sparse retrieval is three-way ambiguous — "genuinely contested", "never addressed",
and "our corpus is thin" are indistinguishable, though UC-2 and UC-4 demand different behaviour
from that signal. A document's standing within a tradition is a polity fact no document
self-declares, which is precisely what a profile exists to record. Everything the user reads,
however, comes from the corpus and verifies verbatim.

**Verification, not authorship.** `contested.locus` must be one of the loci sent; the ruling must
be cited; its quote must match verbatim. A verified citation that resolves to a ruling while
`is_contested` is false fails — the system's only omission check, added because every other check
catches fabrication instead. All failures take the ordinary path: regenerate once, then degrade.
Go does not rewrite the answer.

## Alternatives rejected

- **Derive contestedness from the corpus text alone.** The most attractive option, because it needs
  no declared list and no per-tradition maintenance, and because the system's whole thesis is that
  claims come from sources. Rejected on three grounds. In Phase 1 the evidence is not in the corpus:
  the acquisition list was WCF/WLC/WSC 1788, BCO, WCF 1646 and WEB, none of which record the 2000
  ruling, while WCF 4.1's "in the space of six days" reads as settled and points the wrong way. Even
  with the report ingested, the three-way ambiguity above remains. And a model that fails to notice
  a locus is contested has fabricated nothing, so no check fires — the failure mode with the highest
  stated cost in the product would be the one with no verification story. The list is what supplies
  one. Task 4 now acquires the report, so the *content* is derived from text; only the status is not.
- **Go authors the contested block post-receipt, like `confidence.reason`.** Keeps `filter_spec`
  closed and needs no request change. Rejected because it makes the trust boundary an author of
  theological content, and because it does not actually work: Python, knowing nothing of the locus,
  still resolves it in `position`, so Go would be bolting a flag onto confident prose — or editing
  that prose, which is worse. A verifier that edits what it verifies is no longer a verifier.
- **Carry the loci inside `filter_spec`.** Fewer fields. Rejected: `filter_spec` is retrieval policy
  and contested loci are generation context, so the field would mean two things, and Task 6's
  resolution rule and its unit test — a guard worth keeping intact — would have to be weakened to
  admit something they were written to exclude.
- **Have Go resolve the ruling text and send the quote.** Guarantees the model sees the exact
  wording. Rejected: it inverts who owns retrieval, and it makes the profile engine depend on
  locator resolution that lives downstream of it, which is a dependency cycle of the kind this plan
  has already had to unpick twice.

## Consequences

Contested handling becomes verifiable rather than asserted, which is the same shape as every other
claim in the system: Python generates, Go checks against something known. No new verification
machinery — the locus check reuses the unsent-corpus rule and the quote check reuses NFC substring
containment.

A contested locus now requires its establishing document to be ingested, which bounds a tradition's
`contested` list by its corpus. This is the intended constraint and it has teeth: it is why Task 4
gained the 2000 report, and why adding a locus is a corpus decision rather than a profile edit. A
tradition whose ruling is unavailable gets an honest "the establishing document is not ingested
yet" instead of an invented one.

The proto gains a request field and an answer field. Free now, breaking later — an argument for
landing the `excluded` slot in the same change while ADR-0013's pre-consumer window is open.

Two things would cause us to revisit. If the omission check's blind spot — a contested answer
citing neither the ruling nor anything reaching it — turns out to be common once Phase 2 measures
it, the detection side needs more than a citation intersection. And if a later tradition's
contested list grows large enough that sending it inflates every request, the loci would need
narrowing by retrieval before dispatch, which reopens the ordering between filtering and
generation context.

## Documents updated

- `specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md` — `contested_loci` request field, `Contested`
  answer type, the four contested verification constraints, and `ruling_source` in the profile schema
- `specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md` — the worked PCA profile, and the narrowed
  claim about what crosses the boundary
- `specs/001-phase-1-pca-baseline/PLAN.md` — Task 4 acquires the 2000 report and segments its
  recommendations; Tasks 6, 7, 8 and 11
- `.agents/skills/add-tradition-profile/SKILL.md` — `ruling_source`, and the rule that a locus needs
  its establishing document ingested
- `docs/CORPUS-POLICY.md` — BCO and the 2000 report recorded as unclassified and gating
- `docs/GLOSSARY.md` — `contested` bound to the profile and the corpus
