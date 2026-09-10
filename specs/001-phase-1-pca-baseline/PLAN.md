# Phase 1 — PCA Baseline: Execution Plan

**Volatile.** This file is a delta, not a blueprint. It can be discarded once the phase is done.
The specifications are the durable artefacts.

Each task should be implementable and testable within a single agent session. Check boxes as
acceptance criteria are met. **When implementation reveals something the spec did not anticipate,
update the spec in the same change.**

---

## Task 0: Resolve the Go-in-Phase-1 question

**Depends on:** —

Decide whether Phase 1 includes the Go CLI or is Python-only. See the open decision at the top of
TECHNICAL-SPEC.md. Every task below assumes the Go CLI.

**Resolved: Phase 1 includes the Go CLI** (ADR-0013).

- [x] Decision recorded as an ADR — ADR-0013
- [x] TECHNICAL-SPEC.md open-decision section replaced with the outcome
- [x] Not Python-only, so tasks 6, 7, 8 and 10 stand as written

---

## Task 1: Repository skeleton and `docker compose up`

**Depends on:** Task 0

Compose stack with Postgres + pgvector, Langfuse, and empty service containers. Nothing does
anything yet; the acceptance test passes.

**Status:** landed and verified on a live Docker daemon, clean-slate, including `make provision`
run for real.

- [x] `docker compose up` succeeds with no external accounts — verified from destroyed volumes:
      Postgres re-ran both init scripts, Langfuse re-applied its ClickHouse migrations, and every
      container reached `healthy` in 23 s with no human touching a signup form
- [x] `make provision` pulls images, the **pinned** Qwen3-8B tag and BGE-M3 into `/models/`, and
      invokes corpus acquisition into `/data/` — neither ships in the repo. Task 1 asserts the target
      exists and is documented; Task 11 is where it is run clean-clone end to end, which is why this
      does not make Task 1 wait on Task 4.
      Run for real: 5m40s cold, **3.1s warm** — idempotent. The generation pin is confirmed twice,
      once against the upstream manifest before pulling and once in ollama's own inventory after,
      which names the model by that same digest. The corpus half fails at the Task 4 stub with
      exit 69, which is the designed outcome and not a defect
- [x] After provisioning, the stack comes up with egress blocked — `make dev-offline`, network
      `internal=true`, every container healthy. Proven both ways: HTTPS out and external DNS both
      fail from inside, while service discovery and inter-container traffic work. *Serves* awaits a
      generator and a CLI (Tasks 7 and 10); Task 11 is where the full claim is exercised
- [x] Postgres reachable with pgvector extension available — `vector` 0.8.6, in an `extensions`
      schema that every role's `search_path` ends in. Available to the superuser is not the same
      claim: the extension first landed in `public`, which no service role's path named, so the
      type would have resolved for the DDL and not for the query (fixed in Task 2 review)
- [x] Langfuse reachable, with its organisation, project and API keys provisioned **headlessly from
      environment** — verified by authenticating to `/api/public/projects` with the provisioned
      keys, which returns the `berean` org and `berean-phase-1` project, and by the user row in
      Postgres. No signup form was ever presented.
      Langfuse is a five-container stack — web, worker, ClickHouse, Redis, and the MinIO
      SHARED §1 already requires — and a first boot that asks a human to sign up fails the
      no-external-accounts test as surely as a hosted service would (ADR-0009 status note)
- [x] README states the RAM and disk floor and the expected provisioning duration. The
      clone-to-first-answer path is the acceptance test, and an acceptance test that silently needs a
      well-specified machine is not one
- [x] The `local-only` serving opt-in is documented as an environment setting, default off —
      `BEREAN_SERVE_LOCAL_ONLY`, default `false` (ADR-0017)
- [x] Two DB roles created, with schema-level grants and `ALTER DEFAULT PRIVILEGES` per
      INTEGRATION-SPEC — no tables exist yet, so table grants are re-asserted by the DDL task.
      Proven behaviourally on probe tables rather than by reading the ACLs: `catena` writes
      `corpus` and is refused `trace` **at the schema level**, `gateway` writes `trace` and is
      refused INSERT on `corpus`
- [x] Makefile defines every target the documentation names — `provision` and `dev` here,
      `corpus-verify` from Task 4 — and README documents `make provision` and `make dev`
- [x] Check that fails when a `make <target>` named in any Markdown file has no Makefile rule.
      `make guard-make-targets`; only invocations inside code markup count, because prose says
      "make sure". The README's clone-to-first-answer path is the project's acceptance
      test, so a target that is renamed or never written breaks it silently and only for
      new contributors
- [x] Guard that fails on any staged file containing corpus text — a bright line that nothing
      checks will erode (ADR-0014). `make guard-corpus`, and `.githooks/pre-commit` via `make hooks`

**Decisions Task 1 made that the spec did not anticipate**, recorded in TECHNICAL-SPEC and
INTEGRATION-SPEC in the same change:

- **Three database roles and two schemas.** `berean_owner` owns `corpus` and `trace` and runs
  migrations; neither service authenticates as it. Two roles with disjoint write scope cannot also
  own their own tables, because an owner re-grants itself anything.
- **BGE-M3 runs in-process from `/models/`, not served by Ollama.** Ollama's `bge-m3` is dense-only,
  and the learned sparse vectors are the one advantage ADR-0006 cites for this model.
- **The generation pin is `qwen3:8b-q4_K_M`**, recorded in `tools/provision/models.lock.yaml` with
  the sha256 of its upstream registry manifest. Ollama has no pull-by-digest, so the tag is what is
  pulled and the manifest hash is what proves the tag still points where it pointed (ADR-0018).
- **Every container image is pinned to an exact version**, and `services/catena/uv.lock` is
  committed so the image resolves nothing at build time.
- **`catena acquire` grew `--all` and `--verify-only`**, so `make provision` and `make corpus-verify`
  are expressible without two entry points.
- **Egress-blocked mode is `compose.offline.yaml`**, which marks the default network `internal`.
  Published ports do not survive that, so the CLI runs inside the stack —
  `docker compose … run --rm gateway`. Task 11 runs acceptance this way.
- **`catena` and `gateway` sit behind a compose `services` profile** and are excluded from the
  default `up`. Neither does anything yet, and a container that exits with "not implemented" on
  every start makes a green acceptance test look red. `make build` still builds both, so they
  cannot rot. Task 7 drops catena's profile; gateway keeps its own, being a CLI rather than a
  server.
- **The corpus guard is structural, and its limit is worth stating.** It denies by path and shape
  and never judges what a file means, which is what ADR-0014 asks for. It therefore does **not**
  catch a passage pasted into a `.go` or `.py` test fixture — that case rests on the invented-text
  rule both service AGENTS.md files carry, on the fixture size ceiling, and on review. Task 8's
  "invented text only" checkbox is not made redundant by this guard.

**Four defects the first live run found**, each fixed and re-verified:

- **`langfuse:3` was a floating tag** and had moved to a build whose ClickHouse migration needs a
  text-index syntax 24.8 rejects (`Only literals can be skip index arguments`). Every image is now
  pinned exactly, and Langfuse 4.27.0 is paired with ClickHouse 25.12 — the pairing upstream
  actually tests. The lesson is ADR-0018's, arriving from the direction nobody was watching: the
  argument for pinning the generator applies to every image in the stack.
- **`ollama/ollama:0.6.5` predates Qwen3 support entirely**, so `make provision` could never have
  worked against ADR-0018's default. Now 0.33.2.
- **Switching between `make dev` and `make dev-offline` left a stale network.** Compose reconnects
  containers to an existing network rather than rebuilding it, and a network whose `internal` flag
  changed since creation comes back with an embedded resolver that SERVFAILs every name — including
  a container resolving itself. Healthchecks hid it, because they use localhost. Both targets now
  tear down first.
- **Langfuse 4's Next server binds the container's own IP, not `0.0.0.0`**, so a `localhost`
  healthcheck inside the container is refused while the app is perfectly healthy. The probe uses
  `$(hostname)`. Also `LANGFUSE_INIT_USER_EMAIL` must carry a TLD — `dev@localhost` fails validation
  and takes the whole web container down with it.

**Three more defects, found by running `make provision` rather than reading it:**

- **The embedding fetch silently downloaded no weights.** `allow_patterns` filtered for
  `*.safetensors`, which `BAAI/bge-m3` does not publish — it ships `pytorch_model.bin`. The script
  pulled 42 MB of tokeniser files and printed "Model provisioning complete". It also excluded
  `colbert_linear.pt` and `sparse_linear.pt`, the ColBERT and learned-sparse heads that are the
  entire justification for running this model in-process rather than behind Ollama — so the fetch
  would have quietly foreclosed the Phase 3 path the decision exists to keep open. Every fetch now
  asserts a post-condition: required files present, and total size within 10% of the pin. A
  provisioning step that reports success while acquiring nothing is the worst failure this project
  can have, because it surfaces two tasks later as something else.
- **The lockfile reader was section-blind.** `approx_bytes`, `runtime`, `license` and `adr` each
  appear under both `generation:` and `embedding:`, and a reader taking the first match returns the
  wrong model's value — it compared bge-m3's 2.3 GB against Qwen3's 5.2 GB floor and failed a
  download that had succeeded. The reader is section-aware now.
