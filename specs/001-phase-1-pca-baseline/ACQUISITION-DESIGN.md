# Corpus acquisition — design

**Scope:** PLAN Task 4. The acquisition pipeline, and the first corpus through it
(`wcf-1788-american`). The remaining six corpora are follow-on work against this same interface.

This is a working design document. The durable statements belong in
[INTEGRATION-SPEC](INTEGRATION-SPEC.md); where this document decides something the contract did not
anticipate, that decision is folded back into the spec in the same change.

---

## What acquisition is for

The repository carries no corpus text (ADR-0014). It carries evidence *about* text: a manifest, a
fingerprint file, and the code that reconstructs the text from an upstream source. Acquisition is
what turns an upstream document into staged records whose per-chunk hashes match what a human once
verified by hand.

That framing decides most of what follows. Acquisition is messy, one-time, and human-supervised;
ingestion is deterministic and repeatable. The seam between them is a directory of staged records,
and ingestion never crosses back over it to parse an upstream format or touch the network.

---

## Stages and the adapter boundary

```
fetch → extract → segment → normalise → verify → stage
 ▲        ▲          ▲          │          │        │
 └────────┴──────────┘          └──────────┴────────┘
      per-corpus adapter              generic, one implementation
```

Only the first three stages know anything about a particular corpus. The adapter interface is
correspondingly small:

```python
class Adapter(Protocol):
    corpus_id: str
    work: WorkFacts
    def fetch_plan(self) -> FetchPlan:        ...   # source_url, archive_url
    def extract(self, raw: bytes) -> str:     ...   # bytes -> one document string
    def segment(self, doc: str) -> Iterator[Segment]: ...   # -> (locator, text)
```

The adapter also carries `license_terms` — the terms verbatim as found, with the URL — and
`diagnostic`, the edition-check locator. Neither is a `works` column: the first is a manifest field
and the second is the name of a chunk, so neither belongs in `WorkFacts`, and both are per-corpus
facts a human recorded, which is what an adapter is for.

`WorkFacts` carries the work-level half of the chunk metadata contract — `work`, `author`, `era`,
`language`, `source_language`, `text_form`, `edition`, `license`, `attribution` — which is exactly
the set INTEGRATION-SPEC stores on `corpus.works`. Staging writes it beside the records so Task 5
reads those facts rather than re-deriving them from a source it is forbidden to parse.

**An adapter cannot override normalisation.** `catena.normalise` is applied by the pipeline, not by
the adapter. A per-corpus normalisation is precisely the drift the contract exists to prevent, and
an interface that permits it invites it.

### Why the boundary sits here

`extract` and `segment` are separate because they fail differently. Extraction fails on the shape of
a source — wrong element, JavaScript-rendered page, a PDF's column order — and its failure is
visible as garbage text. Segmentation fails on the structure of a document — a missed section
heading, a catechism answer split from its question — and its failure is visible as a wrong locator
set. Fusing them produces one function that can fail either way and reports both the same.

---

## The fetch cache

PLAN says fetch "caches on `upstream_sha256`", which cannot be literally true: a cache key cannot be
the hash of something not yet fetched. What the plan is reaching for is content addressing, and that
is what this implements.

Fetched bytes are stored at `/data/acquire/<corpus-id>/fetch/<sha256>`. The manifest's
`upstream_sha256` is what *selects* a blob, not what keys the fetch.

| Invocation | Network | Rationale |
| --- | --- | --- |
| `acquire --corpus <id>` | Only on a cache miss | Re-runs and downstream stage re-runs are cheap, and acquisition works with egress blocked once the blob is present |
| `acquire --verify-only` | **Always** | Noticing upstream drift is the entire job of `make corpus-verify`. A cache hit here would report success while evaluating nothing |
| `acquire --from-file PATH` | Never | The local copy is hashed and enters the same cache, so a dead upstream takes an identical path through every later stage |

Each stage writes under `/data/acquire/<corpus-id>/<stage>/` and reads its predecessor's file rather
than receiving a value in memory. That is what makes the stages independently re-runnable and
inspectable, rather than one function with checkpoints inside it.

**Only `fetch` treats its output as a cache.** Implementation revised this: an earlier draft had
every stage reuse its predecessor's output when present, which would let an adapter fix land while
verification still ran against the output of the code it replaced. Silently, and in the one place
this project can least afford it. Extract, segment and normalise are pure and cheap, so they
recompute every run; the files they leave behind are the seam and the inspection surface, not a
cache.

**The inspection surface is read by `make browse`.** Every check acquisition performs reports on text
without showing it, deliberately — a fingerprint diff that printed the passage would put corpus text
in CI logs. So the pipeline can say *that* something changed and never *what it looks like*, and the
failures that matter most are exactly the ones that need an eye: a swallowed heading, a table
flattened down the wrong axis, a normalisation step that ate something it should not have. The
browser reads `stage/` for the text ingestion will load and `segment/` for the line structure
normalisation erases, and serves them on loopback. It also offers the edition verification for a
corpus that has never been blessed, on the conditions ADR-0021's amendment sets out — the passage in
full, a typed name, and a refusal to write if the text moved between being read and being submitted.
Re-blessing stays at the terminal. It is the same answer ADR-0021 gave for the
edition diagnostic — acquired text read locally on demand, never committed so it can be read —
widened from one locator to a whole corpus.

