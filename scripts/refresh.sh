#!/usr/bin/env bash
# End-to-end catalog refresh:
#   fetch → discover → merge → derive think+speed modes → curate → ensure speed
#   default → route caps → backfill → validate → verify → report
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
  echo "=== 1/12 fetch upstream snapshot ==="
  bash scripts/fetch_modelsdev.sh
else
  echo "=== 1/12 fetch: skipped (--no-fetch) ==="
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

echo "=== 2/12 discover new models from trusted sources ==="
python3 scripts/seed_modelsdev.py

echo "=== 3/12 sync trusted fields and fill legacy gaps ==="
python3 scripts/merge_modelsdev.py

echo "=== 4/12 derive thinking modes from trusted reasoning options ==="
python3 scripts/derive_thinking_modes.py

echo "=== 5/12 derive speed modes from trusted experimental.modes ==="
python3 scripts/derive_speed_modes.py

echo "=== 6/12 apply curated patches ==="
python3 scripts/apply_patches.py

echo "=== 7/12 ensure the explicit default entry (also for patched speed modes) ==="
python3 scripts/derive_speed_modes.py --ensure-existing-only

echo "=== 8/12 cap context and output by configured route limits ==="
python3 scripts/apply_route_limits.py

echo "=== 9/12 conservative backfills ==="
python3 scripts/backfill_input.py

echo "=== 10/12 validate full document ==="
python3 scripts/validate.py

echo "=== 11/12 verify thinking modes against the trusted records ==="
# Fails when a patch contradicts the trusted record (an effort value it does not
# publish, or a toggle turned into an effort ladder). Patches for models without
# a trusted record and ladders wider than a gateway-shaped record are reported as
# advisories only.
python3 scripts/verify_thinking.py

echo "=== 12/12 coverage report ==="
python3 scripts/report.py

trap - EXIT
echo "refresh complete. Review the diff, then: bash scripts/publish.sh"
