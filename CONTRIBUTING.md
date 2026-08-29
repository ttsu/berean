# Contributing

## The one line to internalise

**Go is the trust boundary. Python is the model layer.**

Python produces claims; Go adjudicates them. If you are writing verification logic in Python or
retrieval logic in Go, stop and reconsider.

## Before you write code

Read the relevant spec in [specs/](specs/). If it is silent on what you need, ask rather than
infer — and then update the spec with the answer.

**Update specs in the same change as the implementation.** A spec that lags the code is worse than
no spec, because people trust it.

## Hard rules

These are correctness or legal failures, not style preferences:

1. No ESV or NIV text anywhere — source, fixtures, tests, or golden sets.
2. Corpus IDs are edition-specific. `wcf` is a bug; `wcf-1788-american` is correct.
3. Nothing renders unverified.
4. No token streaming.
5. No model introspection, in any form, anywhere.
6. `docker compose up` must work with no external accounts.
7. No CC-BY-NC models or datasets.

## Decisions

Significant technical decisions get an ADR in [docs/adr/](docs/adr/), using
[the template](docs/adr/0000-template.md).

The **Alternatives rejected** section is the point. A decision without it is just a note, and in
six months nobody remembers why the obvious option was not taken.

ADRs are immutable once accepted. To change one, write a new ADR that supersedes it.

## Adding a corpus or a tradition

Follow [.agents/skills/ingest-corpus/SKILL.md](.agents/skills/ingest-corpus/SKILL.md) or
[.agents/skills/add-tradition-profile/SKILL.md](.agents/skills/add-tradition-profile/SKILL.md).
They exist because both processes have failure modes that are silent.

## Retrieval changes

Never make one without a baseline number. See
[.agents/skills/run-evals/SKILL.md](.agents/skills/run-evals/SKILL.md).

## A note on the domain

This project makes claims about what denominations teach. Getting an edition wrong or resolving a
genuinely contested question is not a cosmetic bug — it misrepresents a tradition to people who
care about it. When unsure about a theological or confessional detail, ask rather than guess.
