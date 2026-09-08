# Corpus ingestion — design

**Scope:** PLAN Task 5. The ingestion command, and the resumability model that lets a multi-hour
embedding run survive being killed. Chunking, normalisation, and fetching are Task 4's and are
settled before ingestion reads anything.

This is a working design document. The durable statements belong in
[TECHNICAL-SPEC](TECHNICAL-SPEC.md) and [INTEGRATION-SPEC](INTEGRATION-SPEC.md); where this document
decides something the specs did not anticipate, that decision is folded back in the same change.

**No corpus text appears here.** The worked example uses an invented corpus and invented text, as
fixtures do, because this file is committed and ADR-0014 does not take licence into account.

---

## What ingestion is for

Acquisition ends at a directory of staged records whose per-chunk hashes match what a human verified
by hand. Ingestion reads that directory, enriches, embeds, and loads. It never parses an upstream
format, never touches the network, and never decides what a chunk is.

That leaves it one job with one hard part. The job is to make the database agree with the blessed
staging directory. The hard part is that agreeing takes hours, almost all of it spent in the
embedding model, and the run can die at any point in those hours.

The design's whole claim is that those are the same job. **A database that is behind staging is
behind staging, and it does not matter why.** A killed run, a re-bless under a corrected parser, a
fresh clone, a half-applied migration — all four produce the same disagreement, and one diff
resolves all of them. There is no recovery path separate from the normal path, because there is no
state describing a run in progress for a recovery path to read.

---

## The command

```
catena ingest [--corpus ID | --all] [--apply]
```

The target group mirrors `catena acquire`, mutually exclusive and required.

### It does not write by default, and that inverts its sibling

`catena acquire` writes unless told otherwise, with `--verify-only` to suppress it. `catena ingest`
is the other way round: it computes and prints its plan, and writes only under `--apply`.

The asymmetry is deliberate and it is about what a wrong run costs. Acquisition writes into
gitignored `/data` and a mistake costs minutes of re-fetching. Ingestion updates and deletes rows in
Postgres, and `corpus.chunk_embeddings` cascades from `corpus.chunks`, so a wrong run costs hours of
embedding that no cache can return. The two commands are safe by opposite defaults because their
mistakes are not the same size.

The dry run is also the progress report, which is what keeps it from decaying into a flag typed
without reading. Its output on a resumed run is a live measurement — `0 insert, 0 update, 0 delete,
12,431 embeddings remaining` — and the number moves every time. A confirmation whose content never
changes stops being read; this one is the reason to run the command at all.

---

## Convergence, not insertion

The plan is a three-way diff between the staged records and the corpus tables:

| in staging | in database | action |
| --- | --- | --- |
| locator present | absent | **insert** |
| locator present | present, hash differs | **update**, and drop that chunk's embeddings |
| locator present | present, hash matches | **skip** |
| absent | locator present | **delete** |

Plus the embedding backlog — chunks carrying no `chunk_embeddings` row for the active model — which
is what makes an interrupted run visible without recording that it was interrupted.

### Two keys, and the difference between them is the design

`corpus.chunks` is UNIQUE on `(corpus_id, locator)`, and ingestion is idempotent on `content_hash`.
Those are different keys, and every row of the table above falls out of the difference: **the
locator says which chunk this is, the hash says what it currently says.** Insert is a locator with
no row. Update is the same locator saying something else. Skip is the same locator saying the same
thing. Delete is a row whose locator staging no longer has.

Keying idempotence on the locator alone would make a re-blessed corpus invisible — the rows exist,
so nothing happens, and the database keeps serving text that no longer matches the fingerprints the
project verifies against. That is precisely the failure the fingerprints exist to catch, so the
check cannot be the thing that skips it.

### An update must drop the embedding it invalidates

Deleting a chunk cascades to its embeddings. **Updating one does not**, and nothing in the schema
notices.

An update that rewrites `text` and `content_hash` while leaving the old vector in place produces a
chunk that is retrieved for what it used to say and quoted for what it now says. Verification does
not catch it: check 2 substring-matches the quote against `corpus.chunks.text`, which is the new
text, and it passes. The answer is wrong in the one way the verifier is not looking.

So the update path deletes that chunk's `chunk_embeddings` rows in the same transaction, which
returns the chunk to the backlog and re-embeds it. This is written down because it is invisible: the
buggy version passes every check in the system.

### Deletion is gated because a bless can be wrong

