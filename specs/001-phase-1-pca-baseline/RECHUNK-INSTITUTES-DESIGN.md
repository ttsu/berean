# Re-chunking the *Institutes* — design

**Scope:** PLAN Task 4, and the blocker INGESTION-DESIGN records against Task 5. The *Institutes*
was acquired at one chunk per numbered section and nobody re-measured; its longest section is
66,614 characters, which BGE-M3's own tokeniser makes 16,714 tokens against a window of 8,192.
Ingestion refuses a corpus carrying a chunk the embedder cannot read whole, so the corpus cannot be
ingested as blessed.

This is a working design document. The durable statements belong in
[TECHNICAL-SPEC](TECHNICAL-SPEC.md), [ACQUISITION-DESIGN](ACQUISITION-DESIGN.md) and
[GLOSSARY](../../docs/GLOSSARY.md); where this document decides something the specs did not
anticipate, that decision is folded back in the same change.

**No corpus text appears here.** Every figure below is a count taken over the staged records and
the extracted document; the worked example is invented, as fixtures are, because this file is
committed and ADR-0014 does not take licence into account.

---

## What is actually wrong

Two things, and only one of them is the reason this change was opened.

**The chunk is too big for the embedder.** Four chunks exceed BGE-M3's 8,192-token window:
`Inst. 4.1.27` at 16,714 tokens, `Inst. 3.22.11` at 9,296, `Inst. Pref.7` at 8,671 and
`Inst. 4.20.11` at 8,345. Those are counts from the model's own tokeniser in `models/bge-m3/`, not
an estimate — INGESTION-DESIGN declines to guess the number for exactly the right reason, that it
depends on a tokeniser that arrives with the embedder, and the answer is to run the tokeniser rather
than to defer. The measured ratio is 3.93 characters per token.

A longer chunk does not fail: the encoder truncates and returns a vector,
and nothing downstream can tell. The chunk is then retrieved on its opening fraction and quoted from
its whole text, and verification passes, because check 2 matches against `corpus.chunks.text` rather
than against the vector. INGESTION-DESIGN makes this a refusal rather than a warning for that
reason.

**The chunk is also too big to be a retrieval unit.** A 66,614-character section is one vector over
about six pages of argument. Even where it fits, it dilutes to nothing and cites a reader to a place
they then have to search. The window is what forces the change; retrieval is what decides how far
the change goes.

### The structure was there and the segmenter was throwing it away

CCEL serves this file with blank-line paragraph breaks intact. `_sections` filtered blank lines out
before joining, so paragraph structure never reached a `Segment`. The 1,284 sections contain 2,260
paragraphs.

Those breaks are trustworthy, which had to be established rather than assumed. Of the 976
paragraph breaks inside sections, 910 close one sentence and open another cleanly, 45 end without
terminal punctuation but capitalise the next paragraph, 16 close cleanly but continue in lower case,
and **5 split a sentence** — four in `Inst. Pref.7`, one in `Inst. 3.17.7`. Five in nine hundred and
seventy-six is a rate at which the blank line is a paragraph break, and the five are recorded here
so that a later reader finds a measurement rather than an assumption.

These counts were re-measured after the prefatory address was bounded at its real end, below; the
four absorbed works accounted for 32 of the breaks and most of the untidy ones. The five
sentence-splitting breaks are the same five either way, which is the point of recording them.

---

## The rule

**A chunk is one paragraph.** The section stops being the chunk and becomes the path in the
locator.

This is the rule `pca-ga28-2000-creation-study` already follows, and it was adopted here for that
reason: the report hit the same wall — section IV.A is 40,659 characters with no subsections — and
the project should not carry two answers to one question. Chunks are paragraphs and the section path
lives in the locator.

### What it costs, stated rather than discovered later

**431 of the 2,260 chunks fall under 100 characters.** They are not, in the main, the numbered
lists that run inside the prose — only 44 of the 431 are numbered-list shaped. The bulk is editorial
apparatus and headings: 44 are forty characters or fewer and four words or fewer — running heads,
datelines, and commandment headings; `Inst. 2.8.16.p4` is the text "Second Commandment". A further
17 are section-final scripture-reference blocks. And `Inst. Pref.7` alone yields 56 chunks, of which
45 are under 120 characters and 27 carry "Ed. 15xx" variant-reading notes — every chunk in the whole
corpus that contains "Ed. 15" is one of those 27. A variant-reading note is the same class of
material the adapter already strips elsewhere on stated licensing grounds — footnote anchors,
horizontal rules — and the re-chunk instead promotes it to a first-class, separately citable chunk.

The concrete risk is not dilution but substance. A chunk whose whole text is "Second Commandment"
passes verification check 2 — the text is real and the quote matches it — and renders a citation
that resolves and supports nothing. That is the one gap the verifier structurally cannot close,
because it checks that a quote is real, not that it is substantive.