---

## Committed artefacts

Per corpus, unchanged from the acquisition contract:

```
corpora/<corpus-id>/manifest.yaml
corpora/<corpus-id>/fingerprints.txt
```

The third line of that contract — `tools/acquire/<corpus-id>.py` — moves. See "Spec changes" below.

### `edition_check` records the verification, not the text

Superseded during implementation, and the reversal is ADR-0021.

The contract had four fields — `diagnostic`, `expected`, `verified_by`, `verified` — with `expected`
holding the divergent text quoted, and this document argued for making it the diagnostic locator's
whole normalised text: one home for the quoted text, and that home the committed record rather than
a constant in an adapter. That argument was right about where the text should live and wrong about
whether it should be committed at all.

What settled it is the escalation. Two Phase 1 corpora are PCA-published and `local-only`
(ADR-0017), so the rule would commit a full section of a copyrighted document into a public
Apache-2.0 repository — and choosing per corpus how much text is acceptable is the per-corpus
licensing judgement ADR-0014 exists to remove. The field is `expected_sha256` now, and the
repository carries no corpus text at all.

What replaces the quotation is a command rather than a checkbox. `--show-diagnostic` acquires and
prints the diagnostic locator's normalised text and hash, staging nothing and working before a
corpus has ever been blessed; `--bless` prints the same thing before it prompts. The reason quoted
text beat a checkbox was that it let the next person check, and a command that prints it on demand
does that without the repository distributing anything.

A negative diagnostic — text that must appear nowhere — was considered before any of this and
rejected. It catches nothing the fingerprints do not already catch: every chunk's normalised text is
hashed and committed, so a source that silently swapped editions produces mismatched hashes or an
unexpected locator, and verify reports both. Its only uncovered case is the first acquisition,
before fingerprints exist — which is exactly the moment a human is reading the text by design. It is
also wrong on `wcf-1646-original`, a corpus on the Phase 1 list whose text *is* the text a negative
check would search for, so it would need a per-corpus exemption: complexity generating more
complexity, guarding a check already performed. Under ADR-0021 it is doubly dead, since it would
have to commit the text it searches for.

### Fingerprint ordering is bytewise

`fingerprints.txt` is "sorted by locator", which is underspecified: `WCF 10.1` sorts before
`WCF 2.1` bytewise and after it numerically. The order is **bytewise on the UTF-8 encoding of the
locator**.

A numeric-aware sort needs a locator grammar the format does not have. The moment a locator is
`Inst. 4.17.10` or `Gen 1:1`, "natural order" means a per-corpus parser living inside a
corpus-agnostic file format. The file's job is a diff that is stable across machines and locales;
browsing it is not what it is for.

---

## Verification

Verify compares the acquired `{locator: hash}` map against the committed one and reports three
classes together, never one at a time:

- **missing** — in `fingerprints.txt`, not acquired
- **unexpected** — acquired, not in `fingerprints.txt`
- **mismatched** — in both, different hash

A changed `upstream_sha256` is **reported and is not a failure on its own** — a second decision made
during implementation. Publishers change page furniture without touching text: the OPC's page
carries a site-wide `© <year>` footer, so a check that failed on the upstream digest would fail
every January and be a check nobody trusted. It is also what makes the archive fallback usable at
all, since an archived copy does not hash to the live page's bytes. The fingerprints say whether the
text moved; the digest says whether the bytes did, and those are different questions.

Counts, plus a bounded sample of **locators only**. Never text: a diff that printed the differing
passage would put corpus text into CI logs and terminal scrollback, and the point of ADR-0014 is
that text has exactly one home.

`chunk_count` from the manifest is asserted, not merely recorded. A recorded number nothing checks
is a comment.

A `normalisation_version` mismatch between the manifest and `catena.normalise` fails hard and says
what it means: the contract moved, so every fingerprint in the file is a hash of text this code no
longer produces, and the corpus needs re-blessing.

---

### An unblessed corpus stages, and says it was not verified

Corrected 2026-09-05. Acquisition used to refuse a corpus with no committed manifest — "nothing to
verify against, run `--bless`" — which was reasonable in isolation and wrong in context.

It made the browser's first-bless flow **unreachable by construction**. `browse` discovers corpora by
their staged output; staging happened only after a successful verify; verifying required a committed
manifest; and a manifest is written only by a bless. So the one state the browser's `offer()` accepts
— `UNBLESSED`, which it checks for explicitly — was the one state no corpus could reach there. A
documented, implemented feature that nothing could ever exercise.

It also made `make provision-corpus` fail on any clean clone the moment one corpus was unblessed, and
fail *after* the blessed corpora had already staged, so the run was both broken and half-done.

A plain acquisition of an unblessed corpus now stages, and reports `UNVERIFIED — never blessed`
with the count and where the records went. There is no committed record to drift from, so
verification has nothing to do rather than something it is skipping; the guarantees that matter are
untouched, since text still lands only in gitignored local storage, nothing renders unverified, and
no bless happens without a human typing a name.

