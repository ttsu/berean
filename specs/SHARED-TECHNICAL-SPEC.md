# Shared Technical Specification

Project-wide non-functional requirements. Feature specifications may **tighten** these and may
never relax them without an approved ADR.

MUST / SHOULD / MAY are used in the RFC 2119 sense.

## 1. Portability — the acceptance test

- `docker compose up` MUST give a working system with **no external accounts**. If a change breaks
  this, the change is wrong.
- First run MAY fetch container images and model weights. **Steady-state operation MUST require no
  network egress**: once provisioned, the system runs fully offline, and any code path that reaches
  the public internet to answer a question is a defect. The ESV adapter is the sole exception and is
  deployer-enabled, never default.
- Model weights MUST be fetched by a documented provisioning step, not silently on first query.
- The system MUST NOT depend on any managed service in its default path. No RDS, no EKS, no SQS,
  no Secrets Manager, no proprietary SaaS observability.
- Object storage MUST be accessed through an S3-compatible client, with MinIO as the local
  implementation.
- Deployment MUST be a Helm chart runnable on any Kubernetes, including k3s and kind.
- The generation provider MUST sit behind an interface using the OpenAI-compatible
  chat-completions shape as the internal lingua franca, so Ollama, vLLM, llama.cpp, and hosted
  APIs are interchangeable.
- The translation provider MUST be a pluggable adapter. Offline mode falls back to WEB or NET.

## 2. Licensing

- All bundled models, datasets, and corpora MUST be permissively licensed. **CC-BY-NC is
  disqualifying**, not a tradeoff, and so is **CC-BY-ND** — chunking, embedding, and serving
  excerpts is plausibly a derivative work. Personal non-commercial intent does not rescue a
  restrictively licensed dependency (ADR-0007).
- **No corpus text of any kind MUST appear in the repository**, whatever its licence — not in
  source, fixtures, test data, or the eval golden set (ADR-0014). The repository carries
  acquisition manifests, per-chunk fingerprints, and acquisition scripts. Text is acquired to
  gitignored local storage and is never distributed. The rule is unconditional so that it needs no
  per-corpus licensing judgement and can be enforced mechanically.
- ESV and NIV carry an additional restriction beyond that: they MUST NOT be ingested at all, at any
  point, and are fetched at render time only.
- Every chunk MUST carry `license` and `attribution`. A corpus addition without them is a blocking
  review failure.
- The verification layer MUST refuse to serve any chunk whose license does not permit it, using
  the same mechanism as tier checking.
- Third-party API keys MUST be deployer-supplied. The project MUST NOT ship a key or automate
  around a provider's terms.

## 3. Correctness and verification

- **Nothing renders unverified.** Every citation MUST resolve to real source text or the answer
  degrades to "I can't source this adequately."
- Every citation MUST pass four checks: locator resolves, quote matches source text, tier matches
  the active profile, license permits serving.
- Any claim without a citation MUST fail verification.
- On verification failure the system MUST regenerate once, then degrade. It MUST NOT ship
  unverified content with a warning attached.
- Verification MUST run in the Go gateway. It MUST NOT be delegated to the model layer.
- Any `contrary`-tier citation MUST be labelled as another tradition's position at render time, and
  any `excluded`-tier citation MUST be labelled as repudiated by the active tradition. Neither MAY
  appear in an affirmative claim; both belong in the descriptive slots, where a claim reports what a
  source says rather than resting on its authority.
- An affirmative claim MUST carry at least one `binding` or `governing` citation. Affirmative and
  descriptive claims MUST be separated structurally, by which slot of the answer object they occupy,
  and MUST NOT be told apart by classifying what a claim means (ADR-0016).
- Corpus IDs MUST be edition-specific. A bare work ID is a bug.
- Text MUST be normalised to NFC before storage and before quote comparison.

## 4. Transparency

- **Provenance** (what was retrieved, at what tier, what was filtered and why, which profile
  applied, which checks passed) MUST be captured mechanically by the pipeline and MUST be
  available to the user.
- **Argument** (the theological case with citations) MUST be verifiable against sources.
- **Model introspection** — the model's narrative about its own reasoning — MUST NOT be shipped in
  any form. It is post-hoc rationalisation: plausible, unfalsifiable, and corrosive to the
  product's central claim.
- The "show the work" panel MUST be a log, not a narrative.
- A trace MUST be persisted for every response. Traces are the eval dataset and the audit log.

## 5. Data and boundaries

- One Postgres instance. Two clients with **disjoint write scope**: Python writes corpus tables,
  Go writes session and trace tables. Neither writes the other's.
- One gRPC call from Go into Python per **generation attempt**. A verification failure permits
  exactly one retry call (ADR-0010), so a turn makes at most two. Anything beyond that —
  per-step orchestration, an agent loop driven from Go, multi-hop retrieval across the boundary —
  means the seam is wrong.
- The Go→Python payload MUST be a *resolved filter spec*, never the profile itself.
- The cross-language contract MUST be defined once in protobuf and generated for both sides. It
  MUST NOT be hand-maintained on either side.
- Ingestion MUST be a batch job, never in the request path.
- Chunking MUST follow structural boundaries — verse, article, question/objection/reply. Naive
  fixed-token splitting is prohibited.

## 6. Observability

- Langfuse (self-hosted) for LLM tracing and evals, instrumented from Phase 1. OTel + Phoenix is
  an acceptable substitute. LangSmith is not.
- OpenTelemetry traces for the non-LLM path.
- Token count and cost per request, retrieval latency, and cache hit rate MUST be recorded.
- Trace persistence in Postgres is independent of the observability vendor.

## 7. Evaluation

- Golden sets MUST be tradition-parameterised. A correct Catholic answer on justification is a
  wrong PCA answer; every tradition needs its own.
- Retrieval recall@k MUST be measured **separately** from answer faithfulness.
- Cross-contamination tests are mandatory: assert no Tridentine source appears at `binding` tier
  under a PCA profile, and equivalents for every tradition pair.
- Phase 2 (eval harness and golden set) MUST complete before Phase 3 (hybrid retrieval and
  reranking). This ordering is not negotiable — it is what makes the Phase 3 improvement claim
  falsifiable.
- The embedding model choice MUST be re-evaluated against the golden set before Phase 3.

## 8. Safety and guardrails

- Input classification with a refusal policy for **pastoral-crisis questions**. The system routes
  to human resources and does not counsel. This is a product requirement, not a liability hedge.
- Output grounding checks on every response.
- Lexical claims about Hebrew or Greek MUST cite a lexicon entry. Arguments resting solely on
  etymology MUST be flagged (the word-study fallacy).
- `contested` loci MUST be modelled explicitly. False confidence on genuine intramural
  disagreement is worse than having no profile.
- Corpus availability is uneven across traditions and the UI MUST be upfront about it rather than
  implying parity.

## 9. Performance

Targets, not guarantees, until measured under load in Phase 6.

- Time to first trace event: ≤ 500 ms p95. The SSE feed exists because the answer cannot stream;
  the feed itself must feel immediate.
- Retrieval (embed + search + rerank): ≤ 2 s p95 at Phase 1 corpus size.
- Verification: ≤ 200 ms p95. It is string matching and indexed lookups; if it is slower than
  this, something is wrong.
- Embedding cache and semantic response cache are the biggest cost levers and SHOULD exist before
  any other optimisation.

## 10. Operability

- Migrations MUST be reversible or carry a documented rollback strategy.
- Re-indexing after an embedding model change MUST be a job, not a migration. `embedding_model`
  and `dim` on every chunk are what make this true.
- Secrets via env + SOPS/age, or Vault. Never in the repository.
