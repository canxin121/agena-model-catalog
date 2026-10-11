#!/usr/bin/env bash
# End-to-end catalog refresh:
#   fetch → discover → merge → derive modes → curate → route caps → backfill
#   → validate → verify → report
#
# Mutates models.json in place. A timestamped backup is kept in .cache/ before
# any write, and restored automatically if a stage fails.
#
#   bash scripts/refresh.sh            # full pipeline
#   bash scripts/refresh.sh --no-fetch # reuse an existing .cache snapshot
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p .cache

if [[ "${1:-}" != "--no-fetch" ]]; then
  echo "=== 1/10 fetch upstream snapshot ==="
  bash scripts/fetch_modelsdev.sh
else
  echo "=== 1/10 fetch: skipped (--no-fetch) ==="
fi

BACKUP=$(mktemp ".cache/models.$(date +%Y%m%d-%H%M%S).bak.XXXXXX")
cp models.json "$BACKUP"
echo "backup -> $BACKUP"
restore_on_failure() {
  local status=$?
  if [[ "$status" -ne 0 ]]; then
    cp "$BACKUP" models.json
    echo "refresh failed; restored models.json from $BACKUP" >&2
  fi
}
trap restore_on_failure EXIT

echo "=== 2/10 discover new models from trusted sources ==="
python3 scripts/seed_modelsdev.py

echo "=== 3/10 sync trusted fields and fill legacy gaps ==="
python3 scripts/merge_modelsdev.py

echo "=== 4/10 derive thinking modes from trusted reasoning options ==="
python3 scripts/derive_thinking_modes.py

echo "=== 5/10 apply curated patches ==="
python3 scripts/apply_patches.py

echo "=== 6/10 cap context and output by configured route limits ==="
python3 scripts/apply_route_limits.py

echo "=== 7/10 conservative backfills ==="
python3 scripts/backfill_input.py

echo "=== 8/10 validate full document ==="
python3 scripts/validate.py

echo "=== 9/10 verify thinking modes against the snapshot (advisory) ==="
# Pre-existing patches deliberately differ from gateway-shaped reasoning records
# (for example a documented vendor toggle where models.dev advertises effort
# values), so this audit reports instead of failing the refresh. validate.py
# remains the hard publish gate.
python3 scripts/verify_thinking.py || true

echo "=== 10/10 coverage report ==="
python3 scripts/report.py

trap - EXIT
echo "refresh complete. Review the diff, then: bash scripts/publish.sh"