Staging only drifts from the database after a deliberate `--bless`, so a human has already looked.
That is a weaker guarantee than it sounds. The BCO was blessed once under a stale parser — 429
paragraphs with a running head in 49 of them, one paragraph missing entirely — and 89 of its 430
fingerprints changed when the parser was corrected. The bless reported success the whole time.

A bad bless is cheap to make and re-embedding is not, so the destructive direction does not run
without `--apply`, and `--apply` prints the plan it is about to execute rather than assuming the
operator still remembers the dry run.

---

## The plan is recomputed, not carried

`--apply` recomputes the identical diff and executes it. No plan file is written between the two
invocations.

The alternative — dry run writes a plan artefact, `--apply` validates and replays it — buys the
guarantee that what executes is textually what was read. It was rejected. The race it defends
against requires the operator to interleave a `--bless` between their own dry run and their own
apply, on a batch job run by hand that is never in the request path. The cost is worse than the
race: a plan file becomes a second answer to the question the command exists to answer, and it can
disagree with the database while looking authoritative. Recomputing means the diff has one
implementation that both paths call, and it is never stale.

`--apply` prints the plan it actually executes, so the log records what happened even in the case
where it differed from what the operator read.

---

## Where the crash boundary sits

Applying is two phases, and the boundary between them is the design's load-bearing choice.

**Phase one — text.** Upsert the `corpus.works` row from `work.json`, then apply every insert,
update and delete to `corpus.chunks` in a single transaction per corpus. This is fast; the entire
Phase 1 corpus is 8.2 MB of text.

**Phase two — embeddings.** Embed the backlog in batches, one transaction per batch into
`corpus.chunk_embeddings`.

Once phase one commits, the database holds complete, correct, blessed text for that corpus whether
or not phase two ever runs. **The schema already put the boundary here.** `corpus.chunk_metadata`
inner-joins `corpus.chunk_embeddings`, and the migration says why: a chunk with no embedding "does
not yet carry the whole contract, and it is a half-finished ingestion rather than a row this view
should paper over." So a crash mid-embed leaves a consistent system rather than a partial one,
nothing half-ingested reaches the gateway's read surface, and restart needs no cleanup step. The
design did not choose this boundary so much as find it already chosen.

### The resume query

```sql
SELECT c.id, c.text
  FROM corpus.chunks c
  LEFT JOIN corpus.chunk_embeddings e
    ON e.chunk_id = c.id AND e.embedding_model = $1
 WHERE c.corpus_id = $2 AND e.chunk_id IS NULL
 ORDER BY c.id
```

That is the entire resumption mechanism. No progress file, no checkpoint table, no run ledger,
nothing to leave stale and nothing to reconcile after a hard kill. The database's own contents are
the record of what has been done, which is the only record that cannot disagree with what has been
done.

The `embedding_model` predicate is load-bearing twice. It makes resumption model-aware, so a
re-index under a second model sees a full backlog rather than an empty one. And it is the same
predicate the migration requires of retrieval, because one HNSW index spans every model's vectors.

---

## Batching

### The budget is tokens, not chunks

A transformer pads every sequence in a batch to the longest one in it, and that padding is work the
model does and discards. The corpus spans roughly 14x by median chunk length — 119 characters for a
WEB verse against 1,636 for an *Institutes* paragraph — so a fixed chunk count behaves badly at both
ends. A mixed batch of 255 short chunks and one long one pads everything to the long one. Sorting
fixes the padding but not the variance: 256 short chunks and 256 long ones differ 14x in memory and
in wall-clock, so the amount of work a crash destroys depends on which corpus the run happened to be
in.

Filling each batch to a fixed budget of padded tokens makes the batch size float — at a budget of 16k
padded tokens, roughly 470 short chunks or 39 long ones — so memory, time per batch, and crash loss all stay
flat across corpora. Those two are measured with BGE-M3's own tokeniser: a median WEB verse is 34
tokens and a median *Institutes* paragraph is 408.

The starting budget is a tunable to be measured on the reference machine, not asserted here. The
ceiling is the 16 GB host floor with Ollama holding Qwen3-8B resident, and attention cost grows with
the square of sequence length, so the safe budget is lower for long chunks than a token count alone
suggests.

### Length-sorting is ours, because commit granularity is ours

`sentence-transformers`' `encode()` already sorts by length internally — and returns only when the
whole input is done. Handing it a 31,098-chunk backlog buys efficient batching and zero commit
granularity, so a kill at 95% loses everything. Taking the commit boundary therefore means taking
over the sorting: the resume query orders by `id` for determinism, and the returned backlog is
sorted by length in memory before batches are filled.

