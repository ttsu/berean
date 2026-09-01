#!/usr/bin/env bash
# Fetch the pinned model weights into ./models/. Idempotent.
#
# SHARED §1: first run may fetch images and weights; steady-state operation must
# require none. This is that first run, and it is a documented step rather than
# something that happens silently on first query.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
lock="$repo_root/tools/provision/models.lock.yaml"

# Minimal reader — the lockfile is flat and this avoids a YAML dependency in a
# script that runs before any environment exists.
pin() { sed -n "s/^  $1: *//p" "$lock" | head -1 | tr -d '"'; }

gen_ref="$(pin reference)"
gen_manifest_sha="$(pin manifest_sha256)"
emb_repo="$(pin repo)"
emb_revision="$(pin revision)"

echo "==> Verifying the pinned generation tag still points where it pointed"
tag="${gen_ref#*:}"
actual="$(curl -fsSL \
    -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    "https://registry.ollama.ai/v2/library/qwen3/manifests/${tag}" \
    | shasum -a 256 | cut -d' ' -f1)"
if [ "$actual" != "$gen_manifest_sha" ]; then
    cat >&2 <<EOF
provision: FAIL — upstream drift on ${gen_ref}

  expected manifest sha256  ${gen_manifest_sha}
  found                     ${actual}

The tag has been republished. Pinning exists so this is visible rather than
silent: an unpinned generator makes the Phase 2 baseline unfalsifiable
(ADR-0018). Re-bless deliberately by updating models.lock.yaml, and say why.
EOF
    exit 1
fi
echo "    ${gen_ref} ✓"

echo "==> Pulling ${gen_ref} into ./models/ollama (~5.2 GB)"
docker compose up -d ollama
docker compose exec -T ollama ollama pull "$gen_ref"

echo "==> Fetching ${emb_repo} at ${emb_revision} into ./models/bge-m3 (~2.3 GB)"
uv run --quiet --no-project --with huggingface_hub python - "$emb_repo" "$emb_revision" \
    "$repo_root/models/bge-m3" <<'PY'
import sys
from huggingface_hub import snapshot_download

repo, revision, dest = sys.argv[1:4]
snapshot_download(
    repo_id=repo,
    revision=revision,          # a commit sha, never a branch — a branch is not a pin
    local_dir=dest,
    allow_patterns=["*.json", "*.model", "*.safetensors", "*.txt", "*.py"],
)
print(f"    {repo}@{revision[:12]} → {dest}")
PY

echo "==> Model provisioning complete"
