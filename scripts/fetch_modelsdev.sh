#!/usr/bin/env bash
# Snapshot the models.dev catalog into .cache/ for offline merge/verify steps.
# models.dev is the authoritative base for limits, pricing, descriptions,
# knowledge cutoffs, and input/features capabilities (see README).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/.cache"

SNAPSHOT_TMP=$(mktemp "$ROOT/.cache/models.dev.XXXXXX")
trap 'rm -f "$SNAPSHOT_TMP"' EXIT
curl -fsSL https://models.dev/api.json -o "$SNAPSHOT_TMP"
PROVIDERS=$(python3 - "$SNAPSHOT_TMP" <<'PY'
import json
import sys

with open(sys.argv[1]) as file:
    providers = json.load(file)
if not isinstance(providers, dict) or len(providers) < 100:
    raise SystemExit("models.dev snapshot is incomplete")
print(len(providers))
PY
)
mv "$SNAPSHOT_TMP" "$ROOT/.cache/models.dev.json"
echo "saved models.dev snapshot: $PROVIDERS providers -> .cache/models.dev.json"