`--verify-only` still refuses. Drift detection against no committed record is not a check that
passes, it is a check with nothing to evaluate, and `make corpus-verify` reporting success there
would be exactly the "reports success while evaluating nothing" failure the fetch cache rules were
written to avoid.


## `--bless`

The one action in the process that discards a human verification, so it is the one action that
cannot be automated past.

- **Aborts when stdin is not a TTY.** No flag overrides this. An unattended CI run cannot bless.
- Prints the diagnostic locator's acquired text, the chunk counts, and — on a re-bless over existing
  fingerprints — the full three-class diff *before* asking for anything.
- Blocks on a typed verifier name, which is what lands in `verified_by`. A name passed as a flag
  records that someone typed a name, not that anyone read the text.
- Re-blessing over an existing fingerprint file demands a different, more explicit confirmation than
  a first bless. "Never bless your way past a mismatch you have not understood" is a rule that needs
  the two cases to feel different.
- Manifest and fingerprints are written temp-then-rename. An interrupted bless must not leave a
  half-written fingerprint file that the next run silently verifies against.

---

## Source authority

The PCA publishes no fetchable bare text of the Westminster Confession. `pcaac.org` serves the
confession through a JavaScript application — 230 KB of markup over 2.3 KB of text, and a WordPress
REST payload containing page shortcodes rather than the confession. Its only bare-text artefacts are
proof-text PDFs, which is the apparatus the ingest skill forbids taking.

So source authority cannot rest on the publisher. **The `edition_check` is the authority**: what
makes a corpus `wcf-1788-american` is that a human verified the diagnostic and the fingerprints hold
run to run. `source_url` is provenance — where the bytes came from — not warrant.

For the first corpus the source is `opc.org/wcf.html`, which carries the American revision at 23.3
("Civil magistrates may not assume to themselves… Yet, as nursing fathers…") rather than the 1646
text, and carries no proof-text apparatus. The diagnostic is WCF 23.3 and the human verification at
bless time is what admits it.

The archive fallback is the Wayback Machine's `id_` form, which returns the archived bytes without
the toolbar it otherwise injects, so a fallback acquisition takes the same path through extraction
as a live one.

### What the source's shape turned out to be

Worth recording, because it is the extraction failure the stage split exists to make visible. The
page is a `div.mainBlock` holding an `h1`, an `ol` table of contents, and then 33 `h3` chapter
headings each followed by numbered `p` sections — 171 sections in total, which the blessed
`chunk_count` will assert. Chapter 31 has four sections rather than the 1646 original's five, which
is a second structural confirmation of the American revision alongside 23.3.

**WCF 1.2's lists of the canonical books are three-column tables read *down* each column.** Read
row-major — the obvious implementation — the Old Testament opens "Genesis, II Chronicles, Daniel"
and the New splits "The Epistle to" in one row from "the Hebrews" in the next. That is garbled text
that would have been hashed, blessed, and verified clean forever after, and no later stage could
have noticed. Extraction reads tables column-major, and the suite asserts it.

---

## The catechism adapters

`wlc-1788-american` and `wsc-1788-american` landed against the interface above without changing it,
which is the first thing worth recording: the adapter boundary held for a second document shape.

### Shared helpers, and where the seam falls

Three of the seven corpora are documents on one publisher's site in one markup shape. Two helper
modules now sit under `corpora/`, both underscore-prefixed so the `corpus_id` → module mapping can
never produce them:

- **`_opc.py`** — the OPC page. Container capture on `div.mainBlock`, the dropped-subtree set, block
  flushing tolerant of unbalanced markup, and column-major table flattening. Lifted from the WCF
  adapter unchanged, which its suite proves: `test_acquire_wcf.py` passes untouched, and that is the
  only evidence that a refactor did not move a fingerprint.
- **`_catechism.py`** — Q&A segmentation, shared by the two catechisms.

The split between them is the same one the pipeline draws between `extract` and `segment`, drawn one
level down and for the same reason: `_opc` describes the shape of a publisher's markup and fails as
garbage text, `_catechism` describes the structure of a catechism and fails as a wrong locator set.
One module that did both could fail either way and would report both the same.

`_opc`'s rules are deliberately **not** parameterised per corpus. A catechism page carries no table
of contents, no tables and no proof-text apparatus, so the confession's rules are inert there — and
load-bearing the day the OPC adds proof-texts to a catechism, which would otherwise be segmented as
text.

**This is a contract change.** The acquisition contract lists three committed artefacts per corpus,
one of which is the adapter module; it did not anticipate shared code inside that package. The rule
added to INTEGRATION-SPEC is that an underscore-prefixed module there is a helper and not an
adapter, and that a helper may not do what the adapter interface forbids — normalisation stays with
the pipeline.

### Chunk text carries neither marker

Decided during implementation; the contract was silent. A chunk is `<question> <answer>` with
`Q. n.` and `A.` both dropped.

Check 2 substring-matches a quote against exactly this text, so a marker left sitting on the
boundary fails any quote that spans it — and a model quotes prose, not markers. Dropping the number
also follows the confession's adapter, which puts the section number in the locator and not in the
text. Nothing is lost: every question in both catechisms ends in a question mark, so the boundary
survives its marker.

