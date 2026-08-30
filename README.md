# Berean

Tradition-aware theology and ecclesiology Q&A. You select a denomination; that selection
determines which documents are treated as authoritative, and **every claim resolves to a real,
licensed source before it renders** — or the system says it can't source the answer.

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
docker compose up
```

That must give a working system with no external accounts. It is the project's acceptance test —
if a change breaks it, the change is wrong.

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