- **Docker Desktop's VM memory, not host RAM, is what bounds the stack.** The README's 16 GB floor
  is host RAM and is necessary but not sufficient: the VM commonly defaults to ~8 GiB, the stack
  idles at ~2.5 GiB, and Qwen3-8B needs ~6 GiB on top. The model is OOM-killed with
  `llama-server process has terminated: signal: killed`, which names neither memory nor Docker and
  reads as a bad pin. README now states a 12 GiB Docker allocation and the symptom.

Confirmed working once memory was freed: **JSON-schema-constrained decoding**, which ADR-0018
requires in place of asking the model for JSON. The response parsed and carried exactly the schema's
keys. It also emitted `westminister_confession` — misspelled and not edition-specific — which is a
live instance of the fabrication class check 1 catches, arriving unprompted on the first generation
anyone ran.

---

## Task 2: Proto contract and codegen

**Depends on:** Task 1

`proto/berean/v1/` per INTEGRATION-SPEC, with buf generating both Go and Python.

**Status:** landed. `make proto` generates both sides, `make check` runs the contract lint and both
normalisation suites, and the Go suite runs in a pinned container so no local Go toolchain is
needed.

- [x] `Answer` RPC, `FilterSpec`, `AnswerObject`, `Citation`, `Description`, `Contested`,
      `VerificationResult`, `RetrievalTrace` defined — across six files, split so `common.proto`
      owns the two types (`Tier`, `CitationRef`) that belong to neither side
- [x] Deferred fields present: `conversation_context`, `tier_weights`, `rewritten_query`
- [x] Request carries `previous_failures` (`[VerificationResult]`) and `attempt`. ADR-0010 decided
      the retry carries failure reasons back and no field carried them — without this, Task 8's
      recovery path is inexpressible. Free now, a break after Task 7
- [x] `AnswerObject.no_answer_reason` present; `confidence` documented as wholly Go-derived
- [x] `RetrievalTrace` carries `generation_model` and `top_k`
- [x] **Shared normalisation fixture committed here and asserted by both the Python and Go suites.**
      It cannot wait for Task 5 and Task 8: fingerprints are hashes of post-normalisation text, so an
      ambiguity found when Go first implements the contract invalidates every fingerprint file and
      forces a re-bless of every corpus — including Task 4's by-hand edition verification. Vectors
      cover each `White_Space` code point, each format character stripped in step 0, an NFC-unstable
      sequence, curly and straight apostrophes, and an em dash. Invented text only (ADR-0014).
      `testdata/normalisation/vectors.json`, 58 vectors, read by
      `services/catena/tests/test_normalisation.py` and
      `services/gateway/internal/normalise`
- [x] Both implementations written against the fixture: `catena.normalise` and
      `services/gateway/internal/normalise`. Task 2 rather than Tasks 5 and 8 because a fixture
      nothing implements asserts nothing, and the whole point of the sequencing is that Go has run
      the contract before a corpus is blessed
- [x] `buf generate` produces Go and Python stubs
- [x] Generated code gitignored and regenerated locally; the commit-or-generate decision is
      **deferred to Phase 2** (ADR-0013) — it is CI policy, not contract design.
      **Resolved early, in Task 7 (ADR-0022): the stubs are committed.** The deferral rested on
      this being CI policy, and it stopped being: Task 7 drops catena's compose profile, so
      `docker compose up` on a clean clone now builds an image that must import the contract, and
      `buf.gen.yaml` uses remote plugins. `make check` runs `guard-proto-fresh` so a committed
      artefact cannot drift from what produced it
- [x] `buf breaking` in CI **deferred to Phase 2**; the proto is pre-consumer in Phase 1. The
      configuration is written in `buf.yaml` so enabling it is a CI change.
      `services/catena/tests/test_proto_contract.py` stands in until then: with no break check,
      nothing else would notice a field being dropped
- [x] CI exists as of `.github/workflows/check.yml`: `make proto` then `make check`, on every pull
      request and every push to `main`. It does not turn on `buf breaking` — that stays deferred,
      and is now the one-line change `buf.yaml` was written for. It *does* run `make proto` before
      the suites, because the stubs are gitignored and
      `services/catena/tests/test_proto_contract.py` skips itself without them: the suite standing
      in for the break check is the one suite that must not silently skip on a clean runner

Three things the task did not anticipate, each resolved and propagated to INTEGRATION-SPEC:

- **`tier_weights` cannot be a map keyed by tier.** proto3 map keys cannot be enums, so it is a
  repeated `{tier, weight}` pair. A string-keyed map would have reopened the closed tier set for a
  field nothing reads yet.
- **`conversation_context` needed a type, and the spec gave none.** A `repeated ConversationTurn`
  with `ConversationTurn` empty. A bare `string` would have had to be replaced in Phase 4 rather
  than extended, which is exactly what the field exists to avoid.
- **The fixture carries the two character sets, not only the vectors.** Vectors alone do not catch
  an implementation that reaches for `\s` or `unicode.IsSpace`: the two disagree only on
  U+001C–U+001F, which is the drift the enumerated set was written to prevent. Each suite now
  asserts its own table against the fixture's.

Two stack changes it forced, both small and both recorded where they live:

- **gRPC was pinned at v1.80.0**, the newest release that still built under the then-pinned Go 1.24
  image. Raising it meant raising the toolchain, which is a stack change and belongs in its own
  commit rather than riding along with the contract. Two advisories against gRPC ≤ 1.83.0 forced
  it: the image is now `golang:1.25-alpine` and gRPC v1.83.1, raised in that order.
- **The gateway image now copies `go.sum`.** Without it the build re-resolves the dependency graph
  and writes its own, so the image's dependency set would be whatever the registry served that day.

Six things review found once the contract had landed, every one of them in the surrounding
infrastructure rather than in the contract:

- **pgvector was unreachable from both service roles.** The extension was created into `public`,
  and neither role's `search_path` named `public`. It now lives in an `extensions` schema that
  every role's path ends in (INTEGRATION-SPEC, "Database roles"). Reproduced against a live
  container both ways: the old path raises `type "vector" does not exist` on the first distance
  query, which would have been Task 5, one task after the init script that caused it.
- **`corpora/` was mounted read-only**, so `catena acquire --bless` could not write the manifest
  and fingerprints that are the whole output of blessing. Task 4's first acquisition of a corpus
  would have failed with EROFS.
- **`make dirs` did not create `corpora/`**, the third bind-mount source. Git tracks no empty
  directory and nothing is blessed yet, so on a clean clone Docker would have created it as root
  on Linux — precisely the failure the target exists to prevent, and invisible on macOS.
- **The catena container ran as uid 1001** while `./data` and `./corpora` are owned by whoever ran
  `make dirs`. It now runs as the invoking user, which is what the buf container already did.
  `make config` renders the `services` profile as part of that, having until now validated neither
  service container.
- **The drift check hardcoded the repository** that `generation.registry` also records. Moving the
  pin would have left it hashing the old repository and printing ✓ for a tag it never fetched — a
  silent pass in the one script whose purpose is that drift is loud.
- **The introspection guard scanned three of the six generated modules.** It enumerates the package
  now, so a `rationale` added to `VerificationResult` or `FilterSpec` fails it; and `Argument`'s
  field set is pinned, `warrant` being the field ADR-0003 draws its line around.

---

## Task 3: Corpus and trace schema, and migrations

**Depends on:** Task 1

All DDL lands here. Task 8 writes `VerificationResult` rows and Task 9 writes traces, so both need
their tables before either starts — splitting the DDL across Tasks 3 and 9 makes the two circular.

- [x] `works`, `chunks`, `chunk_embeddings` tables — plus the `chunk_metadata` view that exposes
      the chunk metadata contract over the three
- [x] `responses`, `traces`, `verification_results` tables — plus `candidates`, below
- [x] Every required metadata field NOT NULL where the spec requires it (`author` nullable).
      Asserted field by field from the catalogue, and asserted nullable for `author` rather than
      merely not asserted: a column that quietly became NOT NULL rejects every corporate document
      in the Phase 1 corpus. The view assertion derives its expected column list from the same
      arrays, so no count is stated anywhere and adding a field edits one list
- [x] `license` and `text_form` are database-level enums, not free-text columns. An unrecognised
      value fails at insert, which is what makes check 4 a check with a closed domain (ADR-0017).
      Both label sets are asserted against the specs' spelling, because a drifted label fails at
      ingestion one task later and reads as an ingestion bug
