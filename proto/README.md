# proto/

The Go↔Python contract. **Normative** — where this and any prose document disagree, the proto
wins and the prose is stale.

Nothing is defined here yet. See
[../specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md](../specs/001-phase-1-pca-baseline/INTEGRATION-SPEC.md)
for the intended shape, and Task 2 of the plan.

Layout will be `berean/v1/`. Versioned from the first commit.

```proto
option go_package = "github.com/ttsu/berean/gen/berean/v1;bereanv1";
```

Go output lands in `gen/`, under the root module. Python output goes to `services/catena/gen/`.

Fields that are present-but-unused in Phase 1 — `conversation_context`, `tier_weights`,
`rewritten_query` — exist so later phases add behaviour rather than break the contract. Do not
remove them because they are unused.

Adding a field is cheap. Renaming or removing one is breaking and needs a new package version.
`buf breaking` runs in CI against main.
