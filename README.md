# Berean

Tradition-aware theology and ecclesiology Q&A. You select a denomination; that selection
determines which documents are treated as authoritative, and **every citation resolves to real,
licensed source text before it renders** — or the system says it can't source the answer.

Internal codename for the retrieval and citation service: **Catena**.

The name is from Acts 17:11 — the Bereans examined the Scriptures daily to check whether what they
were told was true. That is what the citation layer does.

> **Not affiliated with berean.bible or the Berean Standard Bible.**

## What makes it different

Most retrieval systems filter documents in or out. Berean assigns each corpus a **stance** within a
tradition:

| Tier | Meaning | PCA example |
| --- | --- | --- |
| `binding` | Confessional standards | WCF, WLC, WSC |
| `governing` | Polity and church order | BCO |
| `advisory` | Respected but non-binding | Calvin, Bavinck, Vos |
| `contrary` | Retrievable, labelled as another tradition's position | Council of Trent |
| `excluded` | Explicitly repudiated by the tradition | Federal Vision (2007 report) |

The `excluded` tier is the point. "This view was examined and rejected by your denomination in
2007" is an answer no filter can produce.

The system also models **contested** loci — where a denomination genuinely disagrees with itself —
and declines to resolve them.

## What this is not

Berean is an educational and research tool. It reports what a tradition's own documents say. It
does not adjudicate whether they are right.

The authority tiers are descriptive, not evaluative. `binding`, `contrary`, and `excluded` record
how the *selected denomination* classifies a corpus, sourced from that body's own confessional and
judicial acts — not how this project rates it. Labelling the 2007 Federal Vision report `excluded`
under a PCA profile is a claim about the PCA's judgement and nothing more. The same corpus can be
`binding` in one profile and `contrary` in another; that is the design working, not a contradiction.

Nothing here endorses any denomination, confession, or theological position, and nothing here
should be read as the personal views of the project's author or its contributors. Which traditions
are modelled first reflects what is publicly documented and tractable to implement — it is not a
ranking. No denomination or church body has reviewed, endorsed, or is otherwise affiliated with
this project.

Answers are machine-generated and can be wrong even when every citation verifies. Verification
proves a quotation is real, correctly attributed, and licensed — not that the argument built on it
is sound. This is not pastoral counsel and it is no substitute for your officers, your presbytery,
or your own reading of the sources. Examine them yourself; the name is a reminder to do exactly
that.

## Architecture in one line

**Go is the trust boundary. Python is the model layer.** Python produces claims; Go adjudicates
them. One gRPC call per generation attempt — once per turn, plus at most one regeneration when
verification fails.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/adr/](docs/adr/).

## Status

**Phase 1** — ingest one corpus (Westminster Standards, 1788 American revision), naive RAG, CLI.
Proving citations verify end to end. Not yet usable.

Phase 2 (eval harness) comes before Phase 3 (hybrid retrieval), deliberately.

## Getting started

