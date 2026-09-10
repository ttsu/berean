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
- On verification failure: regenerate once carrying `previous_failures`, `answer_failures` and
  `attempt`, then degrade. **Never render with a warning attached.** Go sends verification results,
  never composed prose.
- **Two kinds of finding, split by what the rule is about.** The four checks are per citation and
  produce `VerificationResult`. The rules that are about a *slot* — an argument carrying no
  citations, `position` where nothing was argued, the bounds on `no_answer_reason`, and the omission
  check, which fires on an answer whose every citation passed all four — produce `AnswerFailure`
  (ADR-0024). Both are metadata; neither is ever an instruction.
- The tier floor on an argument is answer-level, not part of check 3. Advisory inside an argument
  is permitted and fails only when it is the argument's whole support.
- **Degradation always follows exactly two generation attempts.** An unreachable Catena or an
  unreachable database is an *error*, not a degraded answer: `DEGRADED` means verification refused
  to ship, and laundering an outage into it makes the degradation rate unreadable.
- An honest non-answer is `VERIFIED`, not `DEGRADED`, and renders differently. UC-2 and UC-5 mean
  opposite things and must not share a metric.
- Write scope: session and trace tables only. The `gateway` DB role is read-only on corpus tables
  and that is deliberate — do not work around it.
- **Persist the turn before rendering it.** A turn that reached a user and was never recorded is the
  one outcome the trace tables exist to prevent. Verification refusing to ship is a recorded event;
  a write that failed after the answer was printed is not.
- The whole turn is one transaction, written after it completes: `overall_result` and `confidence`
  are known only then, and a partial trace enters the Phase 2 dataset as a turn that retrieved
  nothing. A row that lies is worse than a row that is missing.
- **A malformed response from Catena is an error, not a degraded turn**, and never a trace row with
  sentinels standing in for what Catena did not send. It sits with the unreachable-Catena case, not
  with the answers verification refused to ship.
- **The renderer decides nothing.** `internal/render` is handed a finished turn and prints the
  answer object that turn nominated. It reads no attempt, so a refused attempt's prose is
  unreachable from it — including through `--show-work`, which is provenance and prints no answer
  prose at all. It never summarises, hedges, softens, or explains: `Confidence.reason` stays the
  only Go-authored string a reader sees, and the refusal and the silence are constants rather than
  sentences composed per turn.
- **The refusal and the honest non-answer must not read alike.** "I can't source this adequately"
  and "The sources in scope are silent on this question" share no words on purpose. UC-2 and UC-5
  mean opposite things; a reader must be able to tell them apart without opening a trace.
- **A citation renders with the tier the resolved profile assigns**, never the one it claimed —
  the same rule as check 3, one layer out. `contrary` and `excluded` additionally render the
  profile's label, which is why the loader requires one at those two stances.

## Conventions

- Generated protobuf types are the contract. Do not define a parallel struct for the answer object.
  They are **committed** (ADR-0022): change `proto/`, run `make proto`, and commit what it writes —
  `make guard-proto-fresh` fails when the tree and the stubs disagree.
- Quote comparison normalises through `internal/normalise`, never through `unicode.IsSpace` or a
  hand-rolled trim. It holds the enumerated `White_Space` set on purpose: Python's `\s` matches
  four code points Go's does not, so the two standard libraries are not the same function. Both
  sides assert `testdata/normalisation/vectors.json`, and drift shows up as a quote that will not
  match a passage it is plainly inside.
- Errors wrap with context; no bare `err` returns across package boundaries.
- Verification is ordinary software — string matching and indexed lookups. If a change here starts
  to need a model call, something has gone wrong.
