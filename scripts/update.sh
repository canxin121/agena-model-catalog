#!/usr/bin/env bash
# Skeleton for refreshing models.json from upstream aggregators.
# The 2026-08 initial version was generated from the Agena runtime's own
# public-source pipeline (models.dev + OpenAI codex + HuggingFace + NVIDIA)
# with its curation pass, then hand-reviewed. Re-run and review diffs.

set -euo pipefail

cd "$(dirname "$0")/.."

# 1. Fetch upstream raw sources (adjust as needed).
# curl -fsSL https://models.dev/api.json -o /tmp/models.dev.json

# 2. Run the curation/normalization step. With the Agena tree checked out:
#    cargo run -p agena-runtime --example export-catalog -- --out models.json

# 3. Validate the result is well-formed and non-empty.
jq -e '.models | type == "object"' models.json >/dev/null
jq -e '.models | length > 0' models.json >/dev/null

echo "models.json validated: $(jq '.models | length' models.json) models"