**On the host**, beyond Docker itself: `git`, `make`, `curl`, `python3` (the guards), and
[`uv`](https://docs.astral.sh/uv/) (the embedding-model fetch). Everything else runs in a
container. Docker Compose v2 — `docker compose`, not `docker-compose`.

```
git clone https://github.com/ttsu/berean.git
cd berean
cp .env.example .env
make provision            # pulls the pinned model weights, acquires the corpus into ./data/
make dev                  # docker compose up, and wait for health
make ingest-all APPLY=1   # chunk, embed and load every acquired corpus
docker compose run --rm gateway \
    ask --profile pca "What does the Westminster Confession teach about assurance?"
```

Provisioning is not optional. Neither model weights nor corpus text ships in the repository
(ADR-0014), so `docker compose up` on its own brings up a stack with no models and an empty
corpus. Acquisition puts text on your disk; ingestion is the separate step that chunks, embeds
and loads it, and until it has run the profile names corpora the database does not have — which
`berean ask` refuses at load rather than answering thinly from what is there.

**What it costs.**

| | |
| --- | --- |
| RAM | **16 GB** host floor. Ollama holding Qwen3-8B (~5.2 GB resident), BGE-M3 (~2.3 GB), Postgres, and a five-container Langfuse install |
| Docker memory | **12 GiB allocated to the Docker VM**, and this is the constraint that actually bites on macOS and Windows — see below |
| Disk | **30 GB** free. ~7.5 GB of weights, ~8 GB of container images, and the rest for acquired text, staged records, and the vector index |
| Time | **2–4 hours** on CPU for a clean provision, almost all of it embedding. Estimated, not yet measured — Task 11 records the wall-clock figure on the reference machine |
| Per answer | **2–4 minutes** on CPU. Measured, not estimated — see below |

**On macOS and Windows, host RAM is not the binding constraint — the Docker VM's allocation is.**
Docker Desktop runs a Linux VM with its own memory ceiling, commonly defaulting to around 8 GiB
regardless of how much the host has. The stack idles at roughly 2.5 GiB (ClickHouse alone takes
~1.3), and Qwen3-8B needs ~6 GiB resident on top of that. Under an 8 GiB ceiling the model is
OOM-killed the first time it is asked to generate, and the error names neither memory nor Docker:

```
llama-server process has terminated: signal: killed
```

That reads as a broken model or a bad pin, and it is neither. Raise Docker Desktop's memory limit to
**12 GiB** (Settings → Resources → Memory) before running anything that generates. Linux hosts run
containers natively and are bounded by host RAM alone, so the 16 GB floor is the whole story there.

**An answer takes minutes, not seconds, and that is expected.** On the reference machine Qwen3-8B
q4_K_M generates at roughly **3.4 tokens per second** against a full retrieval prompt — the context
makes each token dearer than a bare prompt's ~9 t/s — so a Phase 1 answer lands in two to four
minutes. Retrieval itself is three orders of magnitude faster: embedding and search together take
about three seconds, and the trace records each stage separately, so a slow answer can be attributed
rather than guessed at. A GPU changes this picture entirely; the acceptance test does not assume
one.

**A hosted generator is an option, and it is off.** Setting
`CATENA_GENERATION_PROVIDER=anthropic` in `.env` points generation at the Claude API with a key you
supply — `ANTHROPIC_API_KEY`, which this project ships none of. Cost is an **estimate: roughly
$0.05–0.08 per answer**, arithmetic over a Phase 1 prompt plus a completion at published rates,
and it **excludes the thinking tokens**, which are billed as output — so a real bill runs higher.
Nothing on that path is measured here, latency included; the figures above are the local default on
the reference machine, and this repository does not mix measured numbers with estimated ones. The default is `ollama`, selection is
never inferred from a key being present, and nothing else about the system changes: the same
prompt, the same schema, the same verification. What does change is that the passages retrieved for a question
are sent to Anthropic, before the gateway's licence check has ruled on them. That is your call,
under your account and their terms, and it matters most for the `local-only` corpora below
(ADR-0025, [docs/CORPUS-POLICY.md](docs/CORPUS-POLICY.md)).

`make provision` acquires seven corpora and embeds roughly 35,000 chunks, dominated by the ~31,100
verses of the WEB Bible. It is resumable per corpus, so an interrupted run continues rather than
restarts. Nothing in the request path is affected — ingestion is always a batch job.

Model weights are pinned in [tools/provision/models.lock.yaml](tools/provision/models.lock.yaml)
and provisioning fails loudly if an upstream tag has been republished. The generator is the largest
single variable in the Phase 2 baseline, so a silent change to it would move that number invisibly
(ADR-0018).

**Serving PCA-published documents is opt-in.** The *Book of Church Order* and the 2000 creation
study committee report are ingested as `local-only`, and verification refuses to serve them unless
you set `BEREAN_SERVE_LOCAL_ONLY=true` in `.env`. It defaults to **false**, so the opt-in is a
recorded act rather than an omission — and so a fresh clone degrades on questions those documents
answer until you set it. That is a decision about your deployment, not ours (ADR-0017,
[docs/CORPUS-POLICY.md](docs/CORPUS-POLICY.md)).

That must give a working system with no external accounts. It is the project's acceptance test —
if a change breaks it, the change is wrong. `make dev-offline` brings the same stack up on an
internal network with egress blocked, which is how the claim gets tested rather than asserted.

## Development

```
make help           # every target, with a one-line description
make hooks          # install the pre-commit hook that enforces ADR-0014
make proto          # regenerate the Go and Python stubs from proto/
make check          # guards, unit suites, contract lint, and compose validation
make test           # the unit suites on their own
make test-schema    # assert the schema, its constraints and both roles' grants (needs `make dev`)
make test-gateway-db # assert the corpus reads and verification latency against a live database (needs `make dev`)
make migrate        # apply db/migrations/ to a running Postgres
make build          # build the gateway and catena images
make reset          # destroy the volumes, so Postgres re-runs its init scripts
```

All DDL lives in `db/migrations/`, as reversible `up`/`down` pairs applied by a pinned
golang-migrate container. `make dev` applies them, so `make migrate` is only for picking up a new
migration without a restart. `make test-schema` is not part of `make check`: `check` runs with
nothing started, and a grant is only demonstrated by a statement a live database actually refuses.
`make test-gateway-db` is out for the same reason — it asserts that every corpus `profiles/pca.yaml`
names is really ingested, that a citation resolves to the row the corpus tables actually hold, and
that verification stays inside its latency target against the real index. A fake can only agree
with the first and cannot see the rest.

If `make dev` fails with **`error: failed to open database: no schema`**, the Postgres volume
predates the schemas the migrator needs. The init script that creates them runs once, on an empty
data directory, so `make reset` is the fix. Creating the missing schema by hand is not: a volume
old enough to lack it is missing others too, and repairing one hides the rest.

`buf` and the Go toolchain run in pinned containers, so neither is a host prerequisite. The
generated protobuf stubs **are committed** (ADR-0022), so a clean clone builds and `docker compose
up` works with no codegen step. Change anything under `proto/`, run `make proto`, and commit what it
writes: `make guard-proto-fresh` fails when the committed stubs and the contract disagree.

Two guards run in `make check` and are not optional:

- **`make guard-corpus`** rejects any tracked file that could carry corpus text. It denies by path
  and shape — nothing under `./data/` or `./models/`, only `manifest.yaml` and `fingerprints.txt`
  under `corpora/<corpus-id>/`, no text-bearing or dump formats in the source tree, and a size
  ceiling on test fixtures. It never judges what a file means, because a rule needing per-corpus
  licensing judgement is the rule ADR-0014 exists to replace.
- **`make guard-make-targets`** rejects any `make <target>` named in documentation that has no rule
  in the Makefile.

`make check` is also what CI runs, on every pull request and every push to `main`
([`.github/workflows/check.yml`](.github/workflows/check.yml)). The workflow installs `uv`, runs
`make proto`, and then calls that one target — `buf` and Go stay in their pinned containers there
too. So a green run means the checks you run locally passed, rather than a parallel set of checks
that has drifted from them. Nothing in the path touches `./data/`, `./models/` or an upstream
corpus, which is how ADR-0014 survives having a CI log at all.

## Asking a question

```
docker compose run --rm gateway ask --profile pca [--top-k N] [--show-work] "question"
```

One turn per invocation. The gateway resolves the profile, makes one gRPC call into Catena,
verifies every citation that comes back, records the whole turn, and prints — in that order. The
recording comes before the printing deliberately: verification refusing to ship is an event worth
having in the log, and a write that failed after the answer was printed is not.

- `--profile <name>` selects `profiles/<name>.yaml`. There is no default: which corpora are
  authoritative is half the question.
- `--top-k N` overrides the configured retrieval depth for this turn. The value actually used is
  what the trace records, not the configured default.
- `--show-work` prints the trace after the answer — the settings each attempt ran under, every
  candidate retrieved with its score and whether it was included, each of the four checks per
  citation, and every answer-level rule that broke. It is a log. It is not an account of how the
  model reasoned, and there will never be one (ADR-0003).

Each citation renders with its corpus ID, its locator, the work and edition it came from, and the
stance this profile assigns it. A `contrary` or `excluded` citation additionally carries the
profile's own label for that corpus, so another tradition's position cannot be read as this one's.

Three outcomes, and they read differently on purpose:

| | |
| --- | --- |
| **An answer** | Position, arguments, descriptions, each with citations that verified, and a confidence with a stated reason |
| **Silence** | "The sources in scope are silent on this question", above the model's own brief statement of why. A **pass** — the corpus really is silent (UC-2) |
| **A refusal** | "I can't source this adequately", and nothing else. Verification refused to ship after a regeneration; no partial content, no warning beside one |

Answering takes minutes on CPU, almost all of it generation — see the cost table above. Exit status
is 0 for all three outcomes, including the refusal: degradation is the verification system working,
and the rate lives in `trace.responses.overall_result` where it can be counted against the turns
that verified. `64` is a usage error and `69` means the stack is not ready.

## Ingestion

```
docker compose run --rm catena ingest (--corpus <id> | --all) [--apply]
```

`make ingest CORPUS=<id>` and `make ingest-all` wrap it, with `APPLY=1` for `--apply`.

It makes the database agree with the blessed staging directory `catena acquire` wrote into
`./data/`: it reads the staged records, checks each chunk against the fingerprints committed in
`corpora/<corpus-id>/fingerprints.txt`, diffs them against what is loaded, and prints the plan —
inserts, updates, deletes, and how many embeddings are outstanding.

**It writes nothing without `--apply`.** The plan is recomputed on both paths rather than saved
between them, so the dry run cannot go stale. Ingestion is idempotent on the content hash and
resumable per corpus, so an interrupted run continues rather than restarts; deletes cascade to
embeddings, which is why applying is the flag rather than the default.

Ingestion never touches the network and never parses an upstream format — acquisition did both,
and its output is what this reads. Re-running it after `make corpus-verify` reports drift is how an
upstream edition change reaches the index.

## Bible translations

Retrieval runs on the public-domain WEB text. Copyrighted translations are never ingested.

**ESV display is bring-your-own-key.** Each deployer accepts Crossway's non-commercial terms
directly. No key ships with this project. See [docs/CORPUS-POLICY.md](docs/CORPUS-POLICY.md).

## Contributing

Specs are the source of truth and live in [specs/](specs/). Read the relevant one before writing
code, and update it in the same change when implementation reveals something it did not anticipate.

Agent-facing context is in [AGENTS.md](AGENTS.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

Corpus texts carry their own licenses, recorded per chunk and surfaced on the attribution page.
