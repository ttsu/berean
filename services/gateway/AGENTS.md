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

- **One gRPC call into Catena per generation attempt.** A verification failure permits exactly one
  retry call (ADR-0010); a turn therefore makes at most two. Any other second call means the seam is
  wrong — raise it rather than working around it.
- Send a **resolved FilterSpec**, never the profile. No profile name, user identity, or session
  state crosses the boundary. There is a unit test asserting this; keep it passing.
- Verification checks tier against the **resolved profile Go holds**, never the tier Python claimed.
- Tier is checked against the claim's **slot**, not its meaning: an `Argument` needs a `binding` or
  `governing` citation and never holds `contrary` or `excluded`; `descriptions` and
  `contrary_positions` take any tier with labels. Never classify what a claim means (ADR-0016).
  Tier is a per-tradition stance, not a property of the corpus — the same corpus is `contrary` under
  one profile and `binding` under another, so there is no single tier to record against it.
- A citation to a corpus that was not in the FilterSpec is a fabrication. Fail immediately.
- A contested answer carries **no** `arguments`. Flagging a locus contested and resolving it in the
  same answer passes every other check, and it is the worst outcome the product can produce
  (ADR-0019).
- Quotes are checked with a 40-character floor. The four checks prove a citation is real, never that
  its quote supports the claim — that limit is stated in INTEGRATION-SPEC and measured in Phase 2.
- **Go derives both `confidence.level` and `confidence.reason`**, overwriting whatever Python sent.
  A model-authored confidence is introspection in a structured field (SHARED §4, ADR-0020).
- `no_answer_reason` is the one model-authored string that renders uncited. Enforce its bounds
  structurally — non-empty only when every content slot is empty, and at most 200 characters — and
  never relax them. Every slot empty with no reason is a malformed generation: regenerate.
- On verification failure: regenerate once carrying `previous_failures` and `attempt`, then degrade.
  **Never render with a warning attached.** Go sends verification results, never composed prose.
- An honest non-answer is `VERIFIED`, not `DEGRADED`, and renders differently. UC-2 and UC-5 mean
  opposite things and must not share a metric.
- Write scope: session and trace tables only. The `gateway` DB role is read-only on corpus tables
  and that is deliberate — do not work around it.

## Conventions

- Generated protobuf types are the contract. Do not define a parallel struct for the answer object.
  They are generated rather than committed — run `make proto` (ADR-0013 defers the
  commit-or-generate decision to Phase 2).
- Quote comparison normalises through `internal/normalise`, never through `unicode.IsSpace` or a
  hand-rolled trim. It holds the enumerated `White_Space` set on purpose: Python's `\s` matches
  four code points Go's does not, so the two standard libraries are not the same function. Both
  sides assert `testdata/normalisation/vectors.json`, and drift shows up as a quote that will not
  match a passage it is plainly inside.
- Errors wrap with context; no bare `err` returns across package boundaries.
- Verification is ordinary software — string matching and indexed lookups. If a change here starts
  to need a model call, something has gone wrong.
