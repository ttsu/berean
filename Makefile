# Berean — development entry points.
#
# Every `make <target>` named anywhere in this repository's Markdown must have a
# rule here. `make guard-make-targets` enforces that: the README's
# clone-to-first-answer path is the project's acceptance test, and a target that
# is renamed or never written breaks it silently, and only for a new reader.

# Containers that write into a bind mount run as the invoking user (the `user:`
# key on catena), so what they acquire is owned by whoever ran make rather than
# by the image's uid. Same reason the buf container below passes --user.
COMPOSE := BEREAN_UID=$(shell id -u) BEREAN_GID=$(shell id -g) docker compose
OFFLINE := $(COMPOSE) -f compose.yaml -f compose.offline.yaml
PYTHON  := python3
UV      := uv

# Codegen and the Go suite run in pinned containers, so neither buf nor a Go
# toolchain is a host prerequisite -- the README lists git, make, curl, python3,
# uv and Docker, and this keeps that list honest. Pinned for the same reason the
# images and the model weights are: "the same commit" has to mean the same
# stack.
BUF_IMAGE := bufbuild/buf:1.72.0
GO_IMAGE  := golang:1.24-alpine

BUF = docker run --rm \
	  --user "$$(id -u):$$(id -g)" --env HOME=/tmp \
	  --volume "$(CURDIR):/workspace" --workdir /workspace \
	  $(BUF_IMAGE)

# The module and build caches live in named volumes, so a second run does not
# re-download the module graph or rebuild the standard library. Nothing here
# writes into the working tree: go.sum is committed, so the build is read-only
# against it.
GO = docker run --rm \
	  --volume "$(CURDIR):/src" --workdir /src \
	  --volume berean-go-mod:/go/pkg/mod \
	  --volume berean-go-build:/root/.cache/go-build \
	  $(GO_IMAGE)

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-z][a-z0-9-]*:.*?## ' $(MAKEFILE_LIST) \
	    | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Provisioning — neither weights nor corpus text ship in this repository
# ---------------------------------------------------------------------------

# Not in `make help` — plumbing, not something anyone runs directly. Docker
# creates a missing bind-mount source as root, so on Linux the first container
# to touch ./models, ./data or ./corpora leaves a tree the host user cannot
# write. Every target that starts a container depends on this. corpora/ holds
# committed content, but git tracks no empty directory and nothing is blessed
# yet, so on a clean clone it is as absent as the other two.
.PHONY: dirs
dirs:
	@mkdir -p models/ollama models/bge-m3 data corpora

.PHONY: provision
provision: provision-models provision-corpus ## Fetch pinned weights and acquire the corpus

.PHONY: provision-models
provision-models: env dirs ## Fetch the pinned Qwen3-8B and BGE-M3 weights into ./models/
	./tools/provision/pull-models.sh

# Every acquisition target depends on `build`, and that is load-bearing rather
# than tidy. The catena image COPYs services/catena/src at build time and mounts
# no source, so a container started against a stale image runs the adapters the
# image was built with. The failure is not a crash: a new corpus reports
# "unknown corpus", and -- worse -- an *edited* adapter silently acquires through
# the old code, which is how a bless records a human verification of text the
# working tree no longer produces. A few seconds of no-op build is the cheaper
# side of that trade.
.PHONY: provision-corpus
provision-corpus: env dirs build ## Acquire every corpus into ./data/ (ADR-0014)
	$(COMPOSE) run --rm catena acquire --all

.PHONY: corpus-verify
corpus-verify: env dirs build ## Re-acquire every corpus and diff against committed fingerprints
	$(COMPOSE) run --rm catena acquire --all --verify-only

# One corpus at a time, and both write into ./data, so they go through $(COMPOSE)
# for the uid. --no-deps because acquisition reads no database and calls no
# model: without it, compose starts Postgres, the migrator and Ollama before
# printing the text a human is standing there waiting to read.
ACQUIRE_ONE = $(COMPOSE) run --rm --no-deps catena acquire --corpus

# Requiring a corpus ID is the point rather than a nicety -- neither of these
# has an `--all` form, because reading one edition diagnostic and blessing seven
# corpora are different acts.
define require_corpus
@test -n "$(CORPUS)" || { \
    echo "usage: make $(1) CORPUS=<corpus-id>"; \
    echo "  e.g. make $(1) CORPUS=wcf-1788-american"; \
    exit 64; }