Two alternatives were considered and rejected.

*Packing consecutive paragraphs to a size ceiling* — the longest run of paragraphs fitting, say,
6,000 characters — yields 1,350 chunks with only 31 sections split, and keeps the canonical citation
for the rest. It was rejected because the boundary then depends on a tunable: re-tuning the ceiling
re-chunks the corpus, which re-blesses it and re-embeds it, and the number that decides where a
citation begins would be a constant somebody picked. A structural rule has no such dial.

*Splitting only what the embedder cannot read* — a ceiling near the window, splitting four sections
— was rejected because it fixes the refusal and not the defect. It leaves 20,000-character chunks
that embed to one diluted vector, and it makes the chunk boundary a function of the embedding model,
so a model swap would re-chunk the corpus. ADR-0006 exists to make a model swap a re-index rather
than a re-acquisition.

The 431 short chunks are a real cost. Some of it is retrieval noise that Phase 3's reranking
exists to address; the harder part is the headings and apparatus that reranking cannot fix, because
they are not diluted answers but citable non-answers. It is accepted here in exchange for a boundary
that no parameter moves.

Whether `Inst. Pref.7`'s variant-reading tail should be excluded outright, the way the anchors and
rules are, was left here as an open question. It is now half-settled. The four front-matter works
that had been running on past the end of section 7 are gone — see *The address had no end, and
absorbed four more works* below — cut at a structural boundary rather than a convenient one. The 27
"Ed. 15xx" notes inside section 7 itself remain, and that is now a finding rather than a deferral:
they have no clean structural signature to cut on. Indentation was tried as a candidate and it
fails — 763 lines are indented the same way across the whole document, and only 52 of them fall in
this region, so a rule that kept those 52 and excluded the rest would be tuned to this corpus's one
instance of the problem. That is the same tunable this design rejected two sections up, for the same
reason: a heuristic tuned until it fits is how garbage gets blessed. They stay, citable individually,
because the alternative is inventing a boundary the source does not have.

---

## The third locator form

```
Inst. 4.17.10.p1        body:       book . chapter . section . p paragraph
Inst. Pref.7.p56        prefatory:  Pref . section . p paragraph
```

Uniform: every chunk carries a paragraph ordinal, including the 1,133 sections that hold exactly
one. GLOSSARY records this corpus as the only Phase 1 corpus with two locator forms; it now has
three, and the third is a suffix on both of the others.

**The `p` is load-bearing.** The obvious form, `Inst. 4.17.10.1`, matches GA28's shape exactly and
was rejected anyway, because the two works are not in the same position. `GA28 IV.B.2.4` appends an
ordinal to a path that was invented in the first place, so there is nothing for it to be confused
with. `Inst. 4.17.10` is the canonical citation every edition and every scholar uses, and a fourth
numeric component reads as a subdivision of it — a level Calvin does not have. That is the same
defect as the `Inst. 0.0.<n>` that ACQUISITION-DESIGN already rejected for the prefatory address: a
locator that reads as a real address and is not one.

`Inst. 4.17.10.p1` keeps the canonical citation legible as a prefix and says what the suffix is.

It survives every format it has to pass through. `LOCATOR` sees two tokens separated by one space,
`Inst.` and `4.17.10.p1`, which the regex permits and which `WSC Q&A 1` already relies on. The
fingerprints file is `<locator>  <sha256>` parsed by `rpartition` on the double space, so an
internal single space is fine. Nothing in the normalisation contract touches it, and it is ASCII, so
it needs no argument about what survives NFC.

---

## The apparatus this uncovered

The corpus carries **172 identical 66-character underscore rules** — CCEL's horizontal separators —
sitting inside the text of 81 sections: 81 of the rules fall at a section's last line and 91 fall
mid-section.
They are apparatus in exactly the sense the module's docstring already uses of footnote anchors:
"taking the apparatus is what turns a public-domain text into someone's copyrighted arrangement of
it." They are also live in verification, because a quote spanning one must reproduce sixty-six
underscores to pass check 2.

They are stripped in this change rather than a later one, and the reason is arithmetic rather than
tidiness: **80 of the 81 affected sections are multi-paragraph and are being re-chunked anyway**, so
stripping the rules changes exactly one fingerprint beyond what the re-chunk changes. Deferring it
would buy a smaller diff now and cost a second full re-bless of 2,260 chunks later, for a one-chunk
result.

**A rule line becomes a blank line**, not nothing. On this source the two are indistinguishable —
both produce byte-identical output, which was checked rather than assumed — so the choice is made
against a source that changes. A 66-character rule is a divider. If a future CCEL revision moves one
inside a paragraph, blanking preserves the division and dropping silently fuses two paragraphs into
one chunk, which is the failure mode this whole change exists to remove.

