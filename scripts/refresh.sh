#!/usr/bin/env bash
# End-to-end catalog refresh:
#   fetch → discover → merge → derive think+speed modes → curate → ensure speed
#   default → route caps → backfill → validate → verify source metadata → report
#   → build route/artifact/provenance sidecars → verify source completeness
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
  echo "=== 1/15 fetch registered upstream snapshots ==="
  bash scripts/fetch_modelsdev.sh
else
  echo "=== 1/15 fetch: skipped (--no-fetch) ==="
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

echo "=== 2/15 discover new models from trusted sources ==="
python3 scripts/seed_modelsdev.py

echo "=== 3/15 resolve trusted fields by field-group priority and fill legacy gaps ==="
python3 scripts/merge_modelsdev.py

echo "=== 4/15 derive thinking modes from trusted reasoning options ==="
python3 scripts/derive_thinking_modes.py

echo "=== 5/15 derive speed modes from trusted experimental.modes ==="
python3 scripts/derive_speed_modes.py

echo "=== 6/15 apply curated patches ==="
python3 scripts/apply_patches.py

echo "=== 7/15 ensure the explicit default entry (also for patched speed modes) ==="
python3 scripts/derive_speed_modes.py --ensure-existing-only

echo "=== 8/15 cap context and output by configured route limits ==="
python3 scripts/apply_route_limits.py

echo "=== 9/15 conservative backfills ==="
python3 scripts/backfill_input.py

echo "=== 10/15 validate full document ==="
python3 scripts/validate.py

echo "=== 11/15 verify thinking modes against the trusted records ==="
# Fails when a patch contradicts the trusted record (an effort value it does not
# publish, or a toggle turned into an effort ladder). Patches for models without
# a trusted record and ladders wider than a gateway-shaped record are reported as
# advisories only.
python3 scripts/verify_thinking.py

echo "=== 12/15 verify verbosity metadata against all selected source observations ==="
python3 scripts/verify_verbosity.py

echo "=== 13/15 coverage report ==="
python3 scripts/report.py

echo "=== 14/15 build source-scoped route, artifact, provenance, and conflict data ==="
python3 scripts/build_source_artifacts.py

echo "=== 15/15 verify source record completeness and raw-field retention ==="
python3 scripts/verify_source_artifacts.py

trap - EXIT
echo "refresh complete. Review the diff, then: bash scripts/publish.sh"