### Division headings are matched structurally, because the text cannot be committed

The Larger Catechism carries two all-caps headings that divide it and belong to no Q&A. They are
dropped, counted, and the count asserted — `EXPECTED_DIVISIONS`, 2 for the WLC and **0 for the WSC**,
which is what makes a heading appearing there a failure rather than a silent drop.

They are matched as "an all-caps line between Q&As" rather than by their text, and that is forced
rather than chosen: hard-coding the two strings would commit corpus text to this repository, which
ADR-0014 forbids without a per-corpus exemption. The rule was checked against both sources before it
was relied on — those two are the only all-caps lines in either document, and every continuation
line inside WLC 99 and WLC 151 carries lowercase.

A line *after* an answer is deliberately indistinguishable from a continuation of it, and must be:
WLC 99's eight rules and WLC 151's four aggravations are exactly that. The stray-text check
therefore catches prose *before* the first question, which is the case that can actually lose a
chunk.

### What the sources turned out to be

- `opc.org/lc.html` and `opc.org/sc.html`. Not `wlc.html`/`wsc.html`, which 404.
- 196 and 107 Q&As, contiguous from 1, each a single `<p>` of `Q. n. <i>…</i><br />A. …`.
- **WLC 196's paragraph is never closed** — it runs straight into the container's `</div>`. The
  extractor flushes at the container close, so the last chunk survives; a tree builder or a regex
  over `<p>…</p>` loses it, and loses it silently. It has a test.
- Neither page carries a table of contents, a table, or a `<sup>`.

### The Shorter Catechism's diagnostic guards something else

The 1788 revision altered the confession's chapters on the civil magistrate and WLC 109. **It left
the Shorter Catechism unchanged**, so `wsc-1788-american` has no 1646-versus-1788 divergence for a
diagnostic to point at.

The ID stays as it is: a corpus ID is edition-specific by rule, the PCA's standards are one set, and
an ID asserting a different date would invent a distinction the document does not have. What changes
is what the diagnostic is *for*. The confusion this corpus is exposed to is a modernised printing,
and the first thing a modernised printing changes is "Holy Ghost" to "Holy Spirit". WSC 6 is one
short answer containing it — cheap to read at bless and impossible to be uncertain about.

This is recorded in the adapter's own docstring rather than only here, because the person it needs to
reach is whoever reads the module before blessing it.

---

## The *Institutes*

`calvin-institutes-1559-beveridge` — the largest Phase 1 corpus, the only translated one, and the
first that shares nothing with what came before. CCEL serves it as 4.6 MB of plain text, so `_opc`
does not apply and `extract` decodes and trims regions rather than parsing markup.

1,284 chunks: 1,277 body sections across four books of 18, 17, 25 and 20 chapters, plus the seven
sections of Calvin's prefatory address.

### Three hazards, none of which announces itself

**Every chapter opens with a numbered synopsis of itself.** A list of one-line section titles
numbered 1..N, followed by the same numbers again as the real body. Taken naively, a chapter yields
2N chunks — half of them title fragments that would hash, bless, and verify clean forever, with
nothing downstream able to notice. This is the *Institutes*' version of WCF 1.2's column-major
tables, and it is worse, because it affects 74 of the 80 chapters rather than one.

The rule is an invariant rather than a heuristic, which matters because a heuristic tuned until it
fits is how garbage gets blessed. Take the greedy ascending run 1, 2, 3, … matching **only the next
expected number**; then take a second run after it. When the two agree, the second is the body and
the first was the synopsis. When they do not, the chapter carries no synopsis and the single run is
the body — **six of the eighty carry none**, so its presence cannot be assumed. Matching only the
next expected number is also what steps over the numbered lists that appear inside the prose, which
defeated three earlier attempts at this.

Validated before any adapter code was written: the rule reproduces the known section counts of every
chapter, including the hard ones — 2.8 has 59, 3.20 has 52, 4.17 has 50, and the no-synopsis 3.21,
4.1 and 4.20 have 7, 29 and 32.

**Book IV chapter 18's number is missing from the source.** It reads `CHAPTER [653]` — a footnote
anchor swallowed the number. Dropped, the parser loses a whole chapter; mishandled, it renumbers
every chapter after it. It is recovered **positionally**: a chapter marker with no parseable number
takes the next expected one, and the 18/17/25/20 shape is asserted. Recognising it by its title
would commit corpus text, which ADR-0014 forbids.

**1,283 footnote anchors inside the four books** are CCEL apparatus and are stripped in extraction.

### What is not the corpus

The file carries a great deal that is not the work, and excluding it is a licensing act rather than
a tidiness one. **John Murray's introduction is 20th-century and in copyright** — the CCEL header's
`Rights: Public Domain` covers Calvin and Beveridge, not the apparatus a later edition wraps around
them, and `license_terms` records that distinction rather than leaving it to be inferred. Also
dropped: Norton's 1581 translator's preface, the scripture and author indexes, each book's editorial
`ARGUMENT`, and the One Hundred Aphorisms appended at the end.

### Two locator forms, for one corpus

