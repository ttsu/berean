# Berean — development entry points.
#
# Every `make <target>` named anywhere in this repository's Markdown must have a
# rule here. `make guard-make-targets` enforces that: the README's
# clone-to-first-answer path is the project's acceptance test, and a target that
# is renamed or never written breaks it silently, and only for a new reader.

COMPOSE := docker compose
OFFLINE := $(COMPOSE) -f compose.yaml -f compose.offline.yaml
PYTHON  := python3

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
# to touch ./models or ./data leaves a tree the host user cannot write. Every
# target that starts a container depends on this.
.PHONY: dirs
dirs:
	@mkdir -p models/ollama models/bge-m3 data

.PHONY: provision
provision: provision-models provision-corpus ## Fetch pinned weights and acquire the corpus

.PHONY: provision-models
provision-models: env dirs ## Fetch the pinned Qwen3-8B and BGE-M3 weights into ./models/
	./tools/provision/pull-models.sh

.PHONY: provision-corpus
provision-corpus: env dirs ## Acquire every corpus into ./data/ (ADR-0014)
	$(COMPOSE) run --rm catena acquire --all

.PHONY: corpus-verify
corpus-verify: env dirs ## Re-acquire every corpus and diff against committed fingerprints
	$(COMPOSE) run --rm catena acquire --all --verify-only

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
	$(COMPOSE) up -d --wait
	@echo
	@echo "  Postgres  $$($(COMPOSE) port postgres 5432)"
	@echo "  Langfuse  http://$$($(COMPOSE) port langfuse-web 3000)"
	@echo "  Ollama    $$($(COMPOSE) port ollama 11434)"

.PHONY: dev-offline
dev-offline: env dirs ## Bring up the stack with egress blocked (SHARED §1)
	$(COMPOSE) down --remove-orphans
	$(OFFLINE) up -d --wait
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
# Checks
# ---------------------------------------------------------------------------

.PHONY: check
check: guard-corpus guard-make-targets test config ## Run every check that needs no image build

.PHONY: guard-corpus
guard-corpus: ## Fail on any tracked file that could carry corpus text (ADR-0014)
	@$(PYTHON) tools/guards/corpus_guard.py --tracked && echo "corpus-guard: OK"

.PHONY: guard-make-targets
guard-make-targets: ## Fail when documentation names a make target with no rule
	@$(PYTHON) tools/guards/make_targets_guard.py && echo "make-targets: OK"

.PHONY: test
test: ## Run the guard test suites
	@$(PYTHON) tools/guards/tests/test_corpus_guard.py -q
	@$(PYTHON) tools/guards/tests/test_make_targets_guard.py -q

.PHONY: config
config: env ## Validate the compose files
	@$(COMPOSE) config --quiet && $(OFFLINE) config --quiet && echo "compose: OK"

.PHONY: build
build: env ## Build the service images
	$(COMPOSE) --profile services build

.PHONY: hooks
hooks: ## Install the pre-commit hook that runs the corpus guard
	git config core.hooksPath .githooks
	@echo "hooks installed — .githooks/pre-commit runs the corpus guard on every commit"
