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

Each stage writes under `/data/acquire/<corpus-id>/<stage>/` and reads its predecessor's output when
present. That is what makes the stages independently re-runnable, rather than one function with
checkpoints inside it.

---

## Committed artefacts

Per corpus, unchanged from the acquisition contract:

```
corpora/<corpus-id>/manifest.yaml
corpora/<corpus-id>/fingerprints.txt
```

The third line of that contract — `tools/acquire/<corpus-id>.py` — moves. See "Spec changes" below.

### `edition_check` stays as the contract has it

Four fields: `diagnostic`, `expected`, `verified_by`, `verified`. No negative diagnostic.

A "text that must not appear" check was considered and rejected. It catches nothing the fingerprints
do not already catch: every chunk's normalised text is hashed and committed, so a source that
silently swapped editions produces mismatched hashes or an unexpected locator, and verify reports
both. Its only uncovered case is the first acquisition, before fingerprints exist — which is exactly
the moment a human is reading the text by design. It is also wrong on `wcf-1646-original`, a corpus
on the Phase 1 list whose text *is* the text a negative check would search for, so it would need a
per-corpus exemption: complexity generating more complexity, guarding a check already performed.

`expected` is not circular, and it is worth being precise about why. At bless time the human's
reading is the authority; `expected` records what they approved. On every run after, it asserts that
what was acquired now still matches what was approved then. That is the skill's rule — a checkbox
records that someone once believed the edition was right, the quoted text lets the next person
check.

Both `expected` and the acquired text are compared **after normalisation**, because normalised text
is what is on disk and what is hashed. Comparing raw text would make an edition check turn on
whitespace.

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

Counts, plus a bounded sample of **locators only**. Never text: a diff that printed the differing
passage would put corpus text into CI logs and terminal scrollback, and the point of ADR-0014 is
that text has exactly one home.

`chunk_count` from the manifest is asserted, not merely recorded. A recorded number nothing checks
is a comment.

A `normalisation_version` mismatch between the manifest and `catena.normalise` fails hard and says
what it means: the contract moved, so every fingerprint in the file is a hash of text this code no
longer produces, and the corpus needs re-blessing.

---

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

---

## Testing

ADR-0014 bars corpus text from fixtures, which is not an inconvenience to work around — it decides
the shape of the suite.

**The pipeline suite uses an invented corpus.** A fake adapter over a document defined in the test
module, with invented text. Every generic stage — cache, verify, bless, staging, manifest
validation — is exercised there, because none of them care what the text says. No test touches the
network.

**The WCF adapter is tested structurally.** That extraction yields 33 chapters; that every locator
matches `WCF <chapter>.<section>`; that the chapter numbering is contiguous from 1; that no
proof-text markers survive extraction. All of that is assertable without committing a byte of the
confession, and it is what would actually catch a broken parser.

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
  `fingerprints`, and `corpora/wcf_1788_american.py`
- `catena acquire` with real argument parsing, replacing the exit-69 stub
- `corpora/wcf-1788-american/manifest.yaml` and `fingerprints.txt`, blessed by hand
- One new dependency: **PyYAML**. Fetch is stdlib `urllib`, extraction stdlib `html.parser`. The
  offline overlay stays honest and the adapter is per-corpus regardless
- No new Makefile targets — `provision-corpus` and `corpus-verify` already pass the flags, and
  `test-catena` globs new suites up

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
- **INTEGRATION-SPEC:** fingerprint ordering is bytewise on UTF-8, stated rather than implied.
- **INTEGRATION-SPEC:** the fetch cache is content-addressed, and `--verify-only` always re-fetches.
- **`.agents/skills/ingest-corpus`:** the committed-artefacts trio, to match.
- **`tools/guards/corpus_guard.py`:** docstring reference to `tools/acquire/`.

`edition_check` and the manifest schema are unchanged.