Calvin's prefatory address to Francis I opens the work but sits outside the book/chapter scheme.
Rather than exclude it or give it a fake book number, it takes `Inst. Pref.1` through `Inst. Pref.7`
— recorded in GLOSSARY, and the only Phase 1 corpus with two locator forms. The alternative that was
rejected, `Inst. 0.0.<n>`, keeps one shape at the cost of a locator that reads as a real address and
is not one.

---

## The 1646 confession, and the check that a diagnostic cannot make

`wcf-1646-epcew-modernised`, 172 chunks. The corpus ID is the finding.

### No faithful 1646 text exists in fetchable form

Every candidate was checked against the divergence the edition turns on — 23.3, where the original
gives the civil magistrate authority to call synods and the American revision has "nursing fathers":

| Source | Verdict |
| --- | --- |
| OPC `wcf.html` | 1788 American — already held |
| CCEL `westminster3.txt` | 1788 American, published under the original's title |
| CCEL `westminster1` / `westminster2` | Shorter and Larger Catechisms, mislabelled |
| Wikisource, *The Humble Advice of the Assembly of Divines* | the genuine 1646 text, but only 9 of 33 chapters transcribed |
| Internet Archive, 1647 printing | page images, no OCR text at all |
| EEBO | 403; a licensed database |
| six denominational sites | 404 or 410 |

What remains is the EPCEW, which publishes the 1646 recension a chapter to a page.

### A modernised rendering passes every check this pipeline has

The EPCEW text has the original's substance. 23.3 gives the magistrate authority to call synods,
chapter 31 has five sections against the American revision's four, and `WCF 31.5` exists there and
in no other corpus here. The edition diagnostic passes. The 33-chapter assertion passes. The
chapter-31 assertion passes. The fingerprints are stable run to run.

**Its English has been modernised throughout**, and only a diff against the 1788 corpus exposed it:
151 of 171 shared locators differ, where the two editions should differ in a handful of places.

| form | EPCEW | OPC 1788 |
| --- | --- | --- |
| `hath` | 1 | 38 |
| `doth` | 0 | 23 |
| `-eth` verbs | 1 | 52 |
| `has` | 37 | 0 |
| `does` | 23 | 0 |

`dependeth` becomes `depends`; `he hath` becomes `He has`. That is a difference of diction rather
than doctrine, which is why the corpus is kept — for showing what a tradition repudiated, the
argument survives the rewording. What it may not do is claim to be the 1646 text, because every
citation would verify against words no seventeenth-century document contains. Hence
**`wcf-1646-epcew-modernised`** rather than `wcf-1646-original`, with `edition` saying the same
thing in prose.

**The general lesson: an edition diagnostic catches the wrong recension, not a modernised rendering
of the right one.** ADR-0021 made the diagnostic a locator whose text a human reads, and that is
exactly the right instrument for "is this the 1788 or the 1646 confession". It is the wrong
instrument for "is this the 1646 confession or somebody's 1646 confession in today's English",
because the passage reads correctly in both.

So `--bless` now prints a **register profile** beside the diagnostic: counts of `hath`, `doth`,
`-eth`, `has` and `does` across the whole corpus. It asserts nothing. "Old text, modern words" is a
judgement, and a threshold would need one per corpus, which is the per-corpus reasoning this project
keeps removing. It counts a grammatical pattern rather than quoting anything, so it says something
about the text while the repository carries none of it. The two confessions side by side are why it
earns its place — 38/23/52 against 1/0/1 is not a subtle signal.

### `FetchPlan.follow`, for a corpus that is not one document

The source is 33 pages. `FetchPlan` gains `follow`: the adapter is handed the index's bytes and
returns the page URLs in reading order, and fetch downloads them into one blob. Every later stage is
unchanged — the concatenation is content-addressed, cached and `--from-file`-able like any single
document, and the index itself is dropped as the table of contents it is.

The seam is in fetch rather than in an adapter's `extract` for the reason the stages are separate at
all: fetch is the only stage that touches the network, and an adapter downloading its own pages
would put network access behind a function the cache cannot see. `follow` reads bytes and returns
strings; it performs no I/O.

The URLs are **discovered rather than listed** because they carry the confession's chapter titles,
and thirty-three of those written into an adapter is the document's table of contents committed to a
public repository (ADR-0014).

**A page set is fetched politely, one second apart.** Not a nicety: 33 back-to-back requests earned
an HTTP 429 from a small denominational server during development, which fails the whole
acquisition. Acquisition is one-time and human-supervised, so a minute spread over a corpus costs
nothing.

A per-page archive fallback was rejected. A set of archived snapshots is a second source to keep
current, and a corpus that quietly acquired 32 of 33 pages would stage and bless as though complete;
the fallback for a page set is `--from-file`.

### Two source defects worth recording

**Chapter 12, *Of Adoption*, is a single unnumbered paragraph.** The chapter has one section and the
source omits the numeral, so a segmenter requiring one loses `WCF 12.1` entirely. A chapter opening
with unnumbered text takes section 1, and the number of such chapters is asserted at exactly one —
one is a feature of the document, two would be stray text being absorbed into a chunk.