Batches then complete out of `id` order. That is safe, and it is worth stating why: the anti-join
asks only which chunks lack a vector, so any completion order resumes correctly. Nothing depends on
work having been done in order, which is what allows the ordering to be chosen for throughput.

### The model-load tax is per process, not per batch

BGE-M3 runs in-process from `/models/` (TECHNICAL-SPEC), about 2.3 GB, loaded once per invocation
regardless of backlog size. So the marginal cost of resuming is fixed and small against a multi-hour
run, and there is no argument here for large batches. Bound the crash loss; the restart is cheap.

---

## Corpus order under `--all`

Smallest first, WEB last.

The seven non-WEB corpora total 3,849 chunks of 34,947, just over a tenth of the work, so a
spot-checkable system arrives within minutes and WEB's 31,098 verses run as an unattended tail of
uniformly short, best-behaved text. PLAN's spot-check locators both land in the first few hundred
chunks. An interrupted first run leaves the corpora a human wants to look at already finished.

The *Institutes* re-chunk moved this: it is 2,260 chunks where it was 1,284, so it is now well over
half the non-WEB work rather than under half, and "smallest first" puts it last of the seven. The
ordering is unchanged because the argument was never about that corpus — it is that WEB is 89% of
the work and the least interesting to watch.

---

## The cases that are not the happy path

### A chunk the model cannot read whole

BGE-M3's `max_seq_length` is 8192, from the model's own `sentence_bert_config.json`. A longer chunk
does not fail — the encoder truncates and returns a vector, and nothing downstream can tell. The
chunk is then retrieved on its opening fraction and quoted from its whole text, and verification
passes, because check 2 matches against `corpus.chunks.text` rather than against the vector.

**The plan tokenises every staged record and refuses the corpus if any exceeds the limit.** Not a
warning: a truncated embedding is a chunk that silently is not what the index says it is, and the
project does not have a category for that.

This makes ingestion a check on acquisition's chunking, which is where the defect actually lives.
Both corpora that hit it have been re-chunked to paragraphs: the creation-study report first, and
the *Institutes* since — its longest section was 66,614 characters, which BGE-M3's own tokeniser
makes 16,714 tokens against a window of 8,192, and four of its chunks were over. **That re-chunk is
done and this task is no longer blocked.** The corpus is 2,260 chunks under a third locator form,
`Inst. 4.17.10.p1`, and its longest chunk is 2,890 tokens — 35% of the window, and a true bound,
because it is one paragraph with no internal break. See
[RECHUNK-INSTITUTES-DESIGN](RECHUNK-INSTITUTES-DESIGN.md).

The check stays exactly as specified. It is not a check on the *Institutes*; it is a check on every
corpus, and the corpus that motivated it is precisely the one that will now pass it silently. A
refusal that has never fired against real input is a refusal nobody has seen work, so the tests
below exercise it against an invented over-long record rather than relying on the corpus to
misbehave.

The exact number of offending chunks is deliberately not recorded here. It depends on the
tokeniser's characters-per-token ratio, which is not knowable without the tokeniser, and the
tokeniser arrives with the embedder in this task. The check measures it; this document does not
guess at it.

### A normalisation contract change

`work.json` carries `normalisation_version` and `corpus.chunks` stores it. If they disagree for a
corpus, every hash in it was computed under different rules, so the diff correctly reports every
chunk as an update — and reads as thousands of lines of noise that bury whatever else changed.

The plan collapses it to one line naming the version change and the count. The behaviour is
identical; only the report differs. This is the column doing the job the migration gives it, which
is to make a whole class of confusing failure "a lookup instead of an investigation."

### An unblessed corpus

Acquisition permits a corpus to stage while recording that its edition was never verified. Ingestion
refuses it. Staging is allowed to hold work in progress; the database is not.

### Re-verification, every run

Ingestion recomputes the sha256 of every staged record — it does not trust the hash the record
carries — and compares against committed `corpora/<corpus-id>/fingerprints.txt`. It refuses the
corpus if any locator disagrees, or if staging carries a locator the fingerprints file does not.
This costs under a second across all 8.2 MB, so it runs on every invocation rather than only on
insert. A check this cheap has no reason to be conditional, and a conditional check is one whose
skipped path is untested.

---

## A worked example

An invented corpus, `foo-1899-invented`, one chunk, locator `FOO 1.1`, text `The invented text.`

