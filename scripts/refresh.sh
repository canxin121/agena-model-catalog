#!/usr/bin/env bash
# End-to-end catalog refresh:
#   fetch → seed → merge → apply → backfill → validate → report
#
# Mutates models.json in place. A timestamped backup is kept in .cache/ before
# any write; restore from it if a later stage fails validation.
#
#   bash scripts/refresh.sh            # full pipeline
#   bash scripts/refresh.sh --no-fetch # reuse an existing .cache snapshot
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p .cache

if [[ "${1:-}" != "--no-fetch" ]]; then
  echo "=== 1/7 fetch upstream snapshot ==="
  bash scripts/fetch_modelsdev.sh
else
  echo "=== 1/7 fetch: skipped (--no-fetch) ==="
fi

BACKUP=".cache/models.$(date +%Y%m%d-%H%M%S).bak"
cp models.json "$BACKUP"
echo "backup -> $BACKUP"

echo "=== 2/7 seed reviewed new model ids ==="
python3 scripts/seed_modelsdev.py

echo "=== 3/7 merge models.dev base fields (fill missing only) ==="
python3 scripts/merge_modelsdev.py

echo "=== 4/7 apply curated patches ==="
python3 scripts/apply_patches.py

echo "=== 5/7 conservative backfills ==="
python3 scripts/backfill_input.py

echo "=== 6/7 validate full document ==="
python3 scripts/validate.py

echo "=== 7/7 coverage report ==="
python3 scripts/report.py

echo "refresh complete. Review the diff, then: bash scripts/publish.sh"
