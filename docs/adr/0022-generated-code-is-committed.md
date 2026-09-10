# ADR-0022: The generated protobuf is committed, not gitignored

- **Status:** Accepted
- **Date:** 2026-09-10
- **Phase:** 1 — Task 7 puts Catena into the default `docker compose up`

## Context

ADR-0013 deferred "commit or generate" to Phase 2 on the grounds that it is CI policy rather than
contract design. That was right at the time and stopped being right in Task 7, for a reason that
had nothing to do with CI.

Until now `gen/` was gitignored and Catena was a container that did nothing, held out of the default
`up` behind a compose profile. Task 7 gives it a gRPC server, drops the profile, and makes the
gateway depend on it. So `docker compose up` on a clean clone now builds an image that must import
the contract — and **SHARED §1 makes that command the acceptance test**, the one CLAUDE.md says a
change cannot be worth breaking.

That turns a filing question into a build question. `buf.gen.yaml` uses **remote** plugins
(`buf.build/protocolbuffers/go`, `.../python`, and three more), so generating the stubs requires
`buf` and a reachable, un-rate-limited buf.build. Whether that dependency sits inside the image
build or in a `make` step the user has to know to run first is the whole of the decision.

Nothing about the contract changed. What changed is who has to be able to build it, and when.

## Decision

**Commit the generated code — both sides — and assert in CI that regenerating produces no diff.**

- `gen/` (Go) and `services/catena/gen/` (Python) are tracked. The `.gitignore` block that excluded
  them is replaced by a comment pointing here.
- `services/catena/Dockerfile` copies `services/catena/gen` and packages it into the wheel via
  `[tool.hatch.build.targets.wheel] packages`, so an editable dev install and the image resolve the
  import identically. `.dockerignore` gains the matching allow-list line.
- `make check` runs `guard-proto-fresh`, which regenerates and fails on any diff **or any untracked
  stub** — the second half matters because a newly added message produces a file `git diff` reports
  as clean.

This answers the question ADR-0013 deferred, in the "commit" direction, for both languages at once.
Answering it for Python alone would have left the same question open with a smaller blast radius
and two conventions to remember.

## Alternatives rejected

- **Run `buf` in a builder stage inside the Dockerfile.** Keeps the tree free of generated code and
  keeps `docker compose up` working on a clean clone. Rejected because it puts buf.build — a SaaS —
  into the build path of the acceptance test. It needs no account, so it does not strictly violate
  SHARED §1, but "no external accounts" exists to make the acceptance test survive a hostile
  network, and a remote plugin fetch fails exactly when a corporate proxy or an offline afternoon
  says so. The failure would also be remote from its cause: a rate limit surfacing as a broken
  image build.
- **`make build` depends on `make proto`.** The tidiest option on paper: generated code stays out
  of the tree, `buf` stays out of the image. Rejected because it only works when the build goes
  through `make`. `git clone && docker compose up` — which is the acceptance test as literally
  written, and what a new contributor types — fails on `COPY services/catena/gen: not found`, and
  the error names a path rather than the missing step.
- **Commit the Python stubs only.** Enough for Task 7, since nothing yet builds Go from a clean
  clone in anger. Rejected as half a decision: it leaves ADR-0013's question open, and it makes the
  convention depend on which language you are in, which is the kind of rule nobody remembers under
  pressure.
- **Keep deferring to Phase 2.** Rejected because the deferral rested on this being CI policy, and
  it is now a property of the acceptance test.

## Consequences

**What it makes easy.** A clean clone builds and runs with `docker compose up` and nothing else —
no `buf`, no network beyond the base images, no ordering a reader has to know. The contract suite
no longer skips itself on a fresh checkout, and `test_proto_contract.py`'s skip branch becomes
dead.

**What it makes hard.** Every `proto/` change is now a two-part commit, and a reviewer sees
generated diffs beside the contract change. That is the cost, and `guard-proto-fresh` is the whole
of the mitigation: a tree that stops matching what produced it fails `make check` rather than
drifting.

Regeneration is not reproducible across `buf` versions — which is why `BUF_IMAGE` is pinned
exactly, as every image in this stack already is. A `buf` bump now produces a diff in tracked files,
which is a feature: it makes the blast radius of the bump visible in the same commit.

**What would cause us to revisit it.** If `buf` gains local (non-remote) plugin support in this
project's toolchain, the builder-stage option loses its only real objection and becomes worth
re-costing. If the generated tree grows large enough to make diffs unreadable, splitting the CI
check from the commit is the escape hatch — but the acceptance-test argument would still stand.

## Documents updated

- `.gitignore` — the generated-protobuf block replaced by a pointer here
- `.dockerignore` — `!services/catena/gen` added to the allow-list, with the reason
- `services/catena/Dockerfile` — copies `gen/` before `uv sync`, so the wheel carries it
- `services/catena/pyproject.toml` — `packages = ["src/catena", "gen/berean"]`, with the reason
- `Makefile` — `guard-proto-fresh` added, and `make check` runs it in place of `proto-lint`
  (which `make proto` already runs as a prerequisite)
- `docs/adr/0013-go-cli-in-phase-1.md` — the commit-or-generate deferral marked resolved here
- `specs/001-phase-1-pca-baseline/PLAN.md` — Task 2's "generated code gitignored" checkbox
  annotated, Task 7's stubs checkbox recorded as done
- `services/catena/tests/test_proto_contract.py` — the clean-clone skip is gone; absent stubs are
  now a defect rather than an expected state
