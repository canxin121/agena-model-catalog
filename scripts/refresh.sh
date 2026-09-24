#!/usr/bin/env bash
# End-to-end catalog refresh:
#   fetch → discover → merge → curate → route caps → backfill → validate → report
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
  echo "=== 1/8 fetch upstream snapshot ==="
  bash scripts/fetch_modelsdev.sh
else
  echo "=== 1/8 fetch: skipped (--no-fetch) ==="
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

echo "=== 2/8 discover new models from trusted sources ==="
python3 scripts/seed_modelsdev.py

echo "=== 3/8 sync trusted fields and fill legacy gaps ==="
python3 scripts/merge_modelsdev.py

echo "=== 4/8 apply curated patches ==="
python3 scripts/apply_patches.py

echo "=== 5/8 cap context and output by configured route limits ==="
python3 scripts/apply_route_limits.py

echo "=== 6/8 conservative backfills ==="
python3 scripts/backfill_input.py

echo "=== 7/8 validate full document ==="
python3 scripts/validate.py

echo "=== 8/8 coverage report ==="
python3 scripts/report.py

trap - EXIT
echo "refresh complete. Review the diff, then: bash scripts/publish.sh"
