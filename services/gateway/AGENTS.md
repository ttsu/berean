# services/gateway — AGENTS.md

Go. **This service is the trust boundary.**

Everything arriving from `services/catena` is untrusted input. Treat a citation from Python
exactly as you would treat a value from an HTTP request body.

Import path: `github.com/ttsu/berean/services/gateway/...`. The module root is the repository
root, not this directory.

## Owns

Auth, sessions, rate limiting, profile resolution, **citation verification**, trace persistence,
translation-API fetch with attribution, SSE to the client.

Phase 1 scope is much narrower: a CLI binary that resolves the profile, makes one gRPC call,
verifies, and prints. No HTTP, no auth, no SSE. See
[../../specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md](../../specs/001-phase-1-pca-baseline/TECHNICAL-SPEC.md).

## Does not own

Embedding, retrieval, reranking, generation, ingestion, evals. If you are about to write retrieval
logic here, stop — it belongs in Catena.

## Rules

- **Exactly one gRPC call into Catena per turn.** A second call means the seam is wrong. Raise it
  rather than working around it.
- Send a **resolved FilterSpec**, never the profile. No profile name, user identity, or session
  state crosses the boundary. There is a unit test asserting this; keep it passing.
- Verification checks the tier recorded **in Postgres**, never the tier Python claimed.
- A citation to a corpus that was not in the FilterSpec is a fabrication. Fail immediately.
- On verification failure: regenerate once, then degrade. **Never render with a warning attached.**
- Write scope: session and trace tables only. The `gateway` DB role is read-only on corpus tables
  and that is deliberate — do not work around it.

## Conventions

- Generated protobuf types are the contract. Do not define a parallel struct for the answer object.
- Errors wrap with context; no bare `err` returns across package boundaries.
- Verification is ordinary software — string matching and indexed lookups. If a change here starts
  to need a model call, something has gone wrong.