- [x] `source_language` present alongside `language` — the *Institutes* is English text of a Latin
      work, and one column cannot carry both (ADR-0008's backfill argument applies to the split)
- [x] pgvector index on embeddings — HNSW with `vector_cosine_ops`. Not IVFFlat: its lists are
      trained from the rows present when the index is built, and a migration builds it against an
      empty table
- [x] Migration is reversible. `make test-schema` runs the suite, then a full `down` and `up`
      against an empty database and re-runs the structural half — a `down` nobody has run is not a
      rollback strategy
- [x] Insert without `license` or `attribution` fails at the database level, not in application
      code. Also with a blank `attribution`, which is a missing attribution that satisfies NOT NULL
- [x] Table grants applied for both roles, disjoint per INTEGRATION-SPEC. Asserted twice: from the
      catalogue, so the negative half is an assertion rather than an absence of evidence, and from
      each role's own connection, where `catena` is refused `trace` at the schema level and
      `gateway` is refused INSERT on `corpus`

**Decisions Task 3 made that the spec did not anticipate**, recorded in INTEGRATION-SPEC,
TECHNICAL-SPEC and SHARED in the same change:

- **The metadata fields are stored where they are true**, not repeated per chunk: most on `works`,
  the embedding pair on `chunk_embeddings`, and only `locator` on `chunks`. The contract said
  "every chunk in `chunks`", which would have repeated the edition, licence and attribution on each
  of the ~31,100 WEB verses and given a licence correction 31,100 rows to reach. The read surface is
  restored by the `corpus.chunk_metadata` view, which exposes exactly the contract's fields and
  joins `chunk_embeddings` inner — an unembedded chunk does not yet carry the whole contract and is
  a half-finished ingestion, not a row to paper over with two nulls.
- **`tradition` is dropped from the contract.** Which traditions hold a corpus is the profile's N:M
  relation and is the thing anybody means; origination is a weaker claim and is unstatable for the
  WEB, which is ~90% of the index, and for the ecumenical creeds. Nothing read the field — not the
  proto, not retrieval, not any of the four checks — and the use it would first be reached for,
  generalising SHARED §7's cross-contamination assertion, is unsound for exactly those cases.
- **No document states the field count.** A number in prose is a second place to update and goes
  stale silently, so the specs, the skill and the suite all name the fields and none of them count
  them.
- **golang-migrate in a pinned container** (`migrate/migrate:v4.19.0`), `up`/`down` SQL pairs in
  `db/migrations/`, run as `berean_owner` by a compose one-shot in the default `up`. Pinned for the
  same reason `buf` and the Go toolchain are, and containerised so the schema adds no host
  prerequisite to the README's list.
- **A fourth schema, `migration`**, holding the tool's version table and granted to neither
  service. The table is created before the first migration runs, so it cannot be created by one:
  in `corpus` the default privileges would hand `catena` INSERT and DELETE on the record of which
  migrations have been applied, and in `public` `berean_owner` has no CREATE. It is added to the
  init script, so an existing volume needs `make reset`.
- **`docker compose up -d --wait` counts an exited container as a failure** unless a *started*
  service depends on its completion — which is how `minio-init` passes and why the migrator does
  not, its two dependants being behind the `services` profile. `make dev` scales it out of the
  waited-on `up` and runs it on its own, where its exit code is the thing being checked. A bare
  `docker compose up` still applies migrations, because that path uses no `--wait`.
- **`vector(1024)`, and the honest consequence.** pgvector cannot index a vector of unconstrained
  width, so the HNSW index forces a declared dimension. A model of the same width stays the
  re-index job SHARED §10 requires; a model of a different width is a migration as well, and no
  schema over this extension avoids that. SHARED §10 now says so. One index across all models, so
  retrieval MUST filter on `embedding_model`.
- **`trace.candidates` is a table, not a JSON array on `traces`.** It is what Phase 2 computes
  recall@k from, and TECHNICAL-SPEC asks for a trace schema designed with that consumer in mind. It
  carries a `rank` column with no counterpart in the proto: a repeated field carries its order
  positionally, a table has no order without a column, and the order is the whole of what @k means.
- **`request_id` is a uuid**, though the proto carries it as a string, because proto3 has no uuid
  type and the column everything else in `trace` keys on is worth constraining where it can be.
- **`chunks.normalisation_version`**, which the metadata contract does not name. The per-chunk hash
  is over post-normalisation text, so a corpus ingested under one contract version and queried by a
  gateway running another produces quote-match failures on visually identical text. That is the
  symptom the contract exists to prevent; the column makes it a lookup rather than an investigation.
- **The proto's prose invariants are constraints.** `attempts` is 1 or 2 and a third is the seam
  moving; a `verified` turn took one attempt and a `regenerated` turn took two, so the degradation
  rate ADR-0010 needs kept clean cannot be recorded incoherently; `failure_detail` is empty exactly
  when all four checks passed; a candidate carries an `exclusion_reason` exactly when excluded.
  `degraded` is left free on attempt count — whether an unretryable failure degrades at one attempt
  or two is Task 8's to decide, and a constraint here would pre-empt it.
- **No foreign key from `trace` into `corpus`.** On `verification_results` this is load-bearing: a
  citation to a corpus that does not exist is precisely what check 1 records, and a foreign key
  would make the fabrication unrecordable. On `candidates` the reason is weaker — an audit record a
  corpus lifecycle event can cascade away is not an audit record.
- **The whole turn is written in one transaction after it completes**, because `overall_result` and
  `confidence` are known only at the end. A crash mid-turn therefore persists nothing, which is the
  right trade: a partial trace enters the Phase 2 dataset as a turn that retrieved nothing.
- **`make test-schema` is not part of `make check`.** `check` runs with nothing started, and every
  assertion here is about a live database — a grant is only demonstrated by a statement that is
  actually refused.

---

## Task 4: Corpus acquisition pipeline and provenance

**Depends on:** —

Build the acquisition pipeline, then use it to acquire the 1788 American revision of WCF/WLC/WSC,
the current BCO, the 1646 recension (the profile's only `contrary` corpus; see below on why no
faithful 1646 text could be found and what was taken instead) (needed for the edition check, and the profile's only `contrary`
corpus), the WEB text, the 28th General Assembly (2000) creation study committee report
(`pca-ga28-2000-creation-study`) — the document that establishes the contested status of
`creation-days`, without which the corpus says only "in the space of six days" (WCF 4.1) and UC-4
cannot be answered from any ingested text — and Calvin's *Institutes*
(`calvin-institutes-1559-beveridge`), 1559 edition in the Beveridge 1845 translation, which is what
makes UC-6 runnable at all.

Seven corpora. The *Institutes* is the largest by far and the only translated work, so it is the one
that exercises `source_language` and the book/chapter/section locator.

**No corpus text enters the repository** (ADR-0014). The repo carries manifests, fingerprints, and
scripts; text lands in gitignored `/data/`.

**Status: all eight corpora acquire cleanly and all eight are blessed under the current
schema.** Design, and the decisions implementation and review revised, are in
[ACQUISITION-DESIGN.md](ACQUISITION-DESIGN.md).

`wcf-1788-american` (WCF 23.3), `wlc-1788-american` (WLC Q&A 109), `wsc-1788-american`
(WSC Q&A 6), `calvin-institutes-1559-beveridge` (Inst. 4.17.10.p1), `wcf-1646-epcew-modernised`
(WCF 23.3), `pca-ga28-2000-creation-study` (GA28 Rec.2), `web-2020` (Deut 6:4) and
`pca-bco-2026` (BCO 21-4). The confession was blessed once before ADR-0021 changed the manifest
schema — `edition_check` now records the hash of the text the verifier read rather than the text
— and was re-blessed under the new schema; the rest were blessed under it from the start.

The BCO was blessed twice, and the first one was discarded rather than kept. It had captured
what a stale parser produced — 429 paragraphs with the verso running head in 49 of them, `BCO
46-8` carrying the Directory's divider page, `BCO 36-8` absent altogether — and 89 of its 430
fingerprints differ under the corrected parser, the diagnostic `BCO 21-4` among them. So the
reading that admitted the edition had been a reading of furniture-bearing text, and it was done
again. **A bless is only as good as the parser that ran under it**, which is worth stating
because nothing in the pipeline can notice it: verify compares an acquisition against the
manifest, and both sides of that comparison come from the same parser.

Pipeline:

- [x] `catena acquire --corpus <id>` runs fetch → extract → segment → normalise → verify → stage
- [x] Each stage independently re-runnable and idempotent; fetch caches on `upstream_sha256` —
      content-addressed at `/data/acquire/<id>/fetch/<sha256>`, since a cache key cannot be the hash
      of something not yet fetched. Only fetch caches: the pure stages recompute, so an adapter fix
      cannot land while verification still runs against the output of the code it replaced
- [x] Structural chunking lives in the segment stage — WCF per numbered section, WLC/WSC per Q&A
      pair never split, BCO per numbered paragraph, WEB per verse, the *Institutes* per paragraph
      (`Inst. 4.17.10.p1`), the 2000 report per numbered section with its recommendations
      segmented separately from the expository body. **All eight corpora are done.** The BCO is
      `BCO <chapter>-<paragraph>`, 430 paragraphs across chapters 1–63; chapter 44 is `(Vacated)`
      and has none, so chapter numbering is deliberately not asserted contiguous
      WCF — 33 chapters, 171 sections, `WCF <chapter>.<section>`. Its lists of canonical books are
      three-column tables read *down* each column; row-major reading garbles them and nothing
      downstream would notice. WLC — 196 Q&As, `WLC Q&A <n>`; WSC — 107, `WSC Q&A <n>`. Chunk text
      carries neither the `Q. n.` nor the `A.` marker, because check 2 substring-matches against it
      and a marker on the boundary fails any quote spanning it. The catechisms' answers are
      multi-line (WLC 99's eight rules, WLC 151's four aggravations) and WLC 196's paragraph is
      never closed in the source, so the last chunk depends on flushing at the container's close
- [x] The 2000 report's recommendations are independently addressable, so a profile's
      `ruling_source` resolves to the ruling and never to the expository body. The body argues
      four views the denomination did not adopt; tier is per corpus, not per chunk, so nothing
      else separates advocacy from ruling. Done: `GA28 Rec.1`–`Rec.3`, a form deliberately unlike
      the body's `GA28 IV.B.2.4`. **`Rec.2` is the ruling** — the Assembly affirming that a
      diversity of views on the creation days is acceptable — and it is the edition diagnostic,
      because only the adopted report records that its recommendations carried
- [x] **Chunked per paragraph, not per numbered section, and the spec is corrected rather than
      quietly departed from.** Section IV.A is 40,659 characters with no subsections — past
      BGE-M3's 8,192-token limit, so it could not be embedded at all. 513 chunks, median 376
      characters, none over 2,016. The section path lives in the locator instead, which is what
      keeps a citation's place in the argument visible
- [x] `--bless` writes a new manifest after human edition verification; the default mode verifies
      against the committed manifest and fails loudly, never silently, on any mismatch. Bless aborts
      on a non-TTY, blocks on a typed verifier name, demands a distinct confirmation when
      re-blessing, and writes both files temp-then-rename
- [x] `--from-file` accepts a local copy, so a dead or moved upstream does not block a deployer
- [x] `make corpus-verify` re-acquires every corpus and diffs against committed fingerprints —
      this is how upstream drift gets noticed. `--verify-only` always re-fetches and stages nothing;
      the three classes (missing, unexpected, mismatched) report together, as counts plus a bounded
      sample of locators and never text

Provenance and licensing:

- [x] **Resolved (ADR-0017):** BCO and `pca-ga28-2000-creation-study` are ingested as `local-only`.
      Ingestion and serving are separate acts — the repository distributes nothing (ADR-0014), and
      check 4 refuses to serve `local-only` chunks unless the deployer has opted in, defaulting to
      deny. This no longer blocks acquisition. It does mean the manifest must record the terms
      **verbatim as found**, with the URL, in `license_terms`: a licence is evidence, not a label
- [x] Manifest per corpus: source URL, archive fallback URL, retrieval date, licence enum,
      `license_terms` verbatim, attribution, the edition diagnostic's locator and the hash of the
      text its verifier read — never the text (ADR-0021) — normalisation contract version (`1`),
      chunk count. All eight parse through the schema reader with no field missing, and unknown
      keys are rejected rather than ignored — a misspelled field that loads clean is a provenance
      record with a hole in it
- [x] Fingerprints file: one `<locator>  <sha256-of-normalised-text>` per line, sorted —
      bytewise on the UTF-8 encoding of the locator, since "sorted by locator" is
      underspecified and a numeric-aware sort needs a locator grammar the format does not have
- [x] **Verified as the 1788 American revision** — WCF ch. 23 checked by hand against the 1646
      text, read in full at bless and recorded as its hash rather than as a checkbox or as committed
      text (ADR-0021). Blessed once, superseded by the schema change, and re-blessed under the
      current one on 2026-09-04; the confession needs nothing further. The diagnostic can be read
      at any time with `--show-diagnostic`, blessed or not. Chapter 31 having
      four sections rather than the 1646 original's five is a second, structural confirmation the
      adapter gets for free. **WLC 109 is the catechism's share of the same revision** — the 1646
      text lists "tolerating a false religion" among the sins forbidden in the second commandment
      and the American revision deletes it, so the diagnostic is confirmed by an absence.
      **WSC has no such divergence**: the 1788 Synod left the Shorter Catechism unaltered, so its
      diagnostic guards the register instead — WSC 6 names the Holy Ghost, which is the first thing
      a modernised printing rewrites. Recorded in the adapter rather than left for a reader to
      infer from an ID whose date the document does not share
- [x] Licence and attribution confirmed per source and recorded, never assumed. `public-domain` for
      WCF/WLC/WSC, WEB and the Beveridge *Institutes*; `local-only` for the two PCA-published corpora,
      and `public-domain` for the EPCEW 1646. `license_terms` carries what was actually on the page,
      verbatim, 697 to 1,081 characters per corpus — including a site-wide copyright footer beside an
      eighteenth-century text, recorded because a licence is evidence and not a label
- [x] The *Institutes* is taken in the Beveridge 1845 translation, not Battles (1960), which is in
      copyright. Acquired from CCEL as plain text: 4 books, 80 chapters, 1,277 sections plus the
      seven of Calvin's prefatory address, chunked per paragraph to 2,260 chunks (see below). Three
      source hazards are handled and tested — every chapter opens with a numbered synopsis of
      itself that must be discarded (six
      carry none, so its presence cannot be assumed), Book IV chapter 18's number is missing from
      the source and is recovered positionally, and 1,283 footnote anchors are stripped. Murray's
      20th-century introduction is excluded as apparatus still in copyright. Note the practical consequence for Task 11: Battles is the translation a model is
      most likely to have memorised, so UC-6 may fail check 2 on passages the model genuinely knows.
      That is a finding about the generator, not a defect in the verifier
- [x] The *Institutes* is chunked per paragraph rather than per numbered section. Four sections
      exceeded BGE-M3's 8,192-token window, the longest at 16,714 tokens, and the source's own
      blank-line paragraph breaks were being discarded by the segmenter. 2,260 chunks. This
      unblocks Task 5, which refuses a corpus carrying a chunk the embedder cannot read whole
- [ ] Bare text only, never a modern edition's apparatus — footnotes, cross-references, modernised
      spelling, and proof-text selections can carry fresh copyright over public-domain text. Apparatus
      is stripped everywhere: the confession's proof-texts, 1,283 footnote anchors and every chapter
      synopsis in the *Institutes*, Murray's introduction, the BCO's amendment bullets and appendices.
      **This stays open on the spelling clause**, and deliberately: no faithful 1646 text could be
      found, so the `contrary` corpus is the EPCEW's modernised rendering. The departure is recorded
      in the corpus ID — `wcf-1646-epcew-modernised` — and ticking this line would hide the one thing
      it exists to keep visible. It closes if a faithful 1646 text is ever found, and not before

Getting the edition wrong here silently poisons everything downstream. Verify by hand.

---

## Task 5: Ingestion — enrich, embed, load

**Depends on:** Tasks 3, 4

Chunking and normalisation happen in acquisition, so ingestion never parses an upstream format and
never touches the network. It reads staged records, enriches, embeds, and loads.

- [x] Reads staged records from gitignored `data/acquire/<corpus-id>/stage/`; no network in this
      path. **Corrected from `/data/staged/<corpus-id>/`**, which was never built — the seam
      acquisition actually writes is `stage/` under the per-corpus acquisition tree
- [x] Records re-verified against committed fingerprints before insert — ingestion refuses text
      that does not match what was blessed. Every run rather than only on insert: it costs under a
      second across all 8.2 MB, and a conditional check is one whose skipped path is untested. The
      hash each record carries is recomputed rather than trusted
- [x] WEB ingested as `web-2020`, the corpus ID the PCA profile names. **Renamed from `web-2000`,
      which named an edition nobody published.** eBible.org's FAQ says the translation "started out
      as just one Bible translation that was continuously revised until 2020" and that "The World
      English Bible was completed in 2020"; the archive's own about file ends "2020 stable text
      edition". The Protestant edition (`engwebp`) is taken rather than the Classic (`eng-web`):
      66 books, the canon WCF 1.2 enumerates, and "LORD" rather than "Yahweh"
- [x] `calvin-institutes-1559-beveridge` ingested, so UC-6 has a source that carries no binding
      authority. **2,260 paragraph chunks** since the re-chunk, not the ~1,700 sections this line
      was written against, and the largest embedding job after WEB. The `advisory` stance is not
      set here: authority tier is a profile's N:M relation (Task 6), and `corpus.works` carries no
      originating-tradition column, deliberately
- [x] `wcf-1646-epcew-modernised` ingested, so the profile's `contrary` entry resolves and UC-3 has a
      counterpart to contrast against
- [x] Every metadata field populated on every chunk, including `source_language` (`la` for
      the *Institutes*, equal to `language` elsewhere) and `text_form` (`majority` for WEB, whose NT
      follows the Majority Text; `not-applicable` for every non-Scripture corpus). Asserted against
      the live database: 34,947 `chunk_metadata` rows, none carrying a NULL contract field
- [x] Corpus IDs edition-specific (`wcf-1788-american`)
- [x] The Python suite asserts the shared normalisation fixture committed in Task 2 — it is not
      created here, because Task 4 blesses fingerprints against it
- [x] Ingestion is resumable per corpus. 34,947 chunks embed on a clean clone, dominated by WEB's
      31,098 verses, and an interrupted multi-hour run must continue rather than restart.
      Resumption is a query — the anti-join for chunks carrying no vector under the active model —
      rather than a checkpoint, so there is no progress file to leave stale and no cleanup step
      after a hard kill
- [x] BGE-M3 behind an embedder interface; `embedding_model` and `dim` written per chunk
- [x] Re-running ingestion is idempotent, keyed on the per-chunk hash. The locator says which chunk
      this is and the hash says what it currently says, so a re-blessed corpus is an update rather
      than a skip — and an update drops the embeddings it invalidates in the same transaction
- [x] Refuses any corpus carrying a chunk over BGE-M3's 8,192-token window, measured with the
      model's own tokeniser. All eight corpora pass: the longest is an *Institutes* paragraph at
      2,890 tokens
- [ ] Spot-check: `WCF 7.2` and `WSC Q&A 1` retrieve and read correctly. Both resolve in
      `corpus.chunk_metadata` carrying every field, and their stored `content_hash` matches the
      committed fingerprint (`a7749e84ceb7…`, `7d862e906a47…`) — so what the database holds is what
      was blessed. *Retrieving* them is Task 7, and that is what this item still waits on

All eight corpora are ingested: 34,947 chunks, 34,947 embeddings, no chunk missing a vector, one
`embedding_model` (`bge-m3`) at dim 1024, every vector L2-normalised as the cosine index requires.
`make ingest-all` re-runs to `0 insert, 0 update, 0 delete, 0 embeddings remaining` for every
corpus, which is convergence measured rather than argued.

The command is `catena ingest (--corpus <id> | --all) [--apply]`, and it **writes only under
`--apply`** — inverting `catena acquire`, which writes unless told otherwise. The asymmetry is about
what a wrong run costs: acquisition re-fetches into gitignored `/data` in minutes, while ingestion
updates and deletes rows that cascade to embeddings, and that costs hours no cache can return. The
dry run is also the progress report. See [INGESTION-DESIGN](INGESTION-DESIGN.md).

Three things the implementation did not anticipate:

- **A blessed locator missing from staging refuses**, where the design named only mismatched and
  unexpected ones. Left to the diff it becomes a *delete* of a blessed chunk — the BCO's truncated
  bless executed against the database — so all three classes of the fingerprint diff refuse.
- **`work.json`'s `chunk_count` is checked against `records.jsonl`.** The two are written by the
  same step and disagree only when one is half-written, and a truncated `records.jsonl` read as
  complete is a plan that deletes every chunk past the truncation.
- **`make ingest` keeps the `--apply` inversion** rather than applying: `make ingest CORPUS=<id>`
  prints the plan and `make ingest CORPUS=<id> APPLY=1` executes it. A wrapper that silently applied
  would put the whole safety argument one keystroke from being lost.

---

## Task 6: Profile engine (Go)

**Depends on:** Tasks 2, 5

The dependency on Task 5 is real, not bookkeeping: the loader validates corpus IDs against the
database, and there is nothing to validate against until a corpus is ingested. The task header
previously said Task 2 while the parallelisation table said Tasks 2 and 5; the table was right.

**Status:** landed. `profiles/pca.yaml` loads against the live database through the `gateway`
role — all eight corpora it names are ingested, which is the assertion ADR-0015 rests on — and
`make check` runs the unit suite with nothing started.

- [x] PCA profile YAML per INTEGRATION-SPEC, including `calvin-institutes-1559-beveridge` at
      `advisory` — `profiles/pca.yaml`, one file per tradition, named for what `--profile` selects
- [x] Loader validates: unknown stance is an error; `contrary` or `excluded` without `label` is an error
- [x] `scripture.stance` defaults to `binding` when absent; `contrary`/`excluded` rejected (ADR-0011)
- [x] `scripture.corpus_id` appended to the corpora list carrying that stance as its tier
- [x] `contested` entries validated: `ruling_source.corpus_id` absent from `corpora` is a load error
- [x] Loader takes a `CorpusRegistry` interface (`Exists(corpus_id)`, backed by
      `corpus.chunk_metadata`). A profile naming an un-ingested corpus fails at load, as does a `contested` entry
      whose `ruling_source` is not ingested — which is what delivers ADR-0015's honest "the
      establishing document is not ingested yet" instead of an invented ruling. Checking only the
      profile's own `corpora` list proves internal consistency and nothing more.
      `internal/corpus.Registry` is the backing implementation; a registry that *errors* fails the
      load rather than reading as `absent`, because a database that cannot answer has not said no
- [x] The registry is an interface, so the profile unit tests — including the no-identity-leak
      test — need no database. `make test-gateway-db` is where the live assertions run, and it is
      not part of `make check` for the same reason `test-schema` is not
- [x] Resolves to a `FilterSpec` carrying corpus IDs, tiers, weights — **and nothing else**.
      `tier_weights` resolves **empty**: the profile schema carries no weights and there is no
      reranker to read them, and an invented 1.0 per tier would be indistinguishable from
      configuration in Phase 3
- [x] Unit test asserts no profile name, user identity, or session state appears in the FilterSpec —
      it marshals the whole request and scans for a sentinel profile name that cannot occur in a
      corpus ID, since `pca` occurs inside `pca-bco-2026` and would have made the test vacuous
- [x] Contested loci resolve to a **sibling** request field, never into the FilterSpec — pointers
      only (`locus`, `corpus_id`, `locator`), never resolved prose (ADR-0015)
- [x] Schema handles N profiles though only one is populated — `profiles/<name>.yaml`, and the
      loader knows nothing about which one it is reading

Three things the implementation did not anticipate, all recorded in INTEGRATION-SPEC:

- **The decoder is strict.** `stanc: binding` parses cleanly into an empty stance, and an empty
  stance is one `default:` away from being treated as absent. An unrecognised key fails the load
  instead, because a doctrinal commitment silently replaced by an engine default is the failure this
  document exists to prevent.
- **A corpus named twice is a load error, and Scripture shares that namespace.** Resolution appends
  `scripture.corpus_id` to the same list, so naming it again in `corpora` is the same collision —
  and one corpus at two stances would have shipped both to Python to pick between.
- **The ruling locator is `GA28 Rec.2`, not the spec's illustrative `Recommendations 1`.** Task 4
  made the recommendations independently addressable and established that Rec.2 is the ruling.
  TECHNICAL-SPEC is corrected rather than left to be discovered at the first contested answer.

Three more the review found, each fixed with the test that reproduces it:

- **The registry reads `corpus.chunk_metadata`, not `corpus.chunks`.** Ingestion commits text and
  embeddings in separate phases, so a corpus interrupted between them has chunks, no vectors, and
  retrieves nothing — the view inner-joins the vectors for exactly that reason. Reading `chunks`
  would have loaded such a corpus into the filter spec and turned a refusal at load into a thin
  answer at query time. The test writes the half-ingested fixture through a second connection as the
  `catena` role, because the gateway role cannot write what it is asked to refuse.
- **A locus held open twice is a load error.** The corpora rule had no counterpart on `contested`,
  so two rulings for one locus both crossed the boundary and left Python to pick.
- **`ruling_source` may name `scripture.corpus_id`.** The check read the `corpora` list while
  resolution sends that list *plus* Scripture, so a ruling in Scripture was refused — and the
  document could not be edited to satisfy the refusal, since naming it under `corpora` is the
  duplicate that is already an error.

**Left for Task 10:** `Profile` exposes no accessor for a corpus's `label`. The loader requires one
at `contrary` and `excluded`, and Task 10's "contrary citations render with their label" is the
first thing that needs to read it. Adding it here would have been a method with no caller and a test
asserting only its own existence.

---

## Task 7: Catena service — retrieval and generation (Python)

**Depends on:** Tasks 2, 5

**Status:** landed, with one measured failure that is Task 11's to expect rather than Task 7's to
fix — see the last finding below. `catena serve` runs in the default `docker compose up`, reports
SERVING over the gRPC health protocol once BGE-M3 is loaded, and answers `Answer` end to end
against the live stack on a real PCA filter spec. `make check` runs the unit suite with nothing
started; `make test-catena-db` asserts the SQL against a live database.

- [x] gRPC server implementing `Answer` — `catena.serve.server`, thread pool, standard health
      service, graceful SIGTERM. Readiness is not liveness: the port is open for the tens of
      seconds the encoder takes to load, so compose probes health rather than TCP and the gateway
      waits on `service_healthy`
- [x] Dense-only top-k search filtered to the corpus IDs in the FilterSpec — and
      `hnsw.iterative_scan` set per transaction, because pgvector defaults it `off` and HNSW
      post-filters, so a filtered search silently returns fewer than `top_k`
- [x] **No reranking, no BM25, no query rewriting** — and no LangGraph, which TECHNICAL-SPEC defers
      to Phase 5 with the instruction to hit the wall first. The path is linear and a graph would
      only obscure it
- [x] Resolves a sent locus's `ruling` pointer through ordinary retrieval and grounds
      `state_of_debate` in that passage; populates `contested.locus` only from the loci sent. The
      ruling is fetched by `(corpus_id, locator)` — a pointer resolves to exactly one chunk — and
      **pinned ahead of the context budget**, since `state_of_debate` must quote it
- [x] When it sets `is_contested`, it emits **no** `arguments` (ADR-0019) — stated in the prompt,
      and **not enforced here**. This service does not launder its own output: a bad routing goes
      to Go and fails there, which is the intended direction and the only way the rate stays
      measurable for Phase 2
- [x] Emits `no_answer_reason` (≤ 200 chars) when the corpus is silent, with every content slot
      empty. Verified against the **pinned generator with the derived schema** — a question its
      passages did not address returned `no_answer_reason` alone, in 21 tokens, every other slot
      absent — rather than end to end through the service, which needs a corpus genuinely silent on
      something a user would ask. Task 11's UC-2 is where that lands
- [x] Populates neither `confidence.level` nor `confidence.reason` (ADR-0020). Stronger than a
      convention: the field is **absent from the decoding schema**, so it is unpopulatable, and its
      arrival anyway is a loud failure rather than a quiet `ClearField`
- [x] Consumes `previous_failures` and `attempt` on a regeneration — rendered into the prompt by
      Python from the structured results, so Go still composes no prose
- [x] Routes claims into `arguments` or `descriptions` per the slot rules
- [x] Generation behind an OpenAI-compatible interface, default Ollama running the pinned Qwen3-8B
      tag (ADR-0018). stdlib `urllib`: the wire format is what makes providers interchangeable, not
      a vendor SDK. A test asserts the constant matches `models.lock.yaml`
- [x] Structured output conforming to `AnswerObject`, enforced by JSON-schema-constrained decoding
      — schema **derived from the proto descriptor** rather than hand-written, minus `confidence`
      (ADR-0023)
- [x] `RetrievalTrace` populated including excluded candidates with reasons, plus `generation_model`
      and the `top_k` actually used
- [x] Langfuse instrumentation on every model call, carrying token counts (SHARED §6) — verified
      end to end by querying ClickHouse after a live request: a `catena.answer` span and a
      `generate` generation, correlated by `request_id` and naming the pinned tag. Recorded even
      when the generation itself fails, which is what makes a failure rate measurable.
      Observability never fails a request — an unconfigured or unreachable Langfuse degrades to a
      no-op — but it reports the first failure rather than degrading silently. See the defect below
- [x] Never writes to trace tables — the `catena` role has no grant, and retrieval opens a
      read-only connection per request
- [x] **The catena image carries the generated stubs.** Committed, per ADR-0022, and packaged into
      the wheel so an editable dev install and the image resolve the import identically.
      `.dockerignore` gained its allow-list line

**Six things implementation found that the spec did not anticipate**, each recorded in the specs or
an ADR in the same change:

- **`required` in the decoding schema is a correctness question, not a style one** (ADR-0023). A
  fully strict schema made the model narrate into slots whose correct value is nothing —
  `position: "no_position"` beside empty `arguments` violates the empty-when-descriptive rule and
  costs a regeneration on the cheapest case in the system. A fully permissive one produced a
  citation with no `corpus_id` or `locator`, unresolvable by construction. The rule that got both
  right is mechanical: required in messages reachable only through a repeated field, nothing
  elsewhere. `minItems` is honoured by the decoder and is still not used — forced to produce two
  citations from one passage, the model padded with a fabricated sub-quote.
- **The pinned generator thinks, and its thinking is unconstrained.** `reasoning_effort: "none"` is
  required, not tuning: with thinking on, a schema-constrained probe spent its whole budget inside
  `reasoning` and returned empty content. The field is also model introspection, which SHARED §4
  forbids emitting — so nothing reads it.
- **Ollama's default context is 4096 and it truncates silently.** `OLLAMA_CONTEXT_LENGTH: 8192` on
  the ollama service, mirrored in Catena, which fits candidates to a budget derived from it. This is
  what makes `Candidate.exclusion_reason` mean something in Phase 1 — a live query included 11 of 20
  candidates and recorded the other 9.
- **Passage text must never be wrapped in quotation marks.** A probe that did got the marks back
  inside the quote, which fails exact substring containment while reading exactly like a paraphrase
  failure — manufacturing, for free, the risk ADR-0018 names as the live threat to Phase 1.
- **TECHNICAL-SPEC's "the prompt injects the profile summary" was never implementable.** Python
  receives a FilterSpec and no profile (ADR-0015). Corrected to the filter spec summary.
- **Generation is far slower than the retrieval budget suggests.** ~3.4 tokens/second against a
  full ~5,900-token prompt on the reference machine, so a Phase 1 answer takes two to four minutes
  and the client timeout is 900 s. SHARED §9 sets no generation target, and this is the number
  Task 11 has to plan around: ten acceptance questions is roughly half an hour.

**A defect this task shipped and caught, worth recording because the shape recurs.** The first
`observability.py` was written against the Langfuse **v3** SDK — `Langfuse.start_span`, which v4
removed — and wrapped every call in a blanket `suppress(Exception)` under the rule that
observability must never fail a request. So the service logged `langfuse on` at startup, recorded
nothing, and passed its unit suite, because the suite only ever exercised the no-op path. It was
found by querying ClickHouse for ingested events and getting zero.

Two things came out of it, both kept. **Never failing a request and never mentioning a problem are
different promises, and only the first is worth making**: a failure now prints once per process to
stderr and is suppressed after that. And the unit suite now exercises the *configured* path against
a double shaped like the v4 client, including the exact AttributeError that shipped — a no-op is
the one path that cannot tell you the other one is broken.

Worth noting for Task 9: Langfuse 4.27.0 runs in `events_only` mode, so `/api/public/traces` and
`/api/public/observations` both return nothing regardless of what was ingested. The events land in
ClickHouse's `events_full`, which is where to look.

**A seventh finding, and the one that matters most for Task 11: on a broad question the generator
writes past the token ceiling, and prompting does not stop it.**

The UC-4 question — "How many days did creation take, and is that settled?" — retrieves 21
passages, and the model answers with **one** argument whose `warrant` summarises a dozen sources in
a single string, naming each in prose ("The Westminster Shorter Catechism (WSC Q&A 9) states,
'…'"). It runs past `max_tokens` and the truncation guard refuses it, which is correct: an
incomplete answer object must not be presented as considered silence.

Prompting was the prescribed response (ADR-0018: "a better generator or better prompting — never a
looser check 2") and it was tried twice. Bounding the *number* of claims — "at most three
arguments" — the model complied by emitting one and putting everything in the warrant. Bounding
each *field* — "claim: ONE sentence; warrant: ONE or TWO sentences" — plus an explicit "citations
are structured fields, NEVER PROSE" rule that `services/catena/AGENTS.md` had always required and
the prompt had never carried, changed the output not at all. Both instructions are kept: they are
correct, they cost nothing, and they may bind on other questions. Neither bound on this one.

The behaviour is not a loop. The same contested instructions on a two-passage prompt produce a
compact 194-token answer that routes correctly — and, incidentally, produces exactly the ADR-0019
violation this task predicted, setting `is_contested` **and** emitting an argument, which this
service passed through unlaundered for Go to fail. What runs away is the summarising, and it scales
with how much source material is in front of the model.

Three things this is not, and one thing it is. It is not a defect in the service: the refusal is
the designed path, and Go's regenerate-then-degrade handles it. It is not a reason to raise
`max_tokens`: the window is 8192, the prompt is ~4,100 tokens, and 2,048 completion tokens already
take ten minutes at 3.6 t/s. It is not a reason to add `maxLength` to the schema, which would cut a
warrant mid-word and is the same "optimise before measuring" error the phase ordering forbids.

**It is a Phase 2 measurement arriving early**, and Task 11's expectation table should record UC-4
as degrading rather than verifying until a better generator or a per-corpus retrieval quota is
tried. The trace makes the case directly: 21 passages, most of them long GA28 report prose at
`advisory`.

**One thing deliberately not done.** `catena.ingest.bge` and `catena.ingest.embed` are now imported
by the request path, which makes their package name wrong. Moving them is a rename across the
ingestion suite for no behavioural gain, and `bge.py`'s own docstring already anticipated this
reader ("the predicate the resume query and retrieval both filter on"). Left for whenever a second
embedder makes the move pay for itself.

## Task 8: Verification engine (Go)

**Depends on:** Tasks 3, 6, 7

The phase's reason for existing.

**Status:** landed. The engine, the turn that drives it, and the contract change the engine forced
(ADR-0024). Persistence is Task 9's, and rendering is Task 10's.

- [x] Locator resolution: corpus ID + locator → exactly one chunk. `internal/corpus.Lookup`, over
      `corpus.chunks` rather than the `chunk_metadata` view: the view inner-joins the embeddings,
      which is right for "is this corpus ingested" and wrong here — a chunk whose vector has not
      landed is still real text at a real locator, and refusing it would report a fabricated
      citation where the truth is a half-finished ingestion
- [x] Quote match: exact substring containment after normalisation, with a **40-character floor**.
      The four checks prove a citation is real, never that its quote supports the claim; the floor
      blocks the degenerate case without any semantic judgement (ADR-0020). Counted in characters,
      not bytes, and there is a test that fails on a byte count
- [x] Go asserts the same shared normalisation vectors the Python ingestion suite asserts — landed
      at Task 2, and check 2 routes through that package rather than through `strings.TrimSpace`
- [x] Tier check against the **resolved profile**, not the tier Python claimed. `Citation.tier` is
      read nowhere in the engine, which is the point of it
- [x] Every `Argument` carries a `binding` or `governing` citation; advisory-only fails
- [x] `contrary` or `excluded` appearing in `arguments[]` fails; both permitted in the descriptive
      slots with their labels
- [x] `descriptions[].citations` non-empty; `position` empty when `arguments` is empty
- [x] License check reads the enum: `public-domain`, `cc-by`, `cc-by-sa` pass; `local-only` passes
      only under the deployer opt-in; `refused` never passes (ADR-0017). A licence outside the enum
      fails closed, because the only safe reading of one this build does not know is that it
      permits nothing
- [x] Citation to a corpus not in the sent FilterSpec fails immediately
- [x] `contested.locus` not among the loci sent fails immediately, as an unsent corpus does
- [x] When `is_contested`, the locus's ruling is cited and quoted verbatim in `state_of_debate`
- [x] When `is_contested`, `arguments` is empty. Flagging a locus contested and resolving it in the
      same answer otherwise passes every check, and WCF 4.1 is the most retrievable chunk for the
      UC-4 question while reading as settled (ADR-0019)
- [x] A verified citation resolving to a locus's ruling while `is_contested` is false fails — the
      system's only omission check. It fires on *verified* citations only: a fabricated quote at the
      ruling's locator has already failed check 2, and firing here as well would report one mistake
      as two rules broken
- [x] `no_answer_reason` non-empty only when every content slot is empty, and ≤ 200 characters.
      Every slot empty with no reason FAILS and regenerates — a truncated generation must not render
      as considered silence
- [x] `confidence.level` and `confidence.reason` both derived from the verification result by the
      rule in INTEGRATION-SPEC, overwriting whatever Python sent
- [x] Go never rewrites the answer; contested failures regenerate then degrade like any other
- [x] Empty `citations` on any argument fails the answer
- [x] Regenerate once on failure, sending `previous_failures` and `attempt = 2`; degrade on the
      second failure. Go sends verification results, never composed prose instructions
- [x] Degraded output carries no partial unverified content and no `no_answer_reason`. The string
      "I can't source this adequately" is Task 10's to print: the turn returns `DEGRADED` with an
      empty answer object, and a renderer that has to be told which words to use is a renderer that
      cannot accidentally show the failed attempt
- [x] `VerificationResult` **produced** per citation per attempt, alongside `AnswerFailure` for the
      answer-level rules. Task 9 writes both — `trace.verification_results` has a foreign key into
      `trace.traces`, so nothing can be persisted before the trace row is, and the whole turn is one
      transaction at the end (INTEGRATION-SPEC). The checkbox previously read "persisted"
- [x] An honest non-answer is recorded as `VERIFIED` with `no_answer_reason` set, tracked separately
      from `DEGRADED`. UC-2 and UC-5 mean opposite things and must not share a metric
- [x] Unit tests use **invented text only**, never corpus text — substring containment and NFC are
      indifferent to provenance, and pasting WCF 7.2 into a fixture is the ADR-0014 violation the
      policy specifically warns about. The live-database suite borrows real chunks at run time and
      keeps them in memory; nothing it reads is written down
- [x] Latency measured against synthetic load, not the ten acceptance questions — ten hand-run
      queries do not produce a p95. Target ≤ 200 ms, and both measurements are assertions in the
      suite rather than numbers in a report: **p95 0.68 ms** for the engine over eight citations
      against 4,000-character chunks, **p95 1.28 ms** for the same load against the live index

**Decisions Task 8 made that the spec did not anticipate**, recorded in ADR-0024, INTEGRATION-SPEC,
TECHNICAL-SPEC and `services/gateway/AGENTS.md`:

- **Answer-level failures needed a channel of their own** (ADR-0024). `VerificationResult` is shaped
  for the four checks — one citation, four booleans, a detail empty exactly when all four passed —
  and several rules Go enforces are about a *slot* rather than a citation. The omission check forced
  it: every one of the four checks passes and the answer fails, so recording it as a verification
  result means a row whose booleans all say "passed" beside a detail saying the answer did not,
  which `verification_results_detail_iff_failure` rejects. `AnswerFailure`,
  `AnswerRequest.answer_failures` and `trace.answer_failures` are the result. INTEGRATION-SPEC's
  line that the retry "defines nothing new" was written about a narrower case than the one that
  exists, and is corrected
- **The tier floor on an argument is answer-level, not per-citation.** Advisory inside an argument is
  *permitted* — it corroborates — and becomes a failure only when it is the argument's whole
  support. That is a property of the argument, so check 3 stays true of each citation on its own.
  Encoding the floor per citation would mark a legitimate corroborating citation failed and send the
  regeneration hunting for a quote that is fine
- **Degradation always follows exactly two generation attempts**, which Task 3 explicitly left for
  this task and `responses_degraded_is_second_attempt` now holds. An unreachable Catena or database
  is an *error*, not a degraded answer: `DEGRADED` is a successful outcome of the verification
  system, and folding an outage into it makes the one rate ADR-0010 needs kept clean unreadable
- **A fifth uncited surface, closed rather than enumerated.** `state_of_debate` is bound to a
  verbatim quote only when `is_contested` is true, and by nothing when it is false — so an answer
  leaving the flag unset and filling the field carried unbounded prose past every check.
  `STATE_OF_DEBATE_WITHOUT_CONTEST` closes it, which is what keeps INTEGRATION-SPEC's enumeration of
  exactly four true
- **Each of the four checks records what it actually found, and a check that could not run says so.**
  A citation to an out-of-scope corpus is still looked up, so its locator, quote and licence results
  are true rather than borrowed from the tier failure. That costs one indexed lookup on a citation
  already doomed, and it buys a regeneration that is told the right mistake: an out-of-scope corpus
  with a real locator and a real quote is not a fabricated locator, and a result reading "all four
  failed" would send the generator after the wrong one
- **A normalisation contract skew is a diagnosis, never a check.** `Lookup` carries
  `chunks.normalisation_version`, and when a quote misses *and* the chunk was ingested under a
  different contract version, the failure detail says so. It does not fail the citation on the
  version number: the quote may still match across versions, and refusing on the number would
  refuse citations whose text is genuinely there. What it buys is the question a bare "the quote
  does not appear verbatim" leaves open — under a skew that message arrives on every citation to
  that corpus at once and reads exactly like a fabricating model, and the column exists precisely
  so that this is a lookup rather than an investigation
- **Verification is complete rather than short-circuited.** Every citation is checked and every
  broken rule reported, because the regeneration carries them back and telling the generator about
  the first of three buys an attempt that fixes one third of the problem
- **Confidence counts distinct `{corpus_id, locator}` pairs, inside `arguments` only.** "Two or more"
  is otherwise satisfiable by citing one passage twice, which is a corroboration nobody performed;
  and a binding citation inside a `description` rests on no authority, so counting it would raise the
  confidence of an answer that argues nothing
- **The turn is its own package** (`internal/turn`), separate from the engine. The engine judges one
  answer; the turn owns how many times Catena may be asked and what survives. Keeping the count in
  one small file is what makes "at most two calls, and only ever two" reviewable
- **`internal/config`** reads `BEREAN_SERVE_LOCAL_ONLY` and `BEREAN_TOP_K`. The opt-in accepts
  exactly the set Catena's own reader accepts, written out on both sides for the reason the
  normalisation contract is written out on both sides: two standard libraries' idea of "truthy" is
  two different functions, and the one thing that must not vary between them is whether this
  deployment may serve restricted text. A malformed `BEREAN_TOP_K` is an error rather than a silent
  fallback to 20, because `top_k` is recorded in every trace and is one of the two settings most
  likely to move the Phase 2 baseline invisibly
- **`Profile.Name()`**, which Task 6 did not need. `trace.responses.profile` does, and Phase 2 slices
  on it before it slices on anything else

## Task 9: Trace persistence

**Depends on:** Tasks 7, 8

Tables come from Task 3, plus `trace.answer_failures` from Task 8 (ADR-0024); this task is the
persistence path that writes them. Task 8 produces everything they hold — per-citation
`VerificationResult`s, per-slot `AnswerFailure`s, the retrieval trace for each attempt, the overall
result and the derived confidence — and writes nothing.

**Status:** landed. `internal/trace`, migration 000004 from the schema review, and the ordering rule
the review forced on Task 10. Rendering is still Task 10's.

- [x] Trace persisted for every response including degraded ones. A degraded turn is recorded in
      full — the answer object carrying only the derived confidence, *both* attempts' retrieval
      traces, every citation the four checks rejected and every answer-level rule that broke. A
      degradation nobody can inspect afterwards is indistinguishable from a system that never
      answered, and the two mean opposite things
- [x] `trace.answer_failures` written alongside `trace.verification_results`, from the same attempt
      and inside the same transaction. Asserted on both attempts of a degraded turn: the two records
      ADR-0024 split apart are reconstructible only together, and half of them is a failure nobody
      can diagnose
- [x] Schema reviewed against Phase 2's needs before merge — **two columns short**, added in
      migration 000004. Not a revision of the Task 3 migration, which is applied to the database all
      eight corpora are ingested into; the phrase predates 000003. Both new columns are `NOT NULL`
      with no default, which the migration can only satisfy on empty tables — and they were empty,
      because this task is the first writer these tables have ever had
- [x] Gateway role only; Catena has no write access — already asserted at the schema level in
      `tools/db/tests/catena_assertions.sql`, and 000004 adds columns to existing tables while
      granting nothing, so the grant surface is unchanged. Re-run and still passing rather than
      restated in Go
- [x] Reversible (SHARED §10), exercised down and back up against the live database rather than
      read
- [x] Live-database suite, in `make test-gateway-db`. Every readback is on a **second connection**:
      writes are visible to the session that made them whether or not they commit, so a store that
      never commits passes every in-process assertion — which is exactly what shipped once already
      on the Python side. Atomicity is asserted by inducing a failure *after* the response row and
      the first attempt's rows are written, and finding all five tables empty

**Decisions Task 9 made that the spec did not anticipate**, recorded in INTEGRATION-SPEC and
`services/gateway/AGENTS.md` in the same change:

- **The turn is persisted before it is rendered**, which is a rule for Task 10 rather than for this
  package. Verification refusing to ship is a recorded event; a write that failed after the answer
  was printed is not, and a turn that reached a user without being recorded is the one outcome these
  tables exist to prevent. "Nothing renders unverified" has a sibling and this is it
- **A malformed `RetrievalTrace` is an error, not a degraded turn**, and never a row with sentinels
  standing in for what Catena did not send. It is the same class of event as an unreachable Catena:
  the system failed rather than the verification system succeeding. `ErrIncomplete` is typed and
  distinguished from a database outage, because the two want opposite responses — one is a bug in a
  service, the other is a retry. What it buys concretely is a message naming the attempt and the
  field instead of `null value in column "rewritten_query"`, which sends whoever reads it to the
  wrong service
- **`turn.Attempt` grew a `Verify` duration**, measured in `internal/turn` around the engine. The
  engine judges one answer and has no attempt to attribute a cost to; the turn owns the attempt
- **The contract-to-schema enum correspondence is derived, not mapped.** The three Postgres enums
  were written as the proto's values without their prefix, so the derivation *is* the rule, and a
  twelve-entry table restating it is a second place for the two to disagree. What holds them
  together is a unit test that **reads the migrations** and asserts the correspondence in both
  directions — needing no database, so it runs in `make check`. Both directions matter: a proto
  value with no label is an insert that fails having already spent two generations, and a label no
  proto value produces is a `GROUP BY code` silently reporting zero for a rule nobody can raise.
  It earned itself immediately, catching a label-extraction bug where the apostrophe in a comment's
  "I can't source this adequately" paired with the next quote and swallowed a real label
- **`responses.answer` is the rendered answer**, encoded with protojson's proto field names.
  protojson's default would spell it `noAnswerReason`, making that a third spelling of a field the
  proto and every document call `no_answer_reason`, in a column Phase 2 queries through jsonb.
  Unset fields stay omitted, which is what proto3 means by them — emitting defaults would fill the
  record with fields Python never sent, and one of the things this row shows is which fields Python
  populated

**Three gaps the schema review found and deliberately left**, each with the reason, so a later phase
re-opens them on purpose rather than rediscovering them:

- **The gateway's own normalisation contract version is not recorded.** Task 8 already states a skew
  in `verification_results.failure_detail`, and a column would buy a `GROUP BY` over a case that is
  rare and self-announcing — under a skew the message arrives on every citation to that corpus at
  once
- **Token counts and cost (SHARED §6) are held by Langfuse and not by these tables.** Carrying them
  here is a proto change plus a Catena change rather than a revision of this schema, and the
  requirement sits in the observability section the Langfuse instrumentation satisfies. Phase 2
  re-opens it if the eval harness needs them outside the observability stack
- **The answer objects from *failed* attempts are not stored** — only the rendered one, beside the
  verification results and answer failures that say exactly what was wrong with each attempt. What
  this forecloses is studying the prose a rejected generation produced, which is a Phase 2 question
  about generator quality rather than a Phase 1 audit question

---

## Task 10: CLI

**Depends on:** Tasks 6, 8

- [ ] `berean ask --profile pca "question"` returns a verified answer
- [ ] **The turn is persisted before anything is printed** (Task 9). Verification refusing to ship
      is a recorded event; a write that failed after the answer was printed is not
- [ ] The linker-set `version` reaches `trace.responses.gateway_version` — the store refuses to open
      without one, so this is wiring rather than a check
- [ ] `--show-work` prints the trace as a **log, not a narrative**
- [ ] `--top-k` overrides the configured default
- [ ] Citations render with corpus, edition, locator, and tier
- [ ] `contrary` citations render with their label
- [ ] An honest non-answer renders `no_answer_reason` in text visibly distinct from the degraded
      string. A reader must be able to tell "the corpus is silent" from "I could not source this"
- [ ] `catena ingest` documented

---

## Task 11: Phase 1 acceptance

**Depends on:** all

- [ ] Ten questions covering UC-1 to UC-6 run end to end
- [ ] **Zero unverified citations in output** — the phase's hard gate. On its own this gate is
      one-sided: a system that degrades on every question satisfies it perfectly, and so does one
      whose retriever returns nothing. The expectation table below is what makes it mean something
- [ ] **Expected-outcome table**, one row per question, declaring the `OverallResult` it must
      produce and the `corpus_id` + `locator` set its citations must include or exclude. Asserted on
      identifiers and result codes **only, never on expected text** — that is how a golden set
      normally smuggles corpus text into the repository (ADR-0014)
- [ ] UC-1 (assurance) returns `VERIFIED` including a `wcf-1788-american` citation in WCF 18. If it
      returns only proof-texts, that is a real finding: Scripture is ~90% of the index, it is
      `binding` under this profile, so a verse-only answer passes every check while never citing the
      Confession the question asked about. Record the candidate tier mix from the trace and raise an
      ADR rather than quietly adding a quota
- [ ] UC-2 (silent corpus) returns `VERIFIED` with `no_answer_reason` set and every content slot
      empty — **not** `DEGRADED`, and rendered differently
- [ ] UC-3 (civil magistrate) cites `wcf-1788-american` and **no** `wcf-1646-epcew-modernised` citation
- [ ] UC-4 (creation days) flags contested, cites the 2000 report's ruling, carries **no**
      `arguments`, and does not resolve
- [ ] UC-5 (fabricated citation) — the fabrication is prompt-induced, so the assertion is the
      **invariant**: no citation reached output unverified, and any failed check produced exactly one
      regeneration recorded in the trace. Separately, record by hand at least one transcript where a
      real fabrication was caught and degraded. If the model never obliges across all ten questions,
      write that down as a finding about the generator rather than leaving a checkbox blocked
- [ ] UC-6 (descriptive question) answers from `calvin-institutes-1559-beveridge` at `advisory` with
      citations, does not refuse, and states no `position`
- [ ] Run with the `local-only` serving opt-in **set**. Without it the BCO and the 2000 report are
      ingested but refused at check 4, so UC-4 degrades for a configuration reason that looks exactly
      like a verification bug (ADR-0017)
- [ ] Clean clone → `make provision` (models + `catena acquire`) → `docker compose up`
      reproduces all of the above, with acquisition verifying against committed fingerprints
- [ ] Wall-clock provisioning time measured on the reference machine and recorded in the README
      alongside the RAM floor — roughly 35,000 chunks embed on a clean clone
- [ ] Record the first-attempt verification rate separately from the post-retry rate (ADR-0010), and
      the rate at which check 2 failed on near-miss quotes rather than bad locators. The second
      number is the Phase 2 baseline for how much verbatim quoting this generator can do
- [ ] README documents the full path from clone to first answer

---

## Parallelisation

| Can run together | After |
| --- | --- |
| Tasks 3, 4 | Task 1 |
| Tasks 6, 7 | Tasks 2, 5 |
| Tasks 9, 10 | Task 8 |

## Out of scope — do not drift into these

Reranking, BM25, query rewriting, LangGraph, HTTP, SSE, auth, sessions, web UI, conversation
memory, translation display, additional traditions, original languages.

"Web UI" and "HTTP" here mean the product's answer surface: routing, auth, sessions, SSE, and
rendering a verified answer to an end user. They do not reach local developer tooling over
gitignored acquired data, which is what `make browse` is — the same act as `make show-diagnostic`,
widened from one locator to a whole corpus (ADR-0021). It writes in one place only: the first bless
of a corpus, which ADR-0021's amendment moves to the page that shows the diagnostic. The test is
whether the thing touches the answer path: `browse` reaches no model, no proto, no database and
neither service, and binds loopback only.

If a task starts to require one of these, stop and revise the spec instead.