**Proof-text markers are linked in two styles.** The current one puts `footnotes` in the path; an
older one is `/wcf/I_fn.html#fn10`. Matching the path caught only the first and left markers in
eight chunks — a fingerprint of text-plus-apparatus, which blesses and verifies clean forever. Both
styles carry an `fn<n>` fragment and name, which is the marker's real signature, and extraction now
**refuses** rather than emitting a document with a marker still in it.

---

## The 2000 creation study report

`pca-ga28-2000-creation-study`, 513 chunks. The corpus that makes UC-4 answerable: without it the
corpus says only "in the space of six days" (WCF 4.1), and the denomination's actual ruling appears
nowhere.

### The recommendations are addressable, and unmistakably so

`GA28 Rec.1` through `GA28 Rec.3`, a form deliberately unlike the body's `GA28 IV.B.2.4`. A
profile's `ruling_source` resolves to the first and must never resolve to the second, because the
body argues four interpretations the denomination did not adopt and tier is per corpus rather than
per chunk (ADR-0015). The locator is the only thing separating advocacy from ruling, so it should
not take a careful reader to tell them apart: `VI.B.2` and `IV.B.2` differ by one character and mean
opposite things, which is why the hierarchical form was rejected.

`Rec.2` is the ruling — the Assembly affirming a diversity of views on the creation days — and it is
the **edition diagnostic**. A committee draft has recommendations; only the adopted report records
that they carried, which the source does, in italics: *Adopted*, *Adopted as amended*.

### PLAN's chunking rule did not survive the document

The spec says "per numbered section". Section IV.A, the Calendar-Day Interpretation, is **40,659
characters with no subsections** — about 10,000 tokens, past BGE-M3's 8,192 limit. It could not be
embedded, let alone retrieved. The deepest headings run from 1 KB to 40 KB.

Chunks are paragraphs, and the section path moves into the locator: 513 chunks, median 376
characters, none above 2,016. Seventeen fall under ADR-0020's 40-character quote floor, so they can
be cited and never quoted, which is the right direction to fail in.

### On the date, because the source disagrees with the corpus ID

The PCA Historical Center files this under "[27th General Assembly (1999)]" while the ID says the
28th and 2000. The document settles it: it contains "PROPOSAL FOR REPORTING TO THE 28TH GENERAL
ASSEMBLY" and records each recommendation's outcome, and an outcome is something only an Assembly
produces. The 1999 label is the committee's work filed under the year it was written.

### Four source defects, each of which silently corrupts the corpus

**The body marker appears twice.** "REPORT OF THE CREATION STUDY COMMITTEE" is both the page's title
above the contents table and the body's heading below it. Starting at the first swallows the
Historical Center's filing label and the entire index. The last occurrence wins.

**Bold does not mean heading.** Headings are bold, but so is emphasis mid-sentence and so are whole
paragraphs the source chose to set in bold. A heading is a paragraph that is *entirely* bold **and**
no longer than 120 characters; the report has 36 fully-bold paragraphs carrying no number, most of
them short sub-headings (`Conclusion`, `Strengths:`) and some of them body text. No heading in the
document approaches the threshold and every bold body paragraph exceeds it.

**Footnote bodies are not the report.** Dropping the marker leaves the note's text, and all 173
endnotes sit after the appendices in their own `div id="ftnN"` — chunked, they produced 184
paragraphs like `[35]Ibid.` under locators claiming to be the appendix on General Revelation. The
`div` is dropped whole.

**A bracketed number is not always a footnote.** The 1646 adapter refuses any surviving `[n]`, which
would be wrong here: this document cites `Works [1822]` and `God Made visible in His Workes [1641]`
in its own prose. Footnote numbers run to 173 and years are four digits, so the two are separable —
but the general rule is that a marker-shaped string is only apparatus in a source that uses it that
way, and the check belongs per adapter rather than in the pipeline.

---

## The World English Bible

`web-2020`, 31,098 verses — an order of magnitude past anything else acquired here, and the corpus
whose ID had to change.

### The edition is 2020, and `web-2000` named one nobody published

PLAN, TECHNICAL-SPEC and INTEGRATION-SPEC all said `web-2000`. eBible.org is unambiguous that no
such edition exists. Its FAQ: the translation "started out as just one Bible translation that was
**continuously revised until 2020**", and "The World English Bible was **completed in 2020**. A few
minor typos have been corrected since then." The VPL archive's own about file ends "**2020 stable
text edition**". The Sword modules are named `engweb2025eb`, and the files on the server were
rebuilt three days before acquisition.

So `web-2000` asserted an edition that was never a published artefact — the same failure as
`wcf-1646-original`, caught the same way, by reading the source instead of the spec. Renamed, and
the three specs corrected in the same change.

### Which WEB, and why it is a canon question rather than a spelling one

eBible publishes two that matter here. `eng-web` is the **Classic**: it carries the
Deuterocanon and renders the Tetragrammaton "Yahweh". `engwebp` is the **Updated** text restricted
to the 66 books — exactly the canon WCF 1.2 enumerates — and renders it "LORD" (6,576 times;
"Yahweh" appears nowhere in it). Both the canon and the divine name make the Protestant edition the
right text under a Westminster profile, and the two are different corpora rather than two spellings
of one. Taking the wrong one would put the Apocrypha into a corpus a PCA profile treats as
`binding`.