---

## The address had no end, and absorbed four more works

Calvin's address to Francis I has seven numbered sections, and section 7 has no closing marker of
its own — nothing in the source says where the address stops and the next thing begins. `extract`
took the next heading it could find, which was the general index, and let section 7 run the whole
distance to it.

Four further front-matter works sat in that gap, and all four were absorbed: THE EPISTLE TO THE
READER (4 paragraphs), SUBJECT OF THE PRESENT WORK (7), EPISTLE TO THE READER (12), and METHOD AND
ARRANGEMENT, OR SUBJECT OF THE WHOLE WORK (9) — 32 paragraphs, 21,204 characters, none of them
Calvin's address to Francis I. They were addressable as `Inst. Pref.7.p57` through `Inst. Pref.7.p88`.

That is worse than a locator that fails to resolve. `Inst. Pref.7.p61` hashed, would have blessed,
and would have verified clean forever — the text is real, it is simply not the text the locator
names, and nothing downstream can tell the difference. A broken locator announces itself; a locator
that resolves to the wrong work does not.

**The defect predates this change.** Before the re-chunk, `Inst. Pref.7` was a single
33,944-character chunk quietly holding all five regions — the address's own section 7, and the four
works that follow it — fused into one opaque blob nobody could see into. The re-chunk did not create
this defect; it made it visible, by turning one chunk nobody could cite piecemeal into 32 chunks each
citable on its own, and wrong. That is the argument for chunking at a real boundary rather than a
convenient one: the convenient boundary — the next recognisable heading, the general index — had
been hiding this the entire time the corpus stood as one chunk per section.

**The fix.** All four headings sit at indent 0, and nothing else in the prefatory region does, so the
boundary is structural rather than a tuned heuristic. `_address_ends` requires all four to appear,
exactly once each, in order, between the address and the index, and the address ends at the first of
them. All four are asserted rather than only the first: cutting at whichever was found would silently
keep three whole works if CCEL renamed or reordered one heading, and the wrong locators that would
result are invisible downstream in exactly the way described above — they hash, bless and verify
clean.

They are excluded on the same ground Norton's 1581 preface, the indexes, and the aphorisms already
are: they are not the work.

---

## What the change is

Three edits, all in `services/catena/src/catena/acquire/corpora/calvin_institutes_1559_beveridge.py`.

**`extract`** gains `_RULE = re.compile(r"^_{3,}$")` beside `_ANCHOR`, and a rule line is replaced by
an empty line before region selection runs.

**`_sections`** stops filtering blank lines and splits on them instead, yielding one `Segment` per
paragraph under `f"{prefix}{number}.p{ordinal}"`. The synopsis rule, the greedy ascending run, the
expected-section-count assertion and the `ARGUMENT` filter are all untouched — they operate on
section openings, and a section still opens exactly where it did.

The opener strip, `re.sub(rf"^{number}\.\s+", "", text)`, now applies to **paragraph 1 only**. That
is sound and it was verified: all 1,284 sections' first paragraph opens with the section's own
number. It was previously an unstated assumption that the strip depended on, and it becomes an
assertion below.

**The docstring** gains the paragraph rule and the rules-as-apparatus note, and loses the claim that
a chunk is a numbered section.

### Two assertions, in the module's existing idiom

**No chunk exceeds 20,000 characters.** A canary rather than a limit: far above anything this source
produces — the longest is 11,498 — and, at the measured 3.93 characters per token, roughly 5,090
tokens, so it fires well below the window rather than at it. What it catches is a CCEL reflow that
removes blank lines, which is the single change that silently reintroduces the defect this document
exists to fix. The real check stays in ingestion, where the tokeniser is; this one fails where the
defect lives.

**Every section's first paragraph opens with its own number.** Currently assumed by the opener
strip, and a source change that broke it would leave a stray `12.` at the head of a chunk, hash it,
bless it and verify it clean forever.

### The one chunk that cannot be split

`Inst. 4.16.31` is a single 11,498-character paragraph with no internal break. It is the longest
chunk in the corpus after this change at 2,890 tokens — 35% of the window — and because nothing can
split it, it is the true bound: no chunk of this corpus gets nearer the limit unless the source
itself changes. It is named here
because it is the bound: **any rule that splits inside a paragraph would have to invent a boundary
the document does not have**, and no such rule is needed. If a future source produces a paragraph
past the window, the assertion above stops acquisition and the answer is a design decision, not a
sentence splitter added under time pressure.

---

## What the re-bless looks like