**Already done, by acquisition:** fetched, extracted, segmented into chunks — *this is where the
boundary is decided, permanently* — normalised under contract v1, hashed, compared against
`corpora/foo-1899-invented/fingerprints.txt`, and written to
`data/acquire/foo-1899-invented/stage/records.jsonl` as `{locator, text, content_hash}` beside a
`work.json` carrying the work facts, `chunk_count`, and `normalisation_version`. A human blessed it
once, against its edition diagnostic.

**`catena ingest --corpus foo-1899-invented`:**

1. Read both staged files. Recompute the hash of `The invented text.`, match it against the
   committed fingerprint. Tokenise: far under 8192.
2. Ask the database whether `(foo-1899-invented, FOO 1.1)` exists. It does not, so: one insert, one
   embedding pending. Print the tally. **Write nothing.**
3. `--apply`, phase one: upsert `works` from `work.json`; insert the chunk with its locator, text,
   `content_hash` and `normalisation_version`. Commit. The text is durable.
4. `--apply`, phase two: the resume query returns the chunk; it is embedded and its vector written
   to `chunk_embeddings` keyed `(chunk_id, 'bge-m3')`. Commit.
5. `chunk_metadata` now returns `FOO 1.1` carrying every field of the contract.

**And the crash.** Kill the process during a later corpus. `FOO 1.1` was committed at step 4 and is
untouched. Re-running recomputes the same diff: `foo-1899-invented` reports nothing to do and is
skipped in milliseconds, and the tally shows only what remains. Nothing recorded that a run had
previously reached this corpus, because nothing needed to.

---

## Testing

Invented text and invented corpus IDs throughout, per ADR-0014 and the rule Task 8's verification
tests already follow. The design is shaped to make that cheap rather than merely possible.

**The plan is a pure function** from staged records and database state to a list of actions. That is
where every interesting decision lives — the three-way diff, the two keys, the version collapse, the
over-limit refusal — and it is testable with no database, no model, and no fixtures beyond a few
invented records.

**The embedder sits behind an interface** (ADR-0006, which requires this for swappability anyway), so
a fake returning deterministic vectors exercises the whole apply path without loading 2.3 GB. Batch
filling and length-sorting test against it directly.

**The test that proves the design:** apply, kill mid-embed, re-apply; assert the plan converges to
zero remaining and that no chunk gained a duplicate embedding row. Against a fake embedder this runs
in about a second, which means the resumability claim is covered by a unit test rather than by a
multi-hour manual exercise nobody repeats.

**The one that proves the trap:** ingest, change a staged record's text, re-apply, assert the chunk's
embedding rows were deleted and re-created. The buggy implementation passes every other check in the
system, so this is the only place it is caught.

Integration against live Postgres follows the `make test-schema` precedent. The Python suite also
asserts the shared normalisation fixture committed in Task 2, as PLAN requires.

---

## What lands

- `services/catena/src/catena/ingest/` — plan, apply, embedder interface, CLI
- `catena ingest` wired into `catena.__main__`
- `make ingest CORPUS=<id>` and `make ingest-all`, through `$(COMPOSE) run --rm catena`, since the
  command needs `/data`, `/models` and the database. `guard-make-targets` requires any target named
  in documentation to have a rule.
- The embedding dependency added to `services/catena/pyproject.toml`, which currently carries only
  protobuf, grpcio, pyyaml and pypdf

## Spec changes in the same change

1. **PLAN Task 5** names `/data/staged/<corpus-id>/`. No such directory was ever built; the seam is
   `data/acquire/<corpus-id>/stage/`. Corrected.
2. **TECHNICAL-SPEC** says "Text is normalised at ingestion". ADR-0014 moved normalisation into
   acquisition and the staged records are already post-normalisation. Corrected.
3. The convergence policy, the `--apply` inversion and its justification, and the over-limit refusal
   are decisions the specs did not anticipate. Folded into TECHNICAL-SPEC.
4. **PLAN Task 5** gained its dependency on the *Institutes* re-chunk, and Task 4 gained that item.
   Both are now discharged: the re-chunk landed on `main` and Task 4's item is ticked.

## Status

Designed, not implemented, and **no longer blocked**. The *Institutes* re-chunk it waited on is
done, blessed and merged: 2,260 chunks, longest 2,890 tokens against a window of 8,192, so every one
of the eight corpora now passes the over-limit refusal this design specifies. See
[RECHUNK-INSTITUTES-DESIGN](RECHUNK-INSTITUTES-DESIGN.md), which also records two defects that
re-chunk exposed — 172 CCEL rules inside the chunk text, and a prefatory address with no end that
had been absorbing four other works.

Implementation is the next thing to start.