endef

# The one step in this repository that a human has to run, and the only one that
# writes a manifest. `--bless` aborts when stdin is not a terminal and no flag
# overrides that, so this target is deliberately not reachable from `provision`:
# a batch bless would record verifications nobody made.
.PHONY: bless
bless: env dirs build ## Verify one corpus's edition by hand and write its manifest: make bless CORPUS=<id>
	$(call require_corpus,bless)
	$(ACQUIRE_ONE) $(CORPUS) --bless

# What replaces quoting the diagnostic's text into the manifest (ADR-0021).
# `bless` prints this itself before it prompts, so it is never a prerequisite --
# it is here for everyone who reads the record afterwards and wants to see what
# the verifier saw.
.PHONY: show-diagnostic
show-diagnostic: env dirs build ## Print one corpus's edition diagnostic and its hash: make show-diagnostic CORPUS=<id>
	$(call require_corpus,show-diagnostic)
	$(ACQUIRE_ONE) $(CORPUS) --show-diagnostic

# The same act as `show-diagnostic`, widened from one locator to every corpus on
# disk: acquired text read locally, on demand, rather than committed so it can be
# read (ADR-0021). Reading, plus the one write ADR-0021's amendment allows -- an
# unblessed corpus can be blessed from the page that shows its diagnostic. Not
# the product's answer surface -- see PRODUCT-SPEC's non-goals.
#
# On the host rather than through $(COMPOSE), and that is the decision rather
# than a convenience. `make dev-offline` marks the default network internal, and
# published ports do not survive that, so a containerised viewer would be
# unreachable in exactly the run whose acquisition is most worth inspecting.
# It reads ./data and ./corpora and opens no socket but the loopback one.
#
# `docker compose` reads .env by itself; a host-side target does not. The
# local-only opt-in has to be lifted out of the file here or the gate the README
# documents is unreachable through this target -- it fails closed (ADR-0017), so
# the deployer who did exactly what the README says sees a corpus that refuses to
# render and no reason why. An exported value wins, the way it does for compose.
.PHONY: browse
browse: env dirs ## Read the acquired corpora in a browser (loopback only)
	@CATENA_DATA_DIR=$(CURDIR)/data CATENA_CORPORA_DIR=$(CURDIR)/corpora \
	    BEREAN_SERVE_LOCAL_ONLY="$${BEREAN_SERVE_LOCAL_ONLY:-$$(sed -n 's/^BEREAN_SERVE_LOCAL_ONLY=//p' .env | tail -1)}" \
	    $(UV) run --quiet --project services/catena catena browse $(if $(PORT),--port $(PORT),)

# ---------------------------------------------------------------------------
# The contract -- proto/ is normative, and its output is gitignored
# ---------------------------------------------------------------------------

.PHONY: proto
proto: proto-lint ## Regenerate the Go and Python protobuf stubs from proto/
	@# Generated code is not committed; whether it should be is CI policy rather
	@# than contract design, and is deferred to Phase 2 (ADR-0013). Regenerate
	@# after every change to proto/, and run `make test` afterwards -- the
	@# contract suite skips itself when the stubs are absent.
	$(BUF) generate
	@echo "proto: Go stubs in gen/, Python stubs in services/catena/gen/"

.PHONY: proto-lint
proto-lint: ## Lint the contract without generating anything
	@$(BUF) lint && echo "proto-lint: OK"

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

.PHONY: dev
dev: env dirs ## Bring up the stack (Postgres, Langfuse, Ollama)
	@# Down first so a switch from `dev-offline` recreates the network. Compose
	@# reconnects containers to an existing network rather than rebuilding it,
	@# and a network that changed `internal` since it was created comes back
	@# with a resolver that SERVFAILs every name, including a container's own.
	@# Volumes survive; only `make reset` destroys those.
	$(COMPOSE) down --remove-orphans
	@# `--wait` counts any container that exits as a failure unless a started
	@# service depends on its completion -- which is how minio-init passes and
	@# why the migrator does not: the two services that depend on it are behind
	@# the `services` profile. So it is scaled out of the waited-on `up` and run
	@# on its own, where its exit code is the thing being checked rather than a
	@# surprise. A bare `docker compose up` still applies migrations, because
	@# that path uses no `--wait` at all.
	$(COMPOSE) up -d --wait --scale migrate=0
	$(COMPOSE) run --rm migrate up
	@echo
	@echo "  Postgres  $$($(COMPOSE) port postgres 5432)"
	@echo "  Langfuse  http://$$($(COMPOSE) port langfuse-web 3000)"
	@echo "  Ollama    $$($(COMPOSE) port ollama 11434)"

