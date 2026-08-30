# ADR-0012: Drop Tyndale House GNT; SBLGNT and OSHB are the base texts

- **Status:** Accepted
- **Date:** 2026-08-30
- **Phase:** 3–4 in effect, but the licensing rule it settles is Phase 0

Amends ADR-0008 on its base-text recommendation only. ADR-0008's decision — that Hebrew and Greek
are a deterministic lookup tool rather than a retrieval corpus — is unchanged and still governs.

## Context

ADR-0008 lists Tyndale House GNT among the texts usable in place of NA28 and BHS. THGNT is
CC BY-NC-ND, and two independent terms bite:

- **NC.** ADR-0007 commits the project to Apache-2.0, which grants downstream commercial use. A
  bundled non-commercially-licensed corpus cannot carry the rights the project grants, and you
  cannot grant rights you do not hold.
- **ND.** Separately from NC, this system chunks, normalises, embeds, and serves excerpts of every
  corpus it ingests. That is plausibly the creation of a derivative work, which NoDerivatives
  restricts regardless of whether the use is commercial.

The project's intended use is personal and non-commercial. That does not change the analysis, and
ADR-0007 already says so in as many words: personal non-commercial intent does not rescue a
restrictively licensed dependency. The binding constraint is the licence the project *grants*, not
the use its author makes of it.

The rules also disagreed with each other. SHARED §2 disqualified CC-BY-NC *models*; CONTRIBUTING
disqualified NC *models or datasets*. A reviewer got a different answer depending on which document
they opened.

## Decision

**THGNT is not a base text.** SBLGNT for Greek and OSHB (CC-BY) for Hebrew are, as ADR-0008 already
decided in its own Decision section — THGNT appeared only in the rejected-alternatives note.

It moves to the off-limits list in CORPUS-POLICY rather than being deleted, so it is not
re-proposed by someone reading a leaderboard of Greek texts.

SHARED §2 is extended to cover models, datasets, and corpora alike, and to name ND as disqualifying
for the derivative-work reason above, so both documents now state the same rule.

## Alternatives rejected

- **Keep THGNT, relying on the project's personal non-commercial use.** This is the reasoning
  ADR-0007 was written to foreclose. It also fails on ND independently of NC, so even a purely
  non-commercial deployment that redistributed embeddings would be exposed.
- **Keep it as optional-and-not-default, on the ESV bring-your-own-key pattern.** Legitimate, and
  the route to take if THGNT is ever genuinely wanted: not bundled, deployer opts in, never in the
  default path. Rejected for now because it costs an adapter and a licence-acceptance flow to obtain
  a Greek text SBLGNT already provides. Build it when there is a reason, not in advance.
- **Relicense the project to something non-commercial.** Would make THGNT usable. It supersedes
  ADR-0007, forfeits open-source status, and rewrites LICENSE, NOTICE, README, and CONTRIBUTING — an
  enormous cost to acquire one Greek text that is not needed.

## Consequences

The Greek base text is SBLGNT alone, so **its own terms must be confirmed before ingestion** rather
than assumed. CORPUS-POLICY already flags this ("own terms — check before ingestion"), and ADR-0008's
description of it as plainly usable is the looser of the two readings; the CORPUS-POLICY reading
governs.

No behavioural change in Phase 1 — original languages are Phase 3–4 and nothing ingests Greek yet.
The cost of settling it now is one document edit; the cost of settling it after ingestion is a
re-ingest.

The models-versus-datasets discrepancy is closed, so a corpus licence check gives the same answer
from SHARED, CONTRIBUTING, or CORPUS-POLICY.
