#!/usr/bin/env bash
# Snapshot the models.dev catalog into .cache/ for offline merge/verify steps.
# models.dev is the authoritative base for limits, pricing, descriptions,
# knowledge cutoffs, and input/features capabilities (see README).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/.cache"

curl -fsSL https://models.dev/api.json -o "$ROOT/.cache/models.dev.json"
PROVIDERS=$(jq '. | length' "$ROOT/.cache/models.dev.json")
echo "saved models.dev snapshot: $PROVIDERS providers -> .cache/models.dev.json"
