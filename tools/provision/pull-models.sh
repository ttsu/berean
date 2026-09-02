#!/usr/bin/env bash
# Fetch the pinned model weights into ./models/. Idempotent.
#
# SHARED §1: first run may fetch images and weights; steady-state operation must
# require none. This is that first run, and it is a documented step rather than
# something that happens silently on first query.
#
# Every fetch here asserts a post-condition. An earlier version of this script
# filtered for `*.safetensors`, which BAAI/bge-m3 does not publish — it fetched
# 42 MB of tokeniser files and printed "complete". A provisioning step that
# reports success while acquiring nothing is the single worst failure mode this
# project has, because it surfaces three tasks later as something else.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
lock="$repo_root/tools/provision/models.lock.yaml"

# `shasum` is the BSD name and `sha256sum` the coreutils one; a minimal Linux
# image reliably has only the second. Resolving it here means a host missing
# both says so, rather than aborting mid-verification in a way that reads as
# upstream drift.
if command -v sha256sum >/dev/null 2>&1; then
    sha256() { sha256sum; }
elif command -v shasum >/dev/null 2>&1; then
    sha256() { shasum -a 256; }
else
    echo "provision: FAIL — neither sha256sum nor shasum is on PATH" >&2
    exit 1
fi

# Create the bind-mount sources before any container can. Docker creates a
# missing bind-mount source as root on Linux, and the fetch below then runs as
# the host user and cannot write into ./models. macOS remaps ownership and
# hides this, so it is a clean-clone Linux failure that never reproduces here.
mkdir -p "$repo_root/models/ollama" "$repo_root/models/bge-m3" "$repo_root/data"

# Minimal reader, avoiding a YAML dependency in a script that runs before any
# environment exists. It must be section-aware: `approx_bytes`, `runtime`,
# `license` and `adr` all appear under both `generation:` and `embedding:`, and
# a reader that takes the first match silently returns the other model's value.
# That is precisely the bug that let this script compare bge-m3's 2.3 GB against
# Qwen3's 5.2 GB floor and fail a download that had actually succeeded.
pin() {  # pin <section> <key>
    awk -v sec="$1" -v key="$2" '
        /^[a-z_]+:/            { in_sec = ($0 ~ "^" sec ":") }
        in_sec && $1 == key":" { sub(/^[^:]*: */, ""); sub(/ *#.*$/, "");
                                 gsub(/"/, ""); print; exit }
    ' "$lock"
}

gen_ref="$(pin generation reference)"
gen_manifest_sha="$(pin generation manifest_sha256)"
emb_repo="$(pin embedding repo)"
emb_revision="$(pin embedding revision)"
emb_bytes="$(pin embedding approx_bytes)"

echo "==> Verifying the pinned generation tag still points where it pointed"
tag="${gen_ref#*:}"
actual="$(curl -fsSL \
    -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    "https://registry.ollama.ai/v2/library/qwen3/manifests/${tag}" \
    | sha256 | cut -d' ' -f1)"
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
docker compose up -d --wait ollama
docker compose exec -T ollama ollama pull "$gen_ref"

# Ollama names a model by its manifest digest, so its own inventory is a second,
# independent confirmation that what landed is what was pinned.
short="${gen_manifest_sha:0:12}"
if ! docker compose exec -T ollama ollama list | tr -d '\r' | grep -q "$short"; then
    echo "provision: FAIL — ${gen_ref} is not in ollama's inventory under ${short}" >&2
    docker compose exec -T ollama ollama list >&2
    exit 1
fi
echo "    present in ollama as ${short} ✓"

echo "==> Fetching ${emb_repo} at ${emb_revision} into ./models/bge-m3 (~2.3 GB)"
uv run --quiet --no-project --with huggingface_hub python - \
    "$emb_repo" "$emb_revision" "$repo_root/models/bge-m3" "$emb_bytes" <<'PY'
import sys
from pathlib import Path
from huggingface_hub import snapshot_download

repo, revision, dest, floor = sys.argv[1:5]

# bge-m3 publishes `pytorch_model.bin`, not safetensors. colbert_linear.pt and
# sparse_linear.pt are the ColBERT and learned-sparse heads — the whole reason
# this model runs in-process rather than behind Ollama (ADR-0006), so a fetch
# without them is a fetch that quietly forecloses Phase 3.
REQUIRED = [
    "pytorch_model.bin",
    "colbert_linear.pt",
    "sparse_linear.pt",
    "config.json",
    "tokenizer.json",
    "sentencepiece.bpe.model",
]

snapshot_download(
    repo_id=repo,
    revision=revision,          # a commit sha, never a branch — a branch is not a pin
    local_dir=dest,
    # The onnx/ tree duplicates the weights in another runtime's format and the
    # images are documentation; together they are ~2.3 GB of nothing we use.
    ignore_patterns=["onnx/*", "imgs/*", "*.jpg"],
)

root = Path(dest)
missing = [f for f in REQUIRED if not (root / f).is_file()]
if missing:
    sys.exit(f"provision: FAIL — {repo} fetched without: {', '.join(missing)}")

got = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
if got < int(floor) * 0.9:
    sys.exit(f"provision: FAIL — {repo} is {got/1e9:.2f} GB, expected ~{int(floor)/1e9:.2f} GB")

print(f"    {repo}@{revision[:12]} → {dest} ({got/1e9:.2f} GB, all heads present)")
PY

echo "==> Model provisioning complete"