| | before | after |
| --- | --- | --- |
| chunks | 1,284 | **2,260** — 2,177 body, 83 prefatory |
| sections yielding more than one chunk | — | 151 of 1,284 |
| most chunks from one section | — | 56 (`Inst. Pref.7`) |
| longest chunk | 66,614 chars / 16,714 tokens | **11,498 chars / 2,890 tokens** |
| median chunk | 2,411 chars / 604 tokens | 1,636 chars |
| chunks over the 8,192-token window | **4** | **0** |
| chunks under 100 chars | 17 | 431 |
| total text | 3,558,323 chars | 3,524,589 — the 172 rules and the 21,204 characters of absorbed front matter |

The fingerprint diff is 1,284 locators deleted and 2,260 inserted, of which **1,132 carry text that
is byte-identical to the section they came from**. Those are the single-paragraph sections that
carried no rule: normalisation collapses whitespace runs to one space, so a section's normalised
text does not depend on whether its lines were joined with a newline or a space, and only the
locator moves.

### The edition check survives, and that is checkable

`Inst. 4.17.10` is one paragraph and carries no rule. It becomes `Inst. 4.17.10.p1` with **identical
text and an identical sha256**, so `edition_check.expected_sha256` remains valid and only
`edition_check.diagnostic` moves. `diagnostic` in the adapter module moves with it.

The corpus is nonetheless re-blessed, and `verified_by` and `verified` are re-stamped. A bless is a
human reading an edition diagnostic and approving it, and 172 rules did come out of the corpus
between one bless and the next. What the unchanged hash buys is not a skipped bless: it is that the
human doing it can be shown the diagnostic's text is provably the same text they approved before,
so the re-bless is a confirmation rather than a fresh act of faith.

`chunk_count` goes to 2,260 and `fingerprints.txt` is regenerated in full.
`normalisation_version` is untouched — the contract did not change, the parser did.

---

## A worked example

An invented corpus, `foo-1899-invented`, one section, two paragraphs.

```
   3.  The first paragraph of the third section.

   The second paragraph of the third section.
```

Before: one chunk, `FOO 1.3`, text `The first paragraph of the third section. The second paragraph
of the third section.`

After: two chunks. `FOO 1.3.p1` is `The first paragraph of the third section.` — the opener `3. `
stripped, as before. `FOO 1.3.p2` is `The second paragraph of the third section.`, with no strip
applied, because the strip is paragraph 1's.

Had the section held one paragraph, the single chunk would be `FOO 1.3.p1` with text byte-identical
to what `FOO 1.3` held, which is the 1,132.

---

## Testing

`services/catena/tests/test_acquire_institutes.py` extends against invented text throughout, per
ADR-0014 and the rule the existing suite already follows.

- A two-paragraph section splits into `.p1` and `.p2`, and the opener strip touches only `.p1`.
- A one-paragraph section still yields `.p1`, and its text is what the un-split segmenter produced.
- A rule line between two paragraphs is removed and does not become a chunk of its own; a rule line
  at a section's end does not leave a trailing chunk.
- The over-length assertion fires on an invented section past 20,000 characters.
- The first-paragraph-opens-with-its-number assertion fires when it does not.
- Locator uniqueness across the whole corpus. Cheap, and it is the assertion that would have caught
  this class of defect on the first pass.

The synopsis, chapter-numbering and book-count tests are unchanged and must stay green: this change
is below them, and a failure there means paragraph splitting perturbed section detection.

---

## Spec changes in the same change

1. **GLOSSARY**, *Locators* — the *Institutes* now has three forms, not two. Record
   `Inst. 4.17.10.p1` and `Inst. Pref.7.p56`, and why the `p` is there.
2. **TECHNICAL-SPEC:46** — "one chunk per numbered section (`Inst. 4.17.10`)" becomes one chunk per
   paragraph, with book, chapter and section as the locator path.
3. **ACQUISITION-DESIGN**, *The* Institutes — the chunk count, the paragraph rule, the rules as a
   fourth stripped apparatus, and *Two locator forms* becomes *Three*.
4. **PLAN:396** — the chunking line for the *Institutes*.
5. **PLAN Task 4** — the re-chunk item, ticked; **Task 5** — its dependency on this, cleared.
6. **`.agents/skills/ingest-corpus/SKILL.md:136`** — the chunking table row.
7. **INGESTION-DESIGN**, *A chunk the model cannot read whole* — "Task 5 is blocked on re-chunking
   that corpus" is no longer true. That document is on `task-5-ingestion-design` rather than `main`,
   so the edit lands whenever the two branches meet, and this list is the record that it is owed.

## Status

Designed, not implemented. The prototype that produced every figure above was run against the local
staged corpus and discarded; nothing in it was committed. Token counts are from
`models/bge-m3/tokenizer.json` loaded directly, so the claim that this chunking clears the window is
a measurement and not an inference from a characters-per-token ratio.