### `text_form` is `majority`, on the publisher's statement

The enum is closed and the answer is not guessable from the abbreviation. eBible's FAQ: the WEB
"has been edited to conform to the **Greek Majority Text** New Testament where there are significant
differences in manuscripts", using "the Biblia Hebraica Stuttgartensia in the Old Testament, and the
**Byzantine Majority Text**… Robinson-Pierpont and Hodges-Farstad". The text bears it out —
Matthew 17:21, Mark 9:44 and John 5:4 are present where critical texts omit them, and the Comma
Johanneum is absent where the Textus Receptus has it. Recorded from the statement, corroborated by
the text, rather than either alone.

### Five verses are blank, and *which* five is the evidence

Luke 17:36, Acts 8:37, Acts 15:34, Acts 24:7 and Romans 16:25 are absent from that base text, and
the source emits the verse marker with no text after it. `record.stage` refuses an empty normalised
string, so acquiring them aborts the run — a loud failure, but the wrong one.

They are skipped, and the adapter asserts the **exact set** rather than the count. Which verses a
translation omits is evidence about its Greek text: a source blanking a different five would be a
different textual base wearing this one's name, and the edition diagnostic could not see it, because
every remaining verse reads identically. That is the `wcf-1646-epcew-modernised` lesson applied
before it cost anything — a diagnostic locator catches the wrong recension, not a different text
that agrees at the locator you happened to pick.

**Skipping them leaves real gaps**, so verse numbering is deliberately *not* asserted contiguous,
unlike chapter and section numbering everywhere else in this package. Acts runs 8:36 then 8:38, and
that is correct.

### A zip is the right shape, and the locator table is the source's dialect

`extract` opens the archive in memory and reads one member. eBible's VPL form is "BIBLE TEXT ONLY.
All formatting, paragraph breaks, notes, introductions, noncanonical section titles, etc., have been
removed" — the bare text this project wants, with the apparatus already gone. The alternative
single-document forms are HTML per book, which would need `FetchPlan.follow` and a parser to arrive
at exactly the lines this member already contains.

The source's book codes are the older BibleWorks-style forms rather than USFM — `SOL` not `SNG`,
`JOH` not `JHN`, `JAM` not `JAS` — so the adapter's 66-entry table is not decoration: it pins the
dialect the source actually speaks, and an unrecognised code fails rather than inventing a locator.
Book names are identifiers, not text (ADR-0014).

### Scale, measured

| | |
| --- | --- |
| chunks | 31,098 (31,103 verses less the five blanks) |
| extract + segment + normalise + stage | 0.39 s |
| verse length | median 119 characters, max 491 |
| `make browse` | paginates at 500, so 63 pages; loads in 0.44 s and renders one page in 0.02 s |

**482 verses (1.5%) fall below ADR-0020's 40-character quote floor** — including John 11:35, "Jesus
wept." They can be retrieved and cited and never quoted, which is exactly the case ADR-0020
anticipated when it said the floor "will occasionally reject a legitimately short citation… Revisit
the number if it fires on real Westminster content during Task 11." It now has a number attached to
it before Task 11 rather than after.

---

## Testing

ADR-0014 bars corpus text from fixtures, which is not an inconvenience to work around — it decides
the shape of the suite.

**The pipeline suite uses an invented corpus.** A fake adapter over a document defined in the test
module, with invented text. Every generic stage — cache, verify, bless, staging, manifest
validation — is exercised there, because none of them care what the text says. No test touches the
network.

**The adapters are tested structurally.** That extraction yields 33 chapters; that every locator
matches `WCF <chapter>.<section>`; that the chapter numbering is contiguous from 1; that no
proof-text markers survive extraction. All of that is assertable without committing a byte of the
confession, and it is what would actually catch a broken parser.

The catechisms are tested the same way, and the shared helpers get their own suites:
`test_acquire_opc.py` covers the page shape once for all three corpora, and
`test_acquire_catechisms.py` covers Q&A pairing, the division rule, and each adapter's constants
against a page built in the source's layout from invented text. What is **not** a test is that
WLC 109 omits the 1646 clause or that WSC 6 says "Holy Ghost" — asserting either would commit the
phrase, so both are the human's job at bless, which is what the diagnostic exists for.

The 33 is checked, not assumed. The 1903 PCUSA revision added chapters 34 and 35, and a source
carrying them would be the wrong edition in a way WCF 23.3 does not detect — the divergence is
structural rather than textual. The PCA's own publication of the confession ends at chapter 33, "Of
the Last Judgment", which is what the count asserts against. The manifest's hand-blessed
`chunk_count` remains the authority; the chapter count is a cheaper assertion that fails earlier and
names the problem.

Specific cases the suite covers:

- fingerprints round-trip, and the bytewise order is stable
- verify's three classes report together rather than short-circuiting on the first
- `chunk_count` mismatch fails
- bless aborts on a non-TTY
- bless is atomic — an interrupted write leaves the previous file intact
- staging is idempotent
- a cache hit skips the network; `--verify-only` does not
- `--from-file` produces the same staged output as a fetch of the same bytes
- an unknown `license` enum value is rejected, and a missing required manifest field is rejected
- a `normalisation_version` mismatch between manifest and code fails hard

