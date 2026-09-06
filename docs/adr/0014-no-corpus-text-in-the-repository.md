# ADR-0014: No corpus text in the repository, from any source

- **Status:** Accepted (`edition_check` amended by ADR-0021)
- **Date:** 2026-08-30
- **Phase:** 1 — cheap now, and expensive to reverse once git history carries text

## Context

Phase 1 needs the Westminster Standards, the BCO, and the WEB text on disk before anything can be
ingested. The obvious approach is to commit them: they are small, mostly public domain, and
committing makes a clean clone reproducible, which the acceptance test wants.

The problem is that "mostly" does the work in that sentence. Committing requires a licensing
judgement per corpus — public domain by age, explicitly dedicated, denominationally copyrighted,
permissively licensed but with conditions — and that judgement has to be made correctly every time a
corpus is added, indefinitely, including for traditions nobody has scoped yet. It is made by whoever
is adding a corpus, at the moment they are focused on parsing it rather than on licensing.

Two properties make the failure mode worse than usual. Publishing to a public repository is
distribution, which is the act copyright actually restricts, and it is the reason ADR-0007's
"you cannot grant rights you do not hold" bites at all. And git history is permanent: a corpus
committed in error is not removed by deleting it, but by rewriting published history.

## Decision

**No corpus text enters this repository, from any source, whatever its licence.** Not in `data/`,
not in fixtures, not in test data, not in golden sets.

The repository carries, per corpus:

- a **manifest** — source URL, archive fallback, retrieval date, licence, attribution, the edition
  diagnostic and the hash of the text its verifier read, and the normalisation contract version;
  ADR-0021 amended this bullet, which formerly quoted the divergent text into the manifest;
- a **fingerprints file** — one `<locator>  <sha256-of-normalised-text>` per line;
- an **acquisition script**.

**What the rule does not reach: naming a phrase.** Clarified 2026-09-04, when the catechism
adapters landed. An edition diagnostic has to be described somewhere a human can act on — WLC 109 is
verified by confirming that "tolerating a false religion" is *absent*, and WSC 6 by confirming "Holy
Ghost" is *present* — and the adapter's docstring is where the person about to bless it will look.
A phrase of a few words, named as the marker a check turns on, is not the text of the work and does
not put the work in the repository. The precedent was already here: the confession's adapter names
"nursing fathers" for the same purpose.

The boundary is quantity and purpose together. Naming the clause a check turns on is allowed;
quoting a section, an answer, or a passage is not, however short and whatever its licence — which is
the case ADR-0021 decided when it refused to commit the diagnostic's own text and kept only its
hash. If a judgement about which side a string falls on ever feels close, it is the wrong side: this
rule exists to be uniform, and a close call is the per-corpus reasoning it was written to remove.

Text is acquired by a pipeline — fetch, extract, segment, normalise, verify, stage — into gitignored
local storage. Structural chunking moves into acquisition, because per-chunk fingerprints are only
meaningful once chunking has happened.

The fingerprints are what replace the committed copy, and they are a stronger guarantee than one:
every acquisition must reproduce hashes matching the blessed manifest, which proves both that the
text is exactly what was hand-verified and that normalisation is deterministic across machines. A
committed copy would prove neither.

This generalises ADR-0004. That decision split retrieval from display for copyrighted Bibles —
store locators, fetch text. This applies the same shape to every corpus rather than only to the
ones that force it, which is what makes the rule uniform instead of piecemeal.

## Alternatives rejected

- **Commit public-domain corpora, fetch the rest.** More permissive, and better for reproducibility
  — the clean-clone acceptance test would need no provisioning step. Rejected because the line runs
  through a licensing judgement rather than around it: it must be re-made per corpus forever, cannot
  be checked mechanically, and its failure mode is a permanent history rewrite. A bright line that
  is slightly too strict is worth more than a correct line that has to be redrawn by hand each time.
- **Commit everything and rely on personal non-commercial use.** ADR-0007 forecloses this: the
  binding constraint is the Apache-2.0 grant made to others, not the author's own use.
- **Git LFS, GitHub release assets, or a separate data repository.** All three solve size, none
  solves licensing — a release asset or a second public repo is as published as a committed file.
  Relocating distribution is not avoiding it.
- **Commit compressed or encoded text.** Same act, worse diffs, and it defeats the mechanical check.

## Consequences

The clean-clone acceptance test gains a provisioning step: clone, acquire, then `docker compose up`.
This is consistent with the amended portability rule, which already separates first-run provisioning
from steady-state operation, and Tasks 1 and 11 carry it.

Acquisition depends on third-party availability, which is a real fragility for a project reading
from denominational websites. Three mitigations: an archive fallback URL in every manifest,
`--from-file` for a deployer supplying their own copy, and the fingerprints — which let anyone
holding the text prove it is the right text, whatever route it arrived by.

A change to the normalisation contract invalidates every fingerprint file. `normalisation_version`
records what a manifest was blessed under, and bumping it means re-blessing every corpus. That cost
is deliberate: it makes a silent change to normalisation impossible.

Edition verification happens once, by a human, and is recorded as the hash of the text they read
rather than as a checkbox or as the text itself (ADR-0021). Every subsequent acquisition verifies
mechanically, and `--show-diagnostic` reprints what the verifier read without committing it.

A note on the fingerprints themselves: a hash is not the expression, and cannot be inverted to
recover it. For a very short chunk a hash could confirm a guess someone already holds, but
confirming a guess is not distribution, and the alternative — omitting fingerprints — would give up
reproducibility entirely.