.PHONY: dev-offline
dev-offline: env dirs ## Bring up the stack with egress blocked (SHARED §1)
	$(COMPOSE) down --remove-orphans
	$(OFFLINE) up -d --wait --scale migrate=0
	$(OFFLINE) run --rm migrate up
	@echo
	@echo "  Ports are not published on an internal network. Run the CLI inside the stack:"
	@echo "    $(OFFLINE) run --rm gateway ask --profile pca \"...\""

.PHONY: down
down: ## Stop the stack, keep the volumes
	$(COMPOSE) down

.PHONY: reset
reset: ## Stop the stack and destroy the volumes, so Postgres re-runs its init scripts
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Follow the stack's logs
	$(COMPOSE) logs -f

.PHONY: env
env: ## Create .env from .env.example if it is missing
	@test -f .env || { cp .env.example .env; echo "created .env from .env.example"; }

# ---------------------------------------------------------------------------
# Database -- all DDL is db/migrations/, applied by the `migrate` service
# ---------------------------------------------------------------------------

# `make dev` already applies these: the migrate one-shot is in the default `up`,
# because a stack whose tables do not exist is not the working system SHARED §1
# requires. This target is for applying a new migration without a full restart.
.PHONY: migrate
migrate: env dirs ## Apply db/migrations/ to a running Postgres
	$(COMPOSE) up -d --wait postgres
	$(COMPOSE) run --rm migrate up

.PHONY: migrate-down
migrate-down: env ## Roll back the most recent migration -- DESTROYS the data in it
	$(COMPOSE) run --rm migrate down 1

.PHONY: migrate-version
migrate-version: env ## Print the applied migration version, and whether it is dirty
	$(COMPOSE) run --rm migrate version

# Not part of `make check`: `check` runs with nothing started, and every
# assertion here is about a live database -- grants, closed enum domains, and
# constraints that only a real INSERT can exercise.
.PHONY: test-schema
test-schema: ## Assert the schema, its constraints and both roles' grants (needs `make dev`)
	@./tools/db/tests/test_schema.sh

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

.PHONY: check
check: guard-corpus guard-make-targets proto-lint test config ## Run every check that needs no image build

.PHONY: guard-corpus
guard-corpus: ## Fail on any tracked file that could carry corpus text (ADR-0014)
	@$(PYTHON) tools/guards/corpus_guard.py --tracked && echo "corpus-guard: OK"

.PHONY: guard-make-targets
guard-make-targets: ## Fail when documentation names a make target with no rule
	@$(PYTHON) tools/guards/make_targets_guard.py && echo "make-targets: OK"

.PHONY: test
test: test-guards test-catena test-gateway ## Run every unit suite

.PHONY: test-guards
test-guards: ## The repository guards. Host python3, no dependencies
	@$(PYTHON) tools/guards/tests/test_corpus_guard.py -q
	@$(PYTHON) tools/guards/tests/test_make_targets_guard.py -q

.PHONY: test-catena
test-catena: ## The Python suite, including its half of the normalisation contract
	@for suite in services/catena/tests/test_*.py; do \
	    $(UV) run --quiet --project services/catena python "$$suite" -q || exit 1; \
	done
	@echo "catena: OK"

.PHONY: test-gateway
test-gateway: ## The Go suite, in a container -- no local Go toolchain needed
	@$(GO) go test ./...

.PHONY: config
config: env ## Validate the compose files
	@# With no profile, compose renders neither service container, so nothing in
	@# them is checked -- including the interpolation catena's `user:` key needs.
	@$(COMPOSE) --profile services config --quiet \
	    && $(OFFLINE) --profile services config --quiet \
	    && echo "compose: OK"

.PHONY: build
build: env ## Build the service images
	$(COMPOSE) --profile services build

.PHONY: hooks
hooks: ## Install the pre-commit hook that runs the corpus guard
	git config core.hooksPath .githooks
	@echo "hooks installed — .githooks/pre-commit runs the corpus guard on every commit"