Real acquisition of the WCF is not a unit test. It is `make provision-corpus`, and drift detection is
`make corpus-verify`; neither is part of `make check`, which runs with nothing started and no
network.

---

## What lands

- `services/catena/src/catena/acquire/` — `pipeline`, `fetch`, `record`, `manifest`,
  `fingerprints`, `cli`, the three Westminster adapters under `corpora/`, and the `_opc` and
  `_catechism` helpers they share
- `catena acquire` with real argument parsing, replacing the exit-69 stub
- `corpora/wcf-1788-american/manifest.yaml` and `fingerprints.txt`, blessed by hand
- One new dependency: **PyYAML**. Fetch is stdlib `urllib`, extraction stdlib `html.parser`. The
  offline overlay stays honest and the adapter is per-corpus regardless
- No new Makefile targets — `provision-corpus` and `corpus-verify` already pass the flags, and
  `test-catena` globs new suites up

### Every acquisition target depends on `build`

Added 2026-09-04, after `make bless CORPUS=wlc-1788-american` reported `unknown corpus` against a
freshly written adapter. The catena image `COPY`s `services/catena/src` at build time and mounts no
source, so a container started against a stale image runs the adapters the image was built with.

The visible failure — a new corpus reported unknown — is the harmless half. The dangerous half is an
*edited* adapter, where the stale image acquires through the old code and nothing says so: a bless
would then record a human verification against text the working tree no longer produces, which is
precisely the class of silent divergence the fingerprints exist to catch and could not catch here,
because the fingerprints would be written by the same stale code that produced them.

So `provision-corpus`, `corpus-verify`, `bless` and `show-diagnostic` all take `build` as a
prerequisite. A warm no-op build is under two seconds, which is the cheaper side of that trade.
`show-diagnostic` is included for consistency with `bless`, which prints the same text: a stale
diagnostic read is a human reading the wrong text and concluding the edition is right.

### Spec changes in the same change

- **INTEGRATION-SPEC, acquisition contract:** adapters live at
  `services/catena/src/catena/acquire/corpora/<corpus_id>.py` — the corpus ID with hyphens replaced
  by underscores, so `wcf-1788-american` is `wcf_1788_american.py` — not
  `tools/acquire/<corpus-id>.py`.
  Three reasons, and the first is fatal on its own: the catena image copies only
  `services/catena/src`, so a script under `tools/` is not present in the container that
  `make provision-corpus` runs. A hyphenated filename is not an importable module name. And the
  adapters import `catena.normalise` and the pipeline's types, which makes them package code, where
  everything currently under `tools/` is host-side operational scripting the service never imports.
- **ADR-0021, and everything it lists:** `edition_check` records the verification and not the text.
  Raised in review of this task and decided against the whole-text form this document first argued
  for. It amends ADR-0014's manifest bullet, and adds `--show-diagnostic`.
- **INTEGRATION-SPEC:** fingerprint ordering is bytewise on UTF-8, stated rather than implied.
- **INTEGRATION-SPEC:** the fetch cache is content-addressed, and `--verify-only` always re-fetches.
- **`.agents/skills/ingest-corpus`:** the committed-artefacts trio, to match.
- **`tools/guards/corpus_guard.py`:** docstring reference to `tools/acquire/`.

The manifest schema changes in exactly one place, and it is ADR-0021's: `edition_check.expected`
becomes `edition_check.expected_sha256`.

---

## Status

The pipeline and the three Westminster Standards adapters have landed, and all three acquire
cleanly and byte-identically across runs: `wcf-1788-american` against `opc.org/wcf.html`, 171
sections across 33 chapters; `wlc-1788-american` against `opc.org/lc.html`, 196 Q&As;
`wsc-1788-american` against `opc.org/sc.html`, 107. **`wcf-1788-american` was blessed on
2026-09-04 under the current schema and needs nothing further; the two catechisms have never
been blessed.**

The confession was blessed once before review, under the `edition_check.expected` shape ADR-0021
replaced; a manifest is written only by `--bless`, so those artefacts were removed rather than
hand-edited, and it was re-blessed on 2026-09-04 under the current schema. **It is done.** Running
`make bless` against it again only offers to discard a verification that is already correct, and the
re-bless confirmation exists to make that hard to do by accident.

The two catechisms have never been blessed and take the step it already took:

```
make bless CORPUS=wlc-1788-american
make bless CORPUS=wsc-1788-american
```

Each prints one locator to read. **WLC 109 is confirmed by an absence** — "tolerating a false
religion" must not appear among the sins forbidden in the second commandment, because the 1788
revision deleted it. **WSC 6 is confirmed by a presence** — "the Holy Ghost", not "the Holy
Spirit", which is what a modernised printing substitutes. To read any diagnostic without blessing
anything, at any time:

```
make show-diagnostic CORPUS=<corpus-id>
```

The remaining four corpora are follow-on work against this same interface: a module under
`catena/acquire/corpora/`, an entry in that package's `CORPUS_IDS`, and a bless.
