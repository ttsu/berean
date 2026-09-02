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

```
git clone https://github.com/ttsu/berean.git
cd berean
cp .env.example .env
make provision      # pulls the pinned model weights, acquires the corpus into ./data/
make dev            # docker compose up, and wait for health
```

Provisioning is not optional. Neither model weights nor corpus text ships in the repository
(ADR-0014), so `docker compose up` on its own brings up a stack with no models and an empty
corpus.

**What it costs.**

| | |
| --- | --- |
| RAM | **16 GB** host floor. Ollama holding Qwen3-8B (~5.2 GB resident), BGE-M3 (~2.3 GB), Postgres, and a five-container Langfuse install |
| Docker memory | **12 GiB allocated to the Docker VM**, and this is the constraint that actually bites on macOS and Windows — see below |
| Disk | **30 GB** free. ~7.5 GB of weights, ~8 GB of container images, and the rest for acquired text, staged records, and the vector index |
| Time | **2–4 hours** on CPU for a clean provision, almost all of it embedding. Estimated, not yet measured — Task 11 records the wall-clock figure on the reference machine |

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
make check          # guards, guard tests, and compose validation
make build          # build the gateway and catena images
make reset          # destroy the volumes, so Postgres re-runs its init scripts
```

Two guards run in `make check` and are not optional:

- **`make guard-corpus`** rejects any tracked file that could carry corpus text. It denies by path
  and shape — nothing under `./data/` or `./models/`, only `manifest.yaml` and `fingerprints.txt`
  under `corpora/<corpus-id>/`, no text-bearing formats in the source tree, and a size ceiling on
  test fixtures. It never judges what a file means, because a rule needing per-corpus licensing
  judgement is the rule ADR-0014 exists to replace.
- **`make guard-make-targets`** rejects any `make <target>` named in documentation that has no rule
  in the Makefile.

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
